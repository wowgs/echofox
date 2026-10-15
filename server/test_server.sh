#!/bin/zsh
# A second dictation server for tests, with its own llama-server, so tests never share a model with the dictation
# you use. The test llama-server is in memory only while the tests run: `start` stops the working llama-server
# (launchd agent local-voice.llama-server) and starts a test one on port 8093 with the same arguments; `stop` ends
# both test processes and restarts the working dictation server, which starts the llama-server of the model chosen
# in the menu again. Meanwhile, dictate with Claude Code's own dictation.
# The test dictation server listens on port 8091. It reads the same config (~/.local-voice/config.json) through a
# copy in which every model's llamaServer is the test llama-server and no model has a launchd agent; its log,
# metrics and recordings folder are its own.
# Usage: server/test_server.sh [start|stop|status]
set -euo pipefail
cd "${0:A:h}"
PORT=8091
LLAMA_PORT=8093
LABEL=local-voice.llama-server
LLAMA_PLIST=~/Library/LaunchAgents/$LABEL.plist
LOGS=~/Library/Logs/local-voice
STATE=${TMPDIR:-/tmp}/local-voice-test-server
CONFIG=${LOCAL_VOICE_CONFIG:-$HOME/.local-voice/config.json}
pids() { pgrep -f "gemma_voice.py.*--port $PORT" || true; pgrep -f "llama-server.*--port $LLAMA_PORT" || true; }
stop_tests() { for p in $(pids); do kill $p; done; for i in {1..50}; do [[ -z $(pids) ]] && break; sleep 0.1; done; }
case ${1:-start} in
  stop)
    stop_tests
    launchctl kickstart -k gui/$(id -u)/local-voice.gemma-voice
    echo "stopped; the working dictation server restarts the chosen model's llama-server";;
  status)
    p=$(pids); [[ -n $p ]] && echo "running: pids $p, ws://127.0.0.1:$PORT, llama-server :$LLAMA_PORT" || echo "not running";;
  start)
    stop_tests
    [[ -f $LLAMA_PLIST ]] || { echo "no $LLAMA_PLIST: server/llama_launchd.sh install first" >&2; exit 1; }
    mkdir -p $STATE $LOGS
    # The working llama-server's arguments, with the test port.
    llama=(${(f)"$(python3 -c '
import plistlib, sys
a = plistlib.load(open(sys.argv[1], "rb"))["ProgramArguments"]
out, skip = [], False
for x in a:
    if skip: out.append(sys.argv[2]); skip = False; continue
    out.append(x)
    skip = x == "--port"
print("\n".join(out))' $LLAMA_PLIST $LLAMA_PORT)"})
    python3 - $CONFIG $STATE/config.json http://127.0.0.1:$LLAMA_PORT <<'PY'
import json, sys
src, dst, url = sys.argv[1:4]
def fix(x):
    if isinstance(x, dict):
        if "llamaServer" in x:
            x["llamaServer"] = url
            x.pop("launchd", None)
        for v in x.values():
            fix(v)
    return x
json.dump(fix(json.load(open(src))), open(dst, "w"), indent=1)
PY
    launchctl bootout gui/$(id -u)/$LABEL 2>/dev/null || true
    nohup "${llama[@]}" > $LOGS/llama-server-test.log 2>&1 &
    nohup .venv/bin/python gemma_voice.py --config $STATE/config.json --ignore-selection --port $PORT \
      --metrics $LOGS/gemma-voice-test-metrics.jsonl --recordings $STATE/recordings > $LOGS/gemma-voice-test.log 2>&1 &
    for i in {1..120}; do curl -sf http://127.0.0.1:$LLAMA_PORT/health >/dev/null && break; sleep 1; done
    curl -sf http://127.0.0.1:$LLAMA_PORT/health >/dev/null || { echo "the test llama-server does not answer; see $LOGS/llama-server-test.log" >&2; exit 1; }
    echo "started: ws://127.0.0.1:$PORT, llama-server :$LLAMA_PORT; the working llama-server is stopped until 'stop'";;
esac
