// What the dictation server tells about itself (ServerInfo): its audio format, its wait for the text, the longest
// recording, and its adapters (which apps to take the full focus snapshot of, which to build the tree of). Asked at
// the start, again after a failure, when it is older than Tuning.serverInfoMaxAgeSeconds at an app switch, and every
// Tuning.serverStatusPollSeconds while the settings window shows the server's state. onChange is called only when
// the info or the problem changed.
import Foundation
import LocalVoiceCore

final class Server {
    private(set) var info: ServerInfo?
    private(set) var problem: String?
    private var asked: Date?
    private var asking = false
    var onChange: () -> Void = {}

    func refresh(_ url: URL, ifOlderThan age: TimeInterval = 0) {
        if asking { return }
        if let a = asked, info != nil, Date().timeIntervalSince(a) < age { return }
        asking = true
        asked = Date()
        let task = URLSession.shared.webSocketTask(with: url)
        task.resume()
        task.send(.string(ClientMessage.info)) { _ in }
        let timeout = DispatchWorkItem { task.cancel(with: .goingAway, reason: nil) }
        DispatchQueue.main.asyncAfter(deadline: .now() + Tuning.serverInfoTimeoutSeconds, execute: timeout)
        task.receive { [weak self] result in
            timeout.cancel()
            task.cancel(with: .normalClosure, reason: nil)
            DispatchQueue.main.async { self?.received(result, url) }
        }
    }

    private func received(_ result: Result<URLSessionWebSocketTask.Message, Error>, _ url: URL) {
        asking = false
        let before = (info, problem)
        defer { if before.0 != info || before.1 != problem { onChange() } }
        do {
            guard case .success(let m) = result else {
                throw MessageError("the server at \(url.absoluteString) does not answer")
            }
            let data: Data
            switch m {
            case .string(let s): data = Data(s.utf8)
            case .data(let d): data = d
            @unknown default: throw MessageError("an answer of an unknown kind")
            }
            let new = try ServerInfo.decode(data)
            if new != info {
                Log.write("server: " + new.adapters.map { "\($0.name) \($0.enabled ? "on" : "off")\($0.error.map { " (\($0))" } ?? "")" }
                    .joined(separator: ", "))
            }
            info = new
            problem = nil
        } catch {
            if problem == nil { Log.write("server info: \(error)") }
            problem = "\(error)"
            // Until the server answers, ask again: the app may start before the server.
            DispatchQueue.main.asyncAfter(deadline: .now() + Tuning.serverInfoRetrySeconds) { [weak self] in
                self?.refresh(url)
            }
        }
    }
}
