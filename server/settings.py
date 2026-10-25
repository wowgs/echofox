"""The server's settings and the config file it shares with its clients.

The config, ~/.local-voice/config.json ($LOCAL_VOICE_CONFIG), version 3:
  {"version": 3, "model": "<name>", "language": "ru", "adapters": {"<plugin>": {"enabled": true}},
   "models": {"<name>": {"llamaServer": "http://127.0.0.1:8092", "launchd": "<label>", "prompt": "…", "options": {…}}},
   "silenceStopSeconds": 60, "saveRecordings": true, "fillers": {"ru": ["э", "мм"]},
   "server": {"host": …, "port": …, "pieceSeconds": …, …}}
language and silenceStopSeconds: the clients'; the server does not read them. adapters: the adapter plugins that
work (adapters/registry.py); none: the base mode, dictation without context; an adapter's entry may also set chatHistoryTokenBudget and chatTermsTokenBudget for its
own context (tuning.ADAPTER_KNOBS). fillers: the hesitation sounds taken out of the text, by language
(fillers.py has the built-in lists; an empty list turns it off for that language). models: the registry; each a llama.cpp
llama-server, started and stopped through its launchd agent. Only the model chosen in the menus ("model") is in
memory; a name not in the registry, or none: no model in memory. A setting's value: the command line, then the
file, then the default (the test server keeps its own port, log and metrics). The server watches the file:
  "recording" settings take effect at the next recording;
  "model" settings (models) take effect after the running recording;
  "process" settings (host, port) end the process after the running recording; launchd starts it again.
"""
import argparse
import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Callable

import constants
import metrics
import tuning
from dictation import MAX_PROMPT

log = logging.getLogger("gemma_voice")
CONFIG_CHECK_S = 2  # how often the file is looked at
MODEL_DEFAULT = {"gemma-e4b": {"llamaServer": f"http://{constants.HOST}:{constants.WORKING_LLAMA_PORT}",
                               "launchd": constants.LLAMA_LABEL}}


@dataclass(frozen=True)
class Setting:
    key: str                 # in the config file
    name: str                # in the code; with a command-line flag if `flag`
    kind: type
    ok: Callable
    default: object
    level: str               # "recording", "model" or "process"
    section: str = None      # "server", or None: at the top of the file
    flag: bool = True
    help: str = ""


def good_model(m):
    """A registry entry: llamaServer, and optionally launchd, prompt and options that tuning accepts."""
    if not isinstance(m, dict) or not str(m.get("llamaServer", "")).startswith("http") \
            or not isinstance(m.get("launchd", ""), str) or not isinstance(m.get("prompt", ""), str) \
            or len(m.get("prompt", "")) > MAX_PROMPT:
        return False
    try:
        tuning.parse_options(m.get("options"))
        return True
    except ValueError:
        return False


def good_adapters(v):
    def good(e):
        try:
            tuning.adapter_options(e)
            return True
        except ValueError:
            return False
    return all(isinstance(k, str) and isinstance(e, dict) and isinstance(e.get("enabled", False), bool) and good(e)
               for k, e in v.items())


def good_fillers(v):
    return all(isinstance(k, str) and isinstance(w, list) and all(isinstance(x, str) and x.strip() for x in w)
               for k, w in v.items())


SETTINGS = [
    Setting("host", "host", str, bool, constants.HOST, "process", "server", help="where the server listens"),
    Setting("port", "port", int, lambda v: 0 < v < 65536, constants.WORKING_PORT, "process", "server",
            help="the server's port"),
    Setting("models", "models", dict, lambda v: bool(v) and all(good_model(m) for m in v.values()), MODEL_DEFAULT,
            "model", flag=False),
    Setting("saveRecordings", "save_recordings", bool, lambda v: True, True, "recording", flag=False),
    Setting("adapters", "adapters", dict, good_adapters, {}, "recording", flag=False),
    Setting("fillers", "fillers", dict, good_fillers, {}, "recording", flag=False),
    Setting("recordings", "recordings", str, bool, constants.RECORDINGS, "recording", "server",
            help="where the recordings are saved"),
    Setting("metrics", "metrics", str, bool, constants.METRICS, "recording", "server", help="the metrics file"),
    *(Setting(k.key, k.name, k.kind, k.ok, k.default, "recording", "server", flag=k.kind is not bool, help=k.help)
      for k in tuning.KNOBS if k.server),
]
BY_KEY = {s.key: s for s in SETTINGS}


def schema(st):
    """The settings a client may show and change (info's "settings"), with the values in force: the knobs
    (tuning.Knob.schema) and the recordings. The models, the adapters and the fillers have pages of their own."""
    out = [k.schema(getattr(st, k.name, k.default)) for k in tuning.KNOBS]
    save, folder = BY_KEY["saveRecordings"], BY_KEY["recordings"]
    out.append({"key": save.key, "group": "recording", "kind": "boolean", "default": save.default,
                **({"value": st.save_recordings} if getattr(st, "save_recordings", save.default) != save.default else {}),
                "where": ["config"], "help": "save each recording, its pieces and their texts"})
    out.append({"key": folder.key, "group": "recording", "kind": "string", "default": folder.default,
                **({"value": st.recordings} if getattr(st, "recordings", None) not in (None, constants.path(folder.default))
                   else {}),
                "where": ["server"], "help": folder.help})
    return out


def config_file():
    return os.environ.get("LOCAL_VOICE_CONFIG") or constants.path(constants.CONFIG)


def add_flags(parser):
    """A command-line flag for each setting that has one: --piece-seconds and so on."""
    for s in SETTINGS:
        if s.flag:
            parser.add_argument("--" + s.name.replace("_", "-"), type=s.kind, dest=s.name,
                                help=f"{s.help} (default {s.default})" if s.help else None)


def _checked(s, value):
    """The value of a setting, of its kind and in its range; raises ValueError otherwise."""
    if s.key in tuning.BY_KEY:
        return tuning.check(tuning.BY_KEY[s.key], value)
    if s.kind is dict:
        if isinstance(value, dict) and s.ok(value):
            return value
    elif s.kind is bool:
        if isinstance(value, bool):
            return value
    elif not isinstance(value, bool):
        try:
            v = s.kind(value)
            if s.ok(v) and (s.kind is not int or value == v):
                return v
        except (TypeError, ValueError):
            pass
    raise ValueError(f"{s.key} = {value!r} is not valid")


def file_settings(path):
    """The settings in the config file, checked: {key: value}. A wrong key or value is logged and left out; None if
    the file cannot be read or is of another version."""
    try:
        with open(path, encoding="utf-8") as f:
            c = json.load(f) or {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.error("config %s: cannot read it (%s); the server keeps its settings", path, e)
        return None
    if not isinstance(c, dict) or c.get("version") != constants.CONFIG_VERSION:
        log.error("config %s: version %s, the server reads version %d", path,
                  c.get("version") if isinstance(c, dict) else None, constants.CONFIG_VERSION)
        return None
    server = c.get("server") if isinstance(c.get("server"), dict) else {}
    for key in server:
        if BY_KEY.get(key) is None or BY_KEY[key].section != "server":
            log.error("config %s: server.%s is not a setting; known: %s", path, key,
                      ", ".join(s.key for s in SETTINGS if s.section == "server"))
    out = {}
    for s in SETTINGS:
        source = server if s.section == "server" else c
        if s.key not in source:
            continue
        try:
            out[s.key] = _checked(s, source[s.key])
        except ValueError as e:
            log.error("config %s: %s%s; it is left out", path, "server." if s.section else "", e)
    return out


def resolve(cli, from_file):
    """The settings in force: the command line, then the file, then the defaults: {key: value}. A command-line value
    out of range raises ValueError."""
    out = {}
    for s in SETTINGS:
        given = getattr(cli, s.name, None) if s.flag else None
        out[s.key] = _checked(s, given) if given is not None else from_file.get(s.key, s.default)
    return out


def recording_settings(now, into=None):
    """The "recording" settings where the code reads them: a namespace by name (protocol.handle gets it). The
    metrics file is set apart (apply)."""
    st = into if into is not None else argparse.Namespace()
    for s in SETTINGS:
        if s.level == "recording":
            setattr(st, s.name, now[s.key])
    st.recordings = constants.path(now["recordings"])
    st.adapters = [name for name, e in now["adapters"].items() if e.get("enabled")]
    st.adapter_options = {name: tuning.adapter_options(e) for name, e in now["adapters"].items()}
    return st


def apply(now, into=None):
    """The settings in force for the running server: the recording settings' namespace, and the metrics file."""
    metrics.configure(now["metrics"])
    return recording_settings(now, into)


def selected_model(config_path, models):
    """The model chosen in the menus ("model" in the config), if this server has it; None otherwise."""
    try:
        with open(config_path, encoding="utf-8") as f:
            name = (json.load(f) or {}).get("model")
    except (OSError, ValueError, AttributeError):
        return None
    return name if isinstance(name, str) and name in models.entries else None


def migrate(path):
    """Version 2 → 3: adapters became plugins that the config enables. A version-2 file had the built-in adapters
    working, so the upgrade enables the built-in plugins; a new config has none (the base mode). A plugin that asks
    for the screen's content (its manifest's "screen": a messenger's messages) is never enabled for the user: they
    turn it on themselves. The file keeps its order."""
    try:
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(c, dict) or c.get("version") != 2:
        return
    import adapters  # here, not at the top: adapters does not need the settings
    builtin = {n: {"enabled": True} for n, p in adapters.registry.plugins().items()
               if p.builtin and not p.manifest.get("screen")}
    out = {}
    for k, v in c.items():
        out[k] = constants.CONFIG_VERSION if k == "version" else v
        if k == "language" or (k == "model" and "language" not in c):
            out["adapters"] = builtin
    out.setdefault("adapters", builtin)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    log.info("config %s: version 2 → 3; the built-in adapters are enabled: %s", path, ", ".join(builtin) or "none")


class ConfigWatcher:
    """Applies changes of the config file (see the levels above) and, with `follow`, keeps in memory only the model
    chosen in the menus. `current`: the settings in force; `st`: the recording settings' namespace."""

    def __init__(self, path, cli, models, st, current, stop, follow=True):
        self.path, self.cli, self.models, self.st, self.current, self.stop = path, cli, models, st, current, stop
        self.follow, self.chosen, self.chosen_known = follow, None, False
        self.seen = self._mtime()  # before the first model loads, so a change during that load is not lost

    def _mtime(self):
        try:
            return os.stat(self.path).st_mtime_ns
        except OSError:
            return None

    async def follow_selection(self):
        """After the running recording, only the menu's model stays in memory."""
        now = selected_model(self.path, self.models)
        if self.chosen_known and now == self.chosen:
            return
        async with self.models.recording:
            log.info("the menu's model is %s: only it stays in memory", now or "not on this server")
            try:
                await self.models.activate(now)
                self.chosen, self.chosen_known = now, True
            except Exception:
                log.exception("cannot make %s the model in memory", now)

    async def check(self):
        """One look at the file; True while the server goes on."""
        mtime = self._mtime()
        if mtime != self.seen:
            self.seen = mtime
            from_file = file_settings(self.path)
            if from_file is not None:
                try:
                    now = resolve(self.cli, from_file)
                except ValueError as e:
                    log.error("config %s: %s", self.path, e)
                    now = None
                changed = {k for k in BY_KEY if now and now[k] != self.current[k]}
                if changed:
                    levels = {BY_KEY[k].level for k in changed}
                    log.info("config %s changed: %s", self.path,
                             ", ".join(f"{k} {self.current[k]!r} -> {now[k]!r}" for k in sorted(changed)))
                    async with self.models.recording:  # after the running recording
                        if "process" in levels:
                            log.info("host or port changed: the server ends; launchd starts it again")
                            if not self.stop.done():
                                self.stop.set_result(None)
                            return False
                        apply(now, self.st)
                        if "model" in levels:
                            self.models.reconfigure(now["models"])
                            self.chosen_known = False  # start the chosen model again, with the new entries
                            log.info("models: %s", ", ".join(now["models"]))
                        self.current.clear()
                        self.current.update(now)
        if self.follow:
            await self.follow_selection()
        return True

    async def run(self):
        if self.follow:
            await self.follow_selection()
        while await self.check():
            await asyncio.sleep(CONFIG_CHECK_S)
