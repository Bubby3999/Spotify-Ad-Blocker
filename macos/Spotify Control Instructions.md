# Spotify Control for macOS

Created by Bubby3999. See the bundled LICENSE for attribution requirements.

Open Spotify Desktop normally. The helper opens its dashboard when Spotify
opens, checks playback while Spotify is running, and waits when Spotify closes.
Use the music-note menu-bar item to reopen a dismissed dashboard.

The dashboard has an ad-helper toggle, Play/Pause, Refresh, an interval selector
(1, 2, 5 or 10 seconds), daily refresh, playback status and a selectable activity
log. Settings are saved. Closing this dashboard hides its window; the menu-bar
helper continues running.

## Modes

- Open + Stay: reopen Spotify visibly and request playback.
- Open + Hide (default): reopen in the background and request hiding. Check the activity
  log if Spotify remains visible; hiding is not guaranteed on every setup.
- Open + Stay + Lyrics: request the internal lyrics route after playback
  resumes. Automatic display is not visually verified. You can also click
  Spotify's Lyrics button; lyrics are not available for every track.

A mode change takes effect after the next ad recovery.

## Ad handling

Two consecutive explicit ad observations are required, with a 60-second cooldown
and at most two attempts per ad identifier until legitimate playback returns.
Normal track, podcast, local-file and audiobook URIs are excluded. Unknown or
missing metadata is left alone. Spotify is asked to quit normally; it is never
force-quit. Spotify remembers the track and queue; the helper does not restore a
specific URI or position, and restarting can lose the queue.

If prompted, allow Spotify Control to control Spotify in System Settings →
Privacy & Security → Automation. Accessibility permission is not required.

Logs and the editable instructions copy live in
`~/Library/Application Support/Spotify Control/`. The log rotates at about 512 KB.
The local instructions copy is preserved when the app restarts or is rebuilt.

## Build and service controls

Build with `macos/Build Spotify Control.command` from the repository. The app and
generated LaunchAgent go into `macos/build/`. See the repository README for
installation, backups and the Windows version.

To stop the installed helper:

```bash
launchctl bootout "gui/$(id -u)/com.user.spotifyadmute"
```

To prevent login startup:

```bash
launchctl disable "gui/$(id -u)/com.user.spotifyadmute"
```

Stopping the helper does not remove Spotify or change its installation.
