# The menu bar app

Local Voice is a menu bar app. It records your speech, sends it to [the dictation server](1-server.md) and puts the text where you write. Its code is in `macos/`.

Related docs: [the config file](2-config.md), [the recordings and labels](5-recordings.md), [the design of the interface](../design/5-ui.md).

## Dictate

- Tap the right Option key to start a dictation. Tap it again to stop. A tap means that you press and release the key alone.
- Tap the right Command key for a private dictation. The app then reads only the input box and sends no snapshot. The server saves nothing of the recording and writes no text into its log. The icon is purple while it records.
- You choose the keys in the settings window.
- The app stops a recording by itself after 60 s without speech (`silenceStopSeconds`). The server stops it at its time limit, 30 minutes by default.

## Where the text goes

1. If an input box has the focus when the text comes back, the text goes there. You can click into a box while you speak.
2. Otherwise the text goes into the box that had the focus at the tap. Its app comes to the front again.
3. Otherwise the text goes to the clipboard, and the menu says so.

The app first inserts the text with Accessibility, in place of the selected text. If the app in front refuses that, or the text does not appear, Local Voice pastes the text with Cmd+V and then puts the old clipboard back.

After the stop, the app waits up to 180 s for each next piece of text.

## The menu and the settings window

The menu has the things that you use often:

- Permissions, only while one is missing. A click on a missing one opens its place in System Settings.
- The microphone and its input volume. The volume is the one in the Sound settings of macOS.
- Label Recordings…
- Settings… (⌘,) and Quit.

The icon shows the state: recording, private recording, waiting for the text, or a problem.

The settings window has one page for each owner of settings: General, Microphone, Language, Model, the adapters, Recordings & Labels and Diagnostics. On the page Model you choose the model, its quantization (only one whose files are downloaded), the models folder and the prompt. Each other quantization has Download, with its progress and Cancel, or Remove when its files are there. The dictation server does the download, so it goes on when you close the window. Settings for people who tune the model and the context are in the Advanced section of their page. Advanced opens on a click, and its title says how many of its values you changed. The server describes its own settings, so a new one shows in the window by itself.

## Label recordings

Label Recordings… opens a window of cards. Each card is one piece of a saved recording that has no label yet, in random order. The card plays the piece and shows its text. You correct the text into what you meant to write: no hesitation sounds, no repeated words, and after a slip only the corrected words. A model trained on these labels learns to leave such things out.

| Key | Action |
|---|---|
| ⌘↩ | Save and Next: keep the label as `verified`. |
| ⌘U | Unusable: noise, a TV or another voice. |
| ⌘L | Later: keep the piece for next time. |
| Esc | Stop: close the window. |

[The recordings and labels](5-recordings.md) says where the labels go.

## Build and start

```
macos/build-app.sh
open macos/build/LocalVoice.app
```

This app is for work on the Mac where the repository is: the dictation server runs from the repository.

`macos/build-app.sh --bundle` builds `macos/build/bundle/LocalVoice.app`, which carries everything it runs: the server's code, Python 3.14 with the server's packages, and `llama-server` built from source with Metal. The versions are pinned in `macos/pins.sh`. At its start, this app installs the launchd agent of its own server. `--dmg` also builds `macos/build/LocalVoice.dmg` (about 113 MB). The build fails if a library in the bundle comes from Homebrew.

At the first start, macOS asks for two permissions: Microphone, and Accessibility (System Settings, Privacy & Security). The app needs Accessibility for the keys, the snapshot and the insertion of the text.

`build-app.sh` signs the app with the certificate "Local Voice Dev" from the login keychain. `LOCAL_VOICE_SIGN` names another one. Create a self-signed code-signing certificate with that name once. With it, macOS keeps the permissions after each rebuild. Without it, the script signs ad hoc, and macOS refuses the Accessibility permission after a rebuild.

The log of the app is `~/Library/Logs/local-voice/app.log`. It has the length of each text, never the text.

## The code

| Folder in `macos/Sources` | What it holds |
|---|---|
| `LocalVoice/` | The app. `App.swift` connects the parts: the permissions, the server, the keys, the menu, the dictation, the recorder, the insertion and the clipboard. `SettingsWindow.swift` is the settings window. |
| `LocalVoiceCore/` | The logic that needs no screen and no permission: the config, the messages of the protocol, the logic of the keys, the settings (`SettingStore.swift`, `SettingsLayout.swift`), the numbers of the app (`Tuning.swift`). |
| `FocusSnapshot/` | The focus snapshot. |
| `lv-snapshot/` | A tool that prints a focus snapshot. |
| `lv-tests/` | The checks of `LocalVoiceCore`: `swift run --package-path macos lv-tests`. |
