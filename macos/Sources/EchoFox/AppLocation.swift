// Where the app runs from. An app that carries the server must stay in one place while it runs, because the server
// runs from the app's bundle: from a disk image or from App Translocation (ServerProcess.misplaced) it asks to be
// moved to Applications and quits.
import AppKit
import EchoFoxCore

enum AppLocation {
    /// Asks to move the app to Applications and quits if it carries the server and runs from the wrong place; true
    /// then, and the app starts nothing.
    static func refuseIfMisplaced() -> Bool {
        let app = Bundle.main.bundleURL
        guard ServerProcess.bundled(resources: Bundle.main.resourceURL) != nil else { return false }
        let readOnly = (try? app.resourceValues(forKeys: [.volumeIsReadOnlyKey]))?.volumeIsReadOnly ?? false
        guard let why = ServerProcess.misplaced(app: app.path, readOnlyVolume: readOnly) else { return false }
        Log.write("not started \(why), \(app.path): the server needs the app in one place")
        let alert = NSAlert()
        alert.messageText = "Move EchoFox to Applications"
        alert.informativeText = "EchoFox is running \(why). Its dictation server needs EchoFox to stay in one place. "
            + "Drag EchoFox to the Applications folder, then open it from there."
        alert.addButton(withTitle: "Quit")
        NSApp.activate(ignoringOtherApps: true)
        alert.runModal()
        NSApp.terminate(nil)
        return true
    }
}
