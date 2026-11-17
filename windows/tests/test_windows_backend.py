import ctypes
import os
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from controller import Observation
from spotify_windows import APPCOMMAND_MEDIA_PAUSE, APPCOMMAND_MEDIA_PLAY, WM_APPCOMMAND, WM_CLOSE, WindowsSpotify


class NoSuchProcess(Exception):
    pass


class BackendTests(unittest.TestCase):
    def setUp(self):
        # Exercise the Windows adapter without loading native DLLs on macOS/Linux.
        self.backend = WindowsSpotify.__new__(WindowsSpotify)
        self.backend.user32 = Mock()
        self.backend.psutil = Mock(NoSuchProcess=NoSuchProcess)
        self.backend.username = "test-user"
        self.backend.session_id = 1
        self.backend.session_for_pid = Mock(return_value=1)
        self.backend.audio = Mock()
        self.backend.meter_interface = object()
        self.backend.muted_by_us = {}

    def test_only_current_users_spotify_processes_are_returned(self):
        own = SimpleNamespace(pid=123, info={"name": "Spotify.exe", "username": "test-user"})
        other_user = SimpleNamespace(info={"name": "Spotify.exe", "username": "other-user"})
        other_app = SimpleNamespace(info={"name": "chrome.exe", "username": "test-user"})
        inaccessible = SimpleNamespace(info={"name": None, "username": None})
        self.backend.psutil.process_iter.return_value = [own, other_user, other_app, inaccessible]
        self.assertEqual(self.backend.processes(), [own])

    def test_same_users_other_windows_session_is_not_touched(self):
        process = SimpleNamespace(pid=123, info={"name": "Spotify.exe", "username": "test-user"})
        self.backend.psutil.process_iter.return_value = [process]
        for session in (2, None):
            self.backend.session_for_pid.return_value = session
            self.assertEqual(self.backend.processes(), [])

    def test_close_then_terminate_tray_processes_and_wait(self):
        first, tray = Mock(pid=1), Mock(pid=2)
        self.backend.psutil.wait_procs.side_effect = [([first], [tray]), ([tray], [])]
        self.backend.psutil.process_iter.return_value = []
        self.assertTrue(self.backend.quit(Observation([first, tray], 42)))
        self.backend.user32.PostMessageW.assert_called_once_with(42, WM_CLOSE, 0, 0)
        first.terminate.assert_not_called()
        tray.terminate.assert_called_once()
        self.assertEqual(self.backend.psutil.wait_procs.call_args_list[-1].kwargs, {"timeout": 10})

    def test_stubborn_process_does_not_count_as_closed(self):
        process = Mock()
        self.backend.psutil.wait_procs.return_value = ([], [process])
        with self.assertLogs("spotify-ad-blocker", level="ERROR"):
            self.assertFalse(self.backend.quit(Observation([process])))

    def test_process_that_respawns_prevents_relaunch(self):
        self.backend.psutil.wait_procs.return_value = ([], [])
        self.backend.psutil.process_iter.return_value = [
            SimpleNamespace(pid=123, info={"name": "Spotify.exe", "username": "test-user"})]
        with self.assertLogs("spotify-ad-blocker", level="ERROR"):
            self.assertFalse(self.backend.quit(Observation([Mock()])))

    def test_process_disappearing_during_termination_is_harmless(self):
        process = Mock()
        process.terminate.side_effect = NoSuchProcess()
        self.backend.psutil.wait_procs.side_effect = [([], [process]), ([process], [])]
        self.backend.psutil.process_iter.return_value = []
        self.assertTrue(self.backend.quit(Observation([process])))

    def test_access_denied_is_not_silently_ignored(self):
        process = Mock()
        process.terminate.side_effect = PermissionError("access denied")
        self.backend.psutil.wait_procs.return_value = ([], [process])
        with self.assertRaises(PermissionError):
            self.backend.quit(Observation([process]))

    def test_explicit_play_and_pause_target_only_spotifys_window(self):
        hwnd = 0x123456789
        self.backend.play(hwnd)
        self.backend.pause(hwnd)
        calls = self.backend.user32.SendMessageTimeoutW.call_args_list
        self.assertEqual(calls[0].args[:4], (hwnd, WM_APPCOMMAND, hwnd, APPCOMMAND_MEDIA_PLAY << 16))
        self.assertEqual(calls[1].args[:4], (hwnd, WM_APPCOMMAND, hwnd, APPCOMMAND_MEDIA_PAUSE << 16))
        self.assertEqual(calls[0].args[5], 1000)

    def test_hung_window_command_raises_instead_of_blocking_forever(self):
        self.backend.user32.SendMessageTimeoutW.return_value = 0
        with self.assertRaisesRegex(OSError, "timed out"):
            self.backend.play(42)

    def test_protocol_launch_supports_registered_spotify_installs(self):
        with patch("spotify_windows.os.startfile", create=True) as startfile:
            self.backend.launch()
        startfile.assert_called_once_with("spotify:")

    def test_hidden_launch_and_lyrics_use_spotify_protocol(self):
        with patch("spotify_windows.os.startfile", create=True) as startfile:
            self.backend.launch(hidden=True)
            self.backend.open_lyrics()
        self.assertEqual(startfile.call_args_list[0].args, ("spotify:",))
        self.assertEqual(startfile.call_args_list[0].kwargs, {"show_cmd": 0})
        self.assertEqual(startfile.call_args_list[1].args, ("spotify:app:lyrics",))

    def test_hide_checks_visibility_instead_of_assuming_success(self):
        self.backend.user32.IsWindow.return_value = True
        self.backend.user32.IsWindowVisible.side_effect = [True, False]
        self.assertTrue(self.backend.hide(42))
        self.backend.user32.ShowWindowAsync.assert_called_once_with(42, 0)

    def test_already_hidden_window_is_success_and_missing_window_is_not(self):
        self.backend.user32.IsWindow.return_value = True
        self.backend.user32.IsWindowVisible.return_value = False
        self.assertTrue(self.backend.hide(42))
        self.backend.user32.ShowWindowAsync.assert_not_called()
        self.backend.user32.IsWindow.return_value = False
        self.assertFalse(self.backend.hide(42))

    def test_audio_sessions_are_filtered_by_spotify_pid(self):
        spotify = SimpleNamespace(ProcessId=123)
        browser = SimpleNamespace(ProcessId=456)
        system_sound = SimpleNamespace(ProcessId=0)
        self.backend.audio.GetAllSessions.return_value = [spotify, browser, system_sound]
        self.assertEqual(self.backend.sessions({123}), [spotify])

    def test_audio_meter_recovers_when_one_session_disappears(self):
        stale, active = Mock(), Mock()
        stale._ctl.QueryInterface.side_effect = OSError("gone")
        active._ctl.QueryInterface.return_value.GetPeakValue.return_value = 0.3
        self.assertTrue(self.backend.audio_active([stale, active]))
        self.assertIsNone(self.backend.audio_active([stale]))
        self.assertFalse(self.backend.audio_active([]))

    def test_audio_endpoint_error_does_not_prevent_explicit_ad_detection(self):
        with patch.object(self.backend, "processes", return_value=[Mock(pid=123)]), \
                patch.object(self.backend, "window", return_value=(42, "Advertisement")):
            self.backend.audio.GetAllSessions.side_effect = OSError("no speakers")
            current = self.backend.observe()
        self.assertEqual(current.state, "ad")
        self.assertIsNone(current.audio_active)

    def test_only_sessions_muted_by_this_helper_are_unmuted(self):
        manual, normal = Mock(InstanceIdentifier="manual"), Mock(InstanceIdentifier="normal")
        manual.SimpleAudioVolume.GetMute.return_value = 1
        normal.SimpleAudioVolume.GetMute.return_value = 0
        self.backend.mute([manual, normal])
        self.backend.mute([manual, normal])
        normal.SimpleAudioVolume.SetMute.assert_called_once_with(1, None)
        self.backend.restore_mute()
        manual.SimpleAudioVolume.SetMute.assert_not_called()
        normal.SimpleAudioVolume.SetMute.assert_called_with(0, None)
        self.assertEqual(self.backend.muted_by_us, {})


@unittest.skipUnless(sys.platform == "win32", "Requires actual Windows User32/Kernel32")
class NativeWindowsTests(unittest.TestCase):
    def test_native_window_discovery_and_targeted_commands(self):
        """Use a real test window, never close or control a user's Spotify."""
        import ctypes.wintypes as wt
        from spotify_windows import load_user32

        lib, enum_proc = load_user32()
        procedure = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
        lib.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        lib.DefWindowProcW.restype = ctypes.c_ssize_t
        commands = []

        @procedure
        def window_proc(hwnd, message, wparam, lparam):
            if message == WM_APPCOMMAND:
                commands.append((lparam >> 16) & 0xFFF)
                return 1
            return lib.DefWindowProcW(hwnd, message, wparam, lparam)

        class WindowClass(ctypes.Structure):
            _fields_ = [("style", wt.UINT), ("lpfnWndProc", procedure), ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HANDLE), ("hIcon", wt.HANDLE),
                        ("hCursor", wt.HANDLE), ("hbrBackground", wt.HANDLE),
                        ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetModuleHandleW.argtypes = [wt.LPCWSTR]
        kernel.GetModuleHandleW.restype = wt.HANDLE
        instance = kernel.GetModuleHandleW(None)
        class_name = f"Chrome_WidgetWin_SpotifyControlTest_{os.getpid()}"
        window_class = WindowClass(lpfnWndProc=window_proc, hInstance=instance, lpszClassName=class_name)
        lib.RegisterClassW.argtypes = [ctypes.POINTER(WindowClass)]
        lib.RegisterClassW.restype = wt.WORD
        lib.UnregisterClassW.argtypes = [wt.LPCWSTR, wt.HANDLE]
        lib.UnregisterClassW.restype = wt.BOOL
        self.assertTrue(lib.RegisterClassW(ctypes.byref(window_class)))
        self.addCleanup(lib.UnregisterClassW, class_name, instance)
        lib.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, wt.HWND, wt.HANDLE, wt.HANDLE, wt.LPVOID]
        lib.CreateWindowExW.restype = wt.HWND
        hwnd = lib.CreateWindowExW(0, class_name, "Test Artist - Test Song", 0, 0, 0, 100, 100, None, None, instance, None)
        self.assertTrue(hwnd)
        lib.DestroyWindow.argtypes = [wt.HWND]
        lib.DestroyWindow.restype = wt.BOOL
        # DestroyWindow calls WNDPROC; keep the ctypes callback alive through cleanup.
        self.addCleanup(lambda callback=window_proc: lib.DestroyWindow(hwnd))
        backend = WindowsSpotify.__new__(WindowsSpotify)
        backend.user32, backend.enum_proc = lib, enum_proc
        self.assertEqual(backend.window([SimpleNamespace(pid=os.getpid())]), (hwnd, "Test Artist - Test Song"))
        backend.play(hwnd)
        backend.pause(hwnd)
        self.assertEqual(commands, [APPCOMMAND_MEDIA_PLAY, APPCOMMAND_MEDIA_PAUSE])

    def test_duplicate_instance_is_blocked_and_mutex_is_released(self):
        from spotify_windows import single_instance
        with patch("spotify_windows.MUTEX_NAME", f"Local\\SpotifyControlTest_{os.getpid()}"):
            with single_instance():
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    with single_instance():
                        self.fail("Duplicate instance was accepted")
            with single_instance():
                pass

    def test_real_dependency_imports_and_read_only_observation(self):
        backend = WindowsSpotify()
        try:
            self.assertIsInstance(backend.observe(), Observation)
        finally:
            backend.close()

    def test_real_tray_icon_starts_hides_and_stops(self):
        from tray import TrayIcon
        tray = TrayIcon(lambda action: None)
        try:
            tray.start()
            self.assertTrue(tray.icon.visible)
            tray.icon.visible = False
            self.assertFalse(tray.icon.visible)
        finally:
            tray.stop()


if __name__ == "__main__":
    unittest.main()
