#!/bin/sh
# Builds macos/build/EchoFox.app and signs it. Run it with: open macos/build/EchoFox.app
# Usage: macos/build-app.sh [--bundle] [--dmg]
#   no flag   the app alone, for work on this Mac: the dictation server runs from the repository (server/launchd.sh).
#   --bundle  build/bundle/EchoFox.app, the app with everything it runs (docs/design/7-distribution.md): the server's code in
#             Contents/Resources/server, Python with the server's packages in Contents/Resources/python, and
#             llama-server in Contents/Resources/llama, at the versions of pins.sh. Such an app installs the
#             server's launchd agent itself.
#   --dmg     also build/EchoFox.dmg with the app (implies --bundle).
# It signs with the certificate $ECHOFOX_SIGN (default "EchoFox Dev", a self-signed code-signing certificate
# in the login keychain), so that the app's code requirement is its identifier and that certificate, the same for
# every build, and macOS keeps its permissions. Without the certificate it signs ad hoc: then the requirement is the
# hash of the build, and after a rebuild macOS refuses the Accessibility it granted (tccd, 2026-10-15). A Developer
# ID certificate also gets the hardened runtime, which notarization needs.
set -eu
cd "$(dirname "$0")"
bundle=false dmg=false
for a in "$@"; do
  case $a in
    --bundle) bundle=true ;;
    --dmg) bundle=true dmg=true ;;
    *) echo "usage: $0 [--bundle] [--dmg]" >&2; exit 2 ;;
  esac
done

swift build -c release --product EchoFox
app=build/EchoFox.app
$bundle && app=build/bundle/EchoFox.app  # apart from the app of this Mac's work, which must not install the agent
rm -rf "$app"
mkdir -p "$app/Contents/MacOS"
cp .build/release/EchoFox "$app/Contents/MacOS/"
cp app/Info.plist "$app/Contents/"
# The fox of the first start, and the app icon (macos/art/README.md): Icon Composer's app/EchoFox.icon, compiled by
# actool of Xcode into Assets.car, with EchoFox.icns for older macOS. Without Xcode, the prebuilt app/EchoFox.icns,
# which macOS 26 and later shows small on a gray tile.
mkdir -p "$app/Contents/Resources"
cp app/echofox-welcome.png "$app/Contents/Resources/"
xcode=$(xcode-select -p)
case $xcode in *CommandLineTools*) xcode=/Applications/Xcode.app/Contents/Developer ;; esac
if DEVELOPER_DIR=$xcode xcrun --find actool >/dev/null 2>&1; then
  DEVELOPER_DIR=$xcode xcrun actool app/EchoFox.icon --compile "$app/Contents/Resources" --platform macosx \
    --minimum-deployment-target 13.0 --app-icon EchoFox --output-partial-info-plist build/icon-info.plist >/dev/null
  [ -f "$app/Contents/Resources/Assets.car" ] || { echo "actool made no Assets.car" >&2; exit 1; }
else
  echo "no actool (Xcode): the prebuilt icon, on a gray tile in macOS 26 and later" >&2
  cp app/EchoFox.icns "$app/Contents/Resources/"
fi

if $bundle; then
  . ./pins.sh
  cache=.cache
  res=$app/Contents/Resources
  mkdir -p "$cache" "$res"

  # Python, checked against its pinned SHA-256, with the server's packages
  tarball=$cache/$PYTHON_FILE
  [ -f "$tarball" ] || { curl -fL --retry 3 -o "$tarball.tmp" "$PYTHON_URL" && mv "$tarball.tmp" "$tarball"; }
  echo "$PYTHON_SHA256  $tarball" | shasum -a 256 -c - >/dev/null
  tar -xzf "$tarball" -C "$res"
  "$res/python/bin/python3" -m pip install --quiet --no-cache-dir --disable-pip-version-check \
    -r ../server/requirements.txt

  # The server's code, without its tests and the tools of its development
  mkdir -p "$res/server"
  rsync -a --exclude '__pycache__' --exclude '.venv' --exclude 'test_*.py' --exclude 'fakes.py' \
    --exclude 'sandbox.py' --exclude 'testdata' --exclude 'try_wav.py' --exclude 'test_server.sh' \
    --exclude 'launchd.sh' ../server/ "$res/server/"

  # llama-server from its pinned commit, with Metal, as one binary
  src=$cache/llama.cpp-$LLAMA_COMMIT
  if [ ! -x "$src/build/bin/llama-server" ]; then
    rm -rf "$src"
    git init -q "$src"
    git -C "$src" fetch -q --depth 1 "$LLAMA_REPO" "$LLAMA_COMMIT"
    git -C "$src" checkout -q FETCH_HEAD
    # No HTTPS (LLAMA_OPENSSL): it serves 127.0.0.1 only, and OpenSSL would come from Homebrew, not from macOS.
    cmake -S "$src" -B "$src/build" -DCMAKE_BUILD_TYPE=Release -DGGML_METAL=ON -DBUILD_SHARED_LIBS=OFF \
      -DLLAMA_CURL=OFF -DLLAMA_OPENSSL=OFF -DLLAMA_BUILD_TESTS=OFF >/dev/null
    cmake --build "$src/build" --target llama-server -j >/dev/null
  fi
  mkdir -p "$res/llama"
  cp "$src/build/bin/llama-server" "$res/llama/"

  # The bundle runs on a Mac without Homebrew: no executable or library in it may load one from there.
  foreign=$(find "$res" -type f \( -perm -u+x -o -name '*.so' -o -name '*.dylib' \) | while IFS= read -r f; do
    if file -b "$f" | grep -q Mach-O; then otool -L "$f" | tail -n +2 | grep -E '^[[:space:]]+/(opt/homebrew|usr/local)/' |
      sed "s|^|$f: |"; fi
  done)
  if [ -n "$foreign" ]; then echo "libraries from outside macOS and the bundle:" >&2; echo "$foreign" >&2; exit 1; fi
fi

identity=${ECHOFOX_SIGN:-EchoFox Dev}
if security find-identity -p codesigning | grep -q "\"$identity\""; then
  options=""
  case $identity in "Developer ID"*) options="--options runtime --timestamp" ;; esac
  # Inside out: every executable and library in the bundle, then the app
  if $bundle; then
    find "$app/Contents/Resources" -type f \( -perm -u+x -o -name '*.so' -o -name '*.dylib' \) |
      while IFS= read -r f; do
        if file -b "$f" | grep -q Mach-O; then codesign --force --sign "$identity" $options "$f"; fi
      done
  fi
  codesign --force --sign "$identity" $options --entitlements app/entitlements.plist "$app"
else
  echo "no certificate \"$identity\": signing ad hoc; macOS will ask for the permissions again" >&2
  codesign --force --deep --sign - "$app"
fi
codesign -dr - "$app" 2>&1 | tail -1

if $dmg; then
  rm -f build/EchoFox.dmg
  hdiutil create -quiet -volname "EchoFox" -srcfolder "$app" -ov -format UDZO build/EchoFox.dmg
  # A Developer ID signs the dmg too, so that Gatekeeper checks the file that was downloaded
  case $identity in "Developer ID"*) codesign --force --sign "$identity" --timestamp build/EchoFox.dmg ;; esac
  echo build/EchoFox.dmg
fi
echo "$app"
