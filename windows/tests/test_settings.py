import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spotify_ad_blocker import load_settings, save_settings


class SettingsTests(unittest.TestCase):
    def test_old_settings_migrate_without_losing_explicit_choices(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({"interval": 10, "enabled": False}), encoding="utf-8")
            self.assertEqual(load_settings(path), {"interval": 10, "enabled": False, "daily_refresh": True, "reopen_mode": "hide"})
            save_settings(path, 10, False, daily_refresh=False, reopen_mode="lyrics")
            self.assertEqual(load_settings(path), {"interval": 10, "enabled": False, "daily_refresh": False, "reopen_mode": "lyrics"})

    def test_invalid_optional_settings_cannot_crash_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            for invalid in ([], {}, True, None, "unknown"):
                path.write_text(json.dumps({"interval": 2, "enabled": True, "reopen_mode": invalid, "daily_refresh": invalid}), encoding="utf-8")
                settings = load_settings(path)
                self.assertEqual(settings["reopen_mode"], "hide")
                self.assertIsInstance(settings["daily_refresh"], bool)

    def test_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "settings.json"
            save_settings(path, 5, False)
            self.assertEqual(load_settings(path), {"interval": 5, "enabled": False, "daily_refresh": True, "reopen_mode": "hide"})
            self.assertFalse(path.with_suffix(".tmp").exists())

    def test_invalid_or_missing_settings_fall_back_to_safe_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            self.assertEqual(load_settings(path), {"interval": 2, "enabled": True, "daily_refresh": True, "reopen_mode": "hide"})
            for value in (None, [], {"interval": True, "enabled": True}, {"interval": 0, "enabled": True},
                          {"interval": 1, "enabled": "false"}):
                path.write_text(json.dumps(value), encoding="utf-8")
                self.assertEqual(load_settings(path), {"interval": 2, "enabled": True, "daily_refresh": True, "reopen_mode": "hide"})
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(load_settings(path), {"interval": 2, "enabled": True, "daily_refresh": True, "reopen_mode": "hide"})

    def test_cli_help_works_without_loading_windows_dependencies(self):
        script = Path(__file__).resolve().parents[1] / "spotify_ad_blocker.py"
        result = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--headless", result.stdout)
        self.assertIn("--diagnose", result.stdout)

    @unittest.skipIf(sys.platform == "win32", "Non-Windows error path")
    def test_wrong_os_exits_cleanly_without_ctypes_traceback(self):
        script = Path(__file__).resolve().parents[1] / "spotify_ad_blocker.py"
        result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertIn("requires Windows", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
