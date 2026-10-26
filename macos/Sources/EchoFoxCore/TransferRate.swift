// The speed of a download and the time it has left, from the progress the server sends (bytes so far, every 0.5 s:
// server/variants.py, DOWNLOAD_PROGRESS_S). The speed is over the last few seconds, so that it follows the network
// without jumping with each message.
import Foundation

public struct TransferRate {
    /// How far back the speed looks, in seconds.
    public static let window: TimeInterval = 5
    private var samples: [(time: TimeInterval, bytes: Double)] = []

    public init() {}

    /// A progress message: the bytes so far, at a time in seconds.
    public mutating func add(bytes: Double, at time: TimeInterval) {
        if let last = samples.last, bytes < last.bytes { samples.removeAll() }  // another download started
        samples.append((time, bytes))
        while let first = samples.first, time - first.time > Self.window, samples.count > 2 { samples.removeFirst() }
    }

    /// Bytes a second over the window, once it spans a second; nil before.
    public var bytesPerSecond: Double? {
        guard let first = samples.first, let last = samples.last, last.time - first.time >= 1 else { return nil }
        return (last.bytes - first.bytes) / (last.time - first.time)
    }

    /// The seconds left until `total`, at the current speed; nil while the speed is not known or is 0.
    public func secondsLeft(total: Double) -> Double? {
        guard let speed = bytesPerSecond, speed > 0, let bytes = samples.last?.bytes else { return nil }
        return max(0, total - bytes) / speed
    }

    /// "74 MB/s", "4.2 MB/s" (1 MB = 10⁶ bytes, as the sizes in GB).
    public static func speed(_ bytesPerSecond: Double) -> String {
        let mb = bytesPerSecond / 1e6
        return mb >= 10 ? "\(Int(mb.rounded())) MB/s" : String(format: "%.1f MB/s", mb)
    }

    /// "less than a minute left", "about 4 min left", "about 1 h 20 min left".
    public static func left(_ seconds: Double) -> String {
        if seconds < 60 { return "less than a minute left" }
        let minutes = Int((seconds / 60).rounded())
        return minutes < 60 ? "about \(minutes) min left" : "about \(minutes / 60) h \(minutes % 60) min left"
    }
}
