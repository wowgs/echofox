// The settings window (docs/design.md, "Settings"): pages in a sidebar (SettingsSidebar), each built from
// SettingsLayout (SettingsPages). A setting described by a SettingInfo (the server's in its info, the app's in
// SettingsLayout.appSettings) is one SettingRow; the app's other items have views of their own (SettingsPickers,
// LanguageSettings, ModelSettings, AdapterPage, ServerStatus). The window shows the config and the server's info and
// asks the App; what is in force, what a choice writes and the words for values are EchoFoxCore's (SettingStore,
// SettingText, SettingsLayout), so the window decides nothing.
import AppKit
import Combine
import EchoFoxCore
import SwiftUI

protocol SettingsActions: AnyObject {
    func serverState() -> (info: ServerInfo?, problem: String?)
    /// Asks the server for its info once it applied a change of the config; the window hears the answer (refresh).
    func refreshServer()
    /// Asks the server for its info now.
    func askServer()
    /// The config as the app last read it (ConfigStore).
    var config: Config { get }
    @discardableResult func write(_ path: [String], _ value: Any, _ done: String) -> Bool
    @discardableResult func remove(_ path: [String], _ done: String) -> Bool
    func choose(microphone: String)
    func setInputVolume(_ value: Float)
    func openLabeling()
    func openLog()
    /// Uninstall EchoFox…: asks, then removes the models, the app's files and the app (Uninstaller).
    func uninstall()
}

/// The settings window (Apple HIG, Settings): its minimize and zoom buttons dimmed, its title the visible page's, and
/// it opens again on the page last viewed, with the same Advanced sections open.
final class SettingsWindow: NSObject, NSWindowDelegate {
    private var window: NSWindow?
    private var model: SettingsModel?
    private var titles: AnyCancellable?
    weak var actions: SettingsActions?
    /// The app's model downloads, which the first-start window shares.
    var downloads = ModelDownloads()

    func show() {
        let model = self.model ?? SettingsModel(actions: actions, downloads: downloads)
        self.model = model
        model.reload()
        actions?.askServer()  // its info may be older than a download that the first start's window began
        if window == nil {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 760, height: 560),
                             styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
            w.isReleasedWhenClosed = false
            w.minSize = NSSize(width: 640, height: 420)
            w.contentView = NSHostingView(rootView: SettingsView(model: model))
            w.standardWindowButton(.zoomButton)?.isEnabled = false
            w.center()
            w.setFrameAutosaveName("EchoFoxSettings")
            w.delegate = self
            titles = model.$selection.combineLatest(model.$info).sink { [weak w] item, info in
                w?.title = item?.title(adapters: info?.adapters ?? []) ?? "Settings"
            }
            window = w
        }
        if let window { DockPresence.bringForward(window) }
    }

    /// The server's info changed: the window shows it.
    func refresh() { model?.serverChanged() }

    /// The config changed: the window shows it.
    func configChanged(_ config: Config) { model?.config = config }

    func windowWillClose(_ notification: Notification) {
        model?.watchServer(false)
        window = nil
        titles = nil
    }
}

final class SettingsModel: ObservableObject {
    @Published var config = Config()
    @Published var info: ServerInfo?
    @Published var problem: String?
    @Published var inputs: [AudioInput] = []
    @Published var volume: Float?
    /// The page shown; kept for the next launch (a viewer's convenience, so UserDefaults), in SidebarItem's form.
    @Published var selection: SidebarItem? = SidebarItem(saved: UserDefaults.standard.string(forKey: "settingsPage"))
                                                ?? .page(.general) {
        didSet { UserDefaults.standard.set(selection?.saved, forKey: "settingsPage") }
    }
    @Published var adaptersOpen = true
    /// The Advanced sections that are open, by page or adapter: closed until a click.
    @Published var advancedOpen: Set<String> = []
    @Published var labels = (count: 0, seconds: 0.0)
    /// What is typed in a field and not written yet, and the fields whose text was refused; by the field's id.
    @Published var drafts: [String: String] = [:]
    @Published var refused: Set<String> = []
    /// The variant whose removal waits for the user's confirmation (the window keeps no view state of its own).
    @Published var confirmRemoval: String?
    weak var actions: SettingsActions?

    let downloads: ModelDownloads
    private var downloadsChanged: AnyCancellable?
    private var watch: Timer?

    init(actions: SettingsActions?, downloads: ModelDownloads) {
        self.actions = actions
        self.downloads = downloads
        downloadsChanged = downloads.objectWillChange.sink { [weak self] in self?.objectWillChange.send() }
    }

    /// Everything the window shows, read again: when it opens.
    func reload() {
        config = actions?.config ?? Config()
        serverChanged()
        microphoneChanged()
        let labeled = config.folders(info).labeled  // the label files are read off the main thread
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let stats = Labeling.stats(labeled: labeled)
            DispatchQueue.main.async { self?.labels = stats }
        }
    }

    func serverChanged() {
        (info, problem) = actions?.serverState() ?? (nil, nil)
    }

    func microphoneChanged() {
        config = actions?.config ?? config
        inputs = AudioInputs.all()
        let device = AudioInputs.chosen(config.microphone).device
        volume = device.flatMap(AudioInputs.volume)
    }

    /// Asks the server for its state now and every Tuning.serverStatusPollSeconds, while the state is shown.
    func watchServer(_ on: Bool) {
        watch?.invalidate()
        watch = nil
        guard on else { return }
        actions?.askServer()
        watch = Timer.scheduledTimer(withTimeInterval: Tuning.serverStatusPollSeconds, repeats: true) { [weak self] _ in
            self?.actions?.askServer()
        }
    }

    // MARK: What the window shows

    /// The server's adapters, for their names (ServerInfo.adapterTitle).
    var adapters: [ServerInfo.Adapter] { info?.adapters ?? [] }

    /// The menu's model, whose settings, variants and prompt the window shows (SettingStore.menuModel).
    var menuModel: String? { SettingStore.menuModel(in: config, info: info) }

    /// The server's settings and the app's own.
    var settings: [SettingInfo] { (info?.settings ?? []) + SettingsLayout.appSettings }
    var adapterSettings: [SettingInfo] { settings.filter { $0.owner == "adapter" } }
    func setting(_ key: String) -> SettingInfo? { settings.first { $0.key == key } }

    func sections(_ page: SettingsPage) -> [(section: String, ids: [String])] {
        let keys = (info?.settings ?? []).map { (key: $0.key, owner: $0.owner, group: $0.group, advanced: $0.advanced == true) }
        return SettingsLayout.sections(of: page, serverKeys: keys)
    }

    func state(_ s: SettingInfo, _ scope: SettingScope = .owner) -> SettingState {
        SettingStore.state(of: s, in: config, scope: scope, info: info)
    }

    /// The setting that a page item shows, if it is one.
    func shown(_ id: String) -> [(SettingInfo, SettingScope)] { setting(id).map { [($0, .owner)] } ?? [] }

    /// How many of these settings differ from what they would be without a value here: for an Advanced's title.
    func changed(_ settings: [(SettingInfo, SettingScope)]) -> Int {
        settings.filter { state($0.0, $0.1).changed }.count
    }

    // MARK: Fields

    /// A text field's text: its draft while one is typed, else `shown` (the value in force).
    func draft(_ id: String, shown: String) -> Binding<String> {
        Binding(get: { self.drafts[id] ?? shown }, set: { self.drafts[id] = $0 })
    }

    func isOpen(_ id: String) -> Binding<Bool> {
        Binding(get: { self.advancedOpen.contains(id) },
                set: { if $0 { self.advancedOpen.insert(id) } else { self.advancedOpen.remove(id) } })
    }

    func done(_ id: String) {
        drafts[id] = nil
        refused.remove(id)
    }

    // MARK: Writes

    /// What the user entered in a SettingRow, as SettingStore's edit says: written, taken out, or refused and marked.
    func apply(_ edit: SettingEdit, to s: SettingInfo, _ scope: SettingScope, id: String) {
        guard edit != .refuse else {
            refused.insert(id)
            return
        }
        done(id)
        apply(SettingStore.change(edit, of: s, scope: scope, in: config, info: info))
    }

    /// A change that SettingStore made, into the config through the app's ConfigStore; the window shows the config it
    /// then has. Every write of the window goes here.
    func apply(_ change: ConfigChange?) {
        switch change {
        case nil: return
        case let .set(path, value)?: actions?.write(path, value, "settings: \(path.joined(separator: ".")) = \(value)")
        case let .remove(path)?: actions?.remove(path, "settings: \(path.joined(separator: ".")) back to its default")
        }
        config = actions?.config ?? config
    }

    // MARK: Model variants

    /// The downloads and removals of model variants that the app started, by variant (ModelDownloads).
    var jobs: [String: ModelJob] { downloads.jobs }

    func download(catalog: String, variant: String) {
        downloads.download(catalog: catalog, variant: variant, url: config.serverURL)
    }

    func cancel(_ variant: String) { downloads.cancel(variant) }

    func remove(catalog: String, variant: String) {
        downloads.remove(catalog: catalog, variant: variant, url: config.serverURL)
    }
}
