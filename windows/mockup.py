"""Preview the real Windows dashboard with sample data and no Windows adapter."""

import logging
from pathlib import Path
import tempfile

from controller import Observation, SpotifyMonitor

log = logging.getLogger("spotify-ad-blocker")


class MockSpotify:
    def __init__(self):
        self.playing = True

    def observe(self):
        return Observation(
            processes=["mockup"], hwnd=1,
            title="Sample Artist - Sample Song" if self.playing else "Spotify",
            audio_active=self.playing,
        )

    def play(self, _hwnd):
        self.playing = True
        log.info("MOCKUP: sample playback resumed")

    def pause(self, _hwnd):
        self.playing = False
        log.info("MOCKUP: sample playback paused")

    def playpause(self, hwnd):
        self.pause(hwnd) if self.playing else self.play(hwnd)

    def quit(self, _observation):
        raise RuntimeError("Restarting applications is disabled in the mockup")

    def launch(self, hidden=False):
        raise RuntimeError("Launching applications is disabled in the mockup")

    def mute(self, _sessions):
        raise RuntimeError("Changing audio is disabled in the mockup")

    def restore_mute(self):
        pass

    def hide(self, _hwnd):
        return True

    def open_lyrics(self):
        log.info("MOCKUP: lyrics requested; no Spotify connection")

    def close(self):
        pass


def create_dashboard(directory):
    from dashboard import Dashboard

    monitor = SpotifyMonitor()
    dashboard = Dashboard(monitor, MockSpotify, directory / "settings.json", directory / "activity.log", mockup=True)
    dashboard.root.title("Spotify Control — Windows UI Mockup")
    dashboard.description.configure(text="UI mockup · Sample playback only · Spotify is not connected")
    dashboard.footer.configure(text="All controls are simulated. Close this window to exit the mockup.")
    dashboard.log_label.configure(text="Mockup settings are temporary; your installed helper settings are separate.")
    return dashboard


def main():
    log.setLevel(logging.INFO)
    with tempfile.TemporaryDirectory(prefix="spotify-ui-mockup-") as directory:
        dashboard = create_dashboard(Path(directory))
        log.info("MOCKUP: dashboard opened with sample data; Spotify is not connected")
        dashboard.run()


if __name__ == "__main__":
    main()
