param([string]$Python = "python")

$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") { throw "Build this executable on Windows." }
Push-Location $PSScriptRoot
try {
    & $Python -c "import sys; assert sys.version_info >= (3, 10), 'Python 3.10+ required'"
    if ($LASTEXITCODE -ne 0) { throw "Install Python 3.10+ and enable its PATH option." }
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the build environment." }
    $BuildPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    & $BuildPython -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw "Could not install build dependencies." }
    New-Item -ItemType Directory -Force -Path build | Out-Null
    $TestLog = Join-Path $PSScriptRoot "build\test-results.txt"
    $Tests = Start-Process -FilePath $BuildPython -ArgumentList @("-X", "faulthandler", "-m", "unittest", "discover", "-s", "tests", "-v") -RedirectStandardError $TestLog -Wait -NoNewWindow -PassThru
    Get-Content $TestLog | Write-Host
    if ($Tests.ExitCode -ne 0) { throw "Tests failed (exit $($Tests.ExitCode)); the executable was not built." }
    & $BuildPython -m PyInstaller --noconfirm --clean --onefile --windowed --name Spotify-Control --collect-submodules pycaw --hidden-import comtypes.stream --hidden-import pystray._win32 --add-data "Spotify Control Instructions.md;." spotify_ad_blocker.py
    if ($LASTEXITCODE -ne 0) { throw "Packaging failed." }
    $Executable = Join-Path $PSScriptRoot "dist\Spotify-Control.exe"
    $DiagnosticLog = Join-Path $PSScriptRoot ("build\diagnostic-" + [guid]::NewGuid().ToString("N") + ".log")
    $Diagnostic = Start-Process -FilePath $Executable -ArgumentList @("--diagnose", "--log", "`"$DiagnosticLog`"") -PassThru
    if (-not $Diagnostic.WaitForExit(30000)) {
        $Diagnostic.Kill()
        throw "Packaged dependency check timed out."
    }
    $Diagnostic.Refresh()
    if ($Diagnostic.ExitCode -ne 0) { throw "Packaged dependency check failed. See $DiagnosticLog" }
    if (-not (Select-String -Path $DiagnosticLog -Pattern "Read-only diagnostics" -Quiet)) {
        throw "The executable did not produce a diagnostic report."
    }
    $UiLog = Join-Path $PSScriptRoot ("build\ui-check-" + [guid]::NewGuid().ToString("N") + ".log")
    $UiCheck = Start-Process -FilePath $Executable -ArgumentList @("--check-ui", "--log", "`"$UiLog`"") -PassThru
    if (-not $UiCheck.WaitForExit(30000)) {
        $UiCheck.Kill()
        throw "Packaged dashboard check timed out."
    }
    $UiCheck.Refresh()
    if ($UiCheck.ExitCode -ne 0 -or -not (Select-String -Path $UiLog -Pattern "Dashboard startup check passed" -Quiet)) {
        throw "Packaged dashboard check failed. See $UiLog"
    }
    Copy-Item (Join-Path $PSScriptRoot "..\LICENSE") (Join-Path $PSScriptRoot "dist\LICENSE")
    Copy-Item (Join-Path $PSScriptRoot "..\README.md") (Join-Path $PSScriptRoot "dist\README.md")
    Copy-Item "START-HERE.txt" "dist\START-HERE.txt"
    Copy-Item "Spotify Control Instructions.md" "dist\Spotify Control Instructions.md"
    $ReleaseDirectory = Join-Path $PSScriptRoot "..\releases"
    New-Item -ItemType Directory -Force -Path $ReleaseDirectory | Out-Null
    $Archive = Join-Path $ReleaseDirectory "Spotify-Control-Windows.zip"
    Compress-Archive -Path "dist\Spotify-Control.exe", "dist\LICENSE", "dist\README.md", "dist\START-HERE.txt", "dist\Spotify Control Instructions.md" -DestinationPath $Archive -Force
    (Get-FileHash -Path $Archive -Algorithm SHA256).Hash | Set-Content ($Archive + ".sha256")
    Write-Host "Built and smoke-tested: $Executable"
    Write-Host "Download package: $Archive"
    Write-Host "Live Spotify ad skipping still needs an interactive Windows playback test."
}
finally {
    Pop-Location
}
