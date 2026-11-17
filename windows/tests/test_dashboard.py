import logging
import gc
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import tkinter as tk
    from dashboard import Dashboard
except ImportError as error:
    raise unittest.SkipTest(f"Tk is unavailable: {error}")

from controller import Observation, SpotifyMonitor
from spotify_ad_blocker import load_settings


class DashboardTests(unittest.TestCase):
    def setUp(self):
        gc.collect()  # Dispose of earlier Tcl interpreters on the UI thread.
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.monitor = SpotifyMonitor()
        self.backend = Mock()
        self.backend.observe.return_value = Observation()
        path = Path(self.directory.name)
        try:
            self.dashboard = Dashboard(self.monitor, lambda: self.backend, path / "settings.json", path / "activity.log")
        except tk.TclError as error:
            self.skipTest(f"No graphical display: {error}")
        self.dashboard.root.update()
        self.addCleanup(self.cleanup_dashboard)

    def cleanup_dashboard(self):
        self.dashboard.close()
        deadline = time.monotonic() + 2
        while self.dashboard.worker is not None and self.dashboard.worker.is_alive() and time.monotonic() < deadline:
            self.dashboard.root.update()
            time.sleep(0.01)
        try:
            self.dashboard.root.update()
        except tk.TclError:
            pass
        self.dashboard.root.report_callback_exception = lambda *args: None
        self.dashboard = None
        self.monitor = None
        gc.collect()

    def test_dashboard_controls_and_settings_use_real_callbacks(self):
        self.dashboard.toggle.invoke()
        self.assertFalse(self.monitor.enabled.is_set())
        self.dashboard.interval.set("5")
        self.dashboard.interval_picker.event_generate("<<ComboboxSelected>>")
        self.dashboard.root.update()
        self.assertEqual(self.monitor.interval, 5)
        self.assertEqual(load_settings(self.dashboard.settings_path), {"interval": 5, "enabled": False, "daily_refresh": True, "reopen_mode": "hide"})
        self.backend.observe.return_value = Observation([Mock()], 123, "Artist - Track", True)
        self.dashboard.buttons["playpause"].invoke()
        self.dashboard.buttons["refresh"].invoke()
        self.monitor.poll(self.backend)
        self.backend.playpause.assert_called_once_with(123)

    def test_mockup_uses_sample_controls_and_isolated_settings(self):
        from mockup import create_dashboard
        self.dashboard.close()
        directory = Path(self.directory.name)
        self.dashboard = create_dashboard(directory)
        self.monitor = self.dashboard.monitor
        backend = self.dashboard.backend_factory()
        self.dashboard.buttons["playpause"].invoke()
        self.monitor.poll(backend)
        self.assertFalse(backend.playing)
        self.dashboard.toggle.invoke()
        self.dashboard.interval.set("5")
        self.dashboard.change_interval()
        self.dashboard.drain_events()
        self.assertEqual(load_settings(directory / "settings.json"), {"interval": 5, "enabled": False, "daily_refresh": True, "reopen_mode": "hide"})
        self.assertIn("Mockup", self.dashboard.root.title())
        self.assertIn("not connected", self.dashboard.description.cget("text"))
        self.assertEqual(self.dashboard.settings_path.parent, directory)

    def test_reopen_mode_and_daily_refresh_callbacks_persist(self):
        from controller import REOPEN_MODES
        self.dashboard.reopen_mode.set(REOPEN_MODES["lyrics"])
        self.dashboard.change_mode()
        self.dashboard.daily_toggle.invoke()
        saved = load_settings(self.dashboard.settings_path)
        self.assertEqual(saved["reopen_mode"], "lyrics")
        self.assertFalse(saved["daily_refresh"])
        self.assertEqual(self.monitor.reopen_mode, "lyrics")

    def test_instructions_can_be_read_in_the_dashboard(self):
        self.dashboard.show_instructions()
        self.dashboard.root.update()
        self.assertTrue(self.dashboard.instructions_window.winfo_exists())
        self.assertIn("Instructions", self.dashboard.instructions_window.title())

    def test_dismissing_to_tray_keeps_monitor_alive(self):
        self.dashboard.tray = Mock()
        self.dashboard.dismiss()
        self.dashboard.root.update()
        self.assertEqual(self.dashboard.root.state(), "withdrawn")
        self.assertFalse(self.monitor.stop.is_set())
        self.dashboard.show()
        self.dashboard.root.update()
        self.assertNotEqual(self.dashboard.root.state(), "withdrawn")

    def test_worker_messages_are_rendered_on_ui_thread(self):
        record = logging.LogRecord("spotify-ad-blocker", logging.INFO, "", 0, "Restart complete", (), None)
        def send_messages():
            self.dashboard._status("Song playback confirmed")
            self.dashboard.log_handler.emit(record)
        thread = threading.Thread(target=send_messages)
        thread.start()
        thread.join(2)
        self.dashboard.drain_events()
        self.assertEqual(self.dashboard.status.get(), "Song playback confirmed")
        self.assertIn("Restart complete", self.dashboard.activity.get("1.0", "end"))

    def test_activity_view_stays_bounded(self):
        for number in range(400):
            self.dashboard.events.put_nowait(("log", f"Event {number}"))
        for _ in range(4):
            self.dashboard.drain_events()
        self.assertEqual(len(self.dashboard.root.tk.call("after", "info")), 1)
        text = self.dashboard.activity.get("1.0", "end")
        self.assertIn("Event 399", text)
        self.assertNotIn("Event 0\n", text)
        self.assertLessEqual(len(text.splitlines()), 302)

    def test_minimum_window_size_does_not_clip_controls(self):
        root = self.dashboard.root
        root.geometry("560x500")
        root.update()
        for widget in (self.dashboard.toggle, self.dashboard.interval_picker, self.dashboard.footer,
                       self.dashboard.log_label, *self.dashboard.buttons.values()):
            with self.subTest(widget=widget):
                right = widget.winfo_rootx() - root.winfo_rootx() + widget.winfo_width()
                bottom = widget.winfo_rooty() - root.winfo_rooty() + widget.winfo_height()
                self.assertLessEqual(right, root.winfo_width())
                self.assertLessEqual(bottom, root.winfo_height())
        self.assertGreater(self.dashboard.activity.winfo_height(), 40)

    def test_real_event_loop_remains_responsive_and_stops_worker(self):
        callback_errors = []
        statuses = []
        def callback_error(kind, value, traceback):
            callback_errors.append(value)
            self.dashboard.close()
        self.dashboard.root.report_callback_exception = callback_error
        def check_status():
            statuses.append(self.dashboard.status.get())
            self.dashboard.toggle.invoke()
            self.dashboard.buttons["refresh"].invoke()
            self.dashboard.root.after(150, self.dashboard.close)
        self.dashboard.root.after(250, check_status)
        self.dashboard.root.after(5000, self.dashboard.close)
        self.dashboard.run()
        self.assertFalse(callback_errors, callback_errors)
        self.assertTrue(any("Waiting for Spotify" in message for message in statuses), statuses)
        self.assertFalse(self.dashboard.worker.is_alive())
        self.backend.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
