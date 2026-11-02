// A page of the settings window: its sections from SettingsLayout, each item one of the app's own views or a
// SettingRow for a setting described by a SettingInfo; the Advanced section opens on a click.
import EchoFoxCore
import SwiftUI

struct PageView: View {
    @ObservedObject var model: SettingsModel
    let page: SettingsPage

    var body: some View {
        Form {
            if model.info == nil && page.showsServerSettings {
                Text("The dictation server is not answering. Its settings appear here when it answers.")
                    .foregroundStyle(.secondary)
            }
            ForEach(model.sections(page), id: \.section) { section in
                if section.section == SettingsLayout.advanced {
                    AdvancedSection(model: model, id: page.rawValue,
                                    changed: model.changed(section.ids.flatMap(model.shown))) {
                        ForEach(section.ids, id: \.self) { id in ItemView(model: model, id: id) }
                    }
                } else if let header = SettingsLayout.header(section.section, on: page) {
                    Section(header) {
                        ForEach(section.ids, id: \.self) { id in ItemView(model: model, id: id) }
                    }
                } else {
                    Section {
                        ForEach(section.ids, id: \.self) { id in ItemView(model: model, id: id) }
                    }
                }
            }
        }
        .formStyle(.grouped)
    }
}

/// One item of a page: one of the app's own, or a server setting from its description.
struct ItemView: View {
    @ObservedObject var model: SettingsModel
    let id: String

    var body: some View {
        switch id {
        case "dictationKey": KeyPicker(model: model, isPrivate: false, title: "Dictation",
                                       note: "Tap to start and stop. The text goes where the cursor was.")
        case "privateDictationKey": KeyPicker(model: model, isPrivate: true, title: "Private dictation",
                                              note: "Reads nothing on the screen and saves nothing.")
        case "language": LanguagePicker(model: model)
        case "commonNotes": LanguageList(model: model, list: .notes, title: "Notes for every language",
                                         note: "{LANGUAGE} is replaced with the language. English speech gets none.",
                                         every: true)
        case "languageNotes": LanguageList(model: model, list: .notes, title: "Notes for this language",
                                           note: "Rules about this language for the model, one on each line.")
        case "languageFillers": LanguageList(model: model, list: .fillers, title: "Hesitation sounds",
                                             note: "Removed from the text. Separate them with commas.")
        case "microphone": MicrophonePicker(model: model)
        case "inputVolume": VolumeRow(model: model)
        case "model": ModelPicker(model: model)
        case "variant": VariantPicker(model: model)
        case "prompt": PromptEditor(model: model)
        case "labelStats":
            LabeledContent("Labeled") {
                Text("\(model.labels.count) pieces, \(String(format: "%.1f", model.labels.seconds / 60)) min")
            }
        case "labelRecordings": Button("Label Recordings…") { model.actions?.openLabeling() }
        case "serverStatus": ServerStatus(model: model)
        case "openLog": Button("Open the Log") { model.actions?.openLog() }
        default:
            if let s = model.setting(id) { SettingRow(model: model, setting: s, scope: .owner) }
        }
    }
}

/// A setting described by a SettingInfo, in one scope: a switch, a number or a text; the inherited value is the empty
/// field's placeholder; the reset button takes the value out of the config.
struct SettingRow: View {
    @ObservedObject var model: SettingsModel
    let setting: SettingInfo
    let scope: SettingScope

    private var id: String {
        switch scope {
        case .owner: return "setting." + setting.key
        case let .adapter(a): return "adapter.\(a.name).\(setting.key)"
        }
    }
    private var state: SettingState { model.state(setting, scope) }
    private var refused: Bool { model.refused.contains(id) }
    /// The field's text: the value set here; empty when it is inherited (the placeholder shows it).
    private var shown: String {
        ["string", "folder"].contains(setting.kind) ? SettingText.value(state.value) : state.own.map { SettingText.value($0) } ?? ""
    }

    private var note: String? {
        if refused { return SettingText.allowedValues(setting) }
        let parts = [setting.help, scope == .owner ? "" : SettingText.source(state, adapters: model.adapters)]
            .filter { !$0.isEmpty }
        return parts.isEmpty ? nil : parts.joined(separator: " ")
    }

    var body: some View {
        SettingLine(title: setting.title, note: note, refused: refused,
                    pending: model.drafts[id].map { $0 != shown } ?? false) {
            // The reset before the control, so that the controls end at the row's edge
            ResetButton(visible: state.changed, help: "Restore the default") {
                model.apply(.remove, to: setting, scope, id: id)
            }
            control
        }
        .disabled(state.path == nil || disabledAdapter)
    }

    /// A setting of an adapter that is off: shown, not changed.
    private var disabledAdapter: Bool {
        if case let .adapter(a) = scope { return model.config.adapters[a.name] != true }
        return false
    }

    @ViewBuilder private var control: some View {
        switch setting.kind {
        case "boolean":
            Toggle("", isOn: Binding(get: { state.value == .bool(true) },
                                     set: { model.apply(SettingStore.toggle($0, state: state), to: setting, scope, id: id) }))
                .labelsHidden().toggleStyle(.switch)
        case "string", "folder":
            InputField(text: model.draft(id, shown: shown), width: 240, refused: refused, onSubmit: commit)
            if setting.kind == "folder" {
                Button("Choose…") {
                    if let folder = chooseFolder(starting: shown) {
                        model.apply(SettingStore.edit(folder, of: setting, state: state), to: setting, scope, id: id)
                    }
                }
            }
        default:
            InputField(placeholder: SettingText.value(state.inherited), text: model.draft(id, shown: shown), width: 110,
                       number: true, unit: setting.unit, refused: refused, onSubmit: commit)
        }
    }

    private func commit() {
        guard let text = model.drafts[id] else { return }
        model.apply(SettingStore.edit(text, of: setting, state: state), to: setting, scope, id: id)
    }
}

/// An Advanced section: closed until a click; its title says how many of its settings differ from what they would be
/// without a value there, so that a change is never out of sight.
struct AdvancedSection<Content: View>: View {
    @ObservedObject var model: SettingsModel
    let id: String
    let changed: Int
    @ViewBuilder var content: () -> Content

    var body: some View {
        Section {
            DisclosureGroup(isExpanded: model.isOpen(id)) {
                content()
            } label: {
                // The whole row, not only the triangle: a click anywhere on it opens or closes the section.
                Button {
                    withAnimation { model.isOpen(id).wrappedValue.toggle() }
                } label: {
                    HStack {
                        Text(SettingsLayout.advanced)
                        if changed > 0 { Text("\(changed) changed").font(.caption).foregroundStyle(.secondary) }
                        Spacer()
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityHint("Shows or hides the advanced settings")
            }
        }
    }
}
