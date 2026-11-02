"""The claude-code adapter: the Claude Code session a dictation goes into, read from its transcript on the Mac.

- Surface "desktop", Claude Desktop's Code tab, the session in focus. Ways to the session: the web area's URL →
  Desktop's record of the session → its Claude Code transcript ("desktop store"); without a record, the web area's
  title → the one transcript with that title ("title"); several transcripts with that title: no messages. The Markdown
  file that the tab's Files panel shows goes in as a document, read from the session's folder (the record's "cwd";
  desktop.py).
- Surface "terminal", a terminal's tab (Ghostty, Terminal, iTerm2, Warp) with Claude Code in it: the claude among the
  terminal's processes whose session's name the window's title shows ("terminal title", terminal.py); not in tmux or
  screen.
It never guesses a session from the app alone: the newest session of an app is often another one that runs in the
background. The context has only Claude's replies: with the speaker's own messages, the model copied the previous
dictation instead of transcribing the new one (2026-10-14). Claude writes its replies in Markdown, and Claude Code adds
its tags to them; clean makes them plain prose.
"""
from adapters import Adapter, markdown

from . import desktop, terminal, transcripts


ABOUT = "a session with Claude, an AI assistant for software work"


def as_context(found, **details):
    """A transcript that transcripts.context_of found → this adapter's context, or None."""
    if not found:
        return None
    return {"about": ABOUT, "messages": [{"from": "Claude", "text": m["text"]} for m in found["messages"]],
            "source": f"{found['how']}: {found['file']}",
            "details": {"session": found["session"], "file": found["file"], "how": found["how"],
                        "title": found.get("title"), **details}}


class ClaudeCode(Adapter):
    def context(self, surface, snapshot):
        return (terminal_context if surface == "terminal" else desktop_context)(snapshot)

    def clean(self, text):
        return markdown.plain(transcripts.strip_tags(text))


def terminal_context(snapshot):
    t = terminal.session(snapshot)
    if not t:
        return None
    found = transcripts.context_of(transcripts.session_file(t["session"]), "terminal title")
    return as_context(found, pid=t["pid"]) or {"about": ABOUT, "details": {"session": t["session"], "pid": t["pid"]}}


def desktop_context(snapshot):
    local = desktop.code_tab(snapshot)
    if not local:
        return None
    rec = desktop.record(local) or {}
    cli = rec.get("cliSessionId")
    where = transcripts.session_file(cli) if cli else None
    if where:
        found = as_context(transcripts.context_of(where, "desktop store"), desktopSession=local)
    else:
        title = desktop.session_title(snapshot)
        found = as_context(transcripts.context_of(transcripts.titled_session(title), "title")) if title else None
    found = found or {"about": ABOUT, "details": {"desktopSession": local}}  # the tab, but no transcript found
    doc = desktop.open_markdown(snapshot, rec.get("cwd"))
    if doc:
        found["documents"] = [doc]
        found["details"]["openFile"] = doc["name"]
    return found
