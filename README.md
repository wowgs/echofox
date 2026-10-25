# Local Voice

**Speak. Get text. Stay on your Mac.**

Local dictation for the apps you already use, with conversation context to help recognize names and terms.

![Tap a key, speak, and get text in your app. Recognition runs on your Mac, with conversation context when available.](img/how-it-works.svg)

[Download for Mac](https://github.com/wowgs/local-voice/releases) · [User guide](docs/reference/4-app.md) · [Documentation](docs/README.md)

- **Works offline** after the model download. Audio and transcripts stay on your Mac.
- **Uses your conversation** in Claude Desktop's Code tab and Telegram Desktop. Dictation works in other apps without context.
- **Ready to set up.** llama.cpp and all dependencies are included; choose a model in the app and click **Download**.

## Get started

Apple Silicon · macOS 13+ · 16 GB memory minimum · 5.6–9 GB model download. [Model choices and compatibility](docs/reference/4-app.md#requirements-and-model-choices).

1. Download **LocalVoice.dmg**, open it, and drag Local Voice to **Applications**.
2. Open the app and allow **Microphone** and **Accessibility** access.
3. Choose the recommended model variant and click **Download**.

## Speak into any text field

Click where you want to write. Tap **right Option**, speak, then tap it again. Local Voice inserts the text.

Use **right Command** for private dictation: no conversation context and no saved recording. Change keys, microphone, language, and model in **Settings…** in the menu bar.

Regular dictations save audio, transcripts, and any conversation context locally by default. You can turn saving off in Settings. [What gets saved](docs/reference/5-recordings.md).

## Learn more

| | |
|---|---|
| [Using Local Voice](docs/reference/4-app.md) | Controls, settings, text insertion, and reviewing recordings. |
| [Conversation context](docs/reference/3-context.md) | Supported apps and how adapters work. |
| [How recognition works](docs/reference/1-server.md) | Gemma 4 E4B, audio processing, and the local server. |
| [Build and develop](docs/reference/7-development.md) | Build from source and run tests. |

[All documentation](docs/README.md) · [Product plans](docs/ideas.md)
