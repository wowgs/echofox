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
    @Published var page: SettingsPage? = .general
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

struct SettingsView: View {
    @ObservedObject var model: SettingsModel

    var body: some View {
        NavigationSplitView {
            List(SettingsPage.allCases, selection: $model.page) { page in
                Label(page.title, systemImage: page.symbol).tag(page)
            }
            .navigationSplitViewColumnWidth(min: 170, ideal: 190)
        } detail: {
            if let page = model.page {
                PageView(model: model, page: page)
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
                Text("The dictation server has not answered: its settings show up once it does.")
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
                                       note: "A tap starts the recording, the next tap ends it.")
        case "privateDictationKey": KeyPicker(model: model, path: "privateDictationKey", title: "Private dictation",
                                              note: "The same, without reading the screen: no context, nothing saved.")
        case "language": LanguagePicker(model: model)
        case "languageNotes": LanguageList(model: model, field: "notes", title: "Notes for the prompt",
                                           note: "One rule a line, added to the prompt for this language.")
        case "languageFillers": LanguageList(model: model, field: "fillers", title: "Hesitation sounds",
                                             note: "Taken out of the text; separated by commas. Empty: none.")
        case "silenceStopSeconds": AppNumberRow(model: model, path: ["silenceStopSeconds"], title: "Stop after silence",
                                                unit: "s", fallback: model.config.silenceStopSeconds,
                                                note: "The recording stops by itself after this long without speech.")
        case "microphone": MicrophonePicker(model: model)
        case "inputVolume": VolumeRow(model: model)
        case "model": ModelPicker(model: model)
        case "prompt": PromptEditor(model: model)
        case "adapterList": AdapterList(model: model)
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

/// A key's name as words: "pieceSeconds" → "Piece seconds".
func title(of key: String) -> String {
    var out = ""
    for c in key {
        if c.isUppercase { out += " " + c.lowercased() } else { out.append(c) }
    }
    return out.prefix(1).uppercased() + out.dropFirst()
}

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
        SettingLine(title: title(of: setting.key), note: setting.help + range, refused: model.refused.contains(id),
                    pending: model.drafts[id].map { $0 != shown } ?? false) {
            control
            ResetButton(visible: set, help: "Back to the default (\(show(setting.default)))") {
                if let p = path { model.done(id); model.remove(p) }
            }
        }
    }

    private var range: String {
        var parts: [String] = []
        if let lo = setting.min { parts.append((setting.minExclusive == true ? "over " : "from ") + show(.number(lo))) }
        if let hi = setting.max { parts.append((setting.maxExclusive == true ? "under " : "to ") + show(.number(hi))) }
        parts.append("default \(show(setting.default))")
        return " (" + parts.joined(separator: ", ") + ")"
    }

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
        SettingLine(title: title, note: note, refused: model.refused.contains(id),
                    pending: model.drafts[id].map { $0 != shown } ?? false) {
            InputField(text: model.draft(id, shown: shown), width: 80, number: true,
                       refused: model.refused.contains(id)) {
                guard let text = model.drafts[id] else { return }
                if let n = Double(text.replacingOccurrences(of: ",", with: ".")), n >= 0 {
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
        SettingLine(title: title, note: clash ? "The other dictation has the same key: only one of them works."
                                              : note + " A tap: the key pressed and released alone.",
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
        Picker("Language of the speech", selection: Binding(get: { model.config.language }, set: { model.write(["language"], $0) })) {
            Text("The speech's own").tag("")
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
            LabeledContent("Input volume") { Text("this microphone has none to set").foregroundStyle(.secondary) }
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
                Text(own == nil ? "The model's catalog template. {LANGUAGE} becomes the language; its notes follow."
                                : "The model's own template. {LANGUAGE} becomes the language; its notes follow.")
                    .font(.caption).foregroundStyle(.secondary)
                Spacer()
                if own != nil {
                    Button("Use the Catalog's Template") { if let p = path { model.done(id); model.remove(p) } }
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
            Text("The speech's own language has no notes or sounds of its own.").foregroundStyle(.secondary)
        } else {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(title)
                    Spacer()
                    ResetButton(visible: own != nil, help: "Back to the language's defaults") {
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
                    Text(note + (own == nil ? " Now: the language's defaults." : "")).font(.caption).foregroundStyle(.secondary)
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

struct AdapterList: View {
    @ObservedObject var model: SettingsModel

    var body: some View {
        if let adapters = model.info?.adapters, !adapters.isEmpty {
            ForEach(adapters, id: \.name) { a in
                VStack(alignment: .leading, spacing: 4) {
                    Toggle(a.name, isOn: Binding(get: { model.config.adapters[a.name] == true }, set: { on in
                        model.write(["adapters", a.name, "enabled"], on)
                        model.actions?.refreshServer()
                    }))
                    .toggleStyle(.switch)
                    if let d = a.description { Text(d).font(.caption).foregroundStyle(.secondary) }
                    if let e = a.error { Text(e).font(.caption).foregroundStyle(.red) }
                    if model.config.adapters[a.name] == true {
                        ForEach(model.settings.filter { $0.owner == "adapter" }, id: \.key) { s in
                            AdapterSettingRow(model: model, adapter: a, setting: s)
                        }
                    }
                }
            }
        } else {
            Text("No adapters: the server has not answered, or it has none.").foregroundStyle(.secondary)
        }
    }
}

/// A setting of one adapter: its entry in the config, else the adapter's own default (its manifest's context).
struct AdapterSettingRow: View {
    @ObservedObject var model: SettingsModel
    let adapter: ServerInfo.Adapter, setting: SettingInfo
    private var id: String { "adapter.\(adapter.name).\(setting.key)" }

    private var path: [String] { ["adapters", adapter.name, setting.key] }
    private var own: SettingValue? { SettingValue(json: model.config.value(path)).flatMap { $0 == .null ? nil : $0 } }
    private var fallback: SettingValue? { SettingStore.defaultValue(of: setting, adapter: adapter) }
    private var shown: String { own.map { show($0) } ?? "" }

    var body: some View {
        SettingLine(title: title(of: setting.key), note: setting.help + " (\(adapter.name)'s default: \(show(fallback)))",
                    refused: model.refused.contains(id), pending: model.drafts[id].map { $0 != shown } ?? false) {
            if setting.kind == "boolean" {
                Toggle("", isOn: Binding(get: { if case .bool(true)? = own ?? fallback { return true } else { return false } },
                                         set: { model.write(path, $0) }))
                    .labelsHidden().toggleStyle(.switch)
            } else {
                InputField(placeholder: show(fallback), text: model.draft(id, shown: shown), width: 80, number: true,
                           refused: model.refused.contains(id)) {
                    guard let text = model.drafts[id] else { return }
                    if text.isEmpty {
                        model.done(id)
                        if own != nil { model.remove(path) }
                    } else if let n = Double(text), setting.allows(n) {
                        model.done(id)
                        model.write(path, setting.kind == "integer" ? Int(n) as Any : n as Any)
                    } else {
                        model.refused.insert(id)
                    }
                }
                UnitLabel(unit: unit(of: setting.key))
            }
            ResetButton(visible: own != nil, help: "Back to \(adapter.name)'s default") { model.done(id); model.remove(path) }
        }
        .padding(.leading, 16)
    }
}

struct ServerStatus: View {
    @ObservedObject var model: SettingsModel

    var body: some View {
        LabeledContent("Dictation server") { Text(model.config.serverURL.absoluteString).textSelection(.enabled) }
        LabeledContent("State") {
            if let p = model.problem { Text(p).foregroundStyle(.red) }
            else if model.info != nil { Text("answers") } else { Text("not asked yet").foregroundStyle(.secondary) }
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
