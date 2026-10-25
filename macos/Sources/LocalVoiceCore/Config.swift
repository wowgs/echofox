// The config file the app shares with the dictation server, ~/.local-voice/config.json ($LOCAL_VOICE_CONFIG),
// version 6 (server/settings.py has its fields: each setting at its owner). The app reads the model registry, the chosen model, the language,
// the enabled adapters, the silence stop, where the server listens and keeps its recordings, and where the labeled
// recordings go, the microphone and the hotkeys; it writes what the menu and the settings window choose, and takes a
// value out to go back to its default.
import Foundation

public struct Config: Equatable {
    public static let version = 6
    public static let defaultHost = "127.0.0.1"
    public static let defaultPort = 8090  // the server's own default (server/constants.py WORKING_PORT)
    public static let defaultRecordings = "~/speech/recordings"  // the server's own default (constants.py RECORDINGS)
    public static let defaultLabeled = "~/speech/labeled"
    /// "microphone": the Mac's own microphone (the default), macOS's input, or a device's UID.
    public static let builtInMicrophone = "builtin"
    public static let systemMicrophone = "system"

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
    /// The hotkeys: a tap of one right-hand modifier (TapKeyChoice); nil: the action has no key.
    public var dictationKey: TapKeyChoice? = .rightOption
    public var privateDictationKey: TapKeyChoice? = .rightCommand
    /// The file as parsed, for the settings window, which reads any value (a model's options, the server's section).
    public var raw: [String: Any] { file.contents }
    var file = Parsed()

    /// The parsed file, equal when its contents are.
    struct Parsed: Equatable {
        var contents: [String: Any] = [:]
        static func == (a: Parsed, b: Parsed) -> Bool { NSDictionary(dictionary: a.contents).isEqual(to: b.contents) }
    }
    public var microphone = Config.builtInMicrophone
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
        if let s = d["silenceStopSeconds"] as? Double, s > 0 { c.silenceStopSeconds = s }
        if let m = d["microphone"] as? String, !m.isEmpty { c.microphone = m }
        if let k = d["dictationKey"] as? String { c.dictationKey = TapKeyChoice(rawValue: k) }
        if let k = d["privateDictationKey"] as? String { c.privateDictationKey = TapKeyChoice(rawValue: k) }
        c.file = Parsed(contents: d)
        if let server = d["server"] as? [String: Any] {
            if let h = server["host"] as? String, !h.isEmpty { c.host = h }
            if let p = server["port"] as? Int, p > 0, p < 65536 { c.port = p }
            if let r = server["recordings"] as? String, !r.isEmpty { c.recordings = path(r) }
            if let l = server["labeled"] as? String, !l.isEmpty { c.labeled = path(l) }
        }
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

    /// Takes the value at `path` out of the file (back to its default), the rest of the text as it was; checked as
    /// set() checks its edit.
    public static func remove(_ path: [String], in url: URL = Config.url) throws {
        let text = try String(contentsOf: url, encoding: .utf8)
        guard let parsed = try JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any] else {
            throw MessageError("\(url.path) is not a JSON object")
        }
        let expected = removing(path[...], from: parsed)
        if let edited = try? JSONEdit.remove(path, in: text),
           let check = try? JSONSerialization.jsonObject(with: Data(edited.utf8)) as? [String: Any],
           NSDictionary(dictionary: check).isEqual(to: expected) {
            try edited.write(to: url, atomically: true, encoding: .utf8)
            return
        }
        let data = try JSONSerialization.data(withJSONObject: expected,
                                              options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
        try (data + Data("\n".utf8)).write(to: url, options: .atomic)
    }

    static func removing(_ path: ArraySlice<String>, from d: [String: Any]) -> [String: Any] {
        var d = d
        let key = path.first!
        if path.count == 1 {
            d[key] = nil
        } else if let inner = d[key] as? [String: Any] {
            d[key] = removing(path.dropFirst(), from: inner)
        }
        return d
    }

    /// The value at `path` in the file as parsed, or nil.
    public func value(_ path: [String]) -> Any? {
        var node: Any? = raw
        for key in path { node = (node as? [String: Any])?[key] }
        return node
    }

    static func setting(_ path: ArraySlice<String>, to value: Any, in d: [String: Any]) -> [String: Any] {
        var d = d
        let key = path.first!
        d[key] = path.count == 1 ? value : setting(path.dropFirst(), to: value, in: d[key] as? [String: Any] ?? [:])
        return d
    }
}
