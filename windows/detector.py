"""Pure ad-detection logic for the Windows version.

Kept free of Windows imports so it can be unit-tested on any OS.
"""

from dataclasses import dataclass

# A plain Spotify title also appears during startup and navigation.
IDLE_TITLES = {"spotify", "spotify free", "spotify premium"}
AD_TITLES = {"advertisement", "advertisement - spotify", "spotify - advertisement"}

SONG = "song"
PAUSED = "paused"
AD = "ad"
UNKNOWN = "unknown"


def classify(title: str | None, audio_active: bool | None) -> str:
    """Only explicit ad titles justify restarting another application.

    shortcut: window titles cannot identify every ad or media type; use a
    supported Spotify metadata interface if one becomes available on Windows.
    """
    if not title:
        return UNKNOWN
    t = title.strip()
    if t.casefold() in AD_TITLES:
        return AD
    if " - " in t and all(part.strip() for part in t.split(" - ")):
        return SONG
    if t.casefold() in IDLE_TITLES and audio_active is False:
        return PAUSED
    return UNKNOWN


@dataclass
class RestartController:
    """Keep cooldown and retry accounting independent from mute state."""

    cooldown: float = 60.0
    max_attempts: int = 2
    ad_streak: int = 0
    song_streak: int = 0
    attempts: int = 0
    last_attempt: float | None = None

    def update(self, state: str, now: float) -> bool:
        self.ad_streak = self.ad_streak + 1 if state == AD else 0
        self.song_streak = self.song_streak + 1 if state == SONG else 0
        # A transient title or failed restart must not reset the retry budget.
        if self.song_streak >= 2:
            self.attempts = 0
        ready = self.last_attempt is None or now - self.last_attempt >= self.cooldown
        if self.ad_streak >= 2 and ready and self.attempts < self.max_attempts:
            self.attempts += 1
            self.last_attempt = now
            self.ad_streak = 0
            return True
        return False


@dataclass
class MuteController:
    """Decides when to mute/unmute, with the same caution as the Mac app:
    an ad must be seen twice in a row before anything happens, and only a
    real song title unmutes (muting can make the audio meter read silent,
    so the meter can't be trusted while muted)."""

    confirmations_needed: int = 2
    ad_streak: int = 0
    muted: bool = False

    def update(self, state: str) -> str | None:
        """Return "mute", "unmute" or None for this observation."""
        if state == AD:
            self.ad_streak += 1
            if not self.muted and self.ad_streak >= self.confirmations_needed:
                self.muted = True
                return "mute"
            return None
        self.ad_streak = 0
        if state == SONG and self.muted:
            self.muted = False
            return "unmute"
        return None
