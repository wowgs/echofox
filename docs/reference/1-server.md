# The dictation server

The dictation server turns a recording into text. It runs on your Mac as the launchd agent `local-voice.gemma-voice` and listens on `ws://127.0.0.1:8090`. The menu bar app is its client. The [protocol](6-protocol.md) describes what the two send to each other.

The server does not run the model itself. It sends each piece of audio to `llama-server`, the server of [llama.cpp](https://github.com/ggml-org/llama.cpp), which runs Gemma 4 E4B on the GPU of the Mac.

Related docs: [the config file](2-config.md), [the chat context](3-context.md), [the recordings](5-recordings.md), [tests and tools](7-development.md).

## From a recording to text

![A dictation of 35 seconds: one piece goes to the model while you speak, and the rest goes after the stop](../../img/dictation-timeline.svg)

The model starts on the first piece while you still speak, so after the stop only the last piece is left.

1. The app sends the audio while you speak: 16 kHz, 16-bit, mono.
2. Silero VAD marks the speech in the audio as it arrives. A voice activity detector (VAD) is a small model that tells speech from silence. The server uses release v6.2.3 of [Silero VAD](https://github.com/snakers4/silero-vad) (MIT license) in onnxruntime. The VAD is the only judge of speech in the server. When it hears speech, the server sends the app a `speech` message. The app uses these messages to stop a recording after a long silence.
3. When 20 s are heard after the last cut, the server cuts a piece. The cut is at the quietest moment of the 3 s before the 15th second, so that it does not fall inside a word. The piece is 12 to 15 s long, and the audio after it is never shorter than 5 s.
4. At the stop, the server cuts the rest into equal pieces as close to 15 s as it can. No piece is longer than the model takes: 30 s for Gemma 4.
5. A piece with less than 0.3 s of speech does not go to the model. On silence, the model writes text of its own or copies the chat context.
6. Each piece is one request to `llama-server`. The request holds the chat context, the prompt and the audio of the piece. The pieces do not depend on each other, so two of them run at once, one in each slot of `llama-server`.
7. The server takes the hesitation sounds of the language out of the text, for example "э" and "мм" in Russian. Then it sends the text of each piece to the app, in the order of the pieces.

While you speak, the server sends the chat context and the prompt to `llama-server` alone. `llama-server` keeps them in the cache of its slots. After the stop, each piece then processes only its audio.

The server takes one recording at a time. A second recording waits until the first one is done.

## The limit of the text

The text of a piece can have at most 20 tokens for each second of speech in the piece. A token is a part of a word. In 346 pieces with speech (2026-10-22 to 2026-10-25), the most was 10.4 tokens per second. A text that reaches the limit is not speech that the model heard. The server drops it. The limit also stops a model that never ends its text.

## The prompt

The prompt is the template of the model with the name of the language, and then the notes of the language.

- The template of Gemma 4 is the speech recognition prompt from Google's model card, with one more rule: punctuation and capital letters. With this template, the model writes numbers as digits.
- The notes of a language are in `server/languages.json`. The note for Russian says that the speaker often uses the imperative mood.
- You can replace the template of a model in the settings window or in [the config file](2-config.md). The notes of the language always follow it.

The sampler is the one that Google gives for Gemma 4: temperature 1.0, top_k 64, top_p 0.95.

## The models

The config file has a registry of models. Each model is one `llama-server` with its own launchd agent. Only the model that you choose is in memory. When you choose another model, the server starts the launchd agent of that model and stops the others.

The model catalog, `server/catalog.json`, gives what each model needs: the longest audio of one request, the languages that its prompt names, its prompt templates, its sampler, its limit of the text, the arguments of its `llama-server`, and its variants.

A variant is one quantization of the model with its files. Gemma 4 E4B has two: Q4_0 and Q8_0 (the default). Both come from the Hugging Face repository `ggml-org/gemma-4-E4B-it-GGUF` at a fixed revision, and the catalog has the size and the SHA-256 of each file. The files are in the models folder (`server.modelsFolder`), in a folder with the name of the repository: `gemma-4-E4B-it-GGUF/`. The two variants share their audio encoder file.

The server downloads the files of a variant when a client asks it to, and it can remove them again ([the protocol](6-protocol.md#download-a-model)). It continues a download that stopped, and it checks the SHA-256 of each file.

The server writes the launchd agent of the chosen model itself: `llama-server` with the files of the variant, the address of the model and the arguments of the catalog. When you choose another variant or another models folder, the server writes the agent again and restarts `llama-server` after the recording that runs.

For Gemma 4 E4B, `llama-server` runs on `127.0.0.1:8092` with these arguments:

- A context of 16384 tokens in two slots of 8192 tokens, one for each of the two pieces that run at once.
- Every layer on the GPU.
- `--swa-full`: the full cache of the sliding-window layers of Gemma. Without it, a later piece cannot take the shared text from the cache.
- `--cache-ram 0`: no prompt cache in RAM. The default of `llama-server` is 8 GB. It kept old requests and went to swap on a Mac with 24 GB within a day (2026-10-19).

## No telemetry

The server, `llama-server` and the packages in the app send no analytics and no metrics. onnxruntime, which runs Silero VAD, has Microsoft's telemetry on by default, also on macOS: `server/vad.py` turns it off before onnxruntime loads (`ORT_DISABLE_TELEMETRY=1`). `llama-server` runs with `--offline` and `--no-webui`. The only connection outside the Mac is a model download that you ask for.

## Settings and constants

Each setting has one owner: the server, a model, an adapter, a language or the app. The owner gives the default. You change a setting only at its owner, in [the config file](2-config.md) or in the settings window.

A number that guards against mistakes of the model, or a number that was chosen by a measurement, is a constant and not a setting. The cutting of pieces, the speech gate and the limit of the text are constants. Their values and the reasons for them are in `server/tuning.py` and in `server/catalog.json`.

## The files

| File | What it does |
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
| `constants.py` | The numbers, paths and names that the server, its scripts and its tests share. |

## Logs and metrics

- The log of the server is `~/Library/Logs/local-voice/gemma-voice.log`. The log of `llama-server` is `~/Library/Logs/local-voice/llama-server.log`.
- The server writes its metrics to `~/Library/Logs/local-voice/gemma-voice-metrics.jsonl`, one JSON object on each line. Each request to the model has its tokens, speeds and times, the length of its audio and its speech, and the memory of `llama-server`. Each recording has its length and the wait after the stop.
- `server/.venv/bin/python server/metrics.py` prints a summary for each model and the last requests.
