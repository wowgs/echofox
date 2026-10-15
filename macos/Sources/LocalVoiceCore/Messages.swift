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
        public let error: String?
    }
    public let interface: Int
    public let sampleRate: Int
    public let encoding: String
    public let textWaitSeconds: Double
    public let maxRecordingSeconds: Double
    public let adapters: [Adapter]

    /// Apps whose focus an enabled adapter reads.
    public var snapshotApps: Set<String> { Set(adapters.filter(\.enabled).flatMap(\.apps)) }
    /// Electron apps whose accessibility tree an enabled adapter needs.
    public var treeApps: Set<String> { Set(adapters.filter { $0.enabled && $0.electronTree }.flatMap(\.apps)) }

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

    /// The start of a recording.
    public static func start(model: String?, language: String, sampleRate: Int, client: String,
                             snapshot: [String: Any], hints: [String: Any] = [:]) -> String {
        var m: [String: Any] = ["type": "start", "language": language, "sampleRate": sampleRate,
                                "encoding": "pcm_s16le", "client": client, "snapshot": snapshot, "hints": hints]
        if let model { m["model"] = model }
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
