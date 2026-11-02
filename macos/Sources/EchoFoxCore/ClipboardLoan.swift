// The rule of the clipboard lent for a paste (the app's Clipboard does what it says on NSPasteboard). The speaker's
// own contents are saved before the first lend and come back after the last one, and only if nobody changed the
// clipboard meanwhile: the speaker may copy something in that time, and then theirs stays. A lend that follows ours
// keeps the contents saved first, because the clipboard then holds our text. The clipboard's change count tells who
// wrote last. `Contents` is whatever the app saves of the clipboard.
import Foundation

public struct ClipboardLoan<Contents> {
    /// The speaker's contents to bring back, or nil.
    public private(set) var saved: Contents?
    /// The clipboard's change count right after our text went in.
    private var ours = -1
    /// The last lend or keep; a restore of an earlier one does nothing.
    private var turn = 0

    public init() {}

    /// Whether a lend must save the clipboard first: on the first lend, and when the speaker copied something since
    /// our text went in.
    public func mustSave(changeCount: Int) -> Bool { saved == nil || changeCount != ours }

    /// A lend: `contents` are saved (when mustSave said so), and our text went in, which left the clipboard at
    /// `changeCount`. Returns the turn to restore later.
    public mutating func lent(saving contents: Contents?, changeCount: Int) -> Int {
        if let contents { saved = contents }
        ours = changeCount
        turn += 1
        return turn
    }

    /// Our text stays on the clipboard for the speaker to paste: nothing comes back after it.
    public mutating func kept(changeCount: Int) {
        turn += 1
        saved = nil
        ours = changeCount
    }

    /// The restore of `turn` is due, with the clipboard at `changeCount`: the contents to put back, or nil when a later
    /// lend or keep came, or when somebody else wrote the clipboard.
    public mutating func restore(_ turn: Int, changeCount: Int) -> Contents? {
        guard turn == self.turn, let saved else { return nil }
        self.saved = nil
        return changeCount == ours ? saved : nil
    }
}
