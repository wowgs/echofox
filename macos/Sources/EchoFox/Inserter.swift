// Puts the text where the speaker wants it when the text comes back. The rule (which box, which ways in which order,
// when it stops) is InsertionRule in EchoFoxCore; this is its desk on the Mac: the boxes and apps through
// Accessibility, and the ways to put text in. Each way is checked by the box's text length.
// It runs on a queue of its own, not on the main thread: the waits and the Accessibility calls never block the menu,
// and two insertions never overlap.
import AppKit
import ApplicationServices
import Carbon.HIToolbox
import EchoFoxCore
import FocusSnapshot

final class Inserter {
    typealias Result = InsertionResult

    /// The waits, in seconds. Not tuned: set by hand on 2026-10-15; only Claude Desktop was tried with them.
    enum Wait {
        static let check: TimeInterval = 0.5        // for a way's text to show in the box
        static let background: TimeInterval = 1.5   // the same, for an app in the background
        static let focus: TimeInterval = 1.0        // for the box's app to come to the front with the focus in the box
        static let poll: TimeInterval = 0.05
        static let restore: TimeInterval = 1.0      // before the clipboard comes back (an app may read it late)
        static let accessibility: Float = 1.0       // the longest one Accessibility call may take
    }

    static let shared = Inserter()
    static let inputRoles: Set<String> = ["AXTextArea", "AXTextField", "AXSearchField", "AXComboBox"]
    static let typedChunk = 16  // characters per keyboard event when typing (a keyboard event carries only a few)

    private let queue = DispatchQueue(label: "echofox.insert")
    fileprivate lazy var clipboard = Clipboard(restoreAfter: Wait.restore) { [weak self] body in self?.queue.async(execute: body) }

    private init() {
        AXUIElementSetMessagingTimeout(AXUIElementCreateSystemWide(), Wait.accessibility)
    }

    /// Inserts on the insertion queue and calls `done` on the main thread with what happened.
    func insert(_ text: String, into capture: FocusSnapshot.Capture?, done: @escaping (Result, String) -> Void) {
        queue.async {
            let (r, why) = self.insert(text, into: capture)
            DispatchQueue.main.async { done(r, why) }
        }
    }

    private func insert(_ text: String, into capture: FocusSnapshot.Capture?) -> (Result, String) {
        InsertionRule.insert(text, tapBox: capture?.focused, tapPid: capture?.pid, on: self)
    }

    // MARK: The ways

    /// a. Replaces the box's selected text through Accessibility; the result if the text went in, nil if not.
    func setSelectedText(_ text: String, _ e: AXUIElement) -> Result? {
        let before = Self.length(e)
        guard AXUIElementSetAttributeValue(e, kAXSelectedTextAttribute as CFString, text as CFString) == .success
        else { return nil }
        guard let b = before else { return .accessibilityUnchecked }
        return Self.grew(e, from: b, within: Wait.check) ? .accessibility : nil
    }

    /// b. Cmd+V into the box: to the frontmost app if the box's app is in front, else to that app in the background.
    /// Only while the app's own focus is in the box, unless `anyFocus`. In front, the paste counts as done (.paste if
    /// the box grew, .pasteUnchecked if not); in the background, the result if the text went in, nil if not.
    private func pasteInto(_ box: AXUIElement, pid: pid_t, _ text: String, anyFocus: Bool = false) -> Result? {
        guard anyFocus || Self.focused(in: pid).map({ CFEqual($0, box) }) == true else { return nil }
        let front = NSWorkspace.shared.frontmostApplication?.processIdentifier == pid
        let before = Self.length(box)
        clipboard.lend(text) { Self.paste(to: front ? nil : pid) }
        if front {
            return before.map { Self.grew(box, from: $0, within: Wait.check) } == true ? .paste : .pasteUnchecked
        }
        guard let b = before else { return nil }
        return Self.grew(box, from: b, within: Wait.background) ? .pasteInBackground : nil
    }

    /// c. The box's whole value through Accessibility, only if the box is empty. The result if the text went in.
    func setValueIfEmpty(_ text: String, _ box: AXUIElement) -> Result? {
        guard Self.isEmpty(box), let before = Self.length(box) else { return nil }
        var settable: DarwinBoolean = false
        guard AXUIElementIsAttributeSettable(box, kAXValueAttribute as CFString, &settable) == .success,
              settable.boolValue,
              AXUIElementSetAttributeValue(box, kAXValueAttribute as CFString, text as CFString) == .success
        else { return nil }
        // An empty box may still count a character (Claude Desktop's: 1), so the check is against its own length.
        return Self.grew(box, from: before, within: Wait.background) || Self.holds(box, text) ? .valueInBackground : nil
    }

    /// c. Cmd+V as keyboard events through Accessibility to the box's app (AXUIElementPostKeyboardEvent, deprecated
    /// since macOS 10.9 and not offered to Swift, so looked up by name). The result if the text went in.
    private func axPaste(_ text: String, into box: AXUIElement, pid: pid_t) -> Result? {
        guard let before = Self.length(box), let post = Self.postKeyboardEvent else { return nil }
        let app = AXUIElementCreateApplication(pid)
        var ok = true
        clipboard.lend(text) {
            for (key, down) in [(CGKeyCode(kVK_Command), true), (CGKeyCode(kVK_ANSI_V), true),
                                (CGKeyCode(kVK_ANSI_V), false), (CGKeyCode(kVK_Command), false)] {
                ok = ok && post(app, 0, key, DarwinBoolean(down)) == .success
            }
        }
        return ok && Self.grew(box, from: before, within: Wait.background) ? .axKeysInBackground : nil
    }

    private typealias PostKey = @convention(c) (AXUIElement, CGCharCode, CGKeyCode, DarwinBoolean) -> AXError
    private static let postKeyboardEvent: PostKey? = {
        guard let sym = dlsym(dlopen(nil, RTLD_NOW), "AXUIElementPostKeyboardEvent") else { return nil }
        return unsafeBitCast(sym, to: PostKey.self)
    }()

    /// c. The text as typed characters, sent to the box's app in the background. The result if the text went in.
    func type(_ text: String, into box: AXUIElement, pid: pid_t) -> Result? {
        guard let before = Self.length(box) else { return nil }
        let source = CGEventSource(stateID: .combinedSessionState)
        let units = Array(text.utf16)
        for start in stride(from: 0, to: units.count, by: Self.typedChunk) {
            let chunk = Array(units[start..<min(start + Self.typedChunk, units.count)])
            for down in [true, false] {
                let e = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: down)
                e?.flags = []
                chunk.withUnsafeBufferPointer { e?.keyboardSetUnicodeString(stringLength: chunk.count, unicodeString: $0.baseAddress) }
                e?.postToPid(pid)
            }
        }
        return Self.grew(box, from: before, within: Wait.background) ? .typedInBackground : nil
    }

    /// d. Brings the box's app to the front with the focus in the box, pastes, and takes the speaker back to the app
    /// and box they were in (another box of the same app too). Nil if the box did not get the focus, and nothing was
    /// sent; else the paste counts as done, as in b.
    private func bringToFrontAndPaste(_ box: AXUIElement, pid: pid_t, _ text: String) -> Result? {
        guard let app = NSRunningApplication(processIdentifier: pid) else { return nil }
        let back = NSWorkspace.shared.frontmostApplication
        let backBox = back.flatMap { Self.focused(in: $0.processIdentifier) }
        app.activate()
        AXUIElementSetAttributeValue(box, kAXFocusedAttribute as CFString, kCFBooleanTrue)
        let ready = Self.within(Wait.focus) {
            NSWorkspace.shared.frontmostApplication?.processIdentifier == pid
                && Self.focused(in: pid).map { CFEqual($0, box) } == true
        }
        let before = Self.length(box)
        var r: Result?
        if ready {
            clipboard.lend(text) { Self.paste(to: nil) }
            r = before.map { Self.grew(box, from: $0, within: Wait.check) } == true
                ? .pasteBroughtToFront : .pasteBroughtToFrontUnchecked
        }
        if let back, back.processIdentifier != ProcessInfo.processInfo.processIdentifier {
            if back.processIdentifier != pid { back.activate() }
            if let backBox, !CFEqual(backBox, box) {
                AXUIElementSetAttributeValue(backBox, kAXFocusedAttribute as CFString, kCFBooleanTrue)
            }
        }
        return r
    }

    // MARK: Accessibility helpers

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

    /// An empty box: its text is only spaces and line ends. Read, not kept.
    static func isEmpty(_ box: AXUIElement) -> Bool {
        if let s = FocusSnapshot.value(box, "AXValue") as? String {
            return s.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
        return length(box) == 0
    }

    /// Whether the box's text is `text` (spaces and line ends aside). Read, not kept.
    static func holds(_ box: AXUIElement, _ text: String) -> Bool {
        (FocusSnapshot.value(box, "AXValue") as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
            == text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// An element's role and description, for the log; never its value.
    static func describe(_ e: AXUIElement) -> String {
        [FocusSnapshot.value(e, "AXRole") as? String, FocusSnapshot.value(e, "AXDescription") as? String]
            .compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " ")
    }

    /// The element's text length, read here and not kept: AXNumberOfCharacters, or the length of AXValue.
    static func length(_ e: AXUIElement) -> Int? {
        if let n = FocusSnapshot.value(e, "AXNumberOfCharacters") as? Int { return n }
        if let s = FocusSnapshot.value(e, "AXValue") as? String { return s.utf16.count }
        return nil
    }

    static func grew(_ e: AXUIElement, from: Int, within seconds: TimeInterval) -> Bool {
        within(seconds) { (length(e) ?? from) > from }
    }

    /// Whether `condition` holds within `seconds`, checked every Wait.poll. On the insertion queue, not the main one.
    static func within(_ seconds: TimeInterval, _ condition: () -> Bool) -> Bool {
        let until = Date().addingTimeInterval(seconds)
        repeat {
            if condition() { return true }
            Thread.sleep(forTimeInterval: Wait.poll)
        } while Date() < until
        return condition()
    }

    /// Cmd+V: to the frontmost app (pid nil), or to the process `pid` even when it is in the background.
    static func paste(to pid: pid_t?) {
        let source = CGEventSource(stateID: .combinedSessionState)
        for down in [true, false] {
            let e = CGEvent(keyboardEventSource: source, virtualKey: CGKeyCode(kVK_ANSI_V), keyDown: down)
            e?.flags = .maskCommand
            if let pid { e?.postToPid(pid) } else { e?.post(tap: .cghidEventTap) }
        }
    }
}

/// The Mac's side of InsertionRule: the static Accessibility helpers and the ways above.
extension Inserter: InsertionDesk {
    func isInput(_ box: AXUIElement) -> Bool { Self.isInput(box) }
    func length(_ box: AXUIElement) -> Int? { Self.length(box) }
    func isFront(_ pid: Int32) -> Bool { NSWorkspace.shared.frontmostApplication?.processIdentifier == pid }
    func focused(in pid: Int32) -> AXUIElement? { Self.focused(in: pid) }
    func same(_ a: AXUIElement, _ b: AXUIElement) -> Bool { CFEqual(a, b) }
    func describe(_ box: AXUIElement) -> String { Self.describe(box) }
    func focusedInput() -> (box: AXUIElement, pid: Int32)? { Self.focusedInput().map { ($0.0, $0.1) } }
    func paste(_ text: String, into box: AXUIElement, pid: Int32, anyFocus: Bool) -> Result? {
        pasteInto(box, pid: pid, text, anyFocus: anyFocus)
    }
    func keysPaste(_ text: String, into box: AXUIElement, pid: Int32) -> Result? { axPaste(text, into: box, pid: pid) }
    func bringToFrontAndPaste(_ text: String, into box: AXUIElement, pid: Int32) -> Result? {
        bringToFrontAndPaste(box, pid: pid, text)
    }
    func pasteAtCursor(_ text: String) { clipboard.lend(text) { Self.paste(to: nil) } }
    func keep(_ text: String) { clipboard.keep(text) }
}
