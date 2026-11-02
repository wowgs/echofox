"""Claude Desktop's chats (claude.ai conversations, not the Code tab), for the claude-chat adapter, read from the screen.

A chat has no transcript on the Mac: Desktop keeps only the web app's own cache in IndexedDB, in an undocumented
binary format (measured 2026-10-25, Claude Desktop 3.6556.2). So the adapter's surface asks the client for the outline
of the page (manifest "screen": {"outline"}) and reads the messages the window shows. The chat's address is
https://claude.ai/chat/<uuid>.

In the outline, each message is a group labelled "Message <n> of <m>"; its first part is a heading hidden from the eye
("You said: …", "Claude responded: …"). Claude's reply is in a container with the DOM class "group/message-row":
paragraphs, lists with their markers ("• ", "◦ "), links. Left out: what is hidden from the eye (DOM class "sr-only":
the heading, a copy of a tool's status), buttons, a tool's status row ("Searched the web", class "group/morph"), and
the source chips after a sentence (class "group/tag"). The surface's skip list names these, so the client sends them
marked "skipped" and without their children, whose text never enters the snapshot; the parser leaves out what is
marked. The labels are in the app's language, so this reads the structure: a message is a group whose label has two
numbers and which has a hidden heading near its top; Claude's has the message-row container (measured 2026-10-25,
Claude Desktop 3.6556.2; the page is Anthropic's and not documented).
"""
import re

from adapters import SPEAKER, screen

CHAT_URL = re.compile(r"^https://claude\.ai/chat/([0-9a-fA-F-]{36})")
TITLE_SUFFIX = " - Claude"
CLAUDE = "Claude"
MESSAGE_ROW = "group/message-row"


def chat(snapshot):
    """The chat (its uuid) that has the focus in this snapshot, or None."""
    m = CHAT_URL.match(screen.web_url(snapshot))
    return m.group(1) if m else None


def title(snapshot):
    """The chat's title, from the web area's title "<title> - Claude", or None."""
    t = screen.web_title(snapshot)
    t = t[:-len(TITLE_SUFFIX)] if t.endswith(TITLE_SUFFIX) else t
    return t.strip() or None


def _label(node):
    return str(node.get("description") or node.get("title") or "")


def _is_message(nodes, i):
    n = nodes[i]
    if n.get("role") != "AXGroup" or len(re.findall(r"\d+", _label(n))) < 2:
        return False
    d = screen.depth(n)
    return any(m.get("role") == "AXHeading" and "sr-only" in screen.classes(m) and screen.depth(m) <= d + 2
               for m in nodes[i + 1:screen.end(nodes, i)])


def _text(nodes, start, end):
    """The shown text of nodes[start:end], the content of one message: a line for each block under the container
    (a paragraph, a list) and for each list item."""
    top = screen.depth(nodes[start - 1]) + 1 if start else 0  # the depth of the container's children
    lines, line = [], []
    for n in screen.shown(nodes, start, end):
        if screen.depth(n) == top or n.get("role") == "AXListMarker":
            lines.append("".join(line))
            line = []
        if n.get("text"):
            line.append(n["text"])
    lines.append("".join(line))
    return "\n".join(l.strip() for l in lines if l.strip())


def messages(nodes):
    """The messages of the chat in the outline's nodes, oldest first: [{"from": "Claude" or the speaker, "text"}].
    The first one may be cut when the outline is not complete; a message without shown text is left out."""
    out, i = [], 0
    while i < len(nodes):
        if not _is_message(nodes, i):
            i += 1
            continue
        end = screen.end(nodes, i)
        row = next((k for k in range(i + 1, end) if MESSAGE_ROW in screen.classes(nodes[k])), None)
        text = _text(nodes, i + 1, end) if row is None else _text(nodes, row + 1, screen.end(nodes, row))
        if text:
            out.append({"from": CLAUDE if row is not None else SPEAKER, "text": text})
        i = end
    return out
