# Build and develop EchoFox

Build the app, run local checks, or test recognition against a separate server. Related docs: [the dictation server](1-server.md), [the menu bar app](4-app.md), [the protocol](6-protocol.md).

The packaged app already includes its runtime and dependencies. The Homebrew instructions below are for developing from a checkout, not for using a packaged app. To create the self-contained package, see [Build a distributable app](#build-a-distributable-app).

## Build from source

Run these commands from the repository root on an Apple Silicon Mac. You need Homebrew and Swift build tools. This development setup runs the dictation server from the checkout and uses Homebrew’s `llama-server`.

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

3. Create a self-signed code-signing certificate named "EchoFox Dev" in your login keychain (Keychain Access, Certificate Assistant, Create a Certificate). Without it, macOS asks for the permissions again after each build.
4. Build the app and open it:

   ```
   macos/build-app.sh
   open macos/build/EchoFox.app
   ```

5. Allow Microphone and Accessibility when macOS asks. If no model is downloaded, the app asks which one to download.

Use `server/launchd.sh status` to inspect the agent or `server/launchd.sh uninstall` to remove it. To run the dictation server in the terminal instead: `server/.venv/bin/python server/gemma_voice.py`. The dictation server writes the agent of `llama-server` itself, when it starts the chosen model.

## Build a distributable app

Run `macos/build-app.sh --bundle` to create `macos/build/bundle/EchoFox.app`, or use `--dmg` to also create `macos/build/EchoFox.dmg`.

The bundle includes the server, Python 3.14 and its packages, and a Metal build of `llama-server`. Versions are pinned in `macos/pins.sh`. The build rejects libraries linked from Homebrew. Models are downloaded separately.

`ECHOFOX_SIGN` selects the signing identity. Development builds use the self-signed “EchoFox Dev” certificate when available, otherwise ad hoc signing. A public release needs the separate signing and notarization setup described in [distribution](../design/7-distribution.md).

## Run the tests

Server tests need neither a downloaded model nor a running `llama-server`:

```
server/.venv/bin/python -m unittest discover -s server
```

Tests run in a sandbox (`server/sandbox.py`, which every test module imports first). The sandbox has a temporary home folder, a fake `launchctl`, and it refuses the ports of the working server and of the test server. So the tests never touch your config, recordings, metrics, plugins or servers.

Run app checks with:

```
swift run --package-path macos echofox-tests
```

`echofox-tests` is an executable, because XCTest and Swift Testing come only with Xcode.

## Test recognition on a separate server

Use the test server for recognition experiments. Starting it temporarily pauses normal dictation so only one model occupies memory; stopping it restores the working server:

```
server/test_server.sh start
server/.venv/bin/python server/try_wav.py recording.wav --language ru
server/test_server.sh stop
```

`start` waits for the current recording, stops the working servers, and starts isolated test servers. The dictation endpoint is `ws://127.0.0.1:8091`; its model server uses port 8093. The test config has separate metrics and recordings.

| Option | Purpose |
|---|---|
| `VARIANT=q4_0 server/test_server.sh start` | Test a different model variant. |
| `BUNDLE=macos/build/bundle/EchoFox.app server/test_server.sh start` | Test the bundled Python, server, and model runtime. |
| `try_wav.py ... --fast` | Send audio immediately instead of at recording speed. |
| `try_wav.py ... --options ...` or `--prompt ...` | Override settings for an experiment. |

Input WAV files must be 16 kHz, mono, 16-bit. The client prints server messages and the delay after stopping. It reaches the working server only with `--working`.

**Normal dictation stays paused until `server/test_server.sh stop`.** Stop the test server when finished to restore the working servers.

The ports are in `server/constants.py`.

## CI

| Workflow | Trigger | Result |
|---|---|---|
| `tests.yml` | Manual dispatch or a call from the release workflow | Python and Swift checks on a clean Mac. |
| `release.yml` | Push of a `v*` tag or manual dispatch | Tests, then a bundled DMG. |

An ordinary branch push starts neither workflow. A tagged release publishes the DMG to GitHub Releases; a manual run keeps it as an artifact for 14 days.

With the required Developer ID secrets, the release workflow signs and notarizes the package. Without them, it uses ad hoc signing for testing. The required secret names are listed in `.github/workflows/release.yml`.

## Restart the working server

Between dictations, run:

```sh
launchctl kickstart -k gui/$(id -u)/echofox.gemma-voice
```

During shutdown, the server rejects new recordings and allows up to 200 seconds for the current one to finish. launchd waits 210 seconds (`STOP_WAIT_S` and `LAUNCHD_EXIT_TIMEOUT_S` in `server/constants.py`). Dictation resumes when the server is back.
