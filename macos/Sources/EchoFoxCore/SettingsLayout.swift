// Where each setting is shown: in the menu bar's menu, on a page of the settings window, or both (docs/design.md,
// "Как устроены настройки"). What a setting is (its owner, kind, range, default, help) comes from the server's info
// for the server's, the models' and the adapters' settings (SettingInfo), and from the app for its own. Where it is
// shown is the app's alone, here: to move a setting between the menu and the window, change its line in `places`. A
// server setting without a line goes to its owner's page, in its group's section, so a new one always shows up; an
// advanced one goes to that page's Advanced, a section that opens on a click; an adapter's settings show on its own
// page, in its Advanced. The sidebar's Adapters is a heading with a row per adapter, not a page.
import Foundation

public enum SettingsPage: String, CaseIterable, Identifiable {
    case general, microphone, language, model, recordings, diagnostics

    public var id: String { rawValue }

    public var title: String {
        switch self {
        case .general: return "General"
        case .microphone: return "Microphone"
        case .language: return "Language"
        case .model: return "Model"
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
        case .recordings: return "tray.full"
        case .diagnostics: return "stethoscope"
        }
    }
}

public enum SidebarEntry: Hashable {
    case page(SettingsPage)
    /// The heading "Adapters": no page of its own.
    case adapters

    public static let adaptersTitle = "Adapters"
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
        "commonNotes": [.page(.language, section: "Language", order: 1)],
        "languageNotes": [.page(.language, section: "Language", order: 2)],
        "languageFillers": [.page(.language, section: "Language", order: 3)],
        "model": [.page(.model, section: "Model", order: 0)],
        "variant": [.page(.model, section: "Quantization", order: 1)],  // a page's sections go by their first order
        "modelsFolder": [.page(.model, section: "Model", order: 2)],
        "prompt": [.page(.model, section: "Prompt", order: 3)],
        "serverStatus": [.page(.diagnostics, section: "Server", order: 0)],
        "openLog": [.page(.diagnostics, section: "Logs", order: 0)],
        // The server's settings placed by hand
        "saveRecordings": [.page(.recordings, section: "Recordings", order: 0)],
        "recordings": [.page(.recordings, section: "Recordings", order: 1)],
        "labeled": [.page(.recordings, section: "Labels", order: 2)],
    ]

    /// The sidebar, top to bottom: the pages, then the adapters' section, whose heading opens and closes its rows (as
    /// Finder's sidebar groups do).
    public static let sidebar: [SidebarEntry] = [.page(.general), .page(.microphone), .page(.language), .page(.model),
                                                 .page(.recordings), .page(.diagnostics), .adapters]

    /// The app's own settings that a SettingRow shows, described as the server describes its own.
    public static let appSettings = [
        SettingInfo(key: "silenceStopSeconds", owner: "app", kind: "number", title: "Stop after silence",
                    default: .number(Tuning.silenceStopSeconds), min: 0, minExclusive: true, unit: "s",
                    help: "Recording stops after this long without speech."),
    ]

    /// The section of a page that opens on a click: the settings for those who tune the model and the context.
    public static let advanced = "Advanced"

    /// The header a section shows on its page: none when it is the page's own title, which the window shows already.
    public static func header(_ section: String, on page: SettingsPage) -> String? {
        section == page.title ? nil : section
    }

    /// Where a server setting goes when `places` has no line for it: "owner.group" → its page and section. An
    /// adapter's settings show under each adapter (the page Adapters), not here.
    public static let groups: [String: (SettingsPage, String)] = [
        "server.recording": (.general, "Recording"),
        "server.storage": (.recordings, "Recordings"),
    ]

    /// The page of an owner's setting whose group has no line in `groups`.
    static let ownerPages: [String: SettingsPage] = ["server": .general, "model": .model]

    /// The places of a setting: its line in `places`, else its owner's page: in Advanced if it is an advanced one,
    /// else in its group's section, else in "Other". An adapter's setting has none here: it shows under each adapter.
    public static func places(of key: String, owner: String? = nil, group: String? = nil,
                              advanced: Bool = false) -> [SettingPlace] {
        if let p = places[key] { return p }
        guard let owner, owner != "adapter" else { return [] }
        let grouped = groups["\(owner).\(group ?? "")"]
        let page = grouped?.0 ?? ownerPages[owner] ?? .general
        return [.page(page, section: advanced ? Self.advanced : grouped?.1 ?? "Other", order: Int.max)]
    }

    /// The ids in the menu, in order.
    public static var menu: [String] {
        places.compactMap { key, ps -> (Int, String)? in
            for p in ps { if case let .menu(n) = p { return (n, key) } }
            return nil
        }.sorted { $0 < $1 }.map(\.1)
    }

    /// A page's sections in the order of their first place, Advanced last, each with its ids in order. `serverKeys`:
    /// the server's settings with their owners, groups and whether they are advanced.
    public static func sections(of page: SettingsPage,
                                serverKeys: [(key: String, owner: String, group: String, advanced: Bool)])
        -> [(section: String, ids: [String])] {
        var all: [(String, String, Int)] = []  // (section, id, order)
        let appKeys = places.keys.filter { key in !serverKeys.contains { $0.key == key } }
        for key in appKeys {
            for p in places(of: key) { if case let .page(pg, s, n) = p, pg == page { all.append((s, key, n)) } }
        }
        for (key, owner, group, advanced) in serverKeys {
            for p in places(of: key, owner: owner, group: group, advanced: advanced) {
                if case let .page(pg, s, n) = p, pg == page { all.append((s, key, n)) }
            }
        }
        var order: [String] = []
        for (s, _, _) in all.sorted(by: { ($0.2, $0.1) < ($1.2, $1.1) }) where !order.contains(s) { order.append(s) }
        if let i = order.firstIndex(of: advanced) { order.append(order.remove(at: i)) }
        return order.map { s in (s, all.filter { $0.0 == s }.sorted { ($0.2, $0.1) < ($1.2, $1.1) }.map(\.1)) }
    }
}
