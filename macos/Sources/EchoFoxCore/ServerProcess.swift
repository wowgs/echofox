// The dictation server that the app carries (macos/build-app.sh): Python and the server's code in the app's
// Contents/Resources. The app starts it as its own child process and owns it (docs/design.md, "Processes"): the
// server starts the model's llama-server as its child, and both end with the app. The server holds the read end of a
// pipe as its standard input (--parent), so it ends also when the app ends without quitting. A server that ends while
// the app runs is started again (restartDelay). An app that runs from a disk image or from App Translocation starts
// no server: it asks to be moved to Applications. Versions before this ran the server and the model as launchd
// agents, without the app; the app removes those agents at its start (legacyAgents).
import Foundation

public enum ServerProcess {
    public static let logInHome = "Library/Logs/EchoFox/gemma-voice.log"
    /// The launchd agents of the versions that ran the server and the model without the app.
    public static let legacyAgents = ["echofox.gemma-voice", "echofox.llama-server"]
    /// A server that ran at least this long ended for a reason of its own (a changed port): it starts again at once.
    public static let steadySeconds = 30.0
    public static let firstDelaySeconds = 1.0
    public static let maxDelaySeconds = 60.0

    /// How the app starts the server.
    public struct Launch: Equatable {
        public let executable: URL
        public let arguments: [String]
        /// Added to the app's own environment.
        public let environment: [String: String]
        public let directory: URL
    }

    /// The server in the app's resources, if the app carries one.
    public static func bundled(resources: URL?) -> (python: URL, server: URL)? {
        guard let r = resources else { return nil }
        let python = r.appendingPathComponent("python/bin/python3"), server = r.appendingPathComponent("server")
        let fm = FileManager.default
        guard fm.isExecutableFile(atPath: python.path),
              fm.fileExists(atPath: server.appendingPathComponent("gemma_voice.py").path) else { return nil }
        return (python, server)
    }

    /// Why the app at this path must not start the server, or nil if it may: macOS runs a quarantined app from a
    /// random read-only folder (App Translocation), and an app opened from a disk image is on a read-only volume.
    public static func misplaced(app path: String, readOnlyVolume: Bool) -> String? {
        if path.contains("/AppTranslocation/") { return "from a temporary folder of macOS (App Translocation)" }
        if readOnlyVolume { return "from a read-only volume, such as the disk image" }
        return nil
    }

    /// The bundled server of this app version. Python writes no bytecode: the bundle carries it (build-app.sh), and
    /// a new file would break the app's signature. The version goes to the server's log.
    public static func launch(python: URL, server: URL, version: String) -> Launch {
        Launch(executable: python, arguments: [server.appendingPathComponent("gemma_voice.py").path, "--parent"],
               environment: ["PYTHONDONTWRITEBYTECODE": "1", "ECHOFOX_APP_VERSION": version], directory: server)
    }

    /// The wait before a server that ended is started again: none of note after one that ran steadily, else twice
    /// the wait before (from firstDelaySeconds), up to maxDelaySeconds, so that a server that cannot start does not
    /// spin.
    public static func restartDelay(previous: Double, ranSeconds: Double) -> Double {
        ranSeconds >= steadySeconds ? firstDelaySeconds : min(maxDelaySeconds, max(firstDelaySeconds, previous * 2))
    }

    /// launchctl's command that stops a legacy agent, and the file that goes after it.
    public static func legacyRemoval(domain: String, home: URL) -> [(command: [String], file: URL)] {
        legacyAgents.map { (["bootout", "\(domain)/\($0)"], home.appendingPathComponent("Library/LaunchAgents/\($0).plist")) }
    }
}
