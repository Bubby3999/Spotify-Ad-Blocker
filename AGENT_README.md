# Agent setup guidance

Read README.md first. Spotify Control targets Spotify Desktop on macOS and
Windows. An installation agent needs local file and terminal access.

## Source and checks

- UI review: `npm run mockup` opens the native platform dashboard with sample
  data. `npm run mockup -- --windows` previews the Tk dashboard on a Mac too.
  This is a Node launcher with no npm dependencies. The Mac mockup blocks shell
  commands and uses memory-only settings; the Windows mockup never loads the
  Windows Spotify adapter and uses temporary settings files. It can coexist
  with an installed helper because it does not watch Spotify.

- macOS: `macos/SpotifyControl.swift` is the recovered native app source.
  Run `macos/Build Spotify Control.command` to build, run its self-tests and sign
  the candidate. App and resolved LaunchAgent paths are generated in
  `macos/build/`. Do not install the source plist template directly: launchd does
  not expand home-directory variables in it.
- Windows: install `windows/requirements.txt` in a virtual environment, run
  `python -m unittest discover -s windows/tests -v`, and launch
  `python windows/spotify_ad_blocker.py`. Restart is the default; mute is an
  explicit option. `--diagnose` observes Spotify without controlling it.
- Windows packaging: run `windows/Build Spotify Control.ps1` on Windows, or use
  `.github/workflows/windows.yml` after the reviewed source is in an accessible
  GitHub repository. Review the native tests, packaged diagnostics and artifacts.
- See `windows/TESTING.md` for platform limits and interactive Windows checks.
  Mocked tests and a successful package build do not prove live ad skipping.

## Existing installations

Locate the running app, LaunchAgent/startup shortcut, settings and original
source before replacing anything. Back up the current installation and settings,
stop the old helper, install the tested candidate, and verify a single monitor
is running. Preserve a working rollback. Do not run two helpers against Spotify,
including Mac copies started with different data directories.

Both versions rely on Spotify remembering its track and queue; neither restores
a saved track URI or position. Restarts can lose the queue. The Mac app requests
normal quit; the Windows version terminates tray processes left after closing.
Both platforms provide Open + Hide (default), Open + Stay, lyrics requests, daily refresh and Instructions. Lyrics remain experimental. Windows uses a tray icon; Mac uses a menu-bar icon.

## Public repository hygiene

Keep source, tests, build scripts, .gitignore, README, LICENSE, this file and CI
workflows in Git. Personal GitHub setup notes, LOCAL_TEST_PLAN.md, local-notes,
local-test-results, compiled applications, caches, logs and virtual environments
are ignored. Do not copy private Notion links, personal paths, Spotify account
files, old Spotify installers or raw listening history into the public repo.

Retain the Bubby3999 copyright and attribution requirement. Include LICENSE and
README with distributed Windows artifacts and LICENSE in the Mac app bundle.
Do not change Spotify's installation, downgrade it or alter its update settings
as an incidental part of helper setup.

## Packaging

Run `macos/Package Spotify Control.command` to build a universal Mac ZIP. The Windows PowerShell builder creates the Windows ZIP after tests and packaged diagnostics/UI checks. Generated downloads live in `releases/` and are ignored by Git. Native Windows workflow tests target only disposable child processes; audio is simulated and no Spotify login is needed.
