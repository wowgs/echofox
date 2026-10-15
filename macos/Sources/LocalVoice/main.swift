// Local Voice: the menu bar app (App.swift).
import AppKit

let app = NSApplication.shared
let delegate = App()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
