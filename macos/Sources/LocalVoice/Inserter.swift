// Puts the text where the speaker wants it when the text comes back (Alex's rule, 2026-10-15):
//   1. if an input box had the focus at the tap: into that box, wherever the speaker went meanwhile;
//   2. otherwise the input box that has the focus now (the speaker clicked into it while talking);
//   3. otherwise, if the app of the tap is still in front and tells nothing of its focus (an Electron app whose tree no
//      adapter needs), a paste where its cursor is;
//   4. otherwise the clipboard (and the menu).
// Into a box, the ways are tried in this order, each checked by the box's text length, and the first that works wins:
//   a. Accessibility: the box's selected text is replaced. Claude Desktop's box reports success and changes nothing
//      (2026-10-15).
//   b. Cmd+V: to the frontmost app if the box is in it, else to the box's app in the background (CGEventPostToPid),
//      if that app's own focus is still in the box; the clipboard is restored after it. In the background, Claude
//      Desktop did not take it (2026-10-15).
//   c. In the background, without the focus: the box's value through Accessibility, only for an empty box (a draft in
//      the box could lose its formatting); then the text typed as characters into the box's app (CGEventPostToPid).
//   d. The box's app comes to the front, Cmd+V, and the speaker is taken back to the app and box they were in.
import AppKit
import ApplicationServices
import FocusSnapshot

enum Inserter {
    enum Result: String {
        case accessibility, accessibilityUnchecked, paste, pasteUnchecked, pasteInBackground, valueInBackground,
             typedInBackground, axKeysInBackground, pasteBroughtToFront, clipboard
    }

    static let inputRoles: Set<String> = ["AXTextArea", "AXTextField", "AXSearchField", "AXComboBox"]

    static func insert(_ text: String, into capture: FocusSnapshot.Capture?) -> (Result, String) {
        if let box = capture?.focused, let pid = capture?.pid, isInput(box) {
            var tried: [String] = []
            let note = { (r: Result) in (r, "the input box of the tap" + (tried.isEmpty ? "" : "; \(tried.joined(separator: ", "))")) }
            if let r = setSelectedText(text, box) { return note(r) }
            tried.append("selected text: no")
            let front = NSWorkspace.shared.frontmostApplication?.processIdentifier == pid
            let appFocus = focused(in: pid)
            // In the background, Desktop's accessibility focus is not its box any more (2026-10-15), while the page's
            // own focus stays where the speaker left it. So the background ways are tried unless the app's focus is
            // in another input box.
            let otherBox = appFocus.map { !CFEqual($0, box) && isInput($0) } ?? false
            tried.append("the app's focus: \(appFocus.map(describe) ?? "none"), the box's length: \(length(box).map(String.init) ?? "unknown")")
            if let r = pasteInto(box, pid: pid, text, anyFocus: !front && !otherBox) { return note(r) }
            tried.append("cmd+v\(front ? "" : " in the background"): \(otherBox ? "skipped, focus in another box" : "no")")
            if !front && !otherBox {
                if let r = setValueIfEmpty(text, box) { return note(r) }
                tried.append("value: \(isEmpty(box) ? "no" : "skipped, the box is not empty")")
                if let r = axPaste(text, into: box, pid: pid) { return note(r) }
                tried.append("accessibility keys: no")
                if let r = type(text, into: box, pid: pid) { return note(r) }
                tried.append("typing: no")
            }
            if bringToFrontAndPaste(box, pid: pid, text) {
                return (.pasteBroughtToFront, "the input box of the tap, brought to the front and back; " + tried.joined(separator: ", "))
            }
        }
        if let (now, pid) = focusedInput() {
            if let r = setSelectedText(text, now) { return (r, "the input box focused at the end") }
            if let r = pasteInto(now, pid: pid, text) { return (r, "the input box focused at the end") }
        }
        // An app that tells nothing through Accessibility (an Electron app without its tree, in the base mode): the
        // text goes where its cursor is, by a paste, if it is still the app in front.
        if let pid = capture?.pid, capture?.focused == nil,
           NSWorkspace.shared.frontmostApplication?.processIdentifier == pid, focused(in: pid) == nil {
            withText(text) { paste(to: nil) }
            return (.pasteUnchecked, "the app of the tap, which tells nothing of its input box")
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
    static func pasteInto(_ box: AXUIElement, pid: pid_t, _ text: String, anyFocus: Bool = false) -> Result? {
        guard anyFocus || focused(in: pid).map({ CFEqual($0, box) }) == true else { return nil }
        let front = NSWorkspace.shared.frontmostApplication?.processIdentifier == pid
        let before = length(box)
        withText(text) { paste(to: front ? nil : pid) }
        guard let b = before else { return front ? .pasteUnchecked : nil }
        return grew(box, from: b) ? (front ? .paste : .pasteInBackground) : nil
    }

    /// c. The box's whole value through Accessibility, only if the box is empty. The result if the text went in.
    static func setValueIfEmpty(_ text: String, _ box: AXUIElement) -> Result? {
        guard isEmpty(box) else { return nil }
        var settable: DarwinBoolean = false
        guard AXUIElementIsAttributeSettable(box, kAXValueAttribute as CFString, &settable) == .success,
              settable.boolValue,
              AXUIElementSetAttributeValue(box, kAXValueAttribute as CFString, text as CFString) == .success
        else { return nil }
        return grew(box, from: 1) ? .valueInBackground : nil
    }

    /// An empty box: its text is only spaces and line ends (Claude Desktop's empty box has length 1). Read, not kept.
    static func isEmpty(_ box: AXUIElement) -> Bool {
        if let s = FocusSnapshot.value(box, "AXValue") as? String {
            return s.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
        return length(box) == 0
    }

    /// c. Cmd+V as keyboard events through Accessibility to the box's app (AXUIElementPostKeyboardEvent, deprecated
    /// since macOS 10.9, still in the SDK). The result if the text went in.
    static func axPaste(_ text: String, into box: AXUIElement, pid: pid_t) -> Result? {
        guard let before = length(box) else { return nil }
        typealias PostKey = @convention(c) (AXUIElement, CGCharCode, CGKeyCode, DarwinBoolean) -> AXError
        guard let sym = dlsym(UnsafeMutableRawPointer(bitPattern: -2), "AXUIElementPostKeyboardEvent") else { return nil }
        let post = unsafeBitCast(sym, to: PostKey.self)  // unavailable in Swift since it is deprecated (RTLD_DEFAULT = -2)
        let app = AXUIElementCreateApplication(pid)
        var ok = true
        withText(text) {
            for (key, down) in [(CGKeyCode(55), true), (9, true), (9, false), (55, false)] {  // Command, V
                ok = ok && post(app, 0, key, DarwinBoolean(down)) == .success
            }
        }
        return ok && grew(box, from: before, within: 1) ? .axKeysInBackground : nil
    }

    /// c. The text as typed characters, sent to the box's app in the background. The result if the text went in.
    static func type(_ text: String, into box: AXUIElement, pid: pid_t) -> Result? {
        guard let before = length(box) else { return nil }
        let source = CGEventSource(stateID: .combinedSessionState)
        let units = Array(text.utf16)
        var i = 0
        while i < units.count {
            let chunk = Array(units[i..<min(i + 16, units.count)])  // a keyboard event carries a few characters
            for down in [true, false] {
                let e = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: down)
                e?.flags = []
                chunk.withUnsafeBufferPointer { e?.keyboardSetUnicodeString(stringLength: chunk.count, unicodeString: $0.baseAddress) }
                e?.postToPid(pid)
            }
            i += 16
        }
        return grew(box, from: before, within: 1.5) ? .typedInBackground : nil
    }

    /// d. Brings the box's app to the front with the focus in the box, pastes, and takes the speaker back.
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

    /// An element's role and description, for the log; never its value.
    static func describe(_ e: AXUIElement) -> String {
        [FocusSnapshot.value(e, "AXRole") as? String, FocusSnapshot.value(e, "AXDescription") as? String]
            .compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " ")
    }

    /// Whether the element's text grows past `from` within `seconds`.
    static func grew(_ e: AXUIElement, from: Int, within seconds: TimeInterval = 0.5) -> Bool {
        let until = Date().addingTimeInterval(seconds)
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
