# Build and develop EchoFox

Build the app, run local checks, or test recognition against a separate server. Related docs: [the dictation server](1-server.md), [the menu bar app](4-app.md), [the protocol](6-protocol.md).

You use EchoFox as everyone does: the release from GitHub, in `/Applications`. Its server, Python and `llama-server` are inside it. The repository is for changing the code: the tests, the test server and the build of a release.

## Set up the repository

Run these commands from the repository root on an Apple Silicon Mac with Xcode and Python 3.14. The environment is for the server's tests and the test server; it never runs your dictation.

```
python3 -m venv server/.venv
server/.venv/bin/pip install --require-hashes --only-binary :all: -r server/requirements.txt
```

## Build the app

`macos/build-app.sh` builds `macos/build/EchoFox.app`; `--dmg` also builds `macos/build/EchoFox.dmg`, the installer window that dmgbuild lays out ([distribution](../distribution.md#the-installer)). Releases are built by CI ([below](#ci)); a local build is for a check before a tag.

The build needs Xcode, because `actool` compiles the icon, and a Developer ID Application identity in the keychain. `ECHOFOX_SIGN` names the identity; without it, the build takes the one Developer ID Application identity it finds. Without one, the build stops. It signs with the hardened runtime.

The app includes the server, Python 3.14 and its packages, and a Metal build of `llama-server`. Versions are pinned in `macos/pins.sh`, and so is the oldest macOS, `MACOS_MIN`; the build passes it to cmake, `actool` and `LSMinimumSystemVersion`. pip installs wheels only, and checks each against its SHA-256 in `server/requirements.txt`. The app leaves out the server's tests and its development tools. The build keeps its downloads and the `llama-server` build in `macos/.cache`; it builds `llama-server` again when its cmake flags change, and the dmgbuild environment again when `macos/dmg/requirements.txt` changes. After the build, it reads the `minos` of every executable and library in the app and stops if one needs a newer macOS or links a library from Homebrew. It compiles the bytecode of Python, its packages and the server before signing, then checks the signature with `codesign --verify --deep --strict`. Models are downloaded separately.

The version comes from git: `CFBundleShortVersionString` is the nearest tag `v<major>.<minor>[.<patch>]` without the `v`, and `CFBundleVersion` is the number of commits (`git rev-list --count HEAD`). The build stops in a shallow clone or without a tag.

An app writes the server's launchd agent for itself when it starts, so opening a local build takes the dictation server over from the installed app. Open the installed app again to go back.

## Run the tests

Server tests need neither a downloaded model nor a running `llama-server`:

```
server/.venv/bin/python -m unittest discover -s server
```

Tests run in a sandbox (`server/sandbox.py`, which every test module imports first). The sandbox has a temporary home folder, replaces the `launchctl` that `llama.py` calls with a fake, and refuses the ports of the working server and of the test server. So the tests never touch your config, recordings, metrics, plugins or servers. The sandbox knows no plugin: a test of a plugin sets up what that plugin reads.

Run app checks with:

```
swift run --package-path macos echofox-tests
```

`echofox-tests` is an executable, because XCTest and Swift Testing come only with Xcode. Both suites read the protocol examples (`shared/protocol-examples.json`) and the values both sides use (`shared/constants.json`), so a change on one side that the other does not follow fails a test.

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
| `BUNDLE=macos/build/EchoFox.app server/test_server.sh start` | Test the Python and the server of a built app instead of the repository's. |
| `try_wav.py ... --fast` | Send audio immediately instead of at recording speed. |
| `try_wav.py ... --options ...` or `--prompt ...` | Override settings for an experiment. |
| `try_wav.py ... --hint KEY=VALUE` | Send a hint to the adapters in the start message; VALUE is JSON, or else text. For example `--hint 'sessions=["<id>"]'` names Claude Code sessions to the Claude plugin. |

Input WAV files must be 16 kHz, mono, 16-bit. The client prints server messages and the delay after stopping. It reaches the working server only with `--working`.

**Normal dictation stays paused until `server/test_server.sh stop`.** Stop the test server when finished to restore the working servers.

The ports are in `server/constants.py`.

## CI

| Workflow | Trigger | Result |
|---|---|---|
| `tests.yml` | Manual dispatch or a call from the release workflow | Python and Swift checks on a clean Mac. |
| `release.yml` | Push of a `v*` tag or manual dispatch | Tests, then a bundled DMG, the server's tests again with the bundled Python, and the DMG signed and sent to Apple's notary service. |
| `staple.yml` | The notary relay, when Apple has checked the DMG, or manual dispatch with the submission's id | Apple's ticket stapled to the DMG, then the release. |

No checkout keeps the token. Only one job can write to the repository: the last job of `staple.yml`, which creates the release on Linux.

An ordinary branch push starts none of them.

With the Developer ID secrets, `release.yml` signs the DMG and sends it to Apple's notary service without waiting. Apple's check can take minutes or days. When it is over, Apple calls the [notary relay](../../ci/notary-relay/README.md), a Cloudflare Worker, which starts `staple.yml`. That run finds the DMG's artifact on Linux first, so a call with an unknown id starts no Mac. It staples Apple's ticket on a Mac and keeps the DMG as an artifact for 14 days; for a tag, a last job publishes it to GitHub Releases. If the relay does not start it, start `staple.yml` by hand with the submission's id from the log of `release.yml` or from `xcrun notarytool history`. Without the secrets, `release.yml` stops. The secret names are listed at the top of each workflow.

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
