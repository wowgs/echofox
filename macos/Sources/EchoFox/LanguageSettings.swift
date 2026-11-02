// The settings window's Language page: the speech's language, and the lists of the server's prompt (the notes of every
// language, the chosen language's notes and its hesitation sounds). The defaults are the server's
// (server/languages.json); a list or a language equal to its default takes its key out of the config (SettingStore).
import EchoFoxCore
import SwiftUI

struct LanguagePicker: View {
    @ObservedObject var model: SettingsModel

    private var languages: [ServerInfo.Language] { model.info?.languages ?? [] }

    var body: some View {
        Picker("Language", selection: Binding(get: { model.config.language }, set: {
            model.apply(SettingStore.language($0, in: model.config))
        })) {
            Text("Any").tag("")
            ForEach(languages, id: \.code) { Text($0.name).tag($0.code) }
            if !model.config.language.isEmpty, !languages.contains(where: { $0.code == model.config.language }) {
                Text(model.config.language).tag(model.config.language)
            }
        }
    }
}

/// A language's list (its notes or its hesitation sounds), or with `every` the notes of every language: the config's,
/// else the server's.
struct LanguageList: View {
    @ObservedObject var model: SettingsModel
    let list: SettingStore.LanguageList
    let title: String, note: String
    var every = false

    private var code: String { every ? SettingStore.LanguageList.every : Config.languageCode(model.config.language) }
    private var id: String { "language.\(code).\(list.rawValue)" }
    private var path: [String] { list.path(of: code) }
    private var own: [String]? { model.config.value(path) as? [String] }
    private var shown: String { list.text(own ?? list.defaults(of: code, in: model.info) ?? []) }

    var body: some View {
        if code.isEmpty {
            Text("Choose a language to see its notes and sounds.").foregroundStyle(.secondary)
        } else {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(title)
                    Spacer()
                    ResetButton(visible: own != nil, help: "Restore the defaults") {
                        model.done(id)
                        model.apply(SettingStore.reset(path, in: model.config))
                    }
                }
                if list == .notes {
                    TextEditor(text: model.draft(id, shown: shown)).frame(minHeight: 60).inputBox()
                } else {
                    InputField(text: model.draft(id, shown: shown), width: 360) { save() }
                }
                HStack {
                    Text(note).font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    if list == .notes { Button("Save") { save() }.disabled((model.drafts[id] ?? shown) == shown) }
                }
            }
        }
    }

    private func save() {
        guard let text = model.drafts[id] else { return }
        model.done(id)
        model.apply(SettingStore.list(list, of: code, text: text, info: model.info, in: model.config))
    }
}
