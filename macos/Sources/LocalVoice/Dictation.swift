// One dictation: the focus snapshot, the microphone, and one WebSocket to the dictation server, which speaks the
// protocol in the README ("The protocol"). Sending goes through one serial queue, so the start message (which waits for
// the snapshot) goes first and the audio and the stop follow in order. Everything else runs on the main thread.
import FocusSnapshot
import Foundation

final class Dictation {
    enum Phase { case recording, waiting, finished }
    static let doneTimeout: TimeInterval = 180
    static let client = "local-voice-mac"

    private(set) var phase = Phase.recording
    private(set) var texts: [String] = []
    private(set) var errors: [String] = []
    private(set) var capture: FocusSnapshot.Capture?
    var text: String { texts.joined(separator: " ") }
    var onPhase: (Dictation) -> Void = { _ in }

    private let config: Config
    private let queue = DispatchQueue(label: "local-voice.dictation.send")
    private let recorder = Recorder()
    private var task: URLSessionWebSocketTask?
    private var lastSpeech = Date()
    private var silenceTimer: Timer?
    private var doneTimer: Timer?
    private var sendFailed = false
    let started = Date()

    private let full: Bool, tree: Bool

    /// `full`: an enabled adapter reads the frontmost app, so the snapshot has its window, ancestors and processes.
    /// `tree`: the app is an Electron app whose tree an enabled adapter needs.
    init(config: Config, full: Bool, tree: Bool) {
        self.config = config
        self.full = full
        self.tree = tree
    }

    func start() throws {
        let task = URLSession.shared.webSocketTask(with: config.serverURL)
        self.task = task
        task.resume()
        receive()
        let config = self.config, full = self.full, tree = self.tree
        queue.async { [weak self] in
            let capture = FocusSnapshot.capture(full: full, enableElectron: tree)
            DispatchQueue.main.async { self?.capture = capture }
            Log.write("snapshot: app \(capture.snapshot["app"].flatMap { ($0 as? [String: Any])?["bundleId"] } ?? "none"), "
                      + "focused \(capture.focused != nil), web area \(capture.snapshot["webArea"] != nil), "
                      + "\(capture.snapshot["tookMs"] ?? "?") ms")
            var start: [String: Any] = ["type": "start", "sampleRate": 16000, "encoding": "pcm_s16le",
                                        "client": Dictation.client, "language": config.language,
                                        "snapshot": capture.snapshot]
            if let m = config.model { start["model"] = m }
            self?.send(json: start)
        }
        do {
            try recorder.start { [weak self] pcm in
                self?.queue.async { self?.send(.data(pcm)) }
            }
        } catch {
            finish(error: "microphone: \(error.localizedDescription)")
            throw error
        }
        silenceTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in self?.checkSilence() }
    }

    /// Ends the recording; the text follows. reason: "user", "silence", "max_duration" or "error".
    func stop(_ reason: String) {
        guard phase == .recording else { return }
        phase = .waiting
        recorder.stop()
        silenceTimer?.invalidate()
        queue.async { [weak self] in self?.send(json: ["type": "stop", "reason": reason]) }
        doneTimer = Timer.scheduledTimer(withTimeInterval: Dictation.doneTimeout, repeats: false) { [weak self] _ in
            self?.finish(error: "the server sent no end of the text in \(Int(Dictation.doneTimeout)) s")
        }
        Log.write("stop: \(reason), \(String(format: "%.1f", Date().timeIntervalSince(started))) s")
        onPhase(self)
    }

    private func checkSilence() {
        guard phase == .recording, config.silenceStopSeconds > 0,
              Date().timeIntervalSince(lastSpeech) >= config.silenceStopSeconds else { return }
        stop("silence")
    }

    private func finish(error: String?) {
        guard phase != .finished else { return }
        if let error { errors.append(error) }
        phase = .finished
        recorder.stop()
        silenceTimer?.invalidate()
        doneTimer?.invalidate()
        task?.cancel(with: .normalClosure, reason: nil)
        onPhase(self)
    }

    // MARK: The connection

    private func send(json: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: json),
              let s = String(data: data, encoding: .utf8) else { return }
        send(.string(s))
    }

    private func send(_ message: URLSessionWebSocketTask.Message) {
        task?.send(message) { [weak self] error in
            guard let error, let self, !self.sendFailed else { return }
            self.sendFailed = true
            Log.write("send failed: \(error.localizedDescription)")
        }
    }

    private func receive() {
        task?.receive { [weak self] result in
            DispatchQueue.main.async { self?.received(result) }
        }
    }

    private func received(_ result: Result<URLSessionWebSocketTask.Message, Error>) {
        guard phase != .finished else { return }
        switch result {
        case .failure(let error):
            finish(error: "the dictation server at \(config.serverURL.absoluteString): \(error.localizedDescription)")
            return
        case .success(.string(let s)):
            handle(s)
        case .success(.data(let d)):
            handle(String(decoding: d, as: UTF8.self))
        case .success:
            break
        }
        if phase != .finished { receive() }
    }

    private func handle(_ message: String) {
        guard let m = (try? JSONSerialization.jsonObject(with: Data(message.utf8))) as? [String: Any] else { return }
        switch m["type"] as? String {
        case "speech":
            lastSpeech = Date()
        case "text":
            if let t = m["text"] as? String, !t.isEmpty { texts.append(t) }
        case "error":
            errors.append(m["message"] as? String ?? "error")
            Log.write("server error: \(m["message"] as? String ?? "")")
        case "done":
            finish(error: nil)
        default:
            break
        }
    }
}
