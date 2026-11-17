"""Windows process, window and audio operations. Importable on other OSes."""

from contextlib import contextmanager
import ctypes
import ctypes.wintypes as wt
import logging
import os
import sys
import time

from controller import Observation
from detector import AD, SONG, classify

log = logging.getLogger("spotify-ad-blocker")
WM_CLOSE = 0x0010
WM_APPCOMMAND = 0x0319
APPCOMMAND_MEDIA_PLAY = 46
APPCOMMAND_MEDIA_PAUSE = 47
APPCOMMAND_MEDIA_PLAY_PAUSE = 14
MUTEX_NAME = "Local\\SpotifyAdBlocker"


def load_user32():
    lib = ctypes.WinDLL("user32", use_last_error=True)
    enum_proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    signatures = {
        "EnumWindows": ([enum_proc, wt.LPARAM], wt.BOOL),
        "GetWindowThreadProcessId": ([wt.HWND, ctypes.POINTER(wt.DWORD)], wt.DWORD),
        "GetClassNameW": ([wt.HWND, wt.LPWSTR, ctypes.c_int], ctypes.c_int),
        "GetWindowTextLengthW": ([wt.HWND], ctypes.c_int),
        "GetWindowTextW": ([wt.HWND, wt.LPWSTR, ctypes.c_int], ctypes.c_int),
        "PostMessageW": ([wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM], wt.BOOL),
        "IsWindow": ([wt.HWND], wt.BOOL),
        "IsWindowVisible": ([wt.HWND], wt.BOOL),
        "ShowWindowAsync": ([wt.HWND, ctypes.c_int], wt.BOOL),
        "SendMessageTimeoutW": (
            [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT, ctypes.POINTER(ctypes.c_size_t)],
            ctypes.c_ssize_t,
        ),
    }
    for name, (args, result) in signatures.items():
        function = getattr(lib, name)
        function.argtypes = args
        function.restype = result
    return lib, enum_proc


@contextmanager
def single_instance():
    """Two helpers in the same Windows session must not race to restart Spotify."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [wt.LPVOID, wt.BOOL, wt.LPCWSTR]
    kernel.CreateMutexW.restype = wt.HANDLE
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    kernel.CloseHandle.restype = wt.BOOL
    handle = kernel.CreateMutexW(None, False, MUTEX_NAME)
    error = ctypes.get_last_error()
    if not handle:
        raise ctypes.WinError(error)
    try:
        if error == 183:
            raise RuntimeError("Spotify Control is already running. Open its icon in the system tray.")
        yield
    finally:
        kernel.CloseHandle(handle)


class WindowsSpotify:
    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("Spotify Control for Windows requires Windows 10 or 11")
        import comtypes
        import psutil
        from pycaw.pycaw import AudioUtilities, IAudioMeterInformation

        self.psutil = psutil
        self.comtypes = comtypes
        self.audio = AudioUtilities
        self.meter_interface = IAudioMeterInformation
        self.user32, self.enum_proc = load_user32()
        self.username = psutil.Process().username()
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.ProcessIdToSessionId.argtypes = [wt.DWORD, ctypes.POINTER(wt.DWORD)]
        self.kernel.ProcessIdToSessionId.restype = wt.BOOL
        self.session_id = self.session_for_pid(os.getpid())
        if self.session_id is None:
            raise OSError("Could not identify the current Windows session")
        self.muted_by_us = {}
        comtypes.CoInitialize()

    def close(self):
        self.comtypes.CoUninitialize()

    def session_for_pid(self, pid):
        session = wt.DWORD()
        if self.kernel.ProcessIdToSessionId(pid, ctypes.byref(session)):
            return session.value
        return None

    def processes(self):
        result = []
        for proc in self.psutil.process_iter(["name", "username"]):
            if ((proc.info.get("name") or "").casefold() == "spotify.exe"
                    and proc.info.get("username") == self.username
                    and self.session_for_pid(proc.pid) == self.session_id):
                result.append(proc)
        return result

    def window(self, processes):
        pids = {proc.pid for proc in processes}
        found = []

        def callback(hwnd, _):
            pid = wt.DWORD()
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value not in pids:
                return True
            cls = ctypes.create_unicode_buffer(256)
            self.user32.GetClassNameW(hwnd, cls, len(cls))
            if not cls.value.startswith("Chrome_WidgetWin"):
                return True
            length = self.user32.GetWindowTextLengthW(hwnd)
            if length:
                title = ctypes.create_unicode_buffer(length + 1)
                self.user32.GetWindowTextW(hwnd, title, len(title))
                found.append((hwnd, title.value))
            return True

        if pids and not self.user32.EnumWindows(self.enum_proc(callback), 0):
            raise ctypes.WinError(ctypes.get_last_error())
        # Prefer the playback window over a generic Spotify auxiliary window.
        for state in (SONG, AD):
            for hwnd, title in found:
                if classify(title, None) == state:
                    return hwnd, title
        return found[0] if found else (None, None)

    def sessions(self, pids):
        return [session for session in self.audio.GetAllSessions() if session.ProcessId in pids]

    def audio_active(self, sessions):
        readable = not sessions
        for session in sessions:
            try:
                meter = session._ctl.QueryInterface(self.meter_interface)
                peak = meter.GetPeakValue()
                readable = True
                if peak > 0.0001:
                    return True
            except Exception:
                log.debug("Spotify audio meter unavailable", exc_info=True)
        return False if readable else None

    def observe(self):
        processes = self.processes()
        hwnd, title = self.window(processes)
        sessions = []
        audible = False
        if processes:
            try:
                sessions = self.sessions({proc.pid for proc in processes})
                audible = self.audio_active(sessions)
            except Exception:
                # Explicit ad titles remain usable when the audio device disconnects.
                log.debug("Windows audio endpoint unavailable", exc_info=True)
                audible = None
        return Observation(processes, hwnd, title, audible, sessions)

    def quit(self, observation):
        if observation.hwnd:
            if not self.user32.PostMessageW(observation.hwnd, WM_CLOSE, 0, 0):
                log.warning("Spotify did not accept the window close request")
        _, alive = self.psutil.wait_procs(observation.processes, timeout=3)
        # Closing Spotify can leave it in the tray; it must fully exit to skip an ad.
        for proc in alive:
            try:
                proc.terminate()
            except self.psutil.NoSuchProcess:
                pass
        _, alive = self.psutil.wait_procs(alive, timeout=10)
        if alive or self.processes():
            log.error("Spotify processes remain; refusing to start another instance")
            return False
        return True

    def launch(self, hidden=False):
        if hidden:
            os.startfile("spotify:", show_cmd=0)
        else:
            os.startfile("spotify:")

    def hide(self, hwnd):
        if not self.user32.IsWindow(hwnd):
            return False
        if not self.user32.IsWindowVisible(hwnd):
            return True
        self.user32.ShowWindowAsync(hwnd, 0)  # SW_HIDE; do not change focus or send keys.
        for _ in range(10):
            if not self.user32.IsWindow(hwnd):
                return False
            if not self.user32.IsWindowVisible(hwnd):
                return True
            time.sleep(0.05)
        return False

    def open_lyrics(self):
        os.startfile("spotify:app:lyrics")

    def _command(self, hwnd, command):
        # HWND, WPARAM and LPARAM must retain pointer width on 64-bit Windows.
        result = ctypes.c_size_t()
        if not self.user32.SendMessageTimeoutW(
            hwnd, WM_APPCOMMAND, hwnd, command << 16, 0x0002 | 0x0020, 1000, ctypes.byref(result)
        ):
            raise OSError("Spotify playback command failed or timed out")

    def play(self, hwnd):
        self._command(hwnd, APPCOMMAND_MEDIA_PLAY)

    def pause(self, hwnd):
        self._command(hwnd, APPCOMMAND_MEDIA_PAUSE)

    def playpause(self, hwnd):
        self._command(hwnd, APPCOMMAND_MEDIA_PLAY_PAUSE)

    def mute(self, sessions):
        for session in sessions:
            key = session.InstanceIdentifier
            if key not in self.muted_by_us:
                volume = session.SimpleAudioVolume
                if not volume.GetMute():
                    self.muted_by_us[key] = volume
                    volume.SetMute(1, None)

    def restore_mute(self):
        for key, volume in list(self.muted_by_us.items()):
            try:
                volume.SetMute(0, None)
            except Exception:
                log.debug("Could not restore a Spotify audio session; it may have exited", exc_info=True)
            else:
                del self.muted_by_us[key]
