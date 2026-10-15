#!/bin/zsh
# Runs server/gemma_voice.py as a launchd agent of this user: it starts at login and again after a crash.
# Usage: server/launchd.sh install [server arguments] | uninstall | status
# The server arguments go into the agent as they are, for example:
#   server/launchd.sh install --port 8090
# Log: ~/Library/Logs/local-voice/gemma-voice.log
set -e
# The shared numbers and names come from server/constants.py.
HERE=${0:A:h}  # here, not in c(): inside a function $0 is the function's name
c() { PYTHONPATH=$HERE $HERE/.venv/bin/python -c "import constants as c; v = c.$1; print(c.path(v) if isinstance(v, str) and v.startswith('~') else v)"; }
LABEL=$(c SERVER_LABEL)
PLIST=$(c LAUNCH_AGENTS)/$LABEL.plist
SERVER=${0:A:h}
LOG=$(c LOGS)/gemma-voice.log
EXIT_TIMEOUT=$(c LAUNCHD_EXIT_TIMEOUT_S)
DOMAIN=gui/$(id -u)

case $1 in
  install)
    [[ -x $SERVER/.venv/bin/python ]] || { echo "no $SERVER/.venv: set it up first (README)"; exit 1; }
    mkdir -p ~/Library/LaunchAgents ${LOG:h}
    cat > $PLIST <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$SERVER/.venv/bin/python</string>
    <string>$SERVER/gemma_voice.py</string>
$(for a in "${@:2}"; do printf '    <string>%s</string>\n' "$a"; done)
  </array>
  <key>WorkingDirectory</key><string>$SERVER</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ExitTimeOut</key><integer>$EXIT_TIMEOUT</integer>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
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
