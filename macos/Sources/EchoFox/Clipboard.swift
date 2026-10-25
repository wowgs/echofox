// The clipboard, lent to the Inserter for a paste and given back.
import AppKit

/// The clipboard, lent for a paste and given back. The speaker's own contents come back `restoreAfter` after the last
/// paste, and only if nobody changed the clipboard meanwhile (the speaker may copy something in that second). Lent
/// text is marked transient (org.nspasteboard.TransientType), so clipboard managers do not keep it. Used only on the
/// insertion queue.
final class Clipboard {
    static let transient = NSPasteboard.PasteboardType("org.nspasteboard.TransientType")
    private let pb = NSPasteboard.general
    private let restoreAfter: TimeInterval
    private let onQueue: (@escaping () -> Void) -> Void

    /// `onQueue` runs a block on the queue the clipboard is used on (the insertion queue).
    init(restoreAfter: TimeInterval, onQueue: @escaping (@escaping () -> Void) -> Void) {
        self.restoreAfter = restoreAfter
        self.onQueue = onQueue
    }
    private var saved: [[(NSPasteboard.PasteboardType, Data)]]?
    private var ours = -1  // the clipboard's changeCount right after our text went in
    private var turn = 0

    /// Runs `body` (a paste) with `text` on the clipboard; the speaker's contents come back later.
    func lend(_ text: String, _ body: () -> Void) {
        if saved == nil || pb.changeCount != ours {  // the first lend, or the speaker copied something since
            saved = (pb.pasteboardItems ?? []).map { item in
                item.types.compactMap { t in item.data(forType: t).map { (t, $0) } }
            }
        }
        put(text, transient: true)
        body()
        turn += 1
        let mine = turn
        DispatchQueue.global().asyncAfter(deadline: .now() + restoreAfter) { [weak self] in
            self?.onQueue { self?.restore(mine) }
        }
    }

    /// Leaves `text` on the clipboard for the speaker to paste: no restore after it.
    func keep(_ text: String) {
        turn += 1
        saved = nil
        put(text, transient: false)
    }

    private func put(_ text: String, transient: Bool) {
        pb.clearContents()
        let item = NSPasteboardItem()
        item.setString(text, forType: .string)
        if transient { item.setData(Data(), forType: Self.transient) }
        pb.writeObjects([item])
        ours = pb.changeCount
    }

    private func restore(_ mine: Int) {
        guard mine == turn, let saved else { return }
        self.saved = nil
        guard pb.changeCount == ours else { return }  // somebody else wrote the clipboard: theirs stays
        pb.clearContents()
        pb.writeObjects(saved.map { pairs -> NSPasteboardItem in
            let item = NSPasteboardItem()
            for (t, d) in pairs { item.setData(d, forType: t) }
            return item
        })
    }
}
