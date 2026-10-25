// The app's coordinator: a tap of a hotkey starts a dictation (the dictation's key) or a private dictation (its own
// key: the screen is not read, nothing is saved), and the next tap of either stops it; the text goes where the
// Inserter's rule says. The model runs in the dictation server; the app takes the focus snapshot, records, sends and
// inserts. It holds the parts and connects them: Permissions, Server (what the server offers), TapKey, MenuBar,
// SettingsWindow, Dictation, Inserter.
import AppKit
import AVFoundation
import FocusSnapshot
import LocalVoiceCore

final class App: NSObject, NSApplicationDelegate, MenuActions, SettingsActions {
    private let permissions = Permissions()
    private let server = Server()
    private let key = TapKey()
    private lazy var menu = MenuBar(actions: self)
    private let labeling = LabelWindow()
    private let settings = SettingsWindow()
    private let prepareQueue = DispatchQueue(label: "local-voice.prepare")
    private var current: Dictation?
    private var waiting: [Dictation] = []
    private var lastError: String?

    func applicationDidFinishLaunching(_ notification: Notification) {
        Log.write("started, pid \(ProcessInfo.processInfo.processIdentifier)")
        menu.state = { [unowned self] in self.state() }
        settings.actions = self
        key.onTap = { [weak self] action in self?.toggle(isPrivate: action == .privateDictation) }
        keysChanged()
        permissions.onChange = { [weak self] in self?.permissionsChanged() }
        server.onChange = { [weak self] in
            self?.prepareAll()
            self?.menu.update()
            self?.settings.refresh()
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
        let config = Config.load()
        let input = AudioInputs.chosen(config.microphone).input
        let device = input?.id ?? AudioInputs.defaultInput()
        return MenuState(recording: current != nil, privateRecording: current?.isPrivate == true, waiting: !waiting.isEmpty,
                         accessibility: permissions.accessibility,
                         microphone: permissions.microphone, lastError: lastError, config: config, server: server.info,
                         serverProblem: server.problem, microphoneName: input?.name ?? "macOS's input",
                         inputVolume: device.flatMap(AudioInputs.volume))
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

    private func toggle(isPrivate: Bool) {
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
                          tree: info?.treeApps.contains(front) == true, lists: info?.listApps.contains(front) == true,
                          isPrivate: isPrivate)
        if isPrivate { Log.write("a private dictation: the screen is not read, nothing is saved") }
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
        Inserter.shared.insert(text, into: d.capture) { how, why in
            Log.write("text: \(text.count) characters, inserted: \(how.rawValue) (\(why))")
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

    /// The recorded microphone's input volume: the device's own control, the same as in macOS's Sound settings.
    func setInputVolume(_ value: Float) {
        let input = AudioInputs.chosen(Config.load().microphone).input
        guard let device = input?.id ?? AudioInputs.defaultInput() else { return }
        if !AudioInputs.setVolume(value, of: device) { Log.write("the microphone's input volume cannot be set") }
    }

    func choose(microphone: String) {
        write(["microphone"], microphone, "microphone chosen: \(microphone)")
    }

    // MARK: SettingsActions

    func serverState() -> (info: ServerInfo?, problem: String?) { (server.info, server.problem) }

    /// The server applies a change of the config at its next look at the file; then its info is asked again, so the
    /// snapshots, the trees and the settings window follow it.
    func refreshServer() {
        DispatchQueue.main.asyncAfter(deadline: .now() + Tuning.serverConfigApplySeconds) { [weak self] in
            self?.server.refresh(Config.load().serverURL)
        }
    }

    /// The hotkeys from the config: the dictation's key and the private dictation's.
    func keysChanged() {
        let config = Config.load()
        key.set([(.dictation, config.dictationKey), (.privateDictation, config.privateDictationKey)])
    }

    @discardableResult
    func remove(_ path: [String], _ done: String) -> Bool {
        do {
            try Config.remove(path)
            Log.write(done)
            refreshServer()
            return true
        } catch {
            lastError = "cannot write the config: \(error)"
            menu.update()
            return false
        }
    }

    @discardableResult
    func write(_ path: [String], _ value: Any, _ done: String) -> Bool {
        do {
            try Config.set(path, to: value)
            Log.write(done)
            refreshServer()
            return true
        } catch {
            lastError = "cannot write the config: \(error)"
            menu.update()
            return false
        }
    }

    func openLabeling() {
        labeling.show()
    }

    func openSettings() {
        settings.show()
    }

    func openLog() {
        NSWorkspace.shared.open(Log.url)
    }
}
