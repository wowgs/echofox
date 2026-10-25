# Build, tests and tools

This page is for work on the code of Local Voice. Related docs: [the dictation server](1-server.md), [the menu bar app](4-app.md), [the protocol](6-protocol.md).

## Build from source

On this setup, the dictation server runs from the repository, and `llama-server` comes from Homebrew.

1. Install llama.cpp and Python:

   ```
   brew install llama.cpp python
   ```

2. Set up the dictation server and start it as a launchd agent. It starts again at each login, and it starts the model itself.

   ```
   python3 -m venv server/.venv
   server/.venv/bin/pip install -r server/requirements.txt
   server/launchd.sh install
   ```

3. Create a self-signed code-signing certificate named "Local Voice Dev" in your login keychain (Keychain Access, Certificate Assistant, Create a Certificate). Without it, macOS asks for the permissions again after each build.
4. Build the app and open it:

   ```
   macos/build-app.sh
   open macos/build/LocalVoice.app
   ```

5. Allow Microphone and Accessibility when macOS asks. If no model is downloaded, the app asks which one to download.

`server/launchd.sh status` and `server/launchd.sh uninstall` do what they say. To run the dictation server in the terminal instead: `server/.venv/bin/python server/gemma_voice.py`. The dictation server writes the agent of `llama-server` itself, when it starts the chosen model.

To build the app that carries everything, as the release does: `macos/build-app.sh --bundle` or `--dmg` ([the menu bar app](4-app.md#build-and-start)).

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

- `start` stops the working dictation server (after its running recording) and the working `llama-server`, so that only one model is in memory. Then it starts a test dictation server on `ws://127.0.0.1:8091` with its own `llama-server` on port 8093. The test server has its own copy of your config, with its own port, metrics and recordings. `VARIANT=q4_0 server/test_server.sh start` runs another variant of the model. `BUNDLE=macos/build/bundle/LocalVoice.app server/test_server.sh start` runs the Python, the server and the `llama-server` of a bundled app instead of the repository's.
- `try_wav.py` sends a WAV file (16 kHz, mono, 16-bit) the way the app does, at the speed of speech, and prints each message and the wait after the stop. `--fast` sends it at once. `--options` and `--prompt` send the options and the prompt of an experiment. It reaches the working server only with `--working`.
- Your dictation is off until `stop`. `stop` ends the test processes and starts the working dictation server again.

The ports are in `server/constants.py`.

## CI

GitHub Actions runs two workflows:

- `.github/workflows/tests.yml` runs the tests of the server and the checks of the app on a clean Mac. It runs when you start it (Actions, Run workflow) and before every release. A push does not start it: the tests run on your Mac before each commit.
- `.github/workflows/release.yml` runs on a tag `v*`, or when you start it. It runs the tests first, then builds `LocalVoice.dmg` with `macos/build-app.sh --dmg`. On a tag, the dmg goes into a GitHub Release. Started by hand, the dmg stays as an artifact of the run for 14 days. With the Developer ID secrets (listed at the top of the file), it signs the app with Developer ID and notarizes the dmg. Without them, it signs ad hoc, which is only for tests.

## Update the working server

Restart the working server between two dictations, with `launchctl kickstart -k gui/$(id -u)/local-voice.gemma-voice`. On a restart, the server takes no new recording. It lets a running recording finish for up to 200 s, and launchd waits 210 s for it (`STOP_WAIT_S`, `LAUNCHD_EXIT_TIMEOUT_S` in `server/constants.py`). But you cannot dictate until it is back.
