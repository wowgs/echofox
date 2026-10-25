# The config file

The config file is `~/.local-voice/config.json`. The environment variable `LOCAL_VOICE_CONFIG` sets another path. The app writes the file, and the server reads it. You can also edit it by hand.

Related docs: [the dictation server](1-server.md), [the chat context](3-context.md), [the menu bar app](4-app.md).

## An example

```json
{
  "version": 7,
  "model": "Gemma E4B llama.cpp",
  "language": "ru",
  "microphone": "builtin",
  "dictationKey": "rightOption",
  "privateDictationKey": "rightCommand",
  "silenceStopSeconds": 60,
  "adapters": {"claude": {"enabled": true}, "telegram": {"enabled": true, "chatHistoryTokenBudget": 600}},
  "models": {
    "Gemma E4B llama.cpp": {"catalog": "gemma-4-e4b", "llamaServer": "http://127.0.0.1:8092",
                            "launchd": "local-voice.llama-server", "options": {"topK": 40}}
  },
  "languages": {"ru": {"fillers": ["э", "мм"]}},
  "server": {"host": "127.0.0.1", "port": 8090, "maxRecordingMinutes": 30, "saveRecordings": true}
}
```

A key that the file does not have takes its default. A wrong key or value goes to the log of the server, and the server uses the default instead.

## The keys

| Key | What it sets |
|---|---|
| `version` | The format of the file. The server reads version 7. At its start, it updates an older file to version 7 and keeps the order of the file. |
| `model` | The model that you dictate with: a name in `models`. Without one, no model is in memory. |
| `models` | The registry of models. Each entry has `catalog` (its entry in `server/catalog.json`), `llamaServer` (its address), `launchd` (its agent), and optionally `variant` (the quantization: `q4_0` or `q8_0`, by default the catalog's), `prompt` (your own template) and `options` (its advanced settings: `temperature`, `topK`, `topP`, `seed`). |
| `language` | The language of the dictation, for example `ru` or `en`. An empty value means the language that you speak. Without the key, the app takes the first language of macOS. |
| `microphone` | `builtin`, the microphone of the Mac (the default), so that a headset does not take the recording over. `system` follows the input of macOS. A device UID chooses one microphone. If the chosen microphone is not connected, the app records the built-in one. |
| `dictationKey`, `privateDictationKey` | The keys to tap: `rightOption` (the default for dictation), `rightCommand` (the default for private dictation), `rightShift`, `rightControl`, or `none`. |
| `silenceStopSeconds` | The app stops a recording after this many seconds without speech. It must be more than 0. |
| `adapters` | The adapters that work (`enabled`) and their advanced settings. See [the chat context](3-context.md). |
| `languages` | Your changes to a language: `notes`, the lines added to the prompt, and `fillers`, the hesitation sounds that the server takes out. An empty list turns one off. The defaults are in `server/languages.json`. |
| `server` | The settings of the server: `maxRecordingMinutes` (30 by default), `saveRecordings`, `recordings`, `labeled`, `modelsFolder` (the model files, by default `~/Library/Application Support/Local Voice/models`), `metrics`, `host`, `port`. |

## When a change takes effect

The server checks the file every 2 seconds.

- A change of a recording setting takes effect at the next recording.
- A change of `models`, `model` or `modelsFolder` takes effect after the recording that runs.
- A change of `host` or `port` ends the server after the recording that runs. Then launchd starts it again.

The server has no command-line flags for settings. `--config` only names the file.
