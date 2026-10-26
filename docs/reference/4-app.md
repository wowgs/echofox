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

Use an Apple Silicon Mac with at least 16 GB of memory and macOS 14 or later. Everything in the app is built for macOS 14, but it has run only on an Apple M5 with 24 GB and macOS 27; macOS 14–26 are not tested.

The two downloads are differently compressed variants of Gemma 4 E4B:

| Variant | Download size | Approximate memory use | Suggested Mac memory |
|---|---|---|---|
| Q4_0 | 5.6 GB | 7 GB | 16 GB |
| Q8_0 | 9.0 GB | 10 GB | 24 GB or more |

Memory figures are approximate. A systematic comparison of recognition quality and speed is still pending. Change the variant later in **Settings → Model**.

## The first start

Download `EchoFox.dmg` from the [releases](https://github.com/wowgs/echofox/releases), open it, and drag EchoFox to Applications. Then open EchoFox from Applications. If you open it from the dmg, it asks you to move it to Applications and quits: its server must not depend on a disk image that goes away.

If no model is downloaded, a window asks for the language you speak most (it proposes macOS's language, or English) and the variant of Gemma 4 E4B to download, and recommends one for your Mac's memory. The language goes into the config when the download starts; Settings can change both later.

Grant **Microphone** and **Accessibility** permissions in macOS. Accessibility supports the dictation keys, conversation snapshots, and text insertion. Missing permissions appear in the menu; clicking one opens its page in System Settings.

If no model variant is downloaded, a setup window shows the download sizes and estimated memory use. It recommends Q4_0 for a 16 GB Mac or Q8_0 for a Mac with at least 24 GB. Choose a variant and click **Download**. The window shows the download's speed and the time left.

The download goes on if you close the window. While it runs, Settings shows the variant as downloading, without a Download button.

## The menu and the settings window

The menu contains permissions while any are missing, microphone selection, input volume, **Label Recordings…**, **Check for Updates…**, **Settings…** (⌘,), and Quit. When a new version is out, the first line says **Update to EchoFox …**. Input volume is the same control as in macOS Sound settings.

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

## Update

When a new version is out, the menu's first line says so; it opens the update window, and **Install and Relaunch** installs it. **Check for Updates…** looks at once. At its second start the app asks whether to check automatically, about once a day. A restart that would cut a running dictation waits until it ends. The downloaded models stay, and the new version restarts the dictation server and `llama-server` by itself. By hand: quit EchoFox, replace it in Applications with the new version, and open it again.

## Uninstall

Quit EchoFox, stop its two launchd agents, and remove them and the app:

```sh
launchctl bootout gui/$(id -u)/echofox.gemma-voice
launchctl bootout gui/$(id -u)/echofox.llama-server
rm ~/Library/LaunchAgents/echofox.gemma-voice.plist ~/Library/LaunchAgents/echofox.llama-server.plist
```

Your data is in `~/Library/Application Support/EchoFox` (models, plugins), `~/.echofox` (config) and `~/Library/Logs/EchoFox`; your recordings are in the folder set in Settings. If you delete only the app, launchd stops its server after one failed start (macOS 27).

## Logs

The app log is `~/Library/Logs/EchoFox/app.log`. It records text lengths, not transcript contents. To build the app, see the [development guide](7-development.md).

## Code map

| Folder in `macos/Sources` | Purpose |
|---|---|
| `EchoFox/` | App lifecycle, permissions, menu, windows, microphone, dictation, model downloads (`ModelDownloads`), and the Mac side of insertion (`Inserter`, through Accessibility). |
| `EchoFoxCore/` | The decisions that need no screen access, each with checks: the config and its one owner (`ConfigStore`), the protocol, the server agent, key handling, the settings logic (`SettingStore`), which snapshot an app gets (`ServerInfo.snapshotPlan`), which microphone the config means (`MicrophoneChoice`), and where the text goes (`InsertionRule`). |
| `FocusSnapshot/` | Capture the focused app and input field. |
| `echofox-snapshot/` | Command-line snapshot inspection tool. |
| `echofox-tests/` | Checks for `EchoFoxCore`. |
