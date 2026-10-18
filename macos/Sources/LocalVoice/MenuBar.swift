// The menu bar item: an icon for the state (recording, waiting, a problem), and the menu of the app's configuration,
// built each time it opens. A dictation is the hotkey's, not the menu's. It shows; it never decides: the actions go
// back to the App.
import AppKit
import AVFoundation
import LocalVoiceCore

struct MenuState {
    var recording = false, waiting = false
    var accessibility = false, microphone = AVAuthorizationStatus.notDetermined
    var keyName = ""
    var lastError: String?
    var config = Config()
    var server: ServerInfo?, serverProblem: String?
    /// The recorded microphone's name and input volume (0…1; nil: the device has none to set).
    var microphoneName = "", inputVolume: Float?
}

protocol MenuActions: AnyObject {
    func allowAccessibility()
    func allowMicrophone()
    func choose(model: String)
    func choose(language: String)
    func enable(adapter: String, _ on: Bool)
    func choose(microphone: String)
    func setInputVolume(_ value: Float)
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
        // The menu is configuration; a dictation is the hotkey's, and the icon shows it.
        let needsAccessibility = !s.accessibility
        let needsMicrophone = s.microphone == .denied || s.microphone == .restricted
            || s.microphone == .notDetermined && s.accessibility
        if needsAccessibility { menu.addItem(action("Allow Accessibility…") { $0.allowAccessibility() }) }
        if needsMicrophone { menu.addItem(action("Allow the Microphone…") { $0.allowMicrophone() }) }
        if needsAccessibility || needsMicrophone { menu.addItem(.separator()) }
        menu.addItem(submenu("Model: " + (s.config.model ?? "none"), modelItems(s)))
        menu.addItem(submenu("Language: " + languageName(s), languageItems(s)))
        let inputs = AudioInputs.all()
        menu.addItem(submenu("Microphone: " + microphoneName(s, inputs), microphoneItems(s, inputs)))
        menu.addItem(volumeItem(s))
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

    /// The config's microphone is this input: the built-in one for "builtin", the device for its UID.
    private func isChosen(_ input: AudioInput, _ s: MenuState) -> Bool {
        s.config.microphone == Config.builtInMicrophone ? input.builtIn : s.config.microphone == input.uid
    }

    /// The input volume of the microphone the app records: the same control as in macOS's Sound settings.
    private func volumeItem(_ s: MenuState) -> NSMenuItem {
        guard let volume = s.inputVolume else {
            return disabled("Input volume: \(s.microphoneName.isEmpty ? "no microphone" : s.microphoneName) has none")
        }
        let item = NSMenuItem()
        item.view = VolumeView(value: volume) { [weak self] v in self?.actions?.setInputVolume(v) }
        return item
    }

    private func microphoneName(_ s: MenuState, _ inputs: [AudioInput]) -> String {
        if s.config.microphone == Config.systemMicrophone { return "macOS's input" }
        return inputs.first { isChosen($0, s) }?.name ?? "not connected"
    }

    private func microphoneItems(_ s: MenuState, _ inputs: [AudioInput]) -> [NSMenuItem] {
        var items = inputs.map { input in
            checked(action(input.name + (input.builtIn ? " (built-in)" : "")) {
                $0.choose(microphone: input.builtIn ? Config.builtInMicrophone : input.uid)
            }, isChosen(input, s))
        }
        if inputs.isEmpty { items.append(disabled("No microphone found.")) }
        items += [.separator(), checked(action("Follow macOS's Input") { $0.choose(microphone: Config.systemMicrophone) },
                                        s.config.microphone == Config.systemMicrophone)]
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

/// A slider in the menu: "Input volume", 0–100%, applied while it moves.
final class VolumeView: NSView {
    private let slider = NSSlider()
    private let percent = NSTextField(labelWithString: "")
    private let onChange: (Float) -> Void

    init(value: Float, onChange: @escaping (Float) -> Void) {
        self.onChange = onChange
        super.init(frame: NSRect(x: 0, y: 0, width: 260, height: 46))
        let title = NSTextField(labelWithString: "Input volume")
        title.font = .menuFont(ofSize: 0)
        title.textColor = .secondaryLabelColor
        title.frame = NSRect(x: 20, y: 25, width: 160, height: 16)
        percent.font = .monospacedDigitSystemFont(ofSize: NSFont.smallSystemFontSize, weight: .regular)
        percent.textColor = .secondaryLabelColor
        percent.alignment = .right
        percent.frame = NSRect(x: 196, y: 25, width: 46, height: 16)
        slider.minValue = 0
        slider.maxValue = 1
        slider.doubleValue = Double(value)
        slider.isContinuous = true
        slider.target = self
        slider.action = #selector(moved)
        slider.frame = NSRect(x: 18, y: 4, width: 226, height: 20)
        [title, percent, slider].forEach(addSubview)
        show()
    }

    required init?(coder: NSCoder) { nil }

    @objc private func moved() {
        show()
        onChange(Float(slider.doubleValue))
    }

    private func show() { percent.stringValue = "\(Int((slider.doubleValue * 100).rounded()))%" }
}
