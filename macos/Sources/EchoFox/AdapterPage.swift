// An adapter's page in the settings window: whether it is on and works, a section per surface (its apps, where in them
// it works, and what it reads there), and its settings in Advanced.
import EchoFoxCore
import SwiftUI

struct AdapterSwitch: View {
    @ObservedObject var model: SettingsModel
    let adapter: ServerInfo.Adapter

    var body: some View {
        Toggle("", isOn: Binding(get: { model.config.adapters[adapter.name] == true }, set: { on in
            model.apply(SettingStore.adapter(adapter.name, enabled: on, in: model.config))
            model.actions?.refreshServer()
        }))
        .labelsHidden().toggleStyle(.switch)
    }
}

/// One adapter's page: whether it works, its surfaces, its settings.
struct AdapterPage: View {
    @ObservedObject var model: SettingsModel
    let adapter: ServerInfo.Adapter

    /// The identity: what the app reads at every dictation in an app of an enabled adapter, before the server
    /// matches a surface (FocusSnapshot.capture). The same for every adapter, so it is said once, here.
    static let identityNote = "When it is on, EchoFox reads the app's name, the window title, and the page's address "
        + "and title whenever you dictate in one of the apps below."

    var body: some View {
        Form {
            Section {
                if let d = adapter.description, !d.isEmpty {
                    Text(d).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
                LabeledContent("On") { AdapterSwitch(model: model, adapter: adapter) }
                if let e = adapter.error {
                    LabeledContent("Problem") { Text(e).foregroundStyle(.red).textSelection(.enabled) }
                }
            } header: {
                Text("Adapter")
            } footer: {
                Text(Self.identityNote).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            ForEach(adapter.surfaces, id: \.id) { s in SurfaceSection(surface: s) }
            AdvancedSection(model: model, id: "adapter." + adapter.name,
                            changed: model.changed(model.adapterSettings.map { ($0, .adapter(adapter)) })) {
                ForEach(model.adapterSettings, id: \.key) { s in
                    SettingRow(model: model, setting: s, scope: .adapter(adapter))
                }
            }
        }
        .formStyle(.grouped)
    }
}

/// A surface of an adapter: its apps, one row each (as in the sidebar, the icons in one column), the pages or
/// windows in them where it works, what it reads from the screen, and the files it reads.
struct SurfaceSection: View {
    let surface: ServerInfo.Surface

    var body: some View {
        Section(surface.title) {
            ForEach(surface.apps, id: \.self) { id in AppRow(bundleId: id) }
            if let url = surface.match?.url {
                LabeledContent("Only on pages") { Text(ServerInfo.Surface.Match.shown(url)).textSelection(.enabled) }
            }
            if let title = surface.match?.title {
                LabeledContent("Only in windows titled") {
                    Text(ServerInfo.Surface.Match.shown(title)).textSelection(.enabled)
                }
            }
            let kinds = surface.screen?.kinds ?? []
            if !kinds.isEmpty {
                LabeledContent("From the screen") { Text(kinds.joined(separator: ", ")) }
            }
            // A folder for a fixed place on the disk; a file named only in words gets a page
            ForEach(surface.reads ?? [], id: \.self) { read in
                Label {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(read.what).fixedSize(horizontal: false, vertical: true)
                        if let path = read.path { Text(path).foregroundStyle(.secondary).textSelection(.enabled) }
                    }
                } icon: {
                    SidebarIcon {
                        Image(systemName: read.path == nil ? "doc" : "folder").resizable().scaledToFit()
                    }
                }
            }
        }
    }
}
