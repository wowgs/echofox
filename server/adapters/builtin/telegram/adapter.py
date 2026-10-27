"""The Telegram adapter: the chat a dictation goes into, in Telegram Desktop.

The client sends, for this adapter's apps, the rows of the lists in the focused window (manifest "screen": ["lists"]).
The open chat's messages are the list above the input box; desktop.py reads them. The context is what the window has
loaded: the newest messages of the chat, not its whole history. Telegram's texts are plain, so clean only joins the
lines.
"""
from adapters import Adapter, Claim, bundle

from . import desktop


class Telegram(Adapter):
    def claim(self, focus, hints):
        if bundle(focus) not in (self.manifest.get("apps") or []):
            return None
        found = desktop.message_list(focus)
        if not found or not desktop.messages(found.get("rows") or []):
            return None
        return Claim(self.name, 1.0, "the chat open in Telegram Desktop")

    def context(self, focus, hints):
        found = desktop.message_list(focus)
        if not found:
            return None
        rows = found.get("rows") or []
        found_messages = desktop.messages(rows)
        name = desktop.chat_name(((focus or {}).get("window") or {}).get("title"))
        senders = {m["from"] for m in found_messages if m["from"] != desktop.SPEAKER}
        return {"about": f"a Telegram chat with {name}" if name else "a Telegram chat",
                "messages": list(reversed(found_messages)),  # newest first
                "terms": sorted(senders) + ([name] if name and name not in senders else []),
                "source": "the accessibility tree of Telegram Desktop",
                "details": {"chat": name, "rows": len(rows), "rowsInWindow": found.get("rowCount"),
                            "messages": len(found_messages)}}

    def clean(self, text):
        return " ".join(str(text).split())
