#!/bin/bash
set -euo pipefail

source_dir="$(cd "$(dirname "$0")" && pwd)"
build_dir="$source_dir/build"
app="$build_dir/Spotify Control.app"
binary="$app/Contents/MacOS/SpotifyControl"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources" "$build_dir/module-cache"
cp "$source_dir/Info.plist" "$app/Contents/Info.plist"
cp "$source_dir/Spotify Control Instructions.md" "$app/Contents/Resources/"
cp "$source_dir/../LICENSE" "$app/Contents/Resources/LICENSE"

compiler_flags=(-sdk "$(xcrun --sdk macosx --show-sdk-path)")
compiler_dir="$(dirname "$(xcrun --find swiftc)")"
swift_headers="$compiler_dir/../include/swift"
# Some CLT installs define SwiftBridging twice; mask the duplicate locally.
if [[ -f "$swift_headers/module.modulemap" && -f "$swift_headers/bridging.modulemap" ]] && \
   grep -q 'module SwiftBridging' "$swift_headers/module.modulemap" && \
   grep -q 'module SwiftBridging' "$swift_headers/bridging.modulemap"; then
  swift_headers="$(cd "$swift_headers" && pwd)"
  printf '// The SwiftBridging module is supplied by bridging.modulemap.\n' > "$build_dir/empty.modulemap"
  overlay="$build_dir/toolchain-overlay.plist"
  plutil -create xml1 "$overlay"
  plutil -insert version -integer 0 "$overlay"
  plutil -insert roots -array "$overlay"
  plutil -insert roots.0 -dictionary "$overlay"
  plutil -insert roots.0.type -string file "$overlay"
  plutil -insert roots.0.name -string "$swift_headers/module.modulemap" "$overlay"
  plutil -insert roots.0.external-contents -string "$build_dir/empty.modulemap" "$overlay"
  plutil -convert json -o "$build_dir/toolchain-overlay.json" "$overlay"
  compiler_flags+=(-vfsoverlay "$build_dir/toolchain-overlay.json")
fi

architectures=("$(uname -m)")
if [[ "${1:-}" == "--universal" ]]; then architectures=(arm64 x86_64); fi
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--universal" ) ]]; then
  printf 'Usage: Build Spotify Control.command [--universal]\n' >&2
  exit 1
fi
objects=()
for architecture in "${architectures[@]}"; do
  output="$build_dir/SpotifyControl-$architecture"
  (cd "$source_dir"
  xcrun --sdk macosx swiftc -swift-version 5 \
    -target "$architecture-apple-macosx12.0" \
    -module-cache-path "$build_dir/module-cache" \
    -file-prefix-map "$source_dir=." \
    "${compiler_flags[@]}" \
    "SpotifyControl.swift" -framework AppKit -o "$output")
  objects+=("$output")
done
if [[ ${#objects[@]} -eq 2 ]]; then
  lipo -create "${objects[@]}" -output "$binary"
else
  cp "${objects[0]}" "$binary"
fi
"$binary" --self-test
codesign --force --sign - --options runtime \
  --entitlements "$source_dir/BuildSupport/entitlements.plist" "$app"
codesign --verify --deep --strict "$app"

# LaunchAgent files do not expand $HOME; resolve paths in the local build output.
agent="$build_dir/com.user.spotifyadmute.plist"
cp "$source_dir/com.user.spotifyadmute.plist" "$agent"
plutil -remove ProgramArguments "$agent"
plutil -insert ProgramArguments -array "$agent"
plutil -insert ProgramArguments.0 -string "$HOME/Applications/Spotify Control.app/Contents/MacOS/SpotifyControl" "$agent"
plutil -replace StandardOutPath -string "$HOME/Library/Application Support/Spotify Control/service.log" "$agent"
plutil -replace StandardErrorPath -string "$HOME/Library/Application Support/Spotify Control/service.log" "$agent"
plutil -lint "$agent"
if [[ "$(plutil -extract ProgramArguments raw "$agent")" != 1 ]]; then
  printf 'Invalid LaunchAgent: expected exactly one executable argument.\n' >&2
  exit 1
fi
printf 'Built, tested, and signed: %s\n' "$app"
printf 'The installed helper has not been replaced. See README.md for installation.\n'
