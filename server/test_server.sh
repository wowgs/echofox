#!/bin/zsh
# A second dictation server for tests, with its own llama-server, so tests never share a model with the dictation
# you use. The test llama-server is in memory only while the tests run: `start` quits EchoFox, whose dictation server
# and llama-server end with it (a running recording ends first), and starts a test llama-server with the working
# one's arguments; `stop` ends both test processes and opens EchoFox again, which starts its dictation server and the
# llama-server of the model chosen in the menu. Meanwhile, your dictation is off.
# The ports and folders are in constants.py. It reads the same config (~/.echofox/config.json) through a copy in
# which every model's llamaServer is the test llama-server, and whose port, metrics and recordings folder are the test
# server's own; its log is its own too.
# Usage: [VARIANT=<id>] [BUNDLE=<EchoFox.app>] server/test_server.sh [start|stop|status]; VARIANT picks another
# variant of the models (q4_0); BUNDLE runs the Python and the server of that app (macos/build/EchoFox.app, for one)
# instead of this repository's. The llama-server is the app's: BUNDLE's, else the installed one's.
set -euo pipefail
HERE=${0:A:h}  # before any cd (a relative $0 resolves from the current folder), and not in c(): inside a function $0 is the function's name
cd "$HERE"
# The shared numbers and names come from server/constants.py.
c() { PYTHONPATH=$HERE $HERE/.venv/bin/python -c "import constants as c; v = c.$1; print(c.path(v) if isinstance(v, str) and v.startswith('~') else v)"; }
PORT=$(c TEST_PORT)
LLAMA_PORT=$(c TEST_LLAMA_PORT)
WORKING_PORT=$(c WORKING_PORT)
LOGS=$(c LOGS)
STATE=${TMPDIR:-/tmp}/echofox-test-server
CONFIG=${ECHOFOX_CONFIG:-$(c CONFIG)}
EXIT_WAIT=$(c STOP_WAIT_S)
# The Python and the server that run: this repository's, or a bundled app's
if [[ -n ${BUNDLE:-} ]]; then PY=${BUNDLE:A}/Contents/Resources/python/bin/python3 SRV=${BUNDLE:A}/Contents/Resources/server
  export PYTHONDONTWRITEBYTECODE=1  # as the app does: nothing new in the signed bundle
else PY=$HERE/.venv/bin/python SRV=$HERE; fi
pids() { pgrep -f "gemma_voice.py --config $STATE/config.json" || true; pgrep -f "llama-server.*--port $LLAMA_PORT" || true; }
stop_tests() { for p in $(pids); do kill $p; done; for i in {1..50}; do [[ -z $(pids) ]] && break; sleep 0.1; done; }
case ${1:-start} in
  stop)
    stop_tests
    open -a EchoFox
    echo "stopped; EchoFox is open again and starts its dictation server and the chosen model's llama-server";;
  status)
    p=$(pids); [[ -n $p ]] && echo "running: pids $p, ws://127.0.0.1:$PORT, llama-server :$LLAMA_PORT" || echo "not running";;
  start)
    stop_tests
    mkdir -p $STATE $LOGS
    $PY - $CONFIG $STATE/config.json http://127.0.0.1:$LLAMA_PORT $PORT $LOGS/gemma-voice-test-metrics.jsonl \
      $STATE/recordings <<'PY'
import json, os, sys
src, dst, url, port, metrics, recordings = sys.argv[1:7]
def fix(x):
    if isinstance(x, dict):
        if "llamaServer" in x:
            x["llamaServer"] = url
        for v in x.values():
            fix(v)
    return x
config = fix(json.load(open(src)))
config.setdefault("server", {}).update(port=int(port), metrics=metrics, recordings=recordings)
if os.environ.get("VARIANT"):  # another variant of every model, for the test
    for m in config.get("models", {}).values():
        m["variant"] = os.environ["VARIANT"]
json.dump(config, open(dst, "w"), indent=1)
PY
    # The test llama-server: the chosen model's variant (VARIANT=q4_0 picks another) from the catalog, on the test port.
    llama=(${(f)"$(cd $SRV && $PY -c '
import json, sys
import constants, llama
c = json.load(open(sys.argv[1]))
name = c.get("model") if c.get("model") in c["models"] else next(iter(c["models"]))
entry = c["models"][name]
folder = constants.path((c.get("server") or {}).get("modelsFolder") or constants.MODELS_FOLDER)
print("\n".join(llama.command(entry, folder)))' $STATE/config.json)"})
    # EchoFox first: its dictation server ends after its running recording, and its llama-server with it.
    osascript -e 'quit app "EchoFox"' 2>/dev/null || true
    for i in {1..$EXIT_WAIT}; do lsof -nP -iTCP:$WORKING_PORT -sTCP:LISTEN -t >/dev/null 2>&1 || break; sleep 1; done
    nohup "${llama[@]}" > $LOGS/llama-server-test.log 2>&1 &
    nohup $PY $SRV/gemma_voice.py --config $STATE/config.json --ignore-selection \
      > $LOGS/gemma-voice-test.log 2>&1 &
    for i in {1..120}; do curl -sf http://127.0.0.1:$LLAMA_PORT/health >/dev/null && break; sleep 1; done
    curl -sf http://127.0.0.1:$LLAMA_PORT/health >/dev/null || { echo "the test llama-server does not answer; see $LOGS/llama-server-test.log" >&2; exit 1; }
    echo "started: ws://127.0.0.1:$PORT, llama-server :$LLAMA_PORT; EchoFox is quit until 'stop'";;
esac
