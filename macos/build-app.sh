#!/bin/sh
# Builds macos/build/LocalVoice.app and signs it. Run it with: open macos/build/LocalVoice.app
# It signs with the certificate $LOCAL_VOICE_SIGN (default "Local Voice Dev", a self-signed code-signing certificate
# in the login keychain), so that the app's code requirement is its identifier and that certificate, the same for
# every build, and macOS keeps its permissions. Without the certificate it signs ad hoc: then the requirement is the
# hash of the build, and after a rebuild macOS refuses the Accessibility it granted (tccd, 2026-10-15).
set -eu
cd "$(dirname "$0")"
swift build -c release --product LocalVoice
app=build/LocalVoice.app
rm -rf "$app"
mkdir -p "$app/Contents/MacOS"
cp .build/release/LocalVoice "$app/Contents/MacOS/"
cp app/Info.plist "$app/Contents/"
identity=${LOCAL_VOICE_SIGN:-Local Voice Dev}
if security find-identity -p codesigning | grep -q "\"$identity\""; then
  codesign --force --sign "$identity" "$app"
else
  echo "no certificate \"$identity\": signing ad hoc; macOS will ask for the permissions again" >&2
  codesign --force --sign - "$app"
fi
codesign -dr - "$app" 2>&1 | tail -1
echo "$app"
