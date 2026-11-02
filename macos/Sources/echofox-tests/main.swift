// The checks of EchoFoxCore and of FocusSnapshot's token estimate and outline: `swift run --package-path macos echofox-tests`.
// An executable, not a test target: XCTest and Swift Testing come only with Xcode. It exits 1 if a check fails.
import Foundation
import EchoFoxCore
import FocusSnapshot
import Network

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
    check(info.model?.title == "Gemma 4 E4B", "info: the model's name for people")
    check(info.proposedLanguage("ru") == "ru" && info.proposedLanguage("xx") == "en", "info: the first start's language")
    check(info.identityApps == ["com.anthropic.claudefordesktop", "com.mitchellh.ghostty", "com.tdesktop.Telegram"]
          && info.treeApps == ["com.anthropic.claudefordesktop"],
          "info: the identity's apps (the surfaces' apps) and the trees asked for (treeOnRequest)")
    let code = info.adapters.first { $0.name == "claude-code" }!
    let desktop = code.surfaces[0], terminal = code.surfaces[1]
    check(code.surfaces.map(\.id) == ["desktop", "terminal"] && code.apps == ["com.anthropic.claudefordesktop", "com.mitchellh.ghostty"]
          && desktop.treeOnRequest == true && terminal.treeOnRequest == nil
          && desktop.match?.url == "https://claude.ai/epitaxy/*" && desktop.match?.title == nil
          && desktop.screen?.outline?.skip == ["epitaxy-document-page"] && desktop.screen?.outline?.budget == nil
          && desktop.screen?.lists == nil && terminal.screen?.processes != nil
          && desktop.reads?.map(\.path) == ["~/.claude/projects"] && desktop.reads?.map(\.what) == ["The session's transcript"],
          "info: an adapter's surfaces as the example gives them")
    let chat = info.adapters.first { $0.name == "claude-chat" }!.surfaces[0]
    let telegram = info.adapters.first { $0.name == "telegram" }!.surfaces[0]
    check(chat.screen?.outline?.budget == "chatHistoryTokenBudget" && telegram.screen?.lists?.budget == "chatHistoryTokenBudget"
          && telegram.screen?.outline == nil, "info: the surfaces' budgets are the keys of their knobs")
    check(desktop.screen?.kinds == ["Page text"] && terminal.screen?.kinds == ["Running programs"]
          && telegram.screen?.kinds == ["Message lists"] && ServerInfo.Surface.Match.shown("https://claude.ai/chat/*")
              == "https://claude.ai/chat/…", "info: a surface in the settings window's words")
    var off = examples["info"] as! [String: Any]
    off["adapters"] = (off["adapters"] as! [[String: Any]]).map { a in
        var a = a
        a["enabled"] = a["name"] as? String == "telegram"
        return a
    }
    let some = try ServerInfo.decode(data(off))
    check(some.identityApps == ["com.tdesktop.Telegram"] && some.treeApps.isEmpty,
          "info: only the enabled adapters' apps get an identity and a tree")
    check(some.identityPlan(for: "com.tdesktop.Telegram") == IdentityPlan(identity: true, tree: false)
          && info.identityPlan(for: "com.anthropic.claudefordesktop") == IdentityPlan(identity: true, tree: true)
          && some.identityPlan(for: "com.anthropic.claudefordesktop") == .none
          && info.identityPlan(for: "com.apple.TextEdit") == .none, "info: the plan at the hotkey")
    let broken = try JSONDecoder().decode(ServerInfo.Adapter.self, from: Data(#"{"name":"x","enabled":true,"error":"bad"}"#.utf8))
    check(broken.surfaces.isEmpty && broken.apps.isEmpty, "info: an adapter whose manifest did not load has no surfaces")
    check(info.languages.first.map { [$0.code, $0.name] } == ["cs", "Czech"] && info.languages.count == 20,
          "info: the languages")
    check(info.commonNotes?.first?.contains("{LANGUAGE}") == true, "info: the notes of every language, not filled in")
    var other = examples["info"] as! [String: Any]
    other["interface"] = 99
    check((try? ServerInfo.decode(data(other))) == nil, "info: another interface is refused")
    var flac = examples["info"] as! [String: Any]
    flac["encoding"] = "flac"
    check((try? ServerInfo.decode(data(flac))) == nil, "info: another encoding is refused")
} catch {
    check(false, "info does not decode: \(error)")
}

// Where the text goes (InsertionRule), on a desk that records what was tried and does what each case says.
final class FakeDesk: InsertionDesk {
    typealias Box = String
    var inputs: Set<String> = [], lengths: [String: Int] = [:], front: Int32 = 0, focus: [Int32: String] = [:]
    var now: (box: String, pid: Int32)?
    var results: [String: InsertionResult] = [:]   // by way: "selected", "paste", "value", "keys", "type", "front"
    var grows: [String: String] = [:]              // a way after which a box shows the text late: way → box
    var calls: [String] = []
    func isInput(_ box: String) -> Bool { inputs.contains(box) }
    func length(_ box: String) -> Int? { lengths[box] }
    func isFront(_ pid: Int32) -> Bool { pid == front }
    func focused(in pid: Int32) -> String? { focus[pid] }
    func same(_ a: String, _ b: String) -> Bool { a == b }
    func describe(_ box: String) -> String { box }
    func focusedInput() -> (box: String, pid: Int32)? { now }
    private func way(_ name: String, _ box: String) -> InsertionResult? {
        calls.append("\(name) \(box)")
        if let late = grows[name] { lengths[late, default: 0] += 5 }
        return results[name]
    }
    func setSelectedText(_ text: String, _ box: String) -> InsertionResult? { way("selected", box) }
    func paste(_ text: String, into box: String, pid: Int32, anyFocus: Bool) -> InsertionResult? {
        way(anyFocus ? "paste any" : "paste", box)
    }
    func setValueIfEmpty(_ text: String, _ box: String) -> InsertionResult? { way("value", box) }
    func keysPaste(_ text: String, into box: String, pid: Int32) -> InsertionResult? { way("keys", box) }
    func type(_ text: String, into box: String, pid: Int32) -> InsertionResult? { way("type", box) }
    func bringToFrontAndPaste(_ text: String, into box: String, pid: Int32) -> InsertionResult? { way("front", box) }
    func pasteAtCursor(_ text: String) { calls.append("cursor") }
    func keep(_ text: String) { calls.append("clipboard") }
}
do {
    func desk(_ set: (FakeDesk) -> Void) -> FakeDesk {
        let d = FakeDesk()
        d.inputs = ["tap", "other"]
        d.lengths = ["tap": 0, "other": 0]
        set(d)
        return d
    }
    // 1. The box of the tap takes the selected text: nothing else is tried.
    var d = desk { $0.results["selected"] = .accessibility }
    check(InsertionRule.insert("hi", tapBox: "tap", tapPid: 1, on: d).0 == .accessibility && d.calls == ["selected tap"],
          "insert: the selected text of the box of the tap, \(d.calls)")
    // 2. A terminal in front: its Cmd+V counts though the box does not grow, and no way sends the text again.
    d = desk { $0.front = 1; $0.focus[1] = "tap"; $0.results["paste"] = .pasteUnchecked }
    check(InsertionRule.insert("hi", tapBox: "tap", tapPid: 1, on: d).0 == .pasteUnchecked
          && d.calls == ["selected tap", "paste tap"], "insert: a paste in front ends it, \(d.calls)")
    // 3. In the background, the ways in their order, until one works.
    d = desk { $0.front = 2; $0.results["keys"] = .axKeysInBackground }
    check(InsertionRule.insert("hi", tapBox: "tap", tapPid: 1, on: d).0 == .axKeysInBackground
          && d.calls == ["selected tap", "paste any tap", "value tap", "keys tap"], "insert: the background ways in order, \(d.calls)")
    // 4. The app's focus is in another box: no background way, the app comes to the front.
    d = desk { $0.front = 2; $0.focus[1] = "other"; $0.results["front"] = .pasteBroughtToFront }
    check(InsertionRule.insert("hi", tapBox: "tap", tapPid: 1, on: d).0 == .pasteBroughtToFront
          && d.calls == ["selected tap", "paste tap", "front tap"], "insert: focus in another box, \(d.calls)")
    // 5. A way that landed late counts, and no next way sends the text again.
    d = desk { $0.front = 2; $0.grows["paste any"] = "tap" }
    check(InsertionRule.insert("hi", tapBox: "tap", tapPid: 1, on: d).0 == .late
          && d.calls == ["selected tap", "paste any tap"], "insert: a late text counts, \(d.calls)")
    // 6. No box at the tap: the box focused now.
    d = desk { $0.now = ("other", 3); $0.results["selected"] = .accessibility }
    check(InsertionRule.insert("hi", tapBox: nil, tapPid: 1, on: d).0 == .accessibility && d.calls == ["selected other"],
          "insert: the box focused at the end, \(d.calls)")
    // 7. Once the tap's app got keys, the box focused now in that app gets nothing more: the clipboard.
    d = desk { $0.front = 1; $0.focus[1] = "tap"; $0.now = ("tap", 1) }
    check(InsertionRule.insert("hi", tapBox: "tap", tapPid: 1, on: d).0 == .clipboard && d.calls.last == "clipboard"
          && !d.calls.contains("cursor"), "insert: no second try in the tap's app, \(d.calls)")
    // 8. An app that tells nothing of its focus, still in front: a paste where its cursor is.
    d = desk { $0.front = 1 }
    check(InsertionRule.insert("hi", tapBox: nil, tapPid: 1, on: d).0 == .pasteUnchecked && d.calls == ["cursor"],
          "insert: at the cursor of an app that tells nothing, \(d.calls)")
    // 9. Nothing: the clipboard.
    d = desk { $0.front = 2 }
    check(InsertionRule.insert("hi", tapBox: nil, tapPid: nil, on: d).0 == .clipboard && d.calls == ["clipboard"],
          "insert: the clipboard, \(d.calls)")
}

// The labels' stats, and a language's lists as the settings window shows and reads them.
do {
    let dir = FileManager.default.temporaryDirectory.appendingPathComponent("echofox-stats-\(getpid())")
    try? FileManager.default.removeItem(at: dir)
    for (i, (status, seconds)) in [("verified", 2.5), ("verified", 4.0), ("unusable", 9.0)].enumerated() {
        let folder = dir.appendingPathComponent("2026-10-26/r\(i)/piece-1")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try data(["status": status, "audioSeconds": seconds]).write(to: folder.appendingPathComponent("label.json"))
    }
    let stats = Labeling.stats(labeled: dir)
    check(stats.count == 2 && stats.seconds == 6.5, "labels: only the verified ones count, \(stats)")
    check(Labeling.stats(labeled: dir.appendingPathComponent("none")) == (0, 0), "labels: no folder, none")
    try? FileManager.default.removeItem(at: dir)
    let fillers = SettingStore.LanguageList.fillers, notes = SettingStore.LanguageList.notes
    check(fillers.items(" э, мм ,, а-а ") == ["э", "мм", "а-а"] && fillers.text(["э", "мм"]) == "э, мм", "lists: the sounds")
    check(notes.items("one\n\n two ") == ["one", "two"] && notes.text(["a", "b"]) == "a\nb", "lists: the notes")
    check(fillers.path(of: "ru") == ["languages", "ru", "fillers"] && SettingStore.variantPath(of: "m") == ["models", "m", "variant"],
          "paths: a language's list and a model's variant")
} catch {
    check(false, "labels: \(error)")
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

// The app's start and stop, as in the example: the start with the identity, a private one without it.
let identity = (examples["start"] as! [String: Any])["identity"] as! [String: Any]
let start = try JSONSerialization.jsonObject(with: Data(ClientMessage.start(
    model: "gemma-e4b", language: "ru", sampleRate: 16000, client: "echofox-mac", identity: identity).utf8)) as! NSDictionary
check(start == examples["start"] as! NSDictionary, "start: as in the example")
let quiet = try JSONSerialization.jsonObject(with: Data(ClientMessage.start(
    model: nil, language: "ru", sampleRate: 16000, client: "echofox-mac", identity: identity, isPrivate: true).utf8)) as! [String: Any]
check(quiet["identity"] == nil && quiet["private"] as? Bool == true && quiet["snapshot"] == nil,
      "start: a private one carries no identity")
let stop = try JSONSerialization.jsonObject(with: Data(ClientMessage.stop(.user).utf8)) as! [String: String]
check(stop == examples["stop"] as! [String: String], "stop: as in the example")
check(ClientMessage.StopReason.silence.rawValue == "silence", "stop: the reasons' names")

// The server's read request, and the content that answers it: the example's outline, walked on a made-up tree of the
// example's page with the example's skip list, is the example's content.
struct FakeNode {
    var fields: [String: Any] = [:]
    var kids: [FakeNode] = []
    var value: String?
}
func walk(_ root: FakeNode, skip: [String] = [], budget: Int? = nil, asked: ((FakeNode) -> Void)? = nil) -> [String: Any] {
    FocusSnapshot.outline(of: root, root: "webArea", skip: Set(skip), budget: budget, describe: { $0.fields },
                          children: { $0.kids }, shownText: { asked?($0); return $0.value })
}
func nodes(_ outline: [String: Any]) -> [[String: Any]] { outline["nodes"] as? [[String: Any]] ?? [] }
func text(_ s: String) -> FakeNode { FakeNode(fields: ["role": "AXStaticText"], value: s) }
do {
    let read = ServerMessage.parse(String(decoding: data(examples["read"]!), as: UTF8.self))
    let weights = (examples["read"] as! [String: Any])["tokenWeights"] as? [String: Double]
    check(read == .read(ReadRequest(surfaces: [.init(surface: "claude-code/desktop",
                                                     outline: .init(skip: ["epitaxy-document-page"], budget: nil))],
                                    tokenWeights: weights)), "read: as in the example, \(String(describing: read))")
    let more = #"{"type": "read", "surfaces": [{"surface": "telegram/desktop", "outline": null, "lists": {"budget": 600}, "processes": null}, {"surface": "claude-code/terminal", "processes": {}}], "tokenWeights": {}}"#
    check(ServerMessage.parse(more) == .read(ReadRequest(surfaces: [.init(surface: "telegram/desktop", lists: .init(budget: 600)),
                                                                     .init(surface: "claude-code/terminal", processes: .init())],
                                                          tokenWeights: [:])),
          "read: lists with a budget in tokens, processes, null as not asked")
    check(ServerMessage.parse(#"{"type": "read", "surfaces": [{"outline": {}}]}"#) == .other, "read: a surface without its name")
    guard case .read(let request)? = read, let surface = request.surfaces.first else { throw MessageError("no read") }
    let page = FakeNode(fields: ["role": "AXWebArea", "title": "Local Speech - Claude Code", "url": "https://claude.ai/epitaxy/x"], kids: [
        FakeNode(fields: ["role": "AXPopUpButton", "title": "docs"]),
        FakeNode(fields: ["role": "AXPopUpButton", "title": "4-app.md"]),
        FakeNode(fields: ["role": "AXButton", "description": "View source"]),
        FakeNode(fields: ["role": "AXGroup", "domClasses": ["epitaxy-document-page"]], kids: [text("The file's text")]),
    ])
    var outline = walk(page, skip: surface.outline?.skip ?? [], budget: surface.outline?.budget)
    var first = nodes(outline)[0]
    first["url"] = nil  // the example leaves the web area's address out: the identity has it
    outline["nodes"] = [first] + nodes(outline).dropFirst()
    let content = try JSONSerialization.jsonObject(with: Data(ClientMessage.content(
        surfaces: [surface.surface: ["outline": outline]], tookMs: 64).utf8)) as! NSDictionary
    check(content == examples["content"] as! NSDictionary, "content: as in the example, \(content)")
} catch {
    check(false, "read: \(error)")
}

// The outline's walk: the skip list against all DOM classes, the cut to 12 only in the copy sent, the ancestors of the
// last element read, and no input field's value.
do {
    let many = (1...12).map { "c\($0)" } + ["private-part"]
    let skipped = walk(FakeNode(fields: ["role": "AXWebArea"], kids: [
        FakeNode(fields: ["role": "AXGroup", "domClasses": many], kids: [text("secret")])]), skip: ["private-part"])
    let group = nodes(skipped).last ?? [:]
    check(nodes(skipped).count == 2 && group["skipped"] as? Bool == true && (group["domClasses"] as? [String]) == Array(many.prefix(12))
          && skipped["complete"] as? Bool == true, "outline: a skip on the 13th class, 12 classes sent, \(skipped)")

    let tree = FakeNode(fields: ["role": "AXWebArea"], kids: [
        FakeNode(fields: ["role": "AXGroup", "identifier": "a"], kids: [text("old")]),
        FakeNode(fields: ["role": "AXGroup", "identifier": "b"], kids: [
            FakeNode(fields: ["role": "AXGroup", "identifier": "c"], kids: [text(String(repeating: "x", count: 40)),
                                                                             text(String(repeating: "y", count: 40))])]),
    ])
    let cut = walk(tree, budget: 5)  // 40 letters are 12 tokens with the fallback: the last text reaches the budget
    check(nodes(cut).map { $0["identifier"] as? String ?? $0["role"] as! String } == ["AXWebArea", "b", "c", "AXStaticText"]
          && nodes(cut).map { $0["depth"] as! Int } == [0, 1, 2, 3] && nodes(cut).last?["text"] as? String == String(repeating: "y", count: 40)
          && cut["complete"] as? Bool == false, "outline: the budget's stop keeps the last element's ancestors, \(nodes(cut))")
    let whole = walk(tree)
    check(nodes(whole).map { $0["text"] as? String ?? $0["identifier"] as? String ?? "" }
              == ["", "a", "old", "b", "c", String(repeating: "x", count: 40), String(repeating: "y", count: 40)]
          && whole["complete"] as? Bool == true, "outline: no budget, the whole tree in its order")

    var asked: [String] = []
    let field = walk(FakeNode(fields: ["role": "AXWebArea"], kids: [
        FakeNode(fields: ["role": "AXTextField"], value: "typed"), text("shown")]), asked: { asked.append($0.value ?? "") })
    check(asked == ["shown"] && !nodes(field).contains { $0["text"] as? String == "typed" },
          "outline: an input field's value is never read")
}

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
  "version": 11
}

"""
try text.write(to: file, atomically: true, encoding: .utf8)
var c = Config.load(from: file, systemLanguage: "en-GB")
check(c.models == ["a", "b"] && c.model == "a" && c.language == "ru" && c.silenceStopSeconds == 30 && c.port == 8099
      && c.error == nil, "config: read \(c)")
check(c.microphone == "builtin", "config: the built-in microphone by default")
let none = Config.load(from: file.deletingLastPathComponent().appendingPathComponent("not-there.json"), systemLanguage: "ru-RU")
check(none.error == nil && none.model == nil && none.language == "ru", "config: no file yet is the defaults, not an error")
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
  "version": 11,
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

// The config over versions: a newer format is read key by key with a note, and a write keeps what this app does not
// know; the keys the app reads are in the schema.
do {
    let newer = dir.appendingPathComponent("newer.json")
    try #"{"version": 12, "language": "ru", "adapters": {"telegram": {"enabled": true, "newBudget": 5}}, "newThing": [1]}"#
        .write(to: newer, atomically: true, encoding: .utf8)
    let n = Config.load(from: newer, systemLanguage: "en-GB")
    check(n.error == nil && n.note != nil && n.language == "ru" && n.adapters == ["telegram": true],
          "config: a newer format is read, with a note: \(n)")
    try Config.set(["model"], to: "a", in: newer)
    let written = try String(contentsOf: newer, encoding: .utf8)
    check(written.contains(#""version": 12"#) && written.contains(#""newThing": [1]"#) && written.contains(#""newBudget": 5"#),
          "config: a write keeps the newer format's keys: \(written)")
    let schema = try JSONSerialization.jsonObject(with: Data(contentsOf: repo.appendingPathComponent(
        "shared/config.schema.json"))) as! [String: Any]
    func known(_ path: [String], _ node: [String: Any]) -> Bool {
        guard let first = path.first, let props = node["properties"] as? [String: Any],
              let next = props[first] as? [String: Any] else { return false }
        return path.count == 1 || known(Array(path.dropFirst()), next)
    }
    let missing = Config.readKeys.filter { !known($0, schema) }
    check(missing.isEmpty, "config: the keys the app reads are in the schema; missing: \(missing)")
} catch {
    check(false, "config over versions: \(error)")
}

// JSONEdit by itself: nested, empty objects, strings with braces and escapes, arrays, a key that is not an object.
func edit(_ path: [String], _ value: Any, _ text: String) -> String? { try? JSONEdit.set(path, to: value, in: text) }
check(edit(["a"], 1, "{}") == #"{"a": 1}"#, "edit: into an empty object")
check(edit(["a", "b"], true, #"{"x": [1, {"a": 2}], "a": {}}"#) == #"{"x": [1, {"a": 2}], "a": {"b": true}}"#,
      "edit: the right a, into its empty object")
check(edit(["k"], "v", #"{"s": "a\"}{,", "k": null}"#) == #"{"s": "a\"}{,", "k": "v"}"#, "edit: past a tricky string")
check(edit(["s", "x"], 1, #"{"s": "text"}"#) == nil, "edit: through a string: an error")
check(edit(["a"], 1, "[1]") == nil && edit(["a"], 1, #"{"a" 1}"#) == nil, "edit: not an object, or bad JSON: an error")
check(edit(["n"], "ü/", "{\n\t\"m\": 1\n}") == "{\n\t\"m\": 1,\n\t\"n\": \"ü/\"\n}", "edit: a tab's indentation")
try #"{"version": 2, "language": "de"}"#.write(to: file, atomically: true, encoding: .utf8)
let older = Config.load(from: file)
check(older.error == nil && older.note == nil && older.language == "de",
      "config: an older format is read too (the server brings it up), with no note")
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
    check(settings.map(\.key) == ["maxRecordingSeconds", "recordings", "temperature", "chatHistoryTokenBudget"]
          && settings.map(\.owner) == ["server", "server", "model", "adapter"]
          && by["maxRecordingSeconds"]?.advanced == nil && by["temperature"]?.advanced == true, "settings: decoded \(settings.map(\.key))")
    check(by["maxRecordingSeconds"]?.unit == "s" && by["temperature"]?.unit == nil && by["recordings"]?.kind == "folder",
          "settings: the server names units and folders")
    check(info.model?.catalog == "gemma-4-e4b" && info.languages.first { $0.code == "ru" }?.fillers?.contains("э") == true,
          "settings: the model and the languages")
    let gib: UInt64 = 1 << 30
    let pick = { (m: UInt64) in ServerInfo.Variant.recommended(info.model?.variants ?? [], memory: m * gib) }
    check(pick(8) == "q4_0" && pick(16) == "q4_0" && pick(24) == "q4_0" && pick(64) == "q4_0",
          "settings: the variant for 8, 16, 24 and 64 GB: \([8, 16, 24, 64].map { pick(UInt64($0)) })")
    // Without a default (an older server): the biggest that takes at most half of the memory
    let plain = try JSONDecoder().decode([ServerInfo.Variant].self, from: Data("""
        [{"id": "q4_0", "name": "Q4_0", "bytes": 5582359648, "memoryBytes": 6900000000, "downloaded": false},
         {"id": "q8_0", "name": "Q8_0", "bytes": 9022794944, "memoryBytes": 10400000000, "downloaded": true}]
        """.utf8))
    check(ServerInfo.Variant.recommended(plain, memory: 16 * gib) == "q4_0"
          && ServerInfo.Variant.recommended(plain, memory: 24 * gib) == "q8_0", "settings: the variant without a default")
    check(info.model?.variant == "q8_0" && info.model?.variants?.map(\.id) == ["q4_0", "q8_0"]
          && info.model?.variants?.first?.downloaded == false, "settings: the model's variants")
    let cut = by["maxRecordingSeconds"]!, temperature = by["temperature"]!
    check(cut.value == nil && cut.default == .number(1800) && cut.minExclusive == true
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
      "server": {"port": 8090, "maxRecordingSeconds": 2}
    }

    """
    try text.write(to: file, atomically: true, encoding: .utf8)
    var config = Config.load(from: file)
    var st = SettingStore.state(of: cut, in: config)
    check(st.path == ["server", "maxRecordingSeconds"] && st.value == .number(2) && st.changed,
          "settings: a server's at the server, the config's value in force")
    let topK = try JSONDecoder().decode(SettingInfo.self, from: Data(#"{"key":"topK","owner":"model","group":"sampling","kind":"integer","title":"Top K","default":64,"help":"h"}"#.utf8))
    st = SettingStore.state(of: topK, in: config)
    check(st.path == ["models", "a", "options", "topK"] && st.value == .number(2), "settings: a model's in its options")
    check(!SettingStore.state(of: temperature, in: config).changed,
          "settings: a value equal to the default is no change (temperature 1)")
    let terms = try JSONDecoder().decode(SettingInfo.self, from: Data(#"{"key":"chatTermsTokenBudget","owner":"adapter","group":"context","kind":"integer","title":"Names and terms","default":100,"min":0,"help":"h"}"#.utf8))
    let claude = try JSONDecoder().decode(ServerInfo.Adapter.self, from: Data(#"{"name":"claude","enabled":true,"surfaces":[],"context":{"chatTermsTokenBudget":200}}"#.utf8))
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
    try Config.remove(["server", "maxRecordingSeconds"], in: file)
    config = Config.load(from: file)
    check(config.value(["server", "maxRecordingSeconds"]) == nil && config.value(["server", "port"]) as? Int == 8090,
          "settings: a value taken out")
    st = SettingStore.state(of: cut, in: config)
    check(!st.changed && st.value == .number(1800), "settings: then the server's default")
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
        ("maxRecordingSeconds", "server", "recording", false), ("topK", "model", "sampling", true),
        ("chatTermsTokenBudget", "adapter", "context", true), ("brandNew", "server", "new", false)]
    let general = SettingsLayout.sections(of: .general, serverKeys: keys)
    let model = SettingsLayout.sections(of: .model, serverKeys: keys)
    check(general.contains { $0.section == "Recording" && $0.ids == ["silenceStopSeconds", "maxRecordingSeconds"] }
          && general.contains { $0.section == "Other" && $0.ids == ["brandNew"] }
          && !general.contains { $0.ids.contains("topK") || $0.ids.contains("chatTermsTokenBudget") },
          "settings: the server's settings on General \(general)")
    check(model.first?.section == "Model" && model.last?.section == "Advanced" && model.last?.ids == ["topK"],
          "settings: the model's page, its sampler in Advanced \(model)")
    check(Array(model.map(\.section).prefix(3)) == ["Model", "Quantization", "Prompt"]
          && model.first { $0.section == "Quantization" }?.ids == ["variant"],
          "settings: the model, then its quantizations, then its prompt \(model.map(\.section))")
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

// A section named as its page shows no header: the window's title says it already.
check(SettingsLayout.header("Model", on: .model) == nil && SettingsLayout.header("Prompt", on: .model) == "Prompt"
      && SettingsLayout.header("Language", on: .language) == nil, "settings: no header that repeats the page's title")

// The values both sides use (shared/constants.json); the server's tests check the same file.
do {
    let c = try JSONSerialization.jsonObject(with: Data(contentsOf: repo.appendingPathComponent(
        "shared/constants.json"))) as! [String: Any]
    check(c["interface"] as? Int == protocolInterface && c["configVersion"] as? Int == Config.version
          && c["config"] as? String == Config.defaultFile && c["host"] as? String == Config.defaultHost
          && c["workingPort"] as? Int == Config.defaultPort && c["encoding"] as? String == audioEncoding
          && c["recordings"] as? String == Config.defaultRecordings && c["labeled"] as? String == Config.defaultLabeled
          && c["sampleRate"] as? Int == (examples["info"] as! [String: Any])["sampleRate"] as? Int,
          "shared values: the app's copies")
    check(c["serverLog"] as? String == "~/" + ServerProcess.logInHome, "shared values: the server's log")
    check(c["configCheckSeconds"] as? Double == Tuning.configCheckSeconds
          && Tuning.serverConfigApplySeconds > Tuning.configCheckSeconds, "shared values: the config is looked at as often")
} catch {
    check(false, "shared values: \(error)")
}

// The folders: the server's, from its info, else the config's.
do {
    var info = examples["info"] as! [String: Any]
    var settings = info["settings"] as! [[String: Any]]
    settings.append(["key": "labeled", "owner": "server", "group": "recording", "kind": "folder", "title": "Labels",
                     "default": "~/speech/labeled", "value": "/srv/labeled", "help": ""])
    info["settings"] = settings
    let (recordings, labeled) = Config().folders(try ServerInfo.decode(data(info)))
    check(labeled.path == "/srv/labeled" && recordings.path.hasSuffix("/speech/recordings"),
          "folders: the server's \(recordings.path), \(labeled.path)")
    check(Config().folders(nil).labeled == Config().labeled, "folders: the config's without a server")
} catch {
    check(false, "folders: \(error)")
}

// Uninstall: the app's folders; recordings only from folders that are EchoFox's own.
do {
    let home = FileManager.default.temporaryDirectory.appendingPathComponent("echofox-uninstall-\(getpid())")
    let fm = FileManager.default
    for p in [".echofox", "Library/Logs/EchoFox", "speech/recordings/2026-10-27/x",
              "Documents/notes", "Documents/2026-10-27"] {
        try fm.createDirectory(at: home.appendingPathComponent(p), withIntermediateDirectories: true)
    }
    // The server's logs of the versions before echofox-server, under their old names: in the logs' folder, which goes
    for old in ["gemma-voice.log", "gemma-voice-metrics.jsonl"] {
        fm.createFile(atPath: home.appendingPathComponent("\(LogFolder.inHome)/\(old)").path, contents: Data())
    }
    let rec = home.appendingPathComponent("speech/recordings"), docs = home.appendingPathComponent("Documents")
    let names = { (items: [Uninstall.Item]) in items.map { $0.url.path.replacingOccurrences(of: home.path + "/", with: "") } }
    let without = Uninstall.items(home: home, recordings: rec, labeled: docs, withRecordings: false)
    check(names(without) == [".echofox", "Library/Logs/EchoFox"], "uninstall: what exists of the folders")
    check(["gemma-voice.log", "gemma-voice-metrics.jsonl", "echofox-server.log"].allSatisfy { name in
              without.contains { home.appendingPathComponent("\(LogFolder.inHome)/\(name)").path.hasPrefix($0.url.path + "/") }
          }, "uninstall: the server's logs under their old names and the new one go with the logs' folder")
    let with = Uninstall.items(home: home, recordings: rec, labeled: docs, withRecordings: true)
    check(names(with).suffix(1) == ["speech/recordings"] && with.last?.toTrash == true,
          "uninstall: the recordings to the Trash, not a folder that holds other things: \(names(with))")
    try? fm.removeItem(at: home)
} catch {
    check(false, "uninstall: \(error)")
}

// The bundled server, the app's child process.
do {
    let r = URL(fileURLWithPath: "/Applications/EchoFox.app/Contents/Resources")
    let l = ServerProcess.launch(python: r.appendingPathComponent("python/bin/python3"),
                                 server: r.appendingPathComponent("server"), version: "0.2 (180)")
    check(l.executable.path == "/Applications/EchoFox.app/Contents/Resources/python/bin/python3"
          && l.arguments == ["/Applications/EchoFox.app/Contents/Resources/server/echofox-server.py", "--parent"]
          && l.directory.path == "/Applications/EchoFox.app/Contents/Resources/server",
          "server: the bundled Python runs the bundled server, which ends with the app (--parent)")
    check(l.environment == ["PYTHONDONTWRITEBYTECODE": "1", "ECHOFOX_APP_VERSION": "0.2 (180)"],
          "server: no bytecode written, and the app's version")
    check(ServerProcess.misplaced(app: "/Applications/EchoFox.app", readOnlyVolume: false) == nil
          && ServerProcess.misplaced(app: "/Users/someone/Applications/EchoFox.app", readOnlyVolume: false) == nil,
          "server: started from Applications")
    check(ServerProcess.misplaced(app: "/Volumes/EchoFox/EchoFox.app", readOnlyVolume: true) != nil
          && ServerProcess.misplaced(app: "/private/var/folders/x/T/AppTranslocation/0A1B/d/EchoFox.app", readOnlyVolume: true) != nil
          && ServerProcess.misplaced(app: "/private/var/folders/x/T/AppTranslocation/0A1B/d/EchoFox.app", readOnlyVolume: false) != nil,
          "server: not started from a disk image or App Translocation")
    check(ServerProcess.bundled(resources: URL(fileURLWithPath: "/nowhere")) == nil, "server: none without a bundled one")
    var waits: [Double] = [], w = 0.0
    for _ in 0..<8 { w = ServerProcess.restartDelay(previous: w, ranSeconds: 2); waits.append(w) }
    check(waits == [1, 2, 4, 8, 16, 32, 60, 60], "server: one that ends at once starts again later each time: \(waits)")
    check(ServerProcess.restartDelay(previous: 60, ranSeconds: 300) == 1, "server: one that ran a while starts again at once")
    let home = URL(fileURLWithPath: "/Users/someone")
    let legacy = ServerProcess.legacyRemoval(domain: "gui/501", home: home)
    check(legacy.map(\.command) == [["bootout", "gui/501/echofox.gemma-voice"], ["bootout", "gui/501/echofox.llama-server"]]
          && legacy.map(\.file.path) == ["/Users/someone/Library/LaunchAgents/echofox.gemma-voice.plist",
                                         "/Users/someone/Library/LaunchAgents/echofox.llama-server.plist"],
          "server: the launchd agents of older versions are stopped and removed")
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

// The token estimate and the budget's rule: the server's tests check the same examples (shared/token-examples.json).
do {
    let t = try JSONSerialization.jsonObject(with: Data(contentsOf: repo.appendingPathComponent(
        "shared/token-examples.json"))) as! [String: Any]
    let gemma = TokenEstimate((t["weights"] as! [String: Any])["gemma-4-e4b"] as? [String: Double])
    check(gemma != .fallback, "tokens: the examples' weights")
    for e in t["estimates"] as! [[String: Any]] {
        let text = e["text"] as! String, about = e["about"] as! String, tokens = e["tokens"] as! [String: Int]
        check(TokenEstimate.counts(text) == e["counts"] as! [String: Int],
              "tokens: \(about): the characters by kind \(TokenEstimate.counts(text))")
        check(gemma.count(text) == tokens["gemma-4-e4b"], "tokens: \(about): \(gemma.count(text)) with Gemma's weights")
        check(TokenEstimate(nil).count(text) == tokens["fallback"] && TokenEstimate([:]).count(text) == tokens["fallback"],
              "tokens: \(about): \(TokenEstimate(nil).count(text)) with the fallback")
    }
    for e in t["take"] as! [[String: Any]] {
        var budget = TokenBudget(e["budget"] as? Int), kept = 0
        for cost in e["costs"] as! [Int] {
            if budget.isReached { break }
            kept += 1
            budget.add(cost)
        }
        check(kept == e["kept"] as? Int && budget.used == e["used"] as? Int,
              "budget: \(e["about"] as! String): \(kept) items, \(budget.used) tokens")
    }
    var none = TokenBudget(nil)
    none.add(1_000_000)
    check(!none.isReached, "budget: none is never reached")
} catch {
    check(false, "tokens: \(error)")
}

// The settings side: what each choice of the windows writes (a default takes the key out), the hotkeys' values, the
// words of the settings window, the sidebar's saved row, the adapters' names, and whether the first start opens.
do {
    let info = try ServerInfo.decode(data(examples["info"]!))
    let dir = FileManager.default.temporaryDirectory.appendingPathComponent("echofox-choices-\(getpid())")
    try? FileManager.default.removeItem(at: dir)
    try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    let file = dir.appendingPathComponent("config.json")
    let written = """
    {
      "version": 11,
      "language": "de",
      "microphone": "AirPods-1",
      "dictationKey": "rightShift",
      "adapters": {"telegram": {"enabled": true}, "claude-code": {"enabled": false}},
      "models": {"gemma-e4b": {"variant": "q8_0", "prompt": "mine"}},
      "languages": {"ru": {"fillers": ["э"]}}
    }

    """
    try written.write(to: file, atomically: true, encoding: .utf8)
    let c = Config.load(from: file, systemLanguage: "ru-RU")
    let empty = Config.load(from: dir.appendingPathComponent("not-there.json"), systemLanguage: "ru-RU")
    // A value equal to its default takes the key out, and is no change where the file has none
    check(SettingStore.microphone("builtin", in: c) == .remove(["microphone"])
          && SettingStore.microphone("builtin", in: empty) == nil
          && SettingStore.microphone("system", in: c) == .set(["microphone"], "system")
          && SettingStore.microphone("AirPods-1", in: c) == nil, "choices: the microphone")
    check(SettingStore.language("ru", in: c) == .remove(["language"]) && SettingStore.language("ru", in: empty) == nil
          && SettingStore.language("", in: empty) == .set(["language"], "") && SettingStore.language("de", in: c) == nil,
          "choices: the language, whose default is macOS's")
    check(SettingStore.hotkey(.rightOption, isPrivate: false, in: c) == .remove(["dictationKey"])
          && SettingStore.hotkey(nil, isPrivate: false, in: c) == .set(["dictationKey"], "none")
          && SettingStore.hotkey(.rightCommand, isPrivate: true, in: c) == nil
          && SettingStore.hotkey(.rightOption, isPrivate: true, in: c) == .set(["privateDictationKey"], "rightOption"),
          "choices: the hotkeys, and none")
    check(SettingStore.adapter("claude-code", enabled: false, in: c) == .remove(["adapters", "claude-code", "enabled"])
          && SettingStore.adapter("claude-chat", enabled: false, in: c) == nil
          && SettingStore.adapter("claude-chat", enabled: true, in: c) == .set(["adapters", "claude-chat", "enabled"], true)
          && SettingStore.adapter("telegram", enabled: true, in: c) == nil, "choices: an adapter's switch, off by default")
    let variants = info.model?.variants
    check(SettingStore.variant("q4_0", of: "gemma-e4b", variants: variants, in: c) == .remove(["models", "gemma-e4b", "variant"])
          && SettingStore.variant("q4_0", of: "gemma-e4b", variants: variants, in: empty) == nil
          && SettingStore.variant("q8_0", of: "gemma-e4b", variants: variants, in: empty)
              == .set(["models", "gemma-e4b", "variant"], "q8_0")
          && SettingStore.variant("q4_0", of: "gemma-e4b", variants: nil, in: empty)
              == .set(["models", "gemma-e4b", "variant"], "q4_0"),
          "choices: a variant; the catalog's default is none, and an unknown default writes the value")
    check(SettingStore.model("gemma-e4b", info: info, in: empty) == nil
          && SettingStore.model("other", info: info, in: empty) == .set(["model"], "other")
          && SettingStore.model("gemma-e4b", info: nil, in: empty) == .set(["model"], "gemma-e4b"),
          "choices: the model, whose default is the registry's first")
    let catalog = info.model?.prompt
    check(SettingStore.prompt(catalog ?? "", of: "gemma-e4b", catalog: catalog, in: c) == .remove(["models", "gemma-e4b", "prompt"])
          && SettingStore.prompt("new", of: "gemma-e4b", catalog: catalog, in: c) == .set(["models", "gemma-e4b", "prompt"], "new"),
          "choices: a prompt equal to the catalog's is none")
    let fillers = SettingStore.LanguageList.fillers, notes = SettingStore.LanguageList.notes
    let ruFillers = info.languages.first { $0.code == "ru" }?.fillers ?? []
    check(SettingStore.list(fillers, of: "ru", text: fillers.text(ruFillers), info: info, in: c) == .remove(["languages", "ru", "fillers"])
          && SettingStore.list(fillers, of: "ru", text: "", info: info, in: c) == .set(["languages", "ru", "fillers"], [String]())
          && SettingStore.list(notes, of: "*", text: notes.text(info.commonNotes ?? []), info: info, in: empty) == nil
          && SettingStore.list(fillers, of: "ru", text: "э", info: info, in: c) == nil,
          "choices: a language's list equal to the server's is none; an empty one turns it off")
    check(SettingStore.reset(["models", "gemma-e4b", "prompt"], in: c) == .remove(["models", "gemma-e4b", "prompt"])
          && SettingStore.reset(["model"], in: c) == nil, "choices: a reset only of what the file has")
    // true is not 1: the server reads only a boolean as an adapter's switch
    check(ConfigChange.set(["x"], true) != .set(["x"], 1) && ConfigChange.set(["x"], 1) == .set(["x"], 1.0),
          "choices: a boolean is not a number")
    // The menu's model: the config's, else the registry's first; a model's setting is written there
    let topK = SettingInfo(key: "topK", owner: "model", kind: "integer", title: "Top K", default: .number(64))
    check(SettingStore.menuModel(in: empty, info: info) == "gemma-e4b" && SettingStore.menuModel(in: empty, info: nil) == nil
          && SettingStore.state(of: topK, in: empty, info: info).path == ["models", "gemma-e4b", "options", "topK"]
          && SettingStore.state(of: topK, in: empty).path == nil,
          "choices: the menu's model without a model in the config")
    check(SettingStore.change(.write(.number(40)), of: topK, in: empty, info: info) == .set(["models", "gemma-e4b", "options", "topK"], 40)
          && SettingStore.change(.remove, of: topK, in: empty, info: info) == nil
          && SettingStore.change(.refuse, of: topK, in: empty, info: info) == nil, "choices: a row's edit")

    // Through the store: a default takes the key out of the file; nothing to change writes nothing, and no file is made
    let store = ConfigStore(url: file)
    var logged: [String] = []
    store.log = { logged.append($0) }
    check(store.apply(SettingStore.microphone("builtin", in: store.config), "mic") && store.config.value(["microphone"]) == nil
          && store.config.microphone == "builtin" && logged == ["mic"], "store: the default microphone takes the key out")
    check(store.apply(SettingStore.microphone("builtin", in: store.config), "again") && logged == ["mic"],
          "store: nothing to change writes nothing")
    let none = dir.appendingPathComponent("none/config.json")
    let fresh = ConfigStore(url: none)
    check(fresh.apply(SettingStore.language(fresh.config.systemLanguage, in: fresh.config), "language")
          && !FileManager.default.fileExists(atPath: none.path), "store: the first start's macOS language makes no file")

    // The hotkeys from the file: "none" is off, a value this version does not know is the key's default
    try #"{"dictationKey": "none", "privateDictationKey": "leftFoot"}"#.write(to: file, atomically: true, encoding: .utf8)
    var keys = Config.load(from: file)
    check(keys.dictationKey == nil && keys.privateDictationKey == .rightCommand, "keys: none is off, an unknown key the default")
    try #"{"dictationKey": 5, "privateDictationKey": "rightOption"}"#.write(to: file, atomically: true, encoding: .utf8)
    keys = Config.load(from: file)
    check(keys.dictationKey == .rightOption && keys.privateDictationKey == .rightOption && keys.keysClash,
          "keys: a wrong type is the default; the same key twice is a clash")
    keys.dictationKey = nil
    keys.privateDictationKey = nil
    check(!keys.keysClash && TapKeyChoice.configValue(nil) == "none", "keys: two without a key are no clash")
    let schema = try JSONSerialization.jsonObject(with: Data(contentsOf: repo.appendingPathComponent(
        "shared/config.schema.json"))) as! [String: Any]
    let props = schema["properties"] as! [String: Any]
    for key in ["dictationKey", "privateDictationKey"] {
        let values = (props[key] as? [String: Any])?["enum"] as? [String] ?? []
        check(values == TapKeyChoice.allCases.map(\.rawValue) + [TapKeyChoice.off], "keys: the schema's values of \(key): \(values)")
    }

    // The language's code
    check(Config.languageCode("en-GB") == "en" && Config.languageCode("ru") == "ru" && Config.languageCode("") == ""
          && Config.load(from: none, systemLanguage: "pt-BR").systemLanguage == "pt", "language: the code of a tag")

    // One write path: an edit that JSONEdit cannot make writes the file again from its contents
    try #"{"s": "text", "a": 1}"#.write(to: file, atomically: true, encoding: .utf8)
    try Config.set(["s", "x"], to: 1, in: file)
    var parsed = try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as! [String: Any]
    check(NSDictionary(dictionary: parsed).isEqual(to: ["s": ["x": 1], "a": 1]), "config: a set through a string, written again \(parsed)")
    try #"{"s": "text", "a": 1}"#.write(to: file, atomically: true, encoding: .utf8)
    try Config.remove(["s", "x"], in: file)
    parsed = try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as! [String: Any]
    check(NSDictionary(dictionary: parsed).isEqual(to: ["s": "text", "a": 1]), "config: a removal through a string keeps the rest \(parsed)")
    try? FileManager.default.removeItem(at: dir)

    // The words of the settings window
    let cut = info.settings!.first { $0.key == "maxRecordingSeconds" }!
    check(SettingText.allowedValues(cut) == "Enter a number above 0.", "words: \(SettingText.allowedValues(cut))")
    let range = SettingInfo(key: "k", owner: "server", kind: "integer", title: "K", default: nil, min: 5, max: 30)
    let open = SettingInfo(key: "k", owner: "server", kind: "number", title: "K", default: nil, max: 1, maxExclusive: true)
    check(SettingText.allowedValues(range) == "Enter a whole number from 5 to 30."
          && SettingText.allowedValues(open) == "Enter a number below 1."
          && SettingText.allowedValues(SettingInfo(key: "k", owner: "server", kind: "number", title: "K", default: nil))
              == "Enter a number.", "words: what to enter")
    check(SettingText.value(.number(60)) == "60" && SettingText.value(.number(0.95)) == "0.95"
          && SettingText.value(.bool(true)) == "on" && SettingText.value(nil) == "", "words: a value")
    let budget = info.settings!.first { $0.key == "chatHistoryTokenBudget" }!
    let own = try JSONDecoder().decode(ServerInfo.Adapter.self, from: Data(#"{"name":"telegram","enabled":true,"surfaces":[],"context":{"chatHistoryTokenBudget":600}}"#.utf8))
    let bySelf = SettingStore.state(of: budget, in: Config(), scope: .adapter(own))
    let builtIn = SettingStore.state(of: budget, in: Config(), scope: .adapter(info.adapters.first { $0.name == "telegram" }!))
    check(SettingText.source(bySelf, adapters: info.adapters) == "From the Telegram defaults."
          && SettingText.source(builtIn, adapters: info.adapters) == "The built-in default.",
          "words: where an adapter's value comes from")
    check(gigabytes(5_582_359_648) == "5.6 GB" && gigabytes(0) == "0.0 GB", "words: gigabytes")

    // The adapters' names for people: the manifest's title, else the name with a capital
    check(ServerInfo.adapterTitle("claude-code", in: info.adapters) == "Claude Code"
          && ServerInfo.adapterTitle("telegram", in: info.adapters) == "Telegram"
          && ServerInfo.adapterTitle("my-notes", in: []) == "My-notes", "adapters: names for people")

    // The sidebar's row, as the preferences keep it
    let rows: [SidebarItem] = [.page(.model), .adapter("claude-code")]
    check(rows.map(\.saved) == ["page.model", "adapter.claude-code"]
          && rows.allSatisfy { SidebarItem(saved: $0.saved) == $0 }, "sidebar: saved and read back")
    check(SidebarItem(saved: nil) == nil && SidebarItem(saved: "page.gone") == nil && SidebarItem(saved: "adapter.") == nil
          && SidebarItem(saved: "general") == nil, "sidebar: a form this version does not know")
    check(SidebarItem.adapter("claude-code").title(adapters: info.adapters) == "Claude Code"
          && SidebarItem.adapter("claude-code").title(adapters: []) == "Claude-code"
          && SidebarItem.page(.recordings).title(adapters: []) == "Recordings & Labels", "sidebar: the window's title")
    check(SettingsPage.model.showsServerSettings && !SettingsPage.language.showsServerSettings, "sidebar: the server's pages")

    // The first start: whether its window opens
    let m = info.model  // q8_0 downloaded
    var plain = examples["info"] as! [String: Any], model = plain["model"] as! [String: Any]
    model["variants"] = (model["variants"] as! [[String: Any]]).map { var v = $0; v["downloaded"] = false; return v }
    plain["model"] = model
    let bare = try ServerInfo.decode(data(plain)).model  // nothing downloaded
    check(FirstRun.decide(model: m, shown: false, setupDone: nil, configExisted: false) == .show
          && FirstRun.decide(model: m, shown: false, setupDone: nil, configExisted: true) == .setUpEarlier
          && FirstRun.decide(model: m, shown: false, setupDone: true, configExisted: true) == .none
          && FirstRun.decide(model: m, shown: false, setupDone: false, configExisted: true) == .show
          && FirstRun.decide(model: bare, shown: false, setupDone: true, configExisted: true) == .show
          && FirstRun.decide(model: bare, shown: false, setupDone: nil, configExisted: true) == .show
          && FirstRun.decide(model: bare, shown: true, setupDone: nil, configExisted: false) == .none
          && FirstRun.decide(model: nil, shown: false, setupDone: nil, configExisted: false) == .none,
          "first start: shown until Done, again without a model, an earlier version's setup counts as done")
} catch {
    check(false, "settings side: \(error)")
}

// The app's runtime: the menu bar's icon, the queue of dictations, the hotkeys, the menu's lines, the uninstall's
// order, the clipboard's loan, the logs' folder and the one connection to the server.
do {
    func icon(recording: Bool = false, privateRecording: Bool = false, waiting: Bool = false, accessibility: Bool = true,
              microphone: Bool = true, error: String? = nil, server: Bool = false) -> MenuBarStatus {
        MenuBarStatus.of(recording: recording, privateRecording: privateRecording, waiting: waiting,
                         accessibility: accessibility, microphoneAllowed: microphone, lastError: error, serverProblem: server)
    }
    check(icon() == .fox(.idle), "icon: idle")
    check(icon(recording: true, privateRecording: true, accessibility: false, error: "x") == .fox(.privateDictation)
          && icon(recording: true, waiting: true, server: true) == .fox(.recording), "icon: a recording wins over all")
    check(icon(waiting: true, microphone: false) == .fox(.processing), "icon: the wait for the text wins over a problem")
    check(icon(accessibility: false, microphone: false, error: "x", server: true) == .problem("Accessibility permission needed")
          && icon(microphone: false, error: "x") == .problem("Microphone permission needed")
          && icon(error: "boom", server: true) == .problem("boom")
          && icon(server: true) == .problem("the dictation server does not answer"),
          "icon: the permissions, then the last error, then the server")
}
final class QueuedDictation {}
do {
    var q = DictationQueue<QueuedDictation>()
    let a = QueuedDictation(), b = QueuedDictation(), c = QueuedDictation()
    check(!q.busy, "dictations: none at first")
    q.start(a)
    check(q.current === a && q.busy && !q.changed(a, to: .recording), "dictations: one records")
    check(!q.changed(a, to: .waiting) && q.current == nil && q.waiting.count == 1 && q.waiting[0] === a,
          "dictations: one that stopped waits for its text")
    q.start(b)
    check(!q.changed(b, to: .waiting) && q.waiting.count == 2 && q.waiting[1] === b, "dictations: the next waits after it")
    check(q.changed(b, to: .finished) && q.waiting.count == 1 && q.waiting[0] === a, "dictations: a later one may finish first")
    check(q.changed(a, to: .finished) && !q.busy, "dictations: all finished")
    q.start(c)
    check(q.changed(c, to: .finished) && !q.busy, "dictations: one that ends while it records leaves the queue at once")
}
do {
    let shared = HotkeyAssignment.assign([("dictation", TapKeyChoice.rightOption), ("private", .rightOption)])
    check(shared.map(\.0) == ["dictation"] && shared.first?.1 == .rightOption, "hotkeys: the first action keeps a shared key")
    let one = HotkeyAssignment.assign([("dictation", nil), ("private", TapKeyChoice.rightCommand)])
    check(one.map(\.0) == ["private"] && one.first?.1 == .rightCommand, "hotkeys: an action without a key has none")
    let both = HotkeyAssignment.assign([("dictation", TapKeyChoice.rightOption), ("private", .rightCommand)])
    check(both.map(\.0) == ["dictation", "private"] && both.map(\.1) == [.rightOption, .rightCommand], "hotkeys: two keys")
}
do {
    check(Set(SettingsLayout.menu) == Set(MenuSetting.allCases.map(\.rawValue)),
          "menu: every id of SettingsLayout.menu has a line, and every line a place: \(SettingsLayout.menu)")
    let settings = SettingsLayout.menu.compactMap(MenuSetting.init).map(MenuLine.setting)
    check(MenuLine.all(update: false) == settings + [.separator, .checkForUpdates, .settings, .quit],
          "menu: the settings lines in the layout's order, then the fixed lines")
    check(MenuLine.all(update: true) == [.update, .separator] + MenuLine.all(update: false), "menu: an update's line on top")
}
do {
    // The comparator `{ a, _ in a != inUse }` that came before was no strict weak ordering: these checks failed with it
    check(Uninstall.removalOrder(["a", "b", "c", "d", "e"], inUse: "b") == ["a", "c", "d", "e", "b"]
          && Uninstall.removalOrder(["q4_0", "q8_0"], inUse: "q4_0") == ["q8_0", "q4_0"],
          "uninstall: the variant in use last, the others in their order")
    check(Uninstall.removalOrder(["a", "b"], inUse: nil) == ["a", "b"] && Uninstall.removalOrder([], inUse: "a") == [],
          "uninstall: no variant in use")
    check(ServerProcess.logInHome.hasPrefix(LogFolder.inHome + "/"), "logs: the server's log is in the logs' folder")
}
do {
    // The clipboard's change count: 10 is the speaker's; each write of ours or theirs adds one.
    var loan = ClipboardLoan<String>()
    check(loan.mustSave(changeCount: 10), "clipboard: the first lend saves the speaker's")
    let first = loan.lent(saving: "theirs", changeCount: 11)
    check(!loan.mustSave(changeCount: 11), "clipboard: a lend right after ours keeps what was saved first")
    let second = loan.lent(saving: nil, changeCount: 12)
    check(loan.restore(first, changeCount: 12) == nil, "clipboard: an earlier lend's restore does nothing")
    check(loan.restore(second, changeCount: 12) == "theirs" && loan.restore(second, changeCount: 12) == nil,
          "clipboard: the last lend's restore brings the speaker's back, once")
    let copied = loan.lent(saving: "theirs", changeCount: 21)
    check(loan.restore(copied, changeCount: 22) == nil && loan.saved == nil, "clipboard: the speaker copied meanwhile: theirs stays")
    _ = loan.lent(saving: "old", changeCount: 31)
    check(loan.mustSave(changeCount: 32), "clipboard: the speaker copied between two lends: saved again")
    let after = loan.lent(saving: "new", changeCount: 33)
    check(loan.restore(after, changeCount: 33) == "new", "clipboard: the newer contents come back")
    let kept = loan.lent(saving: "theirs", changeCount: 41)
    loan.kept(changeCount: 42)
    check(loan.restore(kept, changeCount: 42) == nil && loan.mustSave(changeCount: 42), "clipboard: kept text stays")
}
do {
    check(ServerConnection.text(of: .string("a")) == "a" && ServerConnection.text(of: .data(Data("б".utf8))) == "б",
          "connection: a text frame as it is, a binary frame as UTF-8")
    // A WebSocket server on the loopback: it answers a text frame with that text and a binary frame, then closes.
    let queue = DispatchQueue(label: "echofox-tests.server")
    let parameters = NWParameters.tcp
    parameters.requiredInterfaceType = .loopback
    parameters.defaultProtocolStack.applicationProtocols.insert(NWProtocolWebSocket.Options(), at: 0)
    let listener = try NWListener(using: parameters)
    func frame(_ opcode: NWProtocolWebSocket.Opcode) -> NWConnection.ContentContext {
        NWConnection.ContentContext(identifier: "frame", metadata: [NWProtocolWebSocket.Metadata(opcode: opcode)])
    }
    listener.newConnectionHandler = { c in
        c.start(queue: queue)
        c.receiveMessage { data, _, _, _ in
            c.send(content: data, contentContext: frame(.text), completion: .contentProcessed { _ in })
            c.send(content: Data(#"{"type":"done"}"#.utf8), contentContext: frame(.binary), completion: .contentProcessed { _ in
                queue.asyncAfter(deadline: .now() + 0.2) { c.cancel() }
            })
        }
    }
    var port: UInt16?
    listener.stateUpdateHandler = { if case .ready = $0 { DispatchQueue.main.async { port = listener.port?.rawValue } } }
    listener.start(queue: queue)
    func spin(seconds: Double, until done: () -> Bool) {
        let end = Date().addingTimeInterval(seconds)
        while !done(), Date() < end { RunLoop.main.run(mode: .default, before: Date().addingTimeInterval(0.01)) }
    }
    spin(seconds: 5) { port != nil }
    let url = URL(string: "ws://127.0.0.1:\(port ?? 0)")!
    func describe(_ e: ServerConnection.Event) -> String {
        switch e {
        case .text(let s): return s
        case .ended: return "ended"
        }
    }
    var events: [String] = []
    let whole = ServerConnection(url: url)
    whole.open { events.append(describe($0)) }
    whole.send(#"{"type":"info"}"#)
    spin(seconds: 5) { events.last == "ended" }
    check(events == [#"{"type":"info"}"#, #"{"type":"done"}"#, "ended"],
          "connection: the frames as text in order, then the end: \(events)")
    var closed: [String] = []
    let early = ServerConnection(url: url)
    early.open { e in
        closed.append(describe(e))
        early.close()
    }
    early.send("first")
    spin(seconds: 1) { false }
    check(closed == ["first"], "connection: no event after close(): \(closed)")
    listener.cancel()
} catch {
    check(false, "connection: \(error)")
}

print(failures == 0 ? "echofox-tests: all checks pass" : "echofox-tests: \(failures) failed")
exit(failures == 0 ? 0 : 1)
