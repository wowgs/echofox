# WebSocket protocol

Connect to `ws://127.0.0.1:8090`. Each connection handles one operation: a recording, a server-info request, a model download, or a model removal.

Runnable message examples live in `shared/protocol-examples.json`. Both `server/test_contract.py` and the app’s `echofox-tests` check this shared contract.

## A recording

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../img/protocol-dark.svg">
  <img alt="A recording on one connection: start, audio, stop, then the texts and done" src="../../img/protocol.svg">
</picture>

The client streams audio while recording. The server returns recognized pieces in recording order.

1. The client sends the start message:

   ```json
   {"type": "start", "model": "<name>", "language": "ru", "sampleRate": 16000, "encoding": "pcm_s16le",
    "client": "<name>", "snapshot": {}, "hints": {}}
   ```

   - `snapshot` is the focus snapshot (see [the chat context](3-context.md)). `hints` carries client information and is passed unchanged to adapters.
   - If `model` is omitted, the server uses the first model in the registry.
   - `"private": true` makes a private dictation: the server saves nothing, runs no adapter and writes no text into its log. The app sends no snapshot with it.
   - An experiment can also send `prompt` and `options`. These override model settings. The app never sends them.
2. The client sends the audio in binary messages: 16-bit little-endian PCM, 16 kHz, mono.
3. When the recording stops, the client sends `{"type": "stop", "reason": "user"}`. The other reasons are `silence`, `max_duration` and `error`.

The server sends:

| Message | When |
|---|---|
| `{"type": "speech"}` | While it hears speech. |
| `{"type": "stopped", "reason": "max_duration"}` | The recording reached its time limit. The server takes no more audio. |
| `{"type": "text", "text": "…"}` | One piece has finished. Results arrive in recording order. |
| `{"type": "error", "message": "…"}` | Something went wrong. Invalid incoming text messages produce an error response without necessarily ending the recording. |
| `{"type": "done"}` | After the last piece. Then the server closes the connection. |

## Server information

Instead of the start message, the client can send `{"type": "info"}`. The server replies and closes the connection. The field outline below is schematic, not valid JSON; see the shared examples for complete messages:

```text
{"type": "info", "interface": 2, "adapterInterface": 2, "sampleRate": 16000, "encoding": "pcm_s16le",
 "textWaitSeconds": 180, "maxRecordingSeconds": 1800.0,
 "languages": [{"code", "name", "notes", "fillers"}],
 "adapters": [{"name", "enabled", "builtin", "version", "author", "source", "description", "apps",
               "electronTree", "reads", "screen", "context", "error"}],
 "models": ["<name>"],
 "model": {"name", "catalog", "prompt", "maxAudioSeconds", "variant",
           "variants": [{"id", "name", "bytes", "memoryBytes", "downloaded", "downloading"}]},
 "settings": [{"key", "owner", "group", "kind", "title", "advanced", "default", "value", "min", "max",
               "minExclusive", "maxExclusive", "help"}]}
```

The response describes audio format, timeouts, languages, adapters, the selected model, and editable settings. `models` lists registry names. `model.variants` includes download size, estimated memory use, and download status for each variant. `model.variant` identifies the active variant.

`settings` describes each setting that the settings window can show and change:

| Field | What it means |
|---|---|
| `owner` | Config destination: `server` (the section `server` of the config), `model` (the model's `options`) or `adapter` (the adapter's entry). |
| `kind` | `number`, `integer`, `boolean` or `string`. |
| `title`, `help` | The name and the description in the window, in plain English for the user. `help` is empty when the title says it all. |
| `advanced` | Present for a setting of the Advanced section. |
| `default` | The component’s default. For an adapter setting, the default of each adapter is in its `context`. |
| `value` | For server and model settings, present only when the effective value is not the default. Adapter settings never have it: the app reads the user's value from the config. |
| `min`, `max` | The range of a number. `minExclusive` and `maxExclusive` mean that the value cannot be equal to the bound. |

Runtime constants are excluded.

## Download a model

The client sends `{"type": "download", "catalog": "gemma-4-e4b", "variant": "q4_0"}`. The server downloads the files of that variant that are not in the models folder yet. The URL, the size and the SHA-256 of each file are in `server/catalog.json`.

| The server sends | When |
|---|---|
| `{"type": "progress", "bytes": 1048576, "total": 5582359648}` | At most every 0.5 s. `bytes` includes files already present. |
| `{"type": "downloaded"}` | All required variant files are available. Then the server closes the connection. |
| `{"type": "error", "message": "…"}` | The download stopped. Then the server closes the connection. |

- Closing the connection does not cancel the download. A new `download` request for the same variant attaches to the existing job.
- `{"type": "cancel"}` on the connection stops the download. Partial data is kept so a later request can resume.
- A file is written as `<file>.part`. It is renamed only after size and SHA-256 verification. A hash mismatch deletes the partial file and reports an error.
- Downloads require free disk space for the remaining files plus 1 GB.

## Remove a model

The client sends `{"type": "remove", "catalog": "gemma-4-e4b", "variant": "q4_0"}`. The server deletes the files of that variant that no other downloaded variant uses. The active variant cannot be removed. It answers `{"type": "removed", "bytes": 4590807392}` or an error, and closes the connection.
