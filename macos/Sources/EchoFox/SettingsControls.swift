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
    var refused = false
    var onSubmit: () -> Void = {}
    @FocusState private var focused: Bool

    var body: some View {
        TextField("", text: $text, prompt: placeholder.isEmpty ? nil : Text(placeholder))
            .labelsHidden()
            .textFieldStyle(.roundedBorder)
            .multilineTextAlignment(number ? .trailing : .leading)
            .font(number ? .body.monospacedDigit() : .body)
            .frame(width: width)
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.red, lineWidth: refused ? 1.5 : 0))
            .focused($focused)
            .onSubmit(onSubmit)
            .onChange(of: focused) { _, now in if !now { onSubmit() } }
    }
}

/// The unit after a number field, in a column as wide as the widest unit, there even without a unit: so every number
/// field of a page ends at the same place, as in macOS's own settings.
struct UnitLabel: View {
    let unit: String?
    /// Every unit of the window's settings, for the column's width.
    let units: [String]
    var body: some View {
        ZStack(alignment: .leading) {
            ForEach(units, id: \.self) { Text($0).hidden() }
            Text(unit ?? "").foregroundStyle(.secondary)
        }
        .accessibilityHidden(unit == nil)
    }
}

/// Takes the value out of the config, back to its default; it keeps its place when there is nothing to reset.
struct ResetButton: View {
    let visible: Bool
    let help: String
    let action: () -> Void

    var body: some View {
        Button(action: action) { Image(systemName: "arrow.uturn.backward.circle") }
            .buttonStyle(.borderless)
            .help(help)
            .accessibilityLabel("Reset to default")
            .opacity(visible ? 1 : 0)
            .disabled(!visible)
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
