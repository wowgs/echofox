// lv-snapshot: waits a few seconds (time to put the cursor in an input box), then prints the focus snapshot as JSON.
// Usage: lv-snapshot [--delay SECONDS] [--out FILE]
import FocusSnapshot
import Foundation

var delay = 3.0, out: String?
var args = CommandLine.arguments.dropFirst().makeIterator()
while let a = args.next() {
    switch a {
    case "--delay": delay = Double(args.next() ?? "") ?? delay
    case "--out": out = args.next()
    default:
        FileHandle.standardError.write("usage: lv-snapshot [--delay SECONDS] [--out FILE]\n".data(using: .utf8)!)
        exit(2)
    }
}
FileHandle.standardError.write("Put the cursor in an input box: the snapshot is taken in \(delay) s.\n".data(using: .utf8)!)
Thread.sleep(forTimeInterval: delay)
let data = try JSONSerialization.data(withJSONObject: FocusSnapshot.take(), options: [.prettyPrinted, .sortedKeys])
if let out = out { try data.write(to: URL(fileURLWithPath: out)) } else { FileHandle.standardOutput.write(data + "\n".data(using: .utf8)!) }
