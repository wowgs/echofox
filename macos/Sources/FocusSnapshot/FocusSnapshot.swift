// The focus snapshot: what the dictation's target looks like when the dictation starts, in two phases
// (docs/adapter-surfaces.md). At the hotkey, capture() reads the identity: the app, its focused window's title and the
// address and title of the web area above the focused element. Then the server matches the identity with the surfaces
// of the enabled adapters and asks for what those surfaces read (EchoFoxCore's ReadRequest), and read() reads it of the
// same window: the outline of the page or window, the rows of the window's lists, the app's child processes. Service
// fields go in, never the text of input fields.
//
// Accessibility needs the "Accessibility" permission of the process that runs this. Electron apps build their
// accessibility tree only on request (ElectronTree). After AXManualAccessibility was set, the focused element appeared
// 2.1 s later (2087–2104 ms, three runs, Claude Desktop 2.37337.1). With enableElectron, capture() asks for the tree
// when the focused element is missing and waits up to electronWaitSeconds; the app asks ahead (ElectronTree.enable), so
// that a later capture() need not wait.
import AppKit
import ApplicationServices
import Darwin
import EchoFoxCore

public enum FocusSnapshot {
    static let elementFields = ["AXRole", "AXSubrole", "AXTitle", "AXDescription", "AXIdentifier"]
    static let maxAncestors = 80
    /// The DOM classes an outline's element keeps in the content; the skip list is checked against all of them.
    static let maxDomClasses = 12
    static let maxProcesses = 40
    /// How long capture() waits for an Electron app's tree after asking for it (it took 2.1 s in Claude Desktop).
    public static let electronWaitSeconds = 3.0
    static let electronPollSeconds = 0.05
    /// The lists of the focused window: how deep under the window to look for them, and how many. How much of each
    /// is the token budget's: a chat's newest messages are at the end of its list, so a list is read from its end.
    static let maxListDepth = 4
    static let maxLists = 6
    /// The outline: how deep under its root. How much of it is the token budget's: a chat's newest messages are at the
    /// end of the tree, so the tree is read from its end. A chat of 4 messages in Claude Desktop had 547 elements, 32
    /// levels deep (2026-10-25).
    static let maxOutlineDepth = 80
    /// The roles whose AXValue is text shown on the screen; an input field's value never goes in.
    static let shownTextRoles: Set<String> = ["AXStaticText", "AXListMarker"]

    /// The first phase: the identity, and the elements that the text and the second phase need later.
    public struct Capture {
        /// {"app": {bundleId, pid, name}, "window": {title}, "webArea": {url, title}}, the parts that exist; nil when
        /// the identity was not asked for (an app of no enabled adapter, a private dictation) or no app is in front.
        public let identity: [String: Any]?
        /// The element with the keyboard focus, where the text goes later, and its app, for the log too.
        public let focused: AXUIElement?
        public let pid: pid_t?
        public let bundleId: String?
        /// Whether this process has the Accessibility permission: without it, the identity has the app only.
        public let trusted: Bool
        public let tookMs: Int
        let window: AXUIElement?
        let webArea: AXUIElement?
    }

    /// The first phase, at the hotkey: the frontmost app (or `target`, any running app: for tools), its focused
    /// element, and with `identity` its identity. The focused element's ancestors are walked up to the nearest web
    /// area, to find it; they are not sent.
    public static func capture(identity: Bool = true, enableElectron: Bool = false,
                               of target: NSRunningApplication? = nil) -> Capture {
        let started = Date()
        let trusted = AXIsProcessTrusted()
        func took() -> Int { Int(Date().timeIntervalSince(started) * 1000) }
        guard let front = target ?? NSWorkspace.shared.frontmostApplication else {
            return Capture(identity: nil, focused: nil, pid: nil, bundleId: nil, trusted: trusted, tookMs: took(),
                           window: nil, webArea: nil)
        }
        let pid = front.processIdentifier
        let app = AXUIElementCreateApplication(pid)
        var focused = element(app, "AXFocusedUIElement")
        if focused == nil, enableElectron, ElectronTree.enable(pid: pid) {
            for _ in 0..<Int(electronWaitSeconds / electronPollSeconds) where focused == nil {
                Thread.sleep(forTimeInterval: electronPollSeconds)
                focused = element(app, "AXFocusedUIElement")
            }
        }
        guard identity else {
            return Capture(identity: nil, focused: focused, pid: pid, bundleId: front.bundleIdentifier, trusted: trusted,
                           tookMs: took(), window: nil, webArea: nil)
        }
        var out: [String: Any] = ["app": ["bundleId": front.bundleIdentifier ?? "", "pid": Int(pid),
                                          "name": front.localizedName ?? ""]]
        let window = element(app, "AXFocusedWindow")
        if let w = window { out["window"] = compact(["title": string(w, "AXTitle")]) }
        var webArea: AXUIElement?
        var e = focused
        for _ in 0..<maxAncestors {
            guard let p = e.flatMap({ element($0, "AXParent") }) else { break }
            e = p
            let role = string(p, "AXRole")
            if role == "AXWebArea" {
                out["webArea"] = compact(["url": url(p), "title": string(p, "AXTitle")])
                webArea = p
                break
            }
            if role == "AXWindow" { break }
        }
        return Capture(identity: out, focused: focused, pid: pid, bundleId: front.bundleIdentifier, trusted: trusted,
                       tookMs: took(), window: window, webArea: webArea)
    }

    /// The second phase: what `request` asks of one surface, read of the captured window, with the estimate of the
    /// read request's model. {"outline": …} with the outline, {"lists": […], "focusedFrame": …} with the lists,
    /// {"processes": [{pid, name}]} with the processes; a part that has nothing to read of is left out.
    public static func read(_ request: ReadRequest.Surface, of capture: Capture, tokens: TokenEstimate) -> [String: Any] {
        var out: [String: Any] = [:]
        if let o = request.outline, let root = capture.webArea ?? capture.window {
            out["outline"] = outline(root, root: capture.webArea == nil ? "window" : "webArea", skip: Set(o.skip ?? []),
                                     budget: o.budget, tokens: tokens)
        }
        if let l = request.lists, let w = capture.window {
            out["lists"] = windowLists(w, budget: l.budget, tokens: tokens)
            if let f = capture.focused, let r = frame(f) { out["focusedFrame"] = r }
        }
        if request.processes != nil, let pid = capture.pid {
            out["processes"] = descendants(of: pid)
        }
        return out
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

    /// An element's address, without an image's data, which is no address.
    static func url(_ e: AXUIElement) -> String? {
        string(e, "AXURL").flatMap { $0.hasPrefix("data:") ? nil : $0 }
    }

    /// Service fields of an element: role, title, description, identifier, all its DOM classes, URL. Never AXValue.
    static func describe(_ e: AXUIElement) -> [String: Any] {
        var d: [String: Any] = [:]
        for k in elementFields { if let s = string(e, k) { d[String(k.dropFirst(2)).lowercasedFirst] = s } }
        if let classes = value(e, "AXDOMClassList") as? [String], !classes.isEmpty { d["domClasses"] = classes }
        if let url = url(e) { d["url"] = url }
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
    /// a row's accessible text and its cells' titles. Each list is read from its end until its text reaches `budget`
    /// tokens; the row that reaches it is the last one (no budget: every row).
    static func windowLists(_ window: AXUIElement, budget: Int?, tokens: TokenEstimate) -> [[String: Any]] {
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
            var kept: [[String: Any]] = [], spent = TokenBudget(budget)
            for r in rows.reversed() {
                if spent.isReached { break }
                let text = string(r, "AXTitle") ?? string(r, "AXValue") ?? string(r, "AXDescription") ?? ""
                let columns = children(r).compactMap { string($0, "AXTitle") }
                spent.add(tokens.count(([text] + columns).joined(separator: " ")))
                kept.append(compact(["text": text.isEmpty ? nil : text, "columns": columns.isEmpty ? nil : columns]))
            }
            return compact(["frame": frame(list), "rowCount": rows.count, "rows": Array(kept.reversed())])
        }
    }

    /// The outline of an accessibility element (outline(of:) has the rule).
    static func outline(_ root: AXUIElement, root name: String, skip: Set<String>, budget: Int?,
                        tokens: TokenEstimate) -> [String: Any] {
        outline(of: root, root: name, skip: skip, budget: budget, tokens: tokens, describe: describe,
                children: children, shownText: { string($0, "AXValue") })
    }

    /// The tree under `root`, flat in the tree's order: each element's depth under the root, its service fields
    /// (`describe`, with all its DOM classes), and the shown text of a static text or a list marker (`shownText`, asked
    /// only of those). It is walked from the end, last child first, until its text reaches `budget` tokens (no budget:
    /// the whole tree): the element whose text reaches it is the last one read, so the outline keeps the end of the
    /// tree, and the ancestors of that element go in too, without their text, so that the element's place is known.
    /// "complete" says whether the outline has all of the tree. An element whose role or one of whose DOM classes is in
    /// `skip` goes in alone, marked "skipped": its children are not read. An element keeps at most maxDomClasses of its
    /// classes. Apart from Accessibility, so that the checks can walk a made-up tree.
    public static func outline<Node>(of root: Node, root name: String, skip: Set<String> = [], budget: Int? = nil,
                                     tokens: TokenEstimate = .fallback, describe: (Node) -> [String: Any],
                                     children: (Node) -> [Node], shownText: (Node) -> String?) -> [String: Any] {
        var nodes: [[String: Any]] = [], spent = TokenBudget(budget), stopped = false, complete = true
        func visit(_ e: Node, _ depth: Int) {
            var d = describe(e)
            let classes = d["domClasses"] as? [String] ?? []
            if classes.count > maxDomClasses { d["domClasses"] = Array(classes.prefix(maxDomClasses)) }
            if !skip.isEmpty && !skip.isDisjoint(with: [d["role"] as? String ?? ""] + classes) {
                d["skipped"] = true  // its children are never read: their text stays out of the snapshot
            } else if depth < maxOutlineDepth {
                for c in children(e).reversed() {
                    visit(c, depth + 1)
                    if stopped { break }
                }
            } else if !children(e).isEmpty {
                complete = false
            }
            d["depth"] = depth
            if !stopped, let role = d["role"] as? String, shownTextRoles.contains(role), let text = shownText(e) {
                d["text"] = text
                spent.add(tokens.count(text))
            }
            nodes.append(d)  // after a stop inside its subtree: an ancestor of the last element read
            if !stopped, spent.isReached {
                stopped = true
                complete = false
            }
        }
        visit(root, 0)
        return ["root": name, "complete": complete, "nodes": Array(nodes.reversed())]
    }

    // MARK: Processes

    /// The app's descendant processes: [{pid, name}], breadth first, at most maxProcesses. The parents come from the
    /// kernel's process table (sysctl KERN_PROC_ALL, as ps reads them), not from proc_pidinfo, which refuses a process
    /// of another user: a terminal's tab runs login, owned by root, between the terminal and its shell (Terminal and
    /// Ghostty, 2026-10-27).
    static func descendants(of root: pid_t) -> [[String: Any]] {
        var children: [pid_t: [pid_t]] = [:]
        for (p, parent) in parents() { children[parent, default: []].append(p) }
        var out: [[String: Any]] = []
        var queue = children[root] ?? []
        while !queue.isEmpty && out.count < maxProcesses {
            let p = queue.removeFirst()
            out.append(compact(["pid": Int(p), "name": name(p)]))
            queue += children[p] ?? []
        }
        return out
    }

    /// Every process with its parent, from the kernel's process table.
    static func parents() -> [(pid: pid_t, parent: pid_t)] {
        var mib: [Int32] = [CTL_KERN, KERN_PROC, KERN_PROC_ALL, 0]
        var size = 0
        guard sysctl(&mib, 4, nil, &size, nil, 0) == 0, size > 0 else { return [] }
        size += size / 8  // processes that start between the two calls
        var procs = [kinfo_proc](repeating: kinfo_proc(), count: size / MemoryLayout<kinfo_proc>.stride)
        guard sysctl(&mib, 4, &procs, &size, nil, 0) == 0 else { return [] }
        return procs.prefix(size / MemoryLayout<kinfo_proc>.stride)
            .map { ($0.kp_proc.p_pid, $0.kp_eproc.e_ppid) }
            .filter { $0.pid > 0 }
    }

    static func name(_ p: pid_t) -> String? {
        var buf = [CChar](repeating: 0, count: 256)
        return proc_name(p, &buf, UInt32(buf.count)) > 0 ? String(cString: buf) : nil
    }
}

extension String {
    var lowercasedFirst: String { prefix(1).lowercased() + dropFirst() }
}
