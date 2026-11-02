// The settings window's pickers of the hotkeys and the microphone, and the microphone's input volume. A choice goes
// into the config as SettingStore says (a default takes the key out); the microphone through the App, as the menu's.
import EchoFoxCore
import SwiftUI

/// A hotkey: one of the right-hand modifier keys, or None. A key that the other action has too is marked.
struct KeyPicker: View {
    @ObservedObject var model: SettingsModel
    let isPrivate: Bool, title: String, note: String

    private var current: TapKeyChoice? { isPrivate ? model.config.privateDictationKey : model.config.dictationKey }

    var body: some View {
        SettingLine(title: title, note: model.config.keysClash ? "The other dictation uses this key too. Choose another one." : note,
                    refused: model.config.keysClash) {
            Picker(title, selection: Binding(get: { TapKeyChoice.configValue(current) }, set: { v in
                model.apply(SettingStore.hotkey(TapKeyChoice(rawValue: v), isPrivate: isPrivate, in: model.config))
            })) {
                ForEach(TapKeyChoice.allCases, id: \.rawValue) { Text($0.title).tag($0.rawValue) }
                Text("None").tag(TapKeyChoice.off)
            }
            .labelsHidden()
            .fixedSize()
        }
    }
}

struct MicrophonePicker: View {
    @ObservedObject var model: SettingsModel

    /// The config's microphone is one of the choices: a connected device, the built-in one, or macOS's input.
    private var chosenIsListed: Bool {
        MicrophoneChoice.isListed(model.config.microphone, among: model.inputs.map(\.device))
    }

    var body: some View {
        Picker("Microphone", selection: Binding(get: { model.config.microphone }, set: {
            model.actions?.choose(microphone: $0)
            model.microphoneChanged()
        })) {
            ForEach(model.inputs, id: \.uid) { input in
                Text(input.name + (input.builtIn ? " (built-in)" : "")).tag(MicrophoneChoice.value(for: input.device))
            }
            Text("Follow macOS's input").tag(Config.systemMicrophone)
            if !chosenIsListed { Text("Not connected").tag(model.config.microphone) }
        }
    }
}

struct VolumeRow: View {
    @ObservedObject var model: SettingsModel

    var body: some View {
        if let v = model.volume {
            LabeledContent("Input volume") {
                Slider(value: Binding(get: { Double(v) }, set: { x in
                    model.actions?.setInputVolume(Float(x))
                    model.volume = Float(x)
                }), in: 0...1).frame(width: 220)
                Text("\(Int((Double(v) * 100).rounded()))%").monospacedDigit().frame(width: 44, alignment: .trailing)
            }
        } else {
            LabeledContent("Input volume") { Text("This microphone has no volume control.").foregroundStyle(.secondary) }
        }
    }
}
