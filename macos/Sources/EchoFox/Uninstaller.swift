// "Uninstall EchoFox…" (docs/reference/4-app.md, "Uninstall"): after a confirmation, the dictation server removes the
// downloaded models (it knows their files), then the agents stop and go, the app's folders, caches, logs and settings
// go (Uninstall.items), the recordings and labels go to the Trash if asked, the app goes to the Trash and quits. macOS
// keeps the Microphone and Accessibility permissions; the confirmation says where to remove them.
import AppKit
import EchoFoxCore

enum Uninstaller {
    /// Asks, then uninstalls. `info`: the server's info, for the models to remove; `folders`: the recordings and labels.
    static func confirmAndRun(info: ServerInfo?, serverURL: URL, folders: (recordings: URL, labeled: URL)) {
        let downloaded = info?.model?.variants?.filter(\.downloaded) ?? []
        let size = downloaded.reduce(0) { $0 + $1.bytes }
        let alert = NSAlert()
        alert.alertStyle = .critical
        alert.messageText = "Uninstall EchoFox?"
        alert.informativeText = "The dictation server, its models" + (size > 0 ? " (\(gigabytes(size)))" : "")
            + ", the settings and the logs are deleted, and EchoFox goes to the Trash.\n\n"
            + "macOS keeps the Microphone and Accessibility permissions: remove them in System Settings → "
            + "Privacy & Security."
        let keep = NSButton(checkboxWithTitle: "Also move the recordings and labels to the Trash", target: nil, action: nil)
        keep.state = .off
        alert.accessoryView = keep
        alert.addButton(withTitle: "Uninstall").hasDestructiveAction = true
        alert.addButton(withTitle: "Cancel")
        NSApp.activate(ignoringOtherApps: true)
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        let withRecordings = keep.state == .on
        Log.write("uninstall: \(downloaded.count) models, recordings \(withRecordings ? "to the Trash" : "kept")")
        // The variant in use last: the server unloads it after the running recording
        let order = downloaded.sorted { a, _ in a.id != info?.model?.variant }
        removeModels(order.map(\.id), catalog: info?.model?.catalog ?? "", url: serverURL) {
            finish(folders: folders, withRecordings: withRecordings)
        }
    }

    /// The server removes the variants one after another; then `done`, also when one fails (its files stay, said in
    /// the log).
    private static func removeModels(_ ids: [String], catalog: String, url: URL, done: @escaping () -> Void) {
        guard let id = ids.first else { return done() }
        let job = ModelJob(url: url, message: ClientMessage.remove(catalog: catalog, variant: id))
        job.onChange = {
            guard job.finished else { return }
            if let e = job.error { Log.write("uninstall: \(id) not removed: \(e)") }
            removeModels(Array(ids.dropFirst()), catalog: catalog, url: url, done: done)
        }
        job.start()
    }

    private static func finish(folders: (recordings: URL, labeled: URL), withRecordings: Bool) {
        let fm = FileManager.default
        for item in Uninstall.items(home: fm.homeDirectoryForCurrentUser, recordings: folders.recordings,
                                    labeled: folders.labeled, withRecordings: withRecordings) {
            do {
                if item.toTrash { try fm.trashItem(at: item.url, resultingItemURL: nil) } else { try fm.removeItem(at: item.url) }
            } catch {
                Log.write("uninstall: \(item.url.path) stays: \(error.localizedDescription)")
            }
        }
        UserDefaults.standard.removePersistentDomain(forName: Uninstall.bundleId)
        NSWorkspace.shared.recycle([Bundle.main.bundleURL]) { _, _ in
            DispatchQueue.main.async { NSApp.terminate(nil) }
        }
    }
}
