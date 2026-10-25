// The app's log, ~/Library/Logs/EchoFox/app.log. It never holds the dictated text, only its length.
import Foundation

enum Log {
    static let folder = "Library/Logs/EchoFox"  // the server's logs are there too (server/constants.py LOGS)
    static let url = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("\(folder)/app.log")
    private static let queue = DispatchQueue(label: "echofox.log")
    private static let stamp: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd HH:mm:ss.SSS"
        return f
    }()

    static func write(_ line: String) {
        let now = Date()
        queue.async {
            let text = "\(stamp.string(from: now)) \(line)\n"
            try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            if let h = try? FileHandle(forWritingTo: url) {
                h.seekToEndOfFile()
                h.write(Data(text.utf8))
                try? h.close()
            } else {
                try? Data(text.utf8).write(to: url)
            }
        }
    }
}
