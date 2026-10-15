"""Adapters: one per target app (the app with the input box). They give the model the context of the conversation
the dictation goes into. Each adapter is a plugin (adapters/registry.py), and works only when the config enables it;
with none enabled, dictation runs in the base mode, without context. Plugins import this module for Adapter, Claim,
bundle, terms, and the libraries markdown and claude_transcripts.

The core (protocol.py) never looks at the screen. The client takes one focus snapshot when the dictation starts
(see SNAPSHOT below) and sends it in the start message. The core asks every adapter whether the snapshot is its own,
and how sure it is (claim), and gives the recording to the surest one; if none claims it, the dictation runs without
context. Only that adapter finds the session and builds its context. Every adapter has clean(text): the core passes
each message of the context through it before the message goes to the model, and takes the terms from the cleaned
messages. clean makes the app's text plain prose (adapters/markdown.py has why).

SNAPSHOT, as the client sends it (only service fields, never the text of input fields):
  {"app": {"bundleId", "pid", "name"},
   "window": {"title", "document"},
   "focused": {"role", "subrole", "title", "description", "identifier", "domClasses": [...]},
   "ancestors": [{"role", "subrole", "title", "description", "identifier", "domClasses", "url"}, ...]  (up the tree),
   "webArea": {"url", "title"}  (the nearest web area above the focused element, if any),
   "processes": [{"pid", "name", "cwd"}, ...]  (the app's child processes)}
Any part may be missing.
"""
import abc
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


class Adapter(abc.ABC):
    """An adapter: claim, context, clean. An adapter without one of them cannot be made. The registry sets `name` and
    `manifest` from the plugin's adapter.json."""
    name = ""
    manifest = {}

    @abc.abstractmethod
    def claim(self, snapshot, sessions):
        """Claim, or None if the snapshot is not this adapter's."""

    @abc.abstractmethod
    def context(self, snapshot, sessions):
        """{"session", "file", "how", "title", "messages": [{"role", "text"}] newest first}, or None."""

    @abc.abstractmethod
    def clean(self, text):
        """A message's text as plain prose for the model: no markup of the app; "" drops the message."""


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


from . import registry  # noqa: E402


def claims(snapshot, sessions=(), enabled=None):
    """The claims of the enabled adapters (`enabled`: names; None: every working plugin), the surest first."""
    names = enabled if enabled is not None else list(registry.plugins())
    out = []
    for a in registry.enabled(names):
        c = a.claim(snapshot, sessions)
        if c is not None:
            out.append((a, c))
    return sorted(out, key=lambda ac: -ac[1].confidence)


def context(snapshot, sessions=(), enabled=None):
    """The context of the conversation the dictation goes into: {"adapter", "confidence", "reason", "session", "file",
    "how", "title", "messages": newest first and cleaned, "terms": from the cleaned messages}, or with no "messages"
    if the surest adapter found no conversation, or None if no enabled adapter claims the snapshot (with none enabled:
    the base mode, no context)."""
    ranked = claims(snapshot, sessions, enabled)
    if not ranked:
        return None
    a, c = ranked[0]
    found = dict(a.context(snapshot, sessions) or {})
    if "messages" in found:
        found["messages"] = [{**m, "text": t} for m in found["messages"] if (t := a.clean(m["text"]))]
        found["terms"] = terms(m["text"] for m in reversed(found["messages"]))
    return {"adapter": c.adapter, "confidence": c.confidence, "reason": c.reason, **found}
