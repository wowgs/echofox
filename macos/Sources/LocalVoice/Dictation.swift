// One dictation: the focus snapshot, the microphone, and one WebSocket to the dictation server (the protocol is in
// server/gemma_voice.py; the messages in LocalVoiceCore/Messages.swift). Sending goes through one serial queue, so the
// start message (which waits for the snapshot) goes first and the audio and the stop follow in order. Everything else
// runs on the main thread.
import FocusSnapshot
import Foundation
import LocalVoiceCore

final class Dictation {
    enum Phase { case recording, waiting, finished }
    static let client = "local-voice-mac"

    private(set) var phase = Phase.recording
    private(set) var texts: [String] = []
    private(set) var errors: [String] = []
    private(set) var capture: FocusSnapshot.Capture?
    var text: String { texts.joined(separator: " ") }
    var onPhase: (Dictation) -> Void = { _ in }
    let started = Date()

    private let config: Config
    private let sampleRate: Int
    private let textWait: TimeInterval
    private let full: Bool, tree: Bool, lists: Bool
    private let queue = DispatchQueue(label: "local-voice.dictation.send")
    private let recorder: Recorder
    private var task: URLSessionWebSocketTask?
    private var lastSpeech = Date()
    private var silenceTimer: Timer?
    private var textTimer: Timer?
    private var sendFailed = false

    /// `server`: what the server said of itself (nil: not known yet; the defaults then). `full`: an enabled adapter
    /// reads the frontmost app, so the snapshot has its window, ancestors and processes. `tree`: the app is an
    /// Electron app whose tree an enabled adapter needs. `lists`: an enabled adapter reads the rows of the app's window
    /// lists (its manifest's "screen").
    init(config: Config, server: ServerInfo?, full: Bool, tree: Bool, lists: Bool = false) {
        self.config = config
        self.sampleRate = server?.sampleRate ?? Tuning.defaultSampleRate
        self.textWait = server?.textWaitSeconds ?? Tuning.defaultTextWaitSeconds
        self.full = full
        self.tree = tree
        self.lists = lists
        self.recorder = Recorder(sampleRate: Double(sampleRate))
    }

    func start() {
        let task = URLSession.shared.webSocketTask(with: config.serverURL)
        self.task = task
        task.resume()
        receive()
        let config = self.config, full = self.full, tree = self.tree, lists = self.lists, rate = self.sampleRate
        queue.async { [weak self] in
            let capture = FocusSnapshot.capture(full: full, enableElectron: tree, lists: lists)
            DispatchQueue.main.async { self?.capture = capture }
            Log.write("snapshot: app \(capture.snapshot["app"].flatMap { ($0 as? [String: Any])?["bundleId"] } ?? "none"), "
                      + "focused \(capture.focused != nil), web area \(capture.snapshot["webArea"] != nil), "
                      + "lists \((capture.snapshot["lists"] as? [Any])?.count ?? 0), "
                      + "\(capture.snapshot["tookMs"] ?? "?") ms")
            self?.send(.string(ClientMessage.start(model: config.model, language: config.language, sampleRate: rate,
                                                   client: Dictation.client, snapshot: capture.snapshot)))
        }
        do {
            try recorder.start(
                onPCM: { [weak self] pcm in self?.queue.async { self?.send(.data(pcm)) } },
                onLost: { [weak self] why in DispatchQueue.main.async { self?.recorderLost(why) } })
        } catch {
            finish(error: "microphone: \(error.localizedDescription)")
            return
        }
        silenceTimer = Timer.scheduledTimer(withTimeInterval: Tuning.silenceCheckSeconds, repeats: true) { [weak self] _ in
            self?.checkSilence()
        }
        Log.write("start: model \(config.model ?? "the server's default"), language \(config.language), "
                  + config.serverURL.absoluteString)
    }

    /// Ends the recording; the text follows.
    func stop(_ reason: ClientMessage.StopReason) {
        guard phase == .recording else { return }
        endRecording()
        queue.async { [weak self] in self?.send(.string(ClientMessage.stop(reason))) }
        Log.write("stop: \(reason.rawValue), \(String(format: "%.1f", Date().timeIntervalSince(started))) s")
        onPhase(self)
    }

    /// The recording ends here (a stop of ours, or the server's): the microphone closes and the wait for text starts.
    private func endRecording() {
        phase = .waiting
        recorder.stop()
        silenceTimer?.invalidate()
        waitForText()
    }

    /// The server has `textWait` for each next piece of text: a long recording has many pieces, and each may take a
    /// while, so the wait starts again with every text.
    private func waitForText() {
        textTimer?.invalidate()
        textTimer = Timer.scheduledTimer(withTimeInterval: textWait, repeats: false) { [weak self] _ in
            guard let self else { return }
            self.finish(error: "the server sent no more text in \(Int(self.textWait)) s")
        }
    }

    private func recorderLost(_ why: String) {
        guard phase == .recording else { return }
        errors.append("the microphone stopped: \(why)")
        stop(.error)
    }

    private func checkSilence() {
        guard phase == .recording, config.silenceStopSeconds > 0,
              Date().timeIntervalSince(lastSpeech) >= config.silenceStopSeconds else { return }
        stop(.silence)
    }

    private func finish(error: String?) {
        guard phase != .finished else { return }
        if let error { errors.append(error) }
        phase = .finished
        recorder.stop()
        silenceTimer?.invalidate()
        textTimer?.invalidate()
        task?.cancel(with: .normalClosure, reason: nil)
        onPhase(self)
    }

    // MARK: The connection

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
        switch ServerMessage.parse(message) {
        case .speech:
            lastSpeech = Date()
        case .text(let t):
            if !t.isEmpty { texts.append(t) }
            if phase == .waiting { waitForText() }
        case .error(let e):
            errors.append(e)
            Log.write("server error: \(e)")
        case .stopped(let reason):  // the server stopped taking audio (the longest recording)
            Log.write("the server stopped the recording: \(reason)")
            if phase == .recording {
                endRecording()
                onPhase(self)
            }
        case .done:
            finish(error: nil)
        case .other, .none:
            break
        }
    }
}
