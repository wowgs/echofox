// The settings window (docs/design/5-ui.md): pages in a sidebar, each built from SettingsLayout. A setting described
// by a SettingInfo (the server's in its info, the app's in SettingsLayout.appSettings) is one SettingRow: a switch, a
// number or a text, with what is in force and where it comes from (SettingStore.state), and a button that takes the
// value out of the config. The app's other items (the hotkeys, the microphone, the model, the prompt, the adapters,
// the labels, the server's state) have views of their own. The window only reads and writes the config and asks the
// App; it decides nothing.
import AppKit
import Combine
import LocalVoiceCore
import SwiftUI

protocol SettingsActions: AnyObject {
    func serverState() -> (info: ServerInfo?, problem: String?)
    /// Asks the server for its info once it applied a change of the config; the window hears the answer (refresh).
    func refreshServer()
    /// Asks the server for its info now.
    func askServer()
    @discardableResult func write(_ path: [String], _ value: Any, _ done: String) -> Bool
    @discardableResult func remove(_ path: [String], _ done: String) -> Bool
    func choose(microphone: String)
    func setInputVolume(_ value: Float)
    func keysChanged()
    func openLabeling()
    func openLog()
}

/// The settings window (Apple HIG, Settings): its minimize and zoom buttons dimmed, its title the visible page's, and
/// it opens again on the page last viewed, with the same Advanced sections open.
final class SettingsWindow: NSObject, NSWindowDelegate {
    private var window: NSWindow?
    private var model: SettingsModel?
    private var titles: AnyCancellable?
    weak var actions: SettingsActions?

    func show() {
        let model = self.model ?? SettingsModel(actions: actions)
        self.model = model
        model.reload()
        if window == nil {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 760, height: 560),
                             styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
            w.isReleasedWhenClosed = false
            w.minSize = NSSize(width: 640, height: 420)
            w.contentView = NSHostingView(rootView: SettingsView(model: model))
            w.standardWindowButton(.zoomButton)?.isEnabled = false
            w.center()
            w.setFrameAutosaveName("LocalVoiceSettings")
            w.delegate = self
            titles = model.$selection.sink { [weak w] item in w?.title = item?.title ?? "Settings" }
            window = w
        }
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    /// The server's info changed: the window shows it.
    func refresh() { model?.serverChanged() }

    func windowWillClose(_ notification: Notification) {
        model?.watchServer(false)
        window = nil
        titles = nil
    }
}

final class SettingsModel: ObservableObject {
    @Published var config = Config.load()
    @Published var info: ServerInfo?
    @Published var problem: String?
    @Published var inputs: [AudioInput] = []
    @Published var volume: Float?
    /// The page shown; kept for the next launch (a viewer's convenience, so UserDefaults).
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
    weak var actions: SettingsActions?

    /// A text field's text: its draft while one is typed, else `shown` (the value in force).
    func draft(_ id: String, shown: String) -> Binding<String> {
        Binding(get: { self.drafts[id] ?? shown }, set: { self.drafts[id] = $0 })
    }

    func isOpen(_ id: String) -> Binding<Bool> {
        Binding(get: { self.advancedOpen.contains(id) },
                set: { if $0 { self.advancedOpen.insert(id) } else { self.advancedOpen.remove(id) } })
    }

    func state(_ s: SettingInfo, _ scope: SettingScope = .owner) -> SettingState {
        SettingStore.state(of: s, in: config, scope: scope)
    }

    /// The setting that a page item shows, if it is one.
    func shown(_ id: String) -> [(SettingInfo, SettingScope)] { setting(id).map { [($0, .owner)] } ?? [] }

    /// How many of these settings differ from what they would be without a value here: for an Advanced's title.
    func changed(_ settings: [(SettingInfo, SettingScope)]) -> Int {
        settings.filter { state($0.0, $0.1).changed }.count
    }

    /// Writes or takes out the value of a setting, as SettingStore's edit says; a refused one is marked.
    func apply(_ edit: SettingEdit, to s: SettingInfo, _ scope: SettingScope, id: String) {
        guard let path = state(s, scope).path else { return }
        switch edit {
        case let .write(v):
            done(id)
            if let json = SettingStore.json(v, of: s) { write(path, json) }
        case .remove:
            done(id)
            if config.value(path) != nil { remove(path) }
        case .refuse:
            refused.insert(id)
        }
    }

    func done(_ id: String) {
        drafts[id] = nil
        refused.remove(id)
    }

    init(actions: SettingsActions?) { self.actions = actions }

    /// Everything the window shows, read again: when it opens.
    func reload() {
        config = Config.load()
        serverChanged()
        microphoneChanged()
        labels = Self.labelStats(config.labeled)
    }

    func serverChanged() { (info, problem) = actions?.serverState() ?? (nil, nil) }

    /// The downloads and removals of model variants that this window started, by variant.
    @Published var jobs: [String: ModelJob] = [:]

    func download(catalog: String, variant: String) {
        let job = ModelJob(url: config.serverURL, message: ClientMessage.download(catalog: catalog, variant: variant))
        job.onChange = { [weak self] in
            self?.objectWillChange.send()
            if job.finished { self?.actions?.askServer() }  // the variant is downloaded, or not
        }
        jobs[variant] = job
        job.start()
    }

    func cancel(_ variant: String) { jobs[variant]?.cancel() }

    func remove(catalog: String, variant: String) {
        let job = ModelJob(url: config.serverURL, message: ClientMessage.remove(catalog: catalog, variant: variant))
        job.onChange = { [weak self] in
            self?.objectWillChange.send()
            if job.finished { self?.actions?.askServer() }
        }
        jobs[variant] = job
        job.start()
    }

    private var watch: Timer?

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

    func microphoneChanged() {
        config = Config.load()
        inputs = AudioInputs.all()
        let device = AudioInputs.chosen(config.microphone).input?.id ?? AudioInputs.defaultInput()
        volume = device.flatMap(AudioInputs.volume)
    }

    /// The server's settings and the app's own.
    var settings: [SettingInfo] { (info?.settings ?? []) + SettingsLayout.appSettings }
    var adapterSettings: [SettingInfo] { settings.filter { $0.owner == "adapter" } }
    func setting(_ key: String) -> SettingInfo? { settings.first { $0.key == key } }

    func sections(_ page: SettingsPage) -> [(section: String, ids: [String])] {
        let keys = (info?.settings ?? []).map { (key: $0.key, owner: $0.owner, group: $0.group, advanced: $0.advanced == true) }
        return SettingsLayout.sections(of: page, serverKeys: keys)
    }

    /// A value into the config; the window then reads the config again, and only it.
    func write(_ path: [String], _ value: Any) {
        actions?.write(path, value, "settings: \(path.joined(separator: ".")) = \(value)")
        config = Config.load()
    }

    func remove(_ path: [String]) {
        actions?.remove(path, "settings: \(path.joined(separator: ".")) back to its default")
        config = Config.load()
    }

    /// The labeled pieces and their seconds of audio, from the label files.
    static func labelStats(_ labeled: URL) -> (count: Int, seconds: Double) {
        guard let e = FileManager.default.enumerator(at: labeled, includingPropertiesForKeys: nil) else { return (0, 0) }
        var count = 0, seconds = 0.0
        for case let url as URL in e where url.lastPathComponent == "label.json" {
            guard let d = (try? JSONSerialization.jsonObject(with: Data(contentsOf: url))) as? [String: Any],
                  d["status"] as? String == "verified" else { continue }
            count += 1
            seconds += d["audioSeconds"] as? Double ?? 0
        }
        return (count, seconds)
    }
}

/// A row of the sidebar: a page, or one adapter under the page Adapters.
enum SidebarItem: Hashable {
    case page(SettingsPage)
    case adapter(String)

    var title: String {
        switch self {
        case let .page(p): return p.title
        case let .adapter(name): return adapterTitle(name)
        }
    }

    /// As UserDefaults keeps it: "page.model", "adapter.claude".
    var saved: String {
        switch self {
        case let .page(p): return "page." + p.rawValue
        case let .adapter(name): return "adapter." + name
        }
    }

    init?(saved: String?) {
        guard let saved, let dot = saved.firstIndex(of: ".") else { return nil }
        let kind = saved[..<dot], name = String(saved[saved.index(after: dot)...])
        if kind == "page", let p = SettingsPage(rawValue: name) { self = .page(p) }
        else if kind == "adapter", !name.isEmpty { self = .adapter(name) }
        else { return nil }
    }
}

/// An adapter's name for people: "claude" → "Claude".
func adapterTitle(_ name: String) -> String { name.prefix(1).uppercased() + name.dropFirst() }

struct SettingsView: View {
    @ObservedObject var model: SettingsModel

    var body: some View {
        NavigationSplitView {
            List(selection: $model.selection) {
                ForEach(SettingsLayout.sidebar, id: \.self) { entry in
                    switch entry {
                    case let .page(page):
                        Label(page.title, systemImage: page.symbol).tag(SidebarItem.page(page))
                    case .adapters:
                        // A heading, not a page: a click anywhere on it opens or closes the adapters' rows.
                        DisclosureGroup(isExpanded: $model.adaptersOpen) {
                            ForEach(model.info?.adapters ?? [], id: \.name) { a in
                                AdapterSidebarRow(model: model, adapter: a).tag(SidebarItem.adapter(a.name))
                            }
                        } label: {
                            Button {
                                withAnimation { model.adaptersOpen.toggle() }
                            } label: {
                                HStack {
                                    Label(SidebarEntry.adaptersTitle, systemImage: SidebarEntry.adaptersSymbol)
                                    Spacer()
                                }
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
            .navigationSplitViewColumnWidth(min: 190, ideal: 210)
        } detail: {
            switch model.selection {
            case let .page(page)?: PageView(model: model, page: page)
            case let .adapter(name)?:
                if let a = model.info?.adapters.first(where: { $0.name == name }) {
                    AdapterPage(model: model, adapter: a)
                } else {
                    Text("The server does not have this adapter any more.").foregroundStyle(.secondary)
                }
            case nil: EmptyView()
            }
        }
    }
}

/// An adapter in the sidebar: the icon of the app it reads, its name (grey when it is off), and a dot for its state
/// as on the page Diagnostics: green when it is on, red when it does not work, none when it is off.
struct AdapterSidebarRow: View {
    @ObservedObject var model: SettingsModel
    let adapter: ServerInfo.Adapter

    private var on: Bool { model.config.adapters[adapter.name] == true }

    var body: some View {
        Label {
            HStack {
                Text(adapterTitle(adapter.name)).foregroundStyle(on || adapter.error != nil ? .primary : .secondary)
                Spacer()
                if adapter.error != nil { StatusDot(color: .red) } else if on { StatusDot(color: .green) }
            }
        } icon: {
            AppIcon(bundleIds: adapter.apps)
        }
        .help(adapter.error.map { "It does not work: \($0)" } ?? (on ? "On" : "Off"))
    }
}

struct PageView: View {
    @ObservedObject var model: SettingsModel
    let page: SettingsPage

    var body: some View {
        Form {
            if model.info == nil && [.general, .model, .recordings].contains(page) {
                Text("The dictation server is not answering. Its settings appear here when it answers.")
                    .foregroundStyle(.secondary)
            }
            ForEach(model.sections(page), id: \.section) { section in
                if section.section == SettingsLayout.advanced {
                    AdvancedSection(model: model, id: page.rawValue,
                                    changed: model.changed(section.ids.flatMap(model.shown))) {
                        ForEach(section.ids, id: \.self) { id in ItemView(model: model, id: id) }
                    }
                } else {
                    Section(section.section) {
                        ForEach(section.ids, id: \.self) { id in ItemView(model: model, id: id) }
                    }
                }
            }
        }
        .formStyle(.grouped)
    }
}

/// One item of a page: one of the app's own, or a server setting from its description.
struct ItemView: View {
    @ObservedObject var model: SettingsModel
    let id: String

    var body: some View {
        switch id {
        case "dictationKey": KeyPicker(model: model, isPrivate: false, title: "Dictation",
                                       note: "Tap to start and stop. The text goes where the cursor was.")
        case "privateDictationKey": KeyPicker(model: model, isPrivate: true, title: "Private dictation",
                                              note: "Reads nothing on the screen and saves nothing.")
        case "language": LanguagePicker(model: model)
        case "languageNotes": LanguageList(model: model, field: "notes", title: "Notes for the model",
                                           note: "Rules about this language for the model, one on each line.")
        case "languageFillers": LanguageList(model: model, field: "fillers", title: "Hesitation sounds",
                                             note: "Removed from the text. Separate them with commas.")
        case "microphone": MicrophonePicker(model: model)
        case "inputVolume": VolumeRow(model: model)
        case "model": ModelPicker(model: model)
        case "variant": VariantPicker(model: model)
        case "prompt": PromptEditor(model: model)
        case "labelStats":
            LabeledContent("Labeled") {
                Text("\(model.labels.count) pieces, \(String(format: "%.1f", model.labels.seconds / 60)) min")
            }
        case "labelRecordings": Button("Label Recordings…") { model.actions?.openLabeling() }
        case "serverStatus": ServerStatus(model: model)
        case "openLog": Button("Open the Log") { model.actions?.openLog() }
        default:
            if let s = model.setting(id) { SettingRow(model: model, setting: s, scope: .owner) }
        }
    }
}

/// What to type when a number was refused, next to its field (Apple HIG, Writing: say how to enter it correctly):
/// "Enter a number from 5 to 30."
func allowedValues(_ s: SettingInfo) -> String {
    let what = s.kind == "integer" ? "a whole number" : "a number"
    let lo = s.min.map { show(.number($0)) }, hi = s.max.map { show(.number($0)) }
    let above = s.minExclusive == true, below = s.maxExclusive == true
    switch (lo, hi) {
    case let (l?, h?): return "Enter \(what) " + (above ? "above \(l)" : "from \(l)") + (below ? " and below \(h)." : " to \(h).")
    case let (l?, nil): return "Enter \(what) " + (above ? "above \(l)." : "of \(l) or more.")
    case let (nil, h?): return "Enter \(what) " + (below ? "below \(h)." : "of \(h) or less.")
    default: return "Enter \(what)."
    }
}

func show(_ v: SettingValue?) -> String {
    switch v {
    case let .number(n)?: return n == n.rounded() && abs(n) < 1e9 ? String(Int(n)) : String(n)
    case let .bool(b)?: return b ? "on" : "off"
    case let .string(s)?: return s
    default: return ""
    }
}

/// Where the value in force comes from, for an adapter's setting: its own default, or the built-in one.
func sourceNote(_ state: SettingState) -> String {
    if state.changed { return "Set here." }
    switch state.source {
    case let .adapter(name): return "From the \(adapterTitle(name)) defaults."
    case .ownerDefault: return "The built-in default."
    }
}

/// A setting described by a SettingInfo, in one scope: a switch, a number or a text; the inherited value is the empty
/// field's placeholder; the reset button takes the value out of the config.
struct SettingRow: View {
    @ObservedObject var model: SettingsModel
    let setting: SettingInfo
    let scope: SettingScope

    private var id: String {
        switch scope {
        case .owner: return "setting." + setting.key
        case let .adapter(a): return "adapter.\(a.name).\(setting.key)"
        }
    }
    private var state: SettingState { model.state(setting, scope) }
    private var refused: Bool { model.refused.contains(id) }
    /// The field's text: the value set here; empty when it is inherited (the placeholder shows it).
    private var shown: String { setting.kind == "string" ? show(state.value) : state.own.map { show($0) } ?? "" }

    private var note: String? {
        if refused { return allowedValues(setting) }
        let parts = [setting.help, scope == .owner ? "" : sourceNote(state)].filter { !$0.isEmpty }
        return parts.isEmpty ? nil : parts.joined(separator: " ")
    }

    var body: some View {
        SettingLine(title: setting.title, note: note, refused: refused,
                    pending: model.drafts[id].map { $0 != shown } ?? false) {
            control
            ResetButton(visible: state.changed, help: "Restore the default") {
                model.apply(.remove, to: setting, scope, id: id)
            }
        }
        .disabled(state.path == nil || disabledAdapter)
    }

    /// A setting of an adapter that is off: shown, not changed.
    private var disabledAdapter: Bool {
        if case let .adapter(a) = scope { return model.config.adapters[a.name] != true }
        return false
    }

    @ViewBuilder private var control: some View {
        switch setting.kind {
        case "boolean":
            Toggle("", isOn: Binding(get: { state.value == .bool(true) },
                                     set: { model.apply(SettingStore.toggle($0, state: state), to: setting, scope, id: id) }))
                .labelsHidden().toggleStyle(.switch)
        case "string":
            InputField(text: model.draft(id, shown: shown), width: 240, refused: refused, onSubmit: commit)
            if setting.key.hasSuffix("Folder") || setting.key == "recordings" || setting.key == "labeled" {
                Button("Choose…") {
                    if let folder = chooseFolder(starting: shown) {
                        model.apply(SettingStore.edit(folder, of: setting, state: state), to: setting, scope, id: id)
                    }
                }
            }
        default:
            InputField(placeholder: show(state.inherited), text: model.draft(id, shown: shown), width: 80, number: true,
                       refused: refused, onSubmit: commit)
            UnitLabel(unit: unit(of: setting.key))
        }
    }

    private func commit() {
        guard let text = model.drafts[id] else { return }
        model.apply(SettingStore.edit(text, of: setting, state: state), to: setting, scope, id: id)
    }
}

struct KeyPicker: View {
    @ObservedObject var model: SettingsModel
    let isPrivate: Bool, title: String, note: String

    private var path: String { isPrivate ? "privateDictationKey" : "dictationKey" }
    private var current: TapKeyChoice? { isPrivate ? model.config.privateDictationKey : model.config.dictationKey }
    private var other: TapKeyChoice? { isPrivate ? model.config.dictationKey : model.config.privateDictationKey }
    private var clash: Bool { current != nil && current == other }

    var body: some View {
        SettingLine(title: title, note: clash ? "The other dictation uses this key too. Choose another one." : note,
                    refused: clash) {
            Picker(title, selection: Binding(get: { current?.rawValue ?? "none" }, set: { v in
                model.write([path], v)
                model.actions?.keysChanged()
            })) {
                ForEach(TapKeyChoice.allCases, id: \.rawValue) { Text($0.title).tag($0.rawValue) }
                Text("None").tag("none")
            }
            .labelsHidden()
            .fixedSize()
        }
    }
}

struct LanguagePicker: View {
    @ObservedObject var model: SettingsModel

    var body: some View {
        Picker("Language", selection: Binding(get: { model.config.language }, set: { model.write(["language"], $0) })) {
            Text("Any").tag("")
            ForEach(model.info?.languages ?? [], id: \.code) { Text($0.name).tag($0.code) }
            if !model.config.language.isEmpty, !(model.info?.languages ?? []).contains(where: { $0.code == model.config.language }) {
                Text(model.config.language).tag(model.config.language)
            }
        }
    }
}

struct MicrophonePicker: View {
    @ObservedObject var model: SettingsModel

    /// The config's microphone is one of the choices: a connected device, the built-in one, or macOS's input.
    private var chosenIsListed: Bool {
        let m = model.config.microphone
        return m == Config.builtInMicrophone || m == Config.systemMicrophone || model.inputs.contains { $0.uid == m }
    }

    var body: some View {
        Picker("Microphone", selection: Binding(get: { model.config.microphone }, set: {
            model.actions?.choose(microphone: $0)
            model.microphoneChanged()
        })) {
            ForEach(model.inputs, id: \.uid) { input in
                Text(input.name + (input.builtIn ? " (built-in)" : "")).tag(input.builtIn ? Config.builtInMicrophone : input.uid)
            }
            Text("Follow macOS's input").tag(Config.systemMicrophone)
            if !chosenIsListed { Text("Not connected").tag(model.config.microphone) }
        }
    }
}

struct VolumeRow: View {
    @ObservedObject var model: SettingsModel

    var body: some View {
        if let v = model.volume {
            LabeledContent("Input volume") {
                Slider(value: Binding(get: { Double(v) }, set: { x in
                    model.actions?.setInputVolume(Float(x))
                    model.volume = Float(x)
                }), in: 0...1).frame(width: 220)
                Text("\(Int((Double(v) * 100).rounded()))%").monospacedDigit().frame(width: 44, alignment: .trailing)
            }
        } else {
            LabeledContent("Input volume") { Text("This microphone has no volume control.").foregroundStyle(.secondary) }
        }
    }
}

struct ModelPicker: View {
    @ObservedObject var model: SettingsModel

    var body: some View {
        Picker("Model", selection: Binding(get: { model.config.model ?? "" }, set: { model.write(["model"], $0) })) {
            ForEach(model.config.models, id: \.self) { Text($0).tag($0) }
        }
        if let e = model.config.error { Text(e).font(.caption).foregroundStyle(.red) }
    }
}

/// The variants of the menu's model: one quantization of it each, with the size of its files. Only a variant whose
/// files are in the models folder can be chosen; another one has Download, with its progress; one that is there and
/// not in force has Remove.
struct VariantPicker: View {
    @ObservedObject var model: SettingsModel

    private var info: ServerInfo.Model? { model.info?.model }

    var body: some View {
        if let variants = info?.variants, !variants.isEmpty, let name = model.config.model {
            SettingLine(title: "Quantization",
                        note: "A smaller one uses less memory and is faster. The model starts again after the recording.") {
                Picker("Quantization", selection: Binding(get: { info?.variant ?? "" }, set: { v in
                    guard variants.first(where: { $0.id == v })?.downloaded == true else { return }  // its files first
                    model.write(["models", name, "variant"], v)
                    model.actions?.refreshServer()
                })) {
                    ForEach(variants, id: \.id) { v in
                        Text("\(v.name), \(gigabytes(v.bytes))" + (v.downloaded ? "" : " (not downloaded)")).tag(v.id)
                    }
                }
                .labelsHidden()
                .fixedSize()
            }
            ForEach(variants.filter { $0.id != info?.variant }, id: \.id) { v in
                VariantFiles(model: model, catalog: info?.catalog ?? "", variant: v)
            }
        }
    }
}

func gigabytes(_ bytes: Double) -> String { String(format: "%.1f GB", bytes / 1e9) }

/// The files of a variant not in force: Download with its progress, or Remove.
struct VariantFiles: View {
    @ObservedObject var model: SettingsModel
    let catalog: String
    let variant: ServerInfo.Variant

    private var job: ModelJob? { model.jobs[variant.id] }

    var body: some View {
        SettingLine(title: variant.name, note: note, refused: job?.error != nil) {
            if let job, job.error == nil, !job.finished {
                ProgressView(value: job.total > 0 ? job.bytes / job.total : 0).frame(width: 140)
                Button("Cancel") { model.cancel(variant.id) }
            } else if variant.downloaded {
                Button("Remove") { model.remove(catalog: catalog, variant: variant.id) }
            } else {
                Button("Download") { model.download(catalog: catalog, variant: variant.id) }
            }
        }
    }

    private var note: String {
        if let e = job?.error { return e }
        if let job, !job.finished { return "\(gigabytes(job.bytes)) of \(gigabytes(job.total))" }
        return variant.downloaded ? "Downloaded, \(gigabytes(variant.bytes))." : "Not downloaded, \(gigabytes(variant.bytes))."
    }
}

/// The model's prompt template: its own in the config, or its catalog entry's. The language's notes follow it.
struct PromptEditor: View {
    @ObservedObject var model: SettingsModel
    private var id: String { "prompt." + (model.config.model ?? "") }

    private var path: [String]? { model.config.model.map { ["models", $0, "prompt"] } }
    private var own: String? { path.flatMap { model.config.value($0) as? String } }
    private var catalog: String { model.info?.model?.prompt ?? "" }
    private var shown: String { own ?? catalog }
    private var text: String { model.drafts[id] ?? shown }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            TextEditor(text: model.draft(id, shown: shown)).font(.system(.body, design: .monospaced))
                .frame(minHeight: 160).inputBox()
            HStack {
                Text("{LANGUAGE} is replaced with the language. Its notes come after the prompt.")
                    .font(.caption).foregroundStyle(.secondary)
                Spacer()
                if own != nil {
                    Button("Restore Default") { if let p = path { model.done(id); model.remove(p) } }
                }
                Button("Save") {
                    let t = text
                    model.done(id)
                    if let p = path { model.write(p, t) }
                }
                .keyboardShortcut("s", modifiers: .command)
                .buttonStyle(.borderedProminent)
                .disabled(text == shown)
            }
        }
    }
}

/// A language's list (its notes or its hesitation sounds): the config's for the language, else the table's.
struct LanguageList: View {
    @ObservedObject var model: SettingsModel
    let field: String, title: String, note: String

    private var code: String { String(model.config.language.prefix(while: { $0 != "-" })) }
    private var id: String { "language.\(code).\(field)" }
    private var path: [String] { ["languages", code, field] }
    private var own: [String]? { model.config.value(path) as? [String] }
    private var defaults: [String] {
        let l = model.info?.languages.first { $0.code == code }
        return (field == "notes" ? l?.notes : l?.fillers) ?? []
    }
    private var separator: String { field == "notes" ? "\n" : ", " }
    private var shown: String { (own ?? defaults).joined(separator: separator) }

    var body: some View {
        if code.isEmpty {
            Text("Choose a language to see its notes and sounds.").foregroundStyle(.secondary)
        } else {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(title)
                    Spacer()
                    ResetButton(visible: own != nil, help: "Restore the defaults of the language") {
                        model.done(id)
                        model.remove(path)
                    }
                }
                if field == "notes" {
                    TextEditor(text: model.draft(id, shown: shown)).frame(minHeight: 60).inputBox()
                } else {
                    InputField(text: model.draft(id, shown: shown), width: 360) { save() }
                }
                HStack {
                    Text(note).font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    if field == "notes" { Button("Save") { save() }.disabled((model.drafts[id] ?? shown) == shown) }
                }
            }
        }
    }

    private func save() {
        guard let text = model.drafts[id] else { return }
        let items = text.components(separatedBy: field == "notes" ? "\n" : ",")
            .map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        model.done(id)
        model.write(path, items)
    }
}

/// An Advanced section: closed until a click; its title says how many of its settings differ from what they would be
/// without a value there, so that a change is never out of sight.
struct AdvancedSection<Content: View>: View {
    @ObservedObject var model: SettingsModel
    let id: String
    let changed: Int
    @ViewBuilder var content: () -> Content

    var body: some View {
        Section {
            DisclosureGroup(isExpanded: model.isOpen(id)) {
                content()
            } label: {
                // The whole row, not only the triangle: a click anywhere on it opens or closes the section.
                Button {
                    withAnimation { model.isOpen(id).wrappedValue.toggle() }
                } label: {
                    HStack {
                        Text(SettingsLayout.advanced)
                        if changed > 0 { Text("\(changed) changed").font(.caption).foregroundStyle(.secondary) }
                        Spacer()
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityHint("Shows or hides the advanced settings")
            }
        }
    }
}

struct AdapterSwitch: View {
    @ObservedObject var model: SettingsModel
    let adapter: ServerInfo.Adapter

    var body: some View {
        Toggle("", isOn: Binding(get: { model.config.adapters[adapter.name] == true }, set: { on in
            model.write(["adapters", adapter.name, "enabled"], on)
            model.actions?.refreshServer()
        }))
        .labelsHidden().toggleStyle(.switch)
    }
}

/// One adapter's page: whether it works, what it reads, its settings.
struct AdapterPage: View {
    @ObservedObject var model: SettingsModel
    let adapter: ServerInfo.Adapter

    var body: some View {
        Form {
            Section("Adapter") {
                SettingLine(title: "On", note: adapter.description) { AdapterSwitch(model: model, adapter: adapter) }
                if let e = adapter.error {
                    LabeledContent("Problem") { Text(e).foregroundStyle(.red).textSelection(.enabled) }
                }
            }
            Section("What it reads") {
                LabeledContent("Apps") { Text(adapter.apps.joined(separator: "\n")).textSelection(.enabled) }
                if let reads = adapter.reads, !reads.isEmpty {
                    LabeledContent("Files") { Text(reads.joined(separator: "\n")).textSelection(.enabled) }
                }
                if let screen = adapter.screen, !screen.isEmpty {
                    LabeledContent("Screen") {
                        Text(screen.contains("lists") ? "the rows of the lists in the focused window" : screen.joined(separator: ", "))
                    }
                }
                if adapter.electronTree {
                    LabeledContent("Accessibility") { Text("Asks the app to expose its window content.") }
                }
            }
            AdvancedSection(model: model, id: "adapter." + adapter.name,
                            changed: model.changed(model.adapterSettings.map { ($0, .adapter(adapter)) })) {
                ForEach(model.adapterSettings, id: \.key) { s in
                    SettingRow(model: model, setting: s, scope: .adapter(adapter))
                }
            }
        }
        .formStyle(.grouped)
    }
}

/// The dictation server's state, asked in the background while it is shown: a dot as in macOS's own settings (green:
/// it answers; red: it does not, and why; grey: not asked yet).
struct ServerStatus: View {
    @ObservedObject var model: SettingsModel

    private var state: (color: Color, text: String) {
        if let p = model.problem { return (.red, p) }
        if model.info != nil { return (.green, "Running") }
        return (.secondary, "Checking…")
    }

    var body: some View {
        LabeledContent("Dictation server") { Text(model.config.serverURL.absoluteString).textSelection(.enabled) }
        LabeledContent("State") {
            HStack(spacing: 6) {
                StatusDot(color: state.color)
                Text(state.text).textSelection(.enabled)
            }
            .accessibilityElement(children: .combine)
        }
        .onAppear { model.watchServer(true) }
        .onDisappear { model.watchServer(false) }
        LabeledContent("Model") { Text(model.config.model ?? "none") }
    }
}
