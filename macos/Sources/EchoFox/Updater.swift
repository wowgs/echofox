// The app's updates (docs/distribution.md, "Updates"): Sparkle 2 reads the feed of Info.plist (SUFeedURL), or the
// test feed of the user default updateFeedURL, and installs only an archive signed with the app's key (SUPublicEDKey).
// A scheduled check that finds an update shows no window: the menu says so (Sparkle's gentle reminders, for an app of
// the menu bar), and that line opens Sparkle's window. The restart that installs an update waits while a dictation
// runs.
import AppKit
import Sparkle

final class Updater: NSObject, SPUUpdaterDelegate, SPUStandardUserDriverDelegate {
    /// The user default that points the app at a test feed (docs/distribution.md, "Testing while the repository is
    /// private"); unset, the feed is Info.plist's.
    static let testFeedKey = "updateFeedURL"

    /// The version of a found update that the menu shows, until the user turns to it.
    private(set) var ready: String?
    /// Whether a dictation runs (recording, or waiting for its text): the restart of an update waits for it.
    var busy: () -> Bool = { false }
    var onChange: () -> Void = {}
    private var controller: SPUStandardUpdaterController?
    private var postponed: (() -> Void)?

    func start() {
        controller = SPUStandardUpdaterController(startingUpdater: true, updaterDelegate: self, userDriverDelegate: self)
    }

    /// Check for Updates: Sparkle's window, with the update if there is one.
    func check() { controller?.checkForUpdates(nil) }

    /// A dictation ended: an install that waited for it goes on.
    func idle() {
        guard !busy(), let install = postponed else { return }
        postponed = nil
        Log.write("update: the dictation ended, the app restarts")
        install()
    }

    // MARK: SPUUpdaterDelegate

    func feedURLString(for updater: SPUUpdater) -> String? {
        guard let url = UserDefaults.standard.string(forKey: Self.testFeedKey), !url.isEmpty else { return nil }
        return url
    }

    func updater(_ updater: SPUUpdater, shouldPostponeRelaunchForUpdate item: SUAppcastItem,
                 untilInvokingBlock installHandler: @escaping () -> Void) -> Bool {
        guard busy() else { return false }
        postponed = installHandler
        Log.write("update \(item.displayVersionString): the restart waits for the dictation to end")
        return true
    }

    // MARK: SPUStandardUserDriverDelegate

    var supportsGentleScheduledUpdateReminders: Bool { true }

    func standardUserDriverShouldHandleShowingScheduledUpdate(_ update: SUAppcastItem,
                                                              andInImmediateFocus immediateFocus: Bool) -> Bool {
        false  // the menu shows it
    }

    func standardUserDriverWillHandleShowingUpdate(_ handleShowingUpdate: Bool, forUpdate update: SUAppcastItem,
                                                   state: SPUUserUpdateState) {
        guard !handleShowingUpdate else { return }
        ready = update.displayVersionString
        Log.write("update \(update.displayVersionString) is ready")
        onChange()
    }

    func standardUserDriverDidReceiveUserAttention(forUpdate update: SUAppcastItem) { clear() }

    func standardUserDriverWillFinishUpdateSession() { clear() }

    private func clear() {
        guard ready != nil else { return }
        ready = nil
        onChange()
    }
}
