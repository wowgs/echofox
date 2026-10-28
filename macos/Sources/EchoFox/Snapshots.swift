// --render KIND INFO OUT [dark] (main.swift): draws one of the app's windows into a PNG and quits, for checking its look
// without a server or the user's config. KIND: first-run, settings (the General page), uninstall (the question), update
// (Sparkle's progress window, a download at 40 %). INFO is a server's info message as JSON.
import AppKit
import EchoFoxCore
import Sparkle
import SwiftUI

enum Snapshots {
    static func render(kind: String, info file: String, to out: String, dark: Bool) -> Never {
        _ = NSApplication.shared
        NSApp.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
        guard let data = FileManager.default.contents(atPath: file), let info = try? ServerInfo.decode(data) else {
            fail("no server info in \(file)")
        }
        switch kind {
        case "first-run": FirstRunWindow.render(info: file, to: out, dark: dark)
        case "settings":
            let model = SettingsModel(actions: nil, downloads: ModelDownloads())
            model.info = info
            model.selection = .page(.general)
            draw(NSHostingView(rootView: SettingsView(model: model).frame(width: 760, height: 560)
                .background(Color(nsColor: .windowBackgroundColor))), to: out)
        case "uninstall":
            let (alert, _) = Uninstaller.confirmation(info: info)
            alert.layout()
            guard let view = alert.window.contentView else { fail("the alert has no view") }
            draw(view, to: out)
        case "update":
            let driver = SPUStandardUserDriver(hostBundle: Bundle.main, delegate: nil)
            driver.showDownloadInitiated { }
            driver.showDownloadDidReceiveExpectedContentLength(60_000_000)
            driver.showDownloadDidReceiveData(ofLength: 24_000_000)
            RunLoop.main.run(until: Date().addingTimeInterval(0.5))
            guard let view = NSApp.windows.last(where: { $0.isVisible })?.contentView else { fail("no update window") }
            draw(view, to: out)
        default: fail("unknown kind \(kind)")
        }
        exit(0)
    }

    private static func draw(_ view: NSView, to out: String) {
        if view.window == nil {
            let w = NSWindow(contentRect: NSRect(origin: .zero, size: view.fittingSize), styleMask: [.titled],
                             backing: .buffered, defer: false)
            w.contentView = view
        }
        view.layoutSubtreeIfNeeded()
        guard let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { fail("cannot draw") }
        view.cacheDisplay(in: view.bounds, to: rep)
        try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: out))
    }

    private static func fail(_ text: String) -> Never {
        FileHandle.standardError.write(Data("render: \(text)\n".utf8))
        exit(1)
    }
}
