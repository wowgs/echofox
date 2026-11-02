// The clipboard, lent to the Inserter for a paste and given back.
import AppKit
import EchoFoxCore

/// The clipboard, lent for a paste and given back. The speaker's own contents come back `restoreAfter` after the last
/// paste, by the rule of ClipboardLoan (EchoFoxCore): only if nobody changed the clipboard meanwhile. Lent text is
/// marked transient (org.nspasteboard.TransientType), so clipboard managers do not keep it. Used only on the insertion
/// queue.
final class Clipboard {
    static let transient = NSPasteboard.PasteboardType("org.nspasteboard.TransientType")
    /// The clipboard's items, each as its types and their data.
    typealias Contents = [[(NSPasteboard.PasteboardType, Data)]]
    private let pb = NSPasteboard.general
    private let restoreAfter: TimeInterval
    private let onQueue: (@escaping () -> Void) -> Void
    private var loan = ClipboardLoan<Contents>()

    /// `onQueue` runs a block on the queue the clipboard is used on (the insertion queue).
    init(restoreAfter: TimeInterval, onQueue: @escaping (@escaping () -> Void) -> Void) {
        self.restoreAfter = restoreAfter
        self.onQueue = onQueue
    }

    /// Runs `body` (a paste) with `text` on the clipboard; the speaker's contents come back later.
    func lend(_ text: String, _ body: () -> Void) {
        let contents = loan.mustSave(changeCount: pb.changeCount) ? read() : nil
        let mine = loan.lent(saving: contents, changeCount: put(text, transient: true))
        body()
        DispatchQueue.global().asyncAfter(deadline: .now() + restoreAfter) { [weak self] in
            self?.onQueue { self?.restore(mine) }
        }
    }

    /// Leaves `text` on the clipboard for the speaker to paste: no restore after it.
    func keep(_ text: String) {
        loan.kept(changeCount: put(text, transient: false))
    }

    private func read() -> Contents {
        (pb.pasteboardItems ?? []).map { item in
            item.types.compactMap { t in item.data(forType: t).map { (t, $0) } }
        }
    }

    /// Puts `text` on the clipboard; returns the clipboard's change count after it.
    private func put(_ text: String, transient: Bool) -> Int {
        pb.clearContents()
        let item = NSPasteboardItem()
        item.setString(text, forType: .string)
        if transient { item.setData(Data(), forType: Self.transient) }
        pb.writeObjects([item])
        return pb.changeCount
    }

    private func restore(_ mine: Int) {
        guard let saved = loan.restore(mine, changeCount: pb.changeCount) else { return }
        pb.clearContents()
        pb.writeObjects(saved.map { pairs -> NSPasteboardItem in
            let item = NSPasteboardItem()
            for (t, d) in pairs { item.setData(d, forType: t) }
            return item
        })
    }
}
