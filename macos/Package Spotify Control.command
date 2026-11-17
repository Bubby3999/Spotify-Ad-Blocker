#!/bin/bash
set -euo pipefail
source_dir="$(cd "$(dirname "$0")" && pwd)"
root_dir="$(cd "$source_dir/.." && pwd)"
"$source_dir/Build Spotify Control.command" --universal
stage="$(mktemp -d "$source_dir/build/package.XXXXXX")"
payload="$stage/Spotify Control"
mkdir -p "$payload" "$root_dir/releases"
ditto "$source_dir/build/Spotify Control.app" "$payload/Spotify Control.app"
cp "$source_dir/Install Spotify Control.command" "$payload/"
cp "$source_dir/com.user.spotifyadmute.plist" "$payload/"
cp "$root_dir/LICENSE" "$payload/LICENSE"
cp "$source_dir/START-HERE.txt" "$payload/START-HERE.txt"
chmod +x "$payload/Install Spotify Control.command"
codesign --verify --deep --strict "$payload/Spotify Control.app"
lipo "$payload/Spotify Control.app/Contents/MacOS/SpotifyControl" -verify_arch arm64 x86_64
archive="$root_dir/releases/Spotify-Control-macOS.zip"
ditto -c -k --sequesterRsrc --keepParent "$payload" "$archive"
(cd "$root_dir/releases" && shasum -a 256 "Spotify-Control-macOS.zip") > "$archive.sha256"
printf 'Download package: %s\n' "$archive"
