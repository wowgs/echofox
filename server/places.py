"""Where the servers listen: the working ones (the dictation you use) and the test ones (server/test_server.sh).
One place for these numbers in the server; the menu bar app reads the working port from the config file."""
HOST = "127.0.0.1"
WORKING_PORT = 8090        # the dictation server you use (launchd agent local-voice.gemma-voice)
WORKING_LLAMA_PORT = 8092  # its llama-server (launchd agent local-voice.llama-server)
TEST_PORT = 8091           # the test dictation server (server/test_server.sh)
TEST_LLAMA_PORT = 8093     # the test llama-server
WORKING_URL = f"ws://{HOST}:{WORKING_PORT}"
TEST_URL = f"ws://{HOST}:{TEST_PORT}"
