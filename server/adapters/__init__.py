"""Adapters: one per product the speaker writes into (Claude Code, Claude chats, Telegram). They give the model the
context of the conversation the dictation goes into. Each adapter is a package of its own (adapters/registry.py), and
works only when the config enables it; with none enabled, dictation runs in the base mode, without context. Adapters
import this module for Adapter, SPEAKER, place, terms and prose, adapters.screen for what they read of the snapshot,
and adapters.markdown for apps that write Markdown. The core knows no vendor: everything about one platform's apps
lives in that platform's adapter.

A product has surfaces: the places where it is on the screen (the Code tab of Claude Desktop, a terminal's tab), in
the adapter's manifest (docs/adapter-surfaces.md). The core (session.py) never looks at the screen. The client sends
the identity of the focused app, window and page in the start message (IDENTITY below). The core matches it with the
surfaces of the enabled adapters (adapters/surfaces.py) and answers at once with a read request: for each matched
surface, what the client reads there and up to which budget. The client reads only that and sends it in a content
message (CONTENT below). Then each matched surface's adapter gets its snapshot, the identity and the content of that
surface, and gives the context of the conversation there, or None when it is not sure. With no context, or with more
than one, the dictation runs without context. Every adapter has clean(text): the core passes each message and document
of the context through it before it goes to the model, and takes the terms from the cleaned messages; the lines that
are not prose (prose()) go afterwards when the adapter's setting proseOnly says so. clean makes the app's text plain
prose (adapters/markdown.py has why).

IDENTITY, the same fields for every app of an enabled adapter's surfaces, and nothing for other apps:
  {"app": {"bundleId", "pid", "name"},
   "window": {"title"}  (the focused window),
   "webArea": {"url", "title"}  (the nearest web area above the focused element, if any)}
CONTENT, for each surface, only what its manifest's "screen" declares (never the text of input fields):
  "outline": {"root": "webArea" or "window", "complete": whether it has the whole tree under the root,
              "nodes": [{"depth": under the root (the root is 0), "role", "subrole", "title", "description",
                         "domClasses", "text": the shown text of a static text or a list marker,
                         "skipped": true for an element of the surface's skip list, sent without its children}, ...]}
             (the tree under the web area of the focused element, or under the focused window without one, in the
              tree's order, flat with depths; read from its end up to the surface's budget: a chat's newest messages
              are there)
  "lists": [{"frame": {"x", "y", "width", "height"}, "rowCount": rows in the list,
             "rows": [{"text": the row's accessible text, "columns": [the titles of its cells]}, ...]}, ...]
           (the lists in the focused window, in the tree's order; the last rows of each, oldest first, up to the
            surface's budget), with "focusedFrame": {"x", "y", "width", "height"}, the focused element on the screen
  "processes": [{"pid", "name"}, ...]  (the app's child processes)
Any part may be missing.
"""
import abc
import asyncio
import concurrent.futures
import logging
import os
import re
import time

log = logging.getLogger("gemma_voice")

SPEAKER = "the speaker"  # who wrote the speaker's own messages, told to the model
SENTENCE_END = re.compile(r"(?<=[.!?…:;])\s+")
LETTERS = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*")  # a word of letters in any script, with its hyphens
PROSE_LETTERS = 0.6  # a line is prose when this share of its characters are letters; not tuned
# Latin-script words: product names, identifiers, file names. A word joined by . _ + # - / stays one term.
WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[._+#/-][A-Za-z0-9]+)*\+*")
STOP = set(("a an and are as at be but by can do for from has have he i if in is it its me my no not of on "
            "or our so that the their them then there they this to too up us was we what when which who will with would "
            "you your ok okay yes just like also all any one two how why get got go see let use").split())


class Adapter(abc.ABC):
    """An adapter: context and clean, for a product whose content tells what the speaker is writing about: a chat
    with an assistant, a messenger, mail, a document, a terminal. An adapter without one of the two cannot be made.
    The registry sets `name` and `manifest` from the adapter's adapter.json."""
    name = ""
    manifest = {}

    @abc.abstractmethod
    def context(self, surface, snapshot):
        """The conversation on the surface `surface` (its id in the manifest) that the snapshot shows, or None when
        it is not found for sure. snapshot: the identity and that surface's content (IDENTITY, CONTENT above).
        {"about": what it is, told to the model ("a chat with Anna in a messenger"),
         "messages": [{"from": who wrote it, told to the model, "text": …}], newest first,
         "documents": [{"name": the file's name, told to the model, "text": …}], the files open beside the
                      conversation, the most relevant first, optional,
         "terms": names and words of this place (contacts, project names), optional,
         "source": where it was read, for the record, optional,
         "details": the adapter's own fields, for the record, optional}"""

    @abc.abstractmethod
    def clean(self, text):
        """A message's or a document's text as plain prose for the model: no markup of the app; "" drops it. The one
        place where an adapter changes a text."""


def place(default, env):
    """A fixed place on the disk that an adapter reads: $<env> if it is set (the tests set it), else `default` with
    ~ expanded. Read at each call."""
    return os.environ.get(env) or os.path.expanduser(default)


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
    return [w for w, _ in sorted(seen.items(), key=lambda kv: (-kv[1][0], -kv[1][1]))]  # the terms' budget cuts them


def prose(text):
    """The lines of the text that are prose: most of their characters (spaces aside) are letters. A table row of
    numbers, a list of paths or values is not something a speaker says, so it goes; its terms were taken before."""
    keep = []
    for line in text.splitlines():
        chars = [c for c in line if not c.isspace()]
        if chars and sum(c.isalpha() for c in chars) >= PROSE_LETTERS * len(chars):
            keep.append(line)
    return "\n".join(keep)


from . import registry, screen, surfaces  # noqa: E402,F401  (they import Adapter from here)
from .surfaces import match, needs_content, read  # noqa: E402,F401


# The adapters run on a thread of their own, not in the event loop's default pool, which the model's requests use:
# an adapter still running at the stop keeps its thread, and must not take one of theirs. While it runs, the next
# dictations get no context instead of a second thread.
_worker = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="adapters")
_running = None  # the call that runs now, a concurrent.futures.Future


async def context_until(identity, matched, content=None, stop=None):
    """context(), on the adapters' thread, until it ends or `stop` (an asyncio.Event: the end of the recording) is set,
    whichever is first. No context by the stop gives {"errors": […]}; so does a call while an earlier one still runs.
    The adapters' time is logged when they end, also after the stop."""
    global _running
    if _running is not None and not _running.done():
        return {"errors": ["the adapters still run for an earlier dictation"]}
    started = time.monotonic()
    _running = _worker.submit(context, identity, matched, content)
    _running.add_done_callback(lambda f: log.info("adapters: %.3f s", time.monotonic() - started))
    found = asyncio.ensure_future(asyncio.shield(asyncio.wrap_future(_running)))
    stopped = asyncio.ensure_future(stop.wait()) if stop is not None else None
    try:
        await asyncio.wait({found} | ({stopped} if stopped else set()), return_when=asyncio.FIRST_COMPLETED)
    finally:
        if stopped:
            stopped.cancel()
    if found.done():
        return found.result()
    found.cancel()
    return {"errors": [f"no context by the stop, {time.monotonic() - started:.1f} s after the start"]}


def _guarded(adapter, what, fn, *args):
    """An adapter's call: its exception is logged and becomes ("error", text), so one adapter cannot stop the others or
    the dictation."""
    try:
        return "ok", fn(*args)
    except Exception as e:  # any exception: an adapter is anyone's code
        log.exception("adapter %s: %s failed", adapter.name, what)
        return "error", f"{adapter.name}.{what}: {type(e).__name__}: {e}"


def _cleaned(a, items, errors, keep):
    """The items' texts through the adapter's clean, as keep(item, text) makes them; an item that cleans to "" goes.
    A clean that fails once fails for all: its error goes to `errors`, and the items after it go."""
    out = []
    for item in items:
        status, t = _guarded(a, "clean", a.clean, str(item.get("text") or ""))
        if status == "error":
            errors.append(t)
            break
        if t:
            out.append(keep(item, t))
    return out


def context(identity, matched, content=None):
    """What the dictation goes into, from the matched surfaces (adapters.match) and the content the client sent for
    them, by surface name: {"adapter", "surface": <adapter>/<id>, "about", "source", "details", "messages": newest
    first and cleaned, "documents": [{"name", "text"}] cleaned, "terms": the adapter's own terms, then the frequent
    ones of the cleaned messages, "errors": what failed in the adapters}; without "messages", "documents" or "terms"
    if the adapter gave none. None if no surface gives a context (with none matched: the base mode, no context). More
    than one context: none of them, and the errors name the surfaces, since the conversation is not certain. A
    document without a name, or empty once cleaned, is left out."""
    errors, found = [], []
    for s in matched:
        status, got = _guarded(s.impl, "context", s.impl.context, s.id, s.snapshot(identity, (content or {}).get(s.name)))
        if status == "error":
            errors.append(got)
        elif got:
            found.append((s, dict(got)))
    if len(found) > 1:
        return {"errors": errors + [f"more than one surface gave a context: {', '.join(s.name for s, _ in found)}; "
                                    "the dictation goes without context"]}
    if not found:
        return {"errors": errors} if errors else None
    s, found = found[0]
    a = s.impl
    out = {"adapter": s.adapter, "surface": s.name, **{k: found[k] for k in ("about", "source", "details") if found.get(k)}}
    messages = []
    if isinstance(found.get("messages"), list):
        messages = _cleaned(a, [m for m in found["messages"] if isinstance(m, dict)], errors,
                            lambda m, t: {"from": str(m.get("from") or ""), "text": t})
        out["messages"] = messages  # whole: the lines that are not prose go later, if the adapter keeps only prose
    if isinstance(found.get("documents"), list):
        named = [d for d in found["documents"]
                 if isinstance(d, dict) and isinstance(d.get("name"), str) and d["name"].strip()]
        documents = _cleaned(a, named, errors, lambda d, t: {"name": d["name"].strip(), "text": t})
        if documents:
            out["documents"] = documents
    own = [t for t in found.get("terms") or [] if isinstance(t, str)]
    found_terms = own + [t for t in terms(m["text"] for m in reversed(messages)) if t not in own]
    if found_terms:
        out["terms"] = found_terms  # also without messages: the names of a place help on their own
    if errors:
        out["errors"] = errors
    return out
