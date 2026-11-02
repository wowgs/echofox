"""What an adapter reads of its snapshot: the identity of the focused app, window and web page, and the content that
its surface declares (SNAPSHOT in adapters/__init__.py). These helpers know no app: an adapter takes them instead of
reading the snapshot's dicts itself. Every helper takes a missing or broken part as empty."""


def _part(snapshot, key):
    v = (snapshot or {}).get(key)
    return v if isinstance(v, dict) else {}


def bundle(snapshot):
    """The bundle id of the focused app, or None."""
    return _part(snapshot, "app").get("bundleId")


def window_title(snapshot):
    """The focused window's title ("" without one)."""
    return str(_part(snapshot, "window").get("title") or "")


def web_area(snapshot):
    """The nearest web area above the focused element: {"url", "title"}, or {} without one."""
    return _part(snapshot, "webArea")


def web_url(snapshot):
    return str(web_area(snapshot).get("url") or "")


def web_title(snapshot):
    return str(web_area(snapshot).get("title") or "")


# The outline: the tree under the web area or the window, flat with depths, in the tree's order.

def outline(snapshot):
    """The outline's {"root", "complete", "nodes"}, or {} without one."""
    return _part(snapshot, "outline")


def nodes(snapshot):
    """The outline's nodes, those that are objects."""
    return [n for n in outline(snapshot).get("nodes") or [] if isinstance(n, dict)]


def depth(node):
    d = node.get("depth")
    return d if isinstance(d, int) else 0


def classes(node):
    return node.get("domClasses") or []


def skipped(node):
    """An element of the surface's skip list: the app sends it without its children, and its text is never read."""
    return node.get("skipped") is True


def end(nodes, i):
    """The index after the subtree of nodes[i]."""
    d, j = depth(nodes[i]), i + 1
    while j < len(nodes) and depth(nodes[j]) > d:
        j += 1
    return j


def children(nodes, i):
    """The indices of the children of nodes[i], in their order."""
    out, j, e = [], i + 1, end(nodes, i)
    while j < e:
        out.append(j)
        j = end(nodes, j)
    return out


def siblings_before(nodes, i):
    """The indices of the elements before nodes[i] under the same parent, the nearest first."""
    d, out = depth(nodes[i]), []
    for j in range(i - 1, -1, -1):
        if depth(nodes[j]) < d:
            break
        if depth(nodes[j]) == d:
            out.append(j)
    return out


def shown(nodes, start=0, stop=None):
    """The nodes of nodes[start:stop] that are not skipped and not under a skipped one."""
    under = None  # the depth of the skipped element whose subtree is left out
    for n in nodes[start:stop]:
        if under is not None and depth(n) > under:
            continue
        under = depth(n) if skipped(n) else None
        if under is None:
            yield n


# The lists of the focused window, and the app's processes.

def lists(snapshot):
    """The lists of the focused window that have rows: [{"frame", "rowCount", "rows": [{"text", "columns"}]}]."""
    return [l for l in (snapshot or {}).get("lists") or [] if isinstance(l, dict) and l.get("rows")]


def focused_frame(snapshot):
    """The focused element on the screen: {"x", "y", "width", "height"}, or {}."""
    return _part(snapshot, "focusedFrame")


def processes(snapshot):
    """The app's child processes: [{"pid", "name"}]."""
    return [p for p in (snapshot or {}).get("processes") or [] if isinstance(p, dict)]


def pids(snapshot):
    return {p.get("pid") for p in processes(snapshot) if isinstance(p.get("pid"), int)}
