#!/bin/sh
# Creates the self-signed code-signing certificate "EchoFox Dev" in the login keychain, for build-app.sh.
# Usage: macos/dev-cert.sh [name]   (default name: EchoFox Dev; build-app.sh reads it from $ECHOFOX_SIGN)
# The certificate is valid for 10 years. Only codesign may use its key without a prompt. The certificate is not
# trusted in the keychain, and codesign does not need that: the app's code requirement names the certificate itself.
set -eu
name=${1:-EchoFox Dev}
keychain=$HOME/Library/Keychains/login.keychain-db
if security find-certificate -c "$name" "$keychain" >/dev/null 2>&1; then
  echo "the login keychain already has a certificate named \"$name\""
  exit 0
fi
dir=$(mktemp -d)
trap 'rm -rf "$dir"' EXIT
cat > "$dir/cert.conf" <<EOF
[req]
distinguished_name = dn
x509_extensions = ext
prompt = no
[dn]
CN = $name
[ext]
basicConstraints = critical, CA:false
keyUsage = critical, digitalSignature
extendedKeyUsage = critical, codeSigning
EOF
# /usr/bin/openssl (LibreSSL) writes a PKCS#12 file that security import reads.
/usr/bin/openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -config "$dir/cert.conf" \
  -keyout "$dir/key.pem" -out "$dir/cert.pem" 2>/dev/null
pass=$(/usr/bin/openssl rand -hex 16)
/usr/bin/openssl pkcs12 -export -inkey "$dir/key.pem" -in "$dir/cert.pem" -name "$name" \
  -passout "pass:$pass" -out "$dir/cert.p12"
security import "$dir/cert.p12" -k "$keychain" -P "$pass" -T /usr/bin/codesign >/dev/null
security find-identity -p codesigning "$keychain" | grep "\"$name\""
