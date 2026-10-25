<img src="img/echofox-icon.png" alt="EchoFox fox wearing a headset" width="88" align="left" hspace="16">

# EchoFox

**Speak your language. Keep your English terms.**

[Download for Mac](https://github.com/wowgs/echofox/releases) · [User guide](docs/reference/4-app.md) · [Docs](docs/README.md)

<br clear="left">

Local dictation for Mac, built for conversations where your language and English technical terms naturally mix.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="img/how-it-works-dark.svg">
  <img alt="Tap a key, speak, and get text in your app. Recognition runs on your Mac, with conversation context when available." src="img/how-it-works.svg">
</picture>

## Made for the way you speak

*«Посмотри этот pull request и проверь, почему падает build».* Sound familiar?

| 💬 Conversation first | 🌍 Your language | ✦ Your English terms |
| :--- | :--- | :--- |
| Recent messages come **before your audio**, so the model has context before it transcribes. | Your chosen language is part of the prompt. The conversation gives the model more examples of how you speak. | Names, tools, and identifiers get a **separate term list**, helping the model recognize the words you use. |

Context is available in **Claude Desktop's Code tab** and **Telegram Desktop**. In other apps, EchoFox works without conversation context. [More about context and adapters →](docs/reference/3-context.md)

## All on your Mac

Gemma 4 E4B runs locally through bundled llama.cpp. Pick a model variant in the app, click **Download**, and you're ready to dictate offline.

Tap <kbd>⌥</kbd> **right Option** to speak; tap again to insert the text.

Use <kbd>⌘</kbd> **right Command** for **Ultra Private Dictation**: the same local recognition, without conversation context or saved recordings.

Regular dictations save audio, text, and context locally by default; saving can be turned off in Settings. [Recording privacy →](docs/reference/5-recordings.md)

Apple Silicon · macOS 13+ · 16 GB memory minimum. [Setup and model choices →](docs/reference/4-app.md#requirements-and-model-choices)

[How recognition works](docs/reference/1-server.md) · [Build and develop](docs/reference/7-development.md) · [All documentation](docs/README.md)
