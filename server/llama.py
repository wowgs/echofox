"""The models: each a llama.cpp llama-server, and the registry that keeps only one of them in memory. The server starts
the llama-server of a model on this Mac as its own child process (command): the files of its variant in the models
folder (catalog.py), its address, and its catalog entry's arguments; it stops it when another model is chosen and when
the server ends."""
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
import signal
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
STOP_WAIT_S = 30      # a llama-server has this long to end after SIGTERM, then it is killed


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


APP_VERSION = "ECHOFOX_APP_VERSION"  # set by the app that starts the server (macos ServerProcess), for the log
BUNDLED_LLAMA_SERVER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "llama", "llama-server")
LOCAL_HOSTS = (constants.HOST, "localhost")


def llama_server():
    """llama.cpp's server: the app bundle's (Contents/Resources/llama, next to the server's folder), else the installed
    app's (constants.LLAMA_SERVER), for a server that runs from the repository; None if neither is there."""
    for path in (BUNDLED_LLAMA_SERVER, constants.LLAMA_SERVER):
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def local(entry):
    """Whether the entry's llama-server is on this Mac, so that the server starts it; one on another computer is
    only asked."""
    return urllib.parse.urlparse(entry["llamaServer"]).hostname in LOCAL_HOSTS


def command(entry, models_folder):
    """The command of a registry entry's llama-server: the files of the entry's variant, the address of its
    llamaServer, its catalog entry's arguments. Raises RuntimeError if a file of the variant or llama-server is
    missing."""
    vid, spec = catalog.variant(entry)
    if spec is None:
        raise RuntimeError(f"the catalog has no variant {vid!r} of {entry.get('catalog') or catalog.DEFAULT}")
    files = catalog.files(entry, models_folder)
    missing = [p for p in files.values() if not os.path.isfile(p)]
    if missing:
        raise RuntimeError(f"the files of variant {vid} are missing: {', '.join(missing)}")
    binary = llama_server()
    if not binary:
        raise RuntimeError(f"no llama-server, neither in the app nor at {constants.LLAMA_SERVER}")
    url = urllib.parse.urlparse(entry["llamaServer"])
    return [binary, "-m", files["model"], "--mmproj", files["mmproj"], "--host", url.hostname,
            "--port", str(url.port or 80), *catalog.of(entry)["llamaServer"]["args"]]


def spawn(argv):
    """Starts a llama-server as this process's child, its output appended to its log (constants.LOGS)."""
    log_file = constants.path(f"{constants.LOGS}/llama-server.log")
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    with open(log_file, "ab") as out:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
    log.info("started llama-server, pid %d: %s", proc.pid, " ".join(argv[:5]))
    return proc


def end(proc):
    """Ends a llama-server that this process started: SIGTERM, then SIGKILL after STOP_WAIT_S."""
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(STOP_WAIT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    log.info("stopped llama-server, pid %d", proc.pid)


def end_stale(port):
    """Ends a llama-server that listens on this port but is not this process's child: one left by a server that was
    killed before it could stop it. Another program on the port is left alone (the start then fails and says so)."""
    pid = listening_pid(port)
    if not pid:
        return
    try:
        name = subprocess.run(["ps", "-p", str(pid), "-o", "comm="], capture_output=True, text=True,
                              timeout=SHORT_TIMEOUT_S).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return
    if os.path.basename(name) != "llama-server":
        return
    with contextlib.suppress(OSError):
        os.kill(pid, signal.SIGTERM)
    end_at = time.monotonic() + STOP_WAIT_S
    while listening_pid(port) == pid and time.monotonic() < end_at:
        time.sleep(HEALTH_POLL_S / 10)
    log.info("stopped a llama-server left on port %d, pid %d", port, pid)


def wait_healthy(url, seconds=constants.MODEL_START_S, stop=None):
    """Waits until a llama-server answers /health with 200 (it loads its model first); False at once when `stop` (a
    threading.Event) is set: the server ends, and its end must not wait for a model that will not come."""
    end = time.monotonic() + seconds
    while time.monotonic() < end and not (stop and stop.is_set()):
        try:
            with urllib.request.urlopen(url + "/health", timeout=SHORT_TIMEOUT_S) as r:
                if r.status == 200:
                    return True
        except OSError:
            pass
        if stop:
            stop.wait(HEALTH_POLL_S)
        else:
            time.sleep(HEALTH_POLL_S)
    return False


UNKNOWN = object()  # Models.active before the first activation, and after the registry changed


class Models:
    """The models of the config's registry, by name; the first is the default. Only one is in memory at a time: the
    llama-server of the active model runs as this process's child, and none other (unless `manage` is off: the test
    server). `make(name, entry)` makes the model object (tests put a stub here)."""

    def __init__(self, entries, make=LlamaModel, manage=True, models_folder=None):
        self.entries, self.make, self.models, self.manage = dict(entries), make, {}, manage
        self.models_folder = models_folder or constants.path(constants.MODELS_FOLDER)
        # The model chosen in the menus ("model" in the server's config file), if this server has it: the config
        # watcher keeps it (settings.ConfigWatcher), so that nothing else reads the file
        self.selected = None
        # The model that this server last made the only one in memory (None: no model); activating it again only
        # checks that its llama-server still runs and answers
        self.active = UNKNOWN
        # The running llama-server and its command; `closing` is set when the server ends
        self.proc, self.argv, self.closing = None, None, threading.Event()
        # When a recording last asked for a model (get), or was seen running: the idle time counts from here
        self.used = time.monotonic()
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
        """The model, the only one in memory; loaded first if it left memory."""
        self.used = time.monotonic()
        await self.activate(name)
        if name not in self.models:
            self.models[name] = self.make(name, self.entries[name])
        return self.models[name]

    def _stop(self):
        if self.proc is not None:
            end(self.proc)
        self.proc, self.argv = None, None

    def _run(self, entry):
        """The entry's llama-server runs: started if none runs, if the one running ended, or if its command changed
        (another variant or models folder)."""
        argv = command(entry, self.models_folder)
        if self.proc is not None and self.proc.poll() is None and argv == self.argv:
            return
        self._stop()
        end_stale(urllib.parse.urlparse(entry["llamaServer"]).port or 80)
        self.proc, self.argv, self.loading = spawn(argv), argv, time.monotonic()

    async def activate(self, name):
        """Makes `name` the only model in memory; None: no model at all. When it already is, starts its llama-server
        again if it ended, and checks that it answers."""
        entry = self.entries.get(name) if name else None
        if self.manage:
            if entry is not None and local(entry):
                await asyncio.to_thread(self._run, entry)
            else:
                await asyncio.to_thread(self._stop)
            self.active = name
        if entry is not None and not await asyncio.to_thread(wait_healthy, entry["llamaServer"].rstrip("/"),
                                                             constants.MODEL_START_S, self.closing):
            raise RuntimeError(f"llama-server of {name} at {entry['llamaServer']} does not answer")
        if getattr(self, "loading", None) is not None:
            log.info("model %s: loaded in %.1f s", name, time.monotonic() - self.loading)
            self.loading = None

    async def unload_when_idle(self, seconds):
        """Ends the llama-server when no recording asked for the model for `seconds()` (the setting
        modelIdleSeconds; 0: never), after the running recording. The model stays the active one, so the menu's
        choice does not load it again; the next recording's get() starts its llama-server first."""
        while True:
            await asyncio.sleep(constants.IDLE_POLL_S)
            if self.recording.locked() or self.proc is None or self.proc.poll() is not None:
                self.used = max(self.used, time.monotonic()) if self.recording.locked() else self.used
                continue
            idle = seconds()
            if not idle or time.monotonic() - self.used < idle:
                continue
            async with self.recording:
                if self.proc is not None and time.monotonic() - self.used >= idle:
                    await asyncio.to_thread(self._stop)
                    log.info("model %s: left memory after %.0f s without a recording", self.active, idle)

    def close(self):
        """The server ends: its llama-server ends too, and the model leaves memory. A wait for a model that is loading
        ends at once."""
        self.closing.set()
        if self.manage:
            self._stop()
