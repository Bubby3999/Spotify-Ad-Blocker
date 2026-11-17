# Cross-platform validation and Windows test strategy

## Implemented behavior

Both platforms offer Open + Hide (default), Open + Stay, Open + Stay + Lyrics,
Play/Pause, enable/disable, 1/2/5/10-second intervals, manual and daily refresh,
Instructions and saved preferences. Windows has a system-tray dashboard launcher;
macOS uses its menu-bar launcher. Closing a live dashboard leaves its helper
running. The UI mockup exits on close and has no Spotify connection.

Explicit saved choices are preserved. New installations and invalid/missing
reopening preferences default to Hide. Existing Windows two-field settings files
migrate to the expanded format without losing interval or enabled choices.

Mac recovery now requires legitimate content after reopening, rather than any
playing state. Already-hidden Spotify is accepted instead of generating a false
hide warning. Windows requests hidden startup, hides the discovered window and
checks native visibility; a hide failure is reported separately from playback.
Lyrics use Spotify's internal route on both platforms and remain experimental.

## Portable tests

Run from the repository root:

```sh
npm run test:mockup
python3.12 -m unittest discover -s windows/tests -v
```

The suite covers detection, pause/unknown-media safety, confirmation, cooldowns,
retry budgets, process exit races, permission errors, reopening modes, hide and
lyrics failures, daily-refresh timing, settings migration, tray dispatch, GUI
controls, temporary mockup settings and clean worker shutdown. The mockup never
imports the Windows Spotify adapter or audio dependencies.

Results on November 16, 2026:

- macOS: 88 Python tests passed, seven native Windows cases skipped; the three
  Node launcher tests and universal Mac build/signature/mockup self-tests passed.
- Windows runner:
  Windows Server 2025 x64, Python 3.12.10; 94 tests passed, one non-Windows
  error-path case skipped. All native fixture and tray cases passed. The built
  executable passed read-only diagnostics and the sample dashboard check.

The Windows runner does not establish live Windows 10/11 Spotify compatibility.

## Native Windows replication without a Spotify account

`tests/fixtures/fake_spotify.py` creates a disposable native media window in a
separate Python process. It exposes a Spotify-style window class and handles
real Windows Play/Pause and close messages. The window has its own message loop,
so the adapter's asynchronous hide request can be observed normally.

`tests/test_windows_workflow.py` exercises real process shutdown, launch, window
discovery, command delivery, hiding, two-ad confirmation and forced termination
when window close is ignored. Every process operation is restricted to the
child created by that test; it cannot capture an installed Spotify instance.

Audio activity is deliberately simulated by a property on the test window. The
fixture does not generate Spotify ads, log into an account, call Spotify's
servers, or prove a hardware audio device works. Separate tests cover pycaw
imports/session filtering and the exact launch/lyrics protocol arguments. This
combination verifies the integration our program controls without asking the
user to own a Windows PC.

The existing native tests also check pointer-width-safe window bindings,
message delivery to a real test window, session-local duplicate-instance
protection, actual tray icon startup/hiding/shutdown and read-only observation
with installed dependencies. Test cleanup retains native callback objects until
their windows are destroyed, and follows Windows' child interpreter processes.

## Automated Windows build and downloadable package

Run on Windows with Python 3.10+ on PATH:

```powershell
powershell -ExecutionPolicy Bypass -File "windows/Build Spotify Control.ps1"
```

The script creates an isolated environment, installs dependencies and runs the
suite. It packages the GUI app, checks the packaged imports with `--diagnose`,
and exercises the packaged dashboard with `--check-ui` using temporary sample
playback. The latter checks controls, mode changes and bundled instructions,
then exits automatically. Neither smoke check controls the user's Spotify.

On success it creates `releases/Spotify-Control-Windows.zip` with the executable,
START-HERE instructions, detailed instructions and license. It also records the
archive checksum. No Python/npm installation is needed on the recipient's PC.
The executable is unsigned.

The GitHub Windows workflow runs the same pipeline. It retains test/diagnostic
logs and uploads the final ZIP and checksum. The source must first be uploaded
to an accessible repository. Native test and package results are recorded only
after that workflow has actually completed; a prepared workflow is not a pass.

## Mac package checks

`macos/Package Spotify Control.command` builds both arm64 and x86_64 slices,
runs built-in regression checks, signs the app locally, checks the signature,
and creates `releases/Spotify-Control-macOS.zip`. The archive includes a generic
installer/plist, instructions and license. The installer resolves each user's
home directory when run and backs up an existing helper. Building the archive
does not replace the developer's installed helper or touch Spotify.

Extract the ZIP into a fresh directory and verify the extracted signature,
both architecture slices, resources and `--self-test` behavior. Run
`--self-test-mockup` in a graphical session to verify settings/log/command
isolation. The Mac package is ad-hoc signed, not Developer ID notarized.

## What simulated tests cannot establish

Live Spotify may change window classes, metadata, protocol support or ad
behavior. An account-free fake cannot reproduce those server-side changes.
Real-account playback, queue retention, per-app audio routing, lyrics display
and focus behavior remain version/device-dependent. Passing native simulations
should be described as such, rather than as universal ad-blocking validation.

If a Windows environment with a signed-in account becomes available, record OS,
architecture, Spotify version/install type and audio endpoint, then check:

1. Read-only diagnosis sees the expected window, title and audio sessions.
2. Each mode resumes a song after an actual ad; Hide leaves no visible window,
   and lyrics opens only where Spotify supports it.
3. Paused ads, normal songs, unknown media and manually closed Spotify are left
   alone. Other apps retain their audio.
4. Tray reopen/quit, saved settings, all intervals, daily refresh, Instructions
   and login startup behave correctly.
5. Slow launches, audio disconnects and persistent ads produce bounded retries
   and accurate errors while the dashboard stays responsive.
6. Compare a short saved queue before/after recovery and test rollback of the
   helper installation. Restarts can lose the queue.

## References

- [Microsoft window hiding](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-showwindowasync)
  and [visibility checks](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-iswindowvisible).
- [Microsoft WM_APPCOMMAND](https://learn.microsoft.com/en-us/windows/win32/inputdev/wm-appcommand): targeted media commands.
- [pystray framework integration](https://pystray.readthedocs.io/en/latest/usage.html): Windows tray callbacks and detached event loop.
- [Python os.startfile](https://docs.python.org/3.12/library/os.html#os.startfile): launch hints and URI dispatch.
- [PyInstaller target-OS builds](https://pyinstaller.org/en/stable/operating-mode.html).
