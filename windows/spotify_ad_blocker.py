"""Spotify Control for Windows: quit Spotify on a confirmed ad, reopen and play.

Launches a dashboard by default. Use --headless for a background monitor,
--diagnose for a read-only report, or --mode mute for the optional mute mode.
"""

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import tempfile

from controller import INTERVALS, REOPEN_MODES, SpotifyMonitor

log = logging.getLogger("spotify-ad-blocker")


def app_directory():
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Spotify Control"


def load_settings(path):
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
        if (isinstance(settings, dict) and type(settings.get("interval")) is int
                and settings["interval"] in INTERVALS and type(settings.get("enabled")) is bool):
            return {
                "interval": settings["interval"], "enabled": settings["enabled"],
                "daily_refresh": settings.get("daily_refresh") if type(settings.get("daily_refresh")) is bool else True,
                "reopen_mode": settings.get("reopen_mode") if isinstance(settings.get("reopen_mode"), str) and settings["reopen_mode"] in REOPEN_MODES else "hide",
            }
    except (OSError, ValueError):
        pass
    return {"interval": 2, "enabled": True, "daily_refresh": True, "reopen_mode": "hide"}


def save_settings(path, interval, enabled, daily_refresh=True, reopen_mode="hide"):
    if type(interval) is not int or interval not in INTERVALS or type(enabled) is not bool:
        raise ValueError("Invalid dashboard settings")
    if type(daily_refresh) is not bool or not isinstance(reopen_mode, str) or reopen_mode not in REOPEN_MODES:
        raise ValueError("Invalid reopening or daily-refresh settings")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"interval": interval, "enabled": enabled, "daily_refresh": daily_refresh, "reopen_mode": reopen_mode}), encoding="utf-8")
    temporary.replace(path)


def configure_logging(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handlers = [RotatingFileHandler(path, maxBytes=512 * 1024, backupCount=2, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    log.setLevel(logging.INFO)
    for handler in handlers:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
        log.addHandler(handler)


def check_dashboard():
    """Exercise the packaged Tk UI with fake playback, then exit automatically."""
    from mockup import create_dashboard
    failures = []
    exercised = False
    with tempfile.TemporaryDirectory(prefix="spotify-ui-check-") as directory:
        dashboard = create_dashboard(Path(directory))
        def callback_error(kind, error, traceback):
            failures.append(error)
            log.error("Dashboard check failed", exc_info=(kind, error, traceback))
            dashboard.close()
        dashboard.root.report_callback_exception = callback_error
        def exercise():
            nonlocal exercised
            dashboard.buttons["playpause"].invoke()
            dashboard.daily_toggle.invoke()
            dashboard.reopen_mode.set(REOPEN_MODES["lyrics"])
            dashboard.change_mode()
            dashboard.show_instructions()
            assert Path(__file__).with_name("Spotify Control Instructions.md").is_file()
            exercised = True
            dashboard.root.after(250, dashboard.close)
        dashboard.root.after(250, exercise)
        dashboard.root.after(10000, dashboard.close)
        dashboard.run()
        if not exercised or failures or dashboard.monitor.failure is not None:
            raise RuntimeError("Packaged dashboard check failed")
    log.info("Dashboard startup check passed")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headless", action="store_true", help="run without the control dashboard")
    parser.add_argument("--diagnose", action="store_true", help="report detection state without changing Spotify")
    parser.add_argument("--check-ui", action="store_true", help="briefly exercise the dashboard with simulated playback, then exit")
    parser.add_argument("--mode", choices=("restart", "mute"), default="restart")
    parser.add_argument("--reopen", choices=tuple(REOPEN_MODES), help="after an ad: hide (default), stay visible, or request lyrics")
    parser.add_argument("--interval", type=int, choices=INTERVALS, help="check interval in seconds (saved in dashboard)")
    parser.add_argument("--log", type=Path, help="override the default rotating activity log")
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        parser.exit(1, "This application requires Windows 10 or 11. Use the macOS app on a Mac.\n")
    log_path = args.log or app_directory() / "activity.log"
    try:
        configure_logging(log_path)
        # Import on the main thread; the worker initializes its own COM apartment.
        import psutil  # noqa: F401
        import pycaw.pycaw  # noqa: F401
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
        from spotify_windows import WindowsSpotify, single_instance

        if args.check_ui:
            check_dashboard()
            return 0

        if args.diagnose:
            backend = WindowsSpotify()
            try:
                current = backend.observe()
                diagnostic = json.dumps({
                    "processes": len(current.processes), "window_found": bool(current.hwnd),
                    "title": current.title, "audio_active": current.audio_active,
                    "audio_sessions": len(current.sessions), "state": current.state,
                }, indent=2)
                log.info("Read-only diagnostics: %s", diagnostic)
                if sys.stdout is not None:
                    print(diagnostic)
            finally:
                backend.close()
            return 0
        with single_instance():
            path = app_directory() / "settings.json"
            settings = load_settings(path)
            monitor = SpotifyMonitor(args.interval or settings["interval"], args.mode,
                                     reopen_mode=args.reopen or settings["reopen_mode"], daily_refresh=settings["daily_refresh"])
            monitor.set_enabled(settings["enabled"] if not args.headless else True)
            if args.headless:
                try:
                    monitor.run(WindowsSpotify)
                finally:
                    monitor.shutdown()
            else:
                from dashboard import Dashboard
                dashboard = Dashboard(monitor, WindowsSpotify, path, log_path, enable_tray=True)
                dashboard.run()
            if monitor.failure is not None:
                return 1
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        log.exception("Spotify Control could not start")
        if not args.headless and not args.diagnose and not args.check_ui:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f"{error}\n\nLog: {log_path}", "Spotify Control", 0x10)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
