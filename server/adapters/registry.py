"""The adapters: the built-in ones in server/adapters/builtin/, the user's in ~/Library/Application Support/EchoFox/
adapters/ ($ECHOFOX_ADAPTERS). Each adapter is a folder, a package, with:
  adapter.json  its manifest, interface 3: shared/adapter.schema.json has its fields. An adapter is a product the
                speaker writes into, and its "surfaces" say where the product is on the screen ("apps", "match"), what
                the app reads there besides the identity ("screen") and which files the adapter reads ("reads").
                "context" has the defaults of its context's settings: the adapter's knobs of tuning.py, such as
                chatHistoryTokenBudget; the user's entry in the config changes them.
  adapter.py    a module with one class that subclasses adapters.Adapter; the folder is a package, so adapter.py can
                import the adapter's other modules (from . import helpers)
An adapter the user puts in the folder is theirs to trust: the server checks only that the manifest follows the
schema's rules (check(); the venv has no JSON Schema library, so the rules are in the code, and test_contract.py ties
them to the schema's fields), that its interface is this one, that its "context" and its budgets name only the
adapter's knobs, and that the module has its class. A user adapter with the name of a built-in one replaces it. An
adapter works only when the config enables it (adapters: {"<name>": {"enabled": true}}).
"""
import contextlib
import importlib.util
import json
import logging
import os
import re
import sys
import threading
from dataclasses import dataclass, field

import adapters
import constants
import tuning

NAME = re.compile(r"[A-Za-z0-9_.-]+")
SURFACE_ID = re.compile(r"[a-z0-9-]+")
# The fields of a surface and of its parts, as shared/adapter.schema.json has them (no other field is allowed)
SURFACE = {"id", "title", "apps", "treeOnRequest", "match", "screen", "reads"}
MATCH = {"url", "title"}
SCREEN = {"outline": {"skip", "budget"}, "lists": {"budget"}, "processes": set()}
READ = {"path", "what"}
BUILTIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "builtin")
log = logging.getLogger("gemma_voice")


def user_dir():
    return os.environ.get("ECHOFOX_ADAPTERS") or constants.path(constants.ADAPTERS)


@dataclass
class Package:
    name: str
    dir: str
    builtin: bool
    manifest: dict = field(default_factory=dict)
    surfaces: list = field(default_factory=list)  # the manifest's, once they are checked
    adapter: object = None
    error: str = None

    def info(self, enabled):
        """For the app: what the adapter is, says about itself, its surfaces as the manifest has them, and whether it
        works."""
        m = self.manifest
        return {"name": self.name, "title": m.get("title"), "enabled": self.name in enabled and self.adapter is not None,
                "builtin": self.builtin, "version": m.get("version"), "author": m.get("author"),
                "source": m.get("source"), "description": m.get("description"), "surfaces": self.surfaces,
                "context": m.get("context") or {}, "error": self.error}


def _object(value, what, allowed):
    if not isinstance(value, dict):
        raise ValueError(f"{what} is not an object")
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise ValueError(f"{what} has {unknown}; it may have only {sorted(allowed)}")
    return value


def _strings(value, what, least=0):
    if not (isinstance(value, list) and len(value) >= least and all(isinstance(s, str) and s for s in value)):
        raise ValueError(f"{what} is not a list of {'at least one ' if least else ''}names")
    return value


def _budget(part, what):
    key = part.get("budget")
    knob = tuning.BY_KEY.get(key) if isinstance(key, str) else None
    if "budget" in part and not (knob and knob.owner == "adapter" and knob.kind is int):
        raise ValueError(f"{what} budget {key!r} is not a token budget of the adapter's knobs")


def check_surface(s, i):
    """One surface of a manifest, checked against the schema's rules; raises ValueError with what is wrong."""
    _object(s, f"surface {i}", SURFACE)
    what = f"surface {s.get('id', i)!r}"
    if not isinstance(s.get("id"), str) or not SURFACE_ID.fullmatch(s["id"]):
        raise ValueError(f"surface {i} has no good \"id\" (small letters, digits and -)")
    if not isinstance(s.get("title"), str):
        raise ValueError(f"{what} has no \"title\"")
    _strings(s.get("apps"), f"{what} \"apps\"", least=1)
    if not isinstance(s.get("treeOnRequest", False), bool):
        raise ValueError(f"{what} \"treeOnRequest\" is neither true nor false")
    for k, v in _object(s.get("match", {}), f"{what} \"match\"", MATCH).items():
        if not isinstance(v, str):
            raise ValueError(f"{what} \"match\" {k} is not a pattern")
    for part, value in _object(s.get("screen", {}), f"{what} \"screen\"", SCREEN).items():
        _object(value, f"{what} \"screen\" {part}", SCREEN[part])
        if "skip" in value:
            _strings(value["skip"], f"{what} outline \"skip\"")
        _budget(value, f"{what} {part}")
    reads = s.get("reads", [])
    if not isinstance(reads, list):
        raise ValueError(f"{what} \"reads\" is not a list")
    for r in reads:
        _object(r, f"{what} \"reads\" entry", READ)
        if not isinstance(r.get("what"), str) or not isinstance(r.get("path", ""), str):
            raise ValueError(f"{what} \"reads\" entry needs \"what\", and \"path\" is text")


def check(m):
    """A manifest, checked against the schema's rules (shared/adapter.schema.json); raises ValueError."""
    if not isinstance(m, dict) or not isinstance(m.get("name"), str) or not NAME.fullmatch(m["name"]):
        raise ValueError("adapter.json has no good \"name\"")
    if m.get("interface") != constants.ADAPTER_INTERFACE:
        raise ValueError(f"interface {m.get('interface')!r}; this server has interface {constants.ADAPTER_INTERFACE}")
    if not isinstance(m.get("version"), str):
        raise ValueError("adapter.json has no \"version\"")
    for k in ("title", "author", "source", "description"):
        if k in m and not isinstance(m[k], str):
            raise ValueError(f"\"{k}\" is not text")
    surfaces = m.get("surfaces")
    if not isinstance(surfaces, list) or not surfaces:
        raise ValueError("adapter.json has no \"surfaces\"")
    for i, s in enumerate(surfaces):
        check_surface(s, i)
    ids = [s["id"] for s in surfaces]
    if len(set(ids)) != len(ids):
        raise ValueError(f"the surfaces' ids repeat: {ids}")
    tuning.parse(m.get("context"), "adapter", "\"context\"")  # raises for a key that is not the adapter's


def load(folder, builtin):
    """One adapter from its folder: its Package, with the adapter object, or with the error that stopped it."""
    p = Package(os.path.basename(folder), folder, builtin)
    try:
        with open(os.path.join(folder, "adapter.json"), encoding="utf-8") as f:
            m = json.load(f)
        if isinstance(m, dict) and isinstance(m.get("name"), str) and NAME.fullmatch(m["name"]):
            p.name, p.manifest = m["name"], m
        check(m)
        p.surfaces = m["surfaces"]
        package = f"echofox_adapter_{re.sub(r'\W', '_', p.name)}"
        spec = importlib.util.spec_from_file_location(package, os.path.join(folder, "adapter.py"),
                                                      submodule_search_locations=[folder])
        module = importlib.util.module_from_spec(spec)
        for name in [n for n in sys.modules if n == package or n.startswith(package + ".")]:
            del sys.modules[name]  # an adapter that loads again gets its modules fresh
        sys.modules[package] = module
        spec.loader.exec_module(module)
        classes = [c for c in vars(module).values() if isinstance(c, type) and issubclass(c, adapters.Adapter)
                   and c is not adapters.Adapter and c.__module__ == module.__name__]
        if len(classes) != 1:
            raise ValueError(f"adapter.py has {len(classes)} subclasses of adapters.Adapter; it needs one")
        p.adapter = classes[0]()
        p.adapter.name = p.name
        p.adapter.manifest = m
    except Exception as e:  # a broken adapter stops only itself
        p.error = f"{type(e).__name__}: {e}"
        log.error("adapter %s (%s): %s", p.name, folder, p.error)
    return p


_packages, _signature = None, None
_lock = threading.Lock()  # packages() runs in worker threads, sometimes two at once


def _folders():
    """[(folder, builtin)] of every adapter folder, built-in first, and their signature: every file of every adapter
    folder with the time it changed."""
    out, sig = [], []
    for root, builtin in ((BUILTIN, True), (user_dir(), False)):
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for n in names:
            folder = os.path.join(root, n)
            if not os.path.isfile(os.path.join(folder, "adapter.json")):
                continue
            out.append((folder, builtin))
            for d, dirs, files in os.walk(folder):
                dirs[:] = [x for x in dirs if x != "__pycache__"]
                for f in sorted(files):
                    if f.endswith((".py", ".json")):
                        with contextlib.suppress(OSError):
                            sig.append((os.path.join(d, f), os.stat(os.path.join(d, f)).st_mtime_ns))
    return out, tuple(sig)


def packages():
    """Every adapter found, by name; a user adapter replaces a built-in one of the same name. The adapters load again
    when a file of an adapter folder changes, so a new or edited adapter works without a restart of the server."""
    global _packages, _signature
    with _lock:
        folders, sig = _folders()
        if _packages is None or sig != _signature:
            found = {}
            for folder, builtin in folders:
                p = load(folder, builtin)
                if p.name in found and not builtin:
                    log.info("adapter %s from %s replaces the built-in one", p.name, folder)
                found[p.name] = p
            _packages, _signature = found, sig
        return _packages


def enabled(names):
    """The working packages among `names` (the config's enabled ones), in the order of the packages."""
    return [p for n, p in packages().items() if n in set(names or ()) and p.adapter is not None]


def context_defaults(name):
    """The defaults of adapter `name`'s context settings, from its manifest, by name ({} for none or no adapter)."""
    p = packages().get(name) if name else None
    return tuning.parse((p.manifest if p else {}).get("context"), "adapter", "\"context\"") if p and not p.error else {}
