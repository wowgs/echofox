// The window of the first start (docs/reference/1-server.md, "The catalog and the downloads"): when no variant of the menu's model is
// downloaded, it asks which one to download, shows the download, and then names the variant in the config. The
// dictation server does the download (ModelJob), so it goes on if the window closes. The fox stands beside it: the
// only place of the full character in the app (macos/art/README.md).
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

    /// Opens the window once in a run of the app, when the server's info says that no variant of the menu's model is
    /// downloaded or downloading.
    func showIfNeeded(_ info: ServerInfo?) {
        guard !shown, let m = info?.model, let variants = m.variants, !variants.isEmpty,
              !variants.contains(where: { $0.downloaded || $0.downloading == true }),
              let name = m.name, let catalog = m.catalog else { return }
        shown = true
        let config = store?.config ?? Config()
        let languages = info?.languages ?? []
        let model = FirstRunModel(name: name, catalog: catalog, title: m.title ?? name, variants: variants,
                                  inForce: m.variant, languages: languages,
                                  language: info?.proposedLanguage(config.language) ?? "en", store: store,
                                  downloads: downloads)
        model.done = { [weak self] in
            self?.askServer()
            self?.window?.close()
        }
        self.model = model
        let view = NSHostingView(rootView: FirstRunView(model: model))
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
}

final class FirstRunModel: ObservableObject {
    let name: String, catalog: String, title: String, variants: [ServerInfo.Variant], inForce: String?
    let languages: [ServerInfo.Language]
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
         languages: [ServerInfo.Language], language: String, store: ConfigStore?, downloads: ModelDownloads) {
        self.store = store
        self.downloads = downloads
        self.name = name
        self.catalog = catalog
        self.title = title
        self.variants = variants
        self.inForce = inForce
        self.languages = languages
        self.language = language
        choice = ServerInfo.Variant.recommended(variants, memory: ProcessInfo.processInfo.physicalMemory)
        downloadsChanged = downloads.objectWillChange.sink { [weak self] in self?.objectWillChange.send() }
        downloads.onEnd { [weak self] variant, job, isDownload in
            guard let self, isDownload, variant == self.choice, job.error == nil else { return }
            if self.choice != self.inForce {  // the catalog's default needs no line in the config
                self.store?.set(["models", self.name, "variant"], to: self.choice,
                                "first start: \(self.name) variant \(self.choice)")
            }
            self.done()
        }
    }

    func download() {
        store?.set(["language"], to: language, "first start: language \(language)")
        downloads.download(catalog: catalog, variant: choice, url: (store?.config ?? Config()).serverURL)
    }
}

struct FirstRunView: View {
    @ObservedObject var model: FirstRunModel
    /// The fox, from the app's Resources (build-app.sh); without it, the window shows the text alone.
    private let fox = Bundle.main.image(forResource: "echofox-welcome")

    var body: some View {
        HStack(spacing: 0) {
            if let fox {
                Image(nsImage: fox).resizable().scaledToFit()
                    .frame(width: 160)
                    .padding(.leading, 20)
                    .accessibilityHidden(true)  // a picture only; the text says what the window is for
            }
            choice.frame(width: 520)
        }
        .frame(height: 400)
    }

    private var choice: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Download the speech model").font(.title2.bold())
            Text("EchoFox turns your speech into text with \(model.title), a model that runs on this Mac. The audio "
                 + "never leaves it. Choose the language you speak most and the model to download.")
                .fixedSize(horizontal: false, vertical: true)
            Picker("Language", selection: $model.language) {
                ForEach(model.languages, id: \.code) { l in Text(l.name).tag(l.code) }
            }
            .fixedSize()
            .disabled(model.job != nil && model.job?.error == nil)
            Picker("", selection: $model.choice) {
                ForEach(model.variants, id: \.id) { v in
                    VStack(alignment: .leading, spacing: 2) {
                        Text("\(model.title), " + v.name + (v.id == ServerInfo.Variant.recommended(model.variants, memory: ProcessInfo.processInfo.physicalMemory)
                                       ? ", recommended for this Mac" : ""))
                        Text("Download \(gigabytes(v.bytes))" + (v.memoryBytes.map { ", uses about \(gigabytes($0)) of memory" } ?? ""))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    .tag(v.id)
                }
            }
            .pickerStyle(.radioGroup)
            .labelsHidden()
            .disabled(model.job != nil && model.job?.error == nil)
            if let job = model.job {
                if let e = job.error {
                    Text(e).foregroundStyle(.red).fixedSize(horizontal: false, vertical: true)
                } else {
                    ProgressView(value: job.total > 0 ? job.bytes / job.total : 0)
                    Text(job.status).font(.caption).foregroundStyle(.secondary).monospacedDigit()
                }
            }
            Spacer()
            HStack {
                Text("A smaller model uses less memory and is faster. You can change it later in Settings.")
                    .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                Spacer()
                if let job = model.job, job.error == nil, !job.finished {
                    Button("Cancel") { job.cancel() }
                } else {
                    Button(model.job?.error == nil ? "Download" : "Try Again") { model.download() }
                        .keyboardShortcut(.defaultAction)
                }
            }
        }
        .padding(20)
    }
}
