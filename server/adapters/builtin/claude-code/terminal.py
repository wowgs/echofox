"""Claude Code in a terminal's tab, for the claude-code adapter (docs/reference/3-context.md, "Claude Code in a
terminal"). Each running claude writes ~/.claude/sessions/<pid>.json with its "sessionId", "name" (the session's
title) and "entrypoint" ("cli" in a terminal); the files are Claude Code's own and not documented (Claude Code 2.1.300,
2026-10-27). Claude Code sets the terminal's title to "✳ <name>", and the terminals show it in the window's title
(Terminal adds the folder, the command and the size; iTerm2 drops the "✳").

The session in focus is the one claude among the terminal app's processes (the snapshot's "processes") whose name the
focused window's title contains; none, or more than one: no session. A claude in tmux or screen is a process of the
multiplexer's server, not of the terminal app, so it is never found: for now such a tab gets no context (measured:
the visible text chose the wrong pane in tmux, docs/observations.md).
"""
import glob
import json
import os

TERMINALS = {"com.mitchellh.ghostty", "com.apple.Terminal", "com.googlecode.iterm2", "dev.warp.Warp-Stable"}


def store():
    """~/.claude/sessions, or $ECHOFOX_CLAUDE_SESSIONS (read at each call, so that tests can set it)."""
    return os.environ.get("ECHOFOX_CLAUDE_SESSIONS") or os.path.expanduser("~/.claude/sessions")


def running(pids):
    """The terminal sessions of these processes: [{"pid", "session", "name"}], from their files in the store."""
    out = []
    for f in glob.glob(os.path.join(glob.escape(store()), "*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                s = json.load(fh)
        except (OSError, ValueError):
            continue
        if (isinstance(s, dict) and s.get("pid") in pids and s.get("entrypoint") == "cli"
                and isinstance(s.get("sessionId"), str) and isinstance(s.get("name"), str) and s["name"]):
            out.append({"pid": s["pid"], "session": s["sessionId"], "name": s["name"]})
    return out


def session(snapshot):
    """The Claude Code session in the focused tab of a terminal in this snapshot: {"session", "name", "pid"}, or
    None."""
    snapshot = snapshot or {}
    if (snapshot.get("app") or {}).get("bundleId") not in TERMINALS:
        return None
    title = str((snapshot.get("window") or {}).get("title") or "")
    pids = {p.get("pid") for p in snapshot.get("processes") or [] if isinstance(p, dict)}
    if not title or not pids:
        return None
    matches = [s for s in running(pids) if s["name"] in title]
    return matches[0] if len(matches) == 1 else None
