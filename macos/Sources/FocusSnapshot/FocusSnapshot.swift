// The focus snapshot: what the dictation's target looks like when the dictation starts. The core takes it once, at the
// hotkey, and sends it to the dictation server, whose adapters decide whose conversation it is
// (server/adapters/__init__.py has the fields). Only service fields go in, never the text of input fields.
//
// Accessibility needs the "Accessibility" permission of the process that runs this. Electron apps (Claude Desktop,
// VS Code) build their accessibility tree only on request: without AXManualAccessibility set, Claude Desktop showed
// only its window (measured 2026-10-15). After it is set, the focused element appeared 2.1 s later (2087–2104 ms, three
// runs, Claude Desktop 2.37337.1). take() sets it when the focused element is missing, waits up to
// electronWaitSeconds, and leaves it set; prepare(pid:) sets it ahead, so that a later take() need not wait.
import AppKit
import ApplicationServices
import Darwin

public enum FocusSnapshot {
    static let elementFields = ["AXRole", "AXSubrole", "AXTitle", "AXDescription", "AXIdentifier"]
    static let maxAncestors = 80
    static let maxDomClasses = 12
    static let maxProcesses = 40
    public static var electronWaitSeconds = 3.0

    /// A snapshot and the element it was taken of: the element with the keyboard focus, where the text goes later.
    public struct Capture {
        public let snapshot: [String: Any]
        public let focused: AXUIElement?
        public let pid: pid_t?
    }

    /// The snapshot of the frontmost app, as a JSON-ready dictionary.
    public static func take(enableElectron: Bool = true) -> [String: Any] {
        capture(full: true, enableElectron: enableElectron).snapshot
    }

    /// The snapshot of the frontmost app, with its focused element and pid. `full`: the window, the focused element's
    /// ancestors and the app's processes too, for adapters; without it, only the app and the focused element, which
    /// the text goes into later.
    public static func capture(full: Bool = true, enableElectron: Bool = true) -> Capture {
        let started = Date()
        guard let front = NSWorkspace.shared.frontmostApplication else {
            return Capture(snapshot: ["error": "no frontmost app"], focused: nil, pid: nil)
        }
        let pid = front.processIdentifier
        let app = AXUIElementCreateApplication(pid)
        var out: [String: Any] = ["app": ["bundleId": front.bundleIdentifier ?? "", "pid": Int(pid),
                                          "name": front.localizedName ?? ""]]
        out["trusted"] = AXIsProcessTrusted()
        var focused = element(app, "AXFocusedUIElement")
        if focused == nil, enableElectron, hasAttribute(app, "AXManualAccessibility") {
            AXUIElementSetAttributeValue(app, "AXManualAccessibility" as CFString, kCFBooleanTrue)
            out["electronTreeEnabled"] = true
            for _ in 0..<Int(electronWaitSeconds * 20) where focused == nil {
                usleep(50_000)
                focused = element(app, "AXFocusedUIElement")
            }
        }
        guard full else {
            if let f = focused { out["focused"] = describe(f) }
            out["tookMs"] = Int(Date().timeIntervalSince(started) * 1000)
            return Capture(snapshot: out, focused: focused, pid: pid)
        }
        if let w = element(app, "AXFocusedWindow") {
            out["window"] = compact(["title": string(w, "AXTitle"), "document": string(w, "AXDocument")])
        }
        if let f = focused {
            out["focused"] = describe(f)
            var ancestors: [[String: Any]] = []
            var e = f
            for _ in 0..<maxAncestors {
                guard let p = element(e, "AXParent") else { break }
                e = p
                let d = describe(e)
                ancestors.append(d)
                if out["webArea"] == nil, (d["role"] as? String) == "AXWebArea" {
                    out["webArea"] = compact(["url": d["url"], "title": d["title"]])
                }
                if (d["role"] as? String) == "AXWindow" { break }
            }
            out["ancestors"] = ancestors
        }
        out["processes"] = descendants(of: pid)
        out["tookMs"] = Int(Date().timeIntervalSince(started) * 1000)
        return Capture(snapshot: out, focused: focused, pid: pid)
    }

    /// Asks an Electron app to build its accessibility tree now (AXManualAccessibility), so that a snapshot taken
    /// later need not wait for it. Returns whether the app has the attribute.
    @discardableResult
    public static func prepare(pid: pid_t) -> Bool {
        let app = AXUIElementCreateApplication(pid)
        guard hasAttribute(app, "AXManualAccessibility") else { return false }
        AXUIElementSetAttributeValue(app, "AXManualAccessibility" as CFString, kCFBooleanTrue)
        return true
    }

    // MARK: Accessibility

    public static func value(_ e: AXUIElement, _ name: String) -> AnyObject? {
        var v: AnyObject?
        return AXUIElementCopyAttributeValue(e, name as CFString, &v) == .success ? v : nil
    }

    public static func element(_ e: AXUIElement, _ name: String) -> AXUIElement? {
        guard let v = value(e, name), CFGetTypeID(v) == AXUIElementGetTypeID() else { return nil }
        return (v as! AXUIElement)
    }

    static func string(_ e: AXUIElement, _ name: String) -> String? {
        guard let v = value(e, name) else { return nil }
        if let s = v as? String { return s.isEmpty ? nil : s }
        if let u = v as? URL { return u.absoluteString }
        return nil
    }

    static func hasAttribute(_ e: AXUIElement, _ name: String) -> Bool {
        var names: CFArray?
        AXUIElementCopyAttributeNames(e, &names)
        return (names as? [String] ?? []).contains(name)
    }

    /// Service fields of an element: role, title, description, identifier, DOM classes, URL. Never AXValue.
    static func describe(_ e: AXUIElement) -> [String: Any] {
        var d: [String: Any] = [:]
        for k in elementFields { if let s = string(e, k) { d[String(k.dropFirst(2)).lowercasedFirst] = s } }
        if let classes = value(e, "AXDOMClassList") as? [String], !classes.isEmpty {
            d["domClasses"] = Array(classes.prefix(maxDomClasses))
        }
        if let url = string(e, "AXURL") { d["url"] = url }
        return d
    }

    static func compact(_ d: [String: Any?]) -> [String: Any] { d.compactMapValues { $0 } }

    // MARK: Processes

    /// The app's descendant processes: [{pid, name, cwd}], breadth first, at most maxProcesses.
    static func descendants(of root: pid_t) -> [[String: Any]] {
        var pids = [pid_t](repeating: 0, count: 8192)
        let n = Int(proc_listallpids(&pids, Int32(pids.count * MemoryLayout<pid_t>.size)))
        var children: [pid_t: [pid_t]] = [:]
        for p in pids.prefix(max(0, n)) where p > 0 {
            var info = proc_bsdinfo()
            if proc_pidinfo(p, PROC_PIDTBSDINFO, 0, &info, Int32(MemoryLayout<proc_bsdinfo>.size)) > 0 {
                children[pid_t(info.pbi_ppid), default: []].append(p)
            }
        }
        var out: [[String: Any]] = []
        var queue = children[root] ?? []
        while !queue.isEmpty && out.count < maxProcesses {
            let p = queue.removeFirst()
            out.append(compact(["pid": Int(p), "name": name(p), "cwd": cwd(p)]))
            queue += children[p] ?? []
        }
        return out
    }

    static func name(_ p: pid_t) -> String? {
        var buf = [CChar](repeating: 0, count: 256)
        return proc_name(p, &buf, UInt32(buf.count)) > 0 ? String(cString: buf) : nil
    }

    static func cwd(_ p: pid_t) -> String? {
        var info = proc_vnodepathinfo()
        guard proc_pidinfo(p, PROC_PIDVNODEPATHINFO, 0, &info, Int32(MemoryLayout<proc_vnodepathinfo>.size)) > 0
        else { return nil }
        return withUnsafeBytes(of: info.pvi_cdir.vip_path) { raw in
            let s = String(cString: raw.bindMemory(to: CChar.self).baseAddress!)
            return s.isEmpty ? nil : s
        }
    }
}

extension String {
    var lowercasedFirst: String { prefix(1).lowercased() + dropFirst() }
}
