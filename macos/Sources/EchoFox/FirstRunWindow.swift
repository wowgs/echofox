// The window of the first start (docs/reference/4-app.md, "The first start"): until the setup is done (Done, which sets
// setupDone in the app's preferences) or while no variant of the menu's model is downloaded, it asks for the language, which variant to download and which adapters may read the conversation,
// shows the two permissions with a button each (the app asks for none by itself), shows the download, and then names
// the variant in the config; it stays open after the download, until Done. An adapter's switch writes the config at
// once. The
// dictation server does the download (ModelJob), so it goes on if the window closes. The fox stands beside it: the
// only place of the full character in the app (macos/art/README.md). `--render-first-run` draws the window into a PNG
// from a server info in a file, for checking its look without a server (main.swift).
import AppKit
import Combine
import EchoFoxCore
import SwiftUI

final class FirstRunWindow: NSObject, NSWindowDelegate {
    private var window: NSWindow?
    private var model: FirstRunModel?
    private var shown = false
    var askServer: () -> Void = {}
    /// The app's config, which the chosen variant is written to.
    var store: ConfigStore?
    /// The app's model downloads, which the settings window shares.
    var downloads = ModelDownloads()
    /// The permissions now (microphone, Accessibility), and the buttons' actions: the system's prompt.
    var permissions: () -> (microphone: Bool, accessibility: Bool) = { (false, false) }
    var allowMicrophone: () -> Void = {}
    var allowAccessibility: () -> Void = {}

    /// A permission changed: the window shows it.
    func permissionsChanged() {
        let p = permissions()
        model?.microphone = p.microphone
        model?.accessibility = p.accessibility
    }

    /// The variant in use was removed: the window may open again (showIfNeeded).
    func allowAgain() { shown = false }

    /// The app's preference that the first start's window was finished with Done; absent before its first start.
    static let setupDone = "setupDone"
    /// Whether the config file was there when the app started: then an earlier version set EchoFox up.
    var configExisted = false

    /// Opens the window once in a run of the app, when the setup is not done or the server's info says that no variant
    /// of the menu's model is downloaded or downloading. An earlier version's setup (no preference yet, but a config
    /// and a downloaded model) counts as done.
    func showIfNeeded(_ info: ServerInfo?) {
        guard !shown, let m = info?.model, let variants = m.variants, !variants.isEmpty,
              let name = m.name, let catalog = m.catalog else { return }
        let prefs = UserDefaults.standard
        let hasModel = variants.contains(where: { $0.downloaded || $0.downloading == true })
        if prefs.object(forKey: Self.setupDone) == nil && configExisted && hasModel {
            prefs.set(true, forKey: Self.setupDone)
            Log.write("first start: set up by an earlier version (a config and a downloaded model)")
        }
        guard !prefs.bool(forKey: Self.setupDone) || !hasModel else { return }
        prefs.set(false, forKey: Self.setupDone)
        shown = true
        let config = store?.config ?? Config()
        let languages = info?.languages ?? []
        let model = FirstRunModel(name: name, catalog: catalog, title: m.title ?? name, variants: variants,
                                  inForce: m.variant, languages: languages,
                                  language: info?.proposedLanguage(config.language) ?? "en",
                                  adapters: info?.adapters ?? [], enabled: config.adapters, store: store,
                                  downloads: downloads)
        (model.microphone, model.accessibility) = permissions()
        model.allowMicrophone = { [weak self] in self?.allowMicrophone() }
        model.allowAccessibility = { [weak self] in self?.allowAccessibility() }
        model.done = { [weak self] in
            UserDefaults.standard.set(true, forKey: Self.setupDone)
            Log.write("first start: done")
            self?.askServer()
            self?.window?.close()
        }
        self.model = model
        let view = NSHostingView(rootView: FirstRunView(model: model))
        view.layoutSubtreeIfNeeded()
        let w = NSWindow(contentRect: NSRect(origin: .zero, size: view.fittingSize), styleMask: [.titled, .closable],
                         backing: .buffered, defer: false)
        w.title = "EchoFox"
        w.isReleasedWhenClosed = false
        w.contentView = view
        w.center()
        w.delegate = self
        window = w
        w.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func windowWillClose(_ notification: Notification) {
        window = nil
        model = nil
    }

    /// Draws the window's content, as the first start shows it for this server info, into a PNG at the screen's
    /// scale, in the light or the dark appearance; nothing is written to the config.
    static func render(info file: String, to out: String, dark: Bool) {
        guard let data = FileManager.default.contents(atPath: file), let info = try? ServerInfo.decode(data),
              let m = info.model, let variants = m.variants, let name = m.name, let catalog = m.catalog else {
            FileHandle.standardError.write(Data("render: no server info with a model in \(file)\n".utf8))
            exit(1)
        }
        let model = FirstRunModel(name: name, catalog: catalog, title: m.title ?? name, variants: variants,
                                  inForce: m.variant, languages: info.languages, language: "ru",
                                  adapters: info.adapters, enabled: [:], store: nil, downloads: ModelDownloads())
        // The window's own background: an offscreen view draws on nothing
        let view = NSHostingView(rootView: FirstRunView(model: model).background(Color(nsColor: .windowBackgroundColor)))
        let w = NSWindow(contentRect: NSRect(origin: .zero, size: view.fittingSize), styleMask: [.titled],
                         backing: .buffered, defer: false)
        w.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
        w.contentView = view
        view.layoutSubtreeIfNeeded()
        guard let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { exit(1) }
        view.cacheDisplay(in: view.bounds, to: rep)
        try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: out))
        exit(0)
    }
}

final class FirstRunModel: ObservableObject {
    let name: String, catalog: String, title: String, variants: [ServerInfo.Variant], inForce: String?
    let languages: [ServerInfo.Language]
    /// The adapters the server has, and which of them the config turns on.
    let adapters: [ServerInfo.Adapter]
    @Published var enabled: [String: Bool]
    /// The variants whose files are on the disk: choosing one makes the window's button Done.
    @Published var downloaded: Set<String>
    @Published var microphone = false
    @Published var accessibility = false
    var allowMicrophone: () -> Void = {}
    var allowAccessibility: () -> Void = {}
    @Published var choice: String
    /// The speaker's main language, written to the config when the download starts.
    @Published var language: String
    var done: () -> Void = {}
    /// The chosen variant's job, the app's (ModelDownloads), also when the settings window started it.
    var job: ModelJob? { downloads.jobs[choice] }

    private let store: ConfigStore?
    private let downloads: ModelDownloads
    private var downloadsChanged: AnyCancellable?

    init(name: String, catalog: String, title: String, variants: [ServerInfo.Variant], inForce: String?,
         languages: [ServerInfo.Language], language: String, adapters: [ServerInfo.Adapter], enabled: [String: Bool],
         store: ConfigStore?, downloads: ModelDownloads) {
        self.store = store
        self.downloads = downloads
        self.name = name
        self.catalog = catalog
        self.title = title
        self.variants = variants
        self.inForce = inForce
        self.languages = languages
        self.language = language
        self.adapters = adapters
        self.enabled = enabled
        downloaded = Set(variants.filter(\.downloaded).map(\.id))
        choice = variants.first(where: \.downloaded)?.id ?? ServerInfo.Variant.recommended(variants, memory: ProcessInfo.processInfo.physicalMemory)
        downloadsChanged = downloads.objectWillChange.sink { [weak self] in self?.objectWillChange.send() }
        downloads.onEnd { [weak self] variant, job, isDownload in
            guard let self, isDownload, variant == self.choice, job.error == nil else { return }
            self.downloaded.insert(variant)
            self.useChoice()  // the window stays: the permissions and the adapters may still be open
        }
    }

    /// An adapter's switch: the config changes at once, as in Settings.
    func setAdapter(_ name: String, _ on: Bool) {
        enabled[name] = on
        store?.set(["adapters", name, "enabled"], to: on, "first start: adapter \(name) \(on ? "on" : "off")")
    }

    func download() {
        store?.set(["language"], to: language, "first start: language \(language)")
        downloads.download(catalog: catalog, variant: choice, url: (store?.config ?? Config()).serverURL)
    }

    /// The chosen variant, downloaded, is the menu model's (the catalog's default needs no line in the config).
    private func useChoice() {
        if choice != inForce {
            store?.set(["models", name, "variant"], to: choice, "first start: \(name) variant \(choice)")
        }
    }

    /// Done: the language and the chosen variant go into the config, and the setup is done.
    func finish() {
        store?.set(["language"], to: language, "first start: language \(language)")
        useChoice()
        done()
    }
}

struct FirstRunView: View {
    @ObservedObject var model: FirstRunModel
    /// The fox, from the app's Resources (build-app.sh); without it, the window shows the text alone.
    private let fox = Bundle.main.image(forResource: "echofox-welcome")
    private var busy: Bool { model.job != nil && model.job?.error == nil }

    var body: some View {
        HStack(alignment: .center, spacing: 0) {
            if let fox {
                Image(nsImage: fox).resizable().scaledToFit()
                    .frame(width: 170)
                    .padding(.leading, 24)
                    .accessibilityHidden(true)  // a picture only; the text says what the window is for
            }
            content.frame(width: 500)
        }
    }

    private var content: some View {
        VStack(alignment: .leading, spacing: 18) {
            VStack(alignment: .leading, spacing: 6) {
                Text("Set up EchoFox").font(.title2.bold())
                Text("\(model.title) runs on this Mac. Nothing leaves it.").foregroundStyle(.secondary)
            }
            Grid(alignment: .leadingFirstTextBaseline, horizontalSpacing: 14, verticalSpacing: 14) {
                GridRow {
                    label("Language")
                    Picker("Language", selection: $model.language) {
                        ForEach(model.languages, id: \.code) { l in Text(l.name).tag(l.code) }
                    }
                    .labelsHidden().fixedSize().disabled(busy)
                }
                GridRow {
                    label("Model")
                    Picker("Model", selection: $model.choice) {
                        ForEach(model.variants, id: \.id) { v in
                            VStack(alignment: .leading, spacing: 2) {
                                Text(v.name + (v.id == recommended ? "  ·  recommended for this Mac" : "")
                                     + (model.downloaded.contains(v.id) ? "  ·  downloaded" : ""))
                                Text("\(gigabytes(v.bytes)) download" + (v.memoryBytes.map { ", about \(gigabytes($0)) of memory" } ?? ""))
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                            .padding(.bottom, 4)
                            .tag(v.id)
                        }
                    }
                    .pickerStyle(.radioGroup).labelsHidden().disabled(busy)
                }
                GridRow {
                    label("Permissions")
                    VStack(alignment: .leading, spacing: 10) {
                        permissionRow("mic", "Microphone", granted: model.microphone, allow: model.allowMicrophone)
                        permissionRow("accessibility", "Accessibility", granted: model.accessibility,
                                      allow: model.allowAccessibility)
                    }
                }
                if !model.adapters.isEmpty {
                    GridRow {
                        label("Conversation")
                        VStack(alignment: .leading, spacing: 10) {
                            ForEach(model.adapters, id: \.name) { a in adapterRow(a) }
                        }
                    }
                }
            }
            if let job = model.job {
                if let e = job.error {
                    Text(e).foregroundStyle(.red).fixedSize(horizontal: false, vertical: true)
                } else {
                    VStack(alignment: .leading, spacing: 4) {
                        ProgressView(value: job.total > 0 ? job.bytes / job.total : 0)
                        Text(job.status).font(.caption).foregroundStyle(.secondary).monospacedDigit()
                    }
                }
            }
            HStack {
                Text("You can change all of this later in Settings.")
                    .font(.caption).foregroundStyle(.secondary)
                Spacer()
                if model.downloaded.contains(model.choice) {
                    Button("Done") { model.finish() }.keyboardShortcut(.defaultAction)
                } else if let job = model.job, job.error == nil, !job.finished {
                    Button("Cancel") { job.cancel() }
                } else {
                    Button(model.job?.error == nil ? "Download" : "Try Again") { model.download() }
                        .keyboardShortcut(.defaultAction)
                }
            }
        }
        .padding(24)
    }

    private var recommended: String {
        ServerInfo.Variant.recommended(model.variants, memory: ProcessInfo.processInfo.physicalMemory)
    }

    private func label(_ text: String) -> some View {
        Text(text).foregroundStyle(.secondary).gridColumnAlignment(.leading)
    }

    /// A permission: its symbol, its name, and Allow (the system's prompt) or a check mark.
    private func permissionRow(_ symbol: String, _ name: String, granted: Bool, allow: @escaping () -> Void) -> some View {
        HStack(spacing: 8) {
            Image(systemName: symbol).frame(width: 18)
            Text(name)
            Spacer(minLength: 12)
            if granted {
                Label("Allowed", systemImage: "checkmark.circle.fill").labelStyle(.iconOnly)
                    .foregroundStyle(.green).help("Allowed")
            } else {
                Button("Allow", action: allow).controlSize(.small)
            }
        }
        .frame(width: 240)
    }

    /// An adapter: the icon of its app, its name, its switch; what it reads is in the tooltip.
    private func adapterRow(_ a: ServerInfo.Adapter) -> some View {
        HStack(spacing: 8) {
            AppIcon(bundleIds: a.apps)
            Text(a.title ?? a.name.capitalized)
            Spacer(minLength: 12)
            Toggle(a.title ?? a.name, isOn: Binding(get: { model.enabled[a.name] == true },
                                                     set: { model.setAdapter(a.name, $0) }))
                .labelsHidden().toggleStyle(.switch).controlSize(.small)
        }
        .frame(width: 240)
        .help(a.description ?? "")
    }
}
