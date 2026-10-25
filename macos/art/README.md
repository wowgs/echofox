# EchoFox art

The approved look of the app. The sources are in this folder. The files that the app carries are in `macos/app/`.

| File | What it is | Where the app uses it |
|---|---|---|
| `echofox-master.png` | The app icon, 1254 × 1254 px: the fox with a headset on a navy tile. | The source of `macos/app/EchoFox.icns`. |
| `echofox-welcome.png` | The full fox character, 1122 × 1402 px, transparent. | The source of `macos/app/echofox-welcome.png`. |
| `approved-menu-bar.png` | The approved menu bar icons, large and at 26 × 24 pt, on a light and a blue-gray menu bar. | A reference only. |

`macos/app/EchoFox.icns` has the ten standard sizes, from 16 × 16 to 512 × 512 pt at 1x and 2x. `macos/app/echofox-welcome.png` is the character at 360 × 450 px, which is 2x for the 160 pt that the first-start window shows:

```sh
sips -Z 450 macos/art/echofox-welcome.png --out macos/app/echofox-welcome.png
```

`build-app.sh` copies both files into `Contents/Resources`. `Info.plist` names the icon in `CFBundleIconFile`.

## Where the fox appears

- The app icon: Finder, Applications, and the dialogs of macOS.
- The menu bar: a fox face, drawn in code by `macos/Sources/EchoFox/MenuBarIcon.swift`. Idle is the face alone. Recording adds a large white headset with a red earpiece. Ultra Private Dictation has a shield with a keyhole on the earpiece. While the app waits for the text, a dark open ring turns on the earpiece. With Reduce Motion, the ring stands still. A problem (a missing permission, an error, no server) shows the crossed-out microphone of SF Symbols. No fox is drawn for it yet.
- The first-start window: the full character, once, beside the choice of the model to download.

The fox appears nowhere else: not in the settings, the menus or the other dialogs.
