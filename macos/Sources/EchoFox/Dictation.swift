// One dictation: the focus snapshot, the microphone, and one ServerConnection to the dictation server (the protocol is
// in docs/reference/6-protocol.md; the messages in EchoFoxCore/Messages.swift). Sending goes through one serial queue,
// so the start message (which waits for the identity) goes first and the audio and the stop follow in order. The
// content that the server's read request asks for is read on a queue of its own, so the audio goes on meanwhile, and
// its message joins the send queue between two pieces of audio. Everything else runs on the main thread. The App's
// DictationQueue (EchoFoxCore) follows its phases.
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
    private let plan: IdentityPlan
    /// A private dictation (the private dictation's hotkey): the screen is not read. The capture keeps only the
    /// focused element, for the insertion; the server gets no identity, no adapter runs, nothing is saved.
    let isPrivate: Bool
    private let queue = DispatchQueue(label: "echofox.dictation.send")
    private let readQueue = DispatchQueue(label: "echofox.dictation.read")
    private let recorder: Recorder
    private let microphone: String
    private let connection: ServerConnection
    private var lastSpeech = Date()
    private var silenceTimer: Timer?
    private var textTimer: Timer?
    private var sendFailed = false

    /// `server`: what the server said of itself (nil: not known yet; the defaults then). `plan`: what the app reads
    /// of the frontmost app at the hotkey (ServerInfo.identityPlan).
    init(config: Config, server: ServerInfo?, plan: IdentityPlan, isPrivate: Bool = false) {
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
        let plan = isPrivate ? IdentityPlan.none : self.plan  // a private dictation reads nothing of the screen
        queue.async { [weak self] in
            let capture = FocusSnapshot.capture(identity: plan.identity, enableElectron: plan.tree)
            DispatchQueue.main.async { self?.capture = capture }
            Log.write("identity: app \(capture.bundleId ?? "none"), "
                      + (capture.identity == nil ? "not sent" : "web area \(capture.identity?["webArea"] != nil)")
                      + ", focused \(capture.focused != nil), \(capture.tookMs) ms"
                      + (capture.trusted ? "" : ", no Accessibility permission"))
            self?.send(text: ClientMessage.start(model: config.model, language: config.language, sampleRate: rate,
                                                 client: Dictation.client, identity: capture.identity,
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
        case .read(let request):
            read(request)
        case .done:
            finish(error: nil)
        case .other, .none, .progress, .downloaded, .removed:  // not messages of a recording
            break
        }
    }

    // MARK: The content

    /// The server's read request: what its matched surfaces read of the window captured at the hotkey. It is read on
    /// the read queue, so the audio goes on, and sent between two pieces of audio. A private dictation, or one whose
    /// identity was not sent, reads nothing. The context's deadline is the recording's stop, so content read after the
    /// stop is not sent.
    private func read(_ request: ReadRequest) {
        guard !isPrivate, let capture, capture.identity != nil else {
            Log.write("content: none, " + (isPrivate ? "a private dictation" : "the identity was not sent"))
            return
        }
        guard phase == .recording else {
            Log.write("content: none, the recording had stopped")
            return
        }
        guard !request.surfaces.isEmpty else {
            Log.write("content: none, no surface matched")
            return
        }
        let tokens = TokenEstimate(request.tokenWeights)
        readQueue.async { [weak self] in
            let started = Date()
            var surfaces: [String: [String: Any]] = [:]
            for s in request.surfaces { surfaces[s.surface] = FocusSnapshot.read(s, of: capture, tokens: tokens) }
            let tookMs = Int(Date().timeIntervalSince(started) * 1000)
            DispatchQueue.main.async {
                guard let self else { return }
                let late = self.phase != .recording
                Log.write("content: \(Dictation.summary(surfaces)), \(tookMs) ms" + (late ? ", not sent: the recording had stopped" : ""))
                if late { return }
                self.queue.async { self.send(text: ClientMessage.content(surfaces: surfaces, tookMs: tookMs)) }
            }
        }
    }

    /// The content for the log: per surface, how much of each part, never its text.
    private static func summary(_ surfaces: [String: [String: Any]]) -> String {
        surfaces.keys.sorted().map { name in
            let c = surfaces[name] ?? [:]
            var parts: [String] = []
            if let o = c["outline"] as? [String: Any] { parts.append("outline \((o["nodes"] as? [Any])?.count ?? 0) elements") }
            if let l = c["lists"] as? [[String: Any]] {
                parts.append("lists \(l.count) with \(l.reduce(0) { $0 + (($1["rows"] as? [Any])?.count ?? 0) }) rows")
            }
            if let p = c["processes"] as? [Any] { parts.append("processes \(p.count)") }
            return "\(name) " + (parts.isEmpty ? "nothing" : parts.joined(separator: ", "))
        }.joined(separator: "; ")
    }
}
