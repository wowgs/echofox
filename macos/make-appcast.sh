#!/bin/sh
# Writes the update feed (appcast, docs/distribution.md "Updates") of one release's dmg to stdout: one item with the
# app's version and build, the oldest macOS, and the dmg at URL with its EdDSA signature; then the feed is signed too
# (the app requires a signed feed). Sparkle's tools come from pins.sh, checked against their SHA-256.
# Usage: macos/make-appcast.sh DMG URL [KEY_FILE] > appcast.xml
#   KEY_FILE  the private EdDSA key (the release's secret SPARKLE_ED_KEY); without it, the key of the login keychain
#             (account echofox), as on the author's Mac for a local test.
set -eu
cd "$(dirname "$0")"
. ./pins.sh
[ $# -ge 2 ] || { echo "usage: $0 DMG URL [KEY_FILE]" >&2; exit 2; }
dmg=$1 url=$2 key=${3-}
case $dmg in /*) ;; *) dmg=$OLDPWD/$dmg ;; esac

tools=.cache/sparkle-$SPARKLE_VERSION
if [ ! -x "$tools/bin/sign_update" ]; then
  tarball=.cache/Sparkle-$SPARKLE_VERSION.tar.xz
  mkdir -p .cache "$tools"
  [ -f "$tarball" ] || { curl -fsSL --retry 3 -o "$tarball.tmp" "$SPARKLE_URL" && mv "$tarball.tmp" "$tarball"; }
  echo "$SPARKLE_SHA256  $tarball" | shasum -a 256 -c - >/dev/null
  tar -xJf "$tarball" -C "$tools"
fi
sign() {
  if [ -n "$key" ]; then "$tools/bin/sign_update" --ed-key-file "$key" "$@"
  else "$tools/bin/sign_update" --account echofox "$@"; fi
}

# The app's versions, from the dmg itself
mnt=$(mktemp -d) work=$(mktemp -d)
feed=$work/appcast.xml  # sign_update knows a feed by its .xml
trap 'hdiutil detach -quiet "$mnt" 2>/dev/null || true; rm -rf "$work"' EXIT
hdiutil attach -quiet -nobrowse -readonly -mountpoint "$mnt" "$dmg"
plist=$mnt/EchoFox.app/Contents/Info.plist
build=$(/usr/libexec/PlistBuddy -c "Print :CFBundleVersion" "$plist")
short=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$plist")
minimum=$(/usr/libexec/PlistBuddy -c "Print :LSMinimumSystemVersion" "$plist")
hdiutil detach -quiet "$mnt"
enclosure=$(sign "$dmg")  # sparkle:edSignature="…" length="…"
case $minimum in *.*.*) ;; *) minimum=$minimum.0 ;; esac  # Sparkle wants three parts

cat > "$feed" <<XML
<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
  <channel>
    <title>EchoFox</title>
    <item>
      <title>EchoFox $short</title>
      <pubDate>$(LC_ALL=C date -u "+%a, %d %b %Y %H:%M:%S +0000")</pubDate>
      <sparkle:version>$build</sparkle:version>
      <sparkle:shortVersionString>$short</sparkle:shortVersionString>
      <sparkle:minimumSystemVersion>$minimum</sparkle:minimumSystemVersion>
      <enclosure url="$url" $enclosure type="application/octet-stream"/>
    </item>
  </channel>
</rss>
XML
sign "$feed" >/dev/null
cat "$feed"
