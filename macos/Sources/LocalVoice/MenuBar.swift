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
    func choose(language: String)
    func enable(adapter: String, _ on: Bool)
    func openLog()
    func openLabeling()
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
        menu.addItem(submenu("Model: " + (s.config.model ?? "none"), modelItems(s)))
        menu.addItem(submenu("Language: " + languageName(s), languageItems(s)))
        let on = (s.server?.adapters ?? []).filter { s.config.adapters[$0.name] == true }
        let failing = on.contains { $0.error != nil } ? " (one does not work)" : ""
        menu.addItem(submenu("Adapters: " + (on.isEmpty ? "none" : on.map(\.name).joined(separator: ", ")) + failing,
                             adapterItems(s)))
        menu.addItem(.separator())
        menu.addItem(action("Label Recordings…") { $0.openLabeling() })
        menu.addItem(action("Open the Log") { $0.openLog() })
        menu.addItem(NSMenuItem(title: "Quit Local Voice", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
    }

    private func modelItems(_ s: MenuState) -> [NSMenuItem] {
        var items = s.config.models.map { name in checked(action(name) { $0.choose(model: name) }, name == s.config.model) }
        if let e = s.config.error { items.append(disabled(e)) }
        return items
    }

    /// The config's language without a region ("ru" of "ru-RU"), as the server reads it.
    private func code(_ s: MenuState) -> String { String(s.config.language.prefix(while: { $0 != "-" })) }

    private func languageName(_ s: MenuState) -> String {
        if s.config.language.isEmpty { return "the speech's own" }
        return s.server?.languages.first { $0.code == code(s) }?.name ?? s.config.language
    }

    private func languageItems(_ s: MenuState) -> [NSMenuItem] {
        var items = [checked(action("The Speech's Own Language") { $0.choose(language: "") }, s.config.language.isEmpty),
                     .separator()]
        let languages = s.server?.languages ?? []
        items += languages.map { l in checked(action(l.name) { $0.choose(language: l.code) }, l.code == code(s)) }
        if !s.config.language.isEmpty, !languages.contains(where: { $0.code == code(s) }) {
            let note = s.server == nil ? "the server has not answered yet" : "the server's prompt does not name it"
            items.append(checked(disabled("\(s.config.language) (\(note))"), true))
        }
        return items
    }

    private func adapterItems(_ s: MenuState) -> [NSMenuItem] {
        guard let server = s.server else { return [disabled("The server has not answered yet.")] }
        guard !server.adapters.isEmpty else { return [disabled("The server has no adapters.")] }
        var items: [NSMenuItem] = []
        for a in server.adapters {
            let on = s.config.adapters[a.name] == true
            let item = checked(action(a.name) { $0.enable(adapter: a.name, !on) }, on)
            item.toolTip = a.description
            items.append(item)
            if let e = a.error { items.append(disabled("  " + cut(e, Tuning.menuErrorChars))) }
        }
        items += [.separator(), disabled("An adapter gives the model the chat of the app you dictate into."),
                  disabled("With none on, dictation has no context.")]
        return items
    }

    private func submenu(_ title: String, _ items: [NSMenuItem]) -> NSMenuItem {
        let m = NSMenu()
        items.forEach(m.addItem)
        let i = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        i.submenu = m
        return i
    }

    private func checked(_ i: NSMenuItem, _ on: Bool) -> NSMenuItem {
        i.state = on ? .on : .off
        return i
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
