#!/bin/zsh
# llama.cpp's llama-server with Gemma 4 E4B (GGUF) as a launchd agent of this user, for the dictation server's
# models of the kind {"llamaServer": "http://127.0.0.1:8092"} (llama.LlamaModel).
# Usage: [CATALOG=<id>] server/llama_launchd.sh install [MODEL.gguf [MMPROJ.gguf]] | uninstall | status
#   defaults: ~/models/gemma-4-E4B-gguf/gemma-4-E4B-it-Q8_0.gguf and mmproj-gemma-4-E4B-it-BF16.gguf
# llama-server runs on 127.0.0.1:8092 with the arguments of the model's catalog entry (catalog.json; CATALOG, by
# default gemma-4-e4b). Gemma 4 E4B's: a 16384-token context in two slots (8192 tokens each: the two pieces of a
# recording run at once, one per slot), every layer on the GPU (Metal), and the full cache of Gemma's sliding-window
# layers (--swa-full). Without it, those layers keep only their window, so a later piece that shares the text but
# not the audio of the one before cannot take the text from the cache: on 2026-10-15 the second piece of a recording
# processed all its 2311 tokens again although 83 % of them matched. The prompt cache in RAM is off (--cache-ram 0):
# the dictation server uses only each slot's own cache, and llama-server's default (8192 MiB, common/common.h) kept the
# states of old requests, which filled up within a day (2026-10-19) and went to swap on a 24 GB Mac.
# Log: ~/Library/Logs/local-voice/llama-server.log.
set -euo pipefail
# The shared numbers and names come from server/constants.py.
HERE=${0:A:h}  # here, not in c(): inside a function $0 is the function's name
c() { PYTHONPATH=$HERE $HERE/.venv/bin/python -c "import constants as c; v = c.$1; print(c.path(v) if isinstance(v, str) and v.startswith('~') else v)"; }
LABEL=$(c LLAMA_LABEL)
PLIST=$(c LAUNCH_AGENTS)/$LABEL.plist
LOG=$(c LOGS)/llama-server.log
HOST=$(c HOST)
PORT=$(c WORKING_LLAMA_PORT)
DIR=~/models/gemma-4-E4B-gguf
case ${1:-status} in
  install)
    model=${2:-$DIR/gemma-4-E4B-it-Q8_0.gguf}; mmproj=${3:-$DIR/mmproj-gemma-4-E4B-it-BF16.gguf}
    [[ -f $model && -f $mmproj ]] || { echo "no $model or $mmproj" >&2; exit 1; }
    bin=$(command -v llama-server) || { echo "llama-server is not installed (brew install llama.cpp)" >&2; exit 1; }
    # The model's own arguments (context, slots, cache) are in its catalog entry: catalog.json, llamaServer.args.
    args=$(PYTHONPATH=$HERE $HERE/.venv/bin/python -c 'import sys, catalog
from xml.sax.saxutils import escape
print("".join(f"<string>{escape(a)}</string>" for a in catalog.entries()[sys.argv[1]]["llamaServer"]["args"]))' "${CATALOG:-gemma-4-e4b}")
    mkdir -p ${LOG:h}
    launchctl bootout gui/$(id -u)/$LABEL 2>/dev/null || true
    for i in $(seq 1 50); do launchctl print gui/$(id -u)/$LABEL >/dev/null 2>&1 || break; sleep 0.1; done
    cat > $PLIST <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$bin</string><string>-m</string><string>$model</string><string>--mmproj</string><string>$mmproj</string>
    <string>--host</string><string>$HOST</string><string>--port</string><string>$PORT</string>
    $args
  </array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/><key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$LOG</string><key>StandardErrorPath</key><string>$LOG</string>
</dict></plist>
PL
    launchctl bootstrap gui/$(id -u) $PLIST
    echo "installed $PLIST: $model, $mmproj";;
  uninstall) launchctl bootout gui/$(id -u)/$LABEL 2>/dev/null || true; rm -f $PLIST; echo "uninstalled";;
  status) launchctl print gui/$(id -u)/$LABEL 2>/dev/null | grep -E "state|pid" | head -3 || echo "not installed";;
esac
