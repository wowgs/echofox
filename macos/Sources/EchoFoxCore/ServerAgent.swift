// The launchd agent of the dictation server when the app carries it (macos/build-app.sh --bundle): Python and the
// server's code in the app's Contents/Resources. The app writes the agent at its start, if it is not what it must be,
// and starts it again; on a Mac where the server runs from the repository (server/launchd.sh), the app has no server
// of its own and leaves the agent alone. The agent carries the app's version, so a new version in the same place
// starts the server again. An app that runs from a disk image or from App Translocation writes no agent: launchd would
// keep a path that is gone after the image is ejected or the app quits. The label, the log and the exit timeout are
// the server's (shared/constants.json); server/launchd.sh writes the same agent for a server that runs from the
// repository, so one Mac has one server on the working port, whichever wrote it last.
import Foundation

public enum ServerAgent {
    public static let label = "echofox.gemma-voice"
    /// launchd waits this long for the server to stop: it lets a running recording end.
    public static let exitTimeoutSeconds = 210
    public static let logInHome = "Library/Logs/EchoFox/gemma-voice.log"

    /// The server in the app's resources, if the app carries one.
    public static func bundled(resources: URL?) -> (python: URL, server: URL)? {
        guard let r = resources else { return nil }
        let python = r.appendingPathComponent("python/bin/python3"), server = r.appendingPathComponent("server")
        let fm = FileManager.default
        guard fm.isExecutableFile(atPath: python.path),
              fm.fileExists(atPath: server.appendingPathComponent("gemma_voice.py").path) else { return nil }
        return (python, server)
    }

    /// Why the app at this path must not write the agent, or nil if it may: macOS runs a quarantined app from a random
    /// read-only folder (App Translocation), and an app opened from a disk image is on a read-only volume.
    public static func misplaced(app path: String, readOnlyVolume: Bool) -> String? {
        if path.contains("/AppTranslocation/") { return "from a temporary folder of macOS (App Translocation)" }
        if readOnlyVolume { return "from a read-only volume, such as the disk image" }
        return nil
    }

    /// The agent's property list for the bundled server of this app version. Python writes no bytecode: the bundle
    /// carries it (build-app.sh), and a new file would break the app's signature.
    public static func plist(python: URL, server: URL, home: URL, version: String) -> [String: Any] {
        let log = home.appendingPathComponent(logInHome).path
        return ["Label": label,
                "ProgramArguments": [python.path, server.appendingPathComponent("gemma_voice.py").path],
                "WorkingDirectory": server.path,
                "EnvironmentVariables": ["PYTHONDONTWRITEBYTECODE": "1", "ECHOFOX_APP_VERSION": version],
                "RunAtLoad": true, "KeepAlive": true, "ExitTimeOut": exitTimeoutSeconds,
                "ProcessType": "Interactive", "StandardOutPath": log, "StandardErrorPath": log]
    }

    public static func url(home: URL) -> URL {
        home.appendingPathComponent("Library/LaunchAgents/\(label).plist")
    }

    /// Whether the agent's file differs from what it must be (or is not there).
    public static func differs(_ wanted: [String: Any], at url: URL) -> Bool {
        guard let data = try? Data(contentsOf: url),
              let now = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any]
        else { return true }
        return !NSDictionary(dictionary: now).isEqual(to: wanted)
    }
}
