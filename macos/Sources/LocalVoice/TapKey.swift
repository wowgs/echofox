// The hotkeys' event monitors; the logic of a tap is TapLogic (LocalVoiceCore). One set of monitors feeds every
// hotkey (dictation, private dictation). Watching keys in other apps needs the Accessibility permission; when it is
// taken away the monitors stop (stop()) and start again when it is back.
import AppKit
import LocalVoiceCore

final class TapKey {
    enum Action { case dictation, privateDictation }

    var onTap: (Action) -> Void = { _ in }
    private var logics: [(Action, TapLogic)] = [(.dictation, TapLogic())]
    private var monitors: [Any] = []

    var running: Bool { !monitors.isEmpty }

    /// The keys of the actions, from the config; two actions never share a key (the first keeps it).
    func set(_ keys: [(Action, TapKeyChoice?)]) {
        var taken = Set<TapKeyChoice>()
        logics = keys.compactMap { action, key in
            guard let key, taken.insert(key).inserted else { return nil }
            return (action, TapLogic(key: key))
        }
    }

    func key(of action: Action) -> TapKeyChoice? { logics.first { $0.0 == action }?.1.key }

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
        for i in logics.indices where logics[i].1.feed(event) { onTap(logics[i].0) }
    }
}
