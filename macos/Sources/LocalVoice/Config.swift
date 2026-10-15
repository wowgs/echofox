// The config file the app shares with the dictation server, ~/.local-voice/config.json ($LOCAL_VOICE_CONFIG),
// version 2 (server/settings.py has its fields). The app reads the model registry, the chosen model, the language,
// the silence stop and where the server listens; it writes only the chosen model.
import Foundation

struct Config {
    static var url: URL {
        if let p = ProcessInfo.processInfo.environment["LOCAL_VOICE_CONFIG"], !p.isEmpty { return URL(fileURLWithPath: p) }
        return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local-voice/config.json")
    }

    var models: [String] = []
    var model: String?
    var language = ""
    var silenceStopSeconds = 60.0
    var host = "127.0.0.1"
    var port = 8090
    var error: String?

    var serverURL: URL { URL(string: "ws://\(host):\(port)")! }

    static func load() -> Config {
        var c = Config()
        c.language = Locale.preferredLanguages.first.map { String($0.prefix(while: { $0 != "-" })) } ?? ""
        guard let data = try? Data(contentsOf: url) else {
            c.error = "cannot read \(url.path)"
            return c
        }
        guard let d = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
            c.error = "\(url.path) is not a JSON object"
            return c
        }
        if let v = d["version"] as? Int, v != 2 { c.error = "\(url.path) is version \(v); the app reads version 2" }
        c.models = ((d["models"] as? [String: Any]) ?? [:]).keys.sorted()
        c.model = d["model"] as? String
        if let l = d["language"] as? String { c.language = l }
        if let s = d["silenceStopSeconds"] as? Double, s >= 0 { c.silenceStopSeconds = s }
        if let server = d["server"] as? [String: Any] {
            if let h = server["host"] as? String, !h.isEmpty { c.host = h }
            if let p = server["port"] as? Int, p > 0, p < 65536 { c.port = p }
        }
        return c
    }

    /// Makes `name` the chosen model. Only the value of the top-level "model" changes, so the file keeps its order
    /// and layout; if that cannot be done safely, the file is written again from its parsed contents.
    static func choose(model name: String) throws {
        let text = try String(contentsOf: url, encoding: .utf8)
        guard var parsed = try JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any] else {
            throw NSError(domain: "LocalVoice", code: 1, userInfo: [NSLocalizedDescriptionKey: "\(url.path) is not a JSON object"])
        }
        let encoder = JSONEncoder()
        encoder.outputFormatting = .withoutEscapingSlashes
        let value = String(decoding: try encoder.encode(name), as: UTF8.self)
        // The top-level key, as Python's json.dump(indent=2) writes it: two spaces in.
        let re = try NSRegularExpression(pattern: #"^(  "model"\s*:\s*)"(?:[^"\\]|\\.)*""#, options: .anchorsMatchLines)
        let range = NSRange(text.startIndex..., in: text)
        if re.numberOfMatches(in: text, range: range) == 1 {
            let edited = re.stringByReplacingMatches(in: text, range: range,
                                                     withTemplate: "$1" + NSRegularExpression.escapedTemplate(for: value))
            if var check = try? JSONSerialization.jsonObject(with: Data(edited.utf8)) as? [String: Any],
               check["model"] as? String == name {
                check["model"] = nil
                var rest = parsed
                rest["model"] = nil
                if NSDictionary(dictionary: check).isEqual(to: rest) {
                    try edited.write(to: url, atomically: true, encoding: .utf8)
                    return
                }
            }
        }
        parsed["model"] = name
        let data = try JSONSerialization.data(withJSONObject: parsed,
                                              options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
        try (data + Data("\n".utf8)).write(to: url, options: .atomic)
    }
}
