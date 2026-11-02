#!/bin/sh
# Puts a built EchoFox into /Applications in place of the installed one, and opens it (docs/reference/7-development.md,
# "Install a local build").
# Usage: macos/install-app.sh [--no-open] [APP]
#   APP        the app to install, macos/build/EchoFox.app by default (macos/build-app.sh builds it).
#   --no-open  do not open the app after the install.
# It quits the running EchoFox first and waits until the app and its dictation server have ended, since the server
# runs from the installed bundle. The installed app goes to the Trash, not away, so it can be put back. The config, the
# models and the recordings are not touched. The new app migrates the config at its start as a release would.
set -eu
cd "$(dirname "$0")"
open_after=true app=build/EchoFox.app
for a in "$@"; do
  case $a in
    --no-open) open_after=false ;;
    -*) echo "usage: $0 [--no-open] [APP]" >&2; exit 2 ;;
    *) app=$a ;;
  esac
done
target=/Applications/EchoFox.app
bundle_id=uk.wowgs.echofox
wait_s=30  # the app's quit ends the server, and the server ends its llama-server; this is far over what that takes

[ -d "$app" ] || { echo "no app at $app: build it with macos/build-app.sh" >&2; exit 1; }
app=$(cd "$app" && pwd)  # defaults reads a plist by its absolute path
[ "$(defaults read "$app/Contents/Info.plist" CFBundleIdentifier)" = "$bundle_id" ] || { echo "$app is not EchoFox ($bundle_id)" >&2; exit 1; }
codesign --verify --deep --strict "$app" || { echo "$app does not pass codesign --verify" >&2; exit 1; }
version=$(defaults read "$app/Contents/Info.plist" CFBundleShortVersionString)
build=$(defaults read "$app/Contents/Info.plist" CFBundleVersion)

# The running EchoFox, wherever it runs from, its server and its llama-server, which run from the installed bundle. SIGTERM ends the app
# at once; its server sees its standard input close and ends with its llama-server (docs/design.md, "Architecture").
running() { pgrep -f "/EchoFox.app/Contents/(MacOS/EchoFox|Resources/python/bin/python3|Resources/llama/llama-server)" || true; }
pids=$(pgrep -f "/EchoFox.app/Contents/MacOS/EchoFox$" || true)
if [ -n "$pids" ]; then
  echo "quitting EchoFox ($pids)"
  kill -TERM $pids
fi
waited=0
while [ -n "$(running)" ]; do
  [ $waited -lt $wait_s ] || { echo "EchoFox or its server still runs after $wait_s s: $(running | tr '\n' ' ')" >&2; exit 1; }
  sleep 1
  waited=$((waited + 1))
done

if [ -e "$target" ]; then
  old=$(defaults read "$target/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null || echo unknown)
  trashed="$HOME/.Trash/EchoFox $old $(date +%Y-%m-%d\ %H.%M.%S).app"
  mv "$target" "$trashed"
  echo "the installed EchoFox $old is in the Trash: $trashed"
fi
ditto "$app" "$target"
echo "installed EchoFox $version ($build) in $target"
if $open_after; then open "$target"; fi
