"""Claude Desktop (bundle id com.anthropic.claudefordesktop), its Code tab, for the Claude plugin.

The Code tab is a web page in the app. Its web area, above the input box, has the URL
https://claude.ai/epitaxy/local_<id>; <id> is the Desktop session. Desktop keeps a record of each session in
~/Library/Application Support/Claude/claude-code-sessions/<…>/<…>/local_<id>.json, whose "cliSessionId" names the
Claude Code transcript (~/.claude/projects/<project>/<cliSessionId>.jsonl) and whose "title" is the session's name
(measured 2026-10-15, Claude Desktop 2.37337.1; the format is Desktop's own and not documented).
"""
import glob
import json
import os
import re

from adapters import bundle

BUNDLE = "com.anthropic.claudefordesktop"
CODE_URL = re.compile(r"^https://claude\.ai/epitaxy/(local_[0-9A-Za-z-]+)")
TITLE_SUFFIX = " - Claude Code"


def store():
    """Desktop's session records, or $LOCAL_VOICE_DESKTOP_SESSIONS (read at each call, so that tests can set it)."""
    return os.environ.get("LOCAL_VOICE_DESKTOP_SESSIONS") or os.path.expanduser(
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
