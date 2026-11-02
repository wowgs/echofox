"""The surfaces of the enabled adapters, matched with the identity of a dictation (docs/adapter-surfaces.md): which
surfaces the focused app, window and page are, what the app reads there (the read request), and which part of the
app's content each surface gets."""
import functools
import re
from dataclasses import dataclass

from . import registry

# What the app sends for each part of a surface's "screen": the lists come with the frame of the focused element,
# which tells the list above it
PARTS = {"outline": ("outline",), "lists": ("lists", "focusedFrame"), "processes": ("processes",)}


@dataclass(frozen=True)
class Surface:
    """A matched surface: its adapter's name and object, and the manifest's surface (`spec`)."""
    adapter: str
    id: str
    spec: dict
    impl: object

    @property
    def name(self):
        return f"{self.adapter}/{self.id}"

    def screen(self):
        return self.spec.get("screen") or {}

    def snapshot(self, identity, content):
        """What its adapter gets: the identity, and of the content only the parts the surface declares."""
        parts = [k for part in self.screen() for k in PARTS[part]]
        return {**{k: v for k, v in (content or {}).items() if k in parts}, **(identity or {})}


@functools.lru_cache(maxsize=256)
def _pattern(pattern):
    return re.compile("".join(".*" if c == "*" else re.escape(c) for c in pattern), re.DOTALL)


def matches(pattern, value):
    """Whether the whole value matches the pattern: * is any text, possibly empty; any other character is itself."""
    return isinstance(value, str) and _pattern(pattern).fullmatch(value) is not None


def _value(identity, part, key):
    v = (identity or {}).get(part)
    return v.get(key) if isinstance(v, dict) else None


def holds(spec, identity):
    """Whether the identity is on the surface: its app is one of the surface's apps, and every rule of its "match"
    holds (url: the web area's address; title: the focused window's title)."""
    if _value(identity, "app", "bundleId") not in spec["apps"]:
        return False
    rules = spec.get("match") or {}
    return all(matches(rules[k], _value(identity, part, key)) for k, (part, key) in
               (("url", ("webArea", "url")), ("title", ("window", "title"))) if k in rules)


def match(identity, enabled):
    """The surfaces of the working adapters among `enabled` (names) that the identity is on, in the order of the
    packages and of each manifest's surfaces."""
    if not identity:
        return []
    return [Surface(p.name, s["id"], s, p.adapter) for p in registry.enabled(enabled) for s in p.surfaces
            if holds(s, identity)]


def read(surfaces, budget):
    """The read request's surfaces: for each, what the app reads, with its skip list, and each budget as a number
    (`budget(adapter, knob key)`) or None for a part without a budget key."""
    out = []
    for s in surfaces:
        entry, screen = {"surface": s.name}, s.screen()
        for part, how in screen.items():
            entry[part] = {**({"skip": list(how.get("skip") or [])} if part == "outline" else {}),
                           **({"budget": budget(s.adapter, how.get("budget")) if how.get("budget") else None}
                              if part != "processes" else {})}
        out.append(entry)
    return out


def recorded(content, name):
    """What a recorded snapshot read for the surface `name`: its "content" is {"surfaces": {name: parts}} as macos
    echofox-snapshot prints it, with the surfaces it was asked to read (--read), or with one surface named "snapshot"
    when its flags said what to read. {} when it has neither."""
    read = (content or {}).get("surfaces") if isinstance(content, dict) else None
    read = read if isinstance(read, dict) else {}
    part = read.get(name, read.get("snapshot"))
    return part if isinstance(part, dict) else {}


def answer(requested, content):
    """The content message's surfaces for a read request's `requested` surfaces, from a recorded snapshot's content
    (recorded): for each surface, the parts it asks for. The test tools answer the server with it."""
    out = {}
    for r in requested:
        read = recorded(content, r["surface"])
        out[r["surface"]] = {k: read[k] for part in PARTS if part in r for k in PARTS[part] if k in read}
    return out


def needs_content(surfaces):
    """Whether the app reads anything for these surfaces besides the identity."""
    return any(s.screen() for s in surfaces)
