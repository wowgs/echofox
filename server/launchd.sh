#!/bin/zsh
# Runs server/gemma_voice.py as a launchd agent of this user: it starts at login and again after a crash.
# Usage: server/launchd.sh install [--config FILE] | uninstall | status
# The settings are in the config file (default ~/.echofox/config.json); --config goes into the agent as it is.
# Log: ~/Library/Logs/EchoFox/gemma-voice.log
set -e
HERE=${0:A:h}  # here, not in c(): inside a function $0 is the function's name
PY=$HERE/.venv/bin/python
[[ -x $PY ]] || { echo "no $HERE/.venv: set it up first (README)"; exit 1; }
# The shared numbers and names come from server/constants.py.
c() { PYTHONPATH=$HERE $PY -c "import constants as c; v = c.$1; print(c.path(v) if isinstance(v, str) and v.startswith('~') else v)"; }
LABEL=$(c SERVER_LABEL)
PLIST=$(c LAUNCH_AGENTS)/$LABEL.plist
LOG=$(c SERVER_LOG)
EXIT_TIMEOUT=$(c LAUNCHD_EXIT_TIMEOUT_S)
DOMAIN=gui/$(id -u)

case $1 in
  install)
    mkdir -p ${PLIST:h} ${LOG:h}
    # plistlib writes the XML, so an argument with & or < stays what it is
    $PY - $PLIST $LABEL $HERE $LOG $EXIT_TIMEOUT $PY "${@:2}" <<'PY'
import plistlib, sys
plist, label, here, log, exit_timeout, python, *args = sys.argv[1:]
with open(plist, "wb") as f:
    plistlib.dump({"Label": label, "ProgramArguments": [python, f"{here}/gemma_voice.py", *args],
                   "WorkingDirectory": here, "RunAtLoad": True, "KeepAlive": True, "ExitTimeOut": int(exit_timeout),
                   "ProcessType": "Interactive", "StandardOutPath": log, "StandardErrorPath": log}, f)
PY
    launchctl bootout $DOMAIN/$LABEL 2>/dev/null || true
    # bootout returns before the old service is gone; bootstrap fails (error 5) until it is
    for i in {1..50}; do launchctl print $DOMAIN/$LABEL >/dev/null 2>&1 || break; sleep 0.2; done
    launchctl bootstrap $DOMAIN $PLIST
    echo "installed $PLIST"
    ;;
  uninstall)
    launchctl bootout $DOMAIN/$LABEL 2>/dev/null || true
    rm -f $PLIST
    echo "removed $PLIST"
    ;;
  status)
    launchctl print $DOMAIN/$LABEL | grep -E '^\s*(state|pid|last exit code|runs) ='
    ;;
  *)
    echo "usage: $0 install | uninstall | status"; exit 2
    ;;
esac
