// Puts the text where the speaker wants it when the text comes back (Alex's rule, 2026-10-15):
//   1. if an input box had the focus at the tap: into that box, wherever the speaker went meanwhile;
//   2. otherwise the input box that has the focus now (the speaker clicked into it while talking);
//   3. otherwise the clipboard (and the menu).
// Into a box, the ways are tried in this order, each checked by the box's text length, and the first that works wins:
//   a. Accessibility: the box's selected text is replaced. Claude Desktop's box reports success and changes nothing
//      (2026-10-15).
//   b. Cmd+V: to the frontmost app if the box is in it, else to the box's app in the background (CGEventPostToPid),
//      if that app's own focus is still in the box; the clipboard is restored after it.
//   c. The box's app comes to the front, Cmd+V, and the speaker is taken back to the app and box they were in.
import AppKit
import ApplicationServices
import FocusSnapshot

enum Inserter {
    enum Result: String {
        case accessibility, accessibilityUnchecked, paste, pasteUnchecked, pasteInBackground, pasteBroughtToFront,
             clipboard
    }

    static let inputRoles: Set<String> = ["AXTextArea", "AXTextField", "AXSearchField", "AXComboBox"]

    static func insert(_ text: String, into capture: FocusSnapshot.Capture?) -> (Result, String) {
        if let box = capture?.focused, let pid = capture?.pid, isInput(box) {
            if let r = setSelectedText(text, box) { return (r, "the input box of the tap") }
            if let r = pasteInto(box, pid: pid, text) { return (r, "the input box of the tap") }
            if bringToFrontAndPaste(box, pid: pid, text) {
                return (.pasteBroughtToFront, "the input box of the tap; the speaker was taken back")
            }
        }
        if let (now, pid) = focusedInput() {
            if let r = setSelectedText(text, now) { return (r, "the input box focused at the end") }
            if let r = pasteInto(now, pid: pid, text) { return (r, "the input box focused at the end") }
        }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        return (.clipboard, "no input box at the tap or now, or the text did not go in")
    }

    /// The focused element of the frontmost app (not this one), if it is an input box, and the app's pid.
    static func focusedInput() -> (AXUIElement, pid_t)? {
        guard let front = NSWorkspace.shared.frontmostApplication,
              front.processIdentifier != ProcessInfo.processInfo.processIdentifier,
              let e = focused(in: front.processIdentifier), isInput(e) else { return nil }
        return (e, front.processIdentifier)
    }

    static func focused(in pid: pid_t) -> AXUIElement? {
        FocusSnapshot.element(AXUIElementCreateApplication(pid), "AXFocusedUIElement")
    }

    static func isInput(_ e: AXUIElement) -> Bool {
        if let role = FocusSnapshot.value(e, "AXRole") as? String, inputRoles.contains(role) { return true }
        var settable: DarwinBoolean = false
        return AXUIElementIsAttributeSettable(e, kAXSelectedTextAttribute as CFString, &settable) == .success
            && settable.boolValue
    }

    /// a. Replaces the box's selected text through Accessibility; the result if the text went in, nil if not.
    static func setSelectedText(_ text: String, _ e: AXUIElement) -> Result? {
        let before = length(e)
        guard AXUIElementSetAttributeValue(e, kAXSelectedTextAttribute as CFString, text as CFString) == .success
        else { return nil }
        guard let b = before else { return .accessibilityUnchecked }
        return grew(e, from: b) ? .accessibility : nil
    }

    /// b. Cmd+V into the box: to the frontmost app if the box's app is in front, else to that app in the background.
    /// Only while the app's own focus is in the box. The result if the text went in, nil if not.
    static func pasteInto(_ box: AXUIElement, pid: pid_t, _ text: String) -> Result? {
        guard let now = focused(in: pid), CFEqual(now, box) else { return nil }
        let front = NSWorkspace.shared.frontmostApplication?.processIdentifier == pid
        let before = length(box)
        withText(text) { paste(to: front ? nil : pid) }
        guard let b = before else { return front ? .pasteUnchecked : nil }
        return grew(box, from: b) ? (front ? .paste : .pasteInBackground) : nil
    }

    /// c. Brings the box's app to the front with the focus in the box, pastes, and takes the speaker back.
    static func bringToFrontAndPaste(_ box: AXUIElement, pid: pid_t, _ text: String) -> Bool {
        guard let app = NSRunningApplication(processIdentifier: pid) else { return false }
        let back = NSWorkspace.shared.frontmostApplication
        let backBox = back.flatMap { focused(in: $0.processIdentifier) }
        app.activate()
        AXUIElementSetAttributeValue(box, kAXFocusedAttribute as CFString, kCFBooleanTrue)
        var ready = false
        let until = Date().addingTimeInterval(1)
        while Date() < until && !ready {
            ready = NSWorkspace.shared.frontmostApplication?.processIdentifier == pid
                && focused(in: pid).map { CFEqual($0, box) } == true
            if !ready { RunLoop.current.run(until: Date().addingTimeInterval(0.05)) }
        }
        let before = length(box)
        if ready { withText(text) { paste(to: nil) } }
        let ok = ready && (before.map { grew(box, from: $0) } ?? true)
        if let back, back.processIdentifier != pid, back.processIdentifier != ProcessInfo.processInfo.processIdentifier {
            back.activate()
            if let backBox { AXUIElementSetAttributeValue(backBox, kAXFocusedAttribute as CFString, kCFBooleanTrue) }
        }
        return ok
    }

    /// Whether the element's text grows past `from` within half a second.
    static func grew(_ e: AXUIElement, from: Int) -> Bool {
        let until = Date().addingTimeInterval(0.5)
        repeat {
            if let n = length(e), n > from { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        } while Date() < until
        return false
    }

    /// The element's text length, read here and not kept: AXNumberOfCharacters, or the length of AXValue.
    static func length(_ e: AXUIElement) -> Int? {
        if let n = FocusSnapshot.value(e, "AXNumberOfCharacters") as? Int { return n }
        if let s = FocusSnapshot.value(e, "AXValue") as? String { return s.utf16.count }
        return nil
    }

    private static var savedClipboard: [[(NSPasteboard.PasteboardType, Data)]]?
    private static var clipboardTurn = 0

    /// Runs `body` with `text` on the clipboard. The clipboard's contents from before the first paste come back a
    /// second after the last one (a background app may read the clipboard late).
    static func withText(_ text: String, _ body: () -> Void) {
        let pb = NSPasteboard.general
        if savedClipboard == nil {
            savedClipboard = (pb.pasteboardItems ?? []).map { item in
                item.types.compactMap { t in item.data(forType: t).map { (t, $0) } }
            }
        }
        pb.clearContents()
        pb.setString(text, forType: .string)
        body()
        clipboardTurn += 1
        let turn = clipboardTurn
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
            guard turn == clipboardTurn, let saved = savedClipboard else { return }
            savedClipboard = nil
            pb.clearContents()
            pb.writeObjects(saved.map { pairs -> NSPasteboardItem in
                let item = NSPasteboardItem()
                for (t, d) in pairs { item.setData(d, forType: t) }
                return item
            })
        }
    }

    /// Cmd+V: to the frontmost app (pid nil), or to the process `pid` even when it is in the background.
    static func paste(to pid: pid_t?) {
        let source = CGEventSource(stateID: .combinedSessionState)
        let v: CGKeyCode = 9  // kVK_ANSI_V
        for down in [true, false] {
            let e = CGEvent(keyboardEventSource: source, virtualKey: v, keyDown: down)
            e?.flags = .maskCommand
            if let pid { e?.postToPid(pid) } else { e?.post(tap: .cghidEventTap) }
        }
    }
}
