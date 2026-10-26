"""The numbers and names the server, its scripts and its tests share: one place for each. The menu bar app gets the
ones it needs from the server (info.info) and reads the working port from the config file."""
import os

# Where the servers listen: the working ones (the dictation you use) and the test ones (server/test_server.sh).
HOST = "127.0.0.1"
WORKING_PORT = 8090        # the dictation server you use
WORKING_LLAMA_PORT = 8092  # its llama-server
TEST_PORT = 8091           # the test dictation server
TEST_LLAMA_PORT = 8093     # the test llama-server
WORKING_URL = f"ws://{HOST}:{WORKING_PORT}"
TEST_URL = f"ws://{HOST}:{TEST_PORT}"

# launchd agents of this user.
SERVER_LABEL = "echofox.gemma-voice"
LLAMA_LABEL = "echofox.llama-server"
LAUNCH_AGENTS = "~/Library/LaunchAgents"

# Files.
CONFIG = "~/.echofox/config.json"                         # $ECHOFOX_CONFIG sets another
LOGS = "~/Library/Logs/EchoFox"
METRICS = f"{LOGS}/gemma-voice-metrics.jsonl"
RECORDINGS = "~/speech/recordings"
LABELED = "~/speech/labeled"  # the labeled pieces (the app writes them; the server only names the folder)
MODELS_FOLDER = "~/Library/Application Support/EchoFox/models"  # the model files, a folder for each model
LLAMA_SERVER = "/opt/homebrew/bin/llama-server"  # llama.cpp's server (Homebrew); launchd's PATH does not have it
PLUGINS = "~/Library/Application Support/EchoFox/adapters"  # $ECHOFOX_PLUGINS sets another
CONFIG_VERSION = 7
PROTOCOL_INTERFACE = 2  # of the protocol (docs/reference/6-protocol.md); the app checks it

# Audio, as the client sends it: 16-bit little-endian PCM, mono.
RATE = 16000
SAMPLE_BYTES = 2
ENCODING = "pcm_s16le"

# Waits, in seconds; each later one is longer than the one before, so a stop never cuts what may still finish.
TEXT_WAIT_S = 180                       # the client waits this long after the stop for each next piece of text
REQUEST_TIMEOUT_S = TEXT_WAIT_S         # one request to llama-server
STOP_WAIT_S = TEXT_WAIT_S + 20          # a stopping server waits for its running recordings
LAUNCHD_EXIT_TIMEOUT_S = STOP_WAIT_S + 10  # launchd waits for the server to stop
MODEL_START_S = 180                     # a llama-server agent has this long to answer /health
MAX_PROMPT = 4000                      # characters of a prompt, the model's or a client's
MAX_RECORDING_MIN = 30                 # the longest recording the server takes; the config can change it


def path(p):
    return os.path.expanduser(p)
