"""The claude-chat adapter: the Claude Desktop chat (a claude.ai conversation) a dictation goes into.

A chat has no transcript on the Mac, so its messages come from the screen: the outline of the page that the client
sends for this adapter's app (manifest "screen": ["outline"]; chat.py reads it). It claims only a chat's URL in the
snapshot (confidence 1.0), never the app alone. The context has only Claude's replies: with the speaker's own
messages, the model copied the previous dictation instead of transcribing the new one (2026-10-14). Claude writes its
replies in Markdown; clean makes them plain prose.
"""
from adapters import Adapter, Claim, markdown

from . import chat

ABOUT = "a chat with Claude, an AI assistant"


class ClaudeChat(Adapter):
    def claim(self, focus, hints):
        c = chat.chat(focus)
        return Claim(self.name, 1.0, f"the Claude Desktop chat {c}") if c else None

    def context(self, focus, hints):
        c = chat.chat(focus)
        return chat_context(focus, c) if c else None

    def clean(self, text):
        return markdown.plain(text)


def chat_context(focus, chat_id):
    """The context of the Claude Desktop chat in focus: Claude's replies that the window shows, newest first."""
    outline = (focus or {}).get("outline") or {}
    replies = [m for m in chat.messages(outline) if m["from"] == chat.CLAUDE]
    name = chat.title(focus)
    return {"about": f"{ABOUT}, titled “{name}”" if name else ABOUT,
            "messages": [{"from": "Claude", "text": m["text"]} for m in reversed(replies)],
            "source": "the accessibility tree of Claude Desktop",
            "details": {"chat": chat_id, "title": name, "replies": len(replies),
                        "outlineNodes": len(outline.get("nodes") or []), "outlineComplete": outline.get("complete")}}
