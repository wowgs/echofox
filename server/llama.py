"""The models: each a llama.cpp llama-server behind its launchd agent, and the registry that keeps only one of them in
memory. The server writes the agent of a model itself (write_agent): the files of its variant in the models folder
(catalog.py), its address, and its catalog entry's arguments."""
import abc
import asyncio
import base64
import contextlib
import ctypes
import ctypes.util
import http.client
import json
import logging
import os
import plistlib
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request

import catalog
import constants
import tuning
from audio import wav

log = logging.getLogger("gemma_voice")
SHORT_TIMEOUT_S = 10  # /tokenize, /detokenize, /props, /health, lsof
HEALTH_POLL_S = 1
BOOTOUT_WAIT_S = 30   # launchctl bootout returns before the agent is gone; this long for it to go


class Cancelled(Exception):
    """A request of a cancelled recording."""


class Model(abc.ABC):
    """What a recording needs of a model (dictation.Dictation): the tests' stub models have the same."""
    name = ""

    @abc.abstractmethod
    def begin(self):
        """A new recording starts: a cancel of the one before does not reach it."""

    @abc.abstractmethod
    def cancel(self):
        """Stops the running recording's requests, also those that have not connected yet."""

    @abc.abstractmethod
    def slots(self):
        """How many requests the model runs at once."""

    @abc.abstractmethod
    def tokenize(self, text):
        """The text's tokens."""

    @abc.abstractmethod
    def detokenize(self, ids):
        """The tokens' text."""

    @abc.abstractmethod
    def warm(self, text, options, slot=None):
        """The text into the slot's cache, with nothing to write; the timings."""

    @abc.abstractmethod
    def complete(self, text, pcm, limit, options, slot=None):
        """One piece: the text, then the audio: (text, timings)."""

    def footprint_mb(self):
        """The model's memory in MB, for the metrics; None if unknown."""
        return None


_libproc = ctypes.CDLL(ctypes.util.find_library("proc")) if ctypes.util.find_library("proc") else None


def footprint_mb(pid):
    """A process's physical footprint in MB, as macOS counts it (proc_pid_rusage, rusage_info_v0: ri_phys_footprint
    is the 8th 64-bit field after the 16-byte uuid; the same number as `footprint <pid>`). None if unknown."""
    if not _libproc or not pid:
        return None
    buf = (ctypes.c_uint64 * 12)()
    if _libproc.proc_pid_rusage(int(pid), 0, ctypes.byref(buf)) != 0:
        return None
    return round(buf[2 + 7] / 2**20)


def listening_pid(port):
    """The process listening on this TCP port of this Mac, or None (lsof)."""
    try:
        out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True,
                             timeout=SHORT_TIMEOUT_S).stdout.split()
        return int(out[0]) if out else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


class LlamaModel(Model):
    """A model behind llama.cpp's llama-server, at the URL of its registry entry (http or https, with a path prefix
    if it has one). Its files, context and slots are set where llama-server starts (agent)."""

    def __init__(self, name, entry):
        self.name, self.url = name, entry["llamaServer"].rstrip("/")
        u = urllib.parse.urlparse(self.url)
        self.https, self.host, self.base = u.scheme == "https", u.hostname, u.path.rstrip("/")
        self.port = u.port or (443 if self.https else 80)
        self.connections, self.pid, self.n_slots = set(), None, None  # the running requests; llama-server's process
        self.cancelled = False  # set by cancel(); a recording's requests that have not connected yet do not start
        self.lock = threading.Lock()
        log.info("model %s: llama-server at %s", name, self.url)

    def begin(self):
        with self.lock:
            self.cancelled = False

    def cancel(self):
        """Stops the recording's requests: closing a request's connection makes llama-server stop decoding it
        (llama-server 0.6.0, build 11429: with the connection closed after 1 s, the next request got its answer 0.2 s
        later; without, 136 s later). A request that has not connected yet does not start (_request). One recording
        at a time uses the model (Models.recording), so these are all its requests."""
        with self.lock:
            self.cancelled = True
            conns = list(self.connections)
        for conn in conns:
            with contextlib.suppress(OSError):
                if conn.sock is not None:
                    conn.sock.shutdown(2)

    def _request(self, method, path, body=None, timeout=constants.REQUEST_TIMEOUT_S):
        """One request on a connection of its own, which cancel() can close; the JSON answer."""
        cls = http.client.HTTPSConnection if self.https else http.client.HTTPConnection
        conn = cls(self.host, self.port, timeout=timeout)
        with self.lock:
            if self.cancelled:
                raise Cancelled("the recording was cancelled before this request")
            self.connections.add(conn)
        try:
            data = json.dumps(body).encode("utf-8") if body is not None else None
            conn.request(method, self.base + path, data, {"Content-Type": "application/json"} if data else {})
            reply = conn.getresponse()
            raw = reply.read()
            if reply.status != 200:
                raise RuntimeError(f"llama-server {method} {path}: HTTP {reply.status}: {raw[:300]!r}")
            return json.loads(raw.decode("utf-8"))
        finally:
            with self.lock:
                self.connections.discard(conn)
            conn.close()

    def slots(self):
        """llama-server's slots (its -np): requests it runs at once. 1 if it does not say."""
        if self.n_slots is None:
            try:
                props = self._request("GET", "/props", timeout=SHORT_TIMEOUT_S)
                self.n_slots = max(1, int(props.get("total_slots") or 1))
            except (OSError, ValueError, TypeError, RuntimeError, Cancelled):
                return 1
        return self.n_slots

    def footprint_mb(self):
        """llama-server's physical footprint in MB, for the metrics; None if its process is not found (or it runs on
        another computer)."""
        if self.host not in (constants.HOST, "localhost"):
            return None
        if self.pid:
            with contextlib.suppress(OSError):
                os.kill(self.pid, 0)
                return footprint_mb(self.pid)
        self.pid = listening_pid(self.port)
        return footprint_mb(self.pid)

    def tokenize(self, text):
        return self._request("POST", "/tokenize", {"content": text}, timeout=SHORT_TIMEOUT_S)["tokens"]

    def detokenize(self, ids):
        return self._request("POST", "/detokenize", {"tokens": list(ids)}, timeout=SHORT_TIMEOUT_S)["content"]

    @staticmethod
    def _body(content, limit, options, slot):
        body = {"messages": [{"role": "user", "content": content}],
                "max_tokens": limit, "stream": False, "cache_prompt": True, **tuning.sampler(options),
                # Gemma 4's template in llama.cpp lets the model think first (reasoning_content), which spent a
                # piece's whole token limit on "Here's a thinking process…" and left no text.
                "chat_template_kwargs": {"enable_thinking": False}}
        if slot is not None:
            body["id_slot"] = slot
        return body

    @staticmethod
    def _timings(r):
        t = r.get("timings") or {}
        return {"ttft_seconds": round(t["prompt_ms"] / 1000, 3) if "prompt_ms" in t else None,
                "prefill_tokens": t.get("prompt_n"), "cached_tokens": t.get("cache_n"),
                "prefill_tps": [round(t["prompt_per_second"], 1)] if "prompt_per_second" in t else [],
                "decode_tokens": t.get("predicted_n", (r.get("usage") or {}).get("completion_tokens")),
                "decode_tps": [round(t["predicted_per_second"], 1)] if "predicted_per_second" in t else []}

    def warm(self, text, options, slot=None):
        """The text alone, with no audio and nothing to write, so that llama-server keeps it in the slot's cache: a
        piece in that slot then processes only its audio. Measured 2026-10-15 (llama-server 0.6.0, build 11429): after
        this request, a piece of the same text and 21 s of audio took 1316 tokens from the cache and processed 537."""
        body = self._body([{"type": "text", "text": text}], 0, options, slot)
        return self._timings(self._request("POST", "/v1/chat/completions", body))

    def complete(self, text, pcm, limit, options, slot=None):
        audio = base64.b64encode(wav(pcm)).decode("ascii")
        body = self._body([{"type": "text", "text": text},
                           {"type": "input_audio", "input_audio": {"data": audio, "format": "wav"}}],
                          limit, options, slot)
        r = self._request("POST", "/v1/chat/completions", body)
        return (r["choices"][0]["message"]["content"] or "").strip(), self._timings(r)


LAUNCHCTL = "/bin/launchctl"


def launchd(*args):
    """launchctl … ; (exit code, its output)."""
    r = subprocess.run([LAUNCHCTL, *args], capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def domain():
    return f"gui/{os.getuid()}"


def agent_running(label):
    return launchd("print", f"{domain()}/{label}")[0] == 0


APP_VERSION = "ECHOFOX_APP_VERSION"  # set by the agent that the bundled app writes (macos ServerAgent)
BUNDLED_LLAMA_SERVER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "llama", "llama-server")


def llama_server():
    """llama.cpp's server: the app bundle's (Contents/Resources/llama, next to the server's folder), else Homebrew's,
    else the first on the PATH."""
    for path in (BUNDLED_LLAMA_SERVER, constants.LLAMA_SERVER):
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return shutil.which("llama-server")


def agent(entry, models_folder):
    """The launchd agent of a registry entry, as a plist's contents: llama-server with the files of the entry's
    variant, on the address of its llamaServer, with its catalog entry's arguments. The bundled app's version
    ($ECHOFOX_APP_VERSION, from the server's own agent) is in it too, so that a new version of the app, with its own
    llama-server, starts it again. Raises RuntimeError if a file of the variant or llama-server is missing."""
    vid, spec = catalog.variant(entry)
    if spec is None:
        raise RuntimeError(f"the catalog has no variant {vid!r} of {entry.get('catalog') or catalog.DEFAULT}")
    files = catalog.files(entry, models_folder)
    missing = [p for p in files.values() if not os.path.isfile(p)]
    if missing:
        raise RuntimeError(f"the files of variant {vid} are missing: {', '.join(missing)}")
    binary = llama_server()
    if not binary:
        raise RuntimeError("llama-server is not installed (brew install llama.cpp)")
    url = urllib.parse.urlparse(entry["llamaServer"])
    log_file = constants.path(f"{constants.LOGS}/llama-server.log")
    version = os.environ.get(APP_VERSION)
    return {"Label": entry["launchd"],
            "ProgramArguments": [binary, "-m", files["model"], "--mmproj", files["mmproj"],
                                 "--host", url.hostname, "--port", str(url.port or 80),
                                 *catalog.of(entry)["llamaServer"]["args"]],
            **({"EnvironmentVariables": {APP_VERSION: version}} if version else {}),
            "RunAtLoad": True, "KeepAlive": True, "ProcessType": "Interactive",
            "StandardOutPath": log_file, "StandardErrorPath": log_file}


def write_agent(entry, models_folder):
    """Writes the launchd agent of a registry entry if it is not what it must be; True if it changed."""
    plist = constants.path(f"{constants.LAUNCH_AGENTS}/{entry['launchd']}.plist")
    want = agent(entry, models_folder)
    try:
        with open(plist, "rb") as f:
            if plistlib.load(f) == want:
                return False
    except (OSError, plistlib.InvalidFileException):
        pass
    os.makedirs(os.path.dirname(plist), exist_ok=True)
    os.makedirs(os.path.dirname(want["StandardOutPath"]), exist_ok=True)
    with open(plist + ".tmp", "wb") as f:
        plistlib.dump(want, f)
    os.replace(plist + ".tmp", plist)
    log.info("wrote the launchd agent %s: %s", entry["launchd"], " ".join(want["ProgramArguments"][:5]))
    return True


def start_agent(label):
    """Starts the launchd agent from its plist; raises RuntimeError if launchctl refuses."""
    if agent_running(label):
        return
    code, out = launchd("bootstrap", domain(), constants.path(f"{constants.LAUNCH_AGENTS}/{label}.plist"))
    if code != 0 and not agent_running(label):
        raise RuntimeError(f"launchctl bootstrap {label}: exit {code}: {out}")
    log.info("started the launchd agent %s", label)


def stop_agent(label):
    """Stops the launchd agent and waits until it is gone (bootout returns before that)."""
    if not agent_running(label):
        return
    code, out = launchd("bootout", f"{domain()}/{label}")
    end = time.monotonic() + BOOTOUT_WAIT_S
    while agent_running(label) and time.monotonic() < end:
        time.sleep(HEALTH_POLL_S / 10)
    if agent_running(label):
        raise RuntimeError(f"launchctl bootout {label}: exit {code}: {out}; it still runs after {BOOTOUT_WAIT_S} s")
    log.info("stopped the launchd agent %s", label)


def wait_healthy(url, seconds=constants.MODEL_START_S):
    """Waits until a llama-server answers /health with 200 (it loads its model first)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            with urllib.request.urlopen(url + "/health", timeout=SHORT_TIMEOUT_S) as r:
                if r.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(HEALTH_POLL_S)
    return False


UNKNOWN = object()  # Models.active before the first activation, and after the registry changed


class Models:
    """The models of the config's registry, by name; the first is the default. Only one is in memory at a time: its
    llama-server's launchd agent runs, the others' agents are stopped (unless `manage` is off: the test server).
    `make(name, entry)` makes the model object (tests put a stub here)."""

    def __init__(self, entries, make=LlamaModel, manage=True, models_folder=None):
        self.entries, self.make, self.models, self.manage = dict(entries), make, {}, manage
        self.models_folder = models_folder or constants.path(constants.MODELS_FOLDER)
        # The model chosen in the menus ("model" in the server's config file), if this server has it: the config
        # watcher keeps it (settings.ConfigWatcher), so that nothing else reads the file
        self.selected = None
        # The model whose agent this server last made the only one running (None: no model); activating it again
        # only checks that it answers
        self.active = UNKNOWN
        # One recording at a time: its requests share the model's slots, and a cancel stops all requests of the
        # model; loading or switching a model waits for the running recording. A second recording waits.
        self.recording = asyncio.Lock()

    def reconfigure(self, entries, models_folder=None):
        """New model entries or a new models folder: the next recording, or the menu's choice, starts its model
        again."""
        self.entries, self.models, self.active = dict(entries), {}, UNKNOWN
        if models_folder:
            self.models_folder = models_folder

    def name_for(self, name):
        """The model a client asks for by name; no name: the default."""
        if not name:
            return next(iter(self.entries))
        return name if name in self.entries else None

    async def get(self, name):
        """The model, the only one in memory."""
        await self.activate(name)
        if name not in self.models:
            self.models[name] = self.make(name, self.entries[name])
        return self.models[name]

    async def activate(self, name):
        """Makes `name` the only model in memory; None: no model at all. When it already is, only checks that it
        answers (launchd restarts a llama-server that stopped)."""
        entry = self.entries.get(name) if name else None
        if self.manage and name != self.active:
            for n, e in self.entries.items():
                if e.get("launchd") and n != name:
                    await asyncio.to_thread(stop_agent, e["launchd"])
            if entry is not None and entry.get("launchd"):
                if await asyncio.to_thread(write_agent, entry, self.models_folder):  # another variant or folder
                    await asyncio.to_thread(stop_agent, entry["launchd"])
                await asyncio.to_thread(start_agent, entry["launchd"])
        if self.manage:
            self.active = name
        if entry is not None and not await asyncio.to_thread(wait_healthy, entry["llamaServer"].rstrip("/")):
            raise RuntimeError(f"llama-server of {name} at {entry['llamaServer']} does not answer")
