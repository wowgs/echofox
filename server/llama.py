"""The models: each a llama.cpp llama-server (server/llama_launchd.sh) behind its launchd agent, and the registry that
keeps only one of them in memory."""
import asyncio
import base64
import contextlib
import ctypes
import ctypes.util
import http.client
import json
import logging
import os
import subprocess
import time
import urllib.parse
import urllib.request

from audio import wav
from dictation import Dictation, sampler_of

log = logging.getLogger("gemma_voice")


def llama_post(url, path, body, timeout):
    req = urllib.request.Request(url + path, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


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
                             timeout=5).stdout.split()
        return int(out[0]) if out else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


class LlamaModel:
    """A model behind llama.cpp's llama-server. Its model, quantization and context are set where llama-server
    starts (server/llama_launchd.sh)."""

    def __init__(self, name, entry):
        self.name, self.url = name, entry["llamaServer"].rstrip("/")
        self.connection, self.pid = None, None  # the connection of the running request; llama-server's process
        log.info("model %s: llama-server at %s", name, self.url)

    def cancel(self):
        """Stops the running request: closing its connection makes llama-server stop decoding (llama-server 0.6.0,
        build 11429: with the connection closed after 1 s, the next request got its answer 0.2 s later; without,
        136 s later)."""
        conn = self.connection
        if conn is not None and conn.sock is not None:
            with contextlib.suppress(OSError):
                conn.sock.shutdown(2)

    def footprint_mb(self):
        """llama-server's physical footprint in MB, for the metrics; None if its process is not found."""
        if self.pid:
            with contextlib.suppress(OSError):
                os.kill(self.pid, 0)
                return footprint_mb(self.pid)
        url = urllib.parse.urlparse(self.url)
        self.pid = listening_pid(url.port or 80) if url.hostname in ("127.0.0.1", "localhost") else None
        return footprint_mb(self.pid)

    def tokenize(self, text):
        return llama_post(self.url, "/tokenize", {"content": text}, 30)["tokens"]

    def detokenize(self, ids):
        return llama_post(self.url, "/detokenize", {"tokens": list(ids)}, 30)["content"]

    def complete(self, text, pcm, limit, options):
        """One piece: the text, then the audio, in one request. (text, timings for the metrics)."""
        audio = base64.b64encode(wav(pcm)).decode("ascii")
        body = {"messages": [{"role": "user", "content": [
                    {"type": "text", "text": text},
                    {"type": "input_audio", "input_audio": {"data": audio, "format": "wav"}}]}],
                "max_tokens": limit, "stream": False, "cache_prompt": True, **sampler_of(options),
                # Gemma 4's template in llama.cpp lets the model think first (reasoning_content), which spent a
                # piece's whole token limit on "Here's a thinking process…" and left no text.
                "chat_template_kwargs": {"enable_thinking": False}}
        url = urllib.parse.urlparse(self.url)
        conn = self.connection = http.client.HTTPConnection(url.hostname, url.port or 80, timeout=300)
        try:
            conn.request("POST", "/v1/chat/completions", json.dumps(body).encode("utf-8"),
                         {"Content-Type": "application/json"})
            reply = conn.getresponse()
            if reply.status != 200:
                raise RuntimeError(f"llama-server: HTTP {reply.status}: {reply.read()[:300]!r}")
            r = json.loads(reply.read().decode("utf-8"))
        finally:
            self.connection = None
            conn.close()
        t = r.get("timings") or {}
        return (r["choices"][0]["message"]["content"] or "").strip(), {
            "ttft_seconds": round(t["prompt_ms"] / 1000, 3) if "prompt_ms" in t else None,
            "prefill_tokens": t.get("prompt_n"), "cached_tokens": t.get("cache_n"),
            "prefill_tps": [round(t["prompt_per_second"], 1)] if "prompt_per_second" in t else [],
            "decode_tokens": t.get("predicted_n", (r.get("usage") or {}).get("completion_tokens")),
            "decode_tps": [round(t["predicted_per_second"], 1)] if "predicted_per_second" in t else []}

    def dictation(self, text_prompt, options=None, meta=None, save_dir=None, **kw):
        return Dictation(self, text_prompt, options or {}, meta or {}, save_dir, **kw)


LAUNCHCTL = os.environ.get("LOCAL_VOICE_LAUNCHCTL", "launchctl")  # tests put a fake here


def launchd(*args):
    """launchctl … in this user's GUI domain; True when it exits 0."""
    import subprocess
    return subprocess.run([LAUNCHCTL, *args], capture_output=True).returncode == 0


def agent_running(label):
    return launchd("print", f"gui/{os.getuid()}/{label}")


def start_agent(label):
    if not agent_running(label):
        launchd("bootstrap", f"gui/{os.getuid()}", os.path.expanduser(f"~/Library/LaunchAgents/{label}.plist"))
        log.info("started the launchd agent %s", label)


def stop_agent(label):
    if agent_running(label):
        launchd("bootout", f"gui/{os.getuid()}/{label}")
        log.info("stopped the launchd agent %s", label)


def wait_healthy(url, seconds=180):
    """Waits until a llama-server answers /health with 200 (it loads its model first)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            with urllib.request.urlopen(url + "/health", timeout=5) as r:
                if r.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(1)
    return False


class Models:
    """The models of the config's registry, by name; the first is the default. Only one is in memory at a time: its
    llama-server's launchd agent runs, the others' agents are stopped. `make(name, entry)` makes the model object
    (tests put a stub here)."""

    def __init__(self, entries, make=LlamaModel):
        self.entries, self.make, self.models = dict(entries), make, {}
        # Whether this server starts and stops the launchd agents (the test server does not).
        self.manage = True
        # One recording at a time: llama-server runs one request at a time (-np 1), and loading or switching a model
        # waits for the running recording. A second recording waits.
        self.recording = asyncio.Lock()

    def reconfigure(self, entries):
        """New model entries: the next recording, or the menu's choice, starts its model again."""
        self.entries, self.models = dict(entries), {}

    def name_for(self, name):
        """The model a client asks for by name; no name (or the URL path /voice_stream of earlier clients): the
        default."""
        name = (name or "").strip("/")
        if name in ("", "voice_stream"):
            return next(iter(self.entries))
        return name if name in self.entries else None

    async def get(self, name):
        """The model, the only one in memory."""
        await self.activate(name)
        if name not in self.models:
            self.models[name] = self.make(name, self.entries[name])
        return self.models[name]

    async def activate(self, name):
        """Makes `name` the only model in memory; None: no model at all (Anthropic is chosen)."""
        entry = self.entries.get(name) if name else None
        if self.manage:
            for n, e in self.entries.items():
                if e.get("launchd") and n != name:
                    await asyncio.to_thread(stop_agent, e["launchd"])
            if entry is not None and entry.get("launchd"):
                await asyncio.to_thread(start_agent, entry["launchd"])
        if entry is not None and not await asyncio.to_thread(wait_healthy, entry["llamaServer"].rstrip("/")):
            raise RuntimeError(f"llama-server of {name} at {entry['llamaServer']} does not answer")
