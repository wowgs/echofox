// Whether the app is in the Dock. It is a menu bar app (main.swift: .accessory): no Dock icon, no main menu. While one
// of its windows is open (the first start, Settings, labeling), also minimized, it is a regular app: in the Dock and in
// ⌘Tab, so a window that went behind the browser comes back with a click, and with the main menu (MainMenu), whose
// Edit menu gives the windows' text fields cut, copy and paste. When the last window closes, it is a menu bar app
// again.
import AppKit
import EchoFoxCore

enum DockPresence {
    /// Whether one of the app's windows is open: a titled window, shown or minimized, Sparkle's and alerts included (the
    /// menu bar's menus have no title bar).
    static var hasWindow: Bool {
        NSApp.windows.contains { w in w.styleMask.contains(.titled) && (w.isVisible || w.isMiniaturized) }
    }

    /// Shows one of the app's windows: the app becomes regular first, then the window comes forward and the app is
    /// activated, so that the main menu answers clicks. A menu bar app that turns regular while it is active keeps a
    /// menu bar that does not answer until it is activated again; then the Dock gets the focus for a moment.
    static func bringForward(_ window: NSWindow) {
        let wasActive = NSApp.isActive
        if NSApp.activationPolicy() != .regular { NSApp.setActivationPolicy(.regular) }
        window.makeKeyAndOrderFront(nil)
        if wasActive, let dock = NSRunningApplication.runningApplications(withBundleIdentifier: "com.apple.dock").first {
            dock.activate()
            DispatchQueue.main.asyncAfter(deadline: .now() + Tuning.dockFocusSeconds) { NSApp.activate(ignoringOtherApps: true) }
        } else {
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    /// The last window change: a later one cancels a pending return to the menu bar.
    private static var change = 0

    /// In the Dock while a window is open, a menu bar app otherwise; called after each window change. The return to the
    /// menu bar waits Tuning.leaveDockSeconds for a window that follows the one that closed (Install in Sparkle's
    /// window closes it and opens the progress window): leaving at once took the focus away, and the progress window
    /// opened behind the other apps.
    static func follow() {
        change += 1
        if hasWindow {
            if NSApp.activationPolicy() != .regular { NSApp.setActivationPolicy(.regular) }
            return
        }
        let mine = change
        DispatchQueue.main.asyncAfter(deadline: .now() + Tuning.leaveDockSeconds) {
            guard mine == change, !hasWindow, NSApp.activationPolicy() != .accessory else { return }
            NSApp.setActivationPolicy(.accessory)
        }
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
