"""The claude-chat adapter: the Claude Desktop chat (a claude.ai conversation) a dictation goes into.

A chat has no transcript on the Mac, so its messages come from the screen: the outline of the page that the client
reads for its surface "desktop" (manifest "screen": {"outline"}; chat.py reads it). The core matches the surface by the
chat's address; the adapter gives a context only for an address with the chat's id. The context has only Claude's
replies: with the speaker's own messages, the model copied the previous dictation instead of transcribing the new one
(2026-10-14). Claude writes its replies in Markdown; clean makes them plain prose.
"""
from adapters import Adapter, markdown, screen

from . import chat

ABOUT = "a chat with Claude, an AI assistant"


class ClaudeChat(Adapter):
    def context(self, surface, snapshot):
        c = chat.chat(snapshot)
        return chat_context(snapshot, c) if c else None

    def clean(self, text):
        return markdown.plain(text)


def chat_context(snapshot, chat_id):
    """The context of the Claude Desktop chat in focus: Claude's replies that the window shows, newest first."""
    replies = [m for m in chat.messages(screen.nodes(snapshot)) if m["from"] == chat.CLAUDE]
    name = chat.title(snapshot)
    return {"about": f"{ABOUT}, titled “{name}”" if name else ABOUT,
            "messages": [{"from": "Claude", "text": m["text"]} for m in reversed(replies)],
            "source": "the accessibility tree of Claude Desktop",
            "details": {"chat": chat_id, "title": name, "replies": len(replies),
                        "outlineNodes": len(screen.nodes(snapshot)),
                        "outlineComplete": screen.outline(snapshot).get("complete")}}
