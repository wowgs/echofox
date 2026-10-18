// The focus snapshot: what the dictation's target looks like when the dictation starts. The core takes it once, at the
// hotkey, and sends it to the dictation server, whose adapters decide whose conversation it is
// (server/adapters/__init__.py has the fields). Service fields go in, never the text of input fields. Screen content
// goes in only when the caller asks: `lists` takes the rows of the lists in the focused window (a messenger's
// messages), and the app asks only for the apps of an enabled adapter whose manifest wants them.
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
    /// How long take() waits for an Electron app's tree after asking for it (it took 2.1 s in Claude Desktop).
    public static let electronWaitSeconds = 3.0
    static let electronPollSeconds = 0.05
    static let maxPids = 8192  // proc_listallpids' buffer: more processes than a Mac runs
    /// The lists of the focused window: how deep under the window to look for them, how many, and how much of each.
    /// A chat's newest messages are at the end of its list, so a long list keeps its last rows.
    static let maxListDepth = 4
    static let maxLists = 6
    static let maxListRows = 150
    static let maxListChars = 30_000

    /// A snapshot and the element it was taken of: the element with the keyboard focus, where the text goes later.
    public struct Capture {
        public let snapshot: [String: Any]
        public let focused: AXUIElement?
        public let pid: pid_t?
    }

    /// The snapshot of the frontmost app (or of `app`), as a JSON-ready dictionary.
    public static func take(enableElectron: Bool = true, lists: Bool = false,
                            of app: NSRunningApplication? = nil) -> [String: Any] {
        capture(full: true, enableElectron: enableElectron, lists: lists, of: app).snapshot
    }

    /// The snapshot of the frontmost app (or of `target`, any running app: for tools), with its focused element and
    /// pid. `full`: the window, the focused element's
    /// ancestors and the app's processes too, for adapters; without it, only the app and the focused element, which
    /// the text goes into later.
    public static func capture(full: Bool = true, enableElectron: Bool = true, lists: Bool = false,
                               of target: NSRunningApplication? = nil) -> Capture {
        let started = Date()
        guard let front = target ?? NSWorkspace.shared.frontmostApplication else {
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
            for _ in 0..<Int(electronWaitSeconds / electronPollSeconds) where focused == nil {
                Thread.sleep(forTimeInterval: electronPollSeconds)
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
            if lists {
                out["lists"] = windowLists(w)
                if let f = focused, let r = frame(f) { out["focusedFrame"] = r }
            }
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

    static func children(_ e: AXUIElement) -> [AXUIElement] { value(e, "AXChildren") as? [AXUIElement] ?? [] }

    /// An element's place on the screen: {"x", "y", "width", "height"} in points.
    static func frame(_ e: AXUIElement) -> [String: Any]? {
        guard let p = value(e, "AXPosition"), let s = value(e, "AXSize"),
              CFGetTypeID(p) == AXValueGetTypeID(), CFGetTypeID(s) == AXValueGetTypeID() else { return nil }
        var point = CGPoint.zero, size = CGSize.zero
        guard AXValueGetValue(p as! AXValue, .cgPoint, &point), AXValueGetValue(s as! AXValue, .cgSize, &size) else {
            return nil
        }
        return ["x": Double(point.x), "y": Double(point.y), "width": Double(size.width), "height": Double(size.height)]
    }

    /// The lists in `window`, in the tree's order: each one's frame, its row count and its last rows (oldest first),
    /// a row's accessible text and its cells' titles.
    static func windowLists(_ window: AXUIElement) -> [[String: Any]] {
        var found: [AXUIElement] = []
        func look(_ e: AXUIElement, _ depth: Int) {
            for c in children(e) where found.count < maxLists {
                if string(c, "AXRole") == "AXList" {
                    found.append(c)
                } else if depth < maxListDepth {
                    look(c, depth + 1)
                }
            }
        }
        look(window, 0)
        return found.map { list in
            let rows = children(list)
            var kept: [[String: Any]] = [], chars = 0
            for r in rows.suffix(maxListRows).reversed() {
                let text = string(r, "AXTitle") ?? string(r, "AXValue") ?? string(r, "AXDescription") ?? ""
                chars += text.count
                if chars > maxListChars { break }
                let columns = children(r).compactMap { string($0, "AXTitle") }
                kept.append(compact(["text": text.isEmpty ? nil : text, "columns": columns.isEmpty ? nil : columns]))
            }
            return compact(["frame": frame(list), "rowCount": rows.count, "rows": Array(kept.reversed())])
        }
    }

    // MARK: Processes

    /// The app's descendant processes: [{pid, name, cwd}], breadth first, at most maxProcesses.
    static func descendants(of root: pid_t) -> [[String: Any]] {
        var pids = [pid_t](repeating: 0, count: maxPids)
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
