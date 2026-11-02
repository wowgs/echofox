"""Claude Desktop (bundle id com.anthropic.claudefordesktop), its Code tab, for the claude-code adapter.

The Code tab is a web page in the app. Its web area, above the input box, has the URL
https://claude.ai/epitaxy/local_<id>; <id> is the Desktop session. Desktop keeps a record of each session in
~/Library/Application Support/Claude/claude-code-sessions/<…>/<…>/local_<id>.json, whose "cliSessionId" names the
Claude Code transcript (~/.claude/projects/<project>/<cliSessionId>.jsonl) and whose "title" is the session's name
(measured 2026-10-15, Claude Desktop 2.37337.1; the format is Desktop's own and not documented).

The Code tab's Files panel shows one file, its preview or its source, in a group with the DOM class
"epitaxy-document-page". Just before that group, at its level, are a button ("View source") and, before it, one pop-up
button for each part of the file's path under the session's folder: "docs", "reference", "4-app.md" (measured
2026-11-02, Claude Desktop, a session in /Users/alex/echofox: a file at the folder's root had one, "README.md"). With
several files open as tabs, the panel shows the active one. The session's folder is the record's "cwd". The adapter
reads the file from the disk, not from the screen: the preview on the screen is the file without its Markdown, and the
manifest's outlineSkip leaves it out of the snapshot ("epitaxy-document-page"), with the panel's file tree
("group/file-tree") and the chat ("epitaxy-chat-panel-body"), whose messages the transcript has.
"""
import glob
import json
import os
import re

from adapters import bundle

BUNDLE = "com.anthropic.claudefordesktop"
CODE_URL = re.compile(r"^https://claude\.ai/epitaxy/(local_[0-9A-Za-z-]+)")
TITLE_SUFFIX = " - Claude Code"
DOCUMENT_PAGE = "epitaxy-document-page"
MARKDOWN = (".md", ".markdown")


def store():
    """Desktop's session records, or $ECHOFOX_DESKTOP_SESSIONS (read at each call, so that tests can set it)."""
    return os.environ.get("ECHOFOX_DESKTOP_SESSIONS") or os.path.expanduser(
        "~/Library/Application Support/Claude/claude-code-sessions")


def web_area(snapshot):
    return (snapshot or {}).get("webArea") or {}


def record(desktop_id, root=None):
    """The session record of local_<id>, or None."""
    if not re.fullmatch(r"local_[0-9A-Za-z-]+", desktop_id or ""):
        return None
    for f in glob.glob(os.path.join(glob.escape(root or store()), "*", "*", f"{desktop_id}.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            continue
    return None


def code_tab(snapshot):
    """The Desktop session (local_<id>) whose Code tab has the focus in this snapshot, or None."""
    if bundle(snapshot) != BUNDLE:
        return None
    m = CODE_URL.match(str(web_area(snapshot).get("url") or ""))
    return m.group(1) if m else None


def open_file(snapshot):
    """The parts of the path, under the session's folder, of the file that the Files panel shows in this snapshot
    (["docs", "reference", "4-app.md"]), or None."""
    nodes = ((snapshot or {}).get("outline") or {}).get("nodes") or []
    page = next((i for i, n in enumerate(nodes) if DOCUMENT_PAGE in (n.get("domClasses") or [])), None)
    if page is None:
        return None
    depth, parts = nodes[page].get("depth"), []
    for n in reversed(nodes[:page]):
        if n.get("depth") != depth:
            if (n.get("depth") or 0) < depth:
                break
            continue  # inside an element before the page
        if n.get("role") == "AXPopUpButton" and isinstance(n.get("title"), str):
            parts.append(n["title"])
        elif n.get("role") != "AXButton" or parts:
            break
    parts.reverse()
    if not parts or any(not p or p in (".", "..") or "/" in p or "\0" in p for p in parts):
        return None
    return parts


def open_markdown(snapshot, folder):
    """The Markdown file that the Files panel shows, read from the session's folder: {"name": its path under the folder,
    "text"}, or None (no file shown, not Markdown, not under the folder, or not readable)."""
    parts = open_file(snapshot)
    if not parts or not folder or not parts[-1].lower().endswith(MARKDOWN):
        return None
    root = os.path.realpath(folder)
    path = os.path.realpath(os.path.join(root, *parts))
    if os.path.commonpath([root, path]) != root:
        return None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return {"name": "/".join(parts), "text": f.read()}
    except OSError:
        return None
