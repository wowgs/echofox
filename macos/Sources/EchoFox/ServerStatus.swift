// The Diagnostics page's server state in the settings window.
import EchoFoxCore
import SwiftUI

/// The dictation server's state, asked in the background while it is shown: a dot as in macOS's own settings (green:
/// it answers; red: it does not, and why; grey: not asked yet).
struct ServerStatus: View {
    @ObservedObject var model: SettingsModel

    private var state: (color: Color, text: String) {
        if let p = model.problem { return (.red, p) }
        if model.info != nil { return (.green, "Running") }
        return (.secondary, "Checking…")
    }

    var body: some View {
        LabeledContent("Dictation server") { Text(model.config.serverURL.absoluteString).textSelection(.enabled) }
        LabeledContent("State") {
            HStack(spacing: 6) {
                StatusDot(color: state.color)
                Text(state.text).textSelection(.enabled)
            }
            .accessibilityElement(children: .combine)
        }
        .onAppear { model.watchServer(true) }
        .onDisappear { model.watchServer(false) }
        LabeledContent("Model") { Text(model.info?.model?.title ?? model.config.model ?? "not known") }
    }
}
