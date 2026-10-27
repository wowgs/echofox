"""The server's settings and the config file it shares with its clients (docs/reference/2-config.md; its version is
constants.CONFIG_VERSION). Each setting has one owner (docs/design.md, "Settings"), and the user's change of it is at
that owner; the knobs that are constants (tuning.py) are not in the file. A setting's value: the file's, else the
default. The server reads the "server" section and the registries; the app's own settings it does not read.

The server watches the file (ConfigWatcher), and each setting has a level:
  "recording" settings take effect at the next recording;
  "model" settings (the model registry, the models folder) after the running recording;
  "process" settings (host, port) end the process after the running recording; the app starts it again.
"""
import argparse
import asyncio
import json
import logging
import os
import shutil
from dataclasses import dataclass
from typing import Callable

import catalog
import constants
import languages
import metrics
import tuning

log = logging.getLogger("gemma_voice")
MODEL_DEFAULT = {"gemma-e4b": {"catalog": catalog.DEFAULT,
                               "llamaServer": f"http://{constants.HOST}:{constants.WORKING_LLAMA_PORT}"}}


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
    folder: bool = False     # a folder's path: the settings window offers the system's folder panel


# The dict settings are read entry by entry and key by key (docs/design.md, "The config file over versions"): a key
# that this version does not know is left out with a warning (a newer EchoFox may have written it), a wrong value is
# left out with an error, and the rest of the entry and of the setting stays. `problem(text, known)` logs it.

def _knobs(raw, owner, where, problem):
    """An entry's knobs of `owner` (a model's options, an adapter's budgets), each checked on its own: the file's
    keys and values that are good."""
    if not isinstance(raw, dict):
        problem(f"{where} is not an object", True)
        return {}
    known = {k.key for k in tuning.KNOBS if k.owner == owner and k.user}
    out = {}
    for key, value in raw.items():
        if key not in known:
            problem(f"{where}.{key} is not known to this version", False)
            continue
        try:
            tuning.parse({key: value}, owner, where)
            out[key] = value
        except ValueError as e:
            problem(f"{where}.{key}: {e}", True)
    return out


def clean_models(v, problem):
    """The registry's entries that can run: each needs llamaServer (http) and a catalog entry that exists (the default
    one if it names none). A wrong variant, prompt or option of an entry is left out, the entry stays. An entry of a
    default model's name gets that model's fields under its own (an app that writes only {"gemma-e4b": {"variant":
    "q4_0"}} writes a whole entry)."""
    out = {}
    for name, entry in v.items():
        where = f"models.{name}"
        if not isinstance(entry, dict):
            problem(f"{where} is not an object", True)
            continue
        m = {**MODEL_DEFAULT.get(name, {}), **entry}
        if not str(m.get("llamaServer", "")).startswith("http"):
            problem(f"{where}.llamaServer = {m.get('llamaServer')!r} is not an http URL; the model is left out", True)
            continue
        if m.get("catalog", catalog.DEFAULT) not in catalog.entries():
            problem(f"{where}.catalog = {m.get('catalog')!r} is not in the catalog; the model is left out", True)
            continue
        e = {k: m[k] for k in ("catalog", "llamaServer") if k in m}
        if "variant" in m:
            if catalog.variant(m)[1] is None:
                problem(f"{where}.variant = {m['variant']!r} is not a variant of {m.get('catalog', catalog.DEFAULT)}", True)
            else:
                e["variant"] = m["variant"]
        if "prompt" in m:
            if isinstance(m["prompt"], str) and len(m["prompt"]) <= constants.MAX_PROMPT:
                e["prompt"] = m["prompt"]
            else:
                problem(f"{where}.prompt is not a text of at most {constants.MAX_PROMPT} characters", True)
        if "options" in m:
            e["options"] = _knobs(m["options"], "model", f"{where}.options", problem)
        for key in set(m) - {"catalog", "llamaServer", "variant", "prompt", "options"}:
            problem(f"{where}.{key} is not known to this version", False)
        out[name] = e
    return out


def clean_adapters(v, problem):
    """Each adapter's "enabled" and budgets, each checked on its own."""
    out = {}
    for name, entry in v.items():
        where = f"adapters.{name}"
        if not isinstance(entry, dict):
            problem(f"{where} is not an object", True)
            continue
        e = {}
        if "enabled" in entry:
            if isinstance(entry["enabled"], bool):
                e["enabled"] = entry["enabled"]
            else:
                problem(f"{where}.enabled = {entry['enabled']!r} is not true or false", True)
        e.update(_knobs({k: x for k, x in entry.items() if k != "enabled"}, "adapter", where, problem))
        out[name] = e
    return out


def clean_languages(v, problem):
    """{code: {"notes": [lines], "fillers": [sounds]}}, each list on its own; "*" (every language) has only notes."""
    out = {}
    for code, entry in v.items():
        where = f"languages.{code}"
        if not isinstance(entry, dict):
            problem(f"{where} is not an object", True)
            continue
        e = {}
        for key, words in entry.items():
            if key not in ({"notes"} if code == languages.ALL else {"notes", "fillers"}):
                problem(f"{where}.{key} is not known to this version", False)
            elif isinstance(words, list) and all(isinstance(w, str) and w.strip() for w in words):
                e[key] = words
            else:
                problem(f"{where}.{key} is not a list of texts", True)
        out[code] = e
    return out


SETTINGS = [
    Setting("host", "host", str, bool, constants.HOST, "process", "server"),
    Setting("port", "port", int, lambda v: 0 < v < 65536, constants.WORKING_PORT, "process", "server"),
    Setting("models", "models", dict, clean_models, MODEL_DEFAULT,
            "model"),
    Setting("adapters", "adapters", dict, clean_adapters, {}, "recording"),
    Setting("languages", "languages", dict, clean_languages, {}, "recording"),
    Setting("saveRecordings", "save_recordings", bool, lambda v: True, True, "recording", "server",
            "Save recordings", "Private dictations are never saved."),
    Setting("recordings", "recordings", str, bool, constants.RECORDINGS, "recording", "server",
            "Recordings folder", "", folder=True),
    Setting("labeled", "labeled", str, bool, constants.LABELED, "recording", "server",
            "Labels folder", "", folder=True),
    Setting("modelsFolder", "models_folder", str, bool, constants.MODELS_FOLDER, "model", "server",
            "Models folder", "", folder=True),
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
    for s in SETTINGS:  # the storage settings: the ones with a title, which are not knobs
        if not s.title:
            continue
        kind = "boolean" if s.kind is bool else "folder" if s.folder else "string"
        now = getattr(st, s.name, s.default)
        shown = constants.path(s.default) if s.kind is str else s.default
        out.append({"key": s.key, "owner": "server", "group": "storage", "kind": kind, "title": s.title,
                    "default": s.default, **({"value": now} if now not in (s.default, shown) else {}),
                    "help": s.help})
    return out


def config_file():
    return os.environ.get("ECHOFOX_CONFIG") or constants.path(constants.CONFIG)


def _checked(s, value, problem):
    """The value of a setting, of its kind and in its range; raises ValueError otherwise. A dict setting is cleaned
    entry by entry (its `ok`), and `problem` hears of each part left out; a registry with no model that can run is
    not valid."""
    if s.key in tuning.BY_KEY:
        return tuning.check(tuning.BY_KEY[s.key], value)
    if s.kind is dict:
        if isinstance(value, dict):
            cleaned = s.ok(value, problem)
            if cleaned or s.key != "models":
                return cleaned
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
    """The settings in the config file, checked: {key: value}. Each key is read on its own (docs/design.md, "The config
    file over versions"): a key this version does not know is left out with a warning, a wrong value with an error,
    and the rest stays. A file of an older format is brought to this one first (migrate); one of a newer format is
    read the same way, key by key. None only if the file cannot be read: the server then keeps its settings."""
    try:
        with open(path, encoding="utf-8") as f:
            c = json.load(f) or {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.error("config %s: cannot read it (%s); the server keeps its settings", path, e)
        return None
    if not isinstance(c, dict):
        log.error("config %s: not a JSON object; the server keeps its settings", path)
        return None
    version = c.get("version")
    if isinstance(version, int) and version < constants.CONFIG_VERSION and version in MIGRATIONS:
        migrate(path)
        return file_settings(path)
    if version != constants.CONFIG_VERSION:
        log.warning("config %s: format %s, this server's is %d; it reads the keys it knows", path, version,
                    constants.CONFIG_VERSION)

    def problem(text, wrong):
        (log.error if wrong else log.warning)("config %s: %s; it is left out", path, text)

    server = c.get("server") if isinstance(c.get("server"), dict) else {}
    for key in server:
        if BY_KEY.get(key) is None or BY_KEY[key].section != "server":
            problem(f"server.{key} is not a setting of this version", False)
    out = {}
    for s in SETTINGS:
        source = server if s.section == "server" else c
        if s.key not in source:
            continue
        try:
            out[s.key] = _checked(s, source[s.key], problem)
        except ValueError as e:
            problem(f"{'server.' if s.section else ''}{e}", True)
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
    """The model chosen in the menus ("model" in the config), if this server has it; None if the config names another
    one. A config without "model", or no config yet (the first start), means the server's default: the registry's
    first model, the one a start message without a model gets."""
    entries = getattr(models, "entries", None) or {}
    try:
        with open(config_path, encoding="utf-8") as f:
            name = (json.load(f) or {}).get("model")
    except FileNotFoundError:
        name = None
    except (OSError, ValueError, AttributeError):
        return None
    if name is None:
        return next(iter(entries), None)
    return name if isinstance(name, str) and name in entries else None


def migrate(path):
    """The config file of an older format brought to this one (constants.CONFIG_VERSION): read once, taken through each
    step from its format on (MIGRATIONS, each one on the dict in memory), and written once, in the file's order, after
    the file as it was is copied to config.json.v<format>.bak. The only write of the server to the config. A file that
    cannot be read, or is of this format or a newer one, is left as it is."""
    try:
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(c, dict):
        return
    done = []
    while isinstance(c.get("version"), int) and c["version"] in MIGRATIONS:
        before = c["version"]
        c, what = MIGRATIONS[before](c, path)
        log.info("config %s: version %d → %d; %s", path, before, c["version"], what)
        done.append(before)
    if not done:
        return
    backup = f"{path}.v{done[0]}.bak"  # the file as the older version wrote it, which an older EchoFox still reads
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
        log.info("config %s: the format %d file kept as %s", path, done[0], backup)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(c, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def from_2(c, path):
    """Version 2 → 3: adapters became optional, and the config enables them. A version-2 file had the built-in adapters
    working, so the upgrade enables the built-in adapters; a new config has none (the base mode). An adapter that asks
    for the screen's content (its manifest's "screen") is never enabled for the user: they turn it on themselves."""
    import adapters  # here, not at the top: only this old step needs the adapters
    builtin = {n: {"enabled": True} for n, p in adapters.registry.packages().items()
               if p.builtin and not p.manifest.get("screen")}
    out = {}
    for k, v in c.items():
        out[k] = 3 if k == "version" else v
        if k == "language" or (k == "model" and "language" not in c):
            out["adapters"] = builtin
    out.setdefault("adapters", builtin)
    return out, f"the built-in adapters are enabled: {', '.join(builtin) or 'none'}"


def from_3(c, path):
    """Version 3 → 4: each setting has its owner (docs/design.md, "Settings"). "fillers" go to the languages;
    "saveRecordings" and "labeled" to the section "server"; a model's knob in the section "server" (the length of
    the text) goes to each model's options; a model's options keep only the model's knobs: an adapter's knob goes to
    each adapter's entry that has no value of its own (the model's value was every adapter's), a server's knob to the
    section "server" if it has none; a model gets its catalog entry."""
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
    return out, "each setting at its owner"


# Version 4 → 5: the settings that were a second way to set the same thing. The length of the text and the drop of
# the model's own text are one knob (maxTokensPerSpeechSecond); speech is only Silero VAD's (the loudness threshold
# is gone); a context budget of 0 is not the adapter's switch.
GONE_IN_5 = ("thresholdDb", "speechAboveNoiseDb", "maxCharsPerSpeechSecond", "outputTokensPerSecond",
             "outputTokensBase", "maxOutputTokens")


def from_4(c, path):
    """Version 4 → 5 (GONE_IN_5): the gone settings leave the file; an adapter whose chatHistoryTokenBudget is 0 is
    turned off instead, and a 0 in adapterDefaults leaves the file."""
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
    return c, f"gone: {', '.join(gone) or 'nothing'}"


# Version 5 → 6: the knobs that became constants (tuning.py) leave the file; contextAsSystem is gone; the
# recording's limit is in minutes.
GONE_IN_6 = ("pieceSeconds", "cutSearchSeconds", "cutWhileSpeaking", "minLastPieceSeconds", "minSpeechSeconds",
             "warmText", "maxTokensPerSpeechSecond", "contextAsSystem")


def from_5(c, path):
    """Version 5 → 6 (GONE_IN_6): the constants leave the section "server" and the models' options;
    maxRecordingSeconds becomes maxRecordingMinutes."""
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
    return c, f"gone: {', '.join(gone) or 'nothing'}"


def from_6(c, path):
    """Version 6 → 7: "adapterDefaults", the adapters' values for every adapter, is gone: an adapter's defaults are
    its manifest's, and the user's change is in its entry. Each of its values goes to every adapter's entry that has
    none of its own, so nothing changes."""
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
    return c, ("adapterDefaults " + (f"moved to the adapters: {', '.join(moved)}" if moved
                                     else "was empty" if shared is not None else "none"))


def from_7(c, path):
    """Version 7 → 8: the adapter "claude" is split by where its context comes from: "claude-code" (Claude Code
    transcripts) and "claude-chat" (Claude Desktop's chats, from the screen). Each gets a copy of the "claude" entry, so
    what was on stays on, with the same settings."""
    entries = c.get("adapters")
    old = entries.pop("claude", None) if isinstance(entries, dict) else None
    if isinstance(old, dict):
        for name in ("claude-code", "claude-chat"):
            entries.setdefault(name, dict(old))
    c["version"] = 8
    return c, ("adapters.claude became claude-code and claude-chat" if isinstance(old, dict) else "no adapters.claude")


def from_8(c, path):
    """Version 8 → 9: the recording's time limit is in seconds, as every other time of the settings:
    server.maxRecordingMinutes becomes maxRecordingSeconds."""
    server = c.get("server")
    m = server.pop("maxRecordingMinutes", None) if isinstance(server, dict) else None
    if isinstance(m, (int, float)) and not isinstance(m, bool):
        server["maxRecordingSeconds"] = round(m * 60)
    c["version"] = 9
    return c, (f"server.maxRecordingMinutes={m!r} became maxRecordingSeconds" if m is not None
               else "no server.maxRecordingMinutes")


# The defaults of version 9 that version 10 changed: a copy of them in a config is not the user's choice
V9_PROMPT = ("Transcribe the following speech segment in {LANGUAGE} + English terms into {LANGUAGE} + English terms "
             "text.\n\nFollow these specific instructions for formatting the answer:\n"
             "* Only output the transcription, with no newlines.\n"
             "* When transcribing numbers, write the digits, i.e. write 1.7 and not one point seven, and write 3 instead "
             "of three.\n"
             "* You transcribe speech of software engineers. Write product names, services and abbreviations in their "
             "official Latin spelling. Write English terms the way they are officially spelled.\n"
             "* Write it with punctuation and capital letters.")
V9_RU_NOTES = ["The speaker often uses the imperative mood (сделай, посмотри, проверь): keep it as spoken.",
               "The speech is Russian with English technical terms.",
               "Keep Russian words with Russian endings in Cyrillic, for example задеплоить, закоммитил."]


def from_9(c, path):
    """Version 9 → 10: the notes of every language ("*" in languages.json) say that the speech mixes in English terms,
    instead of the model's template and the Russian notes. A model's prompt or the Russian notes that are a copy of
    version 9's defaults go, so that the new defaults apply; a changed one stays."""
    gone = []
    for name, m in (c.get("models") or {}).items():
        if isinstance(m, dict) and m.get("prompt") == V9_PROMPT:
            del m["prompt"]
            gone.append(f"models.{name}.prompt")
    langs = c.get("languages")
    ru = langs.get("ru") if isinstance(langs, dict) else None
    if isinstance(ru, dict) and ru.get("notes") == V9_RU_NOTES:
        del ru["notes"]
        gone.append("languages.ru.notes")
        if not ru:
            del langs["ru"]
        if not langs:
            del c["languages"]
    c["version"] = 10
    return c, ("the copies of version 9's defaults went: " + ", ".join(gone)) if gone else "no copy of version 9's defaults"


def from_10(c, path):
    """Version 10 → 11: a model has no launchd agent any more (the server starts the llama-server of a model on this
    Mac as its child process), so its "launchd" goes."""
    gone = []
    for name, m in (c.get("models") or {}).items():
        if isinstance(m, dict) and "launchd" in m:
            del m["launchd"]
            gone.append(f"models.{name}.launchd")
    c["version"] = 11
    return c, ("removed " + ", ".join(gone)) if gone else "no model named a launchd agent"


MIGRATIONS = {2: from_2, 3: from_3, 4: from_4, 5: from_5, 6: from_6, 7: from_7, 8: from_8, 9: from_9,
              10: from_10}  # a file's version → its next step


class ConfigWatcher:
    """Applies changes of the config file (see the levels above) and, with `follow`, keeps in memory only the model
    chosen in the menus. `current`: the settings in force; `st`: the recording settings' namespace."""

    def __init__(self, path, models, st, current, stop, follow=True):
        self.path, self.models, self.st, self.current, self.stop = path, models, st, current, stop
        self.follow = follow
        self.seen = self._mtime()  # before the first model loads, so a change during that load is not lost
        self._select()

    def _select(self):
        """The menu's model, from this server's config file, kept in `models.selected`."""
        self.models.selected = selected_model(self.path, self.models)
        return self.models.selected

    def _mtime(self):
        try:
            return os.stat(self.path).st_mtime_ns
        except OSError:
            return None

    async def follow_selection(self):
        """After the running recording, only the menu's model stays in memory."""
        now = self._select()
        if now == self.models.active:
            return
        async with self.models.recording:
            log.info("the menu's model is %s: only it stays in memory", now or "not on this server")
            try:
                await self.models.activate(now)
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
                            log.info("host or port changed: the server ends; the app starts it again")
                            if not self.stop.done():
                                self.stop.set_result(None)
                            return False
                        apply(now, self.st)
                        if "model" in levels:
                            self.models.reconfigure(now["models"], constants.path(now["modelsFolder"]))
                            log.info("models: %s", ", ".join(now["models"]))
                        self.current.clear()
                        self.current.update(now)
        if self.follow:
            await self.follow_selection()
        else:
            self._select()
        return True

    async def run(self):
        if self.follow:
            await self.follow_selection()
        while await self.check():
            await asyncio.sleep(constants.CONFIG_CHECK_S)
