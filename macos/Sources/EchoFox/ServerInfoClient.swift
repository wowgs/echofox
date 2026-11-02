// The info client: what the dictation server tells about itself (ServerInfo): its audio format, its wait for the
// text, the longest recording, and its adapters (which apps to take the full focus snapshot of, which to build the
// tree of). One request is one ServerConnection with the info message and the server's one answer. Asked at the
// start, again after a failure, when it is older than Tuning.serverInfoMaxAgeSeconds at an app switch, and every
// Tuning.serverStatusPollSeconds while the settings window shows the server's state. onChange is called only when
// the info or the problem changed. Everything runs on the main thread.
import Foundation
import EchoFoxCore

final class ServerInfoClient {
    private(set) var info: ServerInfo?
    private(set) var problem: String?
    private var asked: Date?
    /// The request that runs now, or nil.
    private var connection: ServerConnection?
    var onChange: () -> Void = {}

    func refresh(_ url: URL, ifOlderThan age: TimeInterval = 0) {
        if connection != nil { return }
        if let a = asked, info != nil, Date().timeIntervalSince(a) < age { return }
        asked = Date()
        let c = ServerConnection(url: url)
        connection = c
        let timeout = DispatchWorkItem { [weak self] in self?.answered(nil, url) }
        DispatchQueue.main.asyncAfter(deadline: .now() + Tuning.serverInfoTimeoutSeconds, execute: timeout)
        c.open { [weak self] event in
            timeout.cancel()
            if case .text(let s) = event { self?.answered(s, url) } else { self?.answered(nil, url) }
        }
        c.send(ClientMessage.info)
    }

    /// The server's answer, or nil: no answer in time, or the connection ended.
    private func answered(_ text: String?, _ url: URL) {
        connection?.close()
        connection = nil
        let before = (info, problem)
        defer { if before.0 != info || before.1 != problem { onChange() } }
        do {
            guard let text else { throw MessageError("the server at \(url.absoluteString) does not answer") }
            let new = try ServerInfo.decode(Data(text.utf8))
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
