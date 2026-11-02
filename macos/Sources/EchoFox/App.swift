// The app's coordinator: a tap of a hotkey starts a dictation (the dictation's key) or a private dictation (its own
// key: the screen is not read, nothing is saved), and the next tap of either stops it; the text goes where the
// Inserter's rule says. The model runs in the dictation server; the app takes the focus snapshot, records, sends and
// inserts. It holds the parts and connects them: Permissions, ServerRunner (the server, its child process),
// ServerInfoClient (what the server offers), TapKey, MenuBar, SettingsWindow, Dictation in a DictationQueue,
// Inserter, ModelDownloads, and ConfigStore, the one owner of the config file.
import AppKit
import AVFoundation
import FocusSnapshot
import EchoFoxCore

final class App: NSObject, NSApplicationDelegate, MenuActions, SettingsActions {
    private let store = ConfigStore()
    private let downloads = ModelDownloads()
    private let permissions = Permissions()
    private let infoClient = ServerInfoClient()
    private let key = TapKey()
    private lazy var menu = MenuBar(actions: self)
    private let labeling = LabelWindow()
    private let settings = SettingsWindow()
    private let firstRun = FirstRunWindow()
    private let updater = Updater()
    private let prepareQueue = DispatchQueue(label: "echofox.prepare")
    private var dictations = DictationQueue<Dictation>()
    private var lastError: String?
    /// The dictation server, the app's child process (ServerProcess); nil for an app that carries none.
    private let serverProcess = ServerRunner.bundled(version: App.version)

    func applicationDidFinishLaunching(_ notification: Notification) {
        Log.write("started, pid \(ProcessInfo.processInfo.processIdentifier), version \(App.version)")
        if AppLocation.refuseIfMisplaced() { return }
        firstRun.configExisted = FileManager.default.fileExists(atPath: Config.url.path)  // before anything writes it
        MainMenu.install(settings: #selector(openSettingsFromMenu), target: self)
        DockPresence.watch()
        serverProcess?.onStart = { [weak self] in self?.askServer() }
        serverProcess?.start()
        store.onError = { [weak self] e in
            self?.lastError = e
            self?.menu.update()
        }
        store.log = { Log.write($0) }
        store.observe { [weak self] old, new in self?.configChanged(from: old, to: new) }
        store.start()
        firstRun.store = store
        firstRun.downloads = downloads
        firstRun.permissions = { [unowned self] in
            (self.permissions.microphone == .authorized, self.permissions.accessibility)
        }
        firstRun.allowMicrophone = { [weak self] in self?.allowMicrophone() }
        firstRun.allowAccessibility = { [weak self] in self?.allowAccessibility() }
        settings.downloads = downloads
        downloads.askServer = { [weak self] in self?.askServer() }
        menu.state = { [unowned self] in self.state() }
        settings.actions = self
        key.onTap = { [weak self] action in self?.toggle(isPrivate: action == .privateDictation) }
        keysChanged()
        permissions.onChange = { [weak self] in self?.permissionsChanged() }
        infoClient.onChange = { [weak self] in
            self?.prepareAll()
            self?.menu.update()
            self?.settings.refresh()
            self?.firstRun.showIfNeeded(self?.infoClient.info)
        }
        firstRun.askServer = { [weak self] in self?.askServer() }
        // A removal that leaves no variant downloaded opens the first start's window again (when the info says so)
        downloads.onEnd { [weak self] _, job, isDownload in if !isDownload, job.error == nil { self?.firstRun.allowAgain() } }
        updater.busy = { [unowned self] in self.dictations.busy }
        updater.onChange = { [weak self] in self?.menu.update() }
        updater.start()
        permissions.start()
        permissionsChanged()  // the permissions the app already has: the dictation keys start now
        infoClient.refresh(store.config.serverURL)
        for name in [NSWorkspace.didActivateApplicationNotification, NSWorkspace.didLaunchApplicationNotification] {
            NSWorkspace.shared.notificationCenter.addObserver(forName: name, object: nil, queue: .main) { [weak self] n in
                guard let self, let app = n.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication else { return }
                self.infoClient.refresh(self.store.config.serverURL, ifOlderThan: Tuning.serverInfoMaxAgeSeconds)
                self.prepare(app)
            }
        }
        menu.update()
    }

    /// A click on the app's Dock icon (the one shown while a window is open, DockPresence, or the Dock's recent apps), or
    /// opening the app again from Finder: a minimized window comes back; with no window, Settings opens.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows: Bool) -> Bool {
        let minimized = NSApp.windows.filter(\.isMiniaturized)
        if !minimized.isEmpty {
            minimized.forEach { $0.deminiaturize(nil) }
        } else if !DockPresence.hasWindow {
            openSettings()
        }
        return true
    }

    @objc private func openSettingsFromMenu() { openSettings() }

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
        let microphone = AudioInputs.chosen(config.microphone)
        let current = dictations.current
        return MenuState(recording: current != nil, privateRecording: current?.isPrivate == true,
                         waiting: !dictations.waiting.isEmpty, accessibility: permissions.accessibility,
                         microphone: permissions.microphone, lastError: lastError, config: config, server: infoClient.info,
                         serverProblem: infoClient.problem, microphoneName: microphone.name,
                         inputVolume: microphone.device.flatMap(AudioInputs.volume), update: updater.ready)
    }

    private func permissionsChanged() {
        if permissions.accessibility {
            key.start()
            prepareAll()
        } else {
            key.stop()  // the monitors would stay silent anyway
        }
        firstRun.permissionsChanged()
        menu.update()
    }

    // MARK: Accessibility trees on request

    /// Electron apps build their accessibility tree only on request, about 2 s after it (see FocusSnapshot), and forget
    /// it when they quit. Only the apps of the enabled adapters' surfaces with treeOnRequest are asked (ElectronTree).
    private func prepareAll() {
        for app in NSWorkspace.shared.runningApplications where app.activationPolicy == .regular { prepare(app) }
    }

    private func prepare(_ app: NSRunningApplication) {
        guard permissions.accessibility, let id = app.bundleIdentifier, infoClient.info?.treeApps.contains(id) == true
        else { return }
        let pid = app.processIdentifier
        prepareQueue.async { ElectronTree.enable(pid: pid) }
    }

    // MARK: Dictation

    private func toggle(isPrivate: Bool) {
        if let d = dictations.current {
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
        let info = infoClient.info
        if info == nil { infoClient.refresh(config.serverURL) }
        let d = Dictation(config: config, server: info, plan: info?.identityPlan(for: front) ?? .none, isPrivate: isPrivate)
        if isPrivate { Log.write("a private dictation: the screen is not read, nothing is saved") }
        d.onPhase = { [weak self] d in self?.changed(d) }
        dictations.start(d)
        d.start()
        menu.update()
    }

    private func changed(_ d: Dictation) {
        if dictations.changed(d, to: d.phase) {
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
        Uninstaller.confirmAndRun(info: infoClient.info, serverURL: store.config.serverURL, downloads: downloads,
                                  folders: store.config.folders(infoClient.info))
    }

    func allowAccessibility() {
        permissions.askAccessibility()
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
        guard let device = AudioInputs.chosen(store.config.microphone).device else { return }
        if !AudioInputs.setVolume(value, of: device) { Log.write("the microphone's input volume cannot be set") }
    }

    func choose(microphone: String) {
        store.apply(SettingStore.microphone(microphone, in: store.config), "microphone chosen: \(microphone)")
    }

    // MARK: SettingsActions

    func serverState() -> (info: ServerInfo?, problem: String?) { (infoClient.info, infoClient.problem) }

    var config: Config { store.config }

    func apply(_ change: ConfigChange, _ done: String) { store.apply(change, done) }

    /// The server applies a change of the config at its next look at the file; then its info is asked again, so the
    /// snapshots, the trees and the settings window follow it.
    func refreshServer() {
        DispatchQueue.main.asyncAfter(deadline: .now() + Tuning.serverConfigApplySeconds) { [weak self] in
            guard let self else { return }
            self.infoClient.refresh(self.store.config.serverURL)
        }
    }

    func askServer() { infoClient.refresh(store.config.serverURL) }

    /// "0.2 (180)": CFBundleShortVersionString and CFBundleVersion, which build-app.sh takes from git.
    static let version: String = {
        let info = Bundle.main.infoDictionary ?? [:]
        return "\(info["CFBundleShortVersionString"] as? String ?? "?") (\(info["CFBundleVersion"] as? String ?? "?"))"
    }()

    /// The hotkeys from the config: the dictation's key and the private dictation's.
    private func keysChanged() {
        let config = store.config
        key.set([(.dictation, config.dictationKey), (.privateDictation, config.privateDictationKey)])
    }

    func openLabeling() {
        let (recordings, labeled) = store.config.folders(infoClient.info)
        labeling.show(recordings: recordings, labeled: labeled)
    }

    func openSettings() {
        settings.show()
    }

    func openLog() {
        NSWorkspace.shared.open(Log.url)
    }
}
