"""A disposable native Windows media window for CI; never starts Spotify."""

import argparse
import ctypes
import ctypes.wintypes as wt
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    from spotify_windows import load_user32, WM_APPCOMMAND, WM_CLOSE
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", default="Spotify")
    parser.add_argument("--ignore-close", action="store_true")
    args = parser.parse_args()
    lib, _ = load_user32()
    procedure = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
    lib.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    lib.DefWindowProcW.restype = ctypes.c_ssize_t
    lib.SetWindowTextW.argtypes = [wt.HWND, wt.LPCWSTR]
    lib.SetWindowTextW.restype = wt.BOOL
    lib.SetPropW.argtypes = [wt.HWND, wt.LPCWSTR, wt.HANDLE]
    lib.SetPropW.restype = wt.BOOL
    lib.GetPropW.argtypes = [wt.HWND, wt.LPCWSTR]
    lib.GetPropW.restype = wt.HANDLE
    lib.DestroyWindow.argtypes = [wt.HWND]
    lib.DestroyWindow.restype = wt.BOOL
    lib.PostQuitMessage.argtypes = [ctypes.c_int]

    @procedure
    def window_proc(hwnd, message, wparam, lparam):
        if message == WM_APPCOMMAND:
            command = (lparam >> 16) & 0xFFF
            playing = command == 46 or (command == 14 and not lib.GetPropW(hwnd, "MockPlaying"))
            if command in (14, 46, 47):
                lib.SetPropW(hwnd, "MockPlaying", 1 if playing else None)
                lib.SetWindowTextW(hwnd, "Fixture Artist - Fixture Song" if playing else "Spotify")
                return 1
        if message == WM_CLOSE:
            if not args.ignore_close:
                lib.DestroyWindow(hwnd)
            return 0
        if message == 2:  # WM_DESTROY
            lib.PostQuitMessage(0)
            return 0
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
    name = "Chrome_WidgetWin_SpotifyControlFixture"
    window_class = WindowClass(lpfnWndProc=window_proc, hInstance=instance, lpszClassName=name)
    lib.RegisterClassW.argtypes = [ctypes.POINTER(WindowClass)]
    lib.RegisterClassW.restype = wt.WORD
    if not lib.RegisterClassW(ctypes.byref(window_class)):
        raise ctypes.WinError(ctypes.get_last_error())
    lib.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wt.HWND, wt.HANDLE, wt.HANDLE, wt.LPVOID]
    lib.CreateWindowExW.restype = wt.HWND
    hwnd = lib.CreateWindowExW(0, name, args.title, 0x10CF0000, 50, 50, 320, 160, None, None, instance, None)
    if not hwnd:
        raise ctypes.WinError(ctypes.get_last_error())
    lib.SetPropW(hwnd, "MockPlaying", 1 if args.title == "Advertisement" else None)
    lib.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
    lib.GetMessageW.restype = wt.BOOL
    lib.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
    lib.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
    lib.DispatchMessageW.restype = ctypes.c_ssize_t
    message = wt.MSG()
    while lib.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
        lib.TranslateMessage(ctypes.byref(message))
        lib.DispatchMessageW(ctypes.byref(message))


if __name__ == "__main__":
    main()
