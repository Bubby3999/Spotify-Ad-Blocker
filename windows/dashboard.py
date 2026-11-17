"""Native Tk dashboard. Spotify and COM operations stay off the UI thread."""

import logging
from pathlib import Path
import queue
import os
import threading
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from controller import INTERVALS, REOPEN_MODES
from spotify_ad_blocker import save_settings


class EventLogHandler(logging.Handler):
    def __init__(self, events):
        super().__init__()
        self.events = events
        self.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record):
        try:
            self.events.put_nowait(("log", self.format(record)))
        except queue.Full:
            pass  # The rotating file retains every message if the UI falls behind.


class Dashboard:
    def __init__(self, monitor, backend_factory, settings_path, log_path, enable_tray=False, mockup=False):
        self.monitor = monitor
        self.backend_factory = backend_factory
        self.settings_path = settings_path
        self.enable_tray = enable_tray
        self.mockup = mockup
        self.tray = None
        self.instructions_window = None
        self.events = queue.Queue(maxsize=500)
        self.monitor.report_status = self._status
        self.monitor.report_event = self._event
        self.worker = None
        self.closing = False
        self.root = tk.Tk()
        self.root.title("Spotify Control")
        self.root.geometry("760x700")
        self.root.minsize(600, 620)
        self.root.protocol("WM_DELETE_WINDOW", self.dismiss)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        style = ttk.Style(self.root)
        style.configure("Title.TLabel", font=("Segoe UI", 22, "bold"))
        style.configure("TButton", padding=(12, 8))
        frame = ttk.Frame(self.root, padding=24)
        frame.grid(sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(5, weight=1)
        ttk.Label(frame, text="Spotify Control", style="Title.TLabel").grid(sticky="w")
        mode_text = "Quit Spotify on a confirmed ad, reopen it, then resume playback."
        if monitor.mode == "mute":
            mode_text = "Mute Spotify during confirmed ads, then restore its sound."
        self.description = ttk.Label(frame, text=mode_text, wraplength=640)
        self.description.grid(row=1, sticky="ew", pady=(8, 20))

        options = ttk.Frame(frame)
        options.grid(row=2, sticky="ew", pady=(0, 16))
        self.enabled = tk.BooleanVar(master=self.root, value=monitor.enabled.is_set())
        self.toggle = ttk.Checkbutton(options, text="Ad helper enabled", variable=self.enabled, command=self.toggle_helper)
        self.toggle.grid(row=0, column=0, sticky="w", padx=(0, 24))
        self.daily = tk.BooleanVar(master=self.root, value=monitor.daily_refresh)
        self.daily_toggle = ttk.Checkbutton(options, text="Refresh daily", variable=self.daily, command=self.change_daily)
        self.daily_toggle.grid(row=0, column=1, columnspan=2, sticky="w")
        ttk.Label(options, text="Check every (seconds)").grid(row=1, column=0, sticky="w", pady=(12, 0))
        self.interval = tk.StringVar(master=self.root, value=str(monitor.interval))
        self.interval_picker = ttk.Combobox(options, textvariable=self.interval, values=INTERVALS, state="readonly", width=4)
        self.interval_picker.grid(row=1, column=1, sticky="w", pady=(12, 0))
        self.interval_picker.bind("<<ComboboxSelected>>", self.change_interval)
        ttk.Label(options, text="After an ad").grid(row=2, column=0, sticky="w", pady=(12, 0))
        self.reopen_mode = tk.StringVar(master=self.root, value=REOPEN_MODES[monitor.reopen_mode])
        self.mode_picker = ttk.Combobox(options, textvariable=self.reopen_mode, values=list(REOPEN_MODES.values()), state="readonly", width=28)
        self.mode_picker.grid(row=2, column=1, columnspan=2, sticky="w", pady=(12, 0))
        self.mode_picker.bind("<<ComboboxSelected>>", self.change_mode)
        ttk.Label(options, text="Mode changes apply after the next ad.").grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))

        status_frame = ttk.LabelFrame(frame, text="Playback status", padding=12)
        status_frame.grid(row=3, sticky="ew", pady=(0, 16))
        self.status = tk.StringVar(master=self.root, value="Starting Spotify monitor…")
        self.status_label = ttk.Label(status_frame, textvariable=self.status, wraplength=600)
        self.status_label.pack(fill="x")
        self.refreshed = tk.StringVar(master=self.root, value="Not refreshed yet")
        ttk.Label(status_frame, textvariable=self.refreshed).pack(fill="x", pady=(8, 0))
        controls = ttk.Frame(frame)
        controls.grid(row=4, sticky="w", pady=(0, 20))
        self.buttons = {}
        for column, (text, command) in enumerate((("Play / Pause", "playpause"), ("Refresh", "refresh"))):
            button = ttk.Button(controls, text=text, command=lambda c=command: monitor.request(c))
            button.grid(row=0, column=column, padx=(0, 8))
            self.buttons[command] = button
        self.instructions_button = ttk.Button(controls, text="Instructions", command=self.show_instructions)
        self.instructions_button.grid(row=0, column=2, padx=(0, 8))

        activity = ttk.LabelFrame(frame, text="Activity", padding=8)
        activity.grid(row=5, sticky="nsew")
        activity.columnconfigure(0, weight=1)
        activity.rowconfigure(0, weight=1)
        self.activity = ScrolledText(activity, height=10, wrap="word", state="disabled", font=("Consolas", 10))
        self.activity.grid(sticky="nsew")
        self.footer = ttk.Label(frame, text="Keep this window open to watch for ads. Closing it stops the helper.", wraplength=640)
        self.footer.grid(row=6, sticky="ew", pady=(12, 4))
        self.log_label = ttk.Label(frame, text=f"Log: {log_path}", wraplength=640)
        self.log_label.grid(row=7, sticky="ew")
        self.root.bind("<Configure>", self._resize)
        self.log_handler = EventLogHandler(self.events)
        logging.getLogger("spotify-ad-blocker").addHandler(self.log_handler)
        self.event_timer = self.root.after(100, self.drain_events)

    def _resize(self, event):
        if event.widget is self.root:
            for label in (self.description, self.footer, self.log_label):
                label.configure(wraplength=max(350, event.width - 64))
            self.status_label.configure(wraplength=max(320, event.width - 96))

    def _status(self, message):
        try:
            self.events.put_nowait(("status", message))
        except queue.Full:
            pass

    def _event(self, kind, value):
        try:
            self.events.put_nowait((kind, value))
        except queue.Full:
            pass

    def persist(self):
        try:
            save_settings(self.settings_path, self.monitor.interval, self.monitor.enabled.is_set(),
                          self.monitor.daily_refresh, self.monitor.reopen_mode)
        except OSError:
            logging.getLogger("spotify-ad-blocker").exception("Could not save dashboard settings")

    def toggle_helper(self):
        self.monitor.set_enabled(self.enabled.get())
        self.persist()

    def change_interval(self, _event=None):
        self.monitor.set_interval(int(self.interval.get()))
        self.persist()

    def change_daily(self):
        self.monitor.daily_refresh = self.daily.get()
        self.persist()

    def change_mode(self, _event=None):
        mode = next(key for key, label in REOPEN_MODES.items() if label == self.reopen_mode.get())
        self.monitor.set_reopen_mode(mode)
        self.persist()

    def show(self):
        self.root.deiconify()
        self.monitor.request("refresh")

    def dismiss(self):
        if self.tray is not None:
            self.root.withdraw()
        else:
            self.close()

    def show_instructions(self):
        if self.instructions_window is not None and self.instructions_window.winfo_exists():
            self.instructions_window.deiconify()
            self.instructions_window.lift()
            return
        panel = tk.Toplevel(self.root)
        self.instructions_window = panel
        panel.title("Spotify Control Instructions")
        panel.geometry("700x560")
        panel.minsize(500, 400)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)
        ttk.Button(panel, text="Open file", command=self.open_instructions_file).grid(padx=16, pady=16, sticky="w")
        reader = ScrolledText(panel, wrap="word", font=("Segoe UI", 11), padx=12, pady=12)
        reader.grid(row=1, sticky="nsew", padx=16, pady=(0, 16))
        path = Path(__file__).with_name("Spotify Control Instructions.md")
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            text = f"Instructions could not be loaded: {error}"
        reader.insert("1.0", text)
        reader.configure(state="disabled")

    def open_instructions_file(self):
        if self.mockup:
            logging.getLogger("spotify-ad-blocker").info("MOCKUP: Open file selected; no external application opened")
            return
        try:
            os.startfile(str(Path(__file__).with_name("Spotify Control Instructions.md")))
        except OSError:
            logging.getLogger("spotify-ad-blocker").exception("Could not open the instructions file")

    def drain_events(self):
        self.root.after_cancel(self.event_timer)
        for _ in range(100):
            try:
                kind, message = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "status":
                self.status.set(message)
            elif kind == "refreshed":
                self.refreshed.set(f"Last refresh: {message}")
            elif kind == "session" and self.tray is not None and not self.mockup:
                self.root.deiconify() if message else self.root.withdraw()
            elif kind == "action":
                {"show": self.show, "instructions": self.show_instructions, "quit": self.close}[message]()
                if self.closing:
                    return
            elif kind == "log":
                at_bottom = self.activity.yview()[1] >= 0.99
                self.activity.configure(state="normal")
                self.activity.insert("end", message + "\n")
                lines = int(self.activity.index("end-1c").split(".")[0])
                if lines > 300:
                    self.activity.delete("1.0", f"{lines - 300}.0")
                self.activity.configure(state="disabled")
                if at_bottom:
                    self.activity.see("end")
        if not self.closing:
            self.event_timer = self.root.after(100, self.drain_events)

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.root.after_cancel(self.event_timer)
        self.monitor.shutdown()
        self.status.set("Stopping Spotify monitor…")
        self.toggle.configure(state="disabled")
        self.interval_picker.configure(state="disabled")
        self.daily_toggle.configure(state="disabled")
        self.mode_picker.configure(state="disabled")
        for button in self.buttons.values():
            button.configure(state="disabled")
        self._finish_close()

    def _finish_close(self):
        if self.worker is not None and self.worker.is_alive():
            self.root.after(100, self._finish_close)
        else:
            if self.tray is not None:
                self.tray.stop()
                self.tray = None
            logging.getLogger("spotify-ad-blocker").removeHandler(self.log_handler)
            self.monitor.report_status = lambda message: None
            self.monitor.report_event = lambda kind, value: None
            self.root.destroy()

    def run(self):
        if self.enable_tray and not self.mockup:
            from tray import TrayIcon
            try:
                self.tray = TrayIcon(lambda action: self._event("action", action))
                self.tray.start()
                self.footer.configure(text="Close this window to keep running in the system tray. Choose Quit helper there to stop.")
            except Exception:
                self.tray = None
                logging.getLogger("spotify-ad-blocker").exception("System tray unavailable; closing the dashboard will stop the helper")
        self.worker = threading.Thread(target=self.monitor.run, args=(self.backend_factory,), name="Spotify monitor")
        self.worker.start()
        try:
            self.root.mainloop()
        finally:
            self.monitor.shutdown()
            self.worker.join()
            if not self.closing:
                self.close()
