import os
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from detector import PAUSED, SONG
from mockup import MockSpotify


class MockupTests(unittest.TestCase):
    def test_playback_changes_only_sample_state(self):
        backend = MockSpotify()
        self.assertEqual(backend.observe().state, SONG)
        backend.pause(1)
        self.assertFalse(backend.observe().audio_active)
        self.assertEqual(backend.observe().state, PAUSED)
        backend.play(1)
        self.assertTrue(backend.observe().audio_active)

    def test_restart_launch_and_audio_changes_are_blocked(self):
        backend = MockSpotify()
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            backend.quit(backend.observe())
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            backend.launch()
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            backend.mute([])
        backend.restore_mute()
        backend.close()

    def test_mockup_does_not_import_the_real_windows_adapter(self):
        code = "import sys; import mockup; assert 'spotify_windows' not in sys.modules; assert 'pycaw' not in sys.modules; assert 'psutil' not in sys.modules"
        result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
