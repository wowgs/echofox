// The hotkey's event monitors; the logic of a tap is TapLogic (LocalVoiceCore). Watching keys in other apps needs the
// Accessibility permission; when it is taken away the monitors stop (stop()) and start again when it is back.
import AppKit
import LocalVoiceCore

final class TapKey {
    var onTap: () -> Void = {}
    private var logic = TapLogic()
    private var monitors: [Any] = []

    var keyName: String { logic.keyName }
    var running: Bool { !monitors.isEmpty }

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

    func stop() {
        monitors.forEach(NSEvent.removeMonitor)
        monitors.removeAll()
    }

    private func handle(_ e: NSEvent) {
        let event: TapLogic.Event = e.type == .flagsChanged
            ? .flags(keyCode: e.keyCode, raw: e.modifierFlags.rawValue, timestamp: e.timestamp) : .keyOrClick
        if logic.feed(event) { onTap() }
    }
}
