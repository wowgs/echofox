"""The Claude plugin: the conversation a dictation goes into, in Anthropic's Claude apps.

- Claude Desktop's Code tab, the session in focus (confidence 1.0). Ways to the session: the web area's URL → Desktop's
  record of the session → its Claude Code transcript ("desktop store"); without a record, the web area's title → the
  one transcript with that title ("title"); several transcripts with that title: no context.
- Claude Desktop's chats (claude.ai conversations), the chat in focus (confidence 1.0): it has no transcript on the
  Mac, so its messages come from the screen, the outline of the page that the client sends (chat.py).
- Claude Code sessions that the client names in the start message (confidence 0.9): the newest of them.
It never guesses a session from the app alone: without the Code tab's or the chat's URL in the snapshot (no
Accessibility permission, another window) it does not claim Desktop, and the newest session of an app is often another
one that runs in the background. Like the Code tab's, a chat's context has only Claude's replies: with the speaker's
own messages, the model copied the previous dictation instead of transcribing the new one (2026-10-14).
Claude writes its replies in Markdown; clean makes them plain prose.
"""
from adapters import Adapter, Claim, markdown

from . import chat, desktop, transcripts


ABOUT = "a session with Claude, an AI assistant for software work"
ABOUT_CHAT = "a chat with Claude, an AI assistant"


def as_context(found, **details):
    """A transcript that transcripts.context_of found → this plugin's context, or None."""
    if not found:
        return None
    return {"about": ABOUT, "messages": [{"from": "Claude", "text": m["text"]} for m in found["messages"]],
            "source": f"{found['how']}: {found['file']}",
            "details": {"session": found["session"], "file": found["file"], "how": found["how"],
                        "title": found.get("title"), **details}}


class Claude(Adapter):
    def claim(self, focus, hints):
        m = desktop.code_tab(focus)
        if m:
            return Claim(self.name, 1.0, f"the Code tab of Claude Desktop session {m}")
        c = chat.chat(focus)
        if c:
            return Claim(self.name, 1.0, f"the Claude Desktop chat {c}")
        if sessions(hints):
            return Claim(self.name, 0.9, "the client named its Claude Code sessions")
        return None

    def context(self, focus, hints):
        c = chat.chat(focus)
        if c:
            return chat_context(focus, c)
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


def chat_context(focus, chat_id):
    """The context of the Claude Desktop chat in focus: Claude's replies that the window shows, newest first."""
    outline = (focus or {}).get("outline") or {}
    replies = [m for m in chat.messages(outline) if m["from"] == chat.CLAUDE]
    name = chat.title(focus)
    return {"about": f"{ABOUT_CHAT}, titled “{name}”" if name else ABOUT_CHAT,
            "messages": [{"from": "Claude", "text": m["text"]} for m in reversed(replies)],
            "source": "the accessibility tree of Claude Desktop",
            "details": {"chat": chat_id, "title": name, "replies": len(replies),
                        "outlineNodes": len(outline.get("nodes") or []), "outlineComplete": outline.get("complete")}}


def sessions(hints):
    """The Claude Code session ids a client sends (hints["sessions"])."""
    return [s for s in (hints or {}).get("sessions") or [] if isinstance(s, str)][:50]
