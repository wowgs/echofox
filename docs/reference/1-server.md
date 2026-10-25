# Speech processing

The dictation server turns microphone audio into text. The Mac app handles recording and text insertion; the server handles speech detection, conversation context, and requests to the model.

![Long recordings are processed in pieces while you speak, leaving less work after you stop.](../../img/dictation-timeline.svg)

The server runs as the launchd agent `echofox.gemma-voice`, listening on `ws://127.0.0.1:8090`. It sends audio to a separate `llama-server` process, which runs Gemma 4 E4B on the Mac's GPU.

See also: [configuration](2-config.md), [conversation context](3-context.md), [protocol](6-protocol.md), and [development](7-development.md).

## From a recording to text

1. The app streams microphone audio: 16 kHz, 16-bit, mono.
2. Silero VAD detects speech as the audio arrives. A voice activity detector (VAD) distinguishes speech from silence. The server uses Silero v6.2.3 through onnxruntime.
3. Once 20 seconds have accumulated since the previous cut, the server finds the quietest point between seconds 12 and 15. It sends the completed piece to the model and keeps at least 5 seconds for the next piece.
4. When recording stops, the server splits the remaining audio into roughly 15-second pieces. No piece exceeds the model's 30-second input limit.
5. Pieces with less than 0.3 seconds of detected speech are skipped. This prevents the model from inventing text or copying context when the input is silent.
6. Each piece becomes a separate model request: conversation context, recognition prompt, and audio. Two requests can run at once.
7. The server removes configured hesitation sounds, such as “э” and “мм” in Russian, and returns the text in recording order.

While you speak, the server also prepares the shared context and prompt in the model's two processing slots. This reduces repeated work when the audio is ready. The server handles one recording at a time; a second waits for the first to finish.

Speech detection also drives the app's silence timeout. Audio levels are used to choose cut points and report recording quality, not to decide whether speech is present.

## Guard against runaway output

The output limit is 20 tokens per second of detected speech. A token is a word or part of a word. In a local sample of 346 speech pieces collected on 22–25 October 2026, the maximum observed rate was 10.4 tokens per second.

The server discards output that reaches the limit. This is a safeguard against runaway generation, not proof that every discarded result is wrong.

## Recognition prompt

The prompt combines the model's template with notes for the selected language. The Gemma template requests speech recognition, punctuation, and capitalization; it produces numbers as digits. Language notes live in `server/languages.json`.

A custom model prompt replaces only the template. Language notes are still appended. The default sampling settings are temperature 1.0, top_k 64, and top_p 0.95.

## Models and memory

The model registry is stored in the config file. Each model has its own launchd agent, but only the selected model runs. Switching models starts the selected agent and stops the others.

`server/catalog.json` defines supported models: audio limits, languages, prompt templates, sampling defaults, runtime arguments, and downloadable variants. Gemma 4 E4B has two variants, Q4_0 and Q8_0; Q8_0 is the catalog default.

Both variants come from a pinned revision of `ggml-org/gemma-4-E4B-it-GGUF` on Hugging Face. They share the audio encoder file. Downloads support resuming and SHA-256 verification. See [the download protocol](6-protocol.md#download-a-model).

The server writes the selected model's launchd agent. Changes to the variant or model folder wait until the current recording finishes before restarting `llama-server`.

Gemma runs at `http://127.0.0.1:8092` with:

| Setting | Reason |
|---|---|
| 16,384-token context, split into two 8,192-token slots | Process two audio pieces concurrently. |
| All model layers on the GPU | Use Apple Silicon's GPU for inference. |
| `--swa-full` | Let later pieces reuse the shared prompt text. |
| `--cache-ram 0` | Disable the separate RAM prompt cache, which caused memory growth and swapping in a local run. |

## Privacy and telemetry

Recognition uses local connections. Model downloads are the only external connections made by the current app and server, and require a user request.

`server/vad.py` disables onnxruntime telemetry before loading the runtime. `llama-server` runs with `--offline` and `--no-webui`.

Regular recordings may include audio, transcripts, and conversation context. See [what is saved](5-recordings.md); private dictation skips this storage.

## Settings and constants

Each setting belongs to the server, a model, an adapter, a language, or the app. Its component supplies the default; the config file stores user overrides.

Safety limits and values chosen through measurements are constants rather than user settings. Audio cutting, the minimum speech duration, and output limits are defined in `server/tuning.py` and `server/catalog.json`.

## Code map

| File | Purpose |
|---|---|
| `gemma_voice.py` | Starts the server. |
| `protocol.py` | One connection of a client: the start, the recording, the context. |
| `audio.py` | The loudness of each 30 ms frame, the cuts, WAV files. |
| `vad.py` | Silero VAD on the audio as it arrives. |
| `dictation.py` | The prompt, the context and one request for each piece. |
| `llama.py` | The models in `llama-server` and their launchd agents. |
| `tuning.py` | The table of the settings and constants of a recording. |
| `settings.py` | The config file: reading, checking, updates from older versions. |
| `catalog.json`, `catalog.py` | The model catalog. |
| `languages.json`, `languages.py`, `fillers.py` | The languages: names, notes, hesitation sounds. |
| `adapters/`, `plugins/` | The adapters that give [the chat context](3-context.md). |
| `recordings.py` | [The recordings](5-recordings.md). |
| `metrics.py` | The metrics file and its summary. |
| `constants.py` | Shared constants, paths and names that the server, its scripts and its tests share. |

## Logs and metrics

- The log of the server is `~/Library/Logs/EchoFox/gemma-voice.log`. The log of `llama-server` is `~/Library/Logs/EchoFox/llama-server.log`.
- The server writes its metrics to `~/Library/Logs/EchoFox/gemma-voice-metrics.jsonl`, one JSON object on each line. Each request to the model has its tokens, speeds and times, the length of its audio and its speech, and the memory of `llama-server`. Each recording has its length and the wait after the stop.
- `server/.venv/bin/python server/metrics.py` prints a summary for each model and the last requests.
