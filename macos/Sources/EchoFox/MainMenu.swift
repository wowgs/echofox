// The main menu, which the app shows while it is a regular app (DockPresence: while one of its windows is open). Its
// Edit menu gives the windows' text fields cut, copy and paste.
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
}
