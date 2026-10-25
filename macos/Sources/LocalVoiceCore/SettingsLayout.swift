// Where each setting is shown: in the menu bar's menu, on a page of the settings window, or both (docs/design/5-ui.md,
// "Как устроены настройки"). What a setting is (its owner, kind, range, default, help) comes from the server's info
// for the server's, the models' and the adapters' settings (SettingInfo), and from the app for its own. Where it is
// shown is the app's alone, here: to move a setting between the menu and the window, change its line in `places`. A
// server setting without a line goes to its owner's page, in its group's section, so a new one always shows up; an
// adapter's settings show under each adapter.
import Foundation

public enum SettingsPage: String, CaseIterable, Identifiable {
    case general, microphone, language, model, recognition, adapters, recordings, diagnostics

    public var id: String { rawValue }

    public var title: String {
        switch self {
        case .general: return "General"
        case .microphone: return "Microphone"
        case .language: return "Language"
        case .model: return "Model"
        case .recognition: return "Recognition"
        case .adapters: return "Adapters"
        case .recordings: return "Recordings & Labels"
        case .diagnostics: return "Diagnostics"
        }
    }

    /// The SF Symbol of the page in the sidebar.
    public var symbol: String {
        switch self {
        case .general: return "gearshape"
        case .microphone: return "mic"
        case .language: return "character.bubble"
        case .model: return "cpu"
        case .recognition: return "waveform"
        case .adapters: return "puzzlepiece.extension"
        case .recordings: return "tray.full"
        case .diagnostics: return "stethoscope"
        }
    }
}

public enum SettingPlace: Equatable {
    /// In the menu bar's menu, at this position.
    case menu(Int)
    /// On a page of the settings window, in a section, at this position in it.
    case page(SettingsPage, section: String, order: Int)
}

public enum SettingsLayout {
    /// The app's own items, and the server's settings that are not where their owner and group put them.
    public static let places: [String: [SettingPlace]] = [
        // The app's items
        "permissions": [.menu(0)],
        "microphone": [.menu(1), .page(.microphone, section: "Input", order: 0)],
        "inputVolume": [.menu(2), .page(.microphone, section: "Input", order: 1)],
        "labelRecordings": [.menu(3), .page(.recordings, section: "Labels", order: 1)],
        "labelStats": [.page(.recordings, section: "Labels", order: 0)],
        "dictationKey": [.page(.general, section: "Shortcuts", order: 0)],
        "privateDictationKey": [.page(.general, section: "Shortcuts", order: 1)],
        "silenceStopSeconds": [.page(.general, section: "Recording", order: 0)],
        "language": [.page(.language, section: "Language", order: 0)],
        "languageNotes": [.page(.language, section: "Language", order: 1)],
        "languageFillers": [.page(.language, section: "Language", order: 2)],
        "model": [.page(.model, section: "Model", order: 0)],
        "prompt": [.page(.model, section: "Prompt", order: 0)],
        "adapterList": [.page(.adapters, section: "Adapters", order: 0)],
        "serverStatus": [.page(.diagnostics, section: "Server", order: 0)],
        "openLog": [.page(.diagnostics, section: "Logs", order: 0)],
        // The server's settings placed by hand
        "saveRecordings": [.page(.recordings, section: "Recordings", order: 0)],
        "recordings": [.page(.recordings, section: "Recordings", order: 1)],
        "labeled": [.page(.recordings, section: "Labels", order: 2)],
    ]

    /// Where a server setting goes when `places` has no line for it: "owner.group" → its page and section. An
    /// adapter's settings show under each adapter (the page Adapters), not here.
    public static let groups: [String: (SettingsPage, String)] = [
        "server.cutting": (.recognition, "Cutting into pieces"),
        "server.speech": (.recognition, "Speech"),
        "server.recording": (.recognition, "Recording"),
        "server.storage": (.recordings, "Recordings"),
        "model.sampling": (.model, "Sampling"),
        "model.output": (.model, "Length of the text"),
        "model.context": (.model, "Context"),
    ]

    /// The page of an owner's setting whose group has no line in `groups`.
    static let ownerPages: [String: SettingsPage] = ["server": .recognition, "model": .model]

    /// The places of a setting: its line in `places`, else its owner's page and its group's section, else that page,
    /// "Other". An adapter's setting has none here: it shows under each adapter.
    public static func places(of key: String, owner: String? = nil, group: String? = nil) -> [SettingPlace] {
        if let p = places[key] { return p }
        guard let owner, owner != "adapter" else { return [] }
        if let (page, section) = groups["\(owner).\(group ?? "")"] { return [.page(page, section: section, order: Int.max)] }
        return [.page(ownerPages[owner] ?? .recognition, section: "Other", order: Int.max)]
    }

    /// The ids in the menu, in order.
    public static var menu: [String] {
        places.compactMap { key, ps -> (Int, String)? in
            for p in ps { if case let .menu(n) = p { return (n, key) } }
            return nil
        }.sorted { $0 < $1 }.map(\.1)
    }

    /// A page's sections in the order of their first place, each with its ids in order. `serverKeys`: the server's
    /// settings with their owners and groups.
    public static func sections(of page: SettingsPage, serverKeys: [(key: String, owner: String, group: String)])
        -> [(section: String, ids: [String])] {
        var all: [(String, String, Int)] = []  // (section, id, order)
        let appKeys = places.keys.filter { key in !serverKeys.contains { $0.key == key } }
        for key in appKeys {
            for p in places(of: key) { if case let .page(pg, s, n) = p, pg == page { all.append((s, key, n)) } }
        }
        for (key, owner, group) in serverKeys {
            for p in places(of: key, owner: owner, group: group) {
                if case let .page(pg, s, n) = p, pg == page { all.append((s, key, n)) }
            }
        }
        var order: [String] = []
        for (s, _, _) in all.sorted(by: { ($0.2, $0.1) < ($1.2, $1.1) }) where !order.contains(s) { order.append(s) }
        return order.map { s in (s, all.filter { $0.0 == s }.sorted { ($0.2, $0.1) < ($1.2, $1.1) }.map(\.1)) }
    }
}

/// Where a setting's value is read and written in the config: at its owner. A server's setting in the section
/// "server", a model's in that model's "options", an adapter's in that adapter's entry.
public enum SettingStore {
    public static func path(of s: SettingInfo, model: String?, adapter: String? = nil) -> [String]? {
        switch s.owner {
        case "server": return ["server", s.key]
        case "model": return model.map { ["models", $0, "options", s.key] }
        case "adapter": return adapter.map { ["adapters", $0, s.key] }
        default: return nil
        }
    }

    /// The owner's default: an adapter's own (its info's context), else the setting's.
    public static func defaultValue(of s: SettingInfo, adapter: ServerInfo.Adapter? = nil) -> SettingValue? {
        adapter?.context?[s.key] ?? s.default
    }

    /// The value in force: the config's at the owner, else the owner's default.
    public static func value(of s: SettingInfo, in config: Config, model: String?,
                             adapter: ServerInfo.Adapter? = nil) -> SettingValue? {
        if let p = path(of: s, model: model, adapter: adapter?.name), let v = SettingValue(json: config.value(p)),
           v != .null {
            return v
        }
        return adapter == nil ? (s.value ?? s.default) : defaultValue(of: s, adapter: adapter)
    }
}
