// The app's one owner of the config file (Config): it holds the file as last read, writes through one
// path (each write logged, a failed one reported), and looks at the file every Tuning.configCheckSeconds, as the
// server does, so that a change from elsewhere (an editor, the server's migration) reaches the hotkeys, the server,
// the menu and the windows. It runs on the main thread.
import Foundation

public final class ConfigStore {
    public private(set) var config: Config
    private let url: URL
    private var seen: Date?
    private var observers: [(_ old: Config, _ new: Config) -> Void] = []
    private var timer: Timer?
    /// A write that failed: what to tell the user.
    public var onError: (String) -> Void = { _ in }
    /// Where a write and a config that does not read go (the app's log).
    public var log: (String) -> Void = { _ in }

    public init(url: URL = Config.url) {
        self.url = url
        config = Config.load(from: url)
        seen = Self.modified(url)
    }

    /// Starts looking at the file.
    public func start() {
        timer = Timer.scheduledTimer(withTimeInterval: Tuning.configCheckSeconds, repeats: true) { [weak self] _ in
            self?.check()
        }
    }

    /// `f(old, new)` runs on each change of the config, after it is read again.
    public func observe(_ f: @escaping (_ old: Config, _ new: Config) -> Void) { observers.append(f) }

    /// Writes a change that SettingStore made (a value equal to its default is never written: it takes the key out).
    /// It is the app's one way into the file: Config.set writes a value, Config.remove takes one out. Nil, nothing to
    /// change, writes nothing. False if a write failed.
    @discardableResult
    public func apply(_ change: ConfigChange?, _ done: String) -> Bool {
        switch change {
        case nil: return true
        case let .set(path, value)?: return write(done) { try Config.set(path, to: value, in: url) }
        case let .remove(path)?: return write(done) { try Config.remove(path, in: url) }
        }
    }

    private func write(_ done: String, _ write: () throws -> Void) -> Bool {
        do {
            try write()
            log(done)
            reload()
            return true
        } catch {
            onError("cannot write the config: \(error)")
            return false
        }
    }

    /// One look at the file (the timer's); the config is read again if the file changed.
    public func check() {
        if Self.modified(url) != seen { reload() }
    }

    private func reload() {
        seen = Self.modified(url)
        let old = config
        config = Config.load(from: url)
        if let e = config.error, e != old.error { log("config: \(e)") }
        if let n = config.note, n != old.note { log("config: \(n)") }
        if config != old { observers.forEach { $0(old, config) } }
    }

    private static func modified(_ url: URL) -> Date? {
        (try? FileManager.default.attributesOfItem(atPath: url.path))?[.modificationDate] as? Date
    }
}
