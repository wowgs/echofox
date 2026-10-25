# Local Voice

Local Voice is dictation for the Mac. Tap a key, speak, and tap the key again. The text appears where your cursor was, in any app.

A speech model on your Mac turns the speech into text: Gemma 4 E4B in [llama.cpp](https://github.com/ggml-org/llama.cpp). The audio and the text do not leave your Mac.

The model also reads the conversation that you write into, for example a Claude Code session or a Telegram chat. With it, the model writes the names and terms of the conversation the way the conversation writes them.

## How it works

![The app records and inserts the text, the dictation server cuts the audio and adds the chat context, and llama-server runs the model](img/how-it-works.svg)

Three programs run on your Mac, and each one does one job.

- **The Local Voice app** lives in the menu bar. It starts and stops a recording when you tap a key, and it sends the audio to the dictation server. When the text comes back, the app puts it where your cursor was.
- **The dictation server** cuts the audio into pieces and skips pieces without speech. It asks an adapter for the latest messages of the conversation, and it sends each piece to the model with them. An adapter is a small plugin that knows one app, for example Claude or Telegram.
- **llama-server** runs the model on the GPU of the Mac.

## One dictation

![A dictation of 35 seconds: piece 1 goes to the model while you speak, piece 2 after the stop, and the text comes 2.3 s after the stop](img/dictation-timeline.svg)

The model works on the first piece while you still speak, so after the stop it has only the last piece to do.

On an Apple M5 with 24 GB, the model takes 2.35 s for a piece of about 13 s (the median of 417 pieces, 2026-10-22 to 2026-10-25). For recordings of 20 to 40 s, the text came 2.25 s after the stop (the median of 64 recordings).

## Privacy

- The model, the server and the app run on your Mac. With the default config, every connection goes to 127.0.0.1: from the app to the server, and from the server to `llama-server`.
- A second key starts a private dictation. The app then reads nothing on the screen, and the server saves nothing and writes no text into its log.
- The server saves every other recording, so that you can label it and train the model on your voice later. You can turn this off in the settings window.

## What you need

- A Mac with Apple Silicon and macOS 13 or later. Local Voice was tested only on an Apple M5 with 24 GB and macOS 27.
- About 9.7 GiB of memory while the model is loaded: 7.5 GiB for the model and 2.1 GiB for the rest of `llama-server` (measured on the M5).
- About 9 GB of disk for the model files. The recordings take about 231 MB for each hour of speech.
- [Homebrew](https://brew.sh) for llama.cpp, Python and the download tool.

An estimate for other Macs, not measured: with 16 GB of memory, the model fits, but little memory is left for other apps. With 8 GB, it does not fit.

## Install

1. Install llama.cpp, Python and the Hugging Face download tool:

   ```
   brew install llama.cpp python hf
   ```

2. Download the model and its audio encoder into `~/models/gemma-4-E4B-gguf`:

   ```
   hf download ggml-org/gemma-4-E4B-it-GGUF gemma-4-E4B-it-Q8_0.gguf mmproj-gemma-4-E4B-it-BF16.gguf --local-dir ~/models/gemma-4-E4B-gguf
   ```

3. Set up the dictation server, then start the model and the server as launchd agents. They start again at each login.

   ```
   python3 -m venv server/.venv
   server/.venv/bin/pip install -r server/requirements.txt
   server/llama_launchd.sh install
   server/launchd.sh install
   ```

4. Create a self-signed code-signing certificate named "Local Voice Dev" in your login keychain (Keychain Access, Certificate Assistant, Create a Certificate). Without it, macOS asks for the permissions again after each build.
5. Build the app and start it:

   ```
   macos/build-app.sh
   open macos/build/LocalVoice.app
   ```

6. Allow Microphone and Accessibility when macOS asks. The app needs Accessibility for the keys and to insert the text.

## Use

- Tap the right Option key to start a dictation, and tap it again to stop.
- Tap the right Command key for a private dictation.
- If you do not speak for 60 s, the recording stops by itself.
- The menu bar icon shows the state: recording, private recording (purple), waiting for the text, or a problem.
- Settings… in the menu (⌘,) opens the settings window: the keys, the microphone, the language, the model and its prompt, and the adapters.
- Label Recordings… in the menu lets you correct the text of saved pieces. The labels are for training the model on your voice later.

## Documentation

How Local Voice works, in detail:

1. [The dictation server](docs/reference/1-server.md): the pieces, the speech detection, the prompt, the models.
2. [The config file](docs/reference/2-config.md): every key of `~/.local-voice/config.json`.
3. [The chat context](docs/reference/3-context.md): how adapters find the conversation, and how to write one.
4. [The menu bar app](docs/reference/4-app.md): the keys, where the text goes, the settings window, labeling.
5. [The recordings and labels](docs/reference/5-recordings.md): what the server saves, and where.
6. [The protocol](docs/reference/6-protocol.md): the messages between the app and the server.
7. [Tests and tools](docs/reference/7-development.md): the tests, the test server, the update of the working server.

The design, in Russian:

- [What and why](docs/design/1-what-and-why.md), [Requirements](docs/design/2-requirements.md), [Constraints](docs/design/3-constraints.md), [HLD](docs/design/4-hld.md), [UI](docs/design/5-ui.md), [Future ideas](docs/design/6-future-ideas.md), [Distribution](docs/design/7-distribution.md).
- [Ideas](docs/ideas.md): the work that is left, by priority.
- [Optional adapters](docs/adapters/1-idea.md), [LoRA training](docs/lora-training/1-idea.md), [Dictation terms](docs/dictation-terms/1-untitled.md).
