// The parts the app's windows share for what the user changes, so that every editable field looks editable, the same
// way everywhere (the look of macOS's own settings): a row with the title and its explanation on the leading side and
// the control on the trailing side; text and number fields with a rounded border on the text background, a red one
// when the value is refused; a reset button that always keeps its place, so rows do not jump; a box for longer text.
import AppKit
import SwiftUI

/// A row of a settings page: the title, its explanation under it, and the control on the trailing side.
struct SettingLine<Control: View>: View {
    let title: String
    var note: String? = nil
    var refused = false
    /// A value is typed and not applied yet: say how to apply it.
    var pending = false
    @ViewBuilder var control: () -> Control

    var body: some View {
        LabeledContent {
            HStack(spacing: 6) { control() }
        } label: {
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                if let note {
                    Text(note).font(.caption).foregroundStyle(refused ? Color.red : Color.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if pending { Text("Press Return to apply.").font(.caption).foregroundStyle(Color.accentColor) }
            }
        }
    }
}

/// A state as a small dot, as macOS's own settings show it (Network: green connected, red not): the same in every
/// place of the window that shows a state.
struct StatusDot: View {
    let color: Color
    var body: some View { Image(systemName: "circle.fill").font(.system(size: 8)).foregroundStyle(color) }
}

/// The icon of the first of these apps that is installed, at the size of a sidebar's symbols; else the symbol.
struct AppIcon: View {
    let bundleIds: [String]
    var fallback = "puzzlepiece.extension"

    private static var cache: [String: NSImage] = [:]

    private var image: NSImage? {
        for id in bundleIds {
            if let i = Self.cache[id] { return i }
            if let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: id) {
                let i = NSWorkspace.shared.icon(forFile: url.path)
                Self.cache[id] = i
                return i
            }
        }
        return nil
    }

    var body: some View {
        if let image {
            Image(nsImage: image).resizable().interpolation(.high).frame(width: 18, height: 18)
        } else {
            Image(systemName: fallback)
        }
    }
}

/// An app in a row of its own: its icon in the icon column, its name as Finder shows it (one that is not installed: its
/// bundle id, grey), and a grey note after it.
struct AppRow: View {
    let bundleId: String
    var note: String? = nil

    private var name: String? {
        NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleId)
            .map { FileManager.default.displayName(atPath: $0.path).replacingOccurrences(of: ".app", with: "") }
    }

    var body: some View {
        Label {
            HStack(spacing: 6) {
                if let name { Text(name) } else { Text(bundleId).foregroundStyle(.secondary) }
                if let note { Text(note).foregroundStyle(.secondary) }
            }
        } icon: {
            SidebarIcon { AppIcon(bundleIds: [bundleId]) }
        }
        .help(bundleId)
    }
}

/// A text or number field that looks like one. The placeholder shows inside the empty field, grey; the field has no
/// title of its own: in a grouped Form, SwiftUI shows a TextField's title as a label next to it. What is typed is
/// applied on Return and when the field loses the focus (Apple HIG, Text fields: validate when people switch to
/// another field).
struct InputField: View {
    var placeholder = ""
    @Binding var text: String
    var width: CGFloat = 90
    /// A number: aligned on the trailing side, in digits of one width.
    var number = false
    /// A number's unit, inside the field after the digits ("60 s"), grey.
    var unit: String? = nil
    var refused = false
    var onSubmit: () -> Void = {}
    @FocusState private var focused: Bool

    var body: some View {
        if let unit {
            // The unit inside the field: the box is drawn here, as the rounded field looks, around the digits and it
            HStack(spacing: 4) {
                field.textFieldStyle(.plain)
                Text(unit).foregroundStyle(.secondary).fixedSize()
            }
            .padding(.horizontal, 7)
            .padding(.vertical, 3)
            .frame(width: width)
            .background(RoundedRectangle(cornerRadius: 6).fill(Color(nsColor: .textBackgroundColor)))
            .overlay(RoundedRectangle(cornerRadius: 6)
                .stroke(refused ? Color.red : focused ? Color.accentColor : Color(nsColor: .separatorColor),
                        lineWidth: refused || focused ? 1.5 : 1))
            .contentShape(Rectangle())
            .onTapGesture { focused = true }
        } else {
            field
                .textFieldStyle(.roundedBorder)
                .frame(width: width)
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.red, lineWidth: refused ? 1.5 : 0))
        }
    }

    private var field: some View {
        TextField("", text: $text, prompt: placeholder.isEmpty ? nil : Text(placeholder))
            .labelsHidden()
            .multilineTextAlignment(number ? .trailing : .leading)
            .font(number ? .body.monospacedDigit() : .body)
            .focused($focused)
            .onSubmit(onSubmit)
            .onChange(of: focused) { _, now in if !now { onSubmit() } }
    }
}

/// Takes the value out of the config, back to its default; shown only when there is something to reset.
struct ResetButton: View {
    let visible: Bool
    let help: String
    let action: () -> Void

    var body: some View {
        if visible {
            Button(action: action) { Image(systemName: "arrow.uturn.backward.circle") }
                .buttonStyle(.borderless)
                .help(help)
                .accessibilityLabel("Reset to default")
        }
    }
}

extension View {
    /// A box for longer text (a TextEditor): the text background, a separator-coloured border, an inset.
    func inputBox(cornerRadius: CGFloat = 6) -> some View {
        scrollContentBackground(.hidden)
            .padding(6)
            .background(RoundedRectangle(cornerRadius: cornerRadius).fill(Color(nsColor: .textBackgroundColor)))
            .overlay(RoundedRectangle(cornerRadius: cornerRadius).stroke(Color(nsColor: .separatorColor)))
    }
}

/// A folder chosen in the system's open panel, or nil.
func chooseFolder(starting path: String) -> String? {
    let panel = NSOpenPanel()
    panel.canChooseDirectories = true
    panel.canChooseFiles = false
    panel.canCreateDirectories = true
    panel.directoryURL = URL(fileURLWithPath: (path as NSString).expandingTildeInPath)
    guard panel.runModal() == .OK, let url = panel.url else { return nil }
    let home = FileManager.default.homeDirectoryForCurrentUser.path
    return url.path.hasPrefix(home) ? "~" + url.path.dropFirst(home.count) : url.path
}
