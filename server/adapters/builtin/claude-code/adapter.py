"""The claude-code adapter: the Claude Code session a dictation goes into, read from its transcript on the Mac.

- Claude Desktop's Code tab, the session in focus (confidence 1.0). Ways to the session: the web area's URL → Desktop's
  record of the session → its Claude Code transcript ("desktop store"); without a record, the web area's title → the
  one transcript with that title ("title"); several transcripts with that title: no context.
- Claude Code sessions that the client names in the start message (confidence 0.9): the newest of them.
It never guesses a session from the app alone: without the Code tab's URL in the snapshot (no Accessibility
permission, another window, a chat: that is claude-chat's) it does not claim Desktop, and the newest session of an app
is often another one that runs in the background. The context has only Claude's replies: with the speaker's own
messages, the model copied the previous dictation instead of transcribing the new one (2026-10-14).
Claude writes its replies in Markdown; clean makes them plain prose.
"""
from adapters import Adapter, Claim, markdown

from . import desktop, transcripts


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
    def claim(self, focus, hints):
        m = desktop.code_tab(focus)
        if m:
            return Claim(self.name, 1.0, f"the Code tab of Claude Desktop session {m}")
        if sessions(hints):
            return Claim(self.name, 0.9, "the client named its Claude Code sessions")
        return None

    def context(self, focus, hints):
        local = desktop.code_tab(focus)
        if not local:
            return as_context(transcripts.context_of(transcripts.session_file(sessions(hints)), "named sessions"))
        cli = (desktop.record(local) or {}).get("cliSessionId")
        where = transcripts.session_file([cli]) if cli else None
        if where:
            return as_context(transcripts.context_of(where, "desktop store"), desktopSession=local)
        title = str(desktop.web_area(focus).get("title") or "")
        if title.endswith(desktop.TITLE_SUFFIX):
            return as_context(transcripts.context_of(transcripts.titled_session(title[:-len(desktop.TITLE_SUFFIX)]), "title"))
        return {"about": ABOUT, "details": {"desktopSession": local}}  # claimed, but no transcript found

    def clean(self, text):
        return markdown.plain(text)


def sessions(hints):
    """The Claude Code session ids a client sends (hints["sessions"])."""
    return [s for s in (hints or {}).get("sessions") or [] if isinstance(s, str)][:50]
