import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from detector import AD, PAUSED, SONG, UNKNOWN, MuteController, RestartController, classify


class ClassifyTests(unittest.TestCase):
    def test_song(self):
        self.assertEqual(classify("Daft Punk - One More Time", True), SONG)

    def test_idle_title_silent_is_paused(self):
        self.assertEqual(classify("Spotify Free", False), PAUSED)

    def test_idle_title_with_audio_is_unknown(self):
        self.assertEqual(classify("Spotify", True), UNKNOWN)

    def test_advertisement_title(self):
        self.assertEqual(classify("Advertisement", True), AD)

    def test_unknown(self):
        self.assertEqual(classify("", True), UNKNOWN)
        self.assertEqual(classify("Advertisement", False), AD)

    def test_ad_titles_take_precedence_over_song_separator(self):
        for title in ("Spotify - Advertisement", "Advertisement - Spotify", "  ADVERTISEMENT "):
            with self.subTest(title=title):
                self.assertEqual(classify(title, None), AD)

    def test_unknown_titles_do_not_restart_podcasts_or_navigation(self):
        for title in (None, " ", "Podcast episode", "Advertiser name", "Spotify Premium", " - Song", "Artist - "):
            with self.subTest(title=title):
                self.assertEqual(classify(title, True), UNKNOWN)

    def test_track_named_advertisement_is_still_music(self):
        self.assertEqual(classify("Some Artist - Advertisement", True), SONG)


class RestartControllerTests(unittest.TestCase):
    def test_first_ad_can_restart_immediately_after_confirmation(self):
        c = RestartController()
        self.assertFalse(c.update(AD, 0))
        self.assertTrue(c.update(AD, 1))

    def test_cooldown_does_not_consume_second_attempt(self):
        c = RestartController()
        c.update(AD, 0)
        self.assertTrue(c.update(AD, 1))
        for now in range(2, 61):
            self.assertFalse(c.update(AD, now))
        self.assertEqual(c.attempts, 1)
        self.assertTrue(c.update(AD, 61))

    def test_two_attempts_maximum_even_after_unknown_or_pause(self):
        c = RestartController()
        for now in (0, 1, 61, 62):
            c.update(AD, now)
        self.assertEqual(c.attempts, 2)
        for state, now in ((UNKNOWN, 100), (PAUSED, 101), (AD, 200), (AD, 201), (AD, 1000)):
            self.assertFalse(c.update(state, now))

    def test_only_two_consecutive_song_readings_reset_budget(self):
        c = RestartController(attempts=2, last_attempt=0)
        for state in (SONG, UNKNOWN, SONG, AD):
            self.assertFalse(c.update(state, 100))
        self.assertEqual(c.attempts, 2)
        c.update(SONG, 101)
        c.update(SONG, 102)
        self.assertEqual(c.attempts, 0)
        self.assertFalse(c.update(AD, 103))
        self.assertTrue(c.update(AD, 104))

    def test_interruption_resets_consecutive_confirmation(self):
        c = RestartController()
        c.update(AD, 0)
        c.update(UNKNOWN, 1)
        self.assertFalse(c.update(AD, 2))


class ControllerTests(unittest.TestCase):
    def test_needs_two_ad_observations(self):
        c = MuteController()
        self.assertIsNone(c.update(AD))
        self.assertEqual(c.update(AD), "mute")
        self.assertIsNone(c.update(AD))

    def test_only_song_unmutes(self):
        c = MuteController()
        c.update(AD); c.update(AD)
        self.assertIsNone(c.update(PAUSED))
        self.assertIsNone(c.update(UNKNOWN))
        self.assertEqual(c.update(SONG), "unmute")

    def test_single_ad_blip_ignored(self):
        c = MuteController()
        c.update(AD)
        c.update(SONG)
        self.assertIsNone(c.update(AD))


if __name__ == "__main__":
    unittest.main()
