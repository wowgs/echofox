// The settings window's Model page: the menu's model, its quantizations (variants) with their downloads and removals
// (ModelDownloads), and its prompt template. A choice equal to the server's default takes its key out of the config
// (SettingStore).
import EchoFoxCore
import SwiftUI

/// The model: its name, or a choice when the registry has more than one.
struct ModelPicker: View {
    @ObservedObject var model: SettingsModel

    private var names: [String] { model.info?.models ?? model.config.models }
    private var current: String { model.menuModel ?? "" }

    var body: some View {
        if names.count > 1 {
            Picker("Model", selection: Binding(get: { current }, set: {
                model.apply(SettingStore.model($0, info: model.info, in: model.config))
            })) {
                // the model in force by its name for people (Gemma 4 E4B), the others by their registry name
                ForEach(names, id: \.self) { name in
                    Text(name == model.info?.model?.name ? model.info?.model?.title ?? name : name).tag(name)
                }
            }
        } else {
            LabeledContent("Model") { Text(model.info?.model?.title ?? current) }
        }
        if let e = model.config.error { Text(e).font(.caption).foregroundStyle(.red) }
        if let n = model.config.note { Text(n).font(.caption).foregroundStyle(.secondary) }
    }
}

/// The quantizations of the menu's model, one row each: its size on disk and in memory, whether it is in use,
/// downloaded or downloading, and what can be done with it: Use (only one whose files are on the disk), Download
/// with its progress and Cancel, or Remove, which deletes its files after a confirmation. The one in use cannot be
/// removed (the server refuses it): another one is chosen first.
struct VariantPicker: View {
    @ObservedObject var model: SettingsModel

    private var info: ServerInfo.Model? { model.info?.model }

    var body: some View {
        if let variants = info?.variants, !variants.isEmpty, let name = model.menuModel {
            Text("Smaller: less memory, faster. Larger: fewer errors.").foregroundStyle(.secondary)
            ForEach(variants, id: \.id) { v in
                VariantRow(model: model, name: name, catalog: info?.catalog ?? "", variant: v, variants: variants,
                           inUse: v.id == info?.variant)
            }
        }
    }
}

/// One quantization in a row: its name, its size on the disk and in memory, then its state and what can be done:
/// In use and Remove, or Use and Remove, for one on the disk (Remove after a confirmation, which for the one in use says
/// that dictation stops until a model is downloaded); Download, with its progress and Cancel, for one
/// that is not. While another window (the first start's) downloads it, the server's info says so and there is no
/// Download.
struct VariantRow: View {
    @ObservedObject var model: SettingsModel
    let name: String
    let catalog: String
    let variant: ServerInfo.Variant
    /// All the model's variants, for the catalog's default.
    let variants: [ServerInfo.Variant]
    let inUse: Bool

    private var job: ModelJob? { model.jobs[variant.id] }
    private var running: Bool { job.map { $0.error == nil && !$0.finished } ?? false }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 18) {
                Text(variant.name).frame(width: 64, alignment: .leading)
                Measure(label: "Disk", value: gigabytes(variant.bytes))
                if let m = variant.memoryBytes { Measure(label: "RAM", value: gigabytes(m)) }
                Spacer()
                actions
            }
            if let job, running {
                Text(job.status).font(.caption).foregroundStyle(.secondary).monospacedDigit()
            } else if let e = job?.error {
                Text(e).font(.caption).foregroundStyle(.red).fixedSize(horizontal: false, vertical: true)
            }
        }
        .confirmationDialog("Remove \(variant.name) from this Mac?", isPresented: Binding(
            get: { model.confirmRemoval == variant.id }, set: { if !$0 { model.confirmRemoval = nil } })) {
            Button("Remove \(gigabytes(variant.bytes))", role: .destructive) {
                model.remove(catalog: catalog, variant: variant.id)
            }
            Button("Keep", role: .cancel) {}
        } message: {
            Text(inUse ? "It is the model in use: dictation stops until you download one. Its files are deleted from the disk."
                       : "Its files are deleted from the disk. You can download it again later.")
        }
    }

    @ViewBuilder private var actions: some View {
        if let job, running {
            ProgressView(value: job.total > 0 ? job.bytes / job.total : 0).frame(width: 120)
            Button("Cancel") { model.cancel(variant.id) }
        } else if inUse {
            Label("In use", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
            Button("Remove", role: .destructive) { model.confirmRemoval = variant.id }
        } else if variant.downloaded {
            Button("Use") {
                model.apply(SettingStore.variant(variant.id, of: name, variants: variants, in: model.config))
                model.actions?.refreshServer()
            }
            Button("Remove", role: .destructive) { model.confirmRemoval = variant.id }
        } else if variant.canDownload {
            Button("Download") { model.download(catalog: catalog, variant: variant.id) }
        } else {
            ProgressView().controlSize(.small).help("Downloading in the EchoFox window.")
        }
    }
}

/// A measure next to a name: its label grey, its value plain ("Disk 5.6 GB").
struct Measure: View {
    let label: String
    let value: String

    var body: some View {
        HStack(spacing: 5) {
            Text(label).foregroundStyle(.secondary)
            Text(value).monospacedDigit()
        }
        .accessibilityElement(children: .combine)
    }
}

/// The model's prompt template: its own in the config, or its catalog entry's. The language notes follow it.
struct PromptEditor: View {
    @ObservedObject var model: SettingsModel
    private var id: String { "prompt." + (model.menuModel ?? "") }

    private var path: [String]? { model.menuModel.map(SettingStore.promptPath) }
    private var own: String? { path.flatMap { model.config.value($0) as? String } }
    /// The catalog's prompt of the menu's model; nil before the server's info has that model.
    private var catalog: String? { model.info?.model.flatMap { $0.name == model.menuModel ? $0.prompt : nil } }
    private var shown: String { own ?? catalog ?? "" }
    private var text: String { model.drafts[id] ?? shown }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            TextEditor(text: model.draft(id, shown: shown)).font(.system(.body, design: .monospaced))
                .frame(minHeight: 160).inputBox()
            HStack {
                Text("{LANGUAGE} is replaced with the language. The language notes come after the prompt.")
                    .font(.caption).foregroundStyle(.secondary)
                Spacer()
                if own != nil {
                    Button("Restore Default") {
                        model.done(id)
                        if let p = path { model.apply(SettingStore.reset(p, in: model.config)) }
                    }
                }
                Button("Save") {
                    let t = text
                    model.done(id)
                    if let m = model.menuModel {
                        model.apply(SettingStore.prompt(t, of: m, catalog: catalog, in: model.config))
                    }
                }
                .keyboardShortcut("s", modifiers: .command)
                .buttonStyle(.borderedProminent)
                .disabled(text == shown)
            }
        }
    }
}
