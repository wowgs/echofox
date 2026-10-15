// The hotkey: one tap of a modifier key alone (the right Option by default), pressed and released with no other
// key, modifier or click in between. Watching keys in other apps needs the Accessibility permission.
import AppKit

final class TapKey {
    static let rightOption: UInt16 = 61  // kVK_RightOption
    static let rightOptionMask: UInt = 0x40  // NX_DEVICERALTKEYMASK: the right Option is down
    static let leftOptionMask: UInt = 0x20  // NX_DEVICELALTKEYMASK
    static let longestTap: TimeInterval = 0.6

    var onTap: () -> Void = {}
    private var downAt: TimeInterval?
    private var spoiled = false
    private var monitors: [Any] = []

    func start() {
        guard monitors.isEmpty else { return }
        let mask: NSEvent.EventTypeMask = [.flagsChanged, .keyDown, .leftMouseDown, .rightMouseDown, .otherMouseDown]
        if let m = NSEvent.addGlobalMonitorForEvents(matching: mask, handler: { [weak self] e in self?.handle(e) }) {
            monitors.append(m)
        }
        if let m = NSEvent.addLocalMonitorForEvents(matching: mask, handler: { [weak self] e in self?.handle(e); return e }) {
            monitors.append(m)
        }
    }

    private func handle(_ e: NSEvent) {
        guard e.type == .flagsChanged else {
            if downAt != nil { spoiled = true }
            return
        }
        let raw = e.modifierFlags.rawValue
        if e.keyCode == TapKey.rightOption {
            if raw & TapKey.rightOptionMask != 0 {
                downAt = e.timestamp
                spoiled = !e.modifierFlags.intersection([.command, .control, .shift]).isEmpty
                    || raw & TapKey.leftOptionMask != 0
            } else if let d = downAt {
                downAt = nil
                if !spoiled && e.timestamp - d <= TapKey.longestTap { onTap() }
            }
        } else if downAt != nil {
            spoiled = true
        }
    }
}
