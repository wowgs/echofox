// The window of the first start (docs/reference/4-app.md, "The first start"): until the setup is done (Done, which sets
// setupDone in the app's preferences) or while no variant of the menu's model is downloaded (FirstRun decides), it
// asks for the language, which variant to download and which adapters may read the conversation, shows the two
// permissions with a button each (the app asks for none by itself), shows the download, and then names the variant in
// the config; it stays open after the download, until Done. An adapter's switch writes the config at once. What each
// choice writes is SettingStore's. The dictation server does the download (ModelJob), so it goes on if the window
// closes. The fox stands beside it: the only place of the full character in the app (macos/art/README.md).
// `--render first-run` draws the window into a PNG from a server info in a file, for checking its look without a
// server (Snapshots).
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

    /// Whether the config file was there when the app started: then an earlier version set EchoFox up.
    var configExisted = false

    /// Opens the window when FirstRun.decide says so for the server's info, once in a run of the app.
    func showIfNeeded(_ info: ServerInfo?) {
        let prefs = UserDefaults.standard
        switch FirstRun.decide(model: info?.model, shown: shown, setupDone: prefs.object(forKey: FirstRun.setupDone) as? Bool,
                               configExisted: configExisted) {
        case .none: return
        case .setUpEarlier:
            prefs.set(true, forKey: FirstRun.setupDone)
            Log.write("first start: set up by an earlier version (a config and a downloaded model)")
            return
        case .show: break
        }
        guard let info, let model = FirstRunModel(info: info, config: store?.config ?? Config(), store: store,
                                                  downloads: downloads) else { return }
        prefs.set(false, forKey: FirstRun.setupDone)
        shown = true
        (model.microphone, model.accessibility) = permissions()
        model.allowMicrophone = { [weak self] in self?.allowMicrophone() }
        model.allowAccessibility = { [weak self] in self?.allowAccessibility() }
        model.done = { [weak self] in
            UserDefaults.standard.set(true, forKey: FirstRun.setupDone)
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
        DockPresence.bringForward(w)
    }

    func windowWillClose(_ notification: Notification) {
        window = nil
        model = nil
    }
}

final class FirstRunModel: ObservableObject {
    let name: String, catalog: String, title: String, variants: [ServerInfo.Variant]
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

    /// The window's model for the server's `info`, with the language it proposes for `config` and the adapters the
    /// config turns on; nil without a model with variants in the info. `store` nil: nothing is written (a render).
    init?(info: ServerInfo, config: Config, store: ConfigStore?, downloads: ModelDownloads) {
        guard let m = info.model, let variants = m.variants, !variants.isEmpty, let name = m.name,
              let catalog = m.catalog else { return nil }
        self.store = store
        self.downloads = downloads
        self.name = name
        self.catalog = catalog
        title = m.title ?? name
        self.variants = variants
        languages = info.languages
        language = info.proposedLanguage(config.language)
        adapters = info.adapters
        enabled = config.adapters
        downloaded = Set(variants.filter(\.downloaded).map(\.id))
        choice = variants.first(where: \.downloaded)?.id ?? ServerInfo.Variant.recommended(variants, memory: ProcessInfo.processInfo.physicalMemory)
        downloadsChanged = downloads.objectWillChange.sink { [weak self] in self?.objectWillChange.send() }
        downloads.onEnd { [weak self] variant, job, isDownload in
            guard let self, isDownload, variant == self.choice, job.error == nil else { return }
            self.downloaded.insert(variant)
            self.useChoice()  // the window stays: the permissions and the adapters may still be open
        }
    }

    /// An adapter's name for people, as Settings shows it.
    func title(of adapter: ServerInfo.Adapter) -> String { ServerInfo.adapterTitle(adapter.name, in: adapters) }

    /// An adapter's switch: the config changes at once, as in Settings.
    func setAdapter(_ name: String, _ on: Bool) {
        enabled[name] = on
        guard let store else { return }
        store.apply(SettingStore.adapter(name, enabled: on, in: store.config),
                    "first start: adapter \(name) \(on ? "on" : "off")")
    }

    func download() {
        writeLanguage()
        downloads.download(catalog: catalog, variant: choice, url: (store?.config ?? Config()).serverURL)
    }

    /// The speaker's language into the config (macOS's own needs no line in it).
    private func writeLanguage() {
        guard let store else { return }
        store.apply(SettingStore.language(language, in: store.config), "first start: language \(language)")
    }

    /// The chosen variant, downloaded, is the menu model's (the catalog's default needs no line in the config).
    private func useChoice() {
        guard let store else { return }
        store.apply(SettingStore.variant(choice, of: name, variants: variants, in: store.config),
                    "first start: \(name) variant \(choice)")
    }

    /// Done: the language and the chosen variant go into the config, and the setup is done.
    func finish() {
        writeLanguage()
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
            Text(model.title(of: a))
            Spacer(minLength: 12)
            Toggle(model.title(of: a), isOn: Binding(get: { model.enabled[a.name] == true },
                                                     set: { model.setAdapter(a.name, $0) }))
                .labelsHidden().toggleStyle(.switch).controlSize(.small)
        }
        .frame(width: 240)
        .help(a.description ?? "")
    }
}
