# local-voice

Local dictation on a Mac: speech to text by Gemma 4 E4B in llama.cpp, on this Mac. `server/gemma_voice.py`, the dictation server, has the model registry, the chat context of the Claude Code session the text goes into, and the recordings; its clients only send the audio and show the text. A menu bar app that dictates into any app is planned.

## The dictation server

`server/gemma_voice.py` is the dictation server. It sends the audio to Gemma 4 E4B in llama.cpp's `llama-server` on this Mac, so the audio does not leave the computer.

Set it up once:

```
brew install llama.cpp
python3 -m venv server/.venv
server/.venv/bin/pip install -r server/requirements.txt
server/llama_launchd.sh install
server/launchd.sh install
```

`server/llama_launchd.sh install [MODEL.gguf [MMPROJ.gguf]]` runs `llama-server` as a launchd agent, `local-voice.llama-server`, on `127.0.0.1:8092` with a 16384-token context, one request at a time (`-np 1`) and every layer on the GPU. Without arguments it takes Gemma 4 E4B Q8_0 and its BF16 audio projector from `ggml-org/gemma-4-E4B-it-GGUF` in `~/models/gemma-4-E4B-gguf`. llama.cpp itself logs that its audio input is experimental. Its log is `~/Library/Logs/local-voice/llama-server.log`.

`server/launchd.sh install` runs the dictation server as the launchd agent `local-voice.gemma-voice` on `ws://127.0.0.1:8090`. Its log is `~/Library/Logs/local-voice/gemma-voice.log`. `server/launchd.sh status` and `server/launchd.sh uninstall` do what they say. To run it by hand instead: `server/.venv/bin/python server/gemma_voice.py`.

The server offers the models of the registry in the config file (`models`), and the client names the one it wants. Only the chosen model (`model`) is in memory: the server reads the choice from the same file, starts the launchd agent of that model's `llama-server` and stops the others; with no model chosen, none. The server takes one recording at a time; a second one waits until the first is done.

Gemma 4 takes at most 30 seconds of audio per request (model card; 25 tokens per second). The server cuts a recording after the stop, when its length is known: into equal pieces as close to `pieceSeconds` (20 s) as possible, none longer than 30 s, each cut moved to the quietest moment within `cutSearchSeconds` (3 s) of its equal point. A frame of 30 ms is speech when it is louder than the higher of `thresholdDb` (-45 dBFS) and the recording's noise floor plus `speechAboveNoiseDb` (12 dB). These values are not tuned. Each piece is one request to `llama-server`'s `/v1/chat/completions`: the text (the chat context, then the prompt), then the piece's audio as `input_audio`, with thinking turned off (Gemma 4's template in llama.cpp otherwise lets the model think first and spend the token limit). `llama-server` keeps the text in its cache between the pieces (`cache_prompt`). Without a prompt of the model's own, the server uses Google's ASR template from the model card, and Google's sampler for Gemma 4 (temperature 1.0, top_k 64, top_p 0.95) unless the model's `options` set one. By that template, the model writes numbers as digits.

A piece's text is limited to 10 tokens per second of its audio plus 32 (`outputTokensPerSecond`, `outputTokensBase`; `maxOutputTokens` overrides it), so a model that never ends its text stops. If the client leaves before the last piece, the server closes the running request, and `llama-server` stops decoding it.

The server's settings are in the section `server` of the config file: `pieceSeconds`, `cutSearchSeconds`, `thresholdDb`, `speechAboveNoiseDb`, `outputTokensPerSecond`, `outputTokensBase`, `recordings`, `metrics`, `host`, `port`; `models` and `saveRecordings` are at the top of the file. A command-line flag of the same name (`--piece-seconds` and so on) wins over the file. The server reads only version 2 of the file. It watches the file: a change of a recording setting takes effect at the next recording, a change of `models` after the running recording, and a change of `host` or `port` ends the server after the running recording, so that launchd starts it again.

The server writes its metrics to `~/Library/Logs/local-voice/gemma-voice-metrics.jsonl`, one JSON object per line: each model request (prefill, cached and decode tokens and speeds from `llama-server`, time to the first token, wall time, audio length, `llama-server`'s physical footprint as macOS counts it), each recording (audio length, the wait after the stop) and each recording's levels. `server/metrics.py` prints a summary per model and the last requests.

To send a WAV file the way a client does, and see the timing:

```
server/.venv/bin/python server/try_wav.py recording.wav --language ru
```

To try the model without touching the dictation you use, `server/test_server.sh start` runs a second dictation server on `ws://127.0.0.1:8091` with its own `llama-server` on port 8093, and stops the working `llama-server` meanwhile, so only one model is in memory. `server/test_server.sh stop` ends both and restarts the working dictation server, which starts the chosen model's `llama-server` again. 

The tests need no model and no `llama-server`:

```
server/.venv/bin/python -m unittest discover -s server
```

## The config file

`~/.local-voice/config.json` (`LOCAL_VOICE_CONFIG` sets another path) is read by the dictation server and written by its clients:

```json
{
  "version": 2,
  "model": "Gemma E4B llama.cpp",
  "models": {
    "Gemma E4B llama.cpp": {"llamaServer": "http://127.0.0.1:8092", "launchd": "local-voice.llama-server",
                            "prompt": "Transcribe … in {LANGUAGE} …", "options": {"chatHistoryTokenBudget": 2000}}
  },
  "silenceStopSeconds": 60,
  "saveRecordings": true,
  "server": {"host": "127.0.0.1", "port": 8090, "pieceSeconds": 20}
}
```

- `model`: the chosen model, a name in `models`; `anthropic` or no name: none (then no model is in memory).
- `models`: the registry. Each model is a llama.cpp `llama-server` (`llamaServer`) with its launchd agent (`launchd`), the prompt the server gives the model (`prompt`; `{LANGUAGE}` becomes the dictation language; without it, Google's ASR prompt for Gemma 4) and the server's options for its recordings (`options`): `temperature`, `topK`, `topP`, `seed`, `maxOutputTokens`, the cutting of the recording: `pieceSeconds`, `cutSearchSeconds`, `thresholdDb`, `speechAboveNoiseDb`, and the chat history: `chatHistoryTokenBudget`, `chatTermsTokenBudget` (see below). The server refuses an unknown option. A model is added or removed here, with its `llama-server` (`server/llama_launchd.sh`).
- `silenceStopSeconds`: a client stops a recording after this long without speech that the server hears; 0 turns the stop off.
- `saveRecordings`: keep every recording (see below); on unless `false`.
- `server`: the dictation server's settings (see the server's section).

The server reads this file at each recording, so a change by hand also takes effect with the next recording.

`version` is the format of the file; the server reads only version 2.

## The chat context

Unless a model's `options` set `chatHistoryTokenBudget` to 0, the server puts Claude's final replies in the Claude Code session that the dictation goes into before the prompt, so the model knows the names and terms of the conversation (`server/context.py`). Only the last text of each finished turn (`stop_reason` `end_turn`) goes there: not your own messages (the model copied your previous dictation into the next transcription), and not Claude's texts between tool calls. Tool calls and their results, thinking, attachments, skill texts, subagents, and tags such as `<system-reminder>` are left out.

The session: a client that knows it names its session ids, and the server reads the newest transcript `~/.claude/projects/<project>/<session id>.jsonl` among them. A client that knows only the app with the input box names the app's bundle id, and the server reads the newest transcript whose last line came from that app; that is a guess, because the newest session of the app need not be the one on the screen.

The server keeps the newest replies that fit `chatHistoryTokenBudget` (Gemma tokens, default 1000) and their Latin-script terms, the most frequent first, that fit `chatTermsTokenBudget` (default: a tenth of `chatHistoryTokenBudget`), oldest reply first.

## The recordings

The server keeps every recording and never deletes one. Each recording gets a folder `~/speech/recordings/<YYYY-MM-DD>/<HHMMSS>-<id>/` (the server's `recordings` setting sets another root):

- `mic.wav`: the whole recording as the client sent it (16 kHz, 16-bit, mono), before it is cut into pieces.
- `adapter.json`: the model, the client, the stop reason, the errors, each piece's text and the whole text, the Claude Code session the text went to (its transcript file), the chat context, and the Mac's input volume and input device at the start of the recording. The text you correct and send is your next message in that transcript; `~/speech/tools/link_corrections.py` writes it to `correction.json` in the recording folder.
- `text-before-audio.txt`, `piece-N.wav`, `pieces.jsonl` and `audio.json`: the text the model got before the audio, each piece's audio as the model got it, each piece's text and tokens, and the levels.

Speech takes about 115 MB per hour. `"saveRecordings": false` turns this off.

## The protocol

A client speaks this protocol with `server/gemma_voice.py`, on one WebSocket, `ws://127.0.0.1:8090`:

- It sends `{"type":"start","model":"<name>","language":"ru","sampleRate":16000,"encoding":"pcm_s16le","client":"<name>","sessions":["<session id>",…]}`; a client that knows no session sends `"app":"<bundle id>"` instead. Without `model`, the server takes the registry's first model. An experiment may also send `prompt` and `options`, which override the model's.
- Then it sends binary messages of audio: 16-bit little-endian PCM, 16 kHz, mono. When the recording stops, it sends `{"type":"stop","reason":"user"}` (or `silence`, `max_duration`, `error`).
- The server sends `{"type":"speech"}` while it hears speech, `{"type":"text","text":"…"}` for each finished piece of text, in order, and `{"type":"error","message":"…"}` for errors. After the last piece it sends `{"type":"done"}` and closes the connection.
