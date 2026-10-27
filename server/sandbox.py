"""The tests' sandbox. Every test module imports it before anything else (test_sandbox.py checks that), so that no
test can touch the working setup:
- HOME and the paths the server reads from the environment ($ECHOFOX_CONFIG, $ECHOFOX_ADAPTERS) point into a new
  temporary folder: the config, the recordings, the metrics, the user's adapters and every file an adapter reads under
  HOME there are empty and the tests' own;
- llama.spawn and llama.end_stale are fakes, so no test starts a llama-server or stops one that runs;
- connections to the ports of the working and the test servers (constants.py) are refused, so a test never reaches a
  real dictation server or llama-server."""
import os
import socket
import tempfile

import constants as places

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="echofox-tests-"))
REAL_HOME = os.path.expanduser("~")
os.environ["HOME"] = ROOT
for var, path in {"ECHOFOX_CONFIG": ".echofox/config.json",
                  "ECHOFOX_ADAPTERS": "Library/Application Support/EchoFox/adapters"}.items():
    os.environ[var] = os.path.join(ROOT, path)
    os.makedirs(os.path.dirname(os.environ[var]) if var == "ECHOFOX_CONFIG" else os.environ[var], exist_ok=True)

os.environ.pop("ECHOFOX_APP_VERSION", None)  # the app that starts the server sets it; the tests set it themselves

BLOCKED = {places.WORKING_PORT, places.WORKING_LLAMA_PORT, places.TEST_PORT, places.TEST_LLAMA_PORT}
_connect = socket.socket.connect


def _guarded_connect(self, address):
    if isinstance(address, tuple) and len(address) >= 2 and address[1] in BLOCKED:
        raise ConnectionRefusedError(f"sandbox: a test must not connect to port {address[1]}, a real server's")
    return _connect(self, address)


socket.socket.connect = _guarded_connect

import llama  # noqa: E402  (after the sandbox's paths: llama reads them when it loads)


class FakeProcess:
    """A llama-server that never runs: what spawn gives in the tests. It runs until it is ended."""
    pid = 0

    def __init__(self, argv):
        self.argv, self.returncode = argv, None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


SPAWNED = []  # what the tests started


def _spawn(argv):
    SPAWNED.append(FakeProcess(argv))
    return SPAWNED[-1]


llama.spawn = _spawn
llama.end_stale = lambda port: None
