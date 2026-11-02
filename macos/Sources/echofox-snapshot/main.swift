// echofox-snapshot: waits a few seconds (time to put the cursor in an input box), then takes the focus snapshot with the
// app's own code, in its two phases, and prints {"identity": …, "content": …} as JSON: the identity that the start
// message carries, and the content message that answers a read request (docs/reference/6-protocol.md). Recorded
// snapshots for the adapters' tests come from here.
// Usage: echofox-snapshot [--delay SECONDS] [--app BUNDLE_ID] [--electron] [--out FILE]
//                         [--read FILE | [--outline] [--outline-skip NAMES] [--lists] [--processes] [--budget TOKENS]
//                                        [--weights JSON]]
// --app: that running app instead of the frontmost one, with no delay. --electron: ask the app for its accessibility
// tree first (ElectronTree), as the app does for a surface with treeOnRequest; without it, no attribute of the app is
// set.
// --read: a read message as the server sends it ({"type": "read", "surfaces": […], "tokenWeights": …}), executed as
// the app executes it. Or flags that build a read of one surface, named "snapshot": --outline, the tree of the focused
// web page or window, without the children of the elements named in --outline-skip (comma-separated AX roles or DOM
// classes); --lists, the rows of the window's lists; --processes, the app's child processes; --budget, read the
// outline and the lists up to this many tokens (without it, all of them), counted with --weights, the model's
// tokenWeights (without them, a token per 3.4 characters). Without --read and these flags, only the identity.
// A snapshot with an outline or lists holds the window's text: keep it private.
import AppKit
import EchoFoxCore
import FocusSnapshot
import Foundation

func fail(_ message: String, code: Int32 = 1) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(code)
}

let usage = "usage: echofox-snapshot [--delay SECONDS] [--app BUNDLE_ID] [--electron] [--out FILE] "
    + "[--read FILE | [--outline] [--outline-skip NAMES] [--lists] [--processes] [--budget TOKENS] [--weights JSON]]"
var delay = 3.0, out: String?, electron = false, bundle: String?, readFile: String?
var outline = false, skip: [String]?, lists = false, processes = false, budget: Int?, weights: [String: Double]?
var args = CommandLine.arguments.dropFirst().makeIterator()
while let a = args.next() {
    switch a {
    case "--delay": delay = Double(args.next() ?? "") ?? delay
    case "--out": out = args.next()
    case "--electron": electron = true
    case "--app": bundle = args.next()
    case "--read": readFile = args.next()
    case "--outline": outline = true
    case "--outline-skip": skip = (args.next() ?? "").split(separator: ",").map { String($0) }
    case "--lists": lists = true
    case "--processes": processes = true
    case "--budget": budget = Int(args.next() ?? "")
    case "--weights":
        weights = (try? JSONSerialization.jsonObject(with: Data((args.next() ?? "").utf8))) as? [String: Double]
    default: fail(usage, code: 2)
    }
}

// The read request: the server's message from a file, or one surface from the flags
var request: ReadRequest?
if let readFile {
    guard let data = FileManager.default.contents(atPath: readFile),
          case .read(let r)? = ServerMessage.parse(String(decoding: data, as: UTF8.self)) else {
        fail("\(readFile) is no read message")
    }
    request = r
} else if outline || lists || processes {
    request = ReadRequest(surfaces: [.init(surface: "snapshot",
                                           outline: outline ? .init(skip: skip, budget: budget) : nil,
                                           lists: lists ? .init(budget: budget) : nil,
                                           processes: processes ? .init() : nil)],
                          tokenWeights: weights)
}

var app: NSRunningApplication?
if let bundle {
    guard let found = NSRunningApplication.runningApplications(withBundleIdentifier: bundle).first else {
        fail("\(bundle) is not running")
    }
    app = found
} else {
    FileHandle.standardError.write("Put the cursor in an input box: the snapshot is taken in \(delay) s.\n".data(using: .utf8)!)
    Thread.sleep(forTimeInterval: delay)
}
let capture = FocusSnapshot.capture(identity: true, enableElectron: electron, of: app)
if !capture.trusted {
    FileHandle.standardError.write("This process has no Accessibility permission: the identity has the app only.\n"
        .data(using: .utf8)!)
}
var result: [String: Any] = ["identity": capture.identity ?? [:]]
if let request {
    let started = Date()
    let tokens = TokenEstimate(request.tokenWeights)
    var surfaces: [String: [String: Any]] = [:]
    for s in request.surfaces { surfaces[s.surface] = FocusSnapshot.read(s, of: capture, tokens: tokens) }
    let message = ClientMessage.content(surfaces: surfaces, tookMs: Int(Date().timeIntervalSince(started) * 1000))
    result["content"] = try JSONSerialization.jsonObject(with: Data(message.utf8))
}
let data = try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
if let out { try data.write(to: URL(fileURLWithPath: out)) } else { FileHandle.standardOutput.write(data + "\n".data(using: .utf8)!) }
