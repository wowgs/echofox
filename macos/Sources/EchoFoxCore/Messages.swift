// The messages between the app and the dictation server (docs/reference/6-protocol.md; on the server, protocol.py and
// the modules it hands each message to). The same examples are checked here (echofox-tests) and in the server's tests.
import Foundation

/// The server's interface this app speaks (constants.PROTOCOL_INTERFACE on the server).
public let protocolInterface = 3
/// The audio this app sends; a server that takes another one is refused.
public let audioEncoding = "pcm_s16le"

/// What the server tells about itself ({"type": "info"}).
public struct ServerInfo: Decodable, Equatable {
    /// An adapter: a product the speaker writes into (Claude Code, Telegram), with its surfaces, the places of the
    /// product on the screen (shared/adapter.schema.json has its manifest).
    public struct Adapter: Decodable, Equatable {
        public let name: String
        /// Its name for people, from its manifest; a manifest without one sends none.
        public let title: String?
        public let enabled: Bool
        /// Its surfaces as its manifest gives them; an adapter whose manifest did not load has none.
        public let surfaces: [Surface]
        public let description: String?
        public let error: String?
        /// The defaults of its context settings, from its manifest.
        public let context: [String: SettingValue]?

        /// The apps of its surfaces, each once, in their order: its icon and its rows.
        public var apps: [String] {
            var seen = Set<String>()
            return surfaces.flatMap(\.apps).filter { seen.insert($0).inserted }
        }

        public init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            name = try c.decode(String.self, forKey: .name)
            title = try c.decodeIfPresent(String.self, forKey: .title)
            enabled = try c.decode(Bool.self, forKey: .enabled)
            surfaces = try c.decodeIfPresent([Surface].self, forKey: .surfaces) ?? []
            description = try c.decodeIfPresent(String.self, forKey: .description)
            error = try c.decodeIfPresent(String.self, forKey: .error)
            context = try c.decodeIfPresent([String: SettingValue].self, forKey: .context)
        }

        private enum CodingKeys: String, CodingKey { case name, title, enabled, surfaces, description, error, context }
    }
    /// A place of a product on the screen: its apps, the rules on the identity that tell it there, and what is read
    /// there once the server has matched it.
    public struct Surface: Decodable, Equatable {
        /// Unique within the adapter; the server names the surface <adapter>/<id>.
        public let id: String
        public let title: String
        public let apps: [String]
        /// Its apps build their accessibility tree only on request (Electron, Chromium); none sent is false.
        public let treeOnRequest: Bool?
        public let match: Match?
        public let screen: Screen?
        public let reads: [Read]?

        /// Patterns of the web area's address and of the window's title: * is any text, every other character itself.
        public struct Match: Decodable, Equatable {
            public let url: String?
            public let title: String?

            /// A pattern as the settings window shows it: "…" for any text.
            public static func shown(_ pattern: String) -> String { pattern.replacingOccurrences(of: "*", with: "…") }
        }
        /// What of the screen is read: the outline with its skip list and the key of its budget's knob, the rows of
        /// the window's lists, the app's child processes.
        public struct Screen: Decodable, Equatable {
            public struct Outline: Decodable, Equatable {
                public let skip: [String]?
                public let budget: String?
            }
            public struct Lists: Decodable, Equatable { public let budget: String? }
            public struct Processes: Decodable, Equatable {}
            public let outline: Outline?
            public let lists: Lists?
            public let processes: Processes?

            /// What is read, in words for the settings window, in the schema's order.
            public var kinds: [String] {
                [outline.map { _ in "Page text" }, lists.map { _ in "Message lists" },
                 processes.map { _ in "Running programs" }].compactMap { $0 }
            }
        }
        /// A file the adapter reads here: its place, when it is a fixed one, and what it is.
        public struct Read: Decodable, Equatable, Hashable {
            public let path: String?
            public let what: String
        }
    }
    /// A language the server's prompt names (server/languages.json, and the model's catalog entry names its languages).
    public struct Language: Decodable, Equatable {
        public let code: String
        public let name: String
        /// The language's defaults (server/languages.json): lines added to the prompt, hesitation sounds.
        public let notes: [String]?
        public let fillers: [String]?
    }
    /// The menu's model: its catalog entry and the catalog's prompt template.
    public struct Model: Decodable, Equatable {
        public let name: String?
        public let catalog: String?
        /// The model's name for people, from the catalog ("Gemma 4 E4B"); an older server sends none.
        public let title: String?
        public let prompt: String?
        /// The variant in force (a quantization: "q8_0"), and the catalog's variants of the model.
        public let variant: String?
        public let variants: [Variant]?
    }
    public struct Variant: Decodable, Equatable {
        public let id: String
        public let name: String
        /// The size of its files, and its memory while it is loaded.
        public let bytes: Double
        public let memoryBytes: Double?
        /// Whether it is the catalog's default; an older server sends none.
        public let `default`: Bool?
        /// Whether all its files are in the models folder, and whether the server downloads them now.
        public let downloaded: Bool
        public let downloading: Bool?

        /// Whether a window may offer to download it: not while the server downloads it for another window (a second
        /// request would only follow the same download, and a cancel there would stop both).
        public var canDownload: Bool { !downloaded && downloading != true }

        /// The variant to offer for a Mac with this much memory: the catalog's default if it takes at most half of it,
        /// so that macOS and the other apps keep the rest; else the biggest that does; else the smallest.
        public static func recommended(_ variants: [Variant], memory: UInt64) -> String {
            let size = { (v: Variant) in v.memoryBytes ?? v.bytes }
            let fits = variants.filter { size($0) <= Double(memory) / 2 }
            return (fits.first { $0.default == true } ?? fits.max { size($0) < size($1) }
                    ?? variants.min { size($0) < size($1) })?.id ?? ""
        }
    }
    public let interface: Int
    public let sampleRate: Int
    public let encoding: String
    public let textWaitSeconds: Double
    public let languages: [Language]
    /// The notes of every language (server/languages.json, "*"), {LANGUAGE} not filled in; an older server sends none.
    public let commonNotes: [String]?
    public let adapters: [Adapter]
    /// The settings the server describes; an older server sends none.
    public let settings: [SettingInfo]?
    public let model: Model?
    /// The names of the server's model registry.
    public let models: [String]?

    /// The apps whose identity the app reads at the hotkey: those of the enabled adapters' surfaces.
    public var identityApps: Set<String> {
        Set(adapters.filter(\.enabled).flatMap(\.surfaces).flatMap(\.apps))
    }
    /// The apps that the app asks for their accessibility tree: those of the enabled adapters' surfaces that build it
    /// only on request.
    public var treeApps: Set<String> {
        Set(adapters.filter(\.enabled).flatMap(\.surfaces).filter { $0.treeOnRequest == true }.flatMap(\.apps))
    }

    /// What the app reads of the app `bundleId` at the hotkey. What it reads afterwards is the server's read request.
    public func identityPlan(for bundleId: String) -> IdentityPlan {
        IdentityPlan(identity: identityApps.contains(bundleId), tree: treeApps.contains(bundleId))
    }

    /// A folder setting's value as the server has it (its config's, else its default), nil from an older server.
    public func folder(_ key: String) -> URL? {
        guard case .string(let p)? = settings?.first(where: { $0.key == key })?.value, !p.isEmpty else { return nil }
        return Config.path(p)
    }

    /// An adapter's name for people, the one rule of every window: its manifest's title among `adapters` (the
    /// server's), else its name with a capital first letter ("telegram" → "Telegram", "my-notes" → "My-notes").
    public static func adapterTitle(_ name: String, in adapters: [Adapter]) -> String {
        adapters.first { $0.name == name }?.title ?? name.prefix(1).uppercased() + name.dropFirst()
    }

    /// The language the first start proposes: `current` (the config's, macOS's own until one is chosen) if the model
    /// knows it, else English.
    public func proposedLanguage(_ current: String) -> String {
        languages.contains { $0.code == current } ? current : "en"
    }

    public static func decode(_ data: Data) throws -> ServerInfo {
        let info = try JSONDecoder().decode(ServerInfo.self, from: data)
        guard info.interface == protocolInterface else {
            throw MessageError("the server speaks interface \(info.interface); this app speaks \(protocolInterface)")
        }
        guard info.encoding == audioEncoding else {
            throw MessageError("the server takes \(info.encoding) audio; this app sends \(audioEncoding)")
        }
        return info
    }
}

public enum ClientMessage {
    public static let info = #"{"type":"info"}"#
    public static let cancel = #"{"type":"cancel"}"#

    /// The download, or the removal, of a variant of a catalog's model.
    public static func download(catalog: String, variant: String) -> String {
        json(["type": "download", "catalog": catalog, "variant": variant])
    }

    public static func remove(catalog: String, variant: String) -> String {
        json(["type": "remove", "catalog": catalog, "variant": variant])
    }

    /// The start of a recording, with the identity of the focused app (FocusSnapshot.capture), nil for none.
    /// `isPrivate`: the server saves nothing of it, runs no adapter and logs no text; it gets no identity.
    public static func start(model: String?, language: String, sampleRate: Int, client: String,
                             identity: [String: Any]?, isPrivate: Bool = false) -> String {
        var m: [String: Any] = ["type": "start", "language": language, "sampleRate": sampleRate,
                                "encoding": audioEncoding, "client": client]
        if let model { m["model"] = model }
        if isPrivate { m["private"] = true } else if let identity { m["identity"] = identity }
        return json(m)
    }

    /// The answer to the server's read request: what was read of each surface, by its name, and how long it took.
    public static func content(surfaces: [String: [String: Any]], tookMs: Int) -> String {
        json(["type": "content", "surfaces": surfaces, "tookMs": tookMs])
    }

    /// Why the app stops a recording; the server stops it itself at its time limit ("max_duration").
    public enum StopReason: String { case user, silence, error }

    public static func stop(_ reason: StopReason) -> String { json(["type": "stop", "reason": reason.rawValue]) }

    static func json(_ m: [String: Any]) -> String {
        let data = (try? JSONSerialization.data(withJSONObject: m, options: [.sortedKeys])) ?? Data("{}".utf8)
        return String(decoding: data, as: UTF8.self)
    }
}

/// A message from the server during a recording.
public enum ServerMessage: Equatable {
    case speech, text(String), error(String), stopped(String), done, other
    /// What to read of the screen for the surfaces that the server matched with the start's identity.
    case read(ReadRequest)
    /// A model's download (docs/reference/6-protocol.md): its bytes so far of its total; its end; a removal's bytes.
    case progress(bytes: Double, total: Double), downloaded, removed(Double)

    public static func parse(_ s: String) -> ServerMessage? {
        guard let m = (try? JSONSerialization.jsonObject(with: Data(s.utf8))) as? [String: Any] else { return nil }
        switch m["type"] as? String {
        case "speech": return .speech
        case "text": return (m["text"] as? String).map { .text($0) } ?? .other
        case "error": return .error(m["message"] as? String ?? "error")
        case "stopped": return .stopped(m["reason"] as? String ?? "")
        case "done": return .done
        case "read": return (try? JSONDecoder().decode(ReadRequest.self, from: Data(s.utf8))).map { .read($0) } ?? .other
        case "progress": return .progress(bytes: (m["bytes"] as? NSNumber)?.doubleValue ?? 0,
                                          total: (m["total"] as? NSNumber)?.doubleValue ?? 0)
        case "downloaded": return .downloaded
        case "removed": return .removed((m["bytes"] as? NSNumber)?.doubleValue ?? 0)
        default: return .other
        }
    }
}

/// A JSON value of a setting: its default or its value.
public enum SettingValue: Decodable, Equatable {
    case number(Double), bool(Bool), string(String), null

    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let n = try? c.decode(Double.self) { self = .number(n) }
        else { self = .string(try c.decode(String.self)) }
    }

    /// The value as the config file holds it (NSNumber for numbers and booleans), nil for null.
    public var json: Any? {
        switch self {
        case let .number(n): return n
        case let .bool(b): return b
        case let .string(s): return s
        case .null: return nil
        }
    }

    public init?(json: Any?) {
        switch json {
        case nil: self = .null
        case let n as NSNumber where CFGetTypeID(n) == CFBooleanGetTypeID(): self = .bool(n.boolValue)
        case let n as NSNumber: self = .number(n.doubleValue)
        case let s as String: self = .string(s)
        default: return nil
        }
    }
}

/// A setting the server describes in its info (server/settings.py, schema): what the settings window shows and where
/// it may write it.
public struct SettingInfo: Decodable, Equatable {
    public let key: String
    /// Its owner: server (the config's "server"), model (a model's "options"), adapter (an adapter's entry), app (the
    /// top of the config: the app's own).
    public let owner: String
    /// What it is about: cutting, speech, recording, storage, sampling, output, context.
    public let group: String
    /// number, integer, boolean, string, or folder (a string that is a folder's path: the window offers a folder panel).
    public let kind: String
    /// Its name in the settings window, for the user.
    public let title: String
    /// For those who tune the model and the context: shown in its page's Advanced.
    public let advanced: Bool?
    /// The owner's default: the menu's model's for a model's setting; the fallback for an adapter's (each adapter's
    /// own default is in its info's context).
    public let `default`: SettingValue?
    /// The value in force at its owner, when it is not the default.
    public let value: SettingValue?
    public let min: Double?
    public let max: Double?
    public let minExclusive: Bool?
    public let maxExclusive: Bool?
    /// What it does, in plain words for the user; "" when the title says it all.
    public let help: String
    /// What its number counts, shown beside the field: "s", "min", "tokens"; nil for none.
    public let unit: String?

    /// A setting the app describes itself, as the server describes its own (owner "app": the top of the config).
    public init(key: String, owner: String, group: String = "", kind: String, title: String, advanced: Bool? = nil,
                default d: SettingValue?, value: SettingValue? = nil, min: Double? = nil, max: Double? = nil,
                minExclusive: Bool? = nil, maxExclusive: Bool? = nil, unit: String? = nil, help: String = "") {
        self.key = key; self.owner = owner; self.group = group; self.kind = kind; self.title = title
        self.advanced = advanced; self.default = d; self.value = value; self.min = min; self.max = max
        self.minExclusive = minExclusive; self.maxExclusive = maxExclusive; self.unit = unit; self.help = help
    }

    /// Whether `v` is in the setting's range.
    public func allows(_ v: Double) -> Bool {
        if let lo = min, minExclusive == true ? v <= lo : v < lo { return false }
        if let hi = max, maxExclusive == true ? v >= hi : v > hi { return false }
        return kind != "integer" || v == v.rounded()
    }
}

/// What the app reads of an app at the hotkey (ServerInfo.identityPlan): `identity`, the app, its window's title and
/// the web area's address and title, for an app of an enabled adapter's surfaces; `tree`, its accessibility tree
/// asked for first, for an app that builds it only on request. Another app gets neither: the app reads only its
/// focused element, for the insertion.
public struct IdentityPlan: Equatable {
    public let identity, tree: Bool
    public static let none = IdentityPlan(identity: false, tree: false)
    public init(identity: Bool, tree: Bool) { (self.identity, self.tree) = (identity, tree) }
}

/// The server's read request ({"type": "read"}): for each surface it matched, what to read. The server resolves the
/// budgets: a budget is a number of estimated tokens, counted with `tokenWeights`, or nil for only the structural
/// limits.
public struct ReadRequest: Decodable, Equatable {
    public struct Surface: Decodable, Equatable {
        /// Its name, <adapter>/<id>: the key of its content.
        public let surface: String
        public let outline: Outline?
        public let lists: Lists?
        public let processes: Processes?

        /// The outline, without the children of the elements whose AX role or one of whose DOM classes is in `skip`.
        public struct Outline: Decodable, Equatable {
            public let skip: [String]?
            public let budget: Int?
            public init(skip: [String]? = nil, budget: Int? = nil) { (self.skip, self.budget) = (skip, budget) }
        }
        public struct Lists: Decodable, Equatable {
            public let budget: Int?
            public init(budget: Int? = nil) { self.budget = budget }
        }
        public struct Processes: Decodable, Equatable { public init() {} }

        public init(surface: String, outline: Outline? = nil, lists: Lists? = nil, processes: Processes? = nil) {
            (self.surface, self.outline, self.lists, self.processes) = (surface, outline, lists, processes)
        }
    }
    public let surfaces: [Surface]
    /// The model's tokens per character of each kind (FocusSnapshot's TokenEstimate); none: the fallback.
    public let tokenWeights: [String: Double]?

    public init(surfaces: [Surface], tokenWeights: [String: Double]? = nil) {
        (self.surfaces, self.tokenWeights) = (surfaces, tokenWeights)
    }
}
