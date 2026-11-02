// One download or removal of a model variant on the dictation server (docs/reference/6-protocol.md): one WebSocket
// connection with one message, then the server's progress until it ends. The server does the work; closing this
// connection does not stop a download, and a cancel message does.
import Foundation
import EchoFoxCore

final class ModelJob {
    private(set) var bytes = 0.0, total = 0.0
    private(set) var finished = false, error: String?
    /// The download's speed and the time it has left, from the progress messages.
    private(set) var rate = TransferRate()
    var onChange: () -> Void = {}

    private let connection: ServerConnection
    private let message: String

    init(url: URL, message: String) {
        connection = ServerConnection(url: url)
        self.message = message
    }

    func start() {
        connection.open { [weak self] event in
            switch event {
            case .text(let s): self?.handle(s)
            case .ended: self?.end(error: "the dictation server closed the connection")
            }
        }
        connection.send(message) { [weak self] e in self?.end(error: e.localizedDescription) }
    }

    func cancel() { connection.send(ClientMessage.cancel) }

    private func handle(_ s: String) {
        switch ServerMessage.parse(s) {
        case let .progress(b, t)?:
            (bytes, total) = (b, t)
            rate.add(bytes: b, at: ProcessInfo.processInfo.systemUptime)
            onChange()
        case .downloaded?, .removed?: end(error: nil)
        case let .error(e)?: end(error: e)
        default: break
        }
    }

    /// "2.1 GB of 9.0 GB, 74 MB/s, about 2 min left"; the speed and the time once they are known.
    var status: String {
        var s = "\(gigabytes(bytes)) of \(gigabytes(total))"
        if let speed = rate.bytesPerSecond, speed > 0 {
            s += ", \(TransferRate.speed(speed))"
            if let left = rate.secondsLeft(total: total) { s += ", \(TransferRate.left(left))" }
        }
        return s
    }

    private func end(error: String?) {
        guard !finished else { return }
        finished = true
        self.error = error
        connection.close()
        onChange()
    }
}
