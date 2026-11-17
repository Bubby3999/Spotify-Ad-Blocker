"""Portable monitor and restart lifecycle; Windows I/O lives in spotify_windows."""

from dataclasses import dataclass, field
import logging
import queue
import threading
import time

from detector import AD, SONG, UNKNOWN, MuteController, RestartController, classify

log = logging.getLogger("spotify-ad-blocker")
INTERVALS = (1, 2, 5, 10)
REOPEN_MODES = {
    "hide": "Open + Hide (default)",
    "stay": "Open + Stay",
    "lyrics": "Open + Stay + Lyrics",
}


@dataclass
class Observation:
    processes: list = field(default_factory=list)
    hwnd: int | None = None
    title: str | None = None
    audio_active: bool | None = False
    sessions: list = field(default_factory=list)

    @property
    def state(self):
        return classify(self.title, self.audio_active)


def restart_spotify(backend, observation, stop, report, timeout=30.0, reopen_mode="hide"):
    """Never relaunch until shutdown completes, or call a window alone success."""
    if stop.is_set():
        return False
    if reopen_mode not in REOPEN_MODES:
        raise ValueError("Invalid reopening mode")
    if not observation.processes:
        report("Spotify is closed; nothing to restart")
        return False
    report("Closing Spotify…")
    if not backend.quit(observation):
        report("Restart failed: Spotify did not fully quit")
        return False
    if stop.is_set():
        return False
    report("Opening Spotify…")
    backend.launch(hidden=reopen_mode == "hide")
    deadline = time.monotonic() + timeout
    next_play = time.monotonic()
    confirmed = 0
    window_seen = False
    while not stop.is_set() and time.monotonic() < deadline:
        current = backend.observe()
        if current.hwnd:
            if not window_seen:
                report("Spotify window reopened; checking playback…")
                window_seen = True
            hidden = reopen_mode != "hide" or backend.hide(current.hwnd)
            if current.state == SONG and current.audio_active is True:
                confirmed += 1
                if confirmed >= 2:
                    if not hidden:
                        report("Song playback confirmed, but Spotify could not be hidden")
                        return False
                    if reopen_mode == "lyrics":
                        try:
                            backend.open_lyrics()
                        except Exception:
                            log.exception("Playback resumed, but the lyrics request failed")
                            report("Song playback confirmed; lyrics request failed")
                            return True
                        log.info("Lyrics view requested; song availability and Spotify version determine whether it opens")
                    report("Restart complete: song playback confirmed")
                    return True
            else:
                confirmed = 0
                if time.monotonic() >= next_play:
                    # Direct PLAY is safe to retry; a Play/Pause toggle is not.
                    backend.play(current.hwnd)
                    next_play = time.monotonic() + 3
        else:
            confirmed = 0
        stop.wait(0.5)
    if not stop.is_set():
        detail = "window reopened, but song playback was not confirmed" if window_seen else "no Spotify window appeared"
        report(f"Restart failed: {detail} within {timeout:g}s")
    return False


class SpotifyMonitor:
    def __init__(self, interval=2, mode="restart", report=None, reopen_mode="hide", daily_refresh=True):
        if interval not in INTERVALS:
            raise ValueError("Check interval must be 1, 2, 5 or 10 seconds")
        if mode not in ("restart", "mute"):
            raise ValueError("Mode must be restart or mute")
        if reopen_mode not in REOPEN_MODES:
            raise ValueError("Invalid reopening mode")
        self.interval = interval
        self.mode = mode
        self.reopen_mode = reopen_mode
        self.daily_refresh = daily_refresh
        self.report_event = lambda kind, value: None
        self.session_active = False
        self.last_refresh = None
        self.report_status = report or (lambda message: None)
        self.stop = threading.Event()
        self.enabled = threading.Event()
        self.enabled.set()
        self.wake = threading.Event()
        self.commands = queue.Queue(maxsize=10)
        self.restarts = RestartController()
        self.muting = MuteController()
        self.last_status = None
        self.failure = None

    def report(self, message):
        if message != self.last_status:
            self.last_status = message
            log.info(message)
            self.report_status(message)

    def request(self, command):
        if command not in ("play", "pause", "playpause", "refresh"):
            raise ValueError("Unknown playback command")
        try:
            self.commands.put_nowait(command)
        except queue.Full:
            log.warning("Please wait for the current playback command")
        self.wake.set()

    def set_enabled(self, enabled):
        self.enabled.set() if enabled else self.enabled.clear()
        self.wake.set()

    def set_interval(self, interval):
        if interval not in INTERVALS:
            raise ValueError("Invalid check interval")
        self.interval = interval
        self.wake.set()

    def set_reopen_mode(self, mode):
        if mode not in REOPEN_MODES:
            raise ValueError("Invalid reopening mode")
        self.reopen_mode = mode

    def refresh(self, reason):
        self.last_refresh = time.monotonic()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log.info("Dashboard refreshed (%s)", reason)
        self.report_event("refreshed", stamp)

    def shutdown(self):
        self.stop.set()
        self.wake.set()

    def poll(self, backend):
        observation = backend.observe()
        state = observation.state
        active = bool(observation.processes)
        if active != self.session_active:
            self.session_active = active
            self.report_event("session", active)
            if active:
                self.refresh("Spotify opened")
            else:
                self.last_refresh = None
        if active and self.daily_refresh and self.last_refresh is not None and time.monotonic() - self.last_refresh >= 86400:
            self.refresh("daily")
        while not self.commands.empty():
            command = self.commands.get_nowait()
            if command == "refresh":
                self.refresh("manual")
            else:
                if observation.hwnd:
                    getattr(backend, command)(observation.hwnd)
                else:
                    self.report("Spotify is closed; open it to use playback controls")
        if not self.enabled.is_set():
            self.restarts.update(UNKNOWN, time.monotonic())
            self.muting = MuteController()
            backend.restore_mute()
            self.report("Ad helper off")
            return
        if not observation.processes:
            self.restarts.update(UNKNOWN, time.monotonic())
            self.muting = MuteController()
            backend.restore_mute()
            self.report("Waiting for Spotify — open Spotify to begin")
            return
        if self.mode == "restart":
            # A paused ad must not cause the helper to restart and resume playback.
            active_state = state if observation.audio_active is True else UNKNOWN
            if self.restarts.update(active_state, time.monotonic()):
                log.info("Confirmed ad; restart attempt %s/%s", self.restarts.attempts, self.restarts.max_attempts)
                restart_spotify(backend, observation, self.stop, self.report, reopen_mode=self.reopen_mode)
                return
            if state == AD and self.restarts.attempts >= self.restarts.max_attempts:
                self.report("Restart limit reached; waiting for a song")
                return
            if state == AD and observation.audio_active is not True:
                self.report("Advertisement title detected; waiting for Spotify audio")
                return
        else:
            action = self.muting.update(state)
            if self.muting.muted:
                backend.mute(observation.sessions)
            if action == "unmute":
                backend.restore_mute()
        labels = {AD: "Advertisement detected", SONG: "Track", UNKNOWN: "Unrecognized playback"}
        label = labels.get(state, "Spotify idle or paused")
        self.report(f"{label}: {observation.title or 'waiting for Spotify window'}")

    def run(self, backend_factory):
        backend = None
        try:
            backend = backend_factory()
            while not self.stop.is_set():
                self.wake.clear()
                try:
                    self.poll(backend)
                except Exception:
                    # COM endpoints and Spotify processes can disappear mid-poll.
                    self.restarts.update(UNKNOWN, time.monotonic())
                    self.muting.update(UNKNOWN)
                    log.exception("Spotify check failed; will retry")
                    self.report("Spotify check failed — see the activity log; retrying")
                self.wake.wait(self.interval)
        except Exception as error:
            self.failure = error
            log.exception("Could not start Spotify monitoring")
            self.report("Could not start monitoring — see the activity log")
        finally:
            if backend is not None:
                try:
                    backend.restore_mute()
                except Exception as error:
                    self.failure = error
                    log.exception("Could not restore Spotify's audio state")
                finally:
                    try:
                        backend.close()
                    except Exception as error:
                        self.failure = error
                        log.exception("Could not close Windows audio resources")
