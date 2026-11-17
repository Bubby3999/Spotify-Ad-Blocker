# Spotify Control for Windows

Created by Bubby3999. The accompanying LICENSE requires attribution for
published or distributed uses and improvements.

Open Spotify normally. The dashboard watches for explicit ads while Spotify is
open. Use the system-tray icon to reopen a dismissed dashboard. Closing Spotify
stops playback checks; the helper waits for it to reopen. Closing the dashboard
keeps the helper in the tray. Choose Quit helper in the tray menu to stop it.

## Controls

- Ad helper enabled: turn automatic ad recovery on or off.
- Play / Pause: send a playback command to Spotify's window.
- Refresh: update status and the activity view.
- Check every: choose 1, 2, 5 or 10 seconds.
- Refresh daily: refresh status every 24 hours while Spotify is open.
- Instructions: open this guide. Open file uses the default document application.

Settings are saved under %LOCALAPPDATA%\Spotify Control\. Logs are rotated there
at approximately 512 KB. A sample UI opened by npm run mockup uses temporary
settings and a simulated backend instead of Spotify.

## Modes after an ad

- Open + Hide (default): request a background launch, resume playback and hide
  Spotify's window. A brief flash may still occur while Spotify starts.
- Open + Stay: reopen Spotify visibly and resume playback.
- Open + Stay + Lyrics: reopen visibly, resume, and request spotify:app:lyrics.
  This internal route is experimental and may be ignored. Use Spotify's Lyrics
  button if it does not open; some songs have no lyrics.

A mode change applies to the next ad recovery, not an operation already running.

## Recovery and limitations

Two explicit ad readings and current Spotify audio are required. There is a
60-second cooldown and at most two attempts until confirmed music returns.
Unknown metadata and paused ads are left alone. The helper closes Spotify's
window, waits, terminates remaining Spotify tray processes if necessary, and
reopens it. It reports success only after a track title and audio are observed.
If hiding or lyrics fails, the activity log records that separately.

Spotify remembers the track and queue; the helper does not restore a specific
URI or position. Restarts can lose your queue. Optional --mode mute avoids a
restart and lets ads finish silently. Audio verification currently reads the
default output endpoint, so custom per-app audio routing may prevent detection.
