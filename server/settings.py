"""The server's settings and the config file it shares with its clients.

The config, ~/.echofox/config.json ($ECHOFOX_CONFIG), version 7. Each setting has one owner
(docs/design.md, "Settings"), and the user's change of it is at that owner, in this file only; the knobs
that are constants (tuning.py) are not in it:
  {"version": 7,
   "model": "<name>", "language": "ru", "microphone": …, "dictationKey": …, "silenceStopSeconds": 60,   (the app's)
   "models": {"<name>": {"catalog": "<catalog id>", "llamaServer": "http://127.0.0.1:8092", "launchd": "<label>",
                         "prompt": "…", "options": {the model's knobs}}},
   "adapters": {"<plugin>": {"enabled": true, the adapter's knobs: over its manifest's defaults}},
   "languages": {"<code>": {"notes": ["…"], "fillers": ["э", "мм"]}},
   "server": {"host": …, "port": …, "recordings": …, "saveRecordings": true, "labeled": …, "maxRecordingMinutes": 30}}
The app's settings the server does not read. adapters: the adapter plugins that work (adapters/registry.py); none:
the base mode, dictation without context. languages: changes to the language table (languages.json; an empty list
turns a list off). models: the registry; each a llama.cpp llama-server, started and stopped through its launchd
agent, with its catalog entry (catalog.json). Only the model chosen in the menus ("model") is in memory; a name not in
the registry, or none: no model in memory. A setting's value: the file's, else the default (the test server has a
config file of its own: test_server.sh). The server watches the file:
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

import catalog
import constants
import metrics
import tuning
from dictation import MAX_PROMPT

log = logging.getLogger("gemma_voice")
CONFIG_CHECK_S = 2  # how often the file is looked at
MODEL_DEFAULT = {"gemma-e4b": {"catalog": catalog.DEFAULT,
                               "llamaServer": f"http://{constants.HOST}:{constants.WORKING_LLAMA_PORT}",
                               "launchd": constants.LLAMA_LABEL}}


@dataclass(frozen=True)
class Setting:
    key: str                 # in the config file
    name: str                # in the code
    kind: type
    ok: Callable
    default: object
    level: str               # "recording", "model" or "process"
    section: str = None      # "server", or None: at the top of the file
    title: str = ""          # for the settings window, if it shows the setting
    help: str = ""


def good_model(m):
    """A registry entry: llamaServer, and optionally its catalog entry, its variant (one of the catalog entry's),
    launchd, prompt and options (the model's knobs only)."""
    if not isinstance(m, dict) or not str(m.get("llamaServer", "")).startswith("http") \
            or not isinstance(m.get("launchd", ""), str) or not isinstance(m.get("prompt", ""), str) \
            or len(m.get("prompt", "")) > MAX_PROMPT or m.get("catalog", catalog.DEFAULT) not in catalog.entries():
        return False
    if "variant" in m and catalog.variant(m)[1] is None:
        return False
    try:
        tuning.parse(m.get("options"), "model")
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


def good_languages(v):
    """{code: {"notes": [lines], "fillers": [sounds]}}, either list optional."""
    def strings(w):
        return isinstance(w, list) and all(isinstance(x, str) and x.strip() for x in w)
    return all(isinstance(k, str) and isinstance(e, dict) and set(e) <= {"notes", "fillers"}
               and all(strings(w) for w in e.values()) for k, e in v.items())


SETTINGS = [
    Setting("host", "host", str, bool, constants.HOST, "process", "server"),
    Setting("port", "port", int, lambda v: 0 < v < 65536, constants.WORKING_PORT, "process", "server"),
    Setting("models", "models", dict, lambda v: bool(v) and all(good_model(m) for m in v.values()), MODEL_DEFAULT,
            "model"),
    Setting("adapters", "adapters", dict, good_adapters, {}, "recording"),
    Setting("languages", "languages", dict, good_languages, {}, "recording"),
    Setting("saveRecordings", "save_recordings", bool, lambda v: True, True, "recording", "server",
            "Save recordings", "Keeps each recording and its text. Private dictations are never saved."),
    Setting("recordings", "recordings", str, bool, constants.RECORDINGS, "recording", "server",
            "Recordings folder", ""),
    Setting("labeled", "labeled", str, bool, constants.LABELED, "recording", "server",
            "Labels folder", "Holds the pieces that you labeled."),
    Setting("modelsFolder", "models_folder", str, bool, constants.MODELS_FOLDER, "model", "server",
            "Models folder", "The folder for the model files."),
    Setting("metrics", "metrics", str, bool, constants.METRICS, "recording", "server"),
    *(Setting(k.key, k.name, k.kind, k.ok, k.default, "recording", "server") for k in tuning.KNOBS
      if k.owner == "server" and k.user),
]
BY_KEY = {s.key: s for s in SETTINGS}


def model_defaults(entry):
    """The defaults of the model's knobs and its constants: its catalog entry's options, by name."""
    return tuning.parse(catalog.of(entry).get("options"), "model", "catalog options", constants_too=True)


def schema(st, model_entry=None):
    """The settings a client may show and change (info's "settings"), each with its owner, its owner's default and the
    value in force: the server's settings and its storage; the settings of `model_entry` (the menu's model), its
    catalog's defaults and its options; the adapters' settings with their fallbacks (each adapter's own defaults are
    in info's adapters, "context"). The constants are not settings and are not here."""
    defaults = model_defaults(model_entry) if model_entry else {}
    own = tuning.parse((model_entry or {}).get("options"), "model") if model_entry else {}
    out = []
    for k in (k for k in tuning.KNOBS if k.user):
        if k.owner == "server":
            out.append(k.schema(k.default, getattr(st, k.name, k.default)))
        elif k.owner == "model":
            d = defaults.get(k.name, k.default)
            out.append(k.schema(d, own.get(k.name, d)))
        else:  # an adapter's: the fallback (each adapter's own defaults are in info's adapters, "context")
            out.append(k.schema(k.default, k.default))
    for key, kind in (("saveRecordings", "boolean"), ("recordings", "string"), ("labeled", "string"),
                      ("modelsFolder", "string")):
        s = BY_KEY[key]
        now = getattr(st, s.name, s.default)
        shown = constants.path(s.default) if kind == "string" else s.default
        out.append({"key": key, "owner": "server", "group": "storage", "kind": kind, "title": s.title,
                    "default": s.default, **({"value": now} if now not in (s.default, shown) else {}),
                    "help": s.help})
    return out


def config_file():
    return os.environ.get("ECHOFOX_CONFIG") or constants.path(constants.CONFIG)


def with_defaults(models):
    """The config's registry with the default entries' fields under an entry of the same name: an app that writes only
    a variant of the default model ({"gemma-e4b": {"variant": "q4_0"}}) writes a whole entry."""
    if not isinstance(models, dict):
        return models
    return {n: {**MODEL_DEFAULT[n], **e} if n in MODEL_DEFAULT and isinstance(e, dict) else e for n, e in models.items()}


def _checked(s, value):
    """The value of a setting, of its kind and in its range; raises ValueError otherwise."""
    if s.key == "models":
        value = with_defaults(value)
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


def resolve(from_file):
    """The settings in force: the file's, then the defaults: {key: value}."""
    return {s.key: from_file.get(s.key, s.default) for s in SETTINGS}


def recording_settings(now, into=None):
    """The "recording" settings where the code reads them: a namespace by name (protocol.handle gets it). The
    metrics file is set apart (apply)."""
    st = into if into is not None else argparse.Namespace()
    for s in SETTINGS:
        if s.level == "recording":
            setattr(st, s.name, now[s.key])
    st.recordings = constants.path(now["recordings"])
    st.labeled = constants.path(now["labeled"])
    st.models_folder = constants.path(now["modelsFolder"])
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
    """The config brought to this version, step by step (migrate_2 to migrate_6)."""
    migrate_2(path)
    migrate_3(path)
    migrate_4(path)
    migrate_5(path)
    migrate_6(path)


def migrate_6(path):
    """Version 6 → 7: "adapterDefaults", the adapters' values for every adapter, is gone: an adapter's defaults are
    its manifest's, and the user's change is in its entry. Each of its values goes to every adapter's entry that has
    none of its own, so nothing changes. The file keeps its order."""
    try:
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(c, dict) or c.get("version") != 6:
        return
    shared = c.pop("adapterDefaults", None)
    moved = []
    if isinstance(shared, dict):
        for name, entry in (c.get("adapters") or {}).items():
            if isinstance(entry, dict):
                for k, v in shared.items():
                    if k not in entry:
                        entry[k] = v
                        moved.append(f"adapters.{name}.{k}={v!r}")
    c["version"] = 7
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(c, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    log.info("config %s: version 6 → 7; adapterDefaults %s", path,
             f"moved to the adapters: {', '.join(moved)}" if moved else "was empty" if shared is not None else "none")


# Version 5 → 6: the knobs that became constants (tuning.py) leave the file; contextAsSystem is gone; the
# recording's limit is in minutes.
GONE_IN_6 = ("pieceSeconds", "cutSearchSeconds", "cutWhileSpeaking", "minLastPieceSeconds", "minSpeechSeconds",
             "warmText", "maxTokensPerSpeechSecond", "contextAsSystem")


def migrate_5(path):
    """Version 5 → 6 (GONE_IN_6): the constants leave the section "server" and the models' options;
    maxRecordingSeconds becomes maxRecordingMinutes. The file keeps its order."""
    try:
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(c, dict) or c.get("version") != 5:
        return
    gone = []
    server = c.get("server") if isinstance(c.get("server"), dict) else {}
    for k in GONE_IN_6:
        if k in server:
            gone.append(f"server.{k}={server.pop(k)!r}")
    if "maxRecordingSeconds" in server:
        s = server.pop("maxRecordingSeconds")
        if isinstance(s, (int, float)) and not isinstance(s, bool) and s > 0:
            server["maxRecordingMinutes"] = round(s / 60, 2)
        gone.append(f"server.maxRecordingSeconds={s!r} (now maxRecordingMinutes)")
    for name, entry in (c.get("models") or {}).items():
        options = entry.get("options") if isinstance(entry, dict) else None
        if isinstance(options, dict):
            for k in GONE_IN_6:
                if k in options:
                    gone.append(f"models.{name}.options.{k}={options.pop(k)!r}")
            if not options:
                del entry["options"]
    c["version"] = 6
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(c, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    log.info("config %s: version 5 → 6; gone: %s", path, ", ".join(gone) or "nothing")


# Version 4 → 5: the settings that were a second way to set the same thing. The length of the text and the drop of
# the model's own text are one knob (maxTokensPerSpeechSecond); speech is only Silero VAD's (the loudness threshold
# is gone); a context budget of 0 is not the adapter's switch.
GONE_IN_5 = ("thresholdDb", "speechAboveNoiseDb", "maxCharsPerSpeechSecond", "outputTokensPerSecond",
             "outputTokensBase", "maxOutputTokens")


def migrate_4(path):
    """Version 4 → 5 (GONE_IN_5): the gone settings leave the file; an adapter whose chatHistoryTokenBudget is 0 is
    turned off instead, and a 0 in adapterDefaults leaves the file. The file keeps its order."""
    try:
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(c, dict) or c.get("version") != 4:
        return
    gone = []

    def drop(d, keys, where):
        for k in keys:
            if isinstance(d, dict) and k in d:
                gone.append(f"{where}.{k}={d.pop(k)!r}")

    drop(c.get("server"), GONE_IN_5, "server")
    for name, entry in (c.get("models") or {}).items():
        if isinstance(entry, dict):
            drop(entry.get("options"), GONE_IN_5, f"models.{name}.options")
            if isinstance(entry.get("options"), dict) and not entry["options"]:
                del entry["options"]
    for name, entry in (c.get("adapters") or {}).items():
        if isinstance(entry, dict) and entry.get("chatHistoryTokenBudget") == 0:
            del entry["chatHistoryTokenBudget"]
            entry["enabled"] = False
            gone.append(f"adapters.{name}.chatHistoryTokenBudget=0 (the adapter is turned off instead)")
    if isinstance(c.get("adapterDefaults"), dict) and c["adapterDefaults"].get("chatHistoryTokenBudget") == 0:
        drop(c["adapterDefaults"], ("chatHistoryTokenBudget",), "adapterDefaults")
    c["version"] = 5
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(c, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    log.info("config %s: version 4 → 5; gone: %s", path, ", ".join(gone) or "nothing")


def migrate_3(path):
    """Version 3 → 4: each setting has its owner (docs/design.md, "Settings"). "fillers" go to the languages;
    "saveRecordings" and "labeled" to the section "server"; a model's knob in the section "server" (the length of
    the text) goes to each model's options; a model's options keep only the model's knobs: an adapter's knob goes to
    each adapter's entry that has no value of its own (the model's value was every adapter's), a server's knob to the
    section "server" if it has none; a model gets its catalog entry. The file keeps its order."""
    try:
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(c, dict) or c.get("version") != 3:
        return
    server = dict(c.get("server") or {})
    adapters_ = {k: dict(v) for k, v in (c.get("adapters") or {}).items() if isinstance(v, dict)}
    langs = {k: dict(v) for k, v in (c.get("languages") or {}).items() if isinstance(v, dict)}
    for code, words in (c.get("fillers") or {}).items():
        langs.setdefault(code, {})["fillers"] = words
    for key in ("saveRecordings", "labeled"):
        if key in c:
            server.setdefault(key, c[key])
    moved = {}  # the server section's knobs that are now a model's: every model's value, where it has none
    for key in list(server):
        knob = tuning.BY_KEY.get(key)
        if knob is not None and knob.owner != "server":
            moved[key] = server.pop(key)
    models = {}
    for name, entry in (c.get("models") or {}).items():
        entry = dict(entry)
        entry.setdefault("catalog", catalog.DEFAULT)
        kept = {k: v for k, v in moved.items() if tuning.BY_KEY[k].owner == "model"}
        for key, value in (entry.get("options") or {}).items():
            knob = tuning.BY_KEY.get(key)
            if knob is None:
                log.warning("config %s: models.%s.options.%s is not a setting: dropped", path, name, key)
            elif knob.owner == "model":
                kept[key] = value
            elif knob.owner == "adapter":
                for a in adapters_.values():
                    a.setdefault(key, value)
            else:
                server.setdefault(key, value)
        if kept:
            entry["options"] = kept
        else:
            entry.pop("options", None)
        models[name] = entry
    new = {"version": 4, "models": models, "adapters": adapters_, "server": server}
    out = {k: new.get(k, v) for k, v in c.items() if k not in ("fillers", "saveRecordings", "labeled")}
    if langs:
        out["languages"] = langs
    out.setdefault("server", server)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    log.info("config %s: version 3 → 4: each setting at its owner", path)


def migrate_2(path):
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
        out[k] = 3 if k == "version" else v
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

    def __init__(self, path, models, st, current, stop, follow=True):
        self.path, self.models, self.st, self.current, self.stop = path, models, st, current, stop
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
                now = resolve(from_file)
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
                            self.models.reconfigure(now["models"], constants.path(now["modelsFolder"]))
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
