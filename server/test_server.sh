#!/bin/zsh
# A second dictation server for tests, with its own llama-server, so tests never share a model with the dictation
# you use. The test llama-server is in memory only while the tests run: `start` stops the working dictation server
# (launchd agent local-voice.gemma-voice; it lets a running recording end first) and the working llama-server
# (local-voice.llama-server), so that nothing starts the working model again meanwhile, and starts a test
# llama-server with the working one's arguments; `stop` ends both test processes and starts the working dictation
# server again, which starts the llama-server of the model chosen in the menu. Meanwhile, your dictation is off.
# The ports, labels and folders are in constants.py. It reads the same config (~/.local-voice/config.json) through a
# copy in which every model's llamaServer is the test llama-server and no model has a launchd agent, and whose port,
# metrics and recordings folder are the test server's own; its log is its own too.
# Usage: [VARIANT=<id>] [BUNDLE=<LocalVoice.app>] server/test_server.sh [start|stop|status]; VARIANT picks another
# variant of the models (q4_0); BUNDLE runs the Python, the server and the llama-server of a bundled app (build-app.sh
# --bundle) instead of this repository's.
set -euo pipefail
HERE=${0:A:h}  # before any cd (a relative $0 resolves from the current folder), and not in c(): inside a function $0 is the function's name
cd "$HERE"
# The shared numbers and names come from server/constants.py.
c() { PYTHONPATH=$HERE $HERE/.venv/bin/python -c "import constants as c; v = c.$1; print(c.path(v) if isinstance(v, str) and v.startswith('~') else v)"; }
PORT=$(c TEST_PORT)
LLAMA_PORT=$(c TEST_LLAMA_PORT)
LABEL=$(c LLAMA_LABEL)
SERVER_LABEL=$(c SERVER_LABEL)
SERVER_PLIST=$(c LAUNCH_AGENTS)/$SERVER_LABEL.plist
DOMAIN=gui/$(id -u)
LOGS=$(c LOGS)
STATE=${TMPDIR:-/tmp}/local-voice-test-server
CONFIG=${LOCAL_VOICE_CONFIG:-$(c CONFIG)}
EXIT_WAIT=$(c LAUNCHD_EXIT_TIMEOUT_S)
# The Python and the server that run: this repository's, or a bundled app's
if [[ -n ${BUNDLE:-} ]]; then PY=${BUNDLE:A}/Contents/Resources/python/bin/python3 SRV=${BUNDLE:A}/Contents/Resources/server
else PY=$HERE/.venv/bin/python SRV=$HERE; fi
pids() { pgrep -f "gemma_voice.py --config $STATE/config.json" || true; pgrep -f "llama-server.*--port $LLAMA_PORT" || true; }
stop_tests() { for p in $(pids); do kill $p; done; for i in {1..50}; do [[ -z $(pids) ]] && break; sleep 0.1; done; }
case ${1:-start} in
  stop)
    stop_tests
    launchctl print $DOMAIN/$SERVER_LABEL >/dev/null 2>&1 || launchctl bootstrap $DOMAIN $SERVER_PLIST
    echo "stopped; the working dictation server is back and starts the chosen model's llama-server";;
  status)
    p=$(pids); [[ -n $p ]] && echo "running: pids $p, ws://127.0.0.1:$PORT, llama-server :$LLAMA_PORT" || echo "not running";;
  start)
    stop_tests
    mkdir -p $STATE $LOGS
    python3 - $CONFIG $STATE/config.json http://127.0.0.1:$LLAMA_PORT $PORT $LOGS/gemma-voice-test-metrics.jsonl \
      $STATE/recordings <<'PY'
import json, os, sys
src, dst, url, port, metrics, recordings = sys.argv[1:7]
def fix(x):
    if isinstance(x, dict):
        if "llamaServer" in x:
            x["llamaServer"] = url
            x.pop("launchd", None)
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
entry = {**c["models"][name], "launchd": "test"}
folder = constants.path((c.get("server") or {}).get("modelsFolder") or constants.MODELS_FOLDER)
print("\n".join(llama.agent(entry, folder)["ProgramArguments"]))' $STATE/config.json)"})
    # The working dictation server first: it ends after its running recording (ExitTimeOut in launchd.sh).
    launchctl bootout $DOMAIN/$SERVER_LABEL 2>/dev/null || true
    for i in {1..$EXIT_WAIT}; do launchctl print $DOMAIN/$SERVER_LABEL >/dev/null 2>&1 || break; sleep 1; done
    launchctl bootout $DOMAIN/$LABEL 2>/dev/null || true
    nohup "${llama[@]}" > $LOGS/llama-server-test.log 2>&1 &
    nohup $PY $SRV/gemma_voice.py --config $STATE/config.json --ignore-selection \
      > $LOGS/gemma-voice-test.log 2>&1 &
    for i in {1..120}; do curl -sf http://127.0.0.1:$LLAMA_PORT/health >/dev/null && break; sleep 1; done
    curl -sf http://127.0.0.1:$LLAMA_PORT/health >/dev/null || { echo "the test llama-server does not answer; see $LOGS/llama-server-test.log" >&2; exit 1; }
    echo "started: ws://127.0.0.1:$PORT, llama-server :$LLAMA_PORT; the working dictation server and llama-server are stopped until 'stop'";;
esac
