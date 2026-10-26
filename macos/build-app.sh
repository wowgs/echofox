#!/bin/sh
# Builds macos/build/EchoFox.app and signs it. Run it with: open macos/build/EchoFox.app
# Usage: macos/build-app.sh [--bundle] [--dmg]
#   no flag   the app alone, for work on this Mac: the dictation server runs from the repository (server/launchd.sh).
#   --bundle  build/bundle/EchoFox.app, the app with everything it runs (docs/distribution.md): the server's code in
#             Contents/Resources/server, Python with the server's packages in Contents/Resources/python, and
#             llama-server in Contents/Resources/llama, at the versions of pins.sh. Such an app installs the
#             server's launchd agent itself.
#   --dmg     also build/EchoFox.dmg with the app (implies --bundle).
# It signs with the certificate $ECHOFOX_SIGN (default "EchoFox Dev", a self-signed code-signing certificate
# in the login keychain), so that the app's code requirement is its identifier and that certificate, the same for
# every build, and macOS keeps its permissions. ECHOFOX_SIGN=- signs ad hoc: then the requirement is the hash of the
# build, and after a rebuild macOS refuses the Accessibility it granted (tccd, 2026-10-15). Without ECHOFOX_SIGN and
# outside CI, a missing "EchoFox Dev" means ad hoc with a warning; when ECHOFOX_SIGN is set, or CI is, a missing
# identity stops the build before it starts. A Developer ID certificate also gets the hardened runtime, which
# notarization needs.
# The version is the nearest git tag v<major>.<minor>[.<patch>] (CFBundleShortVersionString) and the number of commits
# (CFBundleVersion), so the history must be whole (no shallow clone). The oldest macOS is pins.sh's MACOS_MIN.
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
. ./pins.sh

if [ -n "${ECHOFOX_SIGN+set}" ] || [ -n "${CI:-}" ]; then
  identity=${ECHOFOX_SIGN-} strict=true
  [ -n "$identity" ] || { echo "ECHOFOX_SIGN is empty or unset: name the signing identity, or - for ad hoc" >&2; exit 1; }
else
  identity="EchoFox Dev" strict=false
fi
if [ "$identity" != - ] && ! security find-identity -p codesigning | grep -qF "\"$identity\""; then
  if $strict; then echo "no signing identity \"$identity\" in the keychains" >&2; exit 1; fi
  echo "no certificate \"$identity\": signing ad hoc; macOS will ask for the permissions again" >&2
  identity=-
fi

[ "$(git rev-parse --is-shallow-repository)" = false ] || { echo "a shallow clone: the version needs the whole history" >&2; exit 1; }
tag=$(git describe --tags --match 'v[0-9]*' --abbrev=0) || { echo "no tag v* in git: no version" >&2; exit 1; }
version=${tag#v} build=$(git rev-list --count HEAD)
echo "$version" | grep -Eq '^[0-9]+(\.[0-9]+){1,2}$' || { echo "the tag $tag is not v<major>.<minor>[.<patch>]" >&2; exit 1; }

swift build -c release --product EchoFox
app=build/EchoFox.app
$bundle && app=build/bundle/EchoFox.app  # apart from the app of this Mac's work, which must not install the agent
rm -rf "$app"
mkdir -p "$app/Contents/MacOS"
cp .build/release/EchoFox "$app/Contents/MacOS/"
cp app/Info.plist "$app/Contents/"
# The version and the oldest macOS, which app/Info.plist leaves out. The app writes the version into the server's
# agent, so that a new version starts the server again (ServerAgent).
/usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string $version" -c "Add :CFBundleVersion string $build" \
  -c "Add :LSMinimumSystemVersion string $MACOS_MIN" "$app/Contents/Info.plist"
# The fox of the first start, and the app icon (macos/art/README.md): Icon Composer's app/EchoFox.icon, compiled by
# actool of Xcode into Assets.car, with EchoFox.icns for older macOS. Without Xcode, the prebuilt app/EchoFox.icns,
# which macOS 26 and later shows small on a gray tile.
mkdir -p "$app/Contents/Resources"
cp app/echofox-welcome.png "$app/Contents/Resources/"
xcode=$(xcode-select -p)
case $xcode in *CommandLineTools*) xcode=/Applications/Xcode.app/Contents/Developer ;; esac
if DEVELOPER_DIR=$xcode xcrun --find actool >/dev/null 2>&1; then
  DEVELOPER_DIR=$xcode xcrun actool app/EchoFox.icon --compile "$app/Contents/Resources" --platform macosx \
    --minimum-deployment-target "$MACOS_MIN" --app-icon EchoFox --output-partial-info-plist build/icon-info.plist >/dev/null
  [ -f "$app/Contents/Resources/Assets.car" ] || { echo "actool made no Assets.car" >&2; exit 1; }
else
  echo "no actool (Xcode): the prebuilt icon, on a gray tile in macOS 26 and later" >&2
  cp app/EchoFox.icns "$app/Contents/Resources/"
fi

if $bundle; then
  export MACOSX_DEPLOYMENT_TARGET="$MACOS_MIN"  # for any package that pip builds from source
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
  # The bytecode of the server, the standard library (the stripped Python has none) and the packages, so that Python
  # finds it and writes nothing into the signed bundle (the agent also sets PYTHONDONTWRITEBYTECODE); it also cuts
  # the server's imports from about 0.26 s to 0.07 s (M5, 2026-10-26). Each .pyc carries its source's hash, not a time
  # that a copy may change.
  "$res/python/bin/python3" -m compileall -q -j 0 --invalidation-mode checked-hash "$res/python/lib" "$res/server"

  # llama-server from its pinned commit, with Metal, as one binary, for the oldest macOS
  src=$cache/llama.cpp-$LLAMA_COMMIT-macos$MACOS_MIN
  if [ ! -x "$src/build/bin/llama-server" ]; then
    rm -rf "$src"
    git init -q "$src"
    git -C "$src" fetch -q --depth 1 "$LLAMA_REPO" "$LLAMA_COMMIT"
    git -C "$src" checkout -q FETCH_HEAD
    # No HTTPS (LLAMA_OPENSSL): it serves 127.0.0.1 only, and OpenSSL would come from Homebrew, not from macOS.
    cmake -S "$src" -B "$src/build" -DCMAKE_BUILD_TYPE=Release -DGGML_METAL=ON -DBUILD_SHARED_LIBS=OFF \
      -DCMAKE_OSX_DEPLOYMENT_TARGET="$MACOS_MIN" -DLLAMA_CURL=OFF -DLLAMA_OPENSSL=OFF -DLLAMA_BUILD_TESTS=OFF >/dev/null
    cmake --build "$src/build" --target llama-server -j >/dev/null
  fi
  mkdir -p "$res/llama"
  cp "$src/build/bin/llama-server" "$res/llama/"
fi

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

if [ "$identity" != - ]; then
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
  codesign --force --deep --sign - "$app"
fi
codesign --verify --deep --strict "$app"
codesign -dr - "$app" 2>&1 | tail -1
echo "version $version ($build), macOS $MACOS_MIN or later"

if $dmg; then
  # The installer window (dmg/settings.py): the app, a link to Applications and the background, by dmgbuild, which
  # runs from its own environment, pinned with hashes (dmg/requirements.txt)
  tools=.cache/dmgtools
  if ! "$tools/bin/python" -c "import dmgbuild" 2>/dev/null; then
    python3 -m venv "$tools"
    "$tools/bin/pip" install --quiet --disable-pip-version-check --require-hashes -r dmg/requirements.txt
  fi
  rm -f build/EchoFox.dmg
  "$tools/bin/dmgbuild" -s dmg/settings.py -D app="$app" -D icon="$app/Contents/Resources/EchoFox.icns" \
    -D background=dmg/background.tiff EchoFox build/EchoFox.dmg >/dev/null
  # A Developer ID signs the dmg too, so that Gatekeeper checks the file that was downloaded
  case $identity in "Developer ID"*) codesign --force --sign "$identity" --timestamp build/EchoFox.dmg ;; esac
  echo build/EchoFox.dmg
fi
echo "$app"
