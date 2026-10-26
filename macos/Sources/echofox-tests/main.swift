// The checks of EchoFoxCore: `swift run --package-path macos echofox-tests`. An executable, not a test target: XCTest and
// Swift Testing come only with Xcode. It exits 1 if a check fails.
import Foundation
import EchoFoxCore

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
    check(info.snapshotApps == ["com.anthropic.claudefordesktop", "com.tdesktop.Telegram"]
          && info.treeApps == ["com.anthropic.claudefordesktop"] && info.listApps == ["com.tdesktop.Telegram"],
          "info: apps, trees and lists")
    check(info.languages.first.map { [$0.code, $0.name] } == ["cs", "Czech"] && info.languages.count == 20,
          "info: the languages")
    var other = examples["info"] as! [String: Any]
    other["interface"] = 99
    check((try? ServerInfo.decode(data(other))) == nil, "info: another interface is refused")
} catch {
    check(false, "info does not decode: \(error)")
}

// The config's "microphone" among the inputs: the built-in one by its kind, a device by its UID, macOS's input.
do {
    typealias D = MicrophoneChoice.Device
    let mac = D(uid: "BuiltInMic", builtIn: true), headset = D(uid: "AirPods-1", builtIn: false)
    check(MicrophoneChoice.value(for: mac) == "builtin" && MicrophoneChoice.value(for: headset) == "AirPods-1", "mic: the value written")
    check(MicrophoneChoice.names("builtin", mac) && !MicrophoneChoice.names("builtin", headset)
          && MicrophoneChoice.names("AirPods-1", headset) && !MicrophoneChoice.names("system", mac), "mic: the check mark")
    check(MicrophoneChoice.isListed("system", among: []) && !MicrophoneChoice.isListed("Gone-2", among: [mac, headset]),
          "mic: a gone device is not listed")
    check(MicrophoneChoice.resolve("AirPods-1", among: [mac, headset]).index == 1, "mic: the chosen device")
    check(MicrophoneChoice.resolve("Gone-2", among: [mac, headset]) == (0, "the chosen microphone is gone: the built-in one"),
          "mic: a gone device falls back to the built-in one")
    check(MicrophoneChoice.resolve("builtin", among: [headset]).index == nil && MicrophoneChoice.resolve("system", among: [mac]).index == nil,
          "mic: no built-in one, or macOS's input: nil")
}

// What the focus snapshot takes of an app, as the example's enabled adapters ask.
do {
    let info = try ServerInfo.decode(data(examples["info"]!))
    check(info.snapshotPlan(for: "com.anthropic.claudefordesktop") == SnapshotPlan(full: true, tree: true, lists: false, outline: true),
          "plan: Claude Desktop, its tree and its outline")
    check(info.snapshotPlan(for: "com.tdesktop.Telegram") == SnapshotPlan(full: true, tree: false, lists: true, outline: false),
          "plan: Telegram, its lists")
    check(info.snapshotPlan(for: "com.apple.TextEdit") == .none, "plan: an app no adapter reads gets nothing")
} catch {
    check(false, "plan: \(error)")
}

// The app's start and stop, as in the example: the same keys.
let start = try JSONSerialization.jsonObject(with: Data(ClientMessage.start(
    model: "gemma-e4b", language: "ru", sampleRate: 16000, client: "echofox-mac",
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
let down = TapKeyChoice.rightOption.downMask, key = TapKeyChoice.rightOption.keyCode
check(!tap.feed(.flags(keyCode: key, raw: down, timestamp: 1)) && tap.feed(.flags(keyCode: key, raw: 0, timestamp: 1.2)),
      "tap: a lone tap")
_ = tap.feed(.flags(keyCode: key, raw: down, timestamp: 2))
_ = tap.feed(.keyOrClick)
check(!tap.feed(.flags(keyCode: key, raw: 0, timestamp: 2.1)), "tap: a key in between")
_ = tap.feed(.flags(keyCode: key, raw: down, timestamp: 3))
check(!tap.feed(.flags(keyCode: key, raw: 0, timestamp: 3 + Tuning.longestTapSeconds + 0.1)), "tap: held too long")
_ = tap.feed(.flags(keyCode: key, raw: down | 0x0010_0000, timestamp: 4))
check(!tap.feed(.flags(keyCode: key, raw: 0, timestamp: 4.1)), "tap: with Command held")
check(!tap.feed(.flags(keyCode: key, raw: 0, timestamp: 5)), "tap: a release without a press")
// The right Command: its own Command flag is down with it, and that does not spoil the tap; ⌘C does.
var command = TapLogic(key: .rightCommand)
let cmdDown = TapKeyChoice.rightCommand.downMask | 0x0010_0000, cmd = TapKeyChoice.rightCommand.keyCode
check(!command.feed(.flags(keyCode: cmd, raw: cmdDown, timestamp: 1)) && command.feed(.flags(keyCode: cmd, raw: 0, timestamp: 1.1)),
      "tap: the right Command alone")
_ = command.feed(.flags(keyCode: cmd, raw: cmdDown, timestamp: 2))
_ = command.feed(.keyOrClick)
check(!command.feed(.flags(keyCode: cmd, raw: 0, timestamp: 2.1)), "tap: ⌘C is no tap")
_ = command.feed(.flags(keyCode: cmd, raw: cmdDown | 0x08, timestamp: 3))
check(!command.feed(.flags(keyCode: cmd, raw: 0, timestamp: 3.1)), "tap: with the left Command held")

// The config: read, and the chosen model written in place.
let dir = FileManager.default.temporaryDirectory.appendingPathComponent("echofox-tests-\(getpid())")
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
  "server": {"port": 8099, "labeled": "~/elsewhere"},
  "version": 7
}

"""
try text.write(to: file, atomically: true, encoding: .utf8)
var c = Config.load(from: file, systemLanguage: "en-GB")
check(c.models == ["a", "b"] && c.model == "a" && c.language == "ru" && c.silenceStopSeconds == 30 && c.port == 8099
      && c.error == nil, "config: read \(c)")
check(c.microphone == "builtin", "config: the built-in microphone by default")
check(c.recordings.path.hasSuffix("/speech/recordings") && !c.recordings.path.contains("~")
      && c.labeled.path.hasSuffix("/elsewhere"), "config: the folders, ~ expanded; the labels' from the server's section")
try Config.set(["model"], to: "b", in: file)
var after = try String(contentsOf: file, encoding: .utf8)
check(after == text.replacingOccurrences(of: #""model": "a""#, with: #""model": "b""#), "config: only the model changed")
c = Config.load(from: file)
check(c.model == "b", "config: the new model reads back")
// An adapter the file does not name yet: added after the last member, with its indentation; the rest stays.
try Config.set(["adapters", "chat"], to: ["enabled": true], in: file)
after = try String(contentsOf: file, encoding: .utf8)
check(after.hasSuffix("""
  "version": 7,
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
    let root = FileManager.default.temporaryDirectory.appendingPathComponent("echofox-label-\(getpid())")
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
          && label["model"] as? String == "m" && label["convention"] as? String == "clean", "label: the label \(label)")
    check((try? String(contentsOf: dir.appendingPathComponent("audio.wav"), encoding: .utf8)) == "RIFF1"
          && (try? String(contentsOf: dir.appendingPathComponent("text-before-audio.txt"), encoding: .utf8)) == "CONTEXT",
          "label: the audio and the context are copied")
    try? FileManager.default.removeItem(at: root)
} catch {
    check(false, "labeling: \(error)")
}

// The settings: the server's description, where a value is read and written (at its owner), and the layout.
do {
    let info = try ServerInfo.decode(data(examples["info"]!))
    let settings = info.settings ?? []
    let by = Dictionary(uniqueKeysWithValues: settings.map { ($0.key, $0) })
    check(settings.map(\.key) == ["maxRecordingMinutes", "recordings", "temperature"]
          && settings.map(\.owner) == ["server", "server", "model"]
          && by["maxRecordingMinutes"]?.advanced == nil && by["temperature"]?.advanced == true, "settings: decoded \(settings.map(\.key))")
    check(by["maxRecordingMinutes"]?.unit == "min" && by["temperature"]?.unit == nil && by["recordings"]?.kind == "folder",
          "settings: the server names units and folders")
    check(info.model?.catalog == "gemma-4-e4b" && info.languages.first { $0.code == "ru" }?.fillers?.contains("э") == true,
          "settings: the model and the languages")
    let gib: UInt64 = 1 << 30
    let pick = { (m: UInt64) in ServerInfo.Variant.recommended(info.model?.variants ?? [], memory: m * gib) }
    check(pick(8) == "q4_0" && pick(16) == "q4_0" && pick(24) == "q8_0" && pick(64) == "q8_0",
          "settings: the variant for 8, 16, 24 and 64 GB: \([8, 16, 24, 64].map { pick(UInt64($0)) })")
    check(info.model?.variant == "q8_0" && info.model?.variants?.map(\.id) == ["q4_0", "q8_0"]
          && info.model?.variants?.first?.downloaded == false, "settings: the model's variants")
    let cut = by["maxRecordingMinutes"]!, temperature = by["temperature"]!
    check(cut.value == nil && cut.default == .number(30) && cut.minExclusive == true
          && temperature.value == .number(0.7), "settings: values")
    check(!cut.allows(0) && cut.allows(0.5) && cut.allows(1000) && !temperature.allows(-1), "settings: range")
    let dir = FileManager.default.temporaryDirectory.appendingPathComponent("echofox-settings-\(getpid())")
    try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    let file = dir.appendingPathComponent("config.json")
    let text = """
    {
      "model": "a",
      "models": {"a": {"llamaServer": "http://h:1", "options": {"topK": 2, "temperature": 1}}},
      "adapters": {"claude": {"enabled": true, "chatTermsTokenBudget": 3}},
      "server": {"port": 8090, "maxRecordingMinutes": 2}
    }

    """
    try text.write(to: file, atomically: true, encoding: .utf8)
    var config = Config.load(from: file)
    var st = SettingStore.state(of: cut, in: config)
    check(st.path == ["server", "maxRecordingMinutes"] && st.value == .number(2) && st.changed,
          "settings: a server's at the server, the config's value in force")
    let topK = try JSONDecoder().decode(SettingInfo.self, from: Data(#"{"key":"topK","owner":"model","group":"sampling","kind":"integer","title":"Top K","default":64,"help":"h"}"#.utf8))
    st = SettingStore.state(of: topK, in: config)
    check(st.path == ["models", "a", "options", "topK"] && st.value == .number(2), "settings: a model's in its options")
    check(!SettingStore.state(of: temperature, in: config).changed,
          "settings: a value equal to the default is no change (temperature 1)")
    let terms = try JSONDecoder().decode(SettingInfo.self, from: Data(#"{"key":"chatTermsTokenBudget","owner":"adapter","group":"context","kind":"integer","title":"Names and terms","default":100,"min":0,"help":"h"}"#.utf8))
    let claude = try JSONDecoder().decode(ServerInfo.Adapter.self, from: Data(#"{"name":"claude","enabled":true,"apps":[],"electronTree":true,"context":{"chatTermsTokenBudget":200}}"#.utf8))
    st = SettingStore.state(of: terms, in: config, scope: .adapter(claude))
    check(st.path == ["adapters", "claude", "chatTermsTokenBudget"] && st.own == .number(3)
          && st.inherited == .number(200) && st.source == .adapter("claude"), "settings: an adapter's over its manifest")
    try Config.remove(["adapters", "claude", "chatTermsTokenBudget"], in: file)
    config = Config.load(from: file)
    st = SettingStore.state(of: terms, in: config, scope: .adapter(claude))
    check(!st.changed && st.value == .number(200) && st.source == .adapter("claude"), "settings: then the manifest's")
    check(SettingStore.edit("200", of: terms, state: st) == .remove && SettingStore.edit("90", of: terms, state: st) == .write(.number(90))
          && SettingStore.edit("", of: terms, state: st) == .remove && SettingStore.edit("-1", of: terms, state: st) == .refuse
          && SettingStore.edit("2.5", of: terms, state: st) == .refuse && SettingStore.edit("abc", of: terms, state: st) == .refuse,
          "settings: an edit equal to the inherited value takes the value out; one out of range is refused")
    check(SettingStore.edit("0,5", of: cut, state: SettingStore.state(of: cut, in: config)) == .write(.number(0.5)),
          "settings: a decimal comma")
    let prose = SettingInfo(key: "proseOnly", owner: "adapter", kind: "boolean", title: "Only sentences", default: .bool(true))
    let proseState = SettingStore.state(of: prose, in: config, scope: .adapter(claude))
    check(SettingStore.toggle(true, state: proseState) == .remove && SettingStore.toggle(false, state: proseState) == .write(.bool(false)),
          "settings: a switch back to the inherited value takes the value out")
    check(SettingStore.json(.number(90), of: terms) as? Int == 90, "settings: an integer is written whole")
    let decimal = try JSONEdit.set(["x"], to: 0.95, in: #"{"x": 1}"#)
    check(decimal == #"{"x": 0.95}"#, "settings: 0.95 is written as 0.95: \(decimal)")
    try Config.remove(["server", "maxRecordingMinutes"], in: file)
    config = Config.load(from: file)
    check(config.value(["server", "maxRecordingMinutes"]) == nil && config.value(["server", "port"]) as? Int == 8090,
          "settings: a value taken out")
    st = SettingStore.state(of: cut, in: config)
    check(!st.changed && st.value == .number(30), "settings: then the server's default")
    let edited = try String(contentsOf: file, encoding: .utf8)
    check(edited.contains(#""server": {"port": 8090}"#), "settings: the rest of the file as it was: \(edited)")
    try Config.remove(["models", "a", "options", "topK"], in: file)
    try Config.remove(["models", "a", "options", "temperature"], in: file)
    let emptied = try String(contentsOf: file, encoding: .utf8)
    check(emptied.contains(#""options": {}"#), "settings: the last member out")
    let missing = try JSONEdit.remove(["nothing"], in: #"{"a": 1}"#), first = try JSONEdit.remove(["a"], in: #"{"a": 1, "b": 2}"#)
    check(missing == #"{"a": 1}"#, "settings: a missing member")
    check(first == #"{"b": 2}"#, "settings: the first member out")
    check(SettingsLayout.menu == ["permissions", "microphone", "inputVolume", "labelRecordings"],
          "settings: the menu \(SettingsLayout.menu)")
    let keys: [(key: String, owner: String, group: String, advanced: Bool)] = [
        ("maxRecordingMinutes", "server", "recording", false), ("topK", "model", "sampling", true),
        ("chatTermsTokenBudget", "adapter", "context", true), ("brandNew", "server", "new", false)]
    let general = SettingsLayout.sections(of: .general, serverKeys: keys)
    let model = SettingsLayout.sections(of: .model, serverKeys: keys)
    check(general.contains { $0.section == "Recording" && $0.ids == ["silenceStopSeconds", "maxRecordingMinutes"] }
          && general.contains { $0.section == "Other" && $0.ids == ["brandNew"] }
          && !general.contains { $0.ids.contains("topK") || $0.ids.contains("chatTermsTokenBudget") },
          "settings: the server's settings on General \(general)")
    check(model.first?.section == "Model" && model.last?.section == "Advanced" && model.last?.ids == ["topK"],
          "settings: the model's page, its sampler in Advanced \(model)")
    check(SettingsLayout.sidebar.contains(.adapters) && !SettingsLayout.places.keys.contains { $0.hasPrefix("adapter") },
          "settings: Adapters is a heading of the sidebar, not a page")
} catch {
    check(false, "settings: \(error)")
}

// The messages of a model's download and removal, as the examples have them.
do {
    let answers = (examples["models"] as? [[String: Any]] ?? []).map { m -> ServerMessage? in
        ServerMessage.parse(String(decoding: try! JSONSerialization.data(withJSONObject: m), as: UTF8.self))
    }
    check(answers == [.progress(bytes: 1048576, total: 5582359648), .downloaded, .removed(4590807392),
                      .error("not enough free disk")], "models: the server's answers \(answers)")
    let sent = try JSONSerialization.jsonObject(with: Data(ClientMessage.download(catalog: "gemma-4-e4b", variant: "q4_0").utf8))
    check(NSDictionary(dictionary: sent as? [String: Any] ?? [:]).isEqual(to: examples["download"] as? [String: Any] ?? [:]),
          "models: the download message is the example's")
}

// A variant that the server downloads for another window offers no second download.
do {
    func v(_ downloaded: Bool, _ downloading: Bool?) throws -> ServerInfo.Variant {
        var o: [String: Any] = ["id": "q8_0", "name": "Q8_0", "bytes": 1e9, "downloaded": downloaded]
        if let d = downloading { o["downloading"] = d }
        return try JSONDecoder().decode(ServerInfo.Variant.self, from: data(o))
    }
    let missing = try v(false, nil), downloading = try v(false, true), there = try v(true, nil)
    check(missing.canDownload && !downloading.canDownload && !there.canDownload,
          "variants: Download only when the files are neither there nor downloading")
} catch {
    check(false, "variants: \(error)")
}

// The launchd agent of a bundled server.
do {
    let home = URL(fileURLWithPath: "/Users/someone"), r = URL(fileURLWithPath: "/Applications/EchoFox.app/Contents/Resources")
    let agent = { (version: String) in
        ServerAgent.plist(python: r.appendingPathComponent("python/bin/python3"), server: r.appendingPathComponent("server"),
                          home: home, version: version)
    }
    let p = agent("0.2 (180)")
    check(p["Label"] as? String == "echofox.gemma-voice"
          && p["ProgramArguments"] as? [String] == ["/Applications/EchoFox.app/Contents/Resources/python/bin/python3",
                                                    "/Applications/EchoFox.app/Contents/Resources/server/gemma_voice.py"]
          && p["ExitTimeOut"] as? Int == 210 && p["KeepAlive"] as? Bool == true, "server agent: its plist")
    check(p["EnvironmentVariables"] as? [String: String] == ["PYTHONDONTWRITEBYTECODE": "1", "ECHOFOX_APP_VERSION": "0.2 (180)"],
          "server agent: no bytecode written, and the app's version")
    check(ServerAgent.misplaced(app: "/Applications/EchoFox.app", readOnlyVolume: false) == nil
          && ServerAgent.misplaced(app: "/Users/someone/Applications/EchoFox.app", readOnlyVolume: false) == nil,
          "server agent: written from Applications")
    check(ServerAgent.misplaced(app: "/Volumes/EchoFox/EchoFox.app", readOnlyVolume: true) != nil
          && ServerAgent.misplaced(app: "/private/var/folders/x/T/AppTranslocation/0A1B/d/EchoFox.app", readOnlyVolume: true) != nil
          && ServerAgent.misplaced(app: "/private/var/folders/x/T/AppTranslocation/0A1B/d/EchoFox.app", readOnlyVolume: false) != nil,
          "server agent: not written from a disk image or App Translocation")
    check(ServerAgent.bundled(resources: URL(fileURLWithPath: "/nowhere")) == nil, "server agent: none without a bundled server")
    let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("echofox-agent-\(getpid()).plist")
    check(ServerAgent.differs(p, at: tmp), "server agent: a missing file differs")
    try PropertyListSerialization.data(fromPropertyList: p, format: .xml, options: 0).write(to: tmp)
    check(!ServerAgent.differs(p, at: tmp), "server agent: the same file does not")
    check(ServerAgent.differs(agent("0.3 (190)"), at: tmp), "server agent: a new version of the app in the same place differs")
    try? FileManager.default.removeItem(at: tmp)
} catch {
    check(false, "server agent: \(error)")
}

// A config that is not there yet gets created at the first value.
do {
    let dir = FileManager.default.temporaryDirectory.appendingPathComponent("echofox-first-\(getpid())")
    let file = dir.appendingPathComponent("config.json")
    try Config.set(["models", "gemma-e4b", "variant"], to: "q4_0", in: file)
    let c = Config.load(from: file)
    check(c.value(["models", "gemma-e4b", "variant"]) as? String == "q4_0" && c.error == nil, "first start: a new config")
    try? FileManager.default.removeItem(at: dir)
} catch {
    check(false, "first start: \(error)")
}

// The config's one owner in the app: its writes and the file's changes from elsewhere reach the observers.
do {
    let dir = FileManager.default.temporaryDirectory.appendingPathComponent("echofox-store-\(getpid())")
    let file = dir.appendingPathComponent("config.json")
    try? FileManager.default.removeItem(at: dir)
    try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    try Data("{\n  \"version\": \(Config.version)\n}\n".utf8).write(to: file)
    let store = ConfigStore(url: file)
    var seen: [(TapKeyChoice?, TapKeyChoice?)] = [], errors: [String] = [], logged: [String] = []
    store.observe { old, new in seen.append((old.dictationKey, new.dictationKey)) }
    store.onError = { errors.append($0) }
    store.log = { logged.append($0) }
    check(store.set(["dictationKey"], to: "rightShift", "keys: right Shift"), "store: a write")
    check(seen.count == 1 && seen[0].1 == .rightShift && logged == ["keys: right Shift"], "store: the write reaches the observer, \(seen)")
    store.check()
    check(seen.count == 1, "store: no change, no call")
    var text = try String(contentsOf: file, encoding: .utf8)
    text = text.replacingOccurrences(of: "rightShift", with: "rightControl")  // an editor's change
    try text.write(to: file, atomically: true, encoding: .utf8)
    try FileManager.default.setAttributes([.modificationDate: Date().addingTimeInterval(5)], ofItemAtPath: file.path)
    store.check()
    check(seen.count == 2 && seen[1] == (.rightShift, .rightControl) && store.config.dictationKey == .rightControl,
          "store: a change from elsewhere reaches the observer, \(seen)")
    try Data("not json".utf8).write(to: file)
    check(!store.remove(["dictationKey"], "keys: default") && errors.count == 1, "store: a failed write is reported, \(errors)")
    try? FileManager.default.removeItem(at: dir)
} catch {
    check(false, "store: \(error)")
}

// A download's speed and time left: from the progress every 0.5 s, over the last 5 s.
do {
    var r = TransferRate()
    r.add(bytes: 0, at: 100)
    check(r.bytesPerSecond == nil, "rate: unknown with one message")
    for i in 1...20 { r.add(bytes: Double(i) * 50e6, at: 100 + Double(i) / 2) }  // 100 MB/s for 10 s
    check(abs((r.bytesPerSecond ?? 0) - 100e6) < 1, "rate: 100 MB/s, \(r.bytesPerSecond ?? -1)")
    for i in 21...30 { r.add(bytes: 1e9 + Double(i - 20) * 10e6, at: 100 + Double(i) / 2) }  // then 20 MB/s for 5 s
    check(abs((r.bytesPerSecond ?? 0) - 20e6) < 1, "rate: the window follows the change, \(r.bytesPerSecond ?? -1)")
    check(abs((r.secondsLeft(total: 2.1e9) ?? 0) - 50) < 0.01, "rate: 1 GB left at 20 MB/s is 50 s")
    r.add(bytes: 5e6, at: 116)
    check(r.bytesPerSecond == nil, "rate: a new download starts over")
    check(TransferRate.speed(74.4e6) == "74 MB/s" && TransferRate.speed(4.25e6) == "4.2 MB/s", "rate: the speed's words")
    check(TransferRate.left(30) == "less than a minute left" && TransferRate.left(250) == "about 4 min left"
          && TransferRate.left(4800) == "about 1 h 20 min left", "rate: the time's words")
}

print(failures == 0 ? "echofox-tests: all checks pass" : "echofox-tests: \(failures) failed")
exit(failures == 0 ? 0 : 1)
