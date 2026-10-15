"""The adapter for Claude Desktop (bundle id com.anthropic.claudefordesktop), its Code tab.

The Code tab is a web page in the app. Its web area, above the input box, has the URL
https://claude.ai/epitaxy/local_<id>; <id> is the Desktop session. Desktop keeps a record of each session in
~/Library/Application Support/Claude/claude-code-sessions/<…>/<…>/local_<id>.json, whose "cliSessionId" names the
Claude Code transcript (~/.claude/projects/<project>/<cliSessionId>.jsonl) and whose "title" is the session's name
(measured 2026-10-15, Claude Desktop 2.37337.1; the format is Desktop's own and not documented). Ways to the session,
the surest first:
  1. the web area's URL → the session record → its transcript ("desktop store");
  2. the web area's title ("<title> - Claude Code") → the transcript with that title ("title");
  3. the newest session Desktop wrote ("newest session of the app"), a guess.
The Chat tab (claude.ai conversations) has no local transcript; it is not read yet.
"""
import glob
import json
import os
import re

from . import Claim, bundle, claude_code

BUNDLE = "com.anthropic.claudefordesktop"
STORE = os.environ.get("LOCAL_VOICE_DESKTOP_SESSIONS") or os.path.expanduser(
    "~/Library/Application Support/Claude/claude-code-sessions")
CODE_URL = re.compile(r"^https://claude\.ai/epitaxy/(local_[0-9A-Za-z-]+)")
TITLE_SUFFIX = " - Claude Code"


def store():
    return STORE


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


class ClaudeDesktop:
    name = "claude-desktop"

    def claim(self, snapshot, sessions):
        if bundle(snapshot) != BUNDLE:
            return None
        m = CODE_URL.match(str(web_area(snapshot).get("url") or ""))
        if m:
            return Claim(self.name, 1.0, f"the Code tab of Desktop session {m.group(1)}")
        return Claim(self.name, 0.5, "Claude Desktop, no Code tab in focus")

    def context(self, snapshot, sessions):
        area = web_area(snapshot)
        m = CODE_URL.match(str(area.get("url") or ""))
        rec = record(m.group(1)) if m else None
        cli = (rec or {}).get("cliSessionId")
        where = claude_code.session_file([cli]) if cli else None
        if where:
            return {**claude_code.context_of(where, "desktop store"), "desktopSession": m.group(1)}
        title = str(area.get("title") or "")
        if title.endswith(TITLE_SUFFIX):
            where = claude_code.titled_session(title[:-len(TITLE_SUFFIX)])
            if where:
                return claude_code.context_of(where, "title")
        return claude_code.context_of(claude_code.entrypoint_session("claude-desktop"), "newest session of the app")
