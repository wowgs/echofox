// The app's coordinator: a tap of the hotkey starts a dictation and the next tap stops it; the text goes where the
// Inserter's rule says. The model runs in the dictation server; the app takes the focus snapshot, records, sends and
// inserts. It holds the parts and connects them: Permissions, Server (what the server offers), TapKey, MenuBar,
// Dictation, Inserter.
import AppKit
import AVFoundation
import FocusSnapshot
import LocalVoiceCore

final class App: NSObject, NSApplicationDelegate, MenuActions {
    private let permissions = Permissions()
    private let server = Server()
    private let key = TapKey()
    private lazy var menu = MenuBar(actions: self)
    private let prepareQueue = DispatchQueue(label: "local-voice.prepare")
    private var current: Dictation?
    private var waiting: [Dictation] = []
    private var lastText: String?, lastNote: String?, lastError: String?

    func applicationDidFinishLaunching(_ notification: Notification) {
        Log.write("started, pid \(ProcessInfo.processInfo.processIdentifier)")
        menu.state = { [unowned self] in self.state() }
        key.onTap = { [weak self] in self?.toggle() }
        permissions.onChange = { [weak self] in self?.permissionsChanged() }
        server.onChange = { [weak self] in
            self?.prepareAll()
            self?.menu.update()
        }
        permissions.start()
        server.refresh(Config.load().serverURL)
        for name in [NSWorkspace.didActivateApplicationNotification, NSWorkspace.didLaunchApplicationNotification] {
            NSWorkspace.shared.notificationCenter.addObserver(forName: name, object: nil, queue: .main) { [weak self] n in
                guard let self, let app = n.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication else { return }
                self.server.refresh(Config.load().serverURL, ifOlderThan: Tuning.serverInfoMaxAgeSeconds)
                self.prepare(app)
            }
        }
        menu.update()
    }

    private func state() -> MenuState {
        MenuState(recording: current != nil, waiting: !waiting.isEmpty, accessibility: permissions.accessibility,
                  microphone: permissions.microphone, keyName: key.keyName, lastText: lastText, lastNote: lastNote,
                  lastError: lastError, config: Config.load(), server: server.info, serverProblem: server.problem)
    }

    private func permissionsChanged() {
        if permissions.accessibility {
            key.start()
            prepareAll()
        } else {
            key.stop()  // the monitors would stay silent anyway
        }
        menu.update()
    }

    // MARK: Electron apps

    /// Electron apps build their accessibility tree only on request, about 2 s after it (see FocusSnapshot), and forget
    /// it when they quit. Only the apps of enabled adapters are asked: the tree costs the app CPU and memory.
    private func prepareAll() {
        for app in NSWorkspace.shared.runningApplications where app.activationPolicy == .regular { prepare(app) }
    }

    private func prepare(_ app: NSRunningApplication) {
        guard permissions.accessibility, let id = app.bundleIdentifier, server.info?.treeApps.contains(id) == true
        else { return }
        let pid = app.processIdentifier
        prepareQueue.async { FocusSnapshot.prepare(pid: pid) }
    }

    // MARK: Dictation

    private func toggle() {
        if let d = current {
            d.stop(.user)
            return
        }
        guard permissions.microphone == .authorized else {
            lastError = "no Microphone permission (System Settings, Privacy & Security, Microphone)"
            permissions.askMicrophone()
            menu.update()
            return
        }
        let config = Config.load()
        if let e = config.error { Log.write("config: \(e)") }
        let front = NSWorkspace.shared.frontmostApplication?.bundleIdentifier ?? ""
        let info = server.info
        if info == nil { server.refresh(config.serverURL) }
        let d = Dictation(config: config, server: info, full: info?.snapshotApps.contains(front) == true,
                          tree: info?.treeApps.contains(front) == true)
        d.onPhase = { [weak self] d in self?.changed(d) }
        current = d
        d.start()
        menu.update()
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
        menu.update()
    }

    private func finished(_ d: Dictation) {
        let text = d.text
        lastError = d.errors.isEmpty ? nil : d.errors.joined(separator: "; ")
        if let e = lastError { Log.write("error: \(e)") }
        guard !text.isEmpty else {
            Log.write("no text")
            return
        }
        lastText = text
        Inserter.shared.insert(text, into: d.capture) { [weak self] how, why in
            Log.write("text: \(text.count) characters, inserted: \(how.rawValue) (\(why))")
            self?.lastNote = how == .clipboard ? "The text is in the clipboard: \(why)." : nil
            self?.menu.update()
        }
    }

    // MARK: MenuActions

    func allowAccessibility() {
        permissions.askAccessibility()
        permissions.openSettings(.accessibility)
    }

    func allowMicrophone() {
        if permissions.microphone == .notDetermined {
            permissions.askMicrophone()
        } else {
            permissions.openSettings(.microphone)
        }
    }

    func copyLastText() {
        guard let t = lastText else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(t, forType: .string)
    }

    func choose(model: String) {
        do {
            try Config.choose(model: model)
            Log.write("model chosen: \(model)")
        } catch {
            lastError = "cannot write the config: \(error)"
            menu.update()
        }
    }

    func openLog() {
        NSWorkspace.shared.open(Log.url)
    }
}
