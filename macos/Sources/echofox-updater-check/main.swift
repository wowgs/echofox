// The check of a built app's update settings (build-app.sh runs it): Sparkle's updater is started for the app as its
// host bundle, with a user driver that shows nothing, and it fails as the app's own would at launch when the keys of
// Info.plist do not fit together (SURequireSignedFeed needs SUVerifyUpdateBeforeExtraction, 2026-10-26).
// Usage: echofox-updater-check <EchoFox.app>
import AppKit
import Sparkle

final class Driver: NSObject, SPUUserDriver {
    func show(_ request: SPUUpdatePermissionRequest, reply: @escaping (SUUpdatePermissionResponse) -> Void) {}
    func showUserInitiatedUpdateCheck(cancellation: @escaping () -> Void) {}
    func showUpdateFound(with appcastItem: SUAppcastItem, state: SPUUserUpdateState, reply: @escaping (SPUUserUpdateChoice) -> Void) {}
    func showUpdateReleaseNotes(with downloadData: SPUDownloadData) {}
    func showUpdateReleaseNotesFailedToDownloadWithError(_ error: Error) {}
    func showUpdateNotFoundWithError(_ error: Error, acknowledgement: @escaping () -> Void) {}
    func showUpdaterError(_ error: Error, acknowledgement: @escaping () -> Void) {}
    func showDownloadInitiated(cancellation: @escaping () -> Void) {}
    func showDownloadDidReceiveExpectedContentLength(_ expectedContentLength: UInt64) {}
    func showDownloadDidReceiveData(ofLength length: UInt64) {}
    func showDownloadDidStartExtractingUpdate() {}
    func showExtractionReceivedProgress(_ progress: Double) {}
    func showReady(toInstallAndRelaunch reply: @escaping (SPUUserUpdateChoice) -> Void) {}
    func showInstallingUpdate(withApplicationTerminated applicationTerminated: Bool, retryTerminatingApplication: @escaping () -> Void) {}
    func showUpdateInstalledAndRelaunched(_ relaunched: Bool, acknowledgement: @escaping () -> Void) {}
    func showUpdateInFocus() {}
    func dismissUpdateInstallation() {}
}
guard CommandLine.arguments.count == 2, let app = Bundle(path: CommandLine.arguments[1]) else {
    print("usage: echofox-updater-check <EchoFox.app>")
    exit(2)
}
let updater = SPUUpdater(hostBundle: app, applicationBundle: app, userDriver: Driver(), delegate: nil)
do {
    try updater.start()
    print("the updater starts")
} catch {
    print("the updater does not start: \(error.localizedDescription)")
    exit(1)
}
