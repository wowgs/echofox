// Where each setting is shown: in the menu bar's menu, on a page of the settings window, or both (docs/design/5-ui.md,
// "Как устроены настройки"). What a setting is (its kind, range, default, help) comes from its owner: the server's
// info for the server's settings (SettingInfo), the app for its own. Where it is shown is the app's alone, here: to
// move a setting between the menu and the window, change its line in `places`. A server setting without a line goes
// to the page and section of its group, so a new one always shows up.
import Foundation

public enum SettingsPage: String, CaseIterable, Identifiable {
    case general, microphone, model, recognition, adapters, recordings, diagnostics

    public var id: String { rawValue }

    public var title: String {
        switch self {
        case .general: return "General"
        case .microphone: return "Microphone"
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
    /// The app's own items and the server's settings that are not where their group puts them.
    public static let places: [String: [SettingPlace]] = [
        // The app's items
        "permissions": [.menu(0)],
        "microphone": [.menu(1), .page(.microphone, section: "Input", order: 0)],
        "inputVolume": [.menu(2), .page(.microphone, section: "Input", order: 1)],
        "labelRecordings": [.menu(3), .page(.recordings, section: "Labels", order: 1)],
        "labelStats": [.page(.recordings, section: "Labels", order: 0)],
        "dictationKey": [.page(.general, section: "Shortcuts", order: 0)],
        "privateDictationKey": [.page(.general, section: "Shortcuts", order: 1)],
        "language": [.page(.general, section: "Speech", order: 0)],
        "silenceStopSeconds": [.page(.general, section: "Speech", order: 1)],
        "model": [.page(.model, section: "Model", order: 0)],
        "prompt": [.page(.recognition, section: "Prompt", order: 0)],
        "adapterList": [.page(.adapters, section: "Adapters", order: 0)],
        "serverStatus": [.page(.diagnostics, section: "Server", order: 0)],
        "openLog": [.page(.diagnostics, section: "Logs", order: 0)],
        // The server's settings placed by hand
        "saveRecordings": [.page(.recordings, section: "Recordings", order: 0)],
        "recordings": [.page(.recordings, section: "Recordings", order: 1)],
    ]

    /// Where a server setting of a group goes when `places` has no line for it.
    public static let groups: [String: (SettingsPage, String)] = [
        "cutting": (.recognition, "Cutting into pieces"),
        "speech": (.recognition, "Speech"),
        "sampling": (.recognition, "Sampling"),
        "output": (.recognition, "Length of the text"),
        "context": (.recognition, "Context"),
        "recording": (.recognition, "Recording"),
    ]

    /// The places of a setting: its line in `places`, else its group's page, else the page Recognition, "Other".
    public static func places(of key: String, group: String? = nil) -> [SettingPlace] {
        if let p = places[key] { return p }
        let (page, section) = group.flatMap { groups[$0] } ?? (.recognition, "Other")
        return [.page(page, section: section, order: Int.max)]
    }

    /// The ids in the menu, in order.
    public static var menu: [String] {
        places.compactMap { key, ps -> (Int, String)? in
            for p in ps { if case let .menu(n) = p { return (n, key) } }
            return nil
        }.sorted { $0 < $1 }.map(\.1)
    }

    /// A page's sections in the order of their first place, each with its ids in order. `serverKeys`: the server's
    /// settings with their groups.
    public static func sections(of page: SettingsPage, serverKeys: [(key: String, group: String)])
        -> [(section: String, ids: [String])] {
        var all: [(String, String, Int)] = []  // (section, id, order)
        let appKeys = places.keys.filter { key in !serverKeys.contains { $0.key == key } }
        for key in appKeys {
            for p in places(of: key) { if case let .page(pg, s, n) = p, pg == page { all.append((s, key, n)) } }
        }
        for (key, group) in serverKeys {
            for p in places(of: key, group: group) { if case let .page(pg, s, n) = p, pg == page { all.append((s, key, n)) } }
        }
        var order: [String] = []
        for (s, _, _) in all.sorted(by: { ($0.2, $0.1) < ($1.2, $1.1) }) where !order.contains(s) { order.append(s) }
        return order.map { s in (s, all.filter { $0.0 == s }.sorted { ($0.2, $0.1) < ($1.2, $1.1) }.map(\.1)) }
    }
}

/// Where a server setting's value is read and written in the config. A model's options win over the server's
/// section (server/tuning.py, value), so the value shown is the model's when it has one, and a change goes where the
/// value is; a new value goes to the server's section when the setting may be there, else to the model's options.
public enum SettingStore {
    public static func path(of s: SettingInfo, in config: Config, model: String?) -> [String]? {
        let modelPath = model.map { ["models", $0, "options", s.key] }
        if let p = modelPath, config.value(p) != nil { return p }
        if s.where.contains("server") { return ["server", s.key] }
        if s.where.contains("model"), let p = modelPath { return p }
        if s.where.contains("config") { return [s.key] }
        return nil
    }

    /// The value in force: the config's (where path(of:) points), else the server's, else the default.
    public static func value(of s: SettingInfo, in config: Config, model: String?) -> SettingValue? {
        if let p = path(of: s, in: config, model: model), let v = SettingValue(json: config.value(p)), v != .null {
            return v
        }
        return s.value ?? s.default
    }
}
