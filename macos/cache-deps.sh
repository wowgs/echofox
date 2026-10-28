#!/bin/sh
# Fills macos/.cache with what the app bundles and what is slow to make, at the versions of pins.sh: the Python
# tarball, checked against its SHA-256; llama-server built from its pinned commit with Metal, as one binary, for the
# oldest macOS; and dmgbuild's environment, pinned with hashes (dmg/requirements.txt). Each part is made only when it is
# missing or its pin changed. It needs no signing identity and no secret, so CI can fill the cache from the default
# branch (.github/workflows/cache.yml), where the release's tags find it. build-app.sh runs it first.
# Usage: macos/cache-deps.sh
set -eu
cd "$(dirname "$0")"
. ./pins.sh
cache=.cache
mkdir -p "$cache"

# Python
tarball=$cache/$PYTHON_FILE
[ -f "$tarball" ] || { curl -fL --retry 3 -o "$tarball.tmp" "$PYTHON_URL" && mv "$tarball.tmp" "$tarball"; }
echo "$PYTHON_SHA256  $tarball" | shasum -a 256 -c - >/dev/null

# llama-server (the build's flags are kept beside it, so that other flags build it again). No HTTPS (LLAMA_OPENSSL):
# it serves 127.0.0.1 only, and OpenSSL would come from Homebrew, not from macOS.
src=$cache/llama.cpp-$LLAMA_COMMIT-macos$MACOS_MIN
flags="-DCMAKE_BUILD_TYPE=Release -DGGML_METAL=ON -DBUILD_SHARED_LIBS=OFF -DCMAKE_OSX_DEPLOYMENT_TARGET=$MACOS_MIN \
-DLLAMA_CURL=OFF -DLLAMA_OPENSSL=OFF -DLLAMA_BUILD_TESTS=OFF"
if [ ! -x "$src/build/bin/llama-server" ] || [ "$(cat "$src/build/echofox-flags" 2>/dev/null)" != "$flags" ]; then
  rm -rf "$src"
  git init -q "$src"
  git -C "$src" fetch -q --depth 1 "$LLAMA_REPO" "$LLAMA_COMMIT"
  git -C "$src" checkout -q FETCH_HEAD
  # shellcheck disable=SC2086  # the flags, split into arguments on purpose
  cmake -S "$src" -B "$src/build" $flags >/dev/null
  cmake --build "$src/build" --target llama-server -j >/dev/null
  echo "$flags" > "$src/build/echofox-flags"
fi

# dmgbuild's environment (the environment keeps the SHA-256 of the file it was made from, so that a change of the file
# makes it again)
tools=$cache/dmgtools
wanted=$(shasum -a 256 dmg/requirements.txt | cut -d' ' -f1)
if [ "$(cat "$tools/requirements.sha256" 2>/dev/null)" != "$wanted" ] || ! "$tools/bin/python" -c "import dmgbuild" 2>/dev/null; then
  rm -rf "$tools"
  python3 -m venv "$tools"
  "$tools/bin/pip" install --quiet --disable-pip-version-check --require-hashes --only-binary :all: -r dmg/requirements.txt
  echo "$wanted" > "$tools/requirements.sha256"
fi
