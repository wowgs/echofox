// The app is a menu bar app (main.swift: .accessory): no Dock icon, no main menu. While one of its windows is open
// (the first start, Settings, labeling), also minimized, it is a regular app: in the Dock and in ⌘Tab, so a window
// that went behind the browser comes back with a click, and with the main menu, whose Edit menu gives the windows' text
// fields cut, copy and paste. When the last window closes, it is a menu bar app again.
import AppKit

enum MainMenu {
    /// The main menu of the regular app: EchoFox (About, Settings…, Quit), Edit and Window.
    static func install(settings: Selector, target: AnyObject) {
        let main = NSMenu()
        let app = NSMenu(title: "EchoFox")
        app.addItem(withTitle: "About EchoFox", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)),
                    keyEquivalent: "")
        app.addItem(.separator())
        let s = app.addItem(withTitle: "Settings…", action: settings, keyEquivalent: ",")
        s.target = target
        app.addItem(.separator())
        app.addItem(withTitle: "Hide EchoFox", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        app.addItem(.separator())
        app.addItem(withTitle: "Quit EchoFox", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "Z")
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        let window = NSMenu(title: "Window")
        window.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        window.addItem(withTitle: "Close", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        for menu in [app, edit, window] {
            main.addItem(withTitle: menu.title, action: nil, keyEquivalent: "").submenu = menu
        }
        NSApp.mainMenu = main
        NSApp.windowsMenu = window
    }

    /// Whether one of the app's windows is open: a titled window, shown or minimized (not a panel, such as an alert).
    static var hasWindow: Bool {
        NSApp.windows.contains { w in
            w.styleMask.contains(.titled) && !(w is NSPanel) && (w.isVisible || w.isMiniaturized)
        }
    }

    /// In the Dock while a window is open, a menu bar app otherwise; called after each window change.
    static func follow() {
        let want: NSApplication.ActivationPolicy = hasWindow ? .regular : .accessory
        if NSApp.activationPolicy() != want { NSApp.setActivationPolicy(want) }
    }

    /// Watches the windows' changes: one that opens, closes, minimizes or comes back.
    static func watch() {
        let names: [Notification.Name] = [NSWindow.didBecomeKeyNotification, NSWindow.willCloseNotification,
                                          NSWindow.didMiniaturizeNotification, NSWindow.didDeminiaturizeNotification]
        for name in names {
            // After the change: a closing window is still visible while its notification runs
            NotificationCenter.default.addObserver(forName: name, object: nil, queue: .main) { _ in
                DispatchQueue.main.async { follow() }
            }
        }
    }
}
