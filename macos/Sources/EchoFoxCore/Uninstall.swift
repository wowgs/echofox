// What "Uninstall EchoFox…" removes (docs/reference/4-app.md, "Uninstall"), besides the models, which the dictation
// server removes first because it knows their files (a models folder of the user's own may hold other files): the
// app's folders, caches and logs, and, if asked, the recordings and the labels, which go to the
// Trash, and only when the folder is EchoFox's own (day folders and nothing else), so that a folder the user chose
// for other things too is never taken.
import Foundation

public enum Uninstall {
    public struct Item: Equatable {
        public let url: URL
        /// To the Trash (the user's own data), else deleted.
        public let toTrash: Bool
    }

    public static let bundleId = "uk.wowgs.echofox"

    /// The items that exist on this Mac, in the order they go.
    public static func items(home: URL, recordings: URL, labeled: URL, withRecordings: Bool) -> [Item] {
        var out: [Item] = []
        for p in [".echofox", "Library/Application Support/EchoFox", "Library/Logs/EchoFox",
                  "Library/Caches/\(bundleId)", "Library/HTTPStorages/\(bundleId)"] {
            out.append(Item(url: home.appendingPathComponent(p), toTrash: false))
        }
        if withRecordings {
            out += [recordings, labeled].filter(isOwnFolder).map { Item(url: $0, toTrash: true) }
        }
        return out.filter { FileManager.default.fileExists(atPath: $0.url.path) }
    }

    /// Whether a recordings or labels folder holds only what EchoFox writes there: folders named by day
    /// (2026-10-27) and hidden files.
    public static func isOwnFolder(_ url: URL) -> Bool {
        guard let names = try? FileManager.default.contentsOfDirectory(atPath: url.path) else { return false }
        return names.allSatisfy { $0.hasPrefix(".") || $0.range(of: #"^\d{4}-\d{2}-\d{2}$"#, options: .regularExpression) != nil }
    }
}
