// Local Voice: the menu bar app. A tap of the right Option starts a dictation and the next tap stops it; the text goes
// into the input box that had the focus when it started. The model runs in the dictation server
// (server/gemma_voice.py); the app takes the focus snapshot, records, sends, and inserts. It needs the Microphone and
// Accessibility permissions.
import AppKit
import AVFoundation
import FocusSnapshot

final class App: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
    private let key = TapKey()
    private let prepareQueue = DispatchQueue(label: "local-voice.prepare")
    private var current: Dictation?
    private var waiting: [Dictation] = []
    private var lastText: String?
    private var lastError: String?
    private var trustTimer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        Log.write("started, pid \(ProcessInfo.processInfo.processIdentifier)")
        let menu = NSMenu()
        menu.delegate = self
        item.menu = menu
        key.onTap = { [weak self] in self?.toggle() }
        askPermissions()
        NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main) { [weak self] n in
            if let app = n.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication {
                self?.prepare(app.processIdentifier)
            }
        }
        update()
    }

    // MARK: Permissions

    private func askPermissions() {
        let prompt = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        if AXIsProcessTrustedWithOptions(prompt) {
            accessibilityGranted()
        } else {
            Log.write("waiting for the Accessibility permission")
            trustTimer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] t in
                guard AXIsProcessTrusted() else { return }
                t.invalidate()
                self?.accessibilityGranted()
            }
        }
        if AVCaptureDevice.authorizationStatus(for: .audio) == .notDetermined {
            AVCaptureDevice.requestAccess(for: .audio) { ok in
                Log.write("microphone permission: \(ok)")
                DispatchQueue.main.async { self.update() }
            }
        }
    }

    private func accessibilityGranted() {
        Log.write("Accessibility permission granted")
        key.start()
        // Electron apps build their accessibility tree only on request, about 2 s after it (see FocusSnapshot).
        for app in NSWorkspace.shared.runningApplications where app.activationPolicy == .regular {
            prepare(app.processIdentifier)
        }
        update()
    }

    private func prepare(_ pid: pid_t) {
        guard AXIsProcessTrusted(), pid != ProcessInfo.processInfo.processIdentifier else { return }
        prepareQueue.async { FocusSnapshot.prepare(pid: pid) }
    }

    // MARK: Dictation

    private func toggle() {
        if let d = current {
            d.stop("user")
            return
        }
        guard AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else {
            lastError = "no Microphone permission (System Settings, Privacy & Security, Microphone)"
            update()
            return
        }
        let config = Config.load()
        if let e = config.error { Log.write("config: \(e)") }
        let d = Dictation(config: config)
        d.onPhase = { [weak self] d in self?.changed(d) }
        current = d
        do {
            try d.start()
            Log.write("start: model \(config.model ?? "none"), language \(config.language), \(config.serverURL.absoluteString)")
        } catch {
            Log.write("cannot start: \(error.localizedDescription)")
        }
        update()
    }

    private func changed(_ d: Dictation) {
        if d === current, d.phase != .recording {
            current = nil
            waiting.append(d)
        }
        if d.phase == .finished {
            waiting.removeAll { $0 === d }
            finished(d)
        }
        update()
    }

    private func finished(_ d: Dictation) {
        let text = d.text
        lastError = d.errors.isEmpty ? nil : d.errors.joined(separator: "; ")
        if !text.isEmpty {
            lastText = text
            let (how, why) = Inserter.insert(text, into: d.capture)
            Log.write("text: \(text.count) characters, inserted: \(how.rawValue) (\(why))")
            if how == .notInserted { lastError = "the text was not inserted (\(why)); copy it from this menu" }
        } else {
            Log.write("no text")
        }
        if let e = lastError { Log.write("error: \(e)") }
    }

    // MARK: Menu

    private func update() {
        let symbol: String, tint: NSColor?
        if current != nil {
            (symbol, tint) = ("mic.fill", .systemRed)
        } else if !waiting.isEmpty {
            (symbol, tint) = ("ellipsis.circle", nil)
        } else if !AXIsProcessTrusted() || AVCaptureDevice.authorizationStatus(for: .audio) != .authorized
                    || lastError != nil {
            (symbol, tint) = ("mic.slash", nil)
        } else {
            (symbol, tint) = ("mic", nil)
        }
        let image = NSImage(systemSymbolName: symbol, accessibilityDescription: "Local Voice")
        image?.isTemplate = true
        item.button?.image = image
        item.button?.contentTintColor = tint
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()
        let status: String
        if current != nil {
            status = "Recording. Tap the right Option to stop."
        } else if !waiting.isEmpty {
            status = "Waiting for the text."
        } else if !AXIsProcessTrusted() {
            status = "Needs the Accessibility permission."
        } else if AVCaptureDevice.authorizationStatus(for: .audio) != .authorized {
            status = "Needs the Microphone permission."
        } else {
            status = "Ready. Tap the right Option to dictate."
        }
        menu.addItem(disabled(status))
        if let t = lastText {
            let shown = t.count > 60 ? String(t.prefix(60)) + "…" : t
            let copy = NSMenuItem(title: "Copy the last text: “\(shown)”", action: #selector(copyLast), keyEquivalent: "")
            copy.target = self
            menu.addItem(copy)
        }
        if let e = lastError {
            menu.addItem(disabled("Last error: " + (e.count > 100 ? String(e.prefix(100)) + "…" : e)))
        }
        menu.addItem(.separator())
        let config = Config.load()
        let models = NSMenu()
        for name in config.models {
            let m = NSMenuItem(title: name, action: #selector(chooseModel(_:)), keyEquivalent: "")
            m.target = self
            m.representedObject = name
            m.state = name == config.model ? .on : .off
            models.addItem(m)
        }
        if let e = config.error { models.addItem(disabled(e)) }
        let modelItem = NSMenuItem(title: "Model", action: nil, keyEquivalent: "")
        modelItem.submenu = models
        menu.addItem(modelItem)
        menu.addItem(disabled("Language: \(config.language.isEmpty ? "the speech's own" : config.language)"))
        menu.addItem(.separator())
        let log = NSMenuItem(title: "Open the Log", action: #selector(openLog), keyEquivalent: "")
        log.target = self
        menu.addItem(log)
        menu.addItem(NSMenuItem(title: "Quit Local Voice", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
    }

    private func disabled(_ title: String) -> NSMenuItem {
        let i = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        i.isEnabled = false
        return i
    }

    @objc private func copyLast() {
        guard let t = lastText else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(t, forType: .string)
    }

    @objc private func chooseModel(_ sender: NSMenuItem) {
        guard let name = sender.representedObject as? String else { return }
        do {
            try Config.choose(model: name)
            Log.write("model chosen: \(name)")
        } catch {
            lastError = "cannot write the config: \(error.localizedDescription)"
            update()
        }
    }

    @objc private func openLog() {
        NSWorkspace.shared.open(Log.url)
    }
}

let app = NSApplication.shared
let delegate = App()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
