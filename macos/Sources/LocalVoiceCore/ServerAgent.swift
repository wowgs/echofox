// The launchd agent of the dictation server when the app carries it (macos/build-app.sh --bundle): Python and the
// server's code in the app's Contents/Resources. The app writes the agent at its start, if it is not what it must be,
// and starts it again; on a Mac where the server runs from the repository (server/launchd.sh), the app has no server
// of its own and leaves the agent alone. The label, the log and the exit timeout are the server's (server/constants.py
// SERVER_LABEL, LOGS, LAUNCHD_EXIT_TIMEOUT_S).
import Foundation

public enum ServerAgent {
    public static let label = "local-voice.gemma-voice"
    /// launchd waits this long for the server to stop: it lets a running recording end (constants.py).
    public static let exitTimeoutSeconds = 210

    /// The server in the app's resources, if the app carries one.
    public static func bundled(resources: URL?) -> (python: URL, server: URL)? {
        guard let r = resources else { return nil }
        let python = r.appendingPathComponent("python/bin/python3"), server = r.appendingPathComponent("server")
        let fm = FileManager.default
        guard fm.isExecutableFile(atPath: python.path),
              fm.fileExists(atPath: server.appendingPathComponent("gemma_voice.py").path) else { return nil }
        return (python, server)
    }

    /// The agent's property list for the bundled server.
    public static func plist(python: URL, server: URL, home: URL) -> [String: Any] {
        let log = home.appendingPathComponent("Library/Logs/local-voice/gemma-voice.log").path
        return ["Label": label,
                "ProgramArguments": [python.path, server.appendingPathComponent("gemma_voice.py").path],
                "WorkingDirectory": server.path,
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
