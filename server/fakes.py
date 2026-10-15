"""Shared pieces of the server's tests: audio, stub models and a fake llama-server. Not a test module."""
import array
import asyncio
import json
import tempfile
import threading
import time
import types

import llama
import metrics
import recordings
from audio import RATE

# No test waits for a real llama-server, touches the real launchd agents or asks macOS about the microphone.
llama.wait_healthy = lambda url, seconds=180: True
recordings.input_info = lambda: None
metrics.METRICS = tempfile.mkdtemp(prefix="gemma-voice-test-metrics-") + "/metrics.jsonl"  # never the real metrics

LOUD = array.array("h", [8000, -8000] * (RATE // 2)).tobytes()  # 1 s, about -12 dBFS
QUIET = b"\0\0" * RATE  # 1 s of silence
ENTRIES = {"gemma-e4b": {"llamaServer": "http://127.0.0.1:9"}, "gemma-12b": {"llamaServer": "http://127.0.0.1:9"}}


def args(**over):
    """The recording settings protocol.handle() gets; recordings never go to the real ~/speech/recordings."""
    return types.SimpleNamespace(**{"threshold_db": -45, "speech_above_noise_db": 12, "piece_seconds": 20,
                                    "cut_search_seconds": 3, "output_tokens_per_second": 10, "output_tokens_base": 32,
                                    "recordings": tempfile.mkdtemp(prefix="gemma-voice-test-recordings-"),
                                    "save_recordings": True, **over})


def seconds(pcm):
    return len(pcm) / 2 / RATE


class StubDictation:
    def __init__(self, stub, text_prompt, options):
        self.stub, self.prompt, self.options = stub, text_prompt, options

    async def prepare(self, context=None):
        self.stub.contexts.append(context)

    async def piece(self, pcm, piece):
        self.stub.calls.append((round(seconds(pcm), 1), self.prompt, self.options))
        return f"{self.stub.name} piece {len(self.stub.calls)}"

    def close(self):
        self.stub.dictations_closed += 1


class StubModel:
    def __init__(self, name="gemma-e4b", entry=None):
        self.name, self.calls, self.contexts, self.dictations_closed = name, [], [], 0

    def dictation(self, text_prompt, options=None, meta=None, save_dir=None, **kw):
        self.save_dir = save_dir
        return StubDictation(self, text_prompt, options or {})


def stub_models(entries=ENTRIES, make=None):
    models = llama.Models(entries, make=make or StubModel)
    models.manage = False
    return models


class FakeAgents:
    """start_agent and stop_agent of the server, recorded instead of run."""

    def __enter__(self):
        self.calls, self.saved = [], (llama.start_agent, llama.stop_agent)
        llama.start_agent = lambda label: self.calls.append(("start", label))
        llama.stop_agent = lambda label: self.calls.append(("stop", label))
        return self

    def __exit__(self, *exc):
        llama.start_agent, llama.stop_agent = self.saved


class FakeLlamaServer:
    """llama-server's /health, /tokenize, /detokenize and /v1/chat/completions, in a thread; a token per word.
    A completion decodes `decode` tokens and takes `delay` seconds."""

    def __init__(self, decode=5, delay=0.0):
        import http.server
        self.seen, self.finished = [], []
        seen, finished = self.seen, self.finished

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):  # /health
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

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


class HangingDictation(StubDictation):
    """A model request that never ends unless cancelled."""

    async def piece(self, pcm, piece):
        self.stub.calls.append(round(seconds(pcm), 1))
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            self.stub.cancelled = True
            raise


class HangingStub(StubModel):
    def dictation(self, text_prompt, options=None, meta=None, save_dir=None, **kw):
        return HangingDictation(self, text_prompt, options or {})
