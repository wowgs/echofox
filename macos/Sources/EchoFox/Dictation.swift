// One dictation: the focus snapshot, the microphone, and one ServerConnection to the dictation server (the protocol is
// in docs/reference/6-protocol.md; the messages in EchoFoxCore/Messages.swift). Sending goes through one serial queue,
// so the start message (which waits for the snapshot) goes first and the audio and the stop follow in order.
// Everything else runs on the main thread. The App's DictationQueue (EchoFoxCore) follows its phases.
import FocusSnapshot
import Foundation
import EchoFoxCore

final class Dictation {
    static let client = "echofox-mac"

    private(set) var phase = DictationPhase.recording
    private(set) var texts: [String] = []
    private(set) var errors: [String] = []
    private(set) var capture: FocusSnapshot.Capture?
    var text: String { texts.joined(separator: " ") }
    var onPhase: (Dictation) -> Void = { _ in }
    let started = Date()

    private let config: Config
    private let sampleRate: Int
    private let textWait: TimeInterval
    private let plan: SnapshotPlan
    /// A private dictation (the private dictation's hotkey): the screen is not read. The capture keeps only the
    /// focused element, for the insertion; the server gets no snapshot, no adapter runs, nothing is saved.
    let isPrivate: Bool
    private let queue = DispatchQueue(label: "echofox.dictation.send")
    private let recorder: Recorder
    private let microphone: String
    private let connection: ServerConnection
    private var lastSpeech = Date()
    private var silenceTimer: Timer?
    private var textTimer: Timer?
    private var sendFailed = false

    /// `server`: what the server said of itself (nil: not known yet; the defaults then). `plan`: what the focus
    /// snapshot takes of the frontmost app (ServerInfo.snapshotPlan).
    init(config: Config, server: ServerInfo?, plan: SnapshotPlan, isPrivate: Bool = false) {
        self.isPrivate = isPrivate
        self.config = config
        self.sampleRate = server?.sampleRate ?? Tuning.defaultSampleRate
        self.textWait = server?.textWaitSeconds ?? Tuning.defaultTextWaitSeconds
        self.plan = plan
        let microphone = AudioInputs.chosen(config.microphone)
        self.recorder = Recorder(sampleRate: Double(sampleRate), microphone: microphone)
        self.microphone = "\(microphone.name) (\(microphone.why))"
        self.connection = ServerConnection(url: config.serverURL)
    }

    func start() {
        connection.open { [weak self] event in self?.received(event) }
        let config = self.config, rate = self.sampleRate, isPrivate = self.isPrivate
        let plan = isPrivate ? SnapshotPlan.none : self.plan  // a private dictation reads nothing of the screen
        queue.async { [weak self] in
            let capture = FocusSnapshot.capture(full: plan.full, enableElectron: plan.tree, lists: plan.lists, outline: plan.outline,
                                                outlineSkip: plan.outlineSkip, screenBudget: plan.screenBudget,
                                                tokens: TokenEstimate(plan.tokenWeights))
            DispatchQueue.main.async { self?.capture = capture }
            Log.write("snapshot: app \(capture.snapshot["app"].flatMap { ($0 as? [String: Any])?["bundleId"] } ?? "none"), "
                      + "focused \(capture.focused != nil), web area \(capture.snapshot["webArea"] != nil), "
                      + "lists \((capture.snapshot["lists"] as? [Any])?.count ?? 0), "
                      + "outline \(((capture.snapshot["outline"] as? [String: Any])?["nodes"] as? [Any])?.count ?? 0) elements, "
                      + "\(capture.snapshot["tookMs"] ?? "?") ms")
            self?.send(text: ClientMessage.start(model: config.model, language: config.language, sampleRate: rate,
                                                 client: Dictation.client, snapshot: isPrivate ? [:] : capture.snapshot,
                                                 isPrivate: isPrivate))
        }
        do {
            try recorder.start(
                onPCM: { [weak self] pcm in self?.queue.async { self?.send(audio: pcm) } },
                onLost: { [weak self] why in DispatchQueue.main.async { self?.recorderLost(why) } })
        } catch {
            finish(error: "microphone: \(error.localizedDescription)")
            return
        }
        silenceTimer = Timer.scheduledTimer(withTimeInterval: Tuning.silenceCheckSeconds, repeats: true) { [weak self] _ in
            self?.checkSilence()
        }
        Log.write("start: model \(config.model ?? "the server's default"), language \(config.language), microphone \(microphone), "
                  + config.serverURL.absoluteString)
    }

    /// Ends the recording; the text follows.
    func stop(_ reason: ClientMessage.StopReason) {
        guard phase == .recording else { return }
        endRecording()
        queue.async { [weak self] in self?.send(text: ClientMessage.stop(reason)) }
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
        guard phase == .recording, Date().timeIntervalSince(lastSpeech) >= config.silenceStopSeconds else { return }
        stop(.silence)
    }

    private func finish(error: String?) {
        guard phase != .finished else { return }
        if let error { errors.append(error) }
        phase = .finished
        recorder.stop()
        silenceTimer?.invalidate()
        textTimer?.invalidate()
        connection.close()  // no event of the server comes after it
        onPhase(self)
    }

    // MARK: The connection

    /// On the send queue. The first failed send goes to the log.
    private func send(text: String) { connection.send(text) { [weak self] in self?.failed($0) } }
    private func send(audio: Data) { connection.send(audio) { [weak self] in self?.failed($0) } }

    private func failed(_ error: Error) {
        guard !sendFailed else { return }
        sendFailed = true
        Log.write("send failed: \(error.localizedDescription)")
    }

    private func received(_ event: ServerConnection.Event) {
        switch event {
        case .ended(let error):
            finish(error: "the dictation server at \(config.serverURL.absoluteString): \(error.localizedDescription)")
        case .text(let s):
            handle(s)
        }
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
        case .other, .none, .progress, .downloaded, .removed:  // not messages of a recording
            break
        }
    }
}
