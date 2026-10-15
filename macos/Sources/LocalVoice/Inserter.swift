// Puts the text into the element that had the keyboard focus when the dictation started. First through
// Accessibility (the element's selected text is replaced); if the app refuses that, or the text did not appear, and the
// same element still has the focus, by pasting (Cmd+V) with the clipboard restored after it. The text is never typed
// anywhere else: if neither works, it stays in the menu.
import AppKit
import ApplicationServices
import FocusSnapshot

enum Inserter {
    enum Result: String { case accessibility, accessibilityUnchecked, paste, notInserted }

    static func insert(_ text: String, into capture: FocusSnapshot.Capture?) -> (Result, String) {
        guard let element = capture?.focused, let pid = capture?.pid else { return (.notInserted, "no focused element") }
        let before = length(element)
        let err = AXUIElementSetAttributeValue(element, kAXSelectedTextAttribute as CFString, text as CFString)
        if err == .success {
            if let b = before, let a = length(element) {
                if a > b { return (.accessibility, "length \(b) → \(a)") }
            } else {
                return (.accessibilityUnchecked, "the element does not tell its length")
            }
        }
        let why = err == .success ? "the selected text was set, but the length did not grow" : "AX error \(err.rawValue)"
        guard NSWorkspace.shared.frontmostApplication?.processIdentifier == pid,
              let now = FocusSnapshot.element(AXUIElementCreateApplication(pid), "AXFocusedUIElement"),
              CFEqual(now, element) else {
            return (.notInserted, "\(why); the focus has moved")
        }
        paste(text)
        return (.paste, why)
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
