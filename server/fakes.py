"""Shared pieces of the server's tests: audio, stub models and a fake llama-server. Not a test module."""
import sandbox  # (before any other import: see sandbox.py)
import array
import json
import tempfile
import threading
import time

import audio
import llama_client
import llama_process
import microphone
import model_registry
import protocol
import settings
import vad
from audio import RATE

# No test waits for a real llama-server, starts one or asks macOS about the microphone. The registry calls
# llama_process's functions, and the session microphone's, through the module, so these replacements reach them
# (test_sandbox.py checks that no other module holds them under a name of its own).
real_wait_healthy = llama_process.wait_healthy  # for the test of the wait itself
llama_process.wait_healthy = lambda url, seconds=0, stop=None: True
microphone.state = lambda: None


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
    built-in Claude adapters enabled."""
    st = settings.recording_settings(settings.in_force({}))
    st.recordings = tempfile.mkdtemp(prefix="recordings-", dir=sandbox.ROOT)
    st.adapters = ["claude-code", "claude-chat"]
    for k, v in over.items():
        setattr(st, k, v)
    return st


def seconds(pcm):
    return audio.seconds(pcm)


class StubModel(llama_client.Model):
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
            raise llama_client.Cancelled("cancelled")
        with self.lock:
            self.order.append(("end", n))
        return f"{self.name} piece {n}", {}


class HangingStub(StubModel):
    """A model request that never ends unless cancelled."""

    def complete(self, text, pcm, limit, options, slot=None):
        with self.lock:
            self.calls.append(round(seconds(pcm), 1))
        self.stop.wait(3600)
        raise llama_client.Cancelled("cancelled")


def stub_models(entries=ENTRIES, make=None, **over):
    return model_registry.Models(entries, make=make or StubModel, manage=False, **over)


class FakeLlama:
    """The server's llama-server processes, recorded instead of run: a model's command is its llamaServer and its
    variant (so another variant is another command), and `calls` has ("start", llamaServer) and ("stop", llamaServer).
    The processes: `procs`."""

    def __enter__(self):
        self.calls, self.procs = [], []
        self.saved = llama_process.command, llama_process.spawn, llama_process.end
        llama_process.command = lambda entry, folder: ["llama-server", entry["llamaServer"],
                                                       str(entry.get("variant", ""))]

        def spawn(argv):
            self.calls.append(("start", argv[1]))
            self.procs.append(sandbox.FakeProcess(argv))
            return self.procs[-1]

        def end(proc):
            self.calls.append(("stop", proc.argv[1]))
            proc.terminate()
        llama_process.spawn, llama_process.end = spawn, end
        return self

    def __exit__(self, *exc):
        llama_process.command, llama_process.spawn, llama_process.end = self.saved


class FakeLlamaServer:
    """llama-server's /health, /props, /tokenize and /v1/chat/completions, in a thread; a token per word.
    A completion decodes `decode` tokens and takes `delay` seconds; /props says `slots` slots. A completion whose text
    has more words than `context` gets llama-server's refusal of a request over a slot's context (HTTP 400)."""

    def __init__(self, decode=5, delay=0.0, slots=1, context=None):
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
                text = " ".join(p.get("text", "") for p in (body.get("messages") or [{}])[0].get("content") or []
                                if isinstance(p, dict))
                if self.path == "/tokenize":
                    out = {"tokens": list(range(len(body["content"].split())))}
                elif context is not None and len(text.split()) > context:
                    data = json.dumps({"error": {"code": 400, "type": "exceed_context_size_error",
                                                 "message": "request exceeds the available context size"}}).encode()
                    self.send_response(400)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
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
        return llama_client.LlamaModel("e4b", {"llamaServer": self.url})

    def completions(self):
        return [body for path, body in self.seen if path == "/v1/chat/completions"]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
