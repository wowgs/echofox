#!/bin/sh
# Builds macos/build/LocalVoice.app and signs it ad hoc. Run it with: open macos/build/LocalVoice.app
# An ad hoc signature changes with every build, so macOS may ask for the permissions again after a rebuild.
set -eu
cd "$(dirname "$0")"
swift build -c release --product LocalVoice
app=build/LocalVoice.app
rm -rf "$app"
mkdir -p "$app/Contents/MacOS"
cp .build/release/LocalVoice "$app/Contents/MacOS/"
cp app/Info.plist "$app/Contents/"
codesign --force --sign - "$app"
echo "$app"
