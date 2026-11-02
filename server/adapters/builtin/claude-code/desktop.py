"""Claude Desktop's Code tab, for the claude-code adapter's surface "desktop".

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
surface's skip list leaves it out of the snapshot ("epitaxy-document-page"), with the panel's file tree
("group/file-tree") and the chat ("epitaxy-chat-panel-body"), whose messages the transcript has.
"""
import glob
import json
import os
import re

from adapters import place, screen

CODE_URL = re.compile(r"^https://claude\.ai/epitaxy/(local_[0-9A-Za-z-]+)")
TITLE_SUFFIX = " - Claude Code"
DOCUMENT_PAGE = "epitaxy-document-page"
MARKDOWN = (".md", ".markdown")


def store():
    return place("~/Library/Application Support/Claude/claude-code-sessions", "ECHOFOX_DESKTOP_SESSIONS")


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
    m = CODE_URL.match(screen.web_url(snapshot))
    return m.group(1) if m else None


def session_title(snapshot):
    """The session's name, from the web area's title "<name> - Claude Code", or None."""
    t = screen.web_title(snapshot)
    return (t[:-len(TITLE_SUFFIX)] or None) if t.endswith(TITLE_SUFFIX) else None


def open_file(snapshot):
    """The parts of the path, under the session's folder, of the file that the Files panel shows in this snapshot
    (["docs", "reference", "4-app.md"]), or None."""
    nodes = screen.nodes(snapshot)
    page = next((i for i, n in enumerate(nodes) if DOCUMENT_PAGE in screen.classes(n)), None)
    if page is None:
        return None
    parts = []
    for n in (nodes[j] for j in screen.siblings_before(nodes, page)):
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
