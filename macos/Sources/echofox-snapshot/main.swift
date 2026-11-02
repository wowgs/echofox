// echofox-snapshot: waits a few seconds (time to put the cursor in an input box), then prints the focus snapshot as JSON.
// Usage: echofox-snapshot [--delay SECONDS] [--out FILE] [--electron] [--lists] [--outline] [--outline-skip NAMES]
//                         [--budget TOKENS] [--weights JSON] [--app BUNDLE_ID]
// --electron: ask an Electron app for its accessibility tree (ElectronTree), as the app does for the electronApps of
// an enabled adapter; without it, no attribute of the app is set.
// --lists: the rows of the window's lists too (what an adapter with "screen": ["lists"] gets); --outline: the tree of
// the focused web page or window (what "screen": ["outline"] gets); --outline-skip: the comma-separated names of a
// manifest's outlineSkip, whose elements go in without their children, as the app takes them; --app: that running app
// instead of the frontmost one, with no delay; --budget: read the lists and the outline up to this many tokens, as
// the app does with an adapter's chat budget (without it, all of them), counted with --weights, the model's
// tokenWeights from the server's info (without it, a token per 3.4 characters). A snapshot with --lists or --outline holds the window's text: keep it private.
import AppKit
import FocusSnapshot
import Foundation

var delay = 3.0, out: String?, electron = false, lists = false, outline = false, skip: Set<String> = [], bundle: String?
var budget: Int?, tokens = TokenEstimate.fallback
var args = CommandLine.arguments.dropFirst().makeIterator()
while let a = args.next() {
    switch a {
    case "--delay": delay = Double(args.next() ?? "") ?? delay
    case "--out": out = args.next()
    case "--electron": electron = true
    case "--lists": lists = true
    case "--outline": outline = true
    case "--outline-skip": skip = Set((args.next() ?? "").split(separator: ",").map { String($0) })
    case "--budget": budget = Int(args.next() ?? "")
    case "--weights":
        tokens = TokenEstimate((try? JSONSerialization.jsonObject(with: Data((args.next() ?? "").utf8))) as? [String: Double])
    case "--app": bundle = args.next()
    default:
        FileHandle.standardError.write("usage: echofox-snapshot [--delay SECONDS] [--out FILE] [--electron] [--lists] [--outline] [--outline-skip NAMES] [--budget TOKENS] [--weights JSON] [--app BUNDLE_ID]\n"
            .data(using: .utf8)!)
        exit(2)
    }
}
var app: NSRunningApplication?
if let bundle {
    guard let found = NSRunningApplication.runningApplications(withBundleIdentifier: bundle).first else {
        FileHandle.standardError.write("\(bundle) is not running\n".data(using: .utf8)!)
        exit(1)
    }
    app = found
} else {
    FileHandle.standardError.write("Put the cursor in an input box: the snapshot is taken in \(delay) s.\n".data(using: .utf8)!)
    Thread.sleep(forTimeInterval: delay)
}
let data = try JSONSerialization.data(withJSONObject: FocusSnapshot.take(enableElectron: electron, lists: lists, outline: outline,
                                                                         outlineSkip: skip, screenBudget: budget,
                                                                         tokens: tokens, of: app),
                                      options: [.prettyPrinted, .sortedKeys])
if let out = out { try data.write(to: URL(fileURLWithPath: out)) } else { FileHandle.standardOutput.write(data + "\n".data(using: .utf8)!) }
