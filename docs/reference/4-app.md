# Use the Mac app

Local Voice lives in the menu bar. Start and stop dictation from the keyboard, without switching away from the app you're writing in.

See also: [configuration](2-config.md), [saved recordings](5-recordings.md), and [build from source](7-development.md#build-from-source).

## Dictate

1. Click a text field.
2. Tap and release **right Option** to start recording.
3. Speak, then tap the same key to stop.

Use **right Command** for private dictation. It skips conversation context and saves no audio or transcript. The app still identifies the input field so it can insert your text. The recording icon is purple.

A tap means pressing and releasing the key on its own. Change either key in **Settings → General**.

Recording stops automatically after 60 seconds without speech by default. The server also enforces a recording limit of 30 minutes by default. Both limits are configurable.

## Where the text goes

The app chooses the destination when the result arrives:

1. Use the currently focused text field. You can move to another field while speaking.
2. Otherwise, use the field focused when recording began, bringing its app to the front.
3. If neither works, copy the text to the clipboard and show a message in the menu.

Local Voice first tries Accessibility insertion, replacing selected text. If the target app refuses it or the text does not appear, Local Voice tries Cmd+V and restores the previous clipboard afterward.

After recording stops, the app waits up to 180 seconds for each next piece of text.

## Requirements and model choices

Use an Apple Silicon Mac with at least 16 GB of memory and macOS 13 or later. The app has been tested on an Apple M5 with 24 GB running macOS 27; older macOS versions have not been verified.

The two downloads are differently compressed variants of Gemma 4 E4B:

| Variant | Download size | Approximate memory use | Suggested Mac memory |
|---|---|---|---|
| Q4_0 | 5.6 GB | 7 GB | 16 GB |
| Q8_0 | 9.0 GB | 10 GB | 24 GB or more |

Memory figures are approximate. A systematic comparison of recognition quality and speed is still pending. Change the variant later in **Settings → Model**.

Model files are separate from the app, so updating the app does not require downloading them again. The server handles downloading, verification, and setup.

## The first start

The packaged app includes llama.cpp, Python, and the dictation server. You only choose a model variant and start its download in the app; no separate runtime or manual model installation is needed.

Grant **Microphone** and **Accessibility** permissions in macOS. Accessibility supports the dictation keys, conversation snapshots, and text insertion. Missing permissions appear in the menu; clicking one opens its page in System Settings.

If no model variant is downloaded, a setup window shows the download sizes and estimated memory use. It recommends Q4_0 for a 16 GB Mac or Q8_0 for a Mac with at least 24 GB. Choose a variant and click **Download**.

The server handles downloads, so they continue if you close the settings window.

## The menu and the settings window

The menu contains permissions while any are missing, microphone selection, input volume, **Label Recordings…**, **Settings…** (⌘,), and Quit. Input volume is the same control as in macOS Sound settings.

The icon shows recording, private recording, processing, or an error.

| Settings page | Use it to |
|---|---|
| General | Choose dictation keys and recording limits. |
| Microphone | Select the input device. |
| Language | Choose the language and edit language-specific prompt notes or hesitation sounds. |
| Model | Choose a downloaded variant, edit the prompt, change the model folder, or download and remove variants. |
| Individual adapters | Enable conversation context for a supported app and adjust its limits. |
| Recordings & Labels | Choose whether and where to save recordings and labels. |
| Diagnostics | Inspect server status and diagnostic information. |

Advanced sections hold tuning options. Their headings show how many values differ from the defaults. The server supplies setting descriptions, so new server settings can appear without an app update.

## Label recordings

**Label Recordings…** opens unlabelled audio pieces in random order. Listen, then correct the transcript to the text you intended to write. Remove hesitation sounds and repeated words; after a self-correction, keep the corrected wording.

This prepares data for future model training. It does not train the model automatically.

| Key | Action |
|---|---|
| ⌘↩ | Save and Next: save the corrected text as `verified`. |
| ⌘U | Unusable: mark noise, a TV, or another voice. |
| ⌘L | Later: leave the piece for another session. |
| Esc | Close the window. |

See [recordings and labels](5-recordings.md) for file formats and storage paths.

## Build and start

Follow the [development guide](7-development.md) for prerequisites and commands. A development app uses the server in the checkout. A bundled app includes Python, server dependencies, and `llama-server`; it installs its own launchd agent.

The app log is `~/Library/Logs/local-voice/app.log`. It records text lengths, not transcript contents.

## Code map

| Folder in `macos/Sources` | Purpose |
|---|---|
| `LocalVoice/` | App lifecycle, permissions, menu, settings window, microphone, dictation, and insertion. |
| `LocalVoiceCore/` | Config, protocol, key handling, and settings logic that needs no screen access. |
| `FocusSnapshot/` | Capture the focused app and input field. |
| `lv-snapshot/` | Command-line snapshot inspection tool. |
| `lv-tests/` | Checks for `LocalVoiceCore`. |
