#!/bin/bash
set -euo pipefail

source_dir="$(cd "$(dirname "$0")" && pwd)"
source_app="$source_dir/Spotify Control.app"
target_app="$HOME/Applications/Spotify Control.app"
agents="$HOME/Library/LaunchAgents"
data_dir="$HOME/Library/Application Support/Spotify Control"
label="gui/$(id -u)/com.user.spotifyadmute"
backup="$data_dir/Backups/$(date +%Y%m%d-%H%M%S)-$$"
agent="$agents/com.user.spotifyadmute.plist"

codesign --verify --deep --strict "$source_app"
mkdir -p "$HOME/Applications" "$agents" "$backup"
if [[ -f "$agent" ]]; then cp "$agent" "$backup/com.user.spotifyadmute.plist"; fi
defaults export com.user.spotifycontrol "$backup/settings.plist" 2>/dev/null || true

if launchctl print "$label" >/dev/null 2>&1; then launchctl bootout "$label"; fi
# Stop a manually opened helper too; this never sends any command to Spotify.
osascript -e 'if application id "com.user.spotifycontrol" is running then tell application id "com.user.spotifycontrol" to quit'
if [[ -d "$target_app" ]]; then mv "$target_app" "$backup/Spotify Control.app"; fi
printf 'Previous helper backup: %s\n' "$backup"
ditto "$source_app" "$target_app"
codesign --verify --deep --strict "$target_app"
cp "$source_dir/com.user.spotifyadmute.plist" "$agent"
plutil -remove ProgramArguments "$agent"
plutil -insert ProgramArguments -array "$agent"
plutil -insert ProgramArguments.0 -string "$target_app/Contents/MacOS/SpotifyControl" "$agent"
plutil -replace StandardOutPath -string "$data_dir/service.log" "$agent"
plutil -replace StandardErrorPath -string "$data_dir/service.log" "$agent"
plutil -lint "$agent"
launchctl enable "$label"
launchctl bootstrap "gui/$(id -u)" "$agent"
printf '\nInstalled Spotify Control. Open Spotify normally.\n'
printf 'Open + Hide is the default unless you previously saved another mode.\n'
printf 'Previous app, service and settings (when present): %s\n' "$backup"
printf 'Press Return to close this installer.\n'
read -r
