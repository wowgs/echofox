"""Adapters: one per target app (the app with the input box). They give the model the context of the conversation
the dictation goes into. Each adapter is a plugin (adapters/registry.py), and works only when the config enables it;
with none enabled, dictation runs in the base mode, without context. Plugins import this module for Adapter, Claim,
bundle and terms, and adapters.markdown for chat apps that write Markdown. The core knows no vendor: everything about
one platform's apps lives in that platform's plugin.

The core (protocol.py) never looks at the screen. The client takes one focus snapshot when the dictation starts
(see SNAPSHOT below) and sends it in the start message. The core asks every adapter whether the snapshot is its own,
and how sure it is (claim), and gives the recording to the surest one; if none claims it, the dictation runs without
context. Only that adapter finds the session and builds its context. Every adapter has clean(text): the core passes
each message of the context through it before the message goes to the model, and takes the terms from the cleaned
messages; the lines that are not prose (prose()) go afterwards when the adapter's setting proseOnly says so. clean makes the app's text plain prose (adapters/markdown.py has why).

FOCUS, the snapshot the client sends (service fields, never the text of input fields; screen content only for the
apps of an enabled adapter whose manifest asks for it in "screen"):
  {"app": {"bundleId", "pid", "name"},
   "window": {"title", "document"},
   "focused": {"role", "subrole", "title", "description", "identifier", "domClasses": [...]},
   "ancestors": [{"role", "subrole", "title", "description", "identifier", "domClasses", "url"}, ...]  (up the tree),
   "webArea": {"url", "title"}  (the nearest web area above the focused element, if any),
   "processes": [{"pid", "name", "cwd"}, ...]  (the app's child processes),
   "focusedFrame": {"x", "y", "width", "height"}  (the focused element on the screen, with "lists"),
   "lists": [{"frame": {"x", "y", "width", "height"}, "rowCount": rows in the list,
              "rows": [{"text": the row's accessible text, "columns": [the titles of its cells]}, ...]}, ...]
            (screen "lists": the lists in the focused window, in the tree's order; the last rows of each, oldest
             first, within the client's limits)}
Any part may be missing.
"""
import abc
import logging
import re
from dataclasses import dataclass

log = logging.getLogger("gemma_voice")

MAX_TERMS = 500
SENTENCE_END = re.compile(r"(?<=[.!?…:;])\s+")
LETTERS = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*")  # a word of letters in any script, with its hyphens
PROSE_LETTERS = 0.6  # a line is prose when this share of its characters are letters; not tuned
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
    """An adapter: claim, context, clean, for any app whose content tells what the speaker is writing about: a chat
    with an assistant, a messenger, mail, a document, a terminal. An adapter without one of the three cannot be made.
    The registry sets `name` and `manifest` from the plugin's adapter.json.

    focus: the snapshot (FOCUS above). hints: what the client knows and sends in the start message, as it is; the core
    does not read it (an old client's "sessions" arrive as hints["sessions"])."""
    name = ""
    manifest = {}

    @abc.abstractmethod
    def claim(self, focus, hints):
        """Claim(adapter, confidence 0..1, reason), or None if the focus is not this adapter's."""

    @abc.abstractmethod
    def context(self, focus, hints):
        """What the speaker writes into, or None:
        {"about": what it is, told to the model ("a Telegram chat with Anna"),
         "messages": [{"from": who wrote it, told to the model, "text": …}], newest first,
         "terms": names and words of this place (contacts, project names), optional,
         "source": where it was read, for the record, optional,
         "details": the adapter's own fields, for the record, optional}"""

    @abc.abstractmethod
    def clean(self, text):
        """A message's text as plain prose for the model: no markup of the app; "" drops the message."""


def names(text):
    """The words of the text in another script than Latin that start with a capital letter inside a sentence: names
    of people, places and products (Флинт, Убунту). The first word of each sentence and line is left out: its capital
    letter tells nothing."""
    out = []
    for line in text.splitlines():
        for sentence in SENTENCE_END.split(line):
            words = LETTERS.findall(sentence)
            out += [w for w in words[1:] if w[:1].isupper() and not w.isascii() and len(w) > 1]
    return out


def terms(texts):
    """The terms of the texts: Latin-script words (product names, identifiers, files) and names in other scripts, the
    most frequent first (ties: the later one first)."""
    seen, i = {}, 0
    for t in texts:
        for w in WORD.findall(t) + names(t):
            i += 1
            w = re.sub(r"[.\-/]+$", "", w)
            if len(w) < 2 or len(w) > 40 or w.count("/") > 1 or w.lower() in STOP:
                continue
            n, _ = seen.get(w, (0, 0))
            seen[w] = (n + 1, i)
    return [w for w, _ in sorted(seen.items(), key=lambda kv: (-kv[1][0], -kv[1][1]))][:MAX_TERMS]


def prose(text):
    """The lines of the text that are prose: most of their characters (spaces aside) are letters. A table row of
    numbers, a list of paths or values is not something a speaker says, so it goes; its terms were taken before."""
    keep = []
    for line in text.splitlines():
        chars = [c for c in line if not c.isspace()]
        if chars and sum(c.isalpha() for c in chars) >= PROSE_LETTERS * len(chars):
            keep.append(line)
    return "\n".join(keep)


def bundle(snapshot):
    return ((snapshot or {}).get("app") or {}).get("bundleId")


from . import registry  # noqa: E402


CONTEXT_TIMEOUT_S = 5.0  # for the whole adapter step; it took 0.04 s with Claude Code's transcript (2026-10-15)


def _guarded(adapter, what, fn, *args):
    """A plugin's call: its exception is logged and becomes ("error", text), so one plugin cannot stop the others or
    the dictation."""
    try:
        return "ok", fn(*args)
    except Exception as e:  # noqa: BLE001: a plugin is anyone's code
        log.exception("adapter %s: %s failed", adapter.name, what)
        return "error", f"{adapter.name}.{what}: {type(e).__name__}: {e}"


def claims(focus, hints=None, enabled=None, errors=None):
    """The claims of the enabled adapters (`enabled`: names; None: every working plugin), the surest first. A plugin
    whose claim fails is left out; its error goes to `errors`."""
    names = enabled if enabled is not None else list(registry.plugins())
    out = []
    for a in registry.enabled(names):
        status, c = _guarded(a, "claim", a.claim, focus or {}, hints or {})
        if status == "error":
            if errors is not None:
                errors.append(c)
            continue
        if isinstance(c, Claim):
            out.append((a, Claim(a.name, min(1.0, max(0.0, float(c.confidence))), str(c.reason))))
    return sorted(out, key=lambda ac: -ac[1].confidence)


def context(focus, hints=None, enabled=None):
    """What the dictation goes into: {"adapter", "confidence", "reason", "about", "source", "details", "messages":
    newest first and cleaned, "terms": the adapter's own terms, then the frequent ones of the cleaned messages,
    "errors": what failed in the plugins}; without "messages" if the surest adapter found nothing or failed; None if no
    enabled adapter claims the focus (with none enabled: the base mode, no context)."""
    errors = []
    ranked = claims(focus, hints, enabled, errors)
    if not ranked:
        return {"errors": errors} if errors else None
    a, c = ranked[0]
    out = {"adapter": c.adapter, "confidence": c.confidence, "reason": c.reason}
    status, found = _guarded(a, "context", a.context, focus or {}, hints or {})
    if status == "error":
        return {**out, "errors": errors + [found]}
    found = dict(found or {})
    out.update({k: found[k] for k in ("about", "source", "details") if found.get(k)})
    if isinstance(found.get("messages"), list):
        messages = []
        for m in found["messages"]:
            if not isinstance(m, dict):
                continue
            status, t = _guarded(a, "clean", a.clean, str(m.get("text") or ""))
            if status == "error":
                errors.append(t)
                break  # a clean that fails once fails for all; the context goes without the rest
            if t:
                messages.append({"from": str(m.get("from") or ""), "text": t})
        own = [t for t in found.get("terms") or [] if isinstance(t, str)]
        out["terms"] = own + [t for t in terms(m["text"] for m in reversed(messages)) if t not in own]
        out["messages"] = messages  # whole: the lines that are not prose go later, if the adapter keeps only prose
    if errors:
        out["errors"] = errors
    return out
