// Where the text goes when it comes back, and in which ways it is tried (the rule of 2026-10-15). The rule decides;
// an InsertionDesk does: the app's Inserter through Accessibility, the checks through a fake one.
//   1. if an input box had the focus at the tap: into that box, wherever the speaker went meanwhile;
//   2. otherwise the input box that has the focus now (the speaker clicked into it while talking);
//   3. otherwise, if the app of the tap is still in front and tells nothing of its focus (an Electron app whose tree no
//      adapter needs), a paste where its cursor is;
//   4. otherwise the clipboard (and the menu).
// Into the box of the tap, the ways are tried in this order; each is checked by the box's text length, and the first
// that works wins. Before each next way, the box is checked again: a way that landed late counts, and no text goes in
// twice. A Cmd+V to the app in front, with its focus in the box, is what the speaker's own Cmd+V would be, so it ends
// the insertion even when the box's length does not show it: a terminal's box (Ghostty's AXTextArea) has the visible
// screen as its value, which need not grow, and the next ways then pasted the same text twice more (2026-10-18). Once
// the tap's app got keys, rules 2 and 3 do not send it more.
//   a. Accessibility: the box's selected text is replaced. Claude Desktop's box reports success and changes nothing
//      (2026-10-15).
//   b. Cmd+V: to the frontmost app if the box is in it, else to the box's app in the background, unless that app's
//      focus is in another box. In the background, Claude Desktop did not take it (2026-10-15).
//   c. In the background, without the focus: the box's value, only for an empty box (a draft could lose its
//      formatting); then Cmd+V as keyboard events; then the text typed into the app's process.
//   d. The box's app comes to the front, Cmd+V, and the speaker is taken back to the app and box they were in.
import Foundation

public enum InsertionResult: String {
    case accessibility, accessibilityUnchecked, paste, pasteUnchecked, pasteInBackground, valueInBackground,
         typedInBackground, axKeysInBackground, pasteBroughtToFront, pasteBroughtToFrontUnchecked, clipboard, late
}

/// What the rule needs from the Mac. Each way gives its result if the text went in, nil if it did not.
public protocol InsertionDesk {
    associatedtype Box
    func isInput(_ box: Box) -> Bool
    /// The box's text length, nil if it does not say.
    func length(_ box: Box) -> Int?
    func isFront(_ pid: Int32) -> Bool
    /// The element with the app's own focus, nil if it tells nothing.
    func focused(in pid: Int32) -> Box?
    func same(_ a: Box, _ b: Box) -> Bool
    func describe(_ box: Box) -> String
    /// The input box that has the focus now, and its app.
    func focusedInput() -> (box: Box, pid: Int32)?
    /// a.
    func setSelectedText(_ text: String, _ box: Box) -> InsertionResult?
    /// b. Only while the app's own focus is in the box, unless `anyFocus`. In front it counts as done (.paste or
    /// .pasteUnchecked); in the background only if the box grew.
    func paste(_ text: String, into box: Box, pid: Int32, anyFocus: Bool) -> InsertionResult?
    /// c.
    func setValueIfEmpty(_ text: String, _ box: Box) -> InsertionResult?
    func keysPaste(_ text: String, into box: Box, pid: Int32) -> InsertionResult?
    func type(_ text: String, into box: Box, pid: Int32) -> InsertionResult?
    /// d. Nil if the box did not get the focus and nothing was sent.
    func bringToFrontAndPaste(_ text: String, into box: Box, pid: Int32) -> InsertionResult?
    /// Rule 3: a paste where the app's cursor is, with no box to check.
    func pasteAtCursor(_ text: String)
    /// Rule 4.
    func keep(_ text: String)
}

public enum InsertionRule {
    /// Puts `text` where the rule says; `tap`: the box that had the focus at the tap (nil: none) and its app (nil:
    /// no snapshot). What happened and why, for the log.
    public static func insert<D: InsertionDesk>(_ text: String, tapBox: D.Box?, tapPid: Int32?,
                                                on desk: D) -> (InsertionResult, String) {
        var tried: [String] = []
        var tapApp: Int32?  // the tap's app, once rule 1 may have sent it keys
        if let box = tapBox, let pid = tapPid, desk.isInput(box) {
            let note = { (r: InsertionResult) in
                (r, "the input box of the tap" + (tried.isEmpty ? "" : "; " + tried.joined(separator: ", ")))
            }
            let baseline = desk.length(box)
            let landed = { baseline.map { b in (desk.length(box) ?? b) > b } ?? false }
            if let r = desk.setSelectedText(text, box) { return note(r) }
            tried.append("selected text: no")
            let front = desk.isFront(pid)
            let appFocus = desk.focused(in: pid)
            // In the background, Desktop's accessibility focus is not its box any more (2026-10-15), while the page's
            // own focus stays where the speaker left it. So the background ways are tried unless the app's focus is
            // in another input box.
            let otherBox = appFocus.map { !desk.same($0, box) && desk.isInput($0) } ?? false
            tried.append("the app's focus: \(appFocus.map(desk.describe) ?? "none"), "
                         + "the box's length: \(baseline.map(String.init) ?? "unknown")")
            if landed() { return note(.late) }
            tapApp = pid
            if let r = desk.paste(text, into: box, pid: pid, anyFocus: !front && !otherBox) { return note(r) }
            tried.append("cmd+v\(front ? "" : " in the background"): \(otherBox ? "skipped, focus in another box" : "no")")
            if !front && !otherBox {
                let ways: [(String, () -> InsertionResult?)] = [
                    ("value", { desk.setValueIfEmpty(text, box) }),
                    ("accessibility keys", { desk.keysPaste(text, into: box, pid: pid) }),
                    ("typing", { desk.type(text, into: box, pid: pid) })]
                for (name, way) in ways {
                    if landed() { return note(.late) }
                    if let r = way() { return note(r) }
                    tried.append("\(name): no")
                }
            }
            if landed() { return note(.late) }
            if let r = desk.bringToFrontAndPaste(text, into: box, pid: pid) {
                return (r, "the input box of the tap, brought to the front and back; " + tried.joined(separator: ", "))
            }
            tried.append("brought to the front: no")
        }
        if let (now, pid) = desk.focusedInput(), pid != tapApp {
            if let r = desk.setSelectedText(text, now) { return (r, "the input box focused at the end") }
            if let r = desk.paste(text, into: now, pid: pid, anyFocus: false) { return (r, "the input box focused at the end") }
        }
        // An app that tells nothing through Accessibility (an Electron app without its tree, in the base mode): the
        // text goes where its cursor is, by a paste, if it is still the app in front.
        if let pid = tapPid, tapBox == nil, desk.isFront(pid), desk.focused(in: pid) == nil {
            desk.pasteAtCursor(text)
            return (.pasteUnchecked, "the app of the tap, which tells nothing of its input box")
        }
        desk.keep(text)
        return (.clipboard, "no input box at the tap or now, or the text did not go in"
                    + (tried.isEmpty ? "" : "; the box of the tap: " + tried.joined(separator: ", ")))
    }
}
