# Configuration

Most settings are available in the app. For manual changes, edit `~/.echofox/config.json`. The app writes this file and the server reloads it automatically. Set `ECHOFOX_CONFIG` to use another path.

Related docs: [the dictation server](1-server.md), [the chat context](3-context.md), [the menu bar app](4-app.md).

## Example

```json
{
  "version": 11,
  "model": "Gemma E4B llama.cpp",
  "language": "ru",
  "microphone": "builtin",
  "dictationKey": "rightOption",
  "privateDictationKey": "rightCommand",
  "silenceStopSeconds": 60,
  "adapters": {"claude-code": {"enabled": true}, "claude-chat": {"enabled": true}, "telegram": {"enabled": true, "chatHistoryTokenBudget": 600}},
  "models": {
    "Gemma E4B llama.cpp": {"catalog": "gemma-4-e4b", "llamaServer": "http://127.0.0.1:8092",
                            "options": {"topK": 40}}
  },
  "languages": {"ru": {"fillers": ["э", "мм"]}},
  "server": {"host": "127.0.0.1", "port": 8090, "maxRecordingSeconds": 1800, "saveRecordings": true}
}
```

This example enables the three built-in adapters and overrides several defaults. Use only the entries you need. Missing settings use their defaults. The server logs an invalid setting and uses its default. If the file is not valid JSON, the server keeps its current settings. A key that a version does not know is left out and kept in the file; a wrong value is replaced by its default, and the server logs it. The rules for changing the file over versions are in the [design](../design.md#the-config-file-over-versions); the keys and their types are in `shared/config.schema.json`.

## Settings reference

| Key | Purpose |
|---|---|
| `version` | The config's format, 11. It changes only for a change that an older version would read wrong. The server brings a file of an older format to 11 once at its start and keeps the old file as `config.json.v<N>.bak`; a file of a newer format is read key by key. Format 11 left out a model's `launchd`. Format 10 left out a model's `prompt` and the Russian `notes` that were copies of format 9's defaults. Format 9 has the recording's time limit in seconds (`maxRecordingSeconds`). Format 8 split the adapter `claude` into `claude-code` and `claude-chat`. |
| `model` | Selected model: a name in `models`. With no model selected, no model is kept in memory. |
| `models` | Model registry; see [model entries](#model-entries) below. |
| `language` | Recognition language, for example `ru` or `en`. An empty value lets the model infer the spoken language. If omitted, the app uses the first macOS language. |
| `microphone` | `builtin` (default) keeps using the built-in microphone when a headset connects. `system` follows the macOS input selection. A device UID selects a specific microphone; if unavailable, the app falls back to the built-in microphone. |
| `dictationKey`, `privateDictationKey` | The keys to tap: `rightOption` (the default for dictation), `rightCommand` (the default for private dictation), `rightShift`, `rightControl`, or `none`. |
| `silenceStopSeconds` | The app stops a recording after this many seconds without speech. It must be more than 0. |
| `adapters` | Adapter enablement (`enabled`) and context settings. See [the chat context](3-context.md). |
| `languages` | Your changes to a language: `notes`, the lines added to the prompt, and `fillers`, hesitation sounds to remove. `"*"` holds the notes of every language; `{LANGUAGE}` in them is replaced with the language's name, and English speech gets none of them. An empty list turns one off. The defaults are in `server/languages.json`. |
| `server` | The settings of the server: `maxRecordingSeconds` (1800 by default), `modelIdleSeconds` (600 by default: the model leaves memory after that long without a dictation; 0 keeps it), `saveRecordings`, `recordings`, `labeled`, `modelsFolder` (the model files, by default `~/Library/Application Support/EchoFox/models`), `metrics`, `host`, `port`. |

## Model entries

Each entry in `models` has a name used by the top-level `model` setting.

| Field | Purpose |
|---|---|
| `catalog` | Model definition in `server/catalog.json`. |
| `llamaServer` | Model server address. The server starts the llama-server of an address on this Mac itself. |
| `variant` | Optional quantization, such as `q4_0` or `q8_0`; defaults to the catalog selection. |
| `prompt` | Optional replacement prompt template. Language notes are still appended. |
| `options` | Sampling overrides: `temperature`, `topK`, `topP`, and `seed`. |

The default entry, `gemma-e4b`, inherits missing fields. For example, `"models": {"gemma-e4b": {"variant": "q4_0"}}` selects a variant without repeating the default model definition.

## When a change takes effect

The server checks the file every 2 seconds.

- Recording settings apply to the next recording.
- Changes to `models`, `model`, or `modelsFolder` apply after the current recording.
- Changing `host` or `port` stops the server after the current recording; the app then starts it again.

The server has no command-line flags for settings. `--config` only names the file; `--ignore-selection`, for the test server, makes it ignore the menu's choice of model.
