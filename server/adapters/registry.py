"""The adapter plugins: the built-in ones in server/plugins/, the user's in ~/Library/Application Support/Local Voice/
adapters/ ($LOCAL_VOICE_PLUGINS). Each plugin is a folder with:
  adapter.json  its manifest: {"name", "version", "author", "source", "description", "interface": 2,
                "apps": [bundle ids it reads the focus of], "electronTree": the app builds its accessibility tree only
                on request (Electron), "reads": [the files it reads],
                "screen": [what of the screen the client sends for its apps: "lists", the rows of the lists in the
                focused window (a messenger's messages); see FOCUS in adapters/__init__.py]}
  adapter.py    a module with one class that subclasses adapters.Adapter; the folder is a package, so adapter.py can
                import the plugin's other modules (from . import helpers)
A plugin the user puts in the folder is theirs to trust: the server checks only that the manifest reads, that its
interface is this one, and that the module has its class (Alex's decision, 2026-10-15). A user plugin with the name of
a built-in one replaces it. A plugin works only when the config enables it (adapters: {"<name>": {"enabled": true}}).
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

INTERFACE = 2  # 2: any app, not only sessions with agents: focus and hints, about, from, terms, source, details
SCREEN = {"lists"}  # what of the screen a plugin can ask the client for (its manifest's "screen")
BUILTIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugins")
log = logging.getLogger("gemma_voice")


def user_dir():
    return os.environ.get("LOCAL_VOICE_PLUGINS") or constants.path(constants.PLUGINS)


@dataclass
class Plugin:
    name: str
    dir: str
    builtin: bool
    manifest: dict = field(default_factory=dict)
    adapter: object = None
    module: object = None
    error: str = None

    def info(self, enabled):
        """For the app: what the plugin is, says about itself, and whether it works."""
        m = self.manifest
        return {"name": self.name, "enabled": self.name in enabled and self.adapter is not None, "builtin": self.builtin,
                "version": m.get("version"), "author": m.get("author"), "source": m.get("source"),
                "description": m.get("description"), "apps": m.get("apps") or [],
                "electronTree": bool(m.get("electronTree")), "reads": m.get("reads") or [],
                "screen": m.get("screen") or [], "error": self.error}


def load(folder, builtin):
    """One plugin from its folder: the Plugin, with its adapter, or with the error that stopped it."""
    p = Plugin(os.path.basename(folder), folder, builtin)
    try:
        with open(os.path.join(folder, "adapter.json"), encoding="utf-8") as f:
            m = json.load(f)
        if not isinstance(m, dict) or not isinstance(m.get("name"), str) or not re.fullmatch(r"[\w.-]+", m["name"]):
            raise ValueError("adapter.json has no good \"name\"")
        p.name, p.manifest = m["name"], m
        if m.get("interface") != INTERFACE:
            raise ValueError(f"interface {m.get('interface')!r}; this server has interface {INTERFACE}")
        if not all(isinstance(a, str) for a in m.get("apps") or []):
            raise ValueError("\"apps\" is not a list of bundle ids")
        unknown = [s for s in m.get("screen") or [] if s not in SCREEN]
        if unknown:
            raise ValueError(f"\"screen\" has {unknown}; the client sends only {sorted(SCREEN)}")
        package = f"lv_plugin_{re.sub(r'\W', '_', p.name)}"
        spec = importlib.util.spec_from_file_location(package, os.path.join(folder, "adapter.py"),
                                                      submodule_search_locations=[folder])
        module = importlib.util.module_from_spec(spec)
        for name in [n for n in sys.modules if n == package or n.startswith(package + ".")]:
            del sys.modules[name]  # a plugin that loads again gets its modules fresh
        sys.modules[package] = module
        spec.loader.exec_module(module)
        p.module = module
        classes = [c for c in vars(module).values() if isinstance(c, type) and issubclass(c, adapters.Adapter)
                   and c is not adapters.Adapter and c.__module__ == module.__name__]
        if len(classes) != 1:
            raise ValueError(f"adapter.py has {len(classes)} subclasses of adapters.Adapter; it needs one")
        p.adapter = classes[0]()
        p.adapter.name = p.name
        p.adapter.manifest = m
    except Exception as e:  # a broken plugin stops only itself
        p.error = f"{type(e).__name__}: {e}"
        log.error("adapter plugin %s (%s): %s", p.name, folder, p.error)
    return p


_plugins, _signature = None, None
_lock = threading.Lock()  # plugins() runs in worker threads, sometimes two at once


def _folders():
    """[(folder, builtin)] of every plugin folder, built-in first, and their signature: every file of every plugin
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


def plugins():
    """Every plugin found, by name; a user plugin replaces a built-in one of the same name. The plugins load again when
    a file of a plugin folder changes, so a new or edited plugin works without a restart of the server."""
    global _plugins, _signature
    with _lock:
        folders, sig = _folders()
        if _plugins is None or sig != _signature:
            found = {}
            for folder, builtin in folders:
                p = load(folder, builtin)
                if p.name in found and not builtin:
                    log.info("adapter plugin %s from %s replaces the built-in one", p.name, folder)
                found[p.name] = p
            _plugins, _signature = found, sig
        return _plugins


def enabled(names):
    """The working adapters among `names` (the config's enabled ones), in the order of the plugins."""
    return [p.adapter for n, p in plugins().items() if n in set(names or ()) and p.adapter is not None]
