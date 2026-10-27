// EchoFox: the menu bar app (App.swift). With --record-test SECONDS OUT [CHOICE], it records the chosen microphone
// (or CHOICE: builtin, system, a device's UID) for that
// long and writes to OUT only what came (samples, seconds, peak level, which microphone), never the audio, then quits:
// a check of the recorder that runs with the app's own Microphone permission (`open -n EchoFox.app --args …`).
// With --render-first-run INFO OUT [dark], it draws the first start's window for the server info in the file INFO
// into the PNG OUT and quits (FirstRunWindow.render).
import AppKit
import EchoFoxCore

if let i = CommandLine.arguments.firstIndex(of: "--record-test"), CommandLine.arguments.count > i + 2 {
    let a = CommandLine.arguments
    RecordTest.run(seconds: Double(a[i + 1]) ?? 3, out: a[i + 2], choice: a.count > i + 3 ? a[i + 3] : nil)
}

if let i = CommandLine.arguments.firstIndex(of: "--render-first-run"), CommandLine.arguments.count > i + 2 {
    let a = CommandLine.arguments
    _ = NSApplication.shared
    FirstRunWindow.render(info: a[i + 1], to: a[i + 2], dark: a.count > i + 3 && a[i + 3] == "dark")
}

let app = NSApplication.shared
let delegate = App()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
