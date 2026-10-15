"""Adapters: one per target app (the app with the input box). They give the model the context of the conversation
the dictation goes into.

The core (protocol.py) never looks at the screen. The client takes one focus snapshot when the dictation starts
(see SNAPSHOT below) and sends it in the start message. The core asks every adapter whether the snapshot is its own,
and how sure it is (claim), and gives the recording to the surest one; if none claims it, the dictation runs without
context. Only that adapter finds the session and builds its context.

SNAPSHOT, as the client sends it (only service fields, never the text of input fields):
  {"app": {"bundleId", "pid", "name"},
   "window": {"title", "document"},
   "focused": {"role", "subrole", "title", "description", "identifier", "domClasses": [...]},
   "ancestors": [{"role", "subrole", "title", "description", "identifier", "domClasses", "url"}, ...]  (up the tree),
   "webArea": {"url", "title"}  (the nearest web area above the focused element, if any),
   "processes": [{"pid", "name", "cwd"}, ...]  (the app's child processes)}
Any part may be missing.
"""
import re
from dataclasses import dataclass

MAX_TERMS = 500
# Latin-script words: product names, identifiers, file names. A word joined by . _ + # - / stays one term.
WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[._+#/-][A-Za-z0-9]+)*\+*")
STOP = set(("a an and are as at be but by can do for from has have he i if in is it its me my no not of on "
            "or our so that the their them then there they this to too up us was we what when which who will with would "
            "you your ok okay yes just like also all any one two how why get got go see let use").split())


@dataclass
class Claim:
    """An adapter's answer to "is this snapshot yours": 0 < confidence <= 1, and why."""
    adapter: str
    confidence: float
    reason: str


def terms(texts):
    """Latin-script terms of the texts, the most frequent first (ties: the later one first)."""
    seen, i = {}, 0
    for t in texts:
        for w in WORD.findall(t):
            i += 1
            w = re.sub(r"[.\-/]+$", "", w)
            if len(w) < 2 or len(w) > 40 or w.count("/") > 1 or w.lower() in STOP:
                continue
            n, _ = seen.get(w, (0, 0))
            seen[w] = (n + 1, i)
    return [w for w, _ in sorted(seen.items(), key=lambda kv: (-kv[1][0], -kv[1][1]))][:MAX_TERMS]


def bundle(snapshot):
    return ((snapshot or {}).get("app") or {}).get("bundleId")


def snapshot_of(start):
    """The snapshot of a start message: "snapshot", or, from clients before snapshots, "app" (a bundle id)."""
    s = start.get("snapshot")
    if isinstance(s, dict):
        return s
    return {"app": {"bundleId": start["app"]}} if isinstance(start.get("app"), str) else {}


from . import claude_code, claude_desktop  # noqa: E402

# The adapters, in the order that breaks a tie of confidence.
ADAPTERS = [claude_desktop.ClaudeDesktop(), claude_code.ClaudeCode()]


def claims(snapshot, sessions=()):
    """Every adapter's claim on the snapshot, the surest first."""
    out = []
    for a in ADAPTERS:
        c = a.claim(snapshot, sessions)
        if c is not None:
            out.append((a, c))
    return sorted(out, key=lambda ac: -ac[1].confidence)


def context(snapshot, sessions=()):
    """The context of the conversation the dictation goes into: {"adapter", "confidence", "reason", "session", "file",
    "how", "title", "messages": newest first, "terms"}, or with no "messages" if the surest adapter found no
    conversation, or None if no adapter claims the snapshot."""
    ranked = claims(snapshot, sessions)
    if not ranked:
        return None
    a, c = ranked[0]
    found = a.context(snapshot, sessions) or {}
    return {"adapter": c.adapter, "confidence": c.confidence, "reason": c.reason, **found}
