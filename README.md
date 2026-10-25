# Local Voice

Local Voice is dictation for the Mac. Tap a key, speak, and tap the key again. The text appears where your cursor was, in any app.

A speech model runs on your Mac and turns the speech into text. The model is Gemma 4 E4B in [llama.cpp](https://github.com/ggml-org/llama.cpp). *The audio and the text do not leave your Mac.*

The model also reads the conversation that you write into, for example a Claude Code session or a Telegram chat. So it writes the names and terms of that conversation correctly.

## How it works

![You tap the key in any app and speak. Local Voice reads the chat of that app, records your voice, and writes the text into the text box where the cursor was](img/how-it-works.svg)

1. You tap the key in any app and speak. You do not switch to Local Voice.
2. Local Voice records your voice and reads the chat of that app.
3. Gemma 4 writes the text, with the names and terms of the chat.
4. The text appears in the text box where your cursor was.

Adapters are the parts of Local Voice that read the chat of one app. Local Voice has adapters for Claude and Telegram, and you can add your own.

## While you speak

![A dictation of 35 seconds: piece 1 goes to the model while you speak, and piece 2 goes after the stop](img/dictation-timeline.svg)

The model works on the first pieces while you still speak. After you stop, only the last piece is left, so the text comes soon after the stop. The bars show the order of the work, and their lengths are an example.

## Privacy

- Local Voice and its model run on your Mac. They send no analytics and no metrics.
- The only connection to the internet is the download of the model, when you ask for it.
- A second key starts a private dictation. The app then reads nothing on the screen, and nothing of the dictation is saved.
- Other recordings are saved on your Mac, so that you can correct them and train the model on your voice later. You can turn this off in the settings.

## Requirements

- A Mac with Apple Silicon and macOS 13 or later.
- Memory and disk space for one of the two models:

| Model | Download | Memory while it runs | For a Mac with |
|---|---|---|---|
| Q4_0, smaller and faster | 5.6 GB | about 7 GB | 16 GB |
| Q8_0, the most exact | 9.0 GB | about 10 GB | 24 GB or more |

At the first start, the app recommends the model for your Mac. You can change the model later in the settings.

Local Voice was tested on an Apple M5 with 24 GB and macOS 27.

## Install

1. Download `LocalVoice.dmg` from the [Releases](https://github.com/wowgs/local-voice/releases) of this repository.
2. Open it and drag Local Voice to the Applications folder.
3. Open Local Voice. Its icon appears in the menu bar.
4. Allow Microphone and Accessibility when macOS asks. The app needs Accessibility for the key and to insert the text.
5. Choose the model in the window that opens, and click Download.

## Use

- Tap the right Option key to start a dictation. Tap it again to stop.
- Tap the right Command key for a private dictation.
- The menu bar icon shows the state: recording, private recording (purple), waiting for the text, or a problem.
- Settings… in the menu opens the settings: the keys, the microphone, the language, the model and the adapters.
- Label Recordings… in the menu lets you correct the text of saved recordings, for training the model later.

## Documentation

How Local Voice works, in detail:

1. [The dictation server](docs/reference/1-server.md): the pieces, the speech detection, the prompt, the models.
2. [The config file](docs/reference/2-config.md): every key of `~/.local-voice/config.json`.
3. [The chat context](docs/reference/3-context.md): how adapters find the conversation, and how to write one.
4. [The menu bar app](docs/reference/4-app.md): the keys, where the text goes, the settings window, labeling.
5. [The recordings and labels](docs/reference/5-recordings.md): what the server saves, and where.
6. [The protocol](docs/reference/6-protocol.md): the messages between the app and the server.
7. [Build, tests and tools](docs/reference/7-development.md): build from source, the tests, the test server.

The design, in Russian:

- [What and why](docs/design/1-what-and-why.md), [Requirements](docs/design/2-requirements.md), [Constraints](docs/design/3-constraints.md), [HLD](docs/design/4-hld.md), [UI](docs/design/5-ui.md), [Future ideas](docs/design/6-future-ideas.md), [Distribution](docs/design/7-distribution.md).
- [Ideas](docs/ideas.md): the work that is left, by priority.
- [Optional adapters](docs/adapters/1-idea.md), [LoRA training](docs/lora-training/1-idea.md), [Dictation terms](docs/dictation-terms/1-untitled.md).
