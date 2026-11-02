// The focus snapshot: what the dictation's target looks like when the dictation starts, in two phases
// (docs/adapter-surfaces.md). At the hotkey, capture() reads the identity: the app with its version, its focused
// window's title and the address and title of the web area above the focused element. Then the server matches the
// identity with the surfaces of the enabled adapters and asks for what those surfaces read (EchoFoxCore's
// ReadRequest), and read() reads it of the same window: the outline of the page or window, the rows of the window's
// lists, the app's child processes. Service fields go in, never the text of input fields. For the tools, windows()
// gives the same first phase for every window of an app, without bringing anything to the front.
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
    /// The most elements one walk reads: the outline, or the search for the lists with their rows and cells. It is a
    /// protection, not a limit of the content: the token budget counts only text, and a surface may have no budget.
    /// On 2026-11-02 the largest tree measured was Claude Desktop's whole window of a long Code tab session: 3538
    /// elements in 440 ms, about 0.12 ms an element. 10000 elements is about three times that tree, about 1.2 s at
    /// that rate.
    public static let maxElements = 10_000
    /// The roles whose AXValue is text shown on the screen; an input field's value never goes in.
    static let shownTextRoles: Set<String> = ["AXStaticText", "AXListMarker"]

    /// Why a walk left part of the tree out. The content says only that it did: the outline's "complete" is false, a
    /// list's rows are fewer than its "rowCount". The contract has no field for the reason, so it goes to the log.
    public enum Cut: String, CaseIterable {
        /// The text reached the token budget.
        case budget
        /// The outline reached maxOutlineDepth levels.
        case depth
        /// The walk read maxElements elements.
        case elements
        /// An element was its own descendant, and its repeat was left out. Nothing is missing then: the element and
        /// its subtree are read once. On 2026-11-02, while Claude Desktop had no focused element, the focused window of
        /// Claude Desktop was the application element (role AXApplication), and that element was its own first child. The
        /// outline repeated the app's menus down to 80 levels: 20117 elements in 2.3 s. In Finder the desktop's
        /// group had the application element 63 times among its children, and the walk ran for minutes.
        case cycle

        /// What the walk left out, for the log.
        public var leftOut: String {
            switch self {
            case .budget: return "what is past the token budget"
            case .depth: return "what is deeper than \(FocusSnapshot.maxOutlineDepth) levels"
            case .elements: return "what is past \(FocusSnapshot.maxElements) elements"
            case .cycle: return "the repeats of an element inside itself"
            }
        }
    }

    /// What read() read of one surface.
    public struct Read {
        /// The surface's content, as the content message carries it.
        public let content: [String: Any]
        /// What each walk left out, by part ("outline", "lists"); a part that left nothing out is not here.
        public let cuts: [String: Set<Cut>]

        /// What the walk of `part` left out, in words for the log; nil when it left nothing out.
        public func leftOut(_ part: String) -> String? {
            cuts[part].map { cut in Cut.allCases.filter(cut.contains).map(\.leftOut).joined(separator: ", ") }
        }
    }

    /// The first phase: the identity, and the elements that the text and the second phase need later.
    public struct Capture {
        /// {"app": {bundleId, pid, name, version}, "window": {title}, "webArea": {url, title}}, the parts that exist;
        /// nil when the identity was not asked for (an app of no enabled adapter, a private dictation) or no app is in
        /// front.
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
        let window = element(app, "AXFocusedWindow")
        let webArea = above(focused).webArea
        return Capture(identity: self.identity(of: front, window: window, webArea: webArea), focused: focused, pid: pid,
                       bundleId: front.bundleIdentifier, trusted: trusted, tookMs: took(), window: window,
                       webArea: webArea)
    }

    /// The first phase for every window of `target`, in the app's order of its windows (AXWindows), without bringing
    /// anything to the front: for the tools, which read windows that are not in focus too. Each window's identity is
    /// the one that capture() reads when that window has the focus. Its web area is the one above the app's focused
    /// element when that element is in the window, as at the hotkey; otherwise it is the page in the
    /// window's tree (webArea(in:)). Only that window gets the focused element, so only its lists have a
    /// focusedFrame. With enableElectron, an Electron app is asked for its tree first, as capture() asks it.
    public static func windows(of target: NSRunningApplication, enableElectron: Bool = false) -> [Capture] {
        let started = Date()
        let first = capture(identity: false, enableElectron: enableElectron, of: target)
        let pid = target.processIdentifier
        let focusedAt = above(first.focused, toWindow: true)
        let all = value(AXUIElementCreateApplication(pid), "AXWindows") as? [AXUIElement] ?? []
        return all.map { w in
            let holdsFocus = focusedAt.window.map { CFEqual($0, w) } ?? false
            let webArea = holdsFocus ? focusedAt.webArea
                : self.webArea(in: w, children: children, role: { string($0, "AXRole") })
            return Capture(identity: identity(of: target, window: w, webArea: webArea),
                           focused: holdsFocus ? first.focused : nil, pid: pid, bundleId: target.bundleIdentifier,
                           trusted: first.trusted, tookMs: Int(Date().timeIntervalSince(started) * 1000), window: w,
                           webArea: webArea)
        }
    }

    /// The identity of an app's window and web area: the parts that exist.
    static func identity(of app: NSRunningApplication, window: AXUIElement?, webArea: AXUIElement?) -> [String: Any] {
        var out: [String: Any] = ["app": compact(["bundleId": app.bundleIdentifier ?? "", "pid": Int(app.processIdentifier),
                                                  "name": app.localizedName ?? "", "version": version(of: app)])]
        if let w = window { out["window"] = compact(["title": string(w, "AXTitle")]) }
        if let a = webArea { out["webArea"] = compact(["url": url(a), "title": string(a, "AXTitle")]) }
        return out
    }

    /// The app's version for people (CFBundleShortVersionString), read from its Info.plist on the disk each time. A
    /// Bundle object would keep the first version it read for the life of this process, and the apps update while the
    /// menu bar app runs. After an update that waits for the app's restart, the disk has the new version while the old
    /// one still runs.
    static func version(of app: NSRunningApplication) -> String? {
        guard let url = app.bundleURL?.appendingPathComponent("Contents/Info.plist"),
              let info = NSDictionary(contentsOf: url) else { return nil }
        return info["CFBundleShortVersionString"] as? String
    }

    /// The nearest web area above the focused element, at most maxAncestors up; the walk ends at the window. With
    /// `toWindow`, the walk goes on above the web area to the window, and gives the window too.
    static func above(_ focused: AXUIElement?, toWindow: Bool = false) -> (webArea: AXUIElement?, window: AXUIElement?) {
        var webArea: AXUIElement?
        var e = focused
        for _ in 0..<maxAncestors {
            guard let p = e.flatMap({ element($0, "AXParent") }) else { break }
            e = p
            let role = string(p, "AXRole")
            if role == "AXWindow" { return (webArea, p) }
            if role == "AXWebArea" && webArea == nil {
                webArea = p
                if !toWindow { break }
            }
        }
        return (webArea, nil)
    }

    /// The page in the tree under `root`: the first web area breadth first that is not empty, else the first empty
    /// one. An empty web area has no element two levels under it. In Claude Desktop 4.4212.0 (2026-11-02), the window
    /// had two web areas in two branches of its tree: first the app's own page (a file: address) with one empty group
    /// in it, then the page of claude.ai, which is the one above the focused element at the hotkey. The search does
    /// not look inside a web area, looks at maxElements elements at most, and at each element once, so that a tree
    /// with a cycle ends. Apart from Accessibility, so that the checks can search a made-up tree.
    public static func webArea<Node: Hashable>(in root: Node, children: (Node) -> [Node],
                                               role: (Node) -> String?) -> Node? {
        var queue = [root], seen: Set<Node> = [root], next = 0, empty: Node?
        while next < queue.count {
            for c in children(queue[next]) where !seen.contains(c) {
                if seen.count > maxElements { return empty }
                seen.insert(c)
                if role(c) == "AXWebArea" {
                    if children(c).contains(where: { !children($0).isEmpty }) { return c }
                    empty = empty ?? c
                } else {
                    queue.append(c)
                }
            }
            next += 1
        }
        return empty
    }

    /// The second phase: what `request` asks of one surface, read of the captured window, with the estimate of the
    /// read request's model. {"outline": …} with the outline, {"lists": […], "focusedFrame": …} with the lists,
    /// {"processes": [{pid, name}]} with the processes; a part that has nothing to read of is left out. With it, what
    /// the walks left out, for the log.
    public static func read(_ request: ReadRequest.Surface, of capture: Capture, tokens: TokenEstimate) -> Read {
        var out: [String: Any] = [:], cuts: [String: Set<Cut>] = [:]
        if let o = request.outline, let root = capture.webArea ?? capture.window {
            let walked = outline(root, root: capture.webArea == nil ? "window" : "webArea", skip: Set(o.skip ?? []),
                                 budget: o.budget, tokens: tokens)
            (out["outline"], cuts["outline"]) = (walked.outline, walked.cuts)
        }
        if let l = request.lists, let w = capture.window {
            let walked = windowLists(w, budget: l.budget, tokens: tokens)
            (out["lists"], cuts["lists"]) = (walked.lists, walked.cuts)
            if let f = capture.focused, let r = frame(f) { out["focusedFrame"] = r }
        }
        if request.processes != nil, let pid = capture.pid {
            out["processes"] = descendants(of: pid)
        }
        return Read(content: out, cuts: cuts.filter { !$0.value.isEmpty })
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

    /// The lists in an accessibility window (lists(in:) has the rule).
    static func windowLists(_ window: AXUIElement, budget: Int?,
                            tokens: TokenEstimate) -> (lists: [[String: Any]], cuts: Set<Cut>) {
        lists(in: window, budget: budget, tokens: tokens, children: children, role: { string($0, "AXRole") },
              text: { string($0, "AXTitle") ?? string($0, "AXValue") ?? string($0, "AXDescription") },
              title: { string($0, "AXTitle") }, frame: frame)
    }

    /// The lists in `window`, in the tree's order, at most maxLists within maxListDepth levels: each one's frame, its
    /// row count and its last rows (oldest first), a row's accessible text (`text`) and its cells' titles (`title`).
    /// Each list is read from its end until its text reaches `budget` tokens; the row that reaches it is the last one
    /// (no budget: every row). The search and the rows with their cells read at most maxElements elements together,
    /// and an element inside itself is not searched again. Apart from Accessibility, so that the checks can walk a
    /// made-up tree.
    public static func lists<Node: Hashable>(in window: Node, budget: Int?, tokens: TokenEstimate = .fallback,
                                             children: (Node) -> [Node], role: (Node) -> String?,
                                             text: (Node) -> String?, title: (Node) -> String?,
                                             frame: (Node) -> [String: Any]?) -> (lists: [[String: Any]], cuts: Set<Cut>) {
        var found: [Node] = [], path: Set<Node> = [window], read = 0, cuts: Set<Cut> = []
        func look(_ e: Node, _ depth: Int) {
            for c in children(e) where found.count < maxLists {
                if read >= maxElements {
                    cuts.insert(.elements)
                    return
                }
                if path.contains(c) {
                    cuts.insert(.cycle)
                    continue
                }
                read += 1
                if role(c) == "AXList" {
                    found.append(c)
                } else if depth < maxListDepth {
                    path.insert(c)
                    look(c, depth + 1)
                    path.remove(c)
                }
            }
        }
        look(window, 0)
        let lists = found.map { list in
            let rows = children(list)
            var kept: [[String: Any]] = [], spent = TokenBudget(budget)
            for r in rows.reversed() {
                if spent.isReached {
                    cuts.insert(.budget)
                    break
                }
                if read >= maxElements {
                    cuts.insert(.elements)
                    break
                }
                let cells = children(r)
                let readable = cells.prefix(maxElements - read - 1)
                if readable.count < cells.count { cuts.insert(.elements) }
                read += 1 + readable.count
                let line = text(r) ?? ""
                let columns = readable.compactMap(title)
                spent.add(tokens.count(([line] + columns).joined(separator: " ")))
                kept.append(compact(["text": line.isEmpty ? nil : line, "columns": columns.isEmpty ? nil : columns]))
            }
            return compact(["frame": frame(list), "rowCount": rows.count, "rows": Array(kept.reversed())])
        }
        return (lists, cuts)
    }

    /// The outline of an accessibility element (outline(of:) has the rule).
    static func outline(_ root: AXUIElement, root name: String, skip: Set<String>, budget: Int?,
                        tokens: TokenEstimate) -> (outline: [String: Any], cuts: Set<Cut>) {
        outline(of: root, root: name, skip: skip, budget: budget, tokens: tokens, describe: describe,
                children: children, shownText: { string($0, "AXValue") })
    }

    /// The tree under `root`, flat in the tree's order: each element's depth under the root, its service fields
    /// (`describe`, with all its DOM classes), and the shown text of a static text or a list marker (`shownText`, asked
    /// only of those). It is walked from the end, last child first, until its text reaches `budget` tokens (no budget:
    /// the whole tree) or maxElements elements are read: the element that reaches either is the last one read, so the
    /// outline keeps the end of the tree, and the ancestors of that element go in too, without their text, so that the
    /// element's place is known. A child that is one of its own ancestors is left out, so that a tree with a cycle
    /// ends. "complete" says whether the outline has all of the tree's elements; the cuts say what was left out. An
    /// element whose role or one of whose DOM classes is in `skip` goes in alone, marked "skipped": its children are
    /// not read. An element keeps at most maxDomClasses of its classes. Apart from Accessibility, so that the checks
    /// can walk a made-up tree.
    public static func outline<Node: Hashable>(of root: Node, root name: String, skip: Set<String> = [],
                                               budget: Int? = nil, tokens: TokenEstimate = .fallback,
                                               describe: (Node) -> [String: Any], children: (Node) -> [Node],
                                               shownText: (Node) -> String?) -> (outline: [String: Any], cuts: Set<Cut>) {
        var nodes: [[String: Any]] = [], spent = TokenBudget(budget), stopped = false, cuts: Set<Cut> = []
        var path: Set<Node> = [], read = 0
        func visit(_ e: Node, _ depth: Int) {
            read += 1
            var d = describe(e)
            let classes = d["domClasses"] as? [String] ?? []
            if classes.count > maxDomClasses { d["domClasses"] = Array(classes.prefix(maxDomClasses)) }
            if !skip.isEmpty && !skip.isDisjoint(with: [d["role"] as? String ?? ""] + classes) {
                d["skipped"] = true  // its children are never read: their text stays out of the snapshot
            } else if depth < maxOutlineDepth {
                path.insert(e)
                for c in children(e).reversed() {
                    if read >= maxElements {
                        stopped = true
                        cuts.insert(.elements)
                        break
                    }
                    if path.contains(c) {
                        cuts.insert(.cycle)
                        continue
                    }
                    visit(c, depth + 1)
                    if stopped { break }
                }
                path.remove(e)
            } else if !children(e).isEmpty {
                cuts.insert(.depth)
            }
            d["depth"] = depth
            if !stopped, let role = d["role"] as? String, shownTextRoles.contains(role), let text = shownText(e) {
                d["text"] = text
                spent.add(tokens.count(text))
            }
            nodes.append(d)  // after a stop inside its subtree: an ancestor of the last element read
            if !stopped, spent.isReached {
                stopped = true
                cuts.insert(.budget)
            }
        }
        visit(root, 0)
        let complete = cuts.isSubset(of: [.cycle])  // a cycle's repeat holds no element that is not read
        return (["root": name, "complete": complete, "nodes": Array(nodes.reversed())], cuts)
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
