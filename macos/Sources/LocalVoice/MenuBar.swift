// The menu bar item: an icon for the state, and the menu built from the state each time it opens. It shows; it never
// decides: the actions go back to the App.
import AppKit
import AVFoundation
import LocalVoiceCore

struct MenuState {
    var recording = false, waiting = false
    var accessibility = false, microphone = AVAuthorizationStatus.notDetermined
    var keyName = ""
    var lastText: String?, lastNote: String?, lastError: String?
    var config = Config()
    var server: ServerInfo?, serverProblem: String?
}

protocol MenuActions: AnyObject {
    func allowAccessibility()
    func allowMicrophone()
    func copyLastText()
    func choose(model: String)
    func openLog()
}

final class MenuBar: NSObject, NSMenuDelegate {
    private let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
    private weak var actions: MenuActions?
    var state: () -> MenuState = { MenuState() }

    init(actions: MenuActions) {
        self.actions = actions
        super.init()
        let menu = NSMenu()
        menu.delegate = self
        item.menu = menu
    }

    func update() {
        let s = state()
        let symbol: String, tint: NSColor?
        if s.recording {
            (symbol, tint) = ("mic.fill", .systemRed)
        } else if s.waiting {
            (symbol, tint) = ("ellipsis.circle", nil)
        } else if !s.accessibility || s.microphone != .authorized || s.lastError != nil || s.serverProblem != nil {
            (symbol, tint) = ("mic.slash", nil)
        } else {
            (symbol, tint) = ("mic", nil)
        }
        let image = NSImage(systemSymbolName: symbol, accessibilityDescription: "Local Voice")
        image?.isTemplate = true
        item.button?.image = image
        item.button?.contentTintColor = tint
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        let s = state()
        menu.removeAllItems()
        handlers.removeAll()
        let status: String
        if s.recording {
            status = "Recording. Tap \(s.keyName) to stop."
        } else if s.waiting {
            status = "Waiting for the text."
        } else if !s.accessibility {
            status = "Needs the Accessibility permission."
        } else if s.microphone != .authorized {
            status = "Needs the Microphone permission."
        } else {
            status = "Ready. Tap \(s.keyName) to dictate."
        }
        menu.addItem(disabled(status))
        if !s.accessibility { menu.addItem(action("Allow Accessibility…") { $0.allowAccessibility() }) }
        if s.microphone == .denied || s.microphone == .restricted || s.microphone == .notDetermined && s.accessibility {
            menu.addItem(action("Allow the Microphone…") { $0.allowMicrophone() })
        }
        if let t = s.lastText {
            menu.addItem(action("Copy the last text: “\(cut(t, Tuning.menuTextChars))”") { $0.copyLastText() })
        }
        if let n = s.lastNote { menu.addItem(disabled(n)) }
        if let e = s.lastError { menu.addItem(disabled("Last error: " + cut(e, Tuning.menuErrorChars))) }
        if let p = s.serverProblem { menu.addItem(disabled("Server: " + cut(p, Tuning.menuErrorChars))) }
        menu.addItem(.separator())
        let models = NSMenu()
        for name in s.config.models {
            let m = action(name) { $0.choose(model: name) }
            m.state = name == s.config.model ? .on : .off
            models.addItem(m)
        }
        if let e = s.config.error { models.addItem(disabled(e)) }
        let modelItem = NSMenuItem(title: "Model", action: nil, keyEquivalent: "")
        modelItem.submenu = models
        menu.addItem(modelItem)
        menu.addItem(disabled("Language: \(s.config.language.isEmpty ? "the speech's own" : s.config.language)"))
        let on = (s.server?.adapters ?? []).filter(\.enabled).map(\.name)
        menu.addItem(disabled("Adapters: " + (on.isEmpty ? "none (dictation without context)" : on.joined(separator: ", "))))
        for a in s.server?.adapters ?? [] {
            if let e = a.error { menu.addItem(disabled("Adapter \(a.name): \(cut(e, Tuning.menuErrorChars))")) }
        }
        menu.addItem(.separator())
        menu.addItem(action("Open the Log") { $0.openLog() })
        menu.addItem(NSMenuItem(title: "Quit Local Voice", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
    }

    private func cut(_ s: String, _ n: Int) -> String { s.count > n ? String(s.prefix(n)) + "…" : s }

    private func disabled(_ title: String) -> NSMenuItem {
        let i = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        i.isEnabled = false
        return i
    }

    private var handlers: [ObjectIdentifier: (MenuActions) -> Void] = [:]

    private func action(_ title: String, _ run: @escaping (MenuActions) -> Void) -> NSMenuItem {
        let i = NSMenuItem(title: title, action: #selector(clicked(_:)), keyEquivalent: "")
        i.target = self
        handlers[ObjectIdentifier(i)] = run
        return i
    }

    @objc private func clicked(_ sender: NSMenuItem) {
        guard let actions, let run = handlers[ObjectIdentifier(sender)] else { return }
        run(actions)
    }
}
