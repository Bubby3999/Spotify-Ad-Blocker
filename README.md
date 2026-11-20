# Spotify Ad Blocker

I built Spotify Control with Codex because repeated ads interrupt background
listening. It watches Spotify Desktop, confirms an ad, then tries to skip it by
quitting and reopening Spotify and requesting playback.

It is intended for **Spotify Free on macOS or Windows**. It does not support
mobile apps or the web player. Spotify Premium users do not need the ad helper.

If you are using an AI Agent to set this up, simply tell it to read AGENT_README.md and execute.

## How it works

1. Watch playback while Spotify is open.
2. Require two consecutive explicit ad readings before acting.
3. Quit Spotify, reopen it, request playback, and check the result.

Both versions rely on Spotify remembering the track and queue. Neither version
explicitly restores a saved track URI or playback position. Restarting can clear
your queue and briefly flash or move Spotify's window, which can interrupt games
or full-screen work. Ads reported in an unfamiliar way may play normally.

| Platform | Implementation | Verification status |
|---|---|---|
| macOS | Native Swift dashboard and login LaunchAgent | Recovered source builds; self-tests and signature pass; live candidate testing pending |
| Windows | Python dashboard; restart is the default, mute is optional | 94 tests passed on a Windows runner; packaged diagnostics/dashboard checks passed; live Spotify playback unverified |

## Dashboard and platform differences

### Try the UI without Spotify

From the repository root, run:

```bash
npm run mockup
```

No `npm install` is needed. This opens the actual Mac dashboard on macOS, or the
Windows dashboard on Windows, using sample playback. Buttons, settings and
status changes are simulated; the mockup does not connect to Spotify, install a
service, or change the installed helper's settings. Closing the mockup exits it.
Node.js 18+ and npm are needed for this launcher; the installed helper does not
depend on Node.

To inspect the Windows dashboard on this Mac:

```bash
npm run mockup -- --windows
```

The Mac preview builds from source using the existing Command Line Tools. The
Windows preview needs Python 3.10+ with Tk; its Spotify-specific dependencies are
not required. Mac settings stay in memory; Windows preview files use a temporary
directory and are removed on normal exit.

### Controls

Both dashboards have an ad-helper toggle, Play/Pause, Refresh, daily refresh,
Instructions, Open + Hide/Stay/Lyrics modes, a saved 1/2/5/10-second check
interval, playback status and an activity log. Spotify work
runs separately from the interface.

| Feature | macOS | Windows |
|---|---|---|
| Open + Hide | Default mode | Default mode |
| Open + Stay | Available | Available |
| Verify hiding | Native app hiding; already-hidden state accepted | Native window visibility checked |
| Automatically request lyrics | Experimental internal Spotify route | Same experimental route |
| Manual lyrics | Use Spotify's Lyrics button | Use Spotify's Lyrics button |
| Daily status refresh | Available while Spotify is open | Available while Spotify is open |
| Dashboard access | Music-note menu-bar item; appears when Spotify opens | System-tray icon; appears when Spotify opens |
| Closing the dashboard | Hides the window; helper keeps running | Hides the window; helper keeps running in the tray |
| Start at login | LaunchAgent | Optional Startup-folder shortcut |
| Optional mute mode | Not implemented | `--mode mute`; lets the ad finish silently |

Lyrics depend on the song and device. See [Spotify's lyrics instructions](https://support.spotify.com/us/article/lyrics/).

### Detection and safeguards

- **macOS:** reads playback state and Spotify URIs. Explicit ad URIs, or an
  `Advertisement` title with an empty URI, count as ads. Track, podcast,
  audiobook and local-file URIs are excluded. It requests a normal quit and does
  not force-quit Spotify. Playback confirmation requires legitimate content, so a still-playing ad is not counted as recovery.
- **Windows:** requires an explicit `Advertisement`, `Advertisement - Spotify`
  or `Spotify - Advertisement` title and active Spotify audio. Unknown titles
  and paused ads do not trigger a restart. It closes the window, waits, and
  terminates Spotify processes still left in the tray before reopening. Success
  requires a track title and Spotify audio in two consecutive checks.
- Both use a 60-second recovery cooldown and bounded retries. Windows audio
  checks use the default output device; per-app output routing may prevent
  verification. The detailed rules and acceptance checks are in
  [the testing guide](windows/TESTING.md).

## Requirements

| | macOS | Windows |
|---|---|---|
| Desktop OS | macOS 12 or newer | Windows 10/11; version-specific live checks pending |
| Spotify | Desktop app; local baseline is 1.2.85.519 | Desktop installer or Microsoft Store app |
| Build tools | Xcode Command Line Tools | Python 3.10+ with Tk, included in the standard python.org installer |
| Spotify permission | Allow Automation control when prompted | Run the helper in the same user session as Spotify |

For setup with an AI coding agent, ask one with local terminal access to read
this README and [AGENT_README.md](AGENT_README.md).

## Download packages

Release name: **version-1.0** (application version 1.0.0).

Packaging produces one archive per platform under `releases/`:

- `Spotify-Control-macOS.zip`: a universal Apple Silicon/Intel app, installer,
  LaunchAgent template, instructions and license. Extract it and open
  `Install Spotify Control.command`. It backs up an existing helper first.
- `Spotify-Control-Windows.zip`: the standalone x64 executable, instructions
  and license. Extract it and open `Spotify-Control.exe`; no Python is required.

Both default to **Open + Hide**. Existing explicit preferences are preserved.
The Mac package is built locally with `macos/Package Spotify Control.command`;
the Windows package is built by the PowerShell builder on Windows or by CI.
Generated archives stay out of Git. The builds are unsigned/not notarized for
public distribution; they contain the license and creator credit.

## Build and install

### macOS

Build from the repository root:

```bash
./"macos/Build Spotify Control.command"
```

The script compiles, runs the built-in regression checks, and ad-hoc signs
`macos/build/Spotify Control.app`. It also generates a LaunchAgent with your home
path. Building does not replace or start the installed helper.

If you already have a helper installed, follow the backup and replacement plan
in [Testing](#testing) first. For installation, stop its LaunchAgent if loaded:

```bash
launchctl bootout "gui/$(id -u)/com.user.spotifyadmute"
```

A “service not found” result means it was not loaded. Then install the new build:

```bash
mkdir -p "$HOME/Applications" "$HOME/Library/LaunchAgents" \
  "$HOME/Library/Application Support/Spotify Control"
ditto "macos/build/Spotify Control.app" "$HOME/Applications/Spotify Control.app"
cp macos/build/com.user.spotifyadmute.plist "$HOME/Library/LaunchAgents/"
launchctl enable "gui/$(id -u)/com.user.spotifyadmute"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.user.spotifyadmute.plist"
```

Use the **generated plist in `macos/build/`**, not the source template. Open
Spotify normally. Allow Spotify Control to control it when macOS prompts, or
use System Settings → Privacy & Security → Automation. Accessibility permission
is not required. The app is locally signed, not notarized.

### Windows

Run from the repository root:

```powershell
py -m venv windows/.venv
windows/.venv/Scripts/python.exe -m pip install -r windows/requirements.txt
windows/.venv/Scripts/python.exe windows/spotify_ad_blocker.py
```

The dashboard uses restart recovery with **Open + Hide** selected by default.
Previously saved explicit choices are retained. From `windows/`, use
these options with `.venv/Scripts/python.exe spotify_ad_blocker.py`:

| Option | Behavior |
|---|---|
| `--interval 2` | Check every 2 seconds; choices are 1, 2, 5 or 10 |
| `--headless` | Run with the helper enabled, without a dashboard; Ctrl+C stops it |
| `--diagnose` | Report window, title, audio sessions and detection without changing Spotify |
| `--mode mute` | Mute confirmed ads instead of restarting; restore sessions muted by this helper |
| `--reopen hide`, `stay` or `lyrics` | Override the saved reopening mode |
| `--check-ui` | Exercise a temporary sample dashboard and exit; used by the package checks |
| `--log PATH` | Choose another rotating log location |

To build a standalone Windows executable:

```powershell
powershell -ExecutionPolicy Bypass -File "windows/Build Spotify Control.ps1"
```

The script runs the tests before packaging `windows/dist/Spotify-Control.exe`,
then runs read-only diagnostics and a simulated UI check of that executable. The output includes
the license and README; Python is not needed on the destination computer. The
executable is unsigned. To start it at login, put a shortcut in the folder opened
by `Win + R` → `shell:startup`.

## Logs, stopping and uninstalling

| | macOS | Windows |
|---|---|---|
| Logs/settings | `~/Library/Application Support/Spotify Control/`; settings in macOS user defaults | `%LOCALAPPDATA%\Spotify Control\` |
| Stop now | `launchctl bootout "gui/$(id -u)/com.user.spotifyadmute"` | Choose Quit helper in the tray menu, or Ctrl+C in headless terminal mode |
| Prevent login startup | `launchctl disable "gui/$(id -u)/com.user.spotifyadmute"` | Remove the Startup-folder shortcut |
| Uninstall after stopping | Remove the helper app and its LaunchAgent | Remove the executable and Startup shortcut |

You can retain or remove the helper's logs and settings separately.

## Queue problems: downgrade to Spotify 1.2.85.519

Newer Spotify Desktop versions can clear your queue when the app restarts after
an ad. In my own use on macOS, **Spotify 1.2.85.519** keeps the queue through
restarts, so that's the version to downgrade to if your queue keeps getting
wiped. No Windows version has been checked yet; Windows mute mode
(`--mode mute`) avoids the problem because it never restarts Spotify.

To downgrade, using a trusted older Spotify installer or app backup:

1. Save the queued tracks to a playlist, keep your current installer/app backup,
   and stop Spotify Control and Spotify.
2. **macOS:** restore your older `Spotify.app` to Applications. **Windows:**
   uninstall the current desktop app through Settings → Apps, then run the older
   desktop installer. Microsoft Store installation does not offer a version
   picker for this process.
3. Check that Spotify's About/version information shows **1.2.85.519** before
   restarting the helper.
4. Test with a short queue first. Restore your saved app/installer if the older
   version cannot sign in or play. Reinstalling can require downloading offline
   content again; see [Spotify's reinstall guide](https://support.spotify.com/us/article/reinstall-spotify/).

This repository supplies no Spotify installer and does not pin updates for you,
so turn off or block Spotify updates if you want to stay on 1.2.85.519. Older
versions miss later fixes, and Spotify can change this behavior at any time.

## Testing

Build and run the Mac self-tests with its build command. Run the portable
Windows suite from the repository root:

```bash
python3.12 -m unittest discover -s windows/tests -v
```

Use Python 3.10+ if your executable has a different name. Windows-only native
tests skip on other OSes; dashboard tests skip without Tk or a graphical display.
Passing these checks does not prove live ad skipping.

The device test sequence is: record the installed version, back up its app,
LaunchAgent and settings, build and run regression checks, stop the old helper,
install the candidate, and confirm only one helper is running. Test controls,
paused playback, actual ads, queue retention, hide/lyrics behavior where
available, and rollback before replacing a daily-use installation permanently.

The [Windows workflow](.github/workflows/windows.yml) runs tests and builds on a
GitHub-hosted Windows machine. It uploads the executable and accompanying
license/docs. A separate interactive Windows 11 machine or VM, with Spotify
signed in, is required to verify real ads, audio, tray behavior and queues. See
[the test plan and verification limits](windows/TESTING.md).

### Validation and remaining limits

On November 16, 2026, the Windows build and tests passed
on Windows Server 2025 x64 with Python 3.12: 94 tests passed and the non-Windows
error-path test skipped. The standalone executable also passed read-only
diagnostics and its temporary dashboard check. macOS universal build, signature
and mockup self-tests passed locally. These results cover simulated playback;
live Spotify ads, hardware audio, queue retention and lyrics remain unverified.

The portable suite covers all three modes, hidden-launch requests, verified
window hiding, lyrics error handling, daily refresh, settings migration, tray
callbacks and UI controls. Windows-only integration tests use a disposable
native media window to exercise actual quit, launch, Play and Hide messages
without a Spotify account. Hardware audio is simulated in those integration
cases; separate adapter checks validate the audio API imports and protocol calls.

Real Spotify can change its ads, metadata or lyrics routes. Native simulated
passes do not prove every Spotify version, queue, audio device or server-side ad
will behave identically. Keep those limits in mind when evaluating a release.

Preview checks:

```bash
npm run test:mockup
python3.12 -m unittest discover -s windows/tests -v
"macos/build/Spotify Control.app/Contents/MacOS/SpotifyControl" --self-test-mockup
```

The last command requires a built Mac app and a graphical session. It exercises
the mock controls and checks that helper settings, polling and shell commands
remain isolated.

## License and credit

Created by [Bubby3999](https://github.com/Bubby3999). Published uses, redistributed
copies and improved or modified versions must retain the license and credit the
original creator. See [LICENSE](LICENSE) for the custom attribution terms.

Contacts:

- [LinkedIn](https://www.linkedin.com/in/loukikgarine)
- Email: loukikram.garine@gmail.com
