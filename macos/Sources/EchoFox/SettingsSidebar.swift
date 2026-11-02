// The settings window's content: the sidebar (SettingsLayout.sidebar: the pages, then a row per adapter under the
// heading Adapters, then About and Uninstall at its bottom) and the selected page beside it.
import AppKit
import EchoFoxCore
import SwiftUI

struct SettingsView: View {
    @ObservedObject var model: SettingsModel

    var body: some View {
        // A plain sidebar and page: no window toolbar, so no sidebar button and no band over the page
        HStack(spacing: 0) {
            List(selection: $model.selection) {
                ForEach(SettingsLayout.sidebar, id: \.self) { entry in
                    switch entry {
                    case let .page(page):
                        Label {
                            Text(page.title)
                        } icon: {
                            SidebarIcon { Image(systemName: page.symbol).resizable().scaledToFit() }
                        }
                        .tag(SidebarItem.page(page))
                    case .adapters:
                        // A section, not a page: its heading opens and closes the adapters' rows; macOS shows its
                        // chevron at the right of the heading when the pointer is over it.
                        Section(SidebarEntry.adaptersTitle, isExpanded: $model.adaptersOpen) {
                            ForEach(model.adapters, id: \.name) { a in
                                AdapterSidebarRow(model: model, adapter: a).tag(SidebarItem.adapter(a.name))
                            }
                        }
                    }
                }
            }
            .listStyle(.sidebar)
            .safeAreaInset(edge: .bottom) { SidebarFooter(model: model) }
            .frame(width: 210)
            Divider()
            Group {
                switch model.selection {
                case let .page(page)?: PageView(model: model, page: page)
                case let .adapter(name)?:
                    if let a = model.adapters.first(where: { $0.name == name }) {
                        AdapterPage(model: model, adapter: a)
                    } else {
                        Text("The server does not have this adapter any more.").foregroundStyle(.secondary)
                    }
                case nil: EmptyView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}

/// A sidebar row's icon in a column of its own: fitted into a square of one size and centered, so that a wide symbol
/// (the stethoscope) and a narrow one (the microphone) take the same room and every title starts at one line.
struct SidebarIcon<Icon: View>: View {
    static var size: CGFloat { 18 }
    static var column: CGFloat { 24 }
    @ViewBuilder let icon: () -> Icon

    var body: some View {
        icon().frame(width: Self.size, height: Self.size).frame(width: Self.column)
    }
}

/// An adapter in the sidebar: the icon of the app it reads, its name (grey when it is off), and a dot for its state
/// as on the page Diagnostics: green when it is on, red when it does not work, none when it is off.
struct AdapterSidebarRow: View {
    @ObservedObject var model: SettingsModel
    let adapter: ServerInfo.Adapter

    private var on: Bool { model.config.adapters[adapter.name] == true }

    var body: some View {
        Label {
            HStack {
                Text(ServerInfo.adapterTitle(adapter.name, in: model.adapters))
                    .foregroundStyle(on || adapter.error != nil ? .primary : .secondary)
                Spacer()
                if adapter.error != nil { StatusDot(color: .red) } else if on { StatusDot(color: .green) }
            }
        } icon: {
            SidebarIcon { AppIcon(bundleIds: adapter.apps) }
        }
        .help(adapter.error.map { "It does not work: \($0)" } ?? (on ? "On" : "Off"))
    }
}

/// The bottom of the sidebar: About, and Uninstall, which asks first (Uninstaller).
struct SidebarFooter: View {
    @ObservedObject var model: SettingsModel

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Divider().padding(.bottom, 4)
            Button { NSApp.orderFrontStandardAboutPanel(nil) } label: { Label("About EchoFox", systemImage: "info.circle") }
            Button(role: .destructive) { model.actions?.uninstall() } label: { Label("Uninstall…", systemImage: "trash") }
                .foregroundStyle(.red)
        }
        .buttonStyle(.plain).font(.callout).foregroundStyle(.secondary)
        .padding(.horizontal, 16).padding(.bottom, 12)
    }
}
