// Electron apps (Claude Desktop, VS Code) build their accessibility tree only on request: without it, Claude Desktop
// showed only its window (measured 2026-10-15). Two attributes of the app's AXUIElement ask for it, and both are set:
// AXManualAccessibility, Electron's switch for assistive apps (electronjs.org, "Accessibility"), and
// AXEnhancedUserInterface, which VoiceOver sets and Chromium watches to detect it (the comment in Chromium's
// browser_accessibility_state_impl.h). AXEnhancedUserInterface is set always: an app need not list it among its
// attributes. The caller asks only for the apps of the enabled adapters' surfaces with treeOnRequest
// (ServerInfo.treeApps); no other app is touched, since the tree costs the app CPU and memory.
import ApplicationServices

public enum ElectronTree {
    /// Asks the app to build its accessibility tree. Returns whether the app took either attribute.
    @discardableResult
    public static func enable(pid: pid_t) -> Bool {
        let app = AXUIElementCreateApplication(pid)
        let manual = AXUIElementSetAttributeValue(app, "AXManualAccessibility" as CFString, kCFBooleanTrue)
        let enhanced = AXUIElementSetAttributeValue(app, "AXEnhancedUserInterface" as CFString, kCFBooleanTrue)
        return manual == .success || enhanced == .success
    }
}
