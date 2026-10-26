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

    private let task: URLSessionWebSocketTask
    private let message: String

    init(url: URL, message: String) {
        task = URLSession.shared.webSocketTask(with: url)
        self.message = message
    }

    func start() {
        task.resume()
        task.send(.string(message)) { [weak self] e in
            if let e { DispatchQueue.main.async { self?.end(error: "\(e.localizedDescription)") } }
        }
        receive()
    }

    func cancel() { task.send(.string(ClientMessage.cancel)) { _ in } }

    private func receive() {
        task.receive { [weak self] result in
            DispatchQueue.main.async {
                guard let self, !self.finished else { return }
                switch result {
                case let .success(.string(s)): self.handle(s)
                case let .success(.data(d)): self.handle(String(decoding: d, as: UTF8.self))
                case .success: break
                case .failure: self.end(error: "the dictation server closed the connection")
                }
                if !self.finished { self.receive() }
            }
        }
    }

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
        task.cancel(with: .normalClosure, reason: nil)
        onChange()
    }
}
