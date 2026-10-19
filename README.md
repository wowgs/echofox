# local-voice

Local dictation on a Mac: speech to text by Gemma 4 E4B in llama.cpp, on this Mac. `server/gemma_voice.py`, the dictation server, has the model registry, the chat context of the Claude Code session the text goes into, and the recordings; its clients only send the audio and show the text. The menu bar app in `macos/` dictates into any app.

## The dictation server

The server's code, in `server/`: `gemma_voice.py` starts it; `protocol.py` is one client connection (the start, the session of a recording, the context step); `audio.py` the levels, the cutting and WAV; `dictation.py` the prompt and the text before the audio and each piece's request; `llama.py` the model interface (`llama.Model`), the models in `llama-server` and their launchd agents; `tuning.py` the one table of a recording's knobs (names, types, ranges, defaults); `settings.py` the config file; `constants.py` every number, path and label the server, its scripts and its tests share; `adapters/` the core of the adapters, their plugin loader (`registry.py`) and `markdown.py`, Markdown to plain prose for plugins of chat apps (with markdown-it-py); `plugins/` the built-in adapter plugins, one per platform; `recordings.py` the recordings (every file of a recording); `metrics.py` writes the metrics and, run as a script, sums them up.

`server/gemma_voice.py` is the dictation server. It sends the audio to Gemma 4 E4B in llama.cpp's `llama-server` on this Mac, so the audio does not leave the computer.

Set it up once:

```
brew install llama.cpp
python3 -m venv server/.venv
server/.venv/bin/pip install -r server/requirements.txt
server/llama_launchd.sh install
server/launchd.sh install
```

`server/llama_launchd.sh install [MODEL.gguf [MMPROJ.gguf]]` runs `llama-server` as a launchd agent, `local-voice.llama-server`, on `127.0.0.1:8092` with a 16384-token context in two slots (`-np 2`, 8192 tokens each), every layer on the GPU, and the full cache of Gemma's sliding-window layers (`--swa-full`), and no prompt cache in RAM (`--cache-ram 0`: the dictation server uses only each slot's own cache). Without arguments it takes Gemma 4 E4B Q8_0 and its BF16 audio projector from `ggml-org/gemma-4-E4B-it-GGUF` in `~/models/gemma-4-E4B-gguf`. llama.cpp itself logs that its audio input is experimental. Its log is `~/Library/Logs/local-voice/llama-server.log`.

`server/launchd.sh install` runs the dictation server as the launchd agent `local-voice.gemma-voice` on `ws://127.0.0.1:8090`. Its log is `~/Library/Logs/local-voice/gemma-voice.log`. `server/launchd.sh status` and `server/launchd.sh uninstall` do what they say. To run it by hand instead: `server/.venv/bin/python server/gemma_voice.py`.

The server offers the models of the registry in the config file (`models`), and the client names the one it wants. Only the chosen model (`model`) is in memory: the server reads the choice from the same file, starts the launchd agent of that model's `llama-server` and stops the others; with no model chosen, none. The server takes one recording at a time; a second one waits until the first is done.

Gemma 4 takes at most 30 seconds of audio per request (model card; 25 tokens per second). The server cuts a recording after the stop, when its length is known: into equal pieces as close to `pieceSeconds` (15 s) as possible, none longer than 30 s, each cut moved to the quietest moment within `cutSearchSeconds` (3 s) of its equal point. A frame of 30 ms is speech when it is louder than the higher of `thresholdDb` (-45 dBFS) and the recording's noise floor plus `speechAboveNoiseDb` (12 dB). These values are not tuned. Each piece is one request to `llama-server`'s `/v1/chat/completions`: the text (the chat context, then the prompt), then the piece's audio as `input_audio`, with thinking turned off (Gemma 4's template in llama.cpp otherwise lets the model think first and spend the token limit). While you speak, the server sends the text alone to `llama-server` (`warmText`, on by default), so that `llama-server` has it in its cache (`cache_prompt`) and after the stop each piece processes only its audio. The pieces do not depend on each other, so they go to `llama-server` at once, piece i to slot (i − 1) mod the slot count, and their texts go to the client in order. A slot is warmed once the recording is long enough for a piece in it. Without a prompt of the model's own, the server uses Google's ASR template from the model card, and Google's sampler for Gemma 4 (temperature 1.0, top_k 64, top_p 0.95) unless the model's `options` set one. By that template, the model writes numbers as digits.

A piece's text is limited to 10 tokens per second of its audio plus 32 (`outputTokensPerSecond`, `outputTokensBase`; `maxOutputTokens` overrides it), so a model that never ends its text stops. If the client leaves before the last piece, the server closes the running request, and `llama-server` stops decoding it.

The server's settings are in the section `server` of the config file: `pieceSeconds`, `cutSearchSeconds`, `thresholdDb`, `speechAboveNoiseDb`, `outputTokensPerSecond`, `outputTokensBase`, `maxRecordingSeconds` (the longest recording, 1800 s by default), `warmText`, `recordings`, `metrics`, `host`, `port`; `models`, `adapters` and `saveRecordings` are at the top of the file. Their types, ranges and defaults are in `server/tuning.py` and `server/settings.py`. A command-line flag of the same name (`--piece-seconds` and so on) wins over the file; a value out of range is refused. The server reads only version 3 of the file, and turns a version-2 file into version 3 at its start, with every built-in plugin enabled. It watches the file: a change of a recording setting takes effect at the next recording, a change of `models` after the running recording, and a change of `host` or `port` ends the server after the running recording, so that launchd starts it again.

The server writes its metrics to `~/Library/Logs/local-voice/gemma-voice-metrics.jsonl`, one JSON object per line: each model request (prefill, cached and decode tokens and speeds from `llama-server`, time to the first token, wall time, audio length, `llama-server`'s physical footprint as macOS counts it), each recording (audio length, the wait after the stop) and each recording's levels. `server/metrics.py` prints a summary per model and the last requests.

To send a WAV file the way a client does, and see the timing (it goes to the test server below; the working one it reaches only with `--working`):

```
server/.venv/bin/python server/try_wav.py recording.wav --language ru
```

To try the model without touching the dictation you use, `server/test_server.sh start` runs a second dictation server on `ws://127.0.0.1:8091` with its own `llama-server` on port 8093 (the ports are in `server/constants.py`), and stops the working dictation server (after its running recording) and the working `llama-server` meanwhile, so only one model is in memory and nothing starts the working one again. Your dictation is off until `server/test_server.sh stop`, which ends both test processes and starts the working dictation server again; it starts the chosen model's `llama-server`. 

The tests need no model and no `llama-server`. They run in a sandbox (`server/sandbox.py`, which every test module imports first): a temporary home folder and paths, a fake `launchctl`, and the ports of the working and the test servers refused, so they never touch your config, recordings, metrics, plugins or servers:

```
server/.venv/bin/python -m unittest discover -s server
```

## The config file

`~/.local-voice/config.json` (`LOCAL_VOICE_CONFIG` sets another path) is read by the dictation server and written by its clients:

```json
{
  "version": 3,
  "model": "Gemma E4B llama.cpp",
  "language": "ru",
  "adapters": {"claude": {"enabled": true}},
  "models": {
    "Gemma E4B llama.cpp": {"llamaServer": "http://127.0.0.1:8092", "launchd": "local-voice.llama-server",
                            "prompt": "Transcribe … in {LANGUAGE} …", "options": {"chatHistoryTokenBudget": 2000}}
  },
  "silenceStopSeconds": 60,
  "saveRecordings": true,
  "server": {"host": "127.0.0.1", "port": 8090, "pieceSeconds": 15}
}
```

- `model`: the chosen model, a name in `models`; `anthropic` or no name: none (then no model is in memory).
- `models`: the registry. Each model is a llama.cpp `llama-server` (`llamaServer`) with its launchd agent (`launchd`), the prompt the server gives the model (`prompt`; `{LANGUAGE}` becomes the dictation language; without it, Google's ASR prompt for Gemma 4) and the server's options for its recordings (`options`): `temperature`, `topK`, `topP`, `seed`, `maxOutputTokens`, the cutting of the recording: `pieceSeconds`, `cutSearchSeconds`, `thresholdDb`, `speechAboveNoiseDb`, and the chat history: `chatHistoryTokenBudget`, `chatTermsTokenBudget` (see below). The server refuses an unknown option. A model is added or removed here, with its `llama-server` (`server/llama_launchd.sh`).
- `language`: the dictation language, a code such as `ru` or `en`; the client sends it in the start message. Without it, the menu bar app takes the first language of macOS. An empty value: the speech's own language.
- `silenceStopSeconds`: a client stops a recording after this long without speech that the server hears; 0 turns the stop off.
- `microphone`: what the menu bar app records. `builtin` (the default): the Mac's own microphone, whatever macOS's input is, so a headset that connects does not take the recording over; `system`: macOS's input; or a device's UID, one microphone. A chosen microphone that is gone falls back to the built-in one. The menu's Microphone submenu writes it, and the Input volume slider under it is the microphone's own volume, the same control as in macOS's Sound settings (shared by every app).
- `saveRecordings`: keep every recording (see below); on unless `false`.
- `fillers`: the hesitation sounds the server takes out of the text, by language, for example `{"ru": ["э", "мм"]}`. The model writes a speaker's hesitations as words, so they go after each piece; the record keeps the model's own text as `raw` in `pieces.jsonl`. Without the key the built-in list of the language applies (`server/fillers.py`; Russian: э, э-э, а-а, м, м-м, эм, ам, хм); an empty list turns the removal off for that language. A sound counts in any length ("ээ", "ммм", "э-э-э"), and one right after a number stays ("5 мм").
- `server`: the dictation server's settings (see the server's section).

The server reads this file at each recording, so a change by hand also takes effect with the next recording.

`version` is the format of the file; the server reads only version 3.

## The context

Without an enabled adapter, dictation runs in the base mode: the model gets only the prompt. With one, and unless a model's `options` set `chatHistoryTokenBudget` to 0, the server puts the messages of the place the dictation goes into (a session with an assistant, a messenger chat, a mail thread) before the prompt, so the model knows the names and terms used there. Adapters find that place and read it.

An adapter is a plugin: a folder with `adapter.json`, its manifest (`name`, `version`, `author`, `source`, `description`, `interface`: 2, `apps`: the bundle ids whose focus it reads, `electronTree`: whether the app builds its accessibility tree only on request, `reads`: the files it reads, `screen`: what of the screen it needs from its apps; `"lists"`, the rows of the lists in the focused window, is the one kind the app sends, and a manifest asking for another is refused), and `adapter.py`, a module with one subclass of `adapters.Adapter`. An adapter serves any app whose content tells what you write about: a chat with an assistant, a messenger, mail, a document. Its interface (version 2):

```
claim(focus, hints)   -> Claim(adapter, confidence 0..1, reason) | None
context(focus, hints) -> {about, messages: [{from, text}] newest first, terms?, source?, details?} | None
clean(text)           -> str   ("" drops the message)
```

`focus` is the snapshot, `hints` what the client sent. `about` says to the model where you write ("a Telegram chat with Anna"), `from` who wrote each message, `terms` the place's own names and words; `source` and `details` go only to the record (`adapter.json`, `chat`). The built-in plugins are in `server/plugins/`; your own go to `~/Library/Application Support/Local Voice/adapters/` (`LOCAL_VOICE_PLUGINS` sets another folder), and one with the name of a built-in plugin replaces it. A plugin works only when the config enables it: `"adapters": {"claude": {"enabled": true}}`. A plugin's folder is a Python package, so `adapter.py` can import its other modules. The server checks only that the manifest reads, that its interface is 2 and that the module has its class; a plugin you add is yours to trust. The server loads the plugins again when a plugin's files change. The menu bar app asks the server which adapters are enabled, and takes the full focus snapshot and builds an Electron app's tree only for their apps.

The client sends a focus snapshot in the start message: the frontmost app, its window, the element with the cursor and its ancestors, the nearest web area's URL and title, and the app's child processes with their working folders. It holds service fields only, never the text of input fields. `macos/` builds it (the `FocusSnapshot` library). The server asks every adapter whether the snapshot is its own and how sure it is, and the surest one finds the conversation. If none claims it, the dictation runs without context.

The built-in plugins, one per platform:

- `claude` (`server/plugins/claude/`): Anthropic's Claude apps. In Claude Desktop's Code tab, the web area has the URL `https://claude.ai/epitaxy/local_<id>`; Desktop's record of that session (`~/Library/Application Support/Claude/claude-code-sessions/…/local_<id>.json`) names the Claude Code transcript (`cliSessionId`). Without a record, the web area's title finds the transcript of that title, but only if exactly one transcript has it. The record's format is Desktop's own and not documented. Without the Code tab in the snapshot (no Accessibility permission, the Chat tab, another window), the plugin does not claim Desktop. A client that names its Claude Code sessions gets the newest of them. From a transcript, only the last text of each finished turn (`stop_reason` `end_turn`) goes to the model: not your own messages (the model copied your previous dictation into the next transcription), and not Claude's texts between tool calls. Tool calls and their results, thinking, attachments, skill texts, subagents, and tags such as `<system-reminder>` are left out. Its `clean` turns Claude's Markdown into plain prose with `adapters/markdown.py`, which any plugin can use. markdown-it-py parses the text (CommonMark with GitHub's tables), so code blocks, HTML and bare URLs go by the parser's tokens. Inline code stays only when it is a term (an identifier, a file, a flag, a short command), the words of links, bold and lists stay, and each heading, list item and table row becomes a sentence.
- `telegram` (`server/plugins/telegram/`): Telegram Desktop. Its manifest asks for `"screen": ["lists"]`, so for Telegram Desktop the app sends the rows of the window's lists. The open chat's messages are the list above the input box; each row is the message's accessible text, lines that Telegram Desktop writes in a fixed order (the speaker's own messages start with "Seen" or "Not seen", then the sender, the text, and a status line with the time), and the plugin keeps the sender and the text. The chat's name comes from the window title. The context is what the window has loaded, the newest messages of the chat. A config upgrade never enables a plugin that reads the screen: you turn it on in the menu.
- Plugins for OpenAI's apps (Codex, ChatGPT) and Google's (Antigravity, Gemini) are planned, in the same kind of slot.

Adapters never guess a session from the app alone: the newest session of an app is often another one that runs in the background. If no session is found exactly, the dictation runs without context.

Every adapter has its own `clean`: the server passes each message through it before the message goes to the model, and takes the terms from the cleaned messages.

An adapter's entry in the config may set its own budgets, which win over the model's options for that adapter's context: `"adapters": {"telegram": {"enabled": true, "chatHistoryTokenBudget": 600}}`; any other key in the entry is an error. The server keeps the newest replies that fit `chatHistoryTokenBudget` (Gemma tokens, default 1000) and their Latin-script terms, the most frequent first, that fit `chatTermsTokenBudget` (default: a tenth of `chatHistoryTokenBudget`), oldest reply first.

To check by hand which conversation a dictation would get, without audio: build the snapshot tool once, then run it and put the cursor in an input box within 5 seconds. The process that runs it needs the Accessibility permission.

```
swift build -c release --package-path macos
macos/.build/release/lv-snapshot --delay 5 | server/.venv/bin/python server/which_session.py
```

For an adapter that reads the screen, `--lists` adds the rows of the window's lists, and `--app <bundle id>` takes the snapshot of that running app at once, without bringing it to the front: `lv-snapshot --app com.tdesktop.Telegram --lists --out snapshot.json`. Such a snapshot holds the window's text, so keep it private.

## The menu bar app

`macos/` holds the menu bar app, Local Voice. A tap of the right Option starts a dictation, and the next tap stops it. The app takes the focus snapshot at the tap, records the microphone, and sends both to the dictation server. When the text comes back, the app puts it into the input box that had the focus at the tap.

Where the text goes: into the input box that has the focus when the text comes back, if there is one, because you may click into a box while you speak. Otherwise into the box that had the focus at the tap: its app comes to the front again. Otherwise the text goes to the clipboard, and the menu says so. Into a box, the app tries Accessibility first: it replaces the selected text. If the app refuses that, or the text does not appear, the app pastes the text with Cmd+V and then restores the clipboard.

The menu is the app's configuration; a dictation is the hotkey's, and the icon shows its state (recording, waiting, a problem). When a permission is missing, the menu offers to allow it. Its submenus choose the model, the language, the microphone and the adapters, and the app writes the choice in the config file (`model`, `language`, `microphone`, `adapters`). The app changes only that value in the text of the file, so the file keeps its order and layout. The languages are the ones the server's prompt names; the server sends them in its info. An adapter's error shows under its name. The app stops a recording by itself after `silenceStopSeconds` without speech, and waits up to 180 seconds for the text after the stop. Its log is `~/Library/Logs/local-voice/app.log`. The log has the length of each text, never the text.

**Labeling.** Label Recordings… in the menu opens a window of cards, one for each piece of a saved recording that is not labeled yet, the newest first. A piece is one model request (`piece-N.wav`, up to 30 s), so it is one example. The window opens in the lower right corner, a third of the screen wide and a bit under half of it high; once you move or resize it, it keeps that frame. The card plays the piece and shows the text that went into the input box (the hesitation sounds already out); you correct it into what you meant to write: no hesitation sounds (э, мм, а-а), no repeated words, and after a slip only what you corrected it to. A model trained on these labels learns to leave such things out itself; the server's `fillers` stay as a second net. `label.json` says so: `"convention": "clean"`. Save and Next (⌘↩) keeps it as `verified`; Unusable (⌘U) keeps it as `unusable` (a TV, noise, another voice: no example); Later (⌘L) leaves it for next time; Stop (Esc) closes the window. A labeled piece goes to `~/speech/labeled/<day>/<id>/piece-N/` (the config's `labeled` sets another folder), apart from the server's recordings: `audio.wav` and `text-before-audio.txt` (copies, so the piece stays whole when recordings are deleted) and `label.json` (your text, the model's text and its own text before the hesitation sounds went, the status, the model, the language, the time). The app finds the recordings in the config's `server.recordings` (default `~/speech/recordings`).

The app's code, in `macos/Sources`: `LocalVoice/` the app (`App.swift` connects the parts: `Permissions`, `Server` for what the server offers, `TapKey`, `MenuBar`, `Dictation`, `Recorder`, `Inserter` and `Clipboard`); `LocalVoiceCore/` its logic that needs no screen and no permission (the config, the protocol's messages, the hotkey's logic, the app's numbers in `Tuning.swift`); `FocusSnapshot/` the focus snapshot. `swift run --package-path macos lv-tests` checks `LocalVoiceCore` (an executable, since XCTest and Swift Testing come only with Xcode).

Build it and start it:

```
macos/build-app.sh
open macos/build/LocalVoice.app
```

At the first start, macOS asks for two permissions: Microphone, and Accessibility (System Settings, Privacy & Security). The app needs Accessibility for the hotkey, the snapshot and the insertion. The build is signed ad hoc, so the signature changes with each build, and macOS may ask for the permissions again after a rebuild.

## The recordings

The server keeps every recording and never deletes one. Each recording gets a folder `~/speech/recordings/<YYYY-MM-DD>/<HHMMSS>-<id>/` (the server's `recordings` setting sets another root):

- `mic.wav`: the whole recording as the client sent it (16 kHz, 16-bit, mono), before it is cut into pieces.
- `adapter.json`: the model, the client, the stop reason, the errors, each piece's text and the whole text, the context (`chat`: the adapter, what it read, its details, the number of messages and terms), and the Mac's input volume and input device at the start of the recording. With the Claude plugin, `chat.details` has the Claude Code session and its transcript file; the text you correct and send is your next message in that transcript, and `~/speech/tools/link_corrections.py` writes it to `correction.json` in the recording folder.
- `text-before-audio.txt`, `piece-N.wav`, `pieces.jsonl` and `audio.json`: the text the model got before the audio, each piece's audio as the model got it, each piece's text and tokens, and the levels.

Speech takes about 115 MB per hour. `"saveRecordings": false` turns this off.

## The protocol

A client speaks this protocol with `server/gemma_voice.py`, on one WebSocket, `ws://127.0.0.1:8090`:

- It sends `{"type":"start","model":"<name>","language":"ru","sampleRate":16000,"encoding":"pcm_s16le","client":"<name>","snapshot":{…},"hints":{…}}`. `snapshot` is the focus snapshot (see the context); `hints` is what the client knows, and goes to the adapters as it is. Without `model`, the server takes the registry's first model. An experiment may also send `prompt` and `options`, which override the model's.
- Then it sends binary messages of audio: 16-bit little-endian PCM, 16 kHz, mono. When the recording stops, it sends `{"type":"stop","reason":"user"}` (or `silence`, `max_duration`, `error`).
- Instead of a start message, a client may send `{"type":"info"}`: the server answers `{"type":"info","interface":2,"adapterInterface":2,"sampleRate":16000,"encoding":"pcm_s16le","textWaitSeconds":180,"maxRecordingSeconds":1800,"languages":[{"code","name"}],"adapters":[{"name","enabled","builtin","version","author","source","description","apps","electronTree","reads","screen","error"}]}` and closes the connection. The menu bar app takes the audio format, the wait for the text, the languages and the adapters from it.
- The server sends `{"type":"speech"}` while it hears speech, `{"type":"stopped","reason":"max_duration"}` when a recording reaches `maxRecordingSeconds` (it takes no more audio), `{"type":"text","text":"…"}` for each finished piece of text, in order, and `{"type":"error","message":"…"}` for errors (a text message that is not a JSON object is one; the recording goes on). After the last piece it sends `{"type":"done"}` and closes the connection.
- Examples of every message are in `shared/protocol-examples.json`; `server/test_contract.py` and the app's `lv-tests` both check them.
