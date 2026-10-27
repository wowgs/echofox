"""Claude Desktop's chats (claude.ai conversations, not the Code tab), for the claude-chat adapter, read from the screen.

A chat has no transcript on the Mac: Desktop keeps only the web app's own cache in IndexedDB, in an undocumented
binary format (measured 2026-10-25, Claude Desktop 3.6556.2). So the adapter asks the client for the outline of the
page (manifest "screen": ["outline"]) and reads the messages the window shows. The chat's address is
https://claude.ai/chat/<uuid>.

In the outline, each message is a group labelled "Message <n> of <m>"; its first part is a heading hidden from the eye
("You said: …", "Claude responded: …"). Claude's reply is in a container with the DOM class "group/message-row":
paragraphs, lists with their markers ("• ", "◦ "), links. Left out: what is hidden from the eye (DOM class "sr-only":
the heading, a copy of a tool's status), buttons, a tool's status row ("Searched the web", class "group/morph"), and
the source chips after a sentence (links with class "group/tag"). The labels are in the app's language, so this reads
the structure: a message is a group whose label has two numbers and which has a hidden heading near its top; Claude's
has the message-row container (measured 2026-10-25, Claude Desktop 3.6556.2; the page is Anthropic's and not
documented).
"""
import re

from adapters import bundle


BUNDLE = "com.anthropic.claudefordesktop"


def web_area(snapshot):
    return (snapshot or {}).get("webArea") or {}


CHAT_URL = re.compile(r"^https://claude\.ai/chat/([0-9a-fA-F-]{36})")
TITLE_SUFFIX = " - Claude"
CLAUDE, SPEAKER = "Claude", "the speaker"
MESSAGE_ROW = "group/message-row"


def chat(snapshot):
    """The chat (its uuid) that has the focus in Claude Desktop in this snapshot, or None."""
    if bundle(snapshot) != BUNDLE:
        return None
    m = CHAT_URL.match(str(web_area(snapshot).get("url") or ""))
    return m.group(1) if m else None


def title(snapshot):
    """The chat's title, from the web area's title "<title> - Claude", or None."""
    t = str(web_area(snapshot).get("title") or "")
    t = t[:-len(TITLE_SUFFIX)] if t.endswith(TITLE_SUFFIX) else t
    return t.strip() or None


def _classes(node):
    return node.get("domClasses") or []


def _label(node):
    return str(node.get("description") or node.get("title") or "")


def _end(nodes, i):
    """The index after the subtree of nodes[i]."""
    d = nodes[i].get("depth", 0)
    j = i + 1
    while j < len(nodes) and nodes[j].get("depth", 0) > d:
        j += 1
    return j


def _is_message(nodes, i):
    n = nodes[i]
    if n.get("role") != "AXGroup" or len(re.findall(r"\d+", _label(n))) < 2:
        return False
    d = n.get("depth", 0)
    return any(m.get("role") == "AXHeading" and "sr-only" in _classes(m) and m.get("depth", 0) <= d + 2
               for m in nodes[i + 1:_end(nodes, i)])


def _skipped(node):
    classes = _classes(node)
    return ("sr-only" in classes or node.get("role") == "AXButton" or "group/morph" in classes
            or (node.get("role") == "AXLink" and "group/tag" in classes))


def _text(nodes, start, end):
    """The shown text of nodes[start:end], the content of one message: a line for each block under the container
    (a paragraph, a list) and for each list item."""
    top = nodes[start - 1].get("depth", 0) + 1 if start else 0  # the depth of the container's children
    lines, line, skip = [], [], None
    for n in nodes[start:end]:
        d = n.get("depth", 0)
        if skip is not None:
            if d > skip:
                continue
            skip = None
        if _skipped(n):
            skip = d
            continue
        if d == top or n.get("role") == "AXListMarker":
            lines.append("".join(line))
            line = []
        if n.get("text"):
            line.append(n["text"])
    lines.append("".join(line))
    return "\n".join(l.strip() for l in lines if l.strip())


def messages(outline):
    """The messages of the chat in the outline, oldest first: [{"from": "Claude" or "the speaker", "text"}]. The
    first one may be cut when the outline is not complete; a message without shown text is left out."""
    nodes = [n for n in (outline or {}).get("nodes") or [] if isinstance(n, dict)]
    out, i = [], 0
    while i < len(nodes):
        if not _is_message(nodes, i):
            i += 1
            continue
        end = _end(nodes, i)
        row = next((k for k in range(i + 1, end) if MESSAGE_ROW in _classes(nodes[k])), None)
        if row is None:
            text = _text(nodes, i + 1, end)
        else:
            text = _text(nodes, row + 1, _end(nodes, row))
        if text:
            out.append({"from": CLAUDE if row is not None else SPEAKER, "text": text})
        i = end
    return out
