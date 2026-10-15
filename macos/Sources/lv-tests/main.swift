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
try Config.choose(model: "b", in: file)
let after = try String(contentsOf: file, encoding: .utf8)
check(after == text.replacingOccurrences(of: #""model": "a""#, with: #""model": "b""#), "config: only the model changed")
c = Config.load(from: file)
check(c.model == "b", "config: the new model reads back")
try #"{"version": 2}"#.write(to: file, atomically: true, encoding: .utf8)
check(Config.load(from: file).error != nil, "config: another version is an error")
check(Config.load(from: dir.appendingPathComponent("none.json"), systemLanguage: "de-DE").language == "de",
      "config: no file: the system's language")
try? FileManager.default.removeItem(at: dir)

print(failures == 0 ? "lv-tests: all checks pass" : "lv-tests: \(failures) failed")
exit(failures == 0 ? 0 : 1)
