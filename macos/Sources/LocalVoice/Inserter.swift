// Puts the text where the speaker wants it when the text comes back (Alex's rule, 2026-10-15):
//   1. if an input box had the focus at the tap: into that box, wherever the speaker went meanwhile;
//   2. otherwise the input box that has the focus now (the speaker clicked into it while talking);
//   3. otherwise, if the app of the tap is still in front and tells nothing of its focus (an Electron app whose tree no
//      adapter needs), a paste where its cursor is;
//   4. otherwise the clipboard (and the menu).
// Into a box, the ways are tried in this order; each is checked by the box's text length, and the first that works
// wins. Before each next way, the box is checked again: a way that landed late counts, and no text goes in twice.
//   a. Accessibility: the box's selected text is replaced. Claude Desktop's box reports success and changes nothing
//      (2026-10-15).
//   b. Cmd+V: to the frontmost app if the box is in it, else to the box's app in the background (CGEventPostToPid),
//      unless that app's focus is in another box. In the background, Claude Desktop did not take it (2026-10-15).
//   c. In the background, without the focus: the box's value through Accessibility, only for an empty box (a draft
//      could lose its formatting); then Cmd+V through Accessibility; then the text typed into the app's process.
//   d. The box's app comes to the front, Cmd+V, and the speaker is taken back to the app and box they were in.
// It runs on a queue of its own, not on the main thread: the waits and the Accessibility calls never block the menu,
// and two insertions never overlap.
import AppKit
import ApplicationServices
import Carbon.HIToolbox
import FocusSnapshot

final class Inserter {
    enum Result: String {
        case accessibility, accessibilityUnchecked, paste, pasteUnchecked, pasteInBackground, valueInBackground,
             typedInBackground, axKeysInBackground, pasteBroughtToFront, clipboard, late
    }

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

    private let queue = DispatchQueue(label: "local-voice.insert")
    private let clipboard = Clipboard()

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
        if let box = capture?.focused, let pid = capture?.pid, Self.isInput(box) {
            var tried: [String] = []
            let note = { (r: Result) in (r, "the input box of the tap" + (tried.isEmpty ? "" : "; " + tried.joined(separator: ", "))) }
            let baseline = Self.length(box)
            let landed = { baseline.map { b in (Self.length(box) ?? b) > b } ?? false }
            if let r = setSelectedText(text, box) { return note(r) }
            tried.append("selected text: no")
            let front = NSWorkspace.shared.frontmostApplication?.processIdentifier == pid
            let appFocus = Self.focused(in: pid)
            // In the background, Desktop's accessibility focus is not its box any more (2026-10-15), while the page's
            // own focus stays where the speaker left it. So the background ways are tried unless the app's focus is
            // in another input box.
            let otherBox = appFocus.map { !CFEqual($0, box) && Self.isInput($0) } ?? false
            tried.append("the app's focus: \(appFocus.map(Self.describe) ?? "none"), the box's length: \(baseline.map(String.init) ?? "unknown")")
            if landed() { return note(.late) }
            if let r = pasteInto(box, pid: pid, text, anyFocus: !front && !otherBox) { return note(r) }
            tried.append("cmd+v\(front ? "" : " in the background"): \(otherBox ? "skipped, focus in another box" : "no")")
            if !front && !otherBox {
                let ways: [(String, () -> Result?)] = [
                    ("value", { self.setValueIfEmpty(text, box) }),
                    ("accessibility keys", { self.axPaste(text, into: box, pid: pid) }),
                    ("typing", { self.type(text, into: box, pid: pid) })]
                for (name, way) in ways {
                    if landed() { return note(.late) }
                    if let r = way() { return note(r) }
                    tried.append("\(name): no")
                }
            }
            if landed() { return note(.late) }
            if bringToFrontAndPaste(box, pid: pid, text) {
                return (.pasteBroughtToFront, "the input box of the tap, brought to the front and back; " + tried.joined(separator: ", "))
            }
        }
        if let (now, pid) = Self.focusedInput() {
            if let r = setSelectedText(text, now) { return (r, "the input box focused at the end") }
            if let r = pasteInto(now, pid: pid, text) { return (r, "the input box focused at the end") }
        }
        // An app that tells nothing through Accessibility (an Electron app without its tree, in the base mode): the
        // text goes where its cursor is, by a paste, if it is still the app in front.
        if let pid = capture?.pid, capture?.focused == nil,
           NSWorkspace.shared.frontmostApplication?.processIdentifier == pid, Self.focused(in: pid) == nil {
            clipboard.lend(text) { Self.paste(to: nil) }
            return (.pasteUnchecked, "the app of the tap, which tells nothing of its input box")
        }
        clipboard.keep(text)
        return (.clipboard, "no input box at the tap or now, or the text did not go in")
    }

    // MARK: The ways

    /// a. Replaces the box's selected text through Accessibility; the result if the text went in, nil if not.
    private func setSelectedText(_ text: String, _ e: AXUIElement) -> Result? {
        let before = Self.length(e)
        guard AXUIElementSetAttributeValue(e, kAXSelectedTextAttribute as CFString, text as CFString) == .success
        else { return nil }
        guard let b = before else { return .accessibilityUnchecked }
        return Self.grew(e, from: b, within: Wait.check) ? .accessibility : nil
    }

    /// b. Cmd+V into the box: to the frontmost app if the box's app is in front, else to that app in the background.
    /// Only while the app's own focus is in the box, unless `anyFocus`. The result if the text went in, nil if not.
    private func pasteInto(_ box: AXUIElement, pid: pid_t, _ text: String, anyFocus: Bool = false) -> Result? {
        guard anyFocus || Self.focused(in: pid).map({ CFEqual($0, box) }) == true else { return nil }
        let front = NSWorkspace.shared.frontmostApplication?.processIdentifier == pid
        let before = Self.length(box)
        clipboard.lend(text) { Self.paste(to: front ? nil : pid) }
        guard let b = before else { return front ? .pasteUnchecked : nil }
        return Self.grew(box, from: b, within: front ? Wait.check : Wait.background)
            ? (front ? .paste : .pasteInBackground) : nil
    }

    /// c. The box's whole value through Accessibility, only if the box is empty. The result if the text went in.
    private func setValueIfEmpty(_ text: String, _ box: AXUIElement) -> Result? {
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
    private func type(_ text: String, into box: AXUIElement, pid: pid_t) -> Result? {
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

    /// d. Brings the box's app to the front with the focus in the box, pastes, and takes the speaker back.
    private func bringToFrontAndPaste(_ box: AXUIElement, pid: pid_t, _ text: String) -> Bool {
        guard let app = NSRunningApplication(processIdentifier: pid) else { return false }
        let back = NSWorkspace.shared.frontmostApplication
        let backBox = back.flatMap { Self.focused(in: $0.processIdentifier) }
        app.activate()
        AXUIElementSetAttributeValue(box, kAXFocusedAttribute as CFString, kCFBooleanTrue)
        let ready = Self.within(Wait.focus) {
            NSWorkspace.shared.frontmostApplication?.processIdentifier == pid
                && Self.focused(in: pid).map { CFEqual($0, box) } == true
        }
        let before = Self.length(box)
        if ready { clipboard.lend(text) { Self.paste(to: nil) } }
        let ok = ready && (before.map { Self.grew(box, from: $0, within: Wait.check) } ?? true)
        if let back, back.processIdentifier != pid, back.processIdentifier != ProcessInfo.processInfo.processIdentifier {
            back.activate()
            if let backBox { AXUIElementSetAttributeValue(backBox, kAXFocusedAttribute as CFString, kCFBooleanTrue) }
        }
        return ok
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

/// The clipboard, lent for a paste and given back. The speaker's own contents come back Wait.restore after the last
/// paste, and only if nobody changed the clipboard meanwhile (the speaker may copy something in that second). Lent
/// text is marked transient (org.nspasteboard.TransientType), so clipboard managers do not keep it. Used only on the
/// insertion queue.
final class Clipboard {
    static let transient = NSPasteboard.PasteboardType("org.nspasteboard.TransientType")
    private let pb = NSPasteboard.general
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
        DispatchQueue.global().asyncAfter(deadline: .now() + Inserter.Wait.restore) { [weak self] in
            Inserter.shared.run { self?.restore(mine) }
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

extension Inserter {
    /// Runs `body` on the insertion queue, after any insertion that runs now.
    func run(_ body: @escaping () -> Void) { queue.async(execute: body) }
}
