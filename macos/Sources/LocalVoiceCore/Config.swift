// The config file the app shares with the dictation server, ~/.local-voice/config.json ($LOCAL_VOICE_CONFIG),
// version 3 (server/settings.py has its fields). The app reads the model registry, the chosen model, the language,
// the enabled adapters, the silence stop, where the server listens and keeps its recordings, and where the labeled
// recordings go; it writes what the menu chooses: the model, the language and the adapters.
import Foundation

public struct Config: Equatable {
    public static let version = 3
    public static let defaultHost = "127.0.0.1"
    public static let defaultPort = 8090  // the server's own default (server/constants.py WORKING_PORT)
    public static let defaultRecordings = "~/speech/recordings"  // the server's own default (constants.py RECORDINGS)
    public static let defaultLabeled = "~/speech/labeled"

    public static var url: URL {
        if let p = ProcessInfo.processInfo.environment["LOCAL_VOICE_CONFIG"], !p.isEmpty { return URL(fileURLWithPath: p) }
        return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local-voice/config.json")
    }

    public var models: [String] = []
    public var model: String?
    public var language = ""
    /// The adapters the file enables or disables, by name; one not named is off.
    public var adapters: [String: Bool] = [:]
    public var silenceStopSeconds = Tuning.silenceStopSeconds
    public var host = Config.defaultHost
    public var port = Config.defaultPort
    /// The server's recordings (server.recordings), and the folder of the recordings you labeled ("labeled").
    public var recordings = Config.path(Config.defaultRecordings)
    public var labeled = Config.path(Config.defaultLabeled)
    public var error: String?

    public var serverURL: URL { URL(string: "ws://\(host):\(port)")! }

    public init() {}

    /// A path of the config: "~" is the home folder.
    public static func path(_ p: String) -> URL {
        URL(fileURLWithPath: (p as NSString).expandingTildeInPath)
    }

    public static func load(from url: URL = Config.url,
                            systemLanguage: String? = Locale.preferredLanguages.first) -> Config {
        var c = Config()
        c.language = systemLanguage.map { String($0.prefix(while: { $0 != "-" })) } ?? ""
        guard let data = try? Data(contentsOf: url) else {
            c.error = "cannot read \(url.path)"
            return c
        }
        guard let d = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
            c.error = "\(url.path) is not a JSON object"
            return c
        }
        if let v = d["version"] as? Int, v != version { c.error = "\(url.path) is version \(v); the app reads \(version)" }
        c.models = ((d["models"] as? [String: Any]) ?? [:]).keys.sorted()
        c.model = d["model"] as? String
        if let l = d["language"] as? String { c.language = l }
        for (name, entry) in (d["adapters"] as? [String: Any]) ?? [:] {
            c.adapters[name] = ((entry as? [String: Any])?["enabled"] as? Bool) ?? false
        }
        if let s = d["silenceStopSeconds"] as? Double, s >= 0 { c.silenceStopSeconds = s }
        if let server = d["server"] as? [String: Any] {
            if let h = server["host"] as? String, !h.isEmpty { c.host = h }
            if let p = server["port"] as? Int, p > 0, p < 65536 { c.port = p }
            if let r = server["recordings"] as? String, !r.isEmpty { c.recordings = path(r) }
        }
        if let l = d["labeled"] as? String, !l.isEmpty { c.labeled = path(l) }
        return c
    }

    /// Writes `value` at `path` (keys of nested objects): the menu's model, language and adapters. Only that value
    /// changes in the text, so the file keeps its order and layout (JSONEdit); the edit is kept only if the file then
    /// parses to its old contents with the new value. Otherwise the file is written again from its parsed contents.
    public static func set(_ path: [String], to value: Any, in url: URL = Config.url) throws {
        let text = try String(contentsOf: url, encoding: .utf8)
        guard let parsed = try JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any] else {
            throw MessageError("\(url.path) is not a JSON object")
        }
        let expected = setting(path[...], to: value, in: parsed)
        if let edited = try? JSONEdit.set(path, to: value, in: text),
           let check = try? JSONSerialization.jsonObject(with: Data(edited.utf8)) as? [String: Any],
           NSDictionary(dictionary: check).isEqual(to: expected) {
            try edited.write(to: url, atomically: true, encoding: .utf8)
            return
        }
        let data = try JSONSerialization.data(withJSONObject: expected,
                                              options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
        try (data + Data("\n".utf8)).write(to: url, options: .atomic)
    }

    static func setting(_ path: ArraySlice<String>, to value: Any, in d: [String: Any]) -> [String: Any] {
        var d = d
        let key = path.first!
        d[key] = path.count == 1 ? value : setting(path.dropFirst(), to: value, in: d[key] as? [String: Any] ?? [:])
        return d
    }
}
