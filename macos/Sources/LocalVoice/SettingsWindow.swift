// The settings window (docs/design/5-ui.md): pages in a sidebar, each built from SettingsLayout. The server's
// settings are drawn from their description in the server's info (SettingInfo): a switch, a number with its range,
// or a text, each with its default and a button that takes the value out of the config (back to the default). The
// app's own items (the hotkeys, the microphone, the model, the prompt, the adapters, the labels, the server's state)
// have views of their own. The window only reads and writes the config and asks the App; it decides nothing.
import AppKit
import LocalVoiceCore
import SwiftUI

protocol SettingsActions: AnyObject {
    func serverState() -> (info: ServerInfo?, problem: String?)
    func refreshServer()
    @discardableResult func write(_ path: [String], _ value: Any, _ done: String) -> Bool
    @discardableResult func remove(_ path: [String], _ done: String) -> Bool
    func choose(microphone: String)
    func setInputVolume(_ value: Float)
    func keysChanged()
    func openLabeling()
    func openLog()
}

final class SettingsWindow: NSObject, NSWindowDelegate {
    private var window: NSWindow?
    private var model: SettingsModel?
    weak var actions: SettingsActions?

    func show() {
        if let window {
            model?.reload()
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        let model = SettingsModel(actions: actions)
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 760, height: 560),
                         styleMask: [.titled, .closable, .resizable, .miniaturizable], backing: .buffered, defer: false)
        w.title = "Local Voice Settings"
        w.isReleasedWhenClosed = false
        w.minSize = NSSize(width: 640, height: 420)
        w.contentView = NSHostingView(rootView: SettingsView(model: model))
        w.center()
        w.setFrameAutosaveName("LocalVoiceSettings")
        w.delegate = self
        window = w
        self.model = model
        model.reload()
        w.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    /// The config or the server changed elsewhere (the menu, the server's info): the window shows it.
    func refresh() { model?.reload() }

    func windowWillClose(_ notification: Notification) {
        window = nil
        model = nil
    }
}

final class SettingsModel: ObservableObject {
    @Published var config = Config.load()
    @Published var info: ServerInfo?
    @Published var problem: String?
    @Published var inputs: [AudioInput] = []
    @Published var volume: Float?
    @Published var selection: SidebarItem? = .page(.general)
    @Published var adaptersOpen = true
    @Published var labels = (count: 0, seconds: 0.0)
    /// What is typed in a field and not written yet, and the fields whose text was refused; by the field's id.
    @Published var drafts: [String: String] = [:]
    @Published var refused: Set<String> = []
    weak var actions: SettingsActions?

    /// A text field's text: its draft while one is typed, else `shown` (the value in force).
    func draft(_ id: String, shown: String) -> Binding<String> {
        Binding(get: { self.drafts[id] ?? shown }, set: { self.drafts[id] = $0 })
    }

    func done(_ id: String) {
        drafts[id] = nil
        refused.remove(id)
    }

    init(actions: SettingsActions?) { self.actions = actions }

    func reload() {
        config = Config.load()
        (info, problem) = actions?.serverState() ?? (nil, nil)
        inputs = AudioInputs.all()
        let device = AudioInputs.chosen(config.microphone).input?.id ?? AudioInputs.defaultInput()
        volume = device.flatMap(AudioInputs.volume)
        labels = Self.labelStats(config.labeled)
    }

    var settings: [SettingInfo] { info?.settings ?? [] }
    func setting(_ key: String) -> SettingInfo? { settings.first { $0.key == key } }

    func sections(_ page: SettingsPage) -> [(section: String, ids: [String])] {
        let keys = settings.map { (key: $0.key, owner: $0.owner, group: $0.group) }
        return SettingsLayout.sections(of: page, serverKeys: keys)
    }

    func write(_ path: [String], _ value: Any) {
        actions?.write(path, value, "settings: \(path.joined(separator: ".")) = \(value)")
        reload()
    }

    func remove(_ path: [String]) {
        actions?.remove(path, "settings: \(path.joined(separator: ".")) back to its default")
        reload()
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
}

/// An adapter's name for people: "claude" → "Claude".
func adapterTitle(_ name: String) -> String { name.prefix(1).uppercased() + name.dropFirst() }

struct SettingsView: View {
    @ObservedObject var model: SettingsModel

    var body: some View {
        NavigationSplitView {
            List(selection: $model.selection) {
                ForEach(SettingsPage.allCases) { page in
                    if page == .adapters {
                        DisclosureGroup(isExpanded: $model.adaptersOpen) {
                            ForEach(model.info?.adapters ?? [], id: \.name) { a in
                                AdapterSidebarRow(model: model, adapter: a).tag(SidebarItem.adapter(a.name))
                            }
                        } label: {
                            Label(page.title, systemImage: page.symbol).tag(SidebarItem.page(page))
                        }
                    } else {
                        Label(page.title, systemImage: page.symbol).tag(SidebarItem.page(page))
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

/// An adapter in the sidebar: its name, and whether it is on.
struct AdapterSidebarRow: View {
    @ObservedObject var model: SettingsModel
    let adapter: ServerInfo.Adapter

    var body: some View {
        HStack {
            Text(adapterTitle(adapter.name))
            Spacer()
            if adapter.error != nil {
                Image(systemName: "exclamationmark.triangle").foregroundStyle(.orange).help("It does not work")
            } else if model.config.adapters[adapter.name] == true {
                Image(systemName: "checkmark.circle.fill").foregroundStyle(.green).help("On")
            }
        }
    }
}

struct PageView: View {
    @ObservedObject var model: SettingsModel
    let page: SettingsPage

    var body: some View {
        Form {
            if model.info == nil && [.recognition, .adapters, .recordings].contains(page) {
                Text("The dictation server is not answering. Its settings appear here when it answers.")
                    .foregroundStyle(.secondary)
            }
            ForEach(model.sections(page), id: \.section) { section in
                Section(section.section) {
                    ForEach(section.ids, id: \.self) { id in ItemView(model: model, id: id) }
                }
            }
        }
        .formStyle(.grouped)
        .navigationTitle(page.title)
    }
}

/// One item of a page: one of the app's own, or a server setting from its description.
struct ItemView: View {
    @ObservedObject var model: SettingsModel
    let id: String

    var body: some View {
        switch id {
        case "dictationKey": KeyPicker(model: model, path: "dictationKey", title: "Dictation",
                                       note: "Tap to start and stop. The text goes where the cursor was.")
        case "privateDictationKey": KeyPicker(model: model, path: "privateDictationKey", title: "Private dictation",
                                              note: "Reads nothing on the screen and saves nothing.")
        case "language": LanguagePicker(model: model)
        case "languageNotes": LanguageList(model: model, field: "notes", title: "Notes for the model",
                                           note: "Rules about this language for the model, one on each line.")
        case "languageFillers": LanguageList(model: model, field: "fillers", title: "Hesitation sounds",
                                             note: "Removed from the text. Separate them with commas.")
        case "silenceStopSeconds": AppNumberRow(model: model, path: ["silenceStopSeconds"], title: "Stop after silence",
                                                unit: "s", fallback: model.config.silenceStopSeconds,
                                                note: "Recording stops after this long without speech.")
        case "microphone": MicrophonePicker(model: model)
        case "inputVolume": VolumeRow(model: model)
        case "model": ModelPicker(model: model)
        case "prompt": PromptEditor(model: model)
        case "adapterList": AdapterList(model: model)
        case "adapterDefaults": AdapterDefaults(model: model)
        case "labelStats":
            LabeledContent("Labeled") {
                Text("\(model.labels.count) pieces, \(String(format: "%.1f", model.labels.seconds / 60)) min")
            }
        case "labelRecordings": Button("Label Recordings…") { model.actions?.openLabeling() }
        case "serverStatus": ServerStatus(model: model)
        case "openLog": Button("Open the Log") { model.actions?.openLog() }
        default:
            if let s = model.setting(id) { SettingRow(model: model, setting: s) }
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

/// A setting's description, or none when the title says it all.
func note(_ help: String) -> String? { help.isEmpty ? nil : help }

func show(_ v: SettingValue?) -> String {
    switch v {
    case let .number(n)?: return n == n.rounded() && abs(n) < 1e9 ? String(Int(n)) : String(n)
    case let .bool(b)?: return b ? "on" : "off"
    case let .string(s)?: return s
    default: return "none"
    }
}

/// A server setting: a switch, a number or a text, written where SettingStore says.
struct SettingRow: View {
    @ObservedObject var model: SettingsModel
    let setting: SettingInfo
    private var id: String { "setting." + setting.key }

    private var path: [String]? { SettingStore.path(of: setting, model: model.config.model) }
    private var value: SettingValue? { SettingStore.value(of: setting, in: model.config, model: model.config.model) }
    private var set: Bool { path.map { model.config.value($0) != nil } ?? false }
    private var shown: String { show(value) == "none" ? "" : show(value) }

    var body: some View {
        SettingLine(title: setting.title, note: refused ? allowedValues(setting) : note(setting.help), refused: refused,
                    pending: model.drafts[id].map { $0 != shown } ?? false) {
            control
            ResetButton(visible: set, help: "Restore the default (\(show(setting.default)))") {
                if let p = path { model.done(id); model.remove(p) }
            }
        }
    }

    private var refused: Bool { model.refused.contains(id) }

    @ViewBuilder private var control: some View {
        switch setting.kind {
        case "boolean":
            Toggle("", isOn: Binding(get: { if case .bool(true)? = value { return true } else { return false } },
                                     set: { on in if let p = path { model.write(p, on) } }))
                .labelsHidden().toggleStyle(.switch)
        case "string":
            InputField(text: model.draft(id, shown: shown), width: 240, refused: model.refused.contains(id),
                       onSubmit: commit)
            if setting.key == "recordings" {
                Button("Choose…") {
                    if let folder = chooseFolder(starting: shown), let p = path { model.done(id); model.write(p, folder) }
                }
            }
        default:
            InputField(placeholder: show(setting.default), text: model.draft(id, shown: shown), width: 80, number: true,
                       refused: model.refused.contains(id), onSubmit: commit)
            UnitLabel(unit: unit(of: setting.key))
        }
    }

    private func commit() {
        guard let p = path, let text = model.drafts[id] else { return }
        if setting.kind == "string" {
            model.done(id)
            model.write(p, text)
            return
        }
        if text.isEmpty {  // an empty field: back to the default
            model.done(id)
            if set { model.remove(p) }
            return
        }
        guard let n = Double(text.replacingOccurrences(of: ",", with: ".")), setting.allows(n) else {
            model.refused.insert(id)
            return
        }
        model.done(id)
        model.write(p, setting.kind == "integer" ? Int(n) as Any : n as Any)
    }
}

/// A number the app keeps at the top of the config (its own setting, not the server's).
struct AppNumberRow: View {
    @ObservedObject var model: SettingsModel
    let path: [String], title: String, unit: String, fallback: Double, note: String
    private var id: String { "app." + path.joined(separator: ".") }
    private var shown: String { show(.number(fallback)) }

    var body: some View {
        SettingLine(title: title, note: model.refused.contains(id) ? "Enter a number above 0." : note,
                    refused: model.refused.contains(id),
                    pending: model.drafts[id].map { $0 != shown } ?? false) {
            InputField(text: model.draft(id, shown: shown), width: 80, number: true,
                       refused: model.refused.contains(id)) {
                guard let text = model.drafts[id] else { return }
                if let n = Double(text.replacingOccurrences(of: ",", with: ".")), n > 0 {
                    model.done(id)
                    model.write(path, n)
                } else {
                    model.refused.insert(id)
                }
            }
            UnitLabel(unit: unit)
            ResetButton(visible: false, help: "") {}
        }
    }
}

struct KeyPicker: View {
    @ObservedObject var model: SettingsModel
    let path: String, title: String, note: String

    private var current: String {
        (model.config.value([path]) as? String) ?? (path == "dictationKey" ? TapKeyChoice.rightOption.rawValue
                                                                            : TapKeyChoice.rightCommand.rawValue)
    }

    var body: some View {
        SettingLine(title: title, note: clash ? "The other dictation uses this key too. Choose another one." : note,
                    refused: clash) {
            Picker(title, selection: Binding(get: { current }, set: { v in
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

    private var clash: Bool {
        let other = path == "dictationKey" ? "privateDictationKey" : "dictationKey"
        let otherValue = (model.config.value([other]) as? String)
            ?? (other == "dictationKey" ? TapKeyChoice.rightOption.rawValue : TapKeyChoice.rightCommand.rawValue)
        return current != "none" && current == otherValue
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

    var body: some View {
        Picker("Microphone", selection: Binding(get: { model.config.microphone }, set: {
            model.actions?.choose(microphone: $0)
            model.reload()
        })) {
            ForEach(model.inputs, id: \.uid) { input in
                Text(input.name + (input.builtIn ? " (built-in)" : "")).tag(input.builtIn ? Config.builtInMicrophone : input.uid)
            }
            Text("Follow macOS's input").tag(Config.systemMicrophone)
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

/// The model's prompt template: its own in the config, or its catalog entry's. The language's notes follow it.
struct PromptEditor: View {
    @ObservedObject var model: SettingsModel
    private let id = "prompt"

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
    private var id: String { "language.\(field)" }
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

/// The adapters, each with its switch; a click on its name in the sidebar opens its page.
struct AdapterList: View {
    @ObservedObject var model: SettingsModel

    var body: some View {
        if let adapters = model.info?.adapters, !adapters.isEmpty {
            ForEach(adapters, id: \.name) { a in
                SettingLine(title: adapterTitle(a.name), note: a.error ?? a.description, refused: a.error != nil) {
                    Button("Open") { model.selection = .adapter(a.name) }.buttonStyle(.borderless)
                    AdapterSwitch(model: model, adapter: a)
                }
            }
        } else {
            Text("No adapters. The server is not answering, or it has none.").foregroundStyle(.secondary)
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

/// The adapters' settings for every adapter (adapterDefaults): over each adapter's own defaults, under a value set on
/// an adapter's page.
struct AdapterDefaults: View {
    @ObservedObject var model: SettingsModel

    var body: some View {
        Text("These values apply to every adapter. A value set on an adapter's page wins.")
            .font(.caption).foregroundStyle(.secondary)
        ForEach(model.settings.filter { $0.owner == "adapter" }, id: \.key) { s in
            AdapterValueRow(model: model, setting: s, adapter: nil)
        }
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
            Section("Context") {
                ForEach(model.settings.filter { $0.owner == "adapter" }, id: \.key) { s in
                    AdapterValueRow(model: model, setting: s, adapter: adapter)
                }
            }
        }
        .formStyle(.grouped)
        .navigationTitle(adapterTitle(adapter.name))
    }
}

/// An adapter's setting, for one adapter (its entry) or for every adapter (adapterDefaults, `adapter` nil). Its note
/// says where the value in force comes from.
struct AdapterValueRow: View {
    @ObservedObject var model: SettingsModel
    let setting: SettingInfo
    let adapter: ServerInfo.Adapter?

    private var id: String { "adapter.\(adapter?.name ?? "*").\(setting.key)" }
    private var path: [String] { adapter.map { ["adapters", $0.name, setting.key] } ?? ["adapterDefaults", setting.key] }
    private func at(_ p: [String]) -> SettingValue? { SettingValue(json: model.config.value(p)).flatMap { $0 == .null ? nil : $0 } }
    private var own: SettingValue? { at(path) }
    private var shared: SettingValue? { adapter == nil ? nil : at(["adapterDefaults", setting.key]) }
    private var adapterDefault: SettingValue? { adapter?.context?[setting.key] }

    /// What is in force without a value here, and where it comes from.
    private var inherited: (value: SettingValue?, from: String) {
        if let v = shared { return (v, "Defaults for all adapters") }
        if let v = adapterDefault { return (v, "\(adapterTitle(adapter!.name)) defaults") }
        return (setting.default, "the built-in default")
    }
    private var shown: String { own.map { show($0) } ?? "" }
    /// Where the value in force comes from; the value itself is in the field (its placeholder) or the switch.
    private var source: String { own != nil ? "Set here." : "From \(inherited.from)." }
    private var refused: Bool { model.refused.contains(id) }

    var body: some View {
        SettingLine(title: setting.title,
                    note: refused ? allowedValues(setting) : [setting.help, source].filter { !$0.isEmpty }.joined(separator: " "),
                    refused: refused, pending: model.drafts[id].map { $0 != shown } ?? false) {
            if setting.kind == "boolean" {
                Toggle("", isOn: Binding(get: { if case .bool(true)? = own ?? inherited.value { return true } else { return false } },
                                         set: { model.write(path, $0) }))
                    .labelsHidden().toggleStyle(.switch)
            } else {
                InputField(placeholder: show(inherited.value), text: model.draft(id, shown: shown), width: 80,
                           number: true, refused: model.refused.contains(id)) { commit() }
                UnitLabel(unit: unit(of: setting.key))
            }
            ResetButton(visible: own != nil, help: "Restore \(inherited.from)") { model.done(id); model.remove(path) }
        }
        .disabled(adapter.map { model.config.adapters[$0.name] != true } ?? false)
    }

    private func commit() {
        guard let text = model.drafts[id] else { return }
        if text.isEmpty {
            model.done(id)
            if own != nil { model.remove(path) }
        } else if let n = Double(text.replacingOccurrences(of: ",", with: ".")), setting.allows(n) {
            model.done(id)
            model.write(path, setting.kind == "integer" ? Int(n) as Any : n as Any)
        } else {
            model.refused.insert(id)
        }
    }
}

struct ServerStatus: View {
    @ObservedObject var model: SettingsModel

    var body: some View {
        LabeledContent("Dictation server") { Text(model.config.serverURL.absoluteString).textSelection(.enabled) }
        LabeledContent("State") {
            if let p = model.problem { Text(p).foregroundStyle(.red) }
            else if model.info != nil { Text("Running") } else { Text("Not checked yet").foregroundStyle(.secondary) }
        }
        LabeledContent("Model") { Text(model.config.model ?? "none") }
        HStack {
            Spacer()
            Button("Ask Again") {
                model.actions?.refreshServer()
                DispatchQueue.main.asyncAfter(deadline: .now() + 1) { model.reload() }
            }
        }
    }
}
