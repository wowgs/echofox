"""The Telegram adapter: the chat a dictation goes into, in Telegram Desktop.

Its surface "desktop" asks the client for the rows of the lists in the focused window (manifest "screen": {"lists"}).
The open chat's messages are the list above the input box; desktop.py reads them. The context is what the window has
loaded: the newest messages of the chat, not its whole history. No message in the window: no context. Telegram's texts
are plain, so clean only joins the lines.
"""
from adapters import SPEAKER, Adapter, screen

from . import desktop


class Telegram(Adapter):
    def context(self, surface, snapshot):
        found = desktop.message_list(snapshot)
        rows = (found or {}).get("rows") or []
        found_messages = desktop.messages(rows)
        if not found_messages:
            return None
        name = desktop.chat_name(screen.window_title(snapshot))
        senders = {m["from"] for m in found_messages if m["from"] != SPEAKER}
        return {"about": f"a Telegram chat with {name}" if name else "a Telegram chat",
                "messages": list(reversed(found_messages)),  # newest first
                "terms": sorted(senders) + ([name] if name and name not in senders else []),
                "source": "the accessibility tree of Telegram Desktop",
                "details": {"chat": name, "rows": len(rows), "rowsInWindow": found.get("rowCount"),
                            "messages": len(found_messages)}}

    def clean(self, text):
        return " ".join(str(text).split())
