# Structural refactoring

The structural problems that the architecture review of 2026-10-26 found in the app, the server and the build. They do not block a release; the release blockers of the same review are fixed separately. Each item names the evidence, so that it can be checked before the work starts. "Checked" means that the evidence was read in the code or reproduced; the rest comes from a reading of the code that was not reproduced.

Related: [design](design.md), [distribution](distribution.md), [plan](plan.md), [development](reference/7-development.md).

## The config has no single owner

- The app reads the config file from disk in 16 places (checked), for example on every menu update (`App.swift`). It writes the file in two ways: `App.write` logs, reports errors and refreshes the server; `FirstRunWindow` calls `Config.set` directly and drops a failed write. Nothing watches the file, so a hand edit of the hotkeys takes effect only after a restart.
- The server's `protocol.py` reads the default config file (`settings.config_file()`, lines 47 and 107, checked), so with `--config` (the test server, `launchd.sh install --config`) the info message and the guard of `remove` use the wrong file.
- Fix: one `ConfigStore` in the app that owns the config in memory, writes through one path and watches the file; on the server, the menu's model kept in memory (set by `ConfigWatcher`) instead of reading the file.

## Values defined twice, in Swift and in Python

- `ServerAgent.exitTimeoutSeconds = 210` copies `LAUNCHD_EXIT_TIMEOUT_S`, which `server/constants.py` derives from `TEXT_WAIT_S` (checked); the Swift test checks 210 against itself. Also copied: the port 8090, the recordings and labels folders, `pcm_s16le`, the config version, `serverConfigApplySeconds` against `CONFIG_CHECK_S`.
- The server's launchd plist is written by `server/launchd.sh` and by `ServerAgent.plist`, under the same label, so starting a bundled app on the development Mac replaces the development agent.
- Fix: a shared JSON file next to `shared/protocol-examples.json`, checked by both test suites; one generator of the plist; a separate label for the development agent. The app takes the folders from the server's info and keeps its own values only as a fallback.

## Server modules with several jobs

- `protocol.py` parses messages, builds the info, checks variant files on disk, runs download and remove, merges options and runs the whole recording (`Session`). Proposed split: `protocol.py` (dispatch and parsing), `session.py`, the variant operations beside `downloads.py`, `info` in its own module.
- The order in which option sources win is coded in four places (`protocol.parse_start`, `dictation.adapter_options`, `dictation.context_options`, `tuning.value`), plus `settings.model_defaults`. Fix: one `tuning.resolve`.
- `settings.py` imports `dictation` for `MAX_PROMPT` (checked), which loads the adapters, fillers and metrics into the settings module. Fix: move the constant to `constants` or `tuning`.
- `Models.get` calls `activate` on every recording, which runs `launchctl print` for each entry; `ConfigWatcher` keeps its own idea of the chosen model. Fix: `Models` keeps the active model's name and does nothing when it is already active.
- The five `migrate_N` functions repeat the read, check and atomic write; `SETTINGS` mirrors part of `tuning.KNOBS`, and `schema()` lists the storage keys again. Fix: one list of steps on the dict in memory, written once; drop the steps for versions 2 to 4 if no such files remain.

## Concurrency

- A plugin's `context` runs with `asyncio.to_thread` under `wait_for` (`protocol.py` line 299, checked). On timeout the thread keeps running in the default executor, the pool that every llama-server request uses (`dictation.run_blocking`). A plugin that always hangs costs one worker per recording. Fix: a small executor of its own for plugins, and no new call while the previous one runs.
- VAD, the levels and the recording file write run on the event loop for each audio message; the first `Stream()` loads the ONNX model on the loop; `catalog.json` and `languages.json` are parsed on every call. Fix: load the VAD model at startup, cache the catalog.

## App logic that the tests cannot reach

- The insertion rules and the order of the insertion methods (`Inserter.swift`) are mixed with Accessibility calls, behind a `static let shared`.
- Which snapshot an app gets (`full`, `tree`, `lists`, `outline`) is decided in `App.swift`.
- "Which input does `config.microphone` mean" has three copies: `AudioInputs.chosen`, `MenuBar.isChosen` and `microphoneName`, `MicrophonePicker.chosenIsListed`.
- The settings views build config paths (`["models", name, "variant"]` and others), parse comma lists, read `label.json` on the main thread and guess units and folder settings from key names.
- Fix: move these into EchoFoxCore with tests: an insertion decision behind a small protocol, `ServerInfo.snapshotPlan(for:)`, one microphone resolver, config paths and list parsing in `SettingStore`, `Labeling.stats`. The server's `SettingInfo` sends a unit and `kind: "folder"`.
- Model downloads have two owners (`FirstRunModel` and `SettingsModel`). Fix: one `ModelDownloads` service that both windows observe.

## Build and supply chain

- The server's packages are pinned by version but not by hash, and source builds are allowed (`build-app.sh`, `tests.yml`); they install while the Developer ID key is in the keychain. Fix: hashes, `--require-hashes --only-binary :all:`.
- `actions/checkout` keeps the token with `contents: write` in `.git/config` during the build. Fix: `persist-credentials: false`, and publishing in a job of its own.
- The bundle cache key is only `hashFiles('macos/pins.sh')`; `build-app.sh` checks only that `llama-server` exists and that `dmgbuild` imports. Fix: the build script and `dmg/requirements.txt` in the key, and a stamp of the cmake flags and the requirements.
- The tests run on any Python 3.14 (`setup-python`), not on the 3.14.9 that ships. Fix: run the server tests with the bundled interpreter in `release.yml`.
- `staple.yml` starts a `macos-26` runner before it finds the artifact, so each forged call to the relay costs a macOS start. Fix: look up the artifact on `ubuntu-latest` first.
- The `.p12` file is not removed when a step of `release.yml` fails (no `trap`).
- `launchd.sh` reads `constants.py` through `.venv` before it checks that `.venv` exists; `test_server.sh` runs `python3 -` instead of the venv's Python.

## Dead code and leftovers

- Unused: `ServerInfo.encoding` (the app writes `pcm_s16le` itself), `maxRecordingSeconds`, `Model.maxAudioSeconds`, `StopReason.maxDuration`, `TapKey.key(of:)`, `TapKey.running`, `Tuning.menuErrorChars`, the always empty `hints`; on the server `GROUPS`, `OWNERS`, `ADAPTER_KNOBS`, `Plugin.module`; `build/icon-info.plist`.
- Used only by tests: `metrics.path()`, `Vad.probabilities`, `ECHOFOX_LAUNCHCTL`, the module global `protocol.Stream`. Fix: pass them in through constructors.
- `which_session.py`, a development tool, ships in the bundle; `macos/prototypes/transparent-realitykit-overlay.swift` belongs to no target.
- Stale: `Dictation.swift` and `Messages.swift` point to `server/gemma_voice.py` for the protocol; the docstrings of `gemma_voice.py` and `settings.py` repeat the docs and are behind them.
- Vendor names in the core's comments (`adapters/__init__.py`, `adapters/markdown.py`); `try_wav.py --session` and `sandbox.py` know the Claude plugin. The app never sends hints, so the Claude plugin's "named sessions" claim is reachable only through `try_wav.py`. Fix: a generic `--hint key=value`, each plugin sets up its own test environment, and a decision on the named-sessions path.

## Keep

- Plugin isolation: `adapters._guarded`, the manifest checks and one surest claimant, so a broken plugin stops only itself.
- One table of settings on the server (`tuning.KNOBS`), sent to the app in the info; the settings window has no list of its own.
- The protocol contract (`shared/protocol-examples.json`), checked from both sides.
- `Config.set` and `JSONEdit`: an edit changes one value in the text and checks the result.
- Downloads: a `.part` file, a SHA-256 check, resume with a Range request.
