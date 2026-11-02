// One WebSocket connection to the dictation server (docs/reference/6-protocol.md), the one way the app talks to it:
// the info client, a dictation and a model's download or removal each open one. The server sends JSON as text
// frames; a binary frame is read as UTF-8 text too, so every owner gets the same strings for ServerMessage.parse and
// ServerInfo.decode. The events come on the main thread, in order, until the connection ends or its owner closes it;
// after close() none comes, so an owner that closed needs no guard of its own.
import Foundation

public final class ServerConnection {
    public enum Event {
        /// A frame from the server, as text.
        case text(String)
        /// The connection ended without close(): the server closed it, or it never opened. The last event.
        case ended(Error)
    }

    private let task: URLSessionWebSocketTask
    private var closed = false

    public init(url: URL) {
        task = URLSession.shared.webSocketTask(with: url)
    }

    /// Opens the connection; `onEvent` gets each event on the main thread.
    public func open(_ onEvent: @escaping (Event) -> Void) {
        task.resume()
        receive(onEvent)
    }

    /// Sends a text frame (a JSON message). `failed`, if given, gets the error on the main thread, also after close().
    public func send(_ text: String, failed: ((Error) -> Void)? = nil) {
        send(.string(text), failed)
    }

    /// Sends a binary frame (audio).
    public func send(_ data: Data, failed: ((Error) -> Void)? = nil) {
        send(.data(data), failed)
    }

    /// Closes the connection; on the main thread. No event comes after it.
    public func close() {
        closed = true
        task.cancel(with: .normalClosure, reason: nil)
    }

    /// A frame as text: a text frame as it is, a binary frame read as UTF-8.
    public static func text(of message: URLSessionWebSocketTask.Message) -> String? {
        switch message {
        case .string(let s): return s
        case .data(let d): return String(decoding: d, as: UTF8.self)
        @unknown default: return nil
        }
    }

    private func send(_ message: URLSessionWebSocketTask.Message, _ failed: ((Error) -> Void)?) {
        task.send(message) { error in
            guard let error, let failed else { return }
            DispatchQueue.main.async { failed(error) }
        }
    }

    private func receive(_ onEvent: @escaping (Event) -> Void) {
        task.receive { [weak self] result in
            DispatchQueue.main.async {
                guard let self, !self.closed else { return }
                switch result {
                case .success(let m):
                    if let s = Self.text(of: m) { onEvent(.text(s)) }
                    if !self.closed { self.receive(onEvent) }
                case .failure(let e):
                    self.closed = true
                    onEvent(.ended(e))
                }
            }
        }
    }
}
