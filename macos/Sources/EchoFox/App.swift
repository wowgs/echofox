// The app's coordinator: a tap of a hotkey starts a dictation (the dictation's key) or a private dictation (its own
// key: the screen is not read, nothing is saved), and the next tap of either stops it; the text goes where the
// Inserter's rule says. The model runs in the dictation server; the app takes the focus snapshot, records, sends and
// inserts. It holds the parts and connects them: Permissions, Server (what the server offers), TapKey, MenuBar,
// SettingsWindow, Dictation, Inserter, and ConfigStore, the one owner of the config file.
import AppKit
import AVFoundation
import FocusSnapshot
import EchoFoxCore

final class App: NSObject, NSApplicationDelegate, MenuActions, SettingsActions {
    private let store = ConfigStore()
    private let downloads = ModelDownloads()
    private let permissions = Permissions()
    private let server = Server()
    private let key = TapKey()
    private lazy var menu = MenuBar(actions: self)
    private let labeling = LabelWindow()
    private let settings = SettingsWindow()
    private let firstRun = FirstRunWindow()
    private let updater = Updater()
    private let prepareQueue = DispatchQueue(label: "echofox.prepare")
    private var current: Dictation?
    private var waiting: [Dictation] = []
    private var lastError: String?
    /// The dictation server, the app's child process (ServerProcess); nil for an app that carries none.
    private var serverProcess: ServerRunner?

    func applicationDidFinishLaunching(_ notification: Notification) {
        Log.write("started, pid \(ProcessInfo.processInfo.processIdentifier), version \(App.version)")
        if refuseMisplaced() { return }
        startServer()
        store.onError = { [weak self] e in
            self?.lastError = e
            self?.menu.update()
        }
        store.log = { Log.write($0) }
        store.observe { [weak self] old, new in self?.configChanged(from: old, to: new) }
        store.start()
        firstRun.store = store
        firstRun.downloads = downloads
        settings.downloads = downloads
        downloads.askServer = { [weak self] in self?.askServer() }
        menu.state = { [unowned self] in self.state() }
        settings.actions = self
        key.onTap = { [weak self] action in self?.toggle(isPrivate: action == .privateDictation) }
        keysChanged()
        permissions.onChange = { [weak self] in self?.permissionsChanged() }
        server.onChange = { [weak self] in
            self?.prepareAll()
            self?.menu.update()
            self?.settings.refresh()
            self?.firstRun.showIfNeeded(self?.server.info)
        }
        firstRun.askServer = { [weak self] in self?.askServer() }
        // A removal that leaves no variant downloaded opens the first start's window again (when the info says so)
        downloads.onEnd { [weak self] _, job, isDownload in if !isDownload, job.error == nil { self?.firstRun.allowAgain() } }
        updater.busy = { [unowned self] in self.current != nil || !self.waiting.isEmpty }
        updater.onChange = { [weak self] in self?.menu.update() }
        updater.start()
        permissions.start()
        server.refresh(store.config.serverURL)
        for name in [NSWorkspace.didActivateApplicationNotification, NSWorkspace.didLaunchApplicationNotification] {
            NSWorkspace.shared.notificationCenter.addObserver(forName: name, object: nil, queue: .main) { [weak self] n in
                guard let self, let app = n.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication else { return }
                self.server.refresh(self.store.config.serverURL, ifOlderThan: Tuning.serverInfoMaxAgeSeconds)
                self.prepare(app)
            }
        }
        menu.update()
    }

    /// The server ends with the app, and its llama-server with it: the model leaves memory.
    func applicationWillTerminate(_ notification: Notification) {
        serverProcess?.stop()
    }

    /// The config changed (a write here, or the file from elsewhere): the hotkeys, the server and the windows follow.
    private func configChanged(from old: Config, to new: Config) {
        if old.dictationKey != new.dictationKey || old.privateDictationKey != new.privateDictationKey { keysChanged() }
        refreshServer()  // the server applies the change at its next look at the file; then its info is asked
        settings.configChanged(new)
        menu.update()
    }

    private func state() -> MenuState {
        let config = store.config
        let input = AudioInputs.chosen(config.microphone).input
        let device = input?.id ?? AudioInputs.defaultInput()
        return MenuState(recording: current != nil, privateRecording: current?.isPrivate == true, waiting: !waiting.isEmpty,
                         accessibility: permissions.accessibility,
                         microphone: permissions.microphone, lastError: lastError, config: config, server: server.info,
                         serverProblem: server.problem, microphoneName: input?.name ?? "macOS's input",
                         inputVolume: device.flatMap(AudioInputs.volume), update: updater.ready)
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
        let config = store.config
        let front = NSWorkspace.shared.frontmostApplication?.bundleIdentifier ?? ""
        let info = server.info
        if info == nil { server.refresh(config.serverURL) }
        let d = Dictation(config: config, server: info, plan: info?.snapshotPlan(for: front) ?? .none, isPrivate: isPrivate)
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
            updater.idle()
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

    func checkForUpdates() { updater.check() }

    func uninstall() {
        Uninstaller.confirmAndRun(info: server.info, serverURL: store.config.serverURL,
                                  folders: store.config.folders(server.info))
    }

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
        let input = AudioInputs.chosen(store.config.microphone).input
        guard let device = input?.id ?? AudioInputs.defaultInput() else { return }
        if !AudioInputs.setVolume(value, of: device) { Log.write("the microphone's input volume cannot be set") }
    }

    func choose(microphone: String) {
        write(["microphone"], microphone, "microphone chosen: \(microphone)")
    }

    // MARK: SettingsActions

    func serverState() -> (info: ServerInfo?, problem: String?) { (server.info, server.problem) }

    var config: Config { store.config }

    /// The server applies a change of the config at its next look at the file; then its info is asked again, so the
    /// snapshots, the trees and the settings window follow it.
    func refreshServer() {
        DispatchQueue.main.asyncAfter(deadline: .now() + Tuning.serverConfigApplySeconds) { [weak self] in
            guard let self else { return }
            self.server.refresh(self.store.config.serverURL)
        }
    }

    func askServer() { server.refresh(store.config.serverURL) }

    /// "0.2 (180)": CFBundleShortVersionString and CFBundleVersion, which build-app.sh takes from git.
    static let version: String = {
        let info = Bundle.main.infoDictionary ?? [:]
        return "\(info["CFBundleShortVersionString"] as? String ?? "?") (\(info["CFBundleVersion"] as? String ?? "?"))"
    }()

    /// An app that carries the server but runs from a disk image or App Translocation asks to be moved to
    /// Applications and quits (ServerProcess.misplaced); true then.
    private func refuseMisplaced() -> Bool {
        let app = Bundle.main.bundleURL
        guard ServerProcess.bundled(resources: Bundle.main.resourceURL) != nil else { return false }
        let readOnly = (try? app.resourceValues(forKeys: [.volumeIsReadOnlyKey]))?.volumeIsReadOnly ?? false
        guard let why = ServerProcess.misplaced(app: app.path, readOnlyVolume: readOnly) else { return false }
        Log.write("not started \(why), \(app.path): the server needs the app in one place")
        let alert = NSAlert()
        alert.messageText = "Move EchoFox to Applications"
        alert.informativeText = "EchoFox is running \(why). Its dictation server needs EchoFox to stay in one place. "
            + "Drag EchoFox to the Applications folder, then open it from there."
        alert.addButton(withTitle: "Quit")
        NSApp.activate(ignoringOtherApps: true)
        alert.runModal()
        NSApp.terminate(nil)
        return true
    }

    /// The app that carries the server starts it as its child process (ServerProcess), after it removed the launchd
    /// agents of the versions that ran the server without the app; launchctl waits, so that runs off the main thread.
    /// An app without a server of its own starts none: it uses the server at the config's address.
    private func startServer() {
        guard let (python, serverFolder) = ServerProcess.bundled(resources: Bundle.main.resourceURL) else { return }
        let home = FileManager.default.homeDirectoryForCurrentUser
        let runner = ServerRunner(launch: ServerProcess.launch(python: python, server: serverFolder, version: App.version),
                                  log: home.appendingPathComponent(ServerProcess.logInHome))
        runner.onStart = { [weak self] in self?.askServer() }
        serverProcess = runner
        DispatchQueue.global(qos: .userInitiated).async {
            for (command, file) in ServerProcess.legacyRemoval(domain: "gui/\(getuid())", home: home)
            where FileManager.default.fileExists(atPath: file.path) {
                let code = App.launchctl(command)
                try? FileManager.default.removeItem(at: file)
                Log.write("server: the launchd agent \(file.lastPathComponent) of an older version removed, bootout exit \(code)")
            }
            DispatchQueue.main.async { runner.start() }
        }
    }

    @discardableResult
    private static func launchctl(_ args: [String]) -> Int32 {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        p.arguments = args
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        guard (try? p.run()) != nil else { return -1 }
        p.waitUntilExit()
        return p.terminationStatus
    }

    /// The hotkeys from the config: the dictation's key and the private dictation's.
    private func keysChanged() {
        let config = store.config
        key.set([(.dictation, config.dictationKey), (.privateDictation, config.privateDictationKey)])
    }

    @discardableResult
    func remove(_ path: [String], _ done: String) -> Bool { store.remove(path, done) }

    @discardableResult
    func write(_ path: [String], _ value: Any, _ done: String) -> Bool { store.set(path, to: value, done) }

    func openLabeling() {
        let (recordings, labeled) = store.config.folders(server.info)
        labeling.show(recordings: recordings, labeled: labeled)
    }

    func openSettings() {
        settings.show()
    }

    func openLog() {
        NSWorkspace.shared.open(Log.url)
    }
}
