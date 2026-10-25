// The two permissions the app needs: Accessibility (the hotkey, the focus, the insertion) and the Microphone.
// One system prompt at a time, Accessibility first. The Accessibility prompt is an ordinary window: any window clicked
// goes over it (macOS 27.0.1, 2026-10-15). Two prompts at once showed on top of each other, and after the Microphone
// one was answered, the Accessibility one stayed open under the other windows. So the Microphone is asked once
// Accessibility is granted, or when the speaker taps the hotkey's menu item without it. The app keeps looking: a
// permission taken away in System Settings is noticed, and one given again too.
import AppKit
import AVFoundation
import EchoFoxCore

final class Permissions {
    var onChange: () -> Void = {}
    private(set) var accessibility = AXIsProcessTrusted()
    private var timer: Timer?

    var microphone: AVAuthorizationStatus { AVCaptureDevice.authorizationStatus(for: .audio) }

    func start() {
        askAccessibility()
        timer = Timer.scheduledTimer(withTimeInterval: Tuning.permissionPollSeconds, repeats: true) { [weak self] _ in
            self?.check()
        }
    }

    private func check() {
        let now = AXIsProcessTrusted()
        guard now != accessibility else { return }
        accessibility = now
        Log.write("Accessibility permission \(now ? "granted" : "taken away")")
        if now { askMicrophone() }
        onChange()
    }

    /// The system's Accessibility prompt, if the app is not trusted.
    func askAccessibility() {
        let prompt = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        accessibility = AXIsProcessTrustedWithOptions(prompt)
        Log.write(accessibility ? "Accessibility permission granted" : "asked for the Accessibility permission")
        if accessibility { askMicrophone() }
        onChange()
    }

    /// The system's Microphone prompt, if the app has not asked before.
    func askMicrophone() {
        guard microphone == .notDetermined else { return }
        AVCaptureDevice.requestAccess(for: .audio) { [weak self] ok in
            Log.write("microphone permission: \(ok)")
            DispatchQueue.main.async { self?.onChange() }
        }
    }

    enum Pane: String { case accessibility = "Privacy_Accessibility", microphone = "Privacy_Microphone" }

    func openSettings(_ pane: Pane) {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?\(pane.rawValue)") {
            NSWorkspace.shared.open(url)
        }
    }
}
