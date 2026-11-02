// The dictation server as the app's child process (ServerProcess): started with the app, started again if it ends
// while the app runs, ended at the app's quit. Its output goes to its log. The app keeps the write end of the
// server's standard input open and writes nothing: when the app ends in any way, the pipe closes and the server ends.
// Before the first start it removes the launchd agents of the versions that ran the server without the app.
import EchoFoxCore
import Foundation

final class ServerRunner {
    private let launch: ServerProcess.Launch
    private let log: URL
    private var process: Process?
    private var input: Pipe?
    private var quitting = false
    private var delay = 0.0
    private var startedAt = Date()
    /// Called on the main thread after each start, so that the app asks the new server for its info.
    var onStart: (() -> Void)?

    init(launch: ServerProcess.Launch, log: URL) {
        self.launch = launch
        self.log = log
    }

    /// The server that this app carries, of this app version; nil for an app without one, which uses the server at
    /// the config's address.
    static func bundled(version: String) -> ServerRunner? {
        guard let (python, server) = ServerProcess.bundled(resources: Bundle.main.resourceURL) else { return nil }
        return ServerRunner(launch: ServerProcess.launch(python: python, server: server, version: version),
                            log: FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(ServerProcess.logInHome))
    }

    /// The first start, on the main thread: the launchd agents of older versions go first. launchctl waits, so that
    /// runs off the main thread, and the server starts after it.
    func start() {
        let home = FileManager.default.homeDirectoryForCurrentUser
        DispatchQueue.global(qos: .userInitiated).async {
            for (command, file) in ServerProcess.legacyRemoval(domain: "gui/\(getuid())", home: home)
            where FileManager.default.fileExists(atPath: file.path) {
                let code = Self.launchctl(command)
                try? FileManager.default.removeItem(at: file)
                Log.write("server: the launchd agent \(file.lastPathComponent) of an older version removed, bootout exit \(code)")
            }
            DispatchQueue.main.async { self.run() }
        }
    }

    /// Starts the server; on the main thread.
    private func run() {
        guard !quitting else { return }
        let p = Process(), pipe = Pipe()
        p.executableURL = launch.executable
        p.arguments = launch.arguments
        p.currentDirectoryURL = launch.directory
        p.environment = ProcessInfo.processInfo.environment.merging(launch.environment) { $1 }
        p.standardInput = pipe
        if let out = Self.append(to: log) {
            p.standardOutput = out
            p.standardError = out
        }
        p.terminationHandler = { [weak self] ended in
            DispatchQueue.main.async { self?.ended(ended) }
        }
        do {
            try p.run()
            (process, input, startedAt) = (p, pipe, Date())
            Log.write("server: started, pid \(p.processIdentifier)")
            onStart?()
        } catch {
            Log.write("server: cannot start \(launch.executable.path): \(error)")
            ended(nil)
        }
    }

    /// The app quits: the server ends (SIGTERM), and its llama-server with it. The app does not wait for it.
    func stop() {
        quitting = true
        process?.terminate()
    }

    private func ended(_ p: Process?) {
        if let p { Log.write("server: ended, pid \(p.processIdentifier), status \(p.terminationStatus)") }
        (process, input) = (nil, nil)
        guard !quitting else { return }
        delay = ServerProcess.restartDelay(previous: delay, ranSeconds: Date().timeIntervalSince(startedAt))
        Log.write("server: starting again in \(delay) s")
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in self?.run() }
    }

    @discardableResult
    private static func launchctl(_ args: [String]) -> Int32 {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        p.arguments = args
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        guard (try? p.run()) != nil else { return -1 }
        p.waitUntilExit()
        return p.terminationStatus
    }

    private static func append(to url: URL) -> FileHandle? {
        let fm = FileManager.default
        try? fm.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        if !fm.fileExists(atPath: url.path) { fm.createFile(atPath: url.path, contents: nil) }
        guard let h = try? FileHandle(forWritingTo: url) else { return nil }
        h.seekToEndOfFile()
        return h
    }
}
