# Local Voice

Local Voice is a Mac dictation app with local speech recognition and conversation context.

![Local Voice records speech in the app you're using, adds conversation context when available, and inserts the recognized text.](img/how-it-works.svg)

Tap the right Option key, speak, and tap it again to insert the text into the app you're using.

Speech recognition runs on your Mac. The app includes [llama.cpp](https://github.com/ggml-org/llama.cpp) and downloads the Gemma 4 E4B speech model for you at first launch. After that, you can dictate offline. Your audio and transcripts stay on your Mac.

In supported apps, Local Voice can also use the current conversation to help recognize names and technical terms. Elsewhere, it works without conversation context.

## Get started

You'll need an Apple Silicon Mac running macOS 13 or later, with at least 16 GB of memory and enough disk space for a model. The app has been tested on an Apple M5 with 24 GB of memory running macOS 27; older macOS versions have not been verified.

**The packaged app includes everything needed to run recognition:** llama.cpp, the dictation server, Python, and its dependencies. You don't need to install Homebrew, use the terminal, or find model files yourself.

1. Download `LocalVoice.dmg` from [Releases](https://github.com/wowgs/local-voice/releases), open it, and drag Local Voice to Applications.
2. Open Local Voice and grant Microphone and Accessibility permissions when prompted. Its icon appears in the menu bar.
3. In the setup window, choose one of the two model variants and click **Download**. The app recommends a variant for your Mac and shows download progress.
4. Once the download finishes, click a text field and tap **right Option** to dictate.

The large model files are downloaded separately so app updates don't require downloading them again. Local Voice handles their download, verification, and setup.

### Choose a model variant

Both variants use the same speech model at different levels of compression:

| Variant | Download size | Approximate memory use | Suggested Mac memory |
|---|---|---|---|
| Q4_0 — smaller download | 5.6 GB | 7 GB | 16 GB |
| Q8_0 — less compressed | 9.0 GB | 10 GB | 24 GB or more |

You can change the variant later in **Settings → Model**. These memory figures are approximate; a systematic comparison of recognition quality and speed is still pending.

## Dictate

1. Click where you want the text to appear.
2. Tap and release the **right Option** key to start recording.
3. Speak, then tap the same key again to stop.

Local Voice processes the recording and inserts the text. If you move to another text field while speaking, the text goes to the field focused when the result arrives. If insertion isn't possible, the text is copied to the clipboard and the menu tells you.

| Control | What it does |
|---|---|
| Right Option | Start or stop a regular dictation. |
| Right Command | Start or stop a private dictation: no conversation context and no saved recording. |
| **Settings…** in the menu bar | Change the keys, microphone, language, model, adapters, and recording preferences. |
| **Label Recordings…** in the menu bar | Review saved recordings and correct their transcripts to prepare examples for future model training. |

The menu bar icon shows when Local Voice is recording, processing speech, or needs attention. Private recording is shown in purple.

## Conversation context

Local Voice uses adapters to read the conversation you're dictating into. An adapter connects one supported app to the speech model; it provides recent messages and terms that may help with recognition.

The built-in adapters support:

- **Claude Desktop's Code tab:** reads the matching Claude Code session's local transcript and uses recent assistant responses as context.
- **Telegram Desktop:** reads messages loaded in the open chat. Enable this adapter in Settings to allow it to read the chat.

If no adapter can identify the conversation, dictation continues without context. Private dictation always skips adapters. See [how context works and how to add an adapter](docs/reference/3-context.md).

## Privacy and saved recordings

Speech recognition happens locally. Local Voice sends no analytics or telemetry; it connects to the internet to download a model when you request one.

**Regular dictations are saved by default**, including audio, transcripts, and any conversation context supplied to the model. They are stored in `~/speech/recordings/` and are not automatically deleted. Turn off **Save recordings** in Settings if you don't want to keep future recordings.

**Private dictation** uses no conversation context and saves no recording or transcript. Use the right Command key to start one.

You can review and correct saved recordings with **Label Recordings…**. This prepares data for future training; correcting a transcript does not automatically train the model. See [recordings and labels](docs/reference/5-recordings.md) for storage locations and file details.

## Speech processing

The menu bar app records your microphone and passes the audio to a local dictation server. The server splits longer recordings into short pieces and sends them to Gemma 4 E4B through llama.cpp.

Processing starts while you're still speaking, which reduces the work left after you stop. For the processing timeline and implementation details, see [the dictation server](docs/reference/1-server.md).

## Documentation

Start with the [documentation index](docs/README.md) to find a guide by task.

- **Using the app:** [controls and settings](docs/reference/4-app.md), [saved recordings](docs/reference/5-recordings.md), [conversation context](docs/reference/3-context.md).
- **Developing:** [build and test](docs/reference/7-development.md), [speech processing](docs/reference/1-server.md), [configuration](docs/reference/2-config.md), [protocol](docs/reference/6-protocol.md).
- **Product plans, in Russian:** [purpose and design](docs/design/1-what-and-why.md), [remaining work](docs/ideas.md), [proposed personal training](docs/lora-training/1-idea.md).
