// The app's dictations: at most one records, and those that stopped recording wait for their text. A tap of a key
// stops the one that records, or starts a new one when none records, also while others still wait for their text. A
// dictation leaves the queue when it finishes, and its text is inserted then.
import Foundation

public enum DictationPhase {
    case recording, waiting, finished
}

public struct DictationQueue<Dictation: AnyObject> {
    /// The dictation that records now.
    public private(set) var current: Dictation?
    /// The dictations that stopped recording and wait for their text, the oldest first.
    public private(set) var waiting: [Dictation] = []

    public init() {}

    /// Whether a dictation records or waits for its text (an update waits for none).
    public var busy: Bool { current != nil || !waiting.isEmpty }

    /// A new dictation records. The caller starts one only when none records (a tap then stops `current`).
    public mutating func start(_ d: Dictation) {
        current = d
    }

    /// A dictation's phase changed: one that stopped recording goes to the waiting ones, one that finished leaves the
    /// queue. True when it finished: its text is due.
    public mutating func changed(_ d: Dictation, to phase: DictationPhase) -> Bool {
        if d === current, phase != .recording {
            current = nil
            waiting.append(d)
        }
        guard phase == .finished else { return false }
        waiting.removeAll { $0 === d }
        return true
    }
}
