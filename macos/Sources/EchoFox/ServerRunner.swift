// The dictation server as the app's child process (ServerProcess): started with the app, started again if it ends
// while the app runs, ended at the app's quit. Its output goes to its log. The app keeps the write end of the
// server's standard input open and writes nothing: when the app ends in any way, the pipe closes and the server ends.
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

    /// Starts the server; on the main thread.
    func start() {
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
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in self?.start() }
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
