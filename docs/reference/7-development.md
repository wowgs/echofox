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

`macos/build-app.sh` builds `macos/build/EchoFox.app`; `--dmg` also builds `macos/build/EchoFox.dmg`, the installer window that dmgbuild lays out ([below](#the-installer)). Releases are built by CI ([below](#ci)); a local build is for a check before a tag.

The build needs Xcode, because `actool` compiles the icon, and a Developer ID Application identity in the keychain. `ECHOFOX_SIGN` names the identity; without it, the build takes the one Developer ID Application identity it finds. Without one, the build stops. It signs with the hardened runtime.

The app includes the server, Python 3.14 and its packages, and a Metal build of `llama-server`. Versions are pinned in `macos/pins.sh`, and so is the oldest macOS, `MACOS_MIN`; the build passes it to cmake, `actool` and `LSMinimumSystemVersion`. pip installs wheels only, and checks each against its SHA-256 in `server/requirements.txt`. The app leaves out the server's tests and its development tools. The build keeps its downloads and the `llama-server` build in `macos/.cache`; it builds `llama-server` again when its cmake flags change, and the dmgbuild environment again when `macos/dmg/requirements.txt` changes. After the build, it reads the `minos` of every executable and library in the app and stops if one needs a newer macOS or links a library from Homebrew. It compiles the bytecode of Python, its packages and the server before signing, then checks the signature with `codesign --verify --deep --strict`. Models are downloaded separately.

The version comes from git: `CFBundleShortVersionString` is the nearest tag `v<major>.<minor>[.<patch>]` without the `v`, and `CFBundleVersion` is the number of commits (`git rev-list --count HEAD`). The build stops in a shallow clone or without a tag.

An app starts its own dictation server as its child process. Quit the installed app before you open a local build: two servers cannot listen on one port, and the second one is started again and again until the port is free.

### The package

| Path in `EchoFox.app/Contents` | What it is |
|---|---|
| `MacOS/EchoFox` | The Mac app. |
| `Resources/server/` | The dictation server, the built-in adapters and Silero VAD. |
| `Resources/python/` | Python 3.14 with the server's packages, without pip: it only installs the packages during the build. |
| `Resources/llama/llama-server` | llama-server, built with Metal into one binary. |
| `Frameworks/Sparkle.framework` | Sparkle, the updater ([updates](#updates)), without its XPC services. |
| `Resources/Assets.car`, `EchoFox.icns` | The app icon ([art](../../macos/art/README.md)). |
| `Resources/licenses/` | The licenses of llama.cpp and Sparkle. Python keeps its license in `Resources/python/lib/python3.14/LICENSE.txt`, each package in its `dist-info`, and Silero VAD in `Resources/server/vad/LICENSE`. |

`macos/pins.sh` pins the versions with their checksums or commits, and the oldest macOS, 26 (the onnxruntime and numpy wheels from PyPI are built for older versions and run on it). Everything in the bundle is built for it, and the build fails if a binary needs a newer macOS or links a library from Homebrew. Python's bytecode is compiled before signing, and the server's agent sets `PYTHONDONTWRITEBYTECODE`, so that nothing is written into the signed bundle. At launch the app starts its own server as its child process (`ServerProcess`, `ServerRunner`), with the app's version in `ECHOFOX_APP_VERSION` for the server's log. It does not do that when it runs from the dmg or from an App Translocation path: it asks the user to move it to Applications and quits. Before the first start, off the main thread, it stops and deletes the launchd agents of older versions (`echofox.gemma-voice`, `echofox.llama-server`), which ran the server without the app. The model is not in the package: it is several gigabytes, it does not change with each app update, and Q4_0 and Q8_0 are variants of one model in the app, not separate builds.

### The installer

The dmg opens a window like those of Ghostty, Chrome and Telegram: the app, a link to `/Applications`, and a background with an arrow and "Drag EchoFox to Applications". The volume's icon is the app's. dmgbuild builds it (`macos/dmg/settings.py`); it writes the window's `.DS_Store` itself, without Finder, so it runs on a runner without a screen. dmgbuild and its dependencies are pinned by version and SHA-256 in `macos/dmg/requirements.txt` and live in their own environment, `macos/.cache/dmgtools`. The background is drawn in `macos/dmg/background.svg` and made into `background.tiff` at 1x and 2x.

The image is compressed with lzma (ULMO, macOS 10.15 or later): of the formats measured, it made the smallest dmg, and it opens about 1.5 seconds slower than the fastest one.

## Run the tests

Server tests need neither a downloaded model nor a running `llama-server`:

```
server/.venv/bin/python -m unittest discover -s server
```

A test closes every file and socket it opens: the tests workflow fails when the log shows a `ResourceWarning`.

Tests run in a sandbox (`server/sandbox.py`, which every test module imports first). The sandbox has a temporary home folder, replaces the start of a llama-server in `llama.py` with a fake, and refuses the ports of the working server and of the test server. So the tests never touch your config, recordings, metrics, adapters or servers. The sandbox knows no adapter: a test of an adapter sets up what that adapter reads.

Run app checks with:

```
swift run --package-path macos echofox-tests
```

To check the look of the first start's window without a server, run `macos/build/EchoFox.app/Contents/MacOS/EchoFox --render-first-run INFO.json OUT.png [dark]`: it draws the window for a server's info (the `info` message, as JSON) into a PNG and quits.

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
| `try_wav.py ... --hint KEY=VALUE` | Send a hint to the adapters in the start message; VALUE is JSON, or else text. For example `--hint 'sessions=["<id>"]'` names Claude Code sessions to the Claude adapter. |

Input WAV files must be 16 kHz, mono, 16-bit. The client prints server messages and the delay after stopping. It reaches the working server only with `--working`.

**Normal dictation stays paused until `server/test_server.sh stop`.** Stop the test server when finished to restore the working servers.

The ports are in `server/constants.py`.

## CI

| Workflow | Trigger | Result |
|---|---|---|
| `tests.yml` | Manual dispatch or a call from the release workflow | Python and Swift checks on a clean Mac; a `ResourceWarning` in the server's tests fails it. |
| `release.yml` | Push of a `v*` tag or manual dispatch | Tests, then a bundled DMG, the server's tests again with the bundled Python, and the DMG signed and sent to Apple's notary service. |
| `staple.yml` | The webhook, when Apple has checked the DMG, or manual dispatch with the submission's id | Apple's ticket stapled to the DMG, then the release. |

No checkout keeps the token. Only one job can write to the repository: the last job of `staple.yml`, which creates the release on Linux.

An ordinary branch push starts none of them.

With the Developer ID secrets, `release.yml` signs the DMG and sends it to Apple's notary service without waiting. Apple's check can take minutes or days. When it is over, Apple calls the webhook named in `release.yml`, which starts `staple.yml`. That run finds the DMG's artifact on Linux first, so a call with an unknown id starts no Mac. It staples Apple's ticket on a Mac and keeps the DMG as an artifact for 14 days; for a tag, a last job publishes it to GitHub Releases. If the webhook does not start it, start `staple.yml` by hand with the submission's id from the log of `release.yml` or from `xcrun notarytool history`. Without the secrets, `release.yml` stops. The secret names are listed at the top of each workflow.

## Updates

The app updates itself through Sparkle 2 (what the user sees: [the Mac app](4-app.md#update)). Its `Info.plist` names the feed, `https://github.com/wowgs/echofox/releases/latest/download/appcast.xml`, and the public EdDSA key; Sparkle installs only an archive signed with the matching private key and a newer `CFBundleVersion`, and it requires the feed to be signed too (`SURequireSignedFeed`). For a tag, `staple.yml` runs `macos/make-appcast.sh` on the stapled dmg: it reads the versions from the app in it, signs the dmg and the feed with the secret `SPARKLE_ED_KEY`, and the release carries `appcast.xml` beside `EchoFox.dmg`. Sparkle's tools are those of the version that `Package.swift` links, pinned in `macos/pins.sh`; `build-app.sh` stops if `Package.resolved` names another one.

To try an update without the real feed, serve a release's dmg and a feed for it (`macos/make-appcast.sh EchoFox.dmg http://127.0.0.1:<port>/EchoFox.dmg`, signed with the key of the login keychain) with `python3 -m http.server`, and point the installed older app at it: `defaults write uk.wowgs.echofox updateFeedURL http://127.0.0.1:<port>/appcast.xml`. `defaults delete uk.wowgs.echofox updateFeedURL` goes back to the real feed.

## Diagrams

Each diagram in `img/` is a light SVG, the source, and a dark variant `<name>-dark.svg`. The docs show them with `<picture>`, so GitHub picks the one for the reader's theme. After you change a diagram, write the dark variants again:

```sh
python3 img/dark.py
```

The script swaps the colors from its table and stops on a color that the table does not have.

## Restart the working server

Between dictations, run:

```sh
pkill -TERM -f "gemma_voice.py --parent"
```

During shutdown, the server rejects new recordings, allows up to 200 seconds for the current one to finish (`STOP_WAIT_S` in `server/constants.py`), and stops its llama-server. The app starts the server again a second later. Dictation resumes when the model has loaded.
