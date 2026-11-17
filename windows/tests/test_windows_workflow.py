"""Native CI recovery against a disposable window; hardware audio is simulated."""

import ctypes
import ctypes.wintypes as wt
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from controller import SpotifyMonitor, restart_spotify
from spotify_windows import WindowsSpotify


class FixtureSpotify(WindowsSpotify):
    """Use real Windows operations, targeting only a child created by this test."""

    def __init__(self, directory, ignore_close=False):
        super().__init__()
        self.fixture = None
        self.ignore_close = ignore_close
        self.lyrics_requested = False
        self.stderr = (directory / "fixture.log").open("ab")
        self.user32.GetPropW.argtypes = [wt.HWND, wt.LPCWSTR]
        self.user32.GetPropW.restype = wt.HANDLE
        self.start_fixture("Advertisement")

    def start_fixture(self, title):
        args = [sys.executable, str(Path(__file__).with_name("fixtures") / "fake_spotify.py"), "--title", title]
        if self.ignore_close:
            args.append("--ignore-close")
        self.fixture = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=self.stderr)

    def processes(self):
        if self.fixture is None or self.fixture.poll() is not None:
            return []
        try:
            root = self.psutil.Process(self.fixture.pid)
            # Windows venv launchers can run the interpreter in a child process.
            return [root, *root.children(recursive=True)]
        except self.psutil.NoSuchProcess:
            return []

    def sessions(self, _pids):
        return []  # No hosted audio device or Spotify account is required.

    def observe(self):
        current = super().observe()
        current.audio_active = bool(current.hwnd and self.user32.GetPropW(current.hwnd, "MockPlaying"))
        return current

    def launch(self, hidden=False):
        self.start_fixture("Spotify")

    def open_lyrics(self):
        self.lyrics_requested = True  # Actual protocol arguments have a separate adapter test.

    def wait_for_window(self):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            current = self.observe()
            # CreateWindow makes HWND visible before the fixture sets its audio property.
            if current.hwnd and current.state == "ad" and current.audio_active is True:
                return current
            if self.fixture.poll() is not None:
                raise RuntimeError("Native fixture exited before creating its window")
            time.sleep(0.05)
        raise TimeoutError("Native fixture window did not appear")

    def close(self):
        try:
            if self.fixture is not None and self.fixture.poll() is None:
                processes = self.processes()
                for process in reversed(processes):
                    try:
                        process.terminate()
                    except self.psutil.NoSuchProcess:
                        pass
                self.psutil.wait_procs(processes, timeout=5)
                self.fixture.wait(timeout=5)
        finally:
            self.stderr.close()
            super().close()


@unittest.skipUnless(sys.platform == "win32", "Native Windows process/window workflow")
class WindowsWorkflowTests(unittest.TestCase):
    def test_all_reopening_modes_with_real_quit_launch_play_and_hide(self):
        for mode in ("hide", "stay", "lyrics"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                backend = FixtureSpotify(Path(directory))
                try:
                    initial = backend.wait_for_window()
                    first_pid = backend.fixture.pid
                    messages = []
                    self.assertTrue(restart_spotify(backend, initial, threading.Event(), messages.append,
                                                    timeout=15, reopen_mode=mode), messages)
                    current = backend.observe()
                    self.assertNotEqual(backend.fixture.pid, first_pid)
                    self.assertEqual(current.state, "song")
                    self.assertTrue(current.audio_active)
                    self.assertEqual(bool(backend.user32.IsWindowVisible(current.hwnd)), mode != "hide")
                    self.assertEqual(backend.lyrics_requested, mode == "lyrics")
                finally:
                    backend.close()

    def test_two_ad_observations_trigger_one_native_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = FixtureSpotify(Path(directory))
            try:
                backend.wait_for_window()
                first_pid = backend.fixture.pid
                monitor = SpotifyMonitor()
                monitor.poll(backend)
                self.assertEqual(backend.fixture.pid, first_pid)
                monitor.poll(backend)
                self.assertNotEqual(backend.fixture.pid, first_pid)
                self.assertEqual(monitor.restarts.attempts, 1)
                self.assertIn("playback confirmed", monitor.last_status)
            finally:
                backend.close()

    def test_unresponsive_close_falls_back_to_terminating_only_the_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = FixtureSpotify(Path(directory), ignore_close=True)
            try:
                initial = backend.wait_for_window()
                self.assertTrue(backend.quit(initial))
                self.assertIsNotNone(backend.fixture.poll())
            finally:
                backend.close()
