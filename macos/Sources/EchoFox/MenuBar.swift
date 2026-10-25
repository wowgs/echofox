// The menu bar item: an icon for the state (recording, a private recording, waiting, a problem), and a short menu of
// what is touched often, built each time it opens from SettingsLayout.menu (docs/design/5-ui.md); everything else is
// in the settings window. A dictation is the hotkeys', not the menu's. It shows; it never decides: the actions go
// back to the App.
import AppKit
import AVFoundation
import EchoFoxCore

struct MenuState {
    var recording = false, privateRecording = false, waiting = false
    var accessibility = false, microphone = AVAuthorizationStatus.notDetermined
    var lastError: String?
    var config = Config()
    var server: ServerInfo?, serverProblem: String?
    /// The recorded microphone's name and input volume (0…1; nil: the device has none to set).
    var microphoneName = "", inputVolume: Float?
}

protocol MenuActions: AnyObject {
    func allowAccessibility()
    func allowMicrophone()
    func choose(microphone: String)
    func setInputVolume(_ value: Float)
    func openLabeling()
    func openSettings()
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
            (symbol, tint) = ("mic.fill", s.privateRecording ? .systemPurple : .systemRed)
        } else if s.waiting {
            (symbol, tint) = ("ellipsis.circle", nil)
        } else if !s.accessibility || s.microphone != .authorized || s.lastError != nil || s.serverProblem != nil {
            (symbol, tint) = ("mic.slash", nil)
        } else {
            (symbol, tint) = ("mic", nil)
        }
        let image = NSImage(systemSymbolName: symbol, accessibilityDescription: "EchoFox")
        image?.isTemplate = true
        item.button?.image = image
        item.button?.contentTintColor = tint
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        let s = state()
        menu.removeAllItems()
        handlers.removeAll()
        let inputs = AudioInputs.all()
        for id in SettingsLayout.menu {
            switch id {
            case "permissions":  // only while one is missing
                if !s.accessibility || s.microphone != .authorized { menu.addItem(permissionsItem(s)) }
            case "microphone": menu.addItem(submenu("Microphone: " + microphoneName(s, inputs), microphoneItems(s, inputs)))
            case "inputVolume": menu.addItem(volumeItem(s))
            case "labelRecordings": menu.addItem(action("Label Recordings…") { $0.openLabeling() })
            default: break
            }
        }
        menu.addItem(.separator())
        let settings = action("Settings…") { $0.openSettings() }
        settings.keyEquivalent = ","
        menu.addItem(settings)
        menu.addItem(NSMenuItem(title: "Quit EchoFox", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
    }

    /// One line for the permissions, shown only while one is missing: its title names what is missing; in it, a
    /// granted one is a grey item with a check, and a missing one opens the place in System Settings where it is given.
    private func permissionsItem(_ s: MenuState) -> NSMenuItem {
        let micOK = s.microphone == .authorized
        let missing = [s.accessibility ? nil : "Accessibility", micOK ? nil : "Microphone"].compactMap { $0 }
        let accessibility = s.accessibility ? checked(disabled("Accessibility"), true)
            : action("Accessibility: Allow…") { $0.allowAccessibility() }
        let microphone = micOK ? checked(disabled("Microphone"), true) : action("Microphone: Allow…") { $0.allowMicrophone() }
        return submenu("Permissions: Allow " + missing.joined(separator: " and "), [accessibility, microphone])
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
