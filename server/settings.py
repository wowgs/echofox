"""The server's settings and the config file it shares with its clients."""
import asyncio
import json
import logging
import os

import metrics
from audio import MODEL_MAX_SECONDS
from dictation import MAX_PROMPT, parse_options

log = logging.getLogger("gemma_voice")


# The config, ~/.local-voice/config.json ($LOCAL_VOICE_CONFIG), version 3, shared with the menus:
#   {"version": 3, "model": "<name>" | "anthropic", "language": "ru", "adapters": {"<plugin>": {"enabled": true}},
#    "models": {"<name>": {"llamaServer": "http://127.0.0.1:8092", "launchd": "<label>", "prompt": "…", "options": {…}}},
#    "silenceStopSeconds": 60, "saveRecordings": true,
#    "server": {"host": …, "port": …, "pieceSeconds": …, …}}
# language: the clients' dictation language; the server does not read it. adapters: the adapter plugins that work
# (adapters/registry.py); none: the base mode, dictation without context. models: the registry; each a llama.cpp llama-server, started and stopped through its launchd agent. Only the model
# chosen in the menus ("model") is in memory; Anthropic chosen: none. The server's settings: built-in defaults, then
# the file, then the command line, which wins (the test server keeps its own port, log and metrics). The server
# watches the file:
#   "recording" settings take effect at the next recording;
#   "model" settings (models) take effect after the running recording;
#   "process" settings (host, port) end the process after the running recording; launchd starts it again.
# config key → (command-line name, kind, check, default, level, where in the file); command-line name None: only in
# the file.
MODEL_DEFAULT = {"gemma-e4b": {"llamaServer": "http://127.0.0.1:8092", "launchd": "local-voice.llama-server"}}


CONFIG_VERSION = 3


def good_adapters(v):
    return all(isinstance(k, str) and isinstance(e, dict) and isinstance(e.get("enabled", False), bool)
               for k, e in v.items())


def migrate(path):
    """Version 2 → 3: adapters became plugins that the config enables. A version-2 file had both built-in adapters
    working, so the upgrade enables them; a new config has none (the base mode). The file keeps its order."""
    try:
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(c, dict) or c.get("version") != 2:
        return
    out = {}
    for k, v in c.items():
        out[k] = 3 if k == "version" else v
        if k == "language" or (k == "model" and "language" not in c):
            out["adapters"] = {"claude-desktop": {"enabled": True}, "claude-code": {"enabled": True}}
    out.setdefault("adapters", {"claude-desktop": {"enabled": True}, "claude-code": {"enabled": True}})
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    log.info("config %s: version 2 → 3; the built-in adapters claude-desktop and claude-code are enabled", path)


def good_model(m):
    """A registry entry: llamaServer, and optionally launchd, prompt and options that parse_options accepts."""
    if not isinstance(m, dict) or not str(m.get("llamaServer", "")).startswith("http") \
            or not isinstance(m.get("launchd", ""), str) or not isinstance(m.get("prompt", ""), str) \
            or len(m.get("prompt", "")) > MAX_PROMPT:
        return False
    try:
        parse_options(m.get("options"))
        return True
    except ValueError:
        return False


SETTINGS = {
    "host": ("host", str, lambda v: bool(v), "127.0.0.1", "process", "server"),
    "port": ("port", int, lambda v: 0 < v < 65536, 8090, "process", "server"),
    "models": (None, dict, lambda v: bool(v) and all(good_model(m) for m in v.values()), MODEL_DEFAULT, "model", None),
    "saveRecordings": (None, bool, lambda v: True, True, "recording", None),
    "adapters": (None, dict, good_adapters, {}, "recording", None),
    "thresholdDb": ("threshold_db", float, lambda v: v < 0, -45.0, "recording", "server"),
    "speechAboveNoiseDb": ("speech_above_noise_db", float, lambda v: v >= 0, 12.0, "recording", "server"),
    "pieceSeconds": ("piece_seconds", float, lambda v: 5 <= v <= MODEL_MAX_SECONDS, 20.0, "recording", "server"),
    "cutSearchSeconds": ("cut_search_seconds", float, lambda v: 0 < v <= 10, 3.0, "recording", "server"),
    "outputTokensPerSecond": ("output_tokens_per_second", float, lambda v: v > 0, 10.0, "recording", "server"),
    "outputTokensBase": ("output_tokens_base", int, lambda v: v >= 0, 32, "recording", "server"),
    "warmText": (None, bool, lambda v: True, True, "recording", "server"),
    "recordings": ("recordings", str, lambda v: bool(v), "~/speech/recordings", "recording", "server"),
    "metrics": ("metrics", str, lambda v: bool(v), "~/Library/Logs/local-voice/gemma-voice-metrics.jsonl",
                "recording", "server"),
}


CONFIG_CHECK_S = 2


def config_file():
    return os.environ.get("LOCAL_VOICE_CONFIG") or os.path.expanduser("~/.local-voice/config.json")


def file_settings(path):
    """The server's settings in the config file, checked: {config key: value}. A wrong key or value is logged and left
    out; None if the file cannot be read or is of another version."""
    try:
        with open(path, encoding="utf-8") as f:
            c = json.load(f) or {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.error("config %s: cannot read it (%s); the server keeps its settings", path, e)
        return None
    if not isinstance(c, dict) or c.get("version") != CONFIG_VERSION:
        log.error("config %s: version %s, the server reads version %d", path,
                  c.get("version") if isinstance(c, dict) else None, CONFIG_VERSION)
        return None
    server = c.get("server") if isinstance(c.get("server"), dict) else {}
    known = {k for k, v in SETTINGS.items() if v[5] == "server"}
    for key in server:
        if key not in known:
            log.error("config %s: server.%s is not a setting; known: %s", path, key, ", ".join(sorted(known)))
    out = {}
    for key, (_, kind, ok, _, _, where) in SETTINGS.items():
        source = server if where == "server" else c
        if key not in source:
            continue
        value = source[key]
        try:
            if kind is dict:
                good = isinstance(value, dict) and ok(value)
            elif kind is bool:
                good = isinstance(value, bool)
            else:
                good = not isinstance(value, bool) and ok(kind(value)) and (kind is not int or value == int(value))
                value = kind(value) if good else value
        except (TypeError, ValueError):
            good = False
        if not good:
            log.error("config %s: %s%s = %r is not valid; it is left out", path, f"{where}." if where else "", key,
                      value)
            continue
        out[key] = value
    return out


def resolve(cli, from_file):
    """The settings in force: the command line, then the file, then the defaults. {config key: value}."""
    out = {}
    for key, (name, _, _, default, _, _) in SETTINGS.items():
        given = getattr(cli, name, None) if name else None
        out[key] = given if given is not None else from_file.get(key, default)
    return out


def apply_recording_settings(st, now):
    """Puts the "recording" settings where the code reads them: `st`, the namespace that protocol.handle() gets, and
    the metrics file."""
    st.threshold_db, st.speech_above_noise_db = now["thresholdDb"], now["speechAboveNoiseDb"]
    st.piece_seconds, st.cut_search_seconds = now["pieceSeconds"], now["cutSearchSeconds"]
    st.output_tokens_per_second, st.output_tokens_base = now["outputTokensPerSecond"], now["outputTokensBase"]
    st.recordings, st.save_recordings = os.path.expanduser(now["recordings"]), now["saveRecordings"]
    st.warm_text = now["warmText"]
    st.adapters = [name for name, e in now["adapters"].items() if e.get("enabled")]
    metrics.METRICS = os.path.expanduser(now["metrics"])


def selected_model(config_path, models):
    """The model chosen in the menus ("model" in the config), if this server has it; None for Anthropic or none."""
    try:
        with open(config_path, encoding="utf-8") as f:
            name = (json.load(f) or {}).get("model")
    except (OSError, ValueError, AttributeError):
        return None
    return name if isinstance(name, str) and name in models.entries else None


async def follow_selection(models, path, chosen):
    """Keeps in memory only the model chosen in the menus (see selected_model), after the running recording."""
    now = selected_model(path, models)
    if now == chosen[0]:
        return
    async with models.recording:
        log.info("the menu's model is %s: only it stays in memory", now or "not on this server")
        try:
            await models.activate(now)
            chosen[0] = now
        except Exception:
            log.exception("cannot make %s the model in memory", now)


async def watch_config(cli, models, st, current, path, stop, follow=True):
    """Applies changes of the config file; see SETTINGS. With `follow`, also keeps in memory only the model chosen in
    the menus."""
    seen, chosen = None, [object()]
    if follow:
        await follow_selection(models, path, chosen)
    while True:
        await asyncio.sleep(CONFIG_CHECK_S)
        try:
            mtime = os.stat(path).st_mtime_ns
        except OSError:
            mtime = None
        if mtime == seen:
            continue
        first, seen = seen is None, mtime
        if first:
            continue
        from_file = file_settings(path)
        if from_file is not None:
            now = resolve(cli, from_file)
            changed = {k for k in SETTINGS if now[k] != current[k]}
            if changed:
                levels = {SETTINGS[k][4] for k in changed}
                log.info("config %s changed: %s", path, ", ".join(f"{k} {current[k]!r} -> {now[k]!r}"
                                                                 for k in sorted(changed)))
                async with models.recording:  # after the running recording
                    if "process" in levels:
                        log.info("host or port changed: the server ends; launchd starts it again with the new "
                                 "settings")
                        stop.set_result(None)
                        return
                    apply_recording_settings(st, now)
                    if "model" in levels:
                        models.reconfigure(now["models"])
                        chosen[0] = object()  # start the chosen model again, with the new entries
                        log.info("models: %s", ", ".join(now["models"]))
                    current.clear()
                    current.update(now)
        if follow:
            await follow_selection(models, path, chosen)
