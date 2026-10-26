# Use the Mac app

EchoFox lives in the menu bar. Start and stop dictation from the keyboard, without switching away from the app you're writing in.

See also: [configuration](2-config.md), [saved recordings](5-recordings.md), and [build from source](7-development.md#build-from-source).

## Dictate

1. Click a text field.
2. Tap and release **right Option** to start recording.
3. Speak, then tap either dictation key to stop.

Use **right Command** for private dictation. It skips conversation context and saves no audio or transcript. The app still identifies the input field so it can insert your text. While it records, the earpiece of the fox in the menu bar is a shield with a keyhole.

A tap means pressing and releasing the key on its own. Change either key in **Settings → General**.

Recording stops automatically after 60 seconds without speech by default. The server also enforces a recording limit of 30 minutes by default. Both limits are configurable.

## Where the text goes

The app chooses the destination when the text arrives:

1. The text field that had the focus when you tapped the key, wherever you are now. If its app is in the background, EchoFox first tries ways that keep it there; only if they fail does it bring that app to the front, paste, and take you back to where you were.
2. Otherwise, the text field that has the focus now, for example one you clicked into while speaking.
3. Otherwise, if the app of the tap is still in front but shows no focused element (an Electron app whose accessibility tree is off), a paste at its cursor.
4. If none works, the text goes to the clipboard and the menu shows a message.

In a field, EchoFox tries Accessibility insertion (it replaces the selected text), then Cmd+V, and checks after each way that the text arrived, so it never goes in twice. Cmd+V restores the previous clipboard afterward.

After recording stops, the app waits up to 180 seconds for each next piece of text.

## Requirements and model choices

Use an Apple Silicon Mac with at least 16 GB of memory and macOS 14 or later. The build checks that every program and library in the app is made for macOS 14. The app has been tested only on an Apple M5 with 24 GB running macOS 27. It has not been run on an older macOS.

The two downloads are differently compressed variants of Gemma 4 E4B:

| Variant | Download size | Approximate memory use | Suggested Mac memory |
|---|---|---|---|
| Q4_0 | 5.6 GB | 7 GB | 16 GB |
| Q8_0 | 9.0 GB | 10 GB | 24 GB or more |

Memory figures are approximate. A systematic comparison of recognition quality and speed is still pending. Change the variant later in **Settings → Model**.

## The first start

Download `EchoFox.dmg` from the [releases](https://github.com/wowgs/echofox/releases), open it, and drag EchoFox to Applications. Then open EchoFox from Applications.

If you open EchoFox from the disk image, it asks you to move it to Applications and quits. It does the same if macOS runs it from a temporary folder. This happens to a downloaded app that was not moved (App Translocation). The dictation server is a launchd agent that starts EchoFox's own copy of Python, so EchoFox must stay in one place.

Grant **Microphone** and **Accessibility** permissions in macOS. Accessibility supports the dictation keys, conversation snapshots, and text insertion. Missing permissions appear in the menu; clicking one opens its page in System Settings.

If no model variant is downloaded, a setup window shows the download sizes and estimated memory use. It recommends Q4_0 for a 16 GB Mac or Q8_0 for a Mac with at least 24 GB. Choose a variant and click **Download**. The window shows the download's speed and the time left.

The download goes on if you close the window.

## Update and remove

To update, quit EchoFox, drag the new version to Applications, and replace the old one. Then open EchoFox. The app writes its version into the server's launchd agent. So a new version starts the dictation server again, and the server then starts `llama-server` again. Model files stay.

To remove EchoFox, quit it and run these commands. They stop the server and the model and delete their launchd agents. Then delete EchoFox from Applications.

```
launchctl bootout gui/$(id -u)/echofox.gemma-voice
launchctl bootout gui/$(id -u)/echofox.llama-server
rm ~/Library/LaunchAgents/echofox.gemma-voice.plist ~/Library/LaunchAgents/echofox.llama-server.plist
```

If you delete only the app, the agents stay. On macOS 27, launchd tries once to start the deleted program and then waits for it to come back ([observations](../observations.md#distribution)). To delete the rest, also remove the models in `~/Library/Application Support/EchoFox`, the config in `~/.echofox`, and the logs in `~/Library/Logs/EchoFox`.

## The menu and the settings window

The menu contains permissions while any are missing, microphone selection, input volume, **Label Recordings…**, **Settings…** (⌘,), and Quit. Input volume is the same control as in macOS Sound settings.

The menu bar icon is a fox face. While you dictate, the fox wears a white headset: the earpiece is red for a recording, a shield with a keyhole for private dictation, and a turning ring while the text is written. If a permission is missing or something fails, the icon is a crossed-out microphone.

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

## Logs

A bundled app installs its own launchd agent off the main thread, so the menu bar icon appears at once. It does not install the agent from a disk image or App Translocation.

The app log is `~/Library/Logs/EchoFox/app.log`. It records text lengths, not transcript contents. To build the app, see the [development guide](7-development.md).

## Code map

| Folder in `macos/Sources` | Purpose |
|---|---|
| `EchoFox/` | App lifecycle, permissions, menu, settings window, microphone, dictation, and insertion. |
| `EchoFoxCore/` | Config, protocol, key handling, and settings logic that needs no screen access. |
| `FocusSnapshot/` | Capture the focused app and input field. |
| `echofox-snapshot/` | Command-line snapshot inspection tool. |
| `echofox-tests/` | Checks for `EchoFoxCore`. |
