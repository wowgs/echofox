// Puts the text where the speaker wants it when the text comes back (Alex's rule, 2026-10-15):
//   1. the input box that has the focus now, if there is one: the speaker may have clicked into it while talking;
//   2. otherwise the input box that had the focus when the dictation started: its app comes to the front again;
//   3. otherwise the clipboard (and the menu).
// Into an input box, the text goes through Accessibility first (its selected text is replaced). Claude Desktop's box
// reports success and changes nothing (2026-10-15), so the text then goes by a paste (Cmd+V), with the clipboard
// restored after it.
import AppKit
import ApplicationServices
import FocusSnapshot

enum Inserter {
    enum Result: String { case accessibility, accessibilityUnchecked, paste, clipboard }

    static let inputRoles: Set<String> = ["AXTextArea", "AXTextField", "AXSearchField", "AXComboBox"]

    static func insert(_ text: String, into capture: FocusSnapshot.Capture?) -> (Result, String) {
        if let now = focusedInput() {
            let same = capture?.focused.map { CFEqual($0, now) } ?? false
            let which = same ? "the focused input box, the one of the start" : "the focused input box"
            if let r = setSelectedText(text, now) { return (r, which) }
            paste(text)
            return (.paste, which)
        }
        if let element = capture?.focused, let pid = capture?.pid {
            if let r = setSelectedText(text, element) { return (r, "the input box of the start") }
            if bringBack(element, pid: pid) {
                paste(text)
                return (.paste, "the input box of the start, brought to the front")
            }
        }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        return (.clipboard, capture?.focused == nil ? "no input box, now or at the start"
                                                     : "no input box now, and the one of the start could not be focused")
    }

    /// The focused element of the frontmost app (not this one), if it is an input box.
    static func focusedInput() -> AXUIElement? {
        guard let front = NSWorkspace.shared.frontmostApplication,
              front.processIdentifier != ProcessInfo.processInfo.processIdentifier,
              let e = FocusSnapshot.element(AXUIElementCreateApplication(front.processIdentifier), "AXFocusedUIElement"),
              isInput(e) else { return nil }
        return e
    }

    static func isInput(_ e: AXUIElement) -> Bool {
        if let role = FocusSnapshot.value(e, "AXRole") as? String, inputRoles.contains(role) { return true }
        var settable: DarwinBoolean = false
        return AXUIElementIsAttributeSettable(e, kAXSelectedTextAttribute as CFString, &settable) == .success
            && settable.boolValue
    }

    /// Replaces the element's selected text; the result if the text went in (checked by the element's length when it
    /// tells it), nil if not.
    static func setSelectedText(_ text: String, _ e: AXUIElement) -> Result? {
        let before = length(e)
        guard AXUIElementSetAttributeValue(e, kAXSelectedTextAttribute as CFString, text as CFString) == .success
        else { return nil }
        guard let b = before, let a = length(e) else { return .accessibilityUnchecked }
        return a > b ? .accessibility : nil
    }

    /// Brings the element's app to the front and the focus into the element; true once both hold (up to 1 s).
    static func bringBack(_ e: AXUIElement, pid: pid_t) -> Bool {
        guard let app = NSRunningApplication(processIdentifier: pid) else { return false }
        app.activate()
        AXUIElementSetAttributeValue(e, kAXFocusedAttribute as CFString, kCFBooleanTrue)
        let until = Date().addingTimeInterval(1)
        while Date() < until {
            if NSWorkspace.shared.frontmostApplication?.processIdentifier == pid,
               let now = FocusSnapshot.element(AXUIElementCreateApplication(pid), "AXFocusedUIElement"), CFEqual(now, e) {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        }
        return false
    }

    /// The element's text length, read here and not kept: AXNumberOfCharacters, or the length of AXValue.
    static func length(_ e: AXUIElement) -> Int? {
        if let n = FocusSnapshot.value(e, "AXNumberOfCharacters") as? Int { return n }
        if let s = FocusSnapshot.value(e, "AXValue") as? String { return s.utf16.count }
        return nil
    }

    static func paste(_ text: String) {
        let pb = NSPasteboard.general
        let saved = (pb.pasteboardItems ?? []).map { item in
            item.types.compactMap { t in item.data(forType: t).map { (t, $0) } }
        }
        pb.clearContents()
        pb.setString(text, forType: .string)
        let source = CGEventSource(stateID: .combinedSessionState)
        let v: CGKeyCode = 9  // kVK_ANSI_V
        for down in [true, false] {
            let e = CGEvent(keyboardEventSource: source, virtualKey: v, keyDown: down)
            e?.flags = .maskCommand
            e?.post(tap: .cghidEventTap)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            pb.clearContents()
            pb.writeObjects(saved.map { pairs -> NSPasteboardItem in
                let item = NSPasteboardItem()
                for (t, d) in pairs { item.setData(d, forType: t) }
                return item
            })
        }
    }
}
