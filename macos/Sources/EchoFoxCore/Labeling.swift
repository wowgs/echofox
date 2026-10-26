// Labeling: you listen to a piece of a saved recording and write what you said. The server keeps every recording in
// <recordings>/<day>/<id>/ (server/recordings.py): piece-N.wav, the audio of one model request; pieces.jsonl, the
// model's text of each piece ("raw": its own text, when hesitation sounds were taken out); text-before-audio.txt,
// the chat context and prompt the model saw; adapter.json, the recording's record. A piece is one card, since a piece
// is what the model hears: the labeled pieces are the examples to check and train the model on.
//
// A labeled piece goes to <labeled>/<day>/<id>/piece-N/, apart from the recordings, so what you confirmed never mixes
// with what the model wrote: audio.wav and text-before-audio.txt (copies, so the piece stays whole when recordings go)
// and label.json. A piece with a label.json is done; "later" writes nothing, so the piece comes back next time.
import Foundation

public struct LabelItem: Equatable {
    /// "<day>/<id>", as the server names a recording.
    public let recording: String
    public let piece: Int
    public let audio: URL
    /// The model's text: what went into the input box, and the model's own when it differs.
    public let text: String
    public let raw: String?
    public let audioSeconds: Double?
    /// Where the speaker was writing, from the recording's record (the adapter's session title or what it is about).
    public let place: String?
    public let started: String?
    public let model: String?
    public let language: String?
    let folder: URL
}

public enum LabelStatus: String {
    /// The text is what was said.
    case verified
    /// The audio is no use for the model (a TV, noise, another voice): kept, but no example.
    case unusable
}

public enum Labeling {
    /// How a label's text is written: what the speaker meant to write. Hesitation sounds (э, мм, а-а) and repeated
    /// words go, and after a slip only the correction stays ("fullback, ой, не fullback, fallback" → "fallback"), so
    /// a model trained on the labels learns to leave them out; the words said on purpose stay.
    public static let convention = "clean"

    /// The pieces labeled as verified, and their seconds of audio, from the label files under `labeled`.
    public static func stats(labeled: URL) -> (count: Int, seconds: Double) {
        guard let e = FileManager.default.enumerator(at: labeled, includingPropertiesForKeys: nil) else { return (0, 0) }
        var count = 0, seconds = 0.0
        for case let url as URL in e where url.lastPathComponent == "label.json" {
            guard let d = (try? JSONSerialization.jsonObject(with: Data(contentsOf: url))) as? [String: Any],
                  d["status"] as? String == LabelStatus.verified.rawValue else { continue }
            count += 1
            seconds += d["audioSeconds"] as? Double ?? 0
        }
        return (count, seconds)
    }

    /// The pieces not labeled yet, the newest recording first, its pieces in order.
    public static func pending(recordings: URL, labeled: URL) -> [LabelItem] {
        let fm = FileManager.default
        var out: [LabelItem] = []
        let days = ((try? fm.contentsOfDirectory(atPath: recordings.path)) ?? []).sorted(by: >)
        for day in days {
            let ids = ((try? fm.contentsOfDirectory(atPath: recordings.appendingPathComponent(day).path)) ?? [])
                .sorted(by: >)
            for id in ids {
                let folder = recordings.appendingPathComponent(day).appendingPathComponent(id)
                guard let lines = try? String(contentsOf: folder.appendingPathComponent("pieces.jsonl"), encoding: .utf8)
                else { continue }
                let record = (try? JSONSerialization.jsonObject(
                    with: Data(contentsOf: folder.appendingPathComponent("adapter.json")))) as? [String: Any]
                let chat = record?["chat"] as? [String: Any]
                let place = ((chat?["details"] as? [String: Any])?["title"] as? String) ?? chat?["about"] as? String
                for line in lines.split(separator: "\n") {
                    guard let p = (try? JSONSerialization.jsonObject(with: Data(line.utf8))) as? [String: Any],
                          let n = p["piece"] as? Int else { continue }
                    let audio = folder.appendingPathComponent("piece-\(n).wav")
                    let done = labelFolder(labeled, "\(day)/\(id)", n).appendingPathComponent("label.json")
                    guard fm.fileExists(atPath: audio.path), !fm.fileExists(atPath: done.path) else { continue }
                    out.append(LabelItem(recording: "\(day)/\(id)", piece: n, audio: audio,
                                         text: p["text"] as? String ?? "", raw: p["raw"] as? String,
                                         audioSeconds: p["audio_seconds"] as? Double, place: place,
                                         started: record?["started"] as? String, model: record?["model"] as? String,
                                         language: record?["language"] as? String, folder: folder))
                }
            }
        }
        return out
    }

    public static func labelFolder(_ labeled: URL, _ recording: String, _ piece: Int) -> URL {
        labeled.appendingPathComponent(recording).appendingPathComponent("piece-\(piece)")
    }

    /// Keeps `item` as labeled: `text` is what was said (for .unusable, whatever was typed). label.json goes last, so
    /// a piece whose copy failed is not counted as done.
    public static func save(_ item: LabelItem, text: String, status: LabelStatus, labeled: URL,
                            now: Date = Date()) throws {
        let fm = FileManager.default
        let dir = labelFolder(labeled, item.recording, item.piece)
        try fm.createDirectory(at: dir, withIntermediateDirectories: true)
        for (from, to) in [(item.audio, "audio.wav"),
                           (item.folder.appendingPathComponent("text-before-audio.txt"), "text-before-audio.txt")]
        where fm.fileExists(atPath: from.path) {
            let target = dir.appendingPathComponent(to)
            try? fm.removeItem(at: target)
            try fm.copyItem(at: from, to: target)
        }
        var label: [String: Any] = [
            "recording": item.recording, "piece": item.piece, "status": status.rawValue, "convention": convention,
            "text": text.trimmingCharacters(in: .whitespacesAndNewlines), "modelText": item.text,
            "labeledAt": ISO8601DateFormatter().string(from: now),
        ]
        if let raw = item.raw { label["modelRaw"] = raw }
        if let s = item.audioSeconds { label["audioSeconds"] = s }
        if let m = item.model { label["model"] = m }
        if let l = item.language { label["language"] = l }
        let data = try JSONSerialization.data(withJSONObject: label, options: [.prettyPrinted, .sortedKeys,
                                                                                .withoutEscapingSlashes])
        try data.write(to: dir.appendingPathComponent("label.json"), options: .atomic)
    }
}
