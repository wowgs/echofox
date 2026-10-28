#!/bin/sh
# Builds macos/build/EchoFox.app, the app with everything it runs (docs/reference/7-development.md, "The package"): the server's code in
# Contents/Resources/server, Python with the server's packages in Contents/Resources/python, and llama-server in
# Contents/Resources/llama, at the versions of pins.sh. The app starts the server as its child process.
# Usage: macos/build-app.sh [--dmg]
#   --dmg  also build/EchoFox.dmg with the app, the installer window.
# It needs Xcode (actool compiles the icon) and a Developer ID Application identity in the keychains: $ECHOFOX_SIGN
# names it, else the build takes the one Developer ID Application identity it finds. It signs with the hardened
# runtime, which notarization needs.
# The version is the nearest git tag v<major>.<minor>[.<patch>] (CFBundleShortVersionString) and the number of commits
# (CFBundleVersion), so the history must be whole (no shallow clone). The oldest macOS is pins.sh's MACOS_MIN.
set -eu
cd "$(dirname "$0")"
dmg=false
for a in "$@"; do
  case $a in
    --dmg) dmg=true ;;
    *) echo "usage: $0 [--dmg]" >&2; exit 2 ;;
  esac
done
. ./pins.sh

identity=${ECHOFOX_SIGN:-$(security find-identity -v -p codesigning | sed -n 's/.*"\(Developer ID Application: .*\)"$/\1/p')}
case $identity in
  "Developer ID Application: "*) ;;
  *) echo "no Developer ID Application identity (found: ${identity:-none}); name it in ECHOFOX_SIGN" >&2; exit 1 ;;
esac
security find-identity -v -p codesigning | grep -qF "\"$identity\"" || { echo "no signing identity \"$identity\" in the keychains" >&2; exit 1; }
xcode=$(xcode-select -p)
case $xcode in *CommandLineTools*) xcode=/Applications/Xcode.app/Contents/Developer ;; esac
DEVELOPER_DIR=$xcode xcrun --find actool >/dev/null 2>&1 || { echo "no actool: the build needs Xcode" >&2; exit 1; }

[ "$(git rev-parse --is-shallow-repository)" = false ] || { echo "a shallow clone: the version needs the whole history" >&2; exit 1; }
tag=$(git describe --tags --match 'v[0-9]*' --abbrev=0) || { echo "no tag v* in git: no version" >&2; exit 1; }
version=${tag#v} build=$(git rev-list --count HEAD)
echo "$version" | grep -Eq '^[0-9]+(\.[0-9]+){1,2}$' || { echo "the tag $tag is not v<major>.<minor>[.<patch>]" >&2; exit 1; }

# The Sparkle that Package.swift links is the one of pins.sh, whose tools sign the release's feed
grep -q "\"version\" : \"$SPARKLE_VERSION\"" Package.resolved || { echo "Package.resolved's Sparkle is not pins.sh's $SPARKLE_VERSION" >&2; exit 1; }
swift build -c release --product EchoFox
swift build -c release --product echofox-updater-check
app=build/EchoFox.app
rm -rf "$app"
mkdir -p "$app/Contents/MacOS"
cp .build/release/EchoFox "$app/Contents/MacOS/"
# Sparkle, the updater (docs/reference/7-development.md, "Updates"), where the app's rpath finds it. The app is not sandboxed, so
# Sparkle's XPC services are left out (Sparkle's documentation).
mkdir -p "$app/Contents/Frameworks"
ditto .build/release/Sparkle.framework "$app/Contents/Frameworks/Sparkle.framework"
rm -rf "$app/Contents/Frameworks/Sparkle.framework/Versions/B/XPCServices" "$app/Contents/Frameworks/Sparkle.framework/XPCServices"
cp app/Info.plist "$app/Contents/"
# The version and the oldest macOS, which app/Info.plist leaves out. The app gives the version to the server, for its
# log (ServerProcess).
/usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string $version" -c "Add :CFBundleVersion string $build" \
  -c "Add :LSMinimumSystemVersion string $MACOS_MIN" "$app/Contents/Info.plist"
# Sparkle starts with the app's update settings, as it must at the app's launch
.build/release/echofox-updater-check "$app" >/dev/null || { .build/release/echofox-updater-check "$app" >&2; exit 1; }
# The fox of the first start, and the app icon (macos/art/README.md): Icon Composer's app/EchoFox.icon, compiled by
# actool of Xcode into Assets.car, with EchoFox.icns for older macOS
mkdir -p "$app/Contents/Resources"
cp app/echofox-welcome.png "$app/Contents/Resources/"
# actool must write the Info.plist keys of the icon somewhere; app/Info.plist has them (CFBundleIconName)
partial=$(mktemp -t echofox-icon)
DEVELOPER_DIR=$xcode xcrun actool app/EchoFox.icon --compile "$app/Contents/Resources" --platform macosx \
  --minimum-deployment-target "$MACOS_MIN" --app-icon EchoFox --output-partial-info-plist "$partial" >/dev/null
rm -f "$partial"
[ -f "$app/Contents/Resources/Assets.car" ] || { echo "actool made no Assets.car" >&2; exit 1; }

# Python, llama-server and dmgbuild, from the cache (cache-deps.sh makes what is missing)
./cache-deps.sh
cache=.cache
res=$app/Contents/Resources
mkdir -p "$res"

# Python, with the server's packages: wheels only, each checked against its SHA-256 in requirements.txt, as nothing
# else may run while the signing key is in the keychain
tar -xzf "$cache/$PYTHON_FILE" -C "$res"
"$res/python/bin/python3" -m pip install --quiet --no-cache-dir --disable-pip-version-check \
  --require-hashes --only-binary :all: -r ../server/requirements.txt
# pip, which comes with this Python, only installs the packages: the app never installs anything, so pip leaves,
# and so does ensurepip, which is a copy of pip in the standard library
"$res/python/bin/python3" -m pip uninstall --yes --quiet --disable-pip-version-check pip
rm -rf "$res"/python/lib/python3.*/ensurepip
left=$(find "$res/python" \( -name pip -o -name 'pip-*' -o -name 'pip3*' -o -name ensurepip \) -print)
[ -z "$left" ] || { echo "pip is still in the bundle: $left" >&2; exit 1; }

# The server's code, without its tests and the tools of its development
mkdir -p "$res/server"
rsync -a --exclude '__pycache__' --exclude '.venv' --exclude 'test_*.py' --exclude 'fakes.py' \
  --exclude 'sandbox.py' --exclude 'testdata' --exclude 'try_wav.py' --exclude 'test_server.sh' \
  --exclude 'which_session.py' ../server/ "$res/server/"
# The bytecode of the server, the standard library (the stripped Python has none) and the packages, so that Python
# finds it and writes nothing into the signed bundle (the agent also sets PYTHONDONTWRITEBYTECODE); it also cuts
# the server's imports from about 0.26 s to 0.07 s (M5, 2026-10-26). Each .pyc carries its source's hash, not a time
# that a copy may change.
"$res/python/bin/python3" -m compileall -q -j 0 --invalidation-mode checked-hash "$res/python/lib" "$res/server"

# llama-server from its pinned commit (cache-deps.sh)
src=$cache/llama.cpp-$LLAMA_COMMIT-macos$MACOS_MIN
mkdir -p "$res/llama"
cp "$src/build/bin/llama-server" "$res/llama/"

# The licenses of what the bundle carries, which they ask to ship with it (docs/reference/7-development.md, "The
# package"): llama.cpp's and Sparkle's here; Python and its packages keep theirs (python/lib/python3.*/LICENSE.txt and
# each package's dist-info), Silero VAD's model has server/vad/LICENSE
mkdir -p "$res/licenses"
cp "$src/LICENSE" "$res/licenses/llama.cpp.txt"
cp .build/artifacts/sparkle/Sparkle/LICENSE "$res/licenses/Sparkle.txt"

# The app runs on a Mac without Homebrew and on macOS $MACOS_MIN: no executable or library in it may load a library
# from Homebrew, or need a newer macOS (the minos of LC_BUILD_VERSION, or the version of the older
# LC_VERSION_MIN_MACOSX).
problems=$(find "$app/Contents" -type f \( -perm -u+x -o -name '*.so' -o -name '*.dylib' \) | while IFS= read -r f; do
  file -b "$f" | grep -q Mach-O || continue
  otool -L "$f" | tail -n +2 | grep -E '^[[:space:]]+/(opt/homebrew|usr/local)/' | sed "s|^|$f: a library from outside macOS and the app:|"
  otool -l "$f" | awk -v min="$MACOS_MIN" -v f="$f" '
    $1 == "cmd" { cmd = $2 }
    ($1 == "minos" && cmd == "LC_BUILD_VERSION") || ($1 == "version" && cmd == "LC_VERSION_MIN_MACOSX") {
      split($2, a, "."); split(min, b, ".")
      if (a[1] + 0 > b[1] + 0 || (a[1] + 0 == b[1] + 0 && a[2] + 0 > b[2] + 0)) print f ": needs macOS " $2
    }'
done)
if [ -n "$problems" ]; then echo "$problems" >&2; exit 1; fi

# Inside out: Sparkle's helpers, then the framework; every executable and library in the bundle; then the app
sparkle=$app/Contents/Frameworks/Sparkle.framework/Versions/B
for f in "$sparkle/Autoupdate" "$sparkle/Updater.app" "$app/Contents/Frameworks/Sparkle.framework"; do
  codesign --force --sign "$identity" --options runtime --timestamp "$f"
done
find "$app/Contents/Resources" -type f \( -perm -u+x -o -name '*.so' -o -name '*.dylib' \) |
  while IFS= read -r f; do
    if file -b "$f" | grep -q Mach-O; then codesign --force --sign "$identity" --options runtime --timestamp "$f"; fi
  done
codesign --force --sign "$identity" --options runtime --timestamp --entitlements app/entitlements.plist "$app"
codesign --verify --deep --strict "$app"
codesign -dr - "$app" 2>&1 | tail -1
echo "version $version ($build), macOS $MACOS_MIN or later"

if $dmg; then
  # The installer window (dmg/settings.py): the app, a link to Applications and the background, by dmgbuild, from its
  # own environment in the cache (cache-deps.sh)
  tools=.cache/dmgtools
  rm -f build/EchoFox.dmg
  "$tools/bin/dmgbuild" -s dmg/settings.py -D app="$app" -D icon="$app/Contents/Resources/EchoFox.icns" \
    -D background=dmg/background.tiff EchoFox build/EchoFox.dmg >/dev/null
  # The dmg is signed too, so that Gatekeeper checks the file that was downloaded
  codesign --force --sign "$identity" --timestamp build/EchoFox.dmg
  echo build/EchoFox.dmg
fi
echo "$app"
