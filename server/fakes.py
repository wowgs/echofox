"""Shared pieces of the server's tests: audio, stub models and a fake llama-server. Not a test module."""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import array
import json
import tempfile
import threading
import time

import audio
import llama
import recordings
import protocol
import settings
import vad
from audio import RATE

# No test waits for a real llama-server, touches the real launchd agents or asks macOS about the microphone.
llama.wait_healthy = lambda url, seconds=0: True
recordings.input_info = lambda: None


class ToneStream(vad.Stream):
    """The VAD for the tests' audio, which is a tone, not speech (test_vad.py): a 32 ms chunk is speech when it is
    loud (an RMS over 1000, about -30 dBFS)."""

    def __init__(self):
        super().__init__(vad=self)

    def run(self, chunk, context, state):
        return float(((chunk * 32768.0) ** 2).mean() ** 0.5 > 1000), state




def handle(ws, models, a):
    """protocol.handle with the tone detector instead of Silero VAD."""
    return protocol.handle(ws, models, a, make_stream=ToneStream)


LOUD = array.array("h", [8000, -8000] * (RATE // 2)).tobytes()  # 1 s, about -12 dBFS
QUIET = b"\0\0" * RATE  # 1 s of silence
ENTRIES = {"gemma-e4b": {"llamaServer": "http://127.0.0.1:9"}, "gemma-12b": {"llamaServer": "http://127.0.0.1:9"}}


def args(**over):
    """The recording settings protocol.handle() gets: the defaults, with the recordings in the sandbox and the
    built-in adapter enabled."""
    st = settings.recording_settings(settings.resolve({}))
    st.recordings = tempfile.mkdtemp(prefix="recordings-", dir=sandbox.ROOT)
    st.adapters = ["claude"]
    for k, v in over.items():
        setattr(st, k, v)
    return st


def seconds(pcm):
    return audio.seconds(pcm)


class StubModel(llama.Model):
    """A model without llama-server: a token per word; each piece's text is "<name> piece N". It notes every call.
    `delays`: seconds each piece takes, by piece number (in its request's thread); `slots_n`: its slots."""

    def __init__(self, name="gemma-e4b", entry=None, slots_n=1, delays=None):
        self.name, self.slots_n, self.delays = name, slots_n, delays or {}
        self.calls, self.warmed, self.order, self.begun, self.cancelled = [], [], [], 0, False
        self.lock = threading.Lock()
        self.stop = threading.Event()

    def begin(self):
        self.begun += 1
        self.stop.clear()

    def cancel(self):
        self.cancelled = True
        self.stop.set()

    def slots(self):
        return self.slots_n

    def tokenize(self, text):
        return list(range(len(text.split())))

    def detokenize(self, ids):
        return " ".join("w" for _ in ids)

    def warm(self, text, options, slot=None):
        with self.lock:
            self.warmed.append(slot)
        return {}

    def complete(self, text, pcm, limit, options, slot=None):
        with self.lock:
            self.calls.append((round(seconds(pcm), 1), text, options))
            n = len(self.calls)
            self.order.append(("start", n, slot))
        if self.stop.wait(self.delays.get(n, 0)):
            raise llama.Cancelled("cancelled")
        with self.lock:
            self.order.append(("end", n))
        return f"{self.name} piece {n}", {}


class HangingStub(StubModel):
    """A model request that never ends unless cancelled."""

    def complete(self, text, pcm, limit, options, slot=None):
        with self.lock:
            self.calls.append(round(seconds(pcm), 1))
        self.stop.wait(3600)
        raise llama.Cancelled("cancelled")


def stub_models(entries=ENTRIES, make=None):
    return llama.Models(entries, make=make or StubModel, manage=False)


class FakeAgents:
    """start_agent, stop_agent and write_agent of the server, recorded instead of run; `rewrite`: the labels whose
    agent write_agent says it changed."""

    def __init__(self, rewrite=()):
        self.rewrite = set(rewrite)

    def __enter__(self):
        self.calls, self.saved = [], (llama.start_agent, llama.stop_agent, llama.write_agent)
        llama.start_agent = lambda label: self.calls.append(("start", label))
        llama.stop_agent = lambda label: self.calls.append(("stop", label))
        llama.write_agent = lambda entry, folder: entry["launchd"] in self.rewrite
        return self

    def __exit__(self, *exc):
        llama.start_agent, llama.stop_agent, llama.write_agent = self.saved


class FakeLlamaServer:
    """llama-server's /health, /tokenize, /detokenize and /v1/chat/completions, in a thread; a token per word.
    A completion decodes `decode` tokens and takes `delay` seconds; /props says `slots` slots."""

    def __init__(self, decode=5, delay=0.0, slots=1):
        import http.server
        self.seen, self.finished = [], []
        seen, finished = self.seen, self.finished

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):  # /health, /props
                data = json.dumps({"total_slots": slots} if self.path == "/props" else {}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen.append((self.path, body))
                if self.path == "/tokenize":
                    out = {"tokens": list(range(len(body["content"].split())))}
                elif self.path == "/detokenize":
                    out = {"content": " ".join("w" for _ in body["tokens"])}
                else:
                    time.sleep(delay)
                    finished.append(time.monotonic())
                    out = {"choices": [{"message": {"content": " text from llama "}}],
                           "timings": {"prompt_n": 30, "cache_n": 6, "prompt_ms": 400.0, "prompt_per_second": 75.0,
                                       "predicted_n": decode, "predicted_per_second": 40.0}}
                data = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def model(self):
        return llama.LlamaModel("e4b", {"llamaServer": self.url})

    def completions(self):
        return [body for path, body in self.seen if path == "/v1/chat/completions"]

    def close(self):
        self.httpd.shutdown()
