"""The tests' sandbox. Every test module imports it before anything else (test_sandbox.py checks that), so that no
test can touch the working setup:
- HOME and every path the server reads from the environment ($LOCAL_VOICE_CONFIG, _PLUGINS, _PROJECTS,
  _DESKTOP_SESSIONS) point into a new temporary folder: the config, the recordings, the metrics, the adapter plugins,
  ~/.claude and Claude Desktop's session records there are empty and the tests' own;
- launchctl is a fake that only notes its arguments ($LOCAL_VOICE_LAUNCHCTL), so no launchd agent starts or stops;
- connections to the ports of the working and the test servers (places.py) are refused, so a test never reaches a
  real dictation server or llama-server."""
import os
import socket
import stat
import tempfile

import places

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="local-voice-tests-"))
REAL_HOME = os.path.expanduser("~")
os.environ["HOME"] = ROOT
for var, path in {"LOCAL_VOICE_CONFIG": ".local-voice/config.json",
                  "LOCAL_VOICE_PLUGINS": "Library/Application Support/Local Voice/adapters",
                  "LOCAL_VOICE_PROJECTS": ".claude/projects",
                  "LOCAL_VOICE_DESKTOP_SESSIONS": "Library/Application Support/Claude/claude-code-sessions"}.items():
    os.environ[var] = os.path.join(ROOT, path)
    os.makedirs(os.path.dirname(os.environ[var]) if var == "LOCAL_VOICE_CONFIG" else os.environ[var], exist_ok=True)

LAUNCHCTL_LOG = os.path.join(ROOT, "launchctl.log")
_fake = os.path.join(ROOT, "launchctl")
with open(_fake, "w") as f:  # `print` (is the agent loaded?) says no; everything else succeeds
    f.write(f'#!/bin/sh\necho "$@" >> "{LAUNCHCTL_LOG}"\n[ "$1" = print ] && exit 113\nexit 0\n')
os.chmod(_fake, os.stat(_fake).st_mode | stat.S_IEXEC)
os.environ["LOCAL_VOICE_LAUNCHCTL"] = _fake

BLOCKED = {places.WORKING_PORT, places.WORKING_LLAMA_PORT, places.TEST_PORT, places.TEST_LLAMA_PORT}
_connect = socket.socket.connect


def _guarded_connect(self, address):
    if isinstance(address, tuple) and len(address) >= 2 and address[1] in BLOCKED:
        raise ConnectionRefusedError(f"sandbox: a test must not connect to port {address[1]}, a real server's")
    return _connect(self, address)


socket.socket.connect = _guarded_connect
