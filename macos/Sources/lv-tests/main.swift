// The checks of LocalVoiceCore: `swift run --package-path macos lv-tests`. An executable, not a test target: XCTest and
// Swift Testing come only with Xcode. It exits 1 if a check fails.
import Foundation
import LocalVoiceCore

var failures = 0
func check(_ ok: @autoclosure () -> Bool, _ what: String, file: String = #fileID, line: Int = #line) {
    if ok() { return }
    failures += 1
    print("FAIL \(file):\(line): \(what)")
}

let repo = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
    .deletingLastPathComponent().deletingLastPathComponent()
let examples = try JSONSerialization.jsonObject(with: Data(contentsOf: repo.appendingPathComponent(
    "shared/protocol-examples.json"))) as! [String: Any]
func data(_ o: Any) -> Data { try! JSONSerialization.data(withJSONObject: o) }

// The server's info, as in the contract's example.
do {
    let info = try ServerInfo.decode(data(examples["info"]!))
    check(info.sampleRate == 16000 && info.textWaitSeconds == 180, "info: the audio and the wait")
    check(info.snapshotApps == ["com.anthropic.claudefordesktop"] && info.treeApps == info.snapshotApps, "info: apps")
    check(info.languages.first.map { [$0.code, $0.name] } == ["cs", "Czech"] && info.languages.count == 20,
          "info: the languages")
    var other = examples["info"] as! [String: Any]
    other["interface"] = 99
    check((try? ServerInfo.decode(data(other))) == nil, "info: another interface is refused")
} catch {
    check(false, "info does not decode: \(error)")
}

// The app's start and stop, as in the example: the same keys.
let start = try JSONSerialization.jsonObject(with: Data(ClientMessage.start(
    model: "gemma-e4b", language: "ru", sampleRate: 16000, client: "local-voice-mac",
    snapshot: ["app": ["bundleId": "com.example.app"]]).utf8)) as! [String: Any]
check(Set(start.keys) == Set((examples["start"] as! [String: Any]).keys), "start: the example's keys")
let stop = try JSONSerialization.jsonObject(with: Data(ClientMessage.stop(.user).utf8)) as! [String: String]
check(stop == examples["stop"] as! [String: String], "stop: as in the example")
check(ClientMessage.StopReason.maxDuration.rawValue == "max_duration", "stop: the reasons' names")

// The server's messages.
let parsed = (examples["server"] as! [[String: Any]]).map { ServerMessage.parse(String(decoding: data($0), as: UTF8.self)) }
check(parsed == [.speech, .text("Привет"), .error("boom"), .stopped("max_duration"), .done], "server messages: \(parsed)")
check(ServerMessage.parse("not json") == nil, "server messages: not JSON")

// The hotkey: a lone tap of the right Option counts; with another key, too long, or with another modifier, not.
var tap = TapLogic()
let down = TapLogic.rightOptionMask, key = TapLogic.rightOption
check(!tap.feed(.flags(keyCode: key, raw: down, timestamp: 1)) && tap.feed(.flags(keyCode: key, raw: 0, timestamp: 1.2)),
      "tap: a lone tap")
_ = tap.feed(.flags(keyCode: key, raw: down, timestamp: 2))
_ = tap.feed(.keyOrClick)
check(!tap.feed(.flags(keyCode: key, raw: 0, timestamp: 2.1)), "tap: a key in between")
_ = tap.feed(.flags(keyCode: key, raw: down, timestamp: 3))
check(!tap.feed(.flags(keyCode: key, raw: 0, timestamp: 3 + Tuning.longestTapSeconds + 0.1)), "tap: held too long")
_ = tap.feed(.flags(keyCode: key, raw: down | TapLogic.otherModifiers, timestamp: 4))
check(!tap.feed(.flags(keyCode: key, raw: 0, timestamp: 4.1)), "tap: with Command held")
check(!tap.feed(.flags(keyCode: key, raw: 0, timestamp: 5)), "tap: a release without a press")

// The config: read, and the chosen model written in place.
let dir = FileManager.default.temporaryDirectory.appendingPathComponent("lv-tests-\(getpid())")
try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
let file = dir.appendingPathComponent("config.json")
let text = """
{
  "model": "a",
  "language": "ru",
  "models": {
    "a": {"llamaServer": "http://h:1", "prompt": "say \\"model\\": here"},
    "b": {"llamaServer": "http://h:2"}
  },
  "silenceStopSeconds": 30,
  "server": {"port": 8099},
  "version": 3
}

"""
try text.write(to: file, atomically: true, encoding: .utf8)
var c = Config.load(from: file, systemLanguage: "en-GB")
check(c.models == ["a", "b"] && c.model == "a" && c.language == "ru" && c.silenceStopSeconds == 30 && c.port == 8099
      && c.error == nil, "config: read \(c)")
check(c.recordings.path.hasSuffix("/speech/recordings") && !c.recordings.path.contains("~")
      && c.labeled.path.hasSuffix("/speech/labeled"), "config: the default folders, ~ expanded")
try Config.set(["model"], to: "b", in: file)
var after = try String(contentsOf: file, encoding: .utf8)
check(after == text.replacingOccurrences(of: #""model": "a""#, with: #""model": "b""#), "config: only the model changed")
c = Config.load(from: file)
check(c.model == "b", "config: the new model reads back")
// An adapter the file does not name yet: added after the last member, with its indentation; the rest stays.
try Config.set(["adapters", "chat"], to: ["enabled": true], in: file)
after = try String(contentsOf: file, encoding: .utf8)
check(after.hasSuffix("""
  "version": 3,
  "adapters": {"enabled": true}
}

""".replacingOccurrences(of: #""adapters": {"enabled": true}"#, with: #""adapters": {"chat": {"enabled": true}}"#)),
      "config: a new object at the end: \(after)")
try Config.set(["adapters", "chat", "enabled"], to: false, in: file)
try Config.set(["adapters", "other", "enabled"], to: true, in: file)
try Config.set(["language"], to: "", in: file)
c = Config.load(from: file, systemLanguage: "en-GB")
check(c.adapters == ["chat": false, "other": true] && c.language == "" && c.models == ["a", "b"] && c.port == 8099,
      "config: the adapters and the language read back: \(c)")
after = try String(contentsOf: file, encoding: .utf8)
check(after.contains(#""adapters": {"chat": {"enabled": false}, "other": {"enabled": true}}"#)
      && after.hasPrefix("{\n  \"model\": \"b\",\n  \"language\": \"\",\n  \"models\": {"),
      "config: the order and the layout stay: \(after)")

// JSONEdit by itself: nested, empty objects, strings with braces and escapes, arrays, a key that is not an object.
func edit(_ path: [String], _ value: Any, _ text: String) -> String? { try? JSONEdit.set(path, to: value, in: text) }
check(edit(["a"], 1, "{}") == #"{"a": 1}"#, "edit: into an empty object")
check(edit(["a", "b"], true, #"{"x": [1, {"a": 2}], "a": {}}"#) == #"{"x": [1, {"a": 2}], "a": {"b": true}}"#,
      "edit: the right a, into its empty object")
check(edit(["k"], "v", #"{"s": "a\"}{,", "k": null}"#) == #"{"s": "a\"}{,", "k": "v"}"#, "edit: past a tricky string")
check(edit(["s", "x"], 1, #"{"s": "text"}"#) == nil, "edit: through a string: an error")
check(edit(["a"], 1, "[1]") == nil && edit(["a"], 1, #"{"a" 1}"#) == nil, "edit: not an object, or bad JSON: an error")
check(edit(["n"], "ü/", "{\n\t\"m\": 1\n}") == "{\n\t\"m\": 1,\n\t\"n\": \"ü/\"\n}", "edit: a tab's indentation")
try #"{"version": 2}"#.write(to: file, atomically: true, encoding: .utf8)
check(Config.load(from: file).error != nil, "config: another version is an error")
check(Config.load(from: dir.appendingPathComponent("none.json"), systemLanguage: "de-DE").language == "de",
      "config: no file: the system's language")
try? FileManager.default.removeItem(at: dir)

// Labeling: the pieces not labeled yet, newest first; a saved one is done, its audio and context copied.
do {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent("lv-label-\(getpid())")
    let recs = root.appendingPathComponent("recordings"), labeled = root.appendingPathComponent("labeled")
    func recording(_ day: String, _ id: String, _ pieces: [(Int, String, String?)]) throws {
        let dir = recs.appendingPathComponent(day).appendingPathComponent(id)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        var lines = ""
        for (n, text, raw) in pieces {
            try Data("RIFF\(n)".utf8).write(to: dir.appendingPathComponent("piece-\(n).wav"))
            var p: [String: Any] = ["piece": n, "text": text, "audio_seconds": 1.5]
            if let raw { p["raw"] = raw }
            lines += String(decoding: try JSONSerialization.data(withJSONObject: p), as: UTF8.self) + "\n"
        }
        try lines.write(to: dir.appendingPathComponent("pieces.jsonl"), atomically: true, encoding: .utf8)
        try "CONTEXT".write(to: dir.appendingPathComponent("text-before-audio.txt"), atomically: true, encoding: .utf8)
        let record: [String: Any] = ["started": day, "model": "m", "language": "ru",
                                     "chat": ["details": ["title": "Radio"], "about": "a chat"]]
        try JSONSerialization.data(withJSONObject: record).write(to: dir.appendingPathComponent("adapter.json"))
    }
    try recording("2026-10-17", "100000-a", [(1, "Привет", "Э, привет"), (2, "мир", nil)])
    try recording("2026-10-18", "090000-b", [(1, "Новое", nil)])
    try FileManager.default.createDirectory(at: recs.appendingPathComponent("2026-10-18/080000-empty"),
                                            withIntermediateDirectories: true)  // a recording without pieces
    var items = Labeling.pending(recordings: recs, labeled: labeled)
    check(items.map { "\($0.recording)#\($0.piece)" } == ["2026-10-18/090000-b#1", "2026-10-17/100000-a#1",
                                                         "2026-10-17/100000-a#2"], "label: newest first: \(items)")
    check(items[1].raw == "Э, привет" && items[1].place == "Radio" && items[1].text == "Привет", "label: an item")
    try Labeling.save(items[1], text: " Ну, привет \n", status: .verified, labeled: labeled)
    try Labeling.save(items[0], text: "", status: .unusable, labeled: labeled)
    items = Labeling.pending(recordings: recs, labeled: labeled)
    check(items.map { "\($0.recording)#\($0.piece)" } == ["2026-10-17/100000-a#2"], "label: saved ones are done")
    let dir = Labeling.labelFolder(labeled, "2026-10-17/100000-a", 1)
    let label = try JSONSerialization.jsonObject(with: Data(contentsOf: dir.appendingPathComponent("label.json")))
        as! [String: Any]
    check(label["text"] as? String == "Ну, привет" && label["modelText"] as? String == "Привет"
          && label["modelRaw"] as? String == "Э, привет" && label["status"] as? String == "verified"
          && label["model"] as? String == "m" && label["convention"] as? String == "verbatim", "label: the label \(label)")
    check((try? String(contentsOf: dir.appendingPathComponent("audio.wav"), encoding: .utf8)) == "RIFF1"
          && (try? String(contentsOf: dir.appendingPathComponent("text-before-audio.txt"), encoding: .utf8)) == "CONTEXT",
          "label: the audio and the context are copied")
    try? FileManager.default.removeItem(at: root)
} catch {
    check(false, "labeling: \(error)")
}

print(failures == 0 ? "lv-tests: all checks pass" : "lv-tests: \(failures) failed")
exit(failures == 0 ? 0 : 1)
