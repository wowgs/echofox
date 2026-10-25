// echofox-snapshot: waits a few seconds (time to put the cursor in an input box), then prints the focus snapshot as JSON.
// Usage: echofox-snapshot [--delay SECONDS] [--out FILE] [--lists] [--outline] [--app BUNDLE_ID]
// --lists: the rows of the window's lists too (what an adapter with "screen": ["lists"] gets); --outline: the tree of
// the focused web page or window (what "screen": ["outline"] gets); --app: that running app instead of the frontmost
// one, with no delay. A snapshot with --lists or --outline holds the window's text: keep it private.
import AppKit
import FocusSnapshot
import Foundation

var delay = 3.0, out: String?, lists = false, outline = false, bundle: String?
var args = CommandLine.arguments.dropFirst().makeIterator()
while let a = args.next() {
    switch a {
    case "--delay": delay = Double(args.next() ?? "") ?? delay
    case "--out": out = args.next()
    case "--lists": lists = true
    case "--outline": outline = true
    case "--app": bundle = args.next()
    default:
        FileHandle.standardError.write("usage: echofox-snapshot [--delay SECONDS] [--out FILE] [--lists] [--outline] [--app BUNDLE_ID]\n"
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
let data = try JSONSerialization.data(withJSONObject: FocusSnapshot.take(lists: lists, outline: outline, of: app),
                                      options: [.prettyPrinted, .sortedKeys])
if let out = out { try data.write(to: URL(fileURLWithPath: out)) } else { FileHandle.standardOutput.write(data + "\n".data(using: .utf8)!) }
