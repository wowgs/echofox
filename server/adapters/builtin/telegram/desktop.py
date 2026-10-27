"""Telegram Desktop on the screen: the chat open in the window, as its accessibility tree shows it.

The window has two lists: the chats on the left and the open chat's messages on the right, above the input box. Each
message is a row whose accessible text is lines joined by "\\n", and whose cells are titled with the columns that the
message has (Telegram Desktop, Telegram/SourceFiles/history/history_inner_widget_accessibility.cpp,
MessageAccessibilityName, branch dev, 2026-10-18):

  "Seen" or "Not seen"            only for the speaker's own messages; the first cell is then titled "Seen"
  the sender                      the speaker's own: "You"; none for some service-like posts
  via the bot, the reply, the forward    when the message has them
  the media, the web page, the caption or the text
  the fact check, "Pinned"        when the message has them
  the status                      "Sent" or "Received", "edited", "at <time>", the views, the signature
  the reactions                   when the message has them

The words are in the app's language, so this module reads the structure, not the words: the speaker's own messages
by the first line repeating the first cell's title (seen messages show it), the status as the last line with a time
in it. A service message (a member joined) is one line without cells.

The window title is the open chat's name: "[(unread) ]<name>[ @ <account> or ' –'][ (total unread)]", or "Telegram"
when no chat is open or the settings hide the name (Telegram/SourceFiles/window/main_window.cpp, updateTitle).
"""
import re

TIME = re.compile(r"\b\d{1,2}[:.]\d{2}(?:\s?[AaPp]\.?[Mm]\.?)?(?!\d)")
SPEAKER = "the speaker"


def chat_name(title):
    """The open chat's name from the window title, or None."""
    t = re.sub("[\u200e\u200f\u202a-\u202e\u2066-\u2069]", "", str(title or "")).strip()
    t = re.sub(r"\s•\s.*$", "", t)  # a canary build's suffix
    t = re.sub(r"\s\(\d+\)$", "", t)  # the total unread
    t = re.sub(r"\s–$", "", t)
    t = re.sub(r"\s@\s.*$", "", t)  # the account, with several accounts
    t = re.sub(r"^\(\d+\)\s", "", t)  # the chat's own unread
    t = t.strip("‎‏‪‫‬ ")  # right-to-left wrapping
    return t if t and t != "Telegram" else None


def _frame(d):
    try:
        return float(d["x"]), float(d["y"]), float(d["width"]), float(d["height"])
    except (KeyError, TypeError, ValueError):
        return None


def message_list(focus):
    """The list of the open chat's messages: the one above the focused input box (the list whose horizontal span holds
    the box's middle), else the widest list with rows."""
    lists = [l for l in (focus or {}).get("lists") or [] if isinstance(l, dict) and l.get("rows")]
    if not lists:
        return None
    box = _frame((focus or {}).get("focusedFrame") or {})
    if box:
        middle = box[0] + box[2] / 2
        above = [l for l in lists if (f := _frame(l.get("frame") or {})) and f[0] <= middle <= f[0] + f[2]]
        if above:
            return max(above, key=lambda l: _frame(l["frame"])[2])
    return max(lists, key=lambda l: (_frame(l.get("frame") or {}) or (0, 0, 0, 0))[2])


def _seen_title(rows):
    """The title of the "Seen" column: a seen message of the speaker repeats it as its first line."""
    for r in rows:
        cols, lines = r.get("columns") or [], str(r.get("text") or "").split("\n")
        if len(cols) > 1 and lines and lines[0] == cols[0]:
            return cols[0]
    return None


def messages(rows):
    """The rows of the message list → [{"from", "text"}], oldest first. The sender is the speaker for their own
    messages. The text keeps what the message shows besides the sender and the status: the text or caption, and the
    lines of a reply, a forward or a medium."""
    seen = _seen_title(rows)
    out = []
    for r in rows:
        cols = r.get("columns") or []
        lines = [l.strip() for l in str(r.get("text") or "").split("\n")]
        if not cols or len(lines) < 2:
            continue  # a service message, or an empty row
        own = seen is not None and cols[0] == seen
        if own:
            lines = lines[1:]
        if len(lines) < 2:
            continue
        sender, body = lines[0], lines[1:]
        status = max((i for i, l in enumerate(body) if TIME.search(l)), default=None)
        if status is not None:
            body = body[:status]
        text = "\n".join(l for l in body if l).strip()
        if text:
            out.append({"from": SPEAKER if own else sender, "text": text})
    return out
