import os
import sys
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from controller import Observation, SpotifyMonitor, restart_spotify


def observation(title="Advertisement", audible=True, hwnd=42):
    return Observation([Mock(pid=123)], hwnd, title, audible, [Mock()])


class Clock:
    """Advance timeout tests without real sleeping or wall-clock dependence."""

    def __init__(self):
        self.now = 0.0
        self.stopped = False

    def is_set(self):
        return self.stopped

    def wait(self, seconds):
        self.now += seconds


class RestartTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.time_patch = patch("controller.time.monotonic", side_effect=lambda: self.clock.now)
        self.time_patch.start()
        self.addCleanup(self.time_patch.stop)
        self.backend = Mock()
        self.backend.quit.return_value = True
        self.messages = []

    def restart(self, initial=None, timeout=5, reopen_mode="hide"):
        return restart_spotify(self.backend, initial or observation(), self.clock, self.messages.append, timeout, reopen_mode)

    def test_quit_before_launch_then_resume_and_verify_two_audio_readings(self):
        self.backend.observe.side_effect = [
            Observation(), observation("Spotify", False), observation("Artist - Song", False),
            observation("Artist - Song"), observation("Artist - Song"),
        ]
        self.assertTrue(self.restart())
        self.assertEqual([call[0] for call in self.backend.method_calls[:2]], ["quit", "launch"])
        self.backend.launch.assert_called_once_with(hidden=True)
        self.backend.play.assert_called_once_with(42)
        self.backend.hide.assert_called_with(42)
        self.assertIn("song playback confirmed", self.messages[-1])

    def test_does_not_toggle_if_spotify_already_autoplays(self):
        self.backend.observe.return_value = observation("Artist - Song")
        self.assertTrue(self.restart())
        self.backend.play.assert_not_called()

    def test_refuses_launch_if_shutdown_fails(self):
        self.backend.quit.return_value = False
        self.assertFalse(self.restart())
        self.backend.launch.assert_not_called()

    def test_does_not_open_spotify_when_already_closed(self):
        self.assertFalse(self.restart(Observation()))
        self.backend.quit.assert_not_called()
        self.backend.launch.assert_not_called()

    def test_missing_window_times_out(self):
        self.backend.observe.return_value = Observation()
        self.assertFalse(self.restart())
        self.assertIn("no Spotify window", self.messages[-1])

    def test_window_without_audio_is_not_success(self):
        for audible in (False, None):
            with self.subTest(audible=audible):
                self.clock.now = 0
                self.backend.observe.return_value = observation("Artist - Song", audible)
                self.assertFalse(self.restart())
                self.assertIn("playback was not confirmed", self.messages[-1])

    def test_playing_ad_is_not_success(self):
        self.backend.observe.return_value = observation()
        self.assertFalse(self.restart())

    def test_disappearing_window_resets_playback_confirmation(self):
        self.backend.observe.side_effect = [observation("Artist - Song"), Observation(), observation("Artist - Song"),
                                            observation("Artist - Song")]
        self.assertTrue(self.restart())
        self.assertEqual(self.backend.observe.call_count, 4)

    def test_shutdown_cancels_waiting_for_window(self):
        self.backend.observe.side_effect = lambda: setattr(self.clock, "stopped", True) or Observation()
        self.assertFalse(self.restart())
        self.assertEqual(self.backend.observe.call_count, 1)

    def test_shutdown_before_restart_leaves_spotify_alone(self):
        self.clock.stopped = True
        self.assertFalse(self.restart())
        self.backend.quit.assert_not_called()

    def test_shutdown_during_quit_prevents_relaunch(self):
        self.backend.quit.side_effect = lambda _: setattr(self.clock, "stopped", True) or True
        self.assertFalse(self.restart())
        self.backend.launch.assert_not_called()

    def test_launch_error_is_reported_to_monitor(self):
        self.backend.launch.side_effect = OSError("protocol not registered")
        with self.assertRaisesRegex(OSError, "protocol"):
            self.restart()

    def test_stay_mode_does_not_hide(self):
        self.backend.observe.return_value = observation("Artist - Song")
        self.assertTrue(self.restart(reopen_mode="stay"))
        self.backend.launch.assert_called_once_with(hidden=False)
        self.backend.hide.assert_not_called()

    def test_lyrics_is_requested_only_after_song_playback_is_confirmed(self):
        self.backend.observe.return_value = observation("Artist - Song")
        self.assertTrue(self.restart(reopen_mode="lyrics"))
        self.backend.open_lyrics.assert_called_once()
        self.backend.hide.assert_not_called()

    def test_failed_lyrics_request_does_not_count_as_failed_playback(self):
        self.backend.observe.return_value = observation("Artist - Song")
        self.backend.open_lyrics.side_effect = OSError("route unavailable")
        with self.assertLogs("spotify-ad-blocker", level="ERROR"):
            self.assertTrue(self.restart(reopen_mode="lyrics"))
        self.assertIn("lyrics request failed", self.messages[-1])

    def test_hide_failure_is_reported_separately_from_playback(self):
        self.backend.observe.return_value = observation("Artist - Song")
        self.backend.hide.return_value = False
        self.assertFalse(self.restart())
        self.assertIn("could not be hidden", self.messages[-1])

    def test_failed_playback_does_not_request_lyrics(self):
        self.backend.observe.return_value = observation()
        self.assertFalse(self.restart(reopen_mode="lyrics"))
        self.backend.open_lyrics.assert_not_called()


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.monitor = SpotifyMonitor()
        self.backend = Mock()
        self.backend.observe.return_value = observation()

    def test_open_hide_and_daily_refresh_are_defaults(self):
        self.assertEqual(self.monitor.reopen_mode, "hide")
        self.assertTrue(self.monitor.daily_refresh)

    def test_daily_refresh_runs_only_while_spotify_is_open(self):
        self.backend.observe.return_value = observation("Artist - Song")
        with patch("controller.time.monotonic", return_value=0):
            self.monitor.poll(self.backend)
        self.assertEqual(self.monitor.last_refresh, 0)
        with patch("controller.time.monotonic", return_value=86401):
            self.monitor.poll(self.backend)
        self.assertEqual(self.monitor.last_refresh, 86401)
        self.backend.observe.return_value = Observation()
        self.monitor.poll(self.backend)
        self.assertIsNone(self.monitor.last_refresh)

    def test_daily_refresh_can_be_disabled_and_manual_refresh_still_works(self):
        self.monitor.daily_refresh = False
        self.backend.observe.return_value = observation("Artist - Song")
        with patch("controller.time.monotonic", return_value=0):
            self.monitor.poll(self.backend)
        with patch("controller.time.monotonic", return_value=90000):
            self.monitor.poll(self.backend)
            self.assertEqual(self.monitor.last_refresh, 0)
            self.monitor.request("refresh")
            self.monitor.poll(self.backend)
        self.assertEqual(self.monitor.last_refresh, 90000)

    def test_chosen_mode_is_used_for_next_recovery(self):
        self.monitor.set_reopen_mode("lyrics")
        with patch("controller.restart_spotify") as restart:
            self.monitor.poll(self.backend)
            self.monitor.poll(self.backend)
        self.assertEqual(restart.call_args.kwargs["reopen_mode"], "lyrics")

    def test_defaults_to_restart_after_two_ads(self):
        with patch("controller.restart_spotify") as restart:
            self.monitor.poll(self.backend)
            restart.assert_not_called()
            self.monitor.poll(self.backend)
            restart.assert_called_once()
        self.backend.mute.assert_not_called()

    def test_unknown_title_never_restarts(self):
        self.backend.observe.return_value = observation("Spotify")
        with patch("controller.restart_spotify") as restart:
            for _ in range(10):
                self.monitor.poll(self.backend)
            restart.assert_not_called()

    def test_disabled_helper_restores_mute_and_does_not_restart(self):
        self.monitor.set_enabled(False)
        with patch("controller.restart_spotify") as restart:
            self.monitor.poll(self.backend)
            self.monitor.poll(self.backend)
            restart.assert_not_called()
        self.backend.restore_mute.assert_called()
        self.assertEqual(self.monitor.last_status, "Ad helper off")

    def test_absent_spotify_breaks_ad_confirmation(self):
        with patch("controller.restart_spotify") as restart:
            self.monitor.poll(self.backend)
            self.backend.observe.return_value = Observation()
            self.monitor.poll(self.backend)
            self.backend.observe.return_value = observation()
            self.monitor.poll(self.backend)
            restart.assert_not_called()

    def test_paused_song_cannot_reset_failed_ad_retry_budget(self):
        self.monitor.restarts.attempts = 2
        self.backend.observe.return_value = observation("Artist - Song", False)
        self.monitor.poll(self.backend)
        self.monitor.poll(self.backend)
        self.assertEqual(self.monitor.restarts.attempts, 2)

    def test_paused_or_unverifiable_ad_does_not_force_playback_to_resume(self):
        for audible in (False, None):
            with self.subTest(audible=audible), patch("controller.restart_spotify") as restart:
                self.backend.observe.return_value = observation(audible=audible)
                self.monitor.poll(self.backend)
                self.monitor.poll(self.backend)
                restart.assert_not_called()

    def test_controls_work_with_automatic_helper_disabled(self):
        self.monitor.set_enabled(False)
        self.monitor.request("play")
        self.monitor.request("pause")
        self.monitor.poll(self.backend)
        self.backend.play.assert_called_once_with(42)
        self.backend.pause.assert_called_once_with(42)

    def test_refresh_does_not_launch_closed_spotify(self):
        self.backend.observe.return_value = Observation()
        self.monitor.request("refresh")
        self.monitor.poll(self.backend)
        self.backend.launch.assert_not_called()

    def test_mute_mode_kept_as_explicit_option(self):
        self.monitor = SpotifyMonitor(mode="mute")
        self.monitor.poll(self.backend)
        self.backend.mute.assert_not_called()
        self.monitor.poll(self.backend)
        self.backend.mute.assert_called_once()
        self.backend.observe.return_value = observation("Artist - Song")
        self.monitor.poll(self.backend)
        self.backend.restore_mute.assert_called_once()

    def test_disabling_mute_mode_clears_confirmation(self):
        self.monitor = SpotifyMonitor(mode="mute")
        self.monitor.poll(self.backend)
        self.monitor.poll(self.backend)
        self.monitor.set_enabled(False)
        self.monitor.poll(self.backend)
        self.monitor.set_enabled(True)
        self.backend.mute.reset_mock()
        self.monitor.poll(self.backend)
        self.backend.mute.assert_not_called()

    def test_worker_recovers_after_transient_poll_error_and_cleans_up(self):
        self.backend.observe.side_effect = [OSError("device disconnected"), Observation()]
        def status(message):
            if message.startswith("Waiting"):
                self.monitor.shutdown()
            else:
                self.monitor.wake.set()
        self.monitor.report_status = status
        with self.assertLogs("spotify-ad-blocker", level="INFO"):
            self.monitor.run(lambda: self.backend)
        self.assertEqual(self.backend.observe.call_count, 2)
        self.backend.close.assert_called_once()

    def test_backend_initialization_failure_is_visible(self):
        with self.assertLogs("spotify-ad-blocker", level="ERROR"):
            self.monitor.run(Mock(side_effect=ImportError("missing dependency")))
        self.assertIsInstance(self.monitor.failure, ImportError)
        self.assertIn("Could not start", self.monitor.last_status)

    def test_invalid_controls_and_intervals_are_rejected(self):
        with self.assertRaises(ValueError):
            self.monitor.set_interval(0)
        with self.assertRaises(ValueError):
            self.monitor.request("quit everything")
        with self.assertRaises(ValueError):
            SpotifyMonitor(mode="invalid")

    def test_shutdown_wakes_sleeping_worker(self):
        observed = threading.Event()
        self.monitor.report_status = lambda _: observed.set()
        self.backend.observe.return_value = Observation()
        self.monitor.set_interval(10)
        worker = threading.Thread(target=self.monitor.run, args=(lambda: self.backend,))
        worker.start()
        try:
            self.assertTrue(observed.wait(2))
        finally:
            self.monitor.shutdown()
            worker.join(2)
        self.assertFalse(worker.is_alive())


if __name__ == "__main__":
    unittest.main()
