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

3. Create the self-signed code-signing certificate "EchoFox Dev" in your login keychain. Without it, macOS asks for the permissions again after each build.

   ```
   macos/dev-cert.sh
   ```
4. Build the app and open it:

   ```
   macos/build-app.sh
   open macos/build/EchoFox.app
   ```

5. Allow Microphone and Accessibility when macOS asks. If no model is downloaded, the app asks which one to download.

Use `server/launchd.sh status` to inspect the agent or `server/launchd.sh uninstall` to remove it. To run the dictation server in the terminal instead: `server/.venv/bin/python server/gemma_voice.py`. The dictation server writes the agent of `llama-server` itself, when it starts the chosen model.

## Build a distributable app

Run `macos/build-app.sh --bundle` to create `macos/build/bundle/EchoFox.app`, or use `--dmg` to also create `macos/build/EchoFox.dmg`, the installer window that dmgbuild lays out ([distribution](../distribution.md#the-installer)).

The bundle includes the server, Python 3.14 and its packages, and a Metal build of `llama-server`. Versions are pinned in `macos/pins.sh`, and so is the oldest macOS, `MACOS_MIN`; the build passes it to cmake, pip, `actool` and `LSMinimumSystemVersion`. After the build, it reads the `minos` of every executable and library in the app and stops if one needs a newer macOS or links a library from Homebrew. It compiles the bytecode of Python, its packages and the server before signing, then checks the signature with `codesign --verify --deep --strict`. Models are downloaded separately.

The version comes from git: `CFBundleShortVersionString` is the nearest tag `v<major>.<minor>[.<patch>]` without the `v`, and `CFBundleVersion` is the number of commits (`git rev-list --count HEAD`). The build stops in a shallow clone or without a tag. Two builds of one commit have the same version, so after a rebuild without a new commit, restart the server yourself.

`ECHOFOX_SIGN` selects the signing identity; `ECHOFOX_SIGN=-` signs ad hoc. Without it and outside CI, the build uses the self-signed “EchoFox Dev” certificate, or signs ad hoc with a warning when there is none. When `ECHOFOX_SIGN` or `CI` is set and the identity is missing, the build stops. A public release needs the signing and notarization setup described in [distribution](../distribution.md#releases).

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
| `release.yml` | Push of a `v*` tag or manual dispatch | Tests, then a bundled DMG, signed and sent to Apple's notary service. |
| `staple.yml` | The notary relay, when Apple has checked the DMG, or manual dispatch with the submission's id | Apple's ticket stapled to the DMG, then the release. |

An ordinary branch push starts none of them.

With the Developer ID secrets, `release.yml` signs the DMG and sends it to Apple's notary service without waiting. Apple's check can take minutes or days. When it is over, Apple calls the [notary relay](../../ci/notary-relay/README.md), a Cloudflare Worker, which starts `staple.yml`. That run staples Apple's ticket to the DMG and publishes it: to GitHub Releases for a tag, or as an artifact for 14 days for a manual run. If the relay does not start it, start `staple.yml` by hand with the submission's id from the log of `release.yml` or from `xcrun notarytool history`. Without the secrets, `release.yml` signs ad hoc, for tests, and publishes the DMG itself. The secret names are listed at the top of each workflow.

## Diagrams

Each diagram in `img/` is a light SVG, the source, and a dark variant `<name>-dark.svg`. The docs show them with `<picture>`, so GitHub picks the one for the reader's theme. After you change a diagram, write the dark variants again:

```sh
python3 img/dark.py
```

The script swaps the colors from its table and stops on a color that the table does not have.

## Restart the working server

Between dictations, run:

```sh
launchctl kickstart -k gui/$(id -u)/echofox.gemma-voice
```

During shutdown, the server rejects new recordings and allows up to 200 seconds for the current one to finish. launchd waits 210 seconds (`STOP_WAIT_S` and `LAUNCHD_EXIT_TIMEOUT_S` in `server/constants.py`). Dictation resumes when the server is back.
