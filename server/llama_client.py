"""The model's HTTP client: what a recording needs of a model (Model), and LlamaModel, which asks llama.cpp's
llama-server for it: the tokens of a text, a warm-up of a slot's cache, one piece's text, and the timings of each
request. Which llama-server runs is the model registry's (model_registry.py); its process is llama_process.py's."""
import abc
import base64
import contextlib
import http.client
import json
import logging
import os
import threading
import urllib.parse

import catalog
import constants
import llama_process
import tuning
from audio import wav

log = logging.getLogger("echofox-server")
SHORT_TIMEOUT_S = 10  # /tokenize, /props
# llama-server's request field of each sampler knob (tuning.SAMPLER, by its name in the code): the request keeps its
# fields when a knob is renamed, and a sampler knob without a field here fails every request (test_llama_client.py)
SAMPLER_FIELDS = {"temperature": "temperature", "top_k": "top_k", "top_p": "top_p", "seed": "seed"}


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
    def warm(self, text, options, slot=None):
        """The text into the slot's cache, with nothing to write; the timings."""

    @abc.abstractmethod
    def complete(self, text, pcm, limit, options, slot=None):
        """One piece: the text, then the audio: (text, timings)."""

    def footprint_mb(self):
        """The model's memory in MB, for the metrics; None if unknown."""
        return None


class LlamaModel(Model):
    """A model behind llama.cpp's llama-server, at the URL of its registry entry (http or https, with a path prefix
    if it has one). Its files, context and slots are set where llama-server starts (llama_process.command); the
    fields that every request of its model carries are its catalog entry's (llamaServer.request)."""

    def __init__(self, name, entry):
        self.name, self.url = name, entry["llamaServer"].rstrip("/")
        u = urllib.parse.urlparse(self.url)
        self.https, self.host, self.base = u.scheme == "https", u.hostname, u.path.rstrip("/")
        self.port = u.port or (443 if self.https else 80)
        self.request_fields = catalog.of(entry).get("llamaServer", {}).get("request") or {}
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
        if self.host not in llama_process.LOCAL_HOSTS:
            return None
        if self.pid:
            with contextlib.suppress(OSError):
                os.kill(self.pid, 0)
                return llama_process.footprint_mb(self.pid)
        self.pid = llama_process.listening_pid(self.port)
        return llama_process.footprint_mb(self.pid)

    def tokenize(self, text):
        return self._request("POST", "/tokenize", {"content": text}, timeout=SHORT_TIMEOUT_S)["tokens"]

    def _body(self, content, limit, options, slot):
        """A chat completion's body: its catalog entry's fields, then the message, the limit, the cache, and the
        sampler knobs that have a value under their request fields (SAMPLER_FIELDS)."""
        body = {**self.request_fields, "messages": [{"role": "user", "content": content}],
                "max_tokens": limit, "stream": False, "cache_prompt": True,
                **{SAMPLER_FIELDS[name]: v for name, v in tuning.sampler(options).items()}}
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
