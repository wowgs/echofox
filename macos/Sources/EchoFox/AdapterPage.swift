// An adapter's page in the settings window: whether it is on and works, what it reads, and its settings in Advanced.
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

/// One adapter's page: whether it works, what it reads, its settings.
struct AdapterPage: View {
    @ObservedObject var model: SettingsModel
    let adapter: ServerInfo.Adapter

    var body: some View {
        Form {
            Section("Adapter") {
                if let d = adapter.description, !d.isEmpty {
                    Text(d).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
                LabeledContent("On") { AdapterSwitch(model: model, adapter: adapter) }
                if let e = adapter.error {
                    LabeledContent("Problem") { Text(e).foregroundStyle(.red).textSelection(.enabled) }
                }
            }
            // Each list in a section of its own, one row per item, the icons in one column (as in the sidebar)
            Section("Apps it reads") {
                ForEach(adapter.apps, id: \.self) { id in AppRow(bundleId: id) }
            }
            if let reads = adapter.reads, !reads.isEmpty {
                Section("Files it reads") {
                    ForEach(reads, id: \.self) { path in
                        Label { Text(path).textSelection(.enabled) } icon: {
                            SidebarIcon { Image(systemName: "folder").resizable().scaledToFit() }
                        }
                    }
                }
            }
            let screen = adapter.screen ?? []
            let tree = adapter.electronApps ?? (adapter.electronTree ? adapter.apps : [])
            if !screen.isEmpty || !tree.isEmpty {
                Section("From the screen") {
                    // Its kinds of screen text; for an adapter that reads the screen of only some of its apps, one row per app
                    let some = adapter.screenApps.flatMap { Set($0) == Set(adapter.apps) ? nil : $0 }
                    ForEach(screen, id: \.self) { s in
                        let kind = s == "lists" ? "Message lists" : s == "outline" ? "Page text" : s
                        if let some {
                            ForEach(some, id: \.self) { id in AppRow(bundleId: id, note: kind.lowercased()) }
                        } else {
                            Label { Text(kind) } icon: {
                                SidebarIcon {
                                    Image(systemName: s == "lists" ? "list.bullet.rectangle" : "doc.text").resizable().scaledToFit()
                                }
                            }
                        }
                    }
                    ForEach(tree, id: \.self) { id in
                        AppRow(bundleId: id, note: "window content, asked for")
                    }
                }
            }
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
