// The messages between the app and the dictation server (server/gemma_voice.py has the protocol). The same examples
// are checked here (lv-tests) and in the server's tests.
import Foundation

/// The server's interface this app speaks (protocol.INTERFACE on the server).
public let protocolInterface = 2

/// What the server tells about itself ({"type": "info"}).
public struct ServerInfo: Decodable, Equatable {
    public struct Adapter: Decodable, Equatable {
        public let name: String
        public let enabled: Bool
        public let apps: [String]
        public let electronTree: Bool
        /// What of the screen the adapter needs from its apps: "lists", the rows of the focused window's lists.
        public let screen: [String]?
        /// The files it reads.
        public let reads: [String]?
        public let description: String?
        public let error: String?
        /// The defaults of its context settings, from its manifest.
        public let context: [String: SettingValue]?
    }
    /// A language the server's prompt names (server/dictation.py LANGUAGES).
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
        public let prompt: String?
        public let maxAudioSeconds: Double?
    }
    public let interface: Int
    public let sampleRate: Int
    public let encoding: String
    public let textWaitSeconds: Double
    public let maxRecordingSeconds: Double
    public let languages: [Language]
    public let adapters: [Adapter]
    /// The settings the server describes; an older server sends none.
    public let settings: [SettingInfo]?
    public let model: Model?

    /// Apps whose focus an enabled adapter reads.
    public var snapshotApps: Set<String> { Set(adapters.filter(\.enabled).flatMap(\.apps)) }
    /// Electron apps whose accessibility tree an enabled adapter needs.
    public var treeApps: Set<String> { Set(adapters.filter { $0.enabled && $0.electronTree }.flatMap(\.apps)) }
    /// Apps whose window lists an enabled adapter reads (a messenger's messages): the snapshot takes their rows.
    public var listApps: Set<String> {
        Set(adapters.filter { $0.enabled && ($0.screen ?? []).contains("lists") }.flatMap(\.apps))
    }

    public static func decode(_ data: Data) throws -> ServerInfo {
        let info = try JSONDecoder().decode(ServerInfo.self, from: data)
        guard info.interface == protocolInterface else {
            throw MessageError("the server speaks interface \(info.interface); this app speaks \(protocolInterface)")
        }
        return info
    }
}

public struct MessageError: Error, CustomStringConvertible {
    public let description: String
    public init(_ d: String) { description = d }
}

public enum ClientMessage {
    public static let info = #"{"type":"info"}"#

    /// The start of a recording. `isPrivate`: the server saves nothing of it, runs no adapter and logs no text.
    public static func start(model: String?, language: String, sampleRate: Int, client: String,
                             snapshot: [String: Any], hints: [String: Any] = [:], isPrivate: Bool = false) -> String {
        var m: [String: Any] = ["type": "start", "language": language, "sampleRate": sampleRate,
                                "encoding": "pcm_s16le", "client": client, "snapshot": snapshot, "hints": hints]
        if let model { m["model"] = model }
        if isPrivate { m["private"] = true }
        return json(m)
    }

    public enum StopReason: String { case user, silence, maxDuration = "max_duration", error }

    public static func stop(_ reason: StopReason) -> String { json(["type": "stop", "reason": reason.rawValue]) }

    static func json(_ m: [String: Any]) -> String {
        let data = (try? JSONSerialization.data(withJSONObject: m, options: [.sortedKeys])) ?? Data("{}".utf8)
        return String(decoding: data, as: UTF8.self)
    }
}

/// A message from the server during a recording.
public enum ServerMessage: Equatable {
    case speech, text(String), error(String), stopped(String), done, other

    public static func parse(_ s: String) -> ServerMessage? {
        guard let m = (try? JSONSerialization.jsonObject(with: Data(s.utf8))) as? [String: Any] else { return nil }
        switch m["type"] as? String {
        case "speech": return .speech
        case "text": return (m["text"] as? String).map { .text($0) } ?? .other
        case "error": return .error(m["message"] as? String ?? "error")
        case "stopped": return .stopped(m["reason"] as? String ?? "")
        case "done": return .done
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
    /// Its owner: server (the config's "server"), model (a model's "options"), adapter (an adapter's entry).
    public let owner: String
    /// What it is about: cutting, speech, recording, storage, sampling, output, context.
    public let group: String
    /// number, integer, boolean or string.
    public let kind: String
    /// The owner's default: the menu's model's for a model's setting; the fallback for an adapter's (each adapter's
    /// own default is in its info's context).
    public let `default`: SettingValue?
    /// The value in force at its owner, when it is not the default.
    public let value: SettingValue?
    public let min: Double?
    public let max: Double?
    public let minExclusive: Bool?
    public let maxExclusive: Bool?
    public let help: String

    /// Whether `v` is in the setting's range.
    public func allows(_ v: Double) -> Bool {
        if let lo = min, minExclusive == true ? v <= lo : v < lo { return false }
        if let hi = max, maxExclusive == true ? v >= hi : v > hi { return false }
        return kind != "integer" || v == v.rounded()
    }
}
