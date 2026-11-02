// The two permissions the app needs: Accessibility (the hotkey, the focus, the insertion) and the Microphone. The app
// asks for neither at its start: the first start's window and the menu show what is missing, and a click there brings
// one window: the system's prompt for the Microphone, System Settings' Accessibility page for Accessibility (two
// prompts at once showed on top of each other, and the Accessibility one, an ordinary window, stayed under the others;
// macOS 27.0.1, 2026-10-15). A dictation without the Microphone asks for it.
// The app keeps looking: a permission taken away in System Settings is noticed, and one given again too.
import AppKit
import AVFoundation
import EchoFoxCore

final class Permissions {
    var onChange: () -> Void = {}
    private(set) var accessibility = AXIsProcessTrusted()
    private var timer: Timer?

    var microphone: AVAuthorizationStatus { AVCaptureDevice.authorizationStatus(for: .audio) }

    func start() {
        timer = Timer.scheduledTimer(withTimeInterval: Tuning.permissionPollSeconds, repeats: true) { [weak self] _ in
            self?.check()
        }
    }

    private lazy var lastMicrophone = microphone

    private func check() {
        let now = AXIsProcessTrusted(), mic = microphone
        guard now != accessibility || mic != lastMicrophone else { return }
        if now != accessibility { Log.write("Accessibility permission \(now ? "granted" : "taken away")") }
        if mic != lastMicrophone { Log.write("microphone permission: \(mic == .authorized ? "granted" : "not granted")") }
        accessibility = now
        lastMicrophone = mic
        onChange()
    }

    /// System Settings' Accessibility page, where the user turns the app on. The system's own prompt is not shown:
    /// it opened together with the page, two windows for one switch, and its button only leads to the same page.
    /// Whether the app is in the page's list before it ever showed the prompt is not checked.
    func askAccessibility() {
        let noPrompt = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: false] as CFDictionary
        accessibility = AXIsProcessTrustedWithOptions(noPrompt)
        Log.write(accessibility ? "Accessibility permission granted" : "opened the Accessibility page of System Settings")
        if !accessibility { openSettings(.accessibility) }
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
