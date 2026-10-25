# Tests and tools

This page is for work on the code of Local Voice. Related docs: [the dictation server](1-server.md), [the menu bar app](4-app.md), [the protocol](6-protocol.md).

## Run the tests

The tests of the server need no model and no `llama-server`:

```
server/.venv/bin/python -m unittest discover -s server
```

They run in a sandbox (`server/sandbox.py`, which every test module imports first). The sandbox has a temporary home folder, a fake `launchctl`, and it refuses the ports of the working server and of the test server. So the tests never touch your config, recordings, metrics, plugins or servers.

The checks of the app:

```
swift run --package-path macos lv-tests
```

`lv-tests` is an executable, because XCTest and Swift Testing come only with Xcode.

## Try the model without your dictation

Do not run tests or experiments on the dictation server that you use. Use the test server:

```
server/test_server.sh start
server/.venv/bin/python server/try_wav.py recording.wav --language ru
server/test_server.sh stop
```

- `start` stops the working dictation server (after its running recording) and the working `llama-server`, so that only one model is in memory. Then it starts a test dictation server on `ws://127.0.0.1:8091` with its own `llama-server` on port 8093. The test server has its own copy of your config, with its own port, metrics and recordings. `VARIANT=q4_0 server/test_server.sh start` runs another variant of the model.
- `try_wav.py` sends a WAV file (16 kHz, mono, 16-bit) the way the app does, at the speed of speech, and prints each message and the wait after the stop. `--fast` sends it at once. `--options` and `--prompt` send the options and the prompt of an experiment. It reaches the working server only with `--working`.
- Your dictation is off until `stop`. `stop` ends the test processes and starts the working dictation server again.

The ports are in `server/constants.py`.

## Update the working server

Restart the working server between two dictations, with `launchctl kickstart -k gui/$(id -u)/local-voice.gemma-voice`. On a restart, the server takes no new recording. It lets a running recording finish for up to 200 s, and launchd waits 210 s for it (`STOP_WAIT_S`, `LAUNCHD_EXIT_TIMEOUT_S` in `server/constants.py`). But you cannot dictate until it is back.

## Install the server by hand

`server/launchd.sh install` makes the launchd agent of the dictation server. `status` and `uninstall` do what they say. The dictation server writes the agent of `llama-server` itself, when it starts the chosen model. To run the dictation server in the terminal instead: `server/.venv/bin/python server/gemma_voice.py`.
