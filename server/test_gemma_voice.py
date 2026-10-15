"""Tests of the voice_stream server without the model: a stub stands in for Gemma.
Run: server/.venv/bin/python -m unittest discover -s server"""
import array
import asyncio
import base64
import json
import os
import tempfile
import threading
import time
import types
import unittest

import context
import gemma_voice as g
import recordings
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

g.RECORDINGS = tempfile.mkdtemp(prefix="gemma-voice-test-recordings-")  # never the real ~/speech/recordings
g.METRICS = os.path.join(tempfile.mkdtemp(prefix="gemma-voice-test-metrics-"), "metrics.jsonl")  # never the real metrics
LOUD = array.array("h", [8000, -8000] * (g.RATE // 2)).tobytes()  # 1 s, about -12 dBFS
QUIET = b"\0\0" * g.RATE  # 1 s of silence


def seconds(pcm):
    return len(pcm) / 2 / g.RATE


def levels(pcm, chunk=None):
    lv = g.Levels(-45)
    for i in range(0, len(pcm), chunk or len(pcm) or 1):
        lv.feed(pcm[i:i + (chunk or len(pcm))])
    return lv


def split(pcm, piece_s=20, search_s=3):
    lv = levels(pcm)
    return [round(seconds(p), 1) for p in g.split(pcm, lv.rms, lv.threshold, piece_s, search_s)]


class SplitTest(unittest.TestCase):
    def test_a_recording_near_the_wanted_length_is_one_piece(self):
        self.assertEqual(split(LOUD + QUIET + LOUD), [3.0])
        self.assertEqual(split(LOUD * 28), [28.0])  # round(28 / 20) = 1, and 28 s fits the model

    def test_silence_never_becomes_a_piece(self):
        self.assertEqual(split(QUIET * 3), [])

    def test_pieces_are_equal_and_as_close_to_the_wanted_length_as_possible(self):
        self.assertEqual(split(LOUD * 45), [22.5, 22.5])  # 2 pieces of 22.5 s, not 20 + 20 + 5
        self.assertEqual(sorted(split(LOUD * 62)), [20.6, 20.7, 20.7])

    def test_none_is_longer_than_the_model_takes(self):
        self.assertTrue(all(x <= 30 for x in split(LOUD * 61, piece_s=30)))
        self.assertEqual(len(split(LOUD * 61, piece_s=30)), 3)  # round(61 / 30) = 2 would make 30.5 s pieces

    def test_a_cut_moves_into_the_nearest_pause(self):
        pieces = split(LOUD * 19 + QUIET + LOUD * 21)  # the equal point is 20.5 s, the pause 19 to 20 s
        self.assertEqual(len(pieces), 2)
        self.assertTrue(19.0 <= pieces[0] <= 20.0, pieces)


def tone(amplitude, seconds=1):
    return array.array("h", [amplitude, -amplitude] * int(g.RATE * seconds / 2)).tobytes()


class LevelsTest(unittest.TestCase):
    def test_the_threshold_follows_the_noise_floor_of_a_loud_microphone(self):
        noise, speech = tone(100), tone(2300)  # -50.3 and -23.1 dBFS: a microphone at full input volume
        lv = levels(noise * 3 + speech + noise * 3 + speech)
        r = lv.report()
        self.assertEqual(r["noise_floor_dbfs"], -50.3)
        self.assertEqual(r["threshold_dbfs"], -38.3)  # the floor + 12 dB, above -45
        self.assertAlmostEqual(r["speech_fraction"], 0.25, delta=0.01)  # the noise is not speech
        self.assertEqual(split(noise * 3), [])  # and alone never becomes a piece

    def test_a_quiet_microphone_keeps_the_lowest_threshold(self):
        r = levels(tone(20) * 3 + tone(500)).report()  # noise -64.3, speech -36.3 dBFS
        self.assertEqual(r["threshold_dbfs"], -45.0)
        self.assertAlmostEqual(r["speech_fraction"], 0.25, delta=0.01)

    def test_speech_without_pauses_still_counts(self):
        self.assertEqual(levels(LOUD * 5).report()["speech_fraction"], 1.0)  # the cap: 6 dB under the 90th percentile
        self.assertEqual(split(LOUD * 5), [5.0])


    def test_speech_noise_clipping_and_digital_silence(self):
        clip = array.array("h", [32767, -32768] * (g.RATE // 2)).tobytes()
        r = levels(LOUD * 2 + QUIET + clip).report()
        self.assertEqual(r["seconds"], 3.99)
        self.assertEqual(r["peak_dbfs"], 0.0)
        self.assertEqual(r["clipped_samples"], 33 * g.FRAME)  # whole 30 ms frames; the last 10 ms wait for more
        self.assertGreaterEqual(r["longest_digital_silence_s"], 0.96)  # the 1 s of zeros
        self.assertEqual(len(r["dbfs_per_second"]), 4)

    def test_chunks_of_any_size_give_the_same_levels(self):
        data = LOUD + QUIET + LOUD
        self.assertEqual(levels(data, 999).rms, levels(data).rms)  # frames and samples split across chunks




# No test waits for a real llama-server, touches the real launchd agents or asks macOS about the microphone.
recordings.input_info = lambda: None
g.wait_healthy = lambda url, seconds=180: True
ENTRIES = {"gemma-e4b": {"llamaServer": "http://127.0.0.1:9"}, "gemma-12b": {"llamaServer": "http://127.0.0.1:9"}}
ARGS = types.SimpleNamespace(threshold_db=-45, speech_above_noise_db=12, piece_seconds=20, cut_search_seconds=3)


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

    def dictation(self, text_prompt, options=None, meta=None, save_dir=None):
        self.save_dir = save_dir
        return StubDictation(self, text_prompt, options or {})


def stub_models(entries=ENTRIES, make=None):
    models = g.Models(entries, make=make or StubModel)
    models.manage = False
    return models


class FakeAgents:
    """start_agent and stop_agent of the server, recorded instead of run."""

    def __enter__(self):
        self.calls, self.saved = [], (g.start_agent, g.stop_agent)
        g.start_agent = lambda label: self.calls.append(("start", label))
        g.stop_agent = lambda label: self.calls.append(("stop", label))
        return self

    def __exit__(self, *exc):
        g.start_agent, g.stop_agent = self.saved


class ModelsTest(unittest.IsolatedAsyncioTestCase):
    async def test_one_model_in_memory_at_a_time(self):
        entries = {"a": {"llamaServer": "http://h:1", "launchd": "x.a"}, "b": {"llamaServer": "http://h:2", "launchd": "x.b"}}
        with FakeAgents() as agents:
            models = g.Models(entries, make=StubModel)
            a = await models.get("a")
            self.assertIs(await models.get("a"), a)  # made once
            self.assertEqual(agents.calls[:2], [("stop", "x.b"), ("start", "x.a")])
            await models.get("b")
            self.assertEqual(agents.calls[-2:], [("stop", "x.a"), ("start", "x.b")])


class OptionsTest(unittest.TestCase):
    def test_known_options_are_checked_and_renamed(self):
        self.assertEqual(g.parse_options({"temperature": 0, "topK": 1, "maxOutputTokens": 200, "pieceSeconds": 10}),
                         {"temperature": 0.0, "top_k": 1, "max_output_tokens": 200, "piece_seconds": 10.0})
        self.assertEqual(g.parse_options(None), {})

    def test_unknown_or_wrong_options_are_refused(self):
        for bad, why in [({"tempreature": 0}, "unknown option"), ({"topK": 1.5}, "integer"), ({"topP": 2}, "out of range"),
                         ({"pieceSeconds": 45}, "out of range"), ({"temperature": "0"}, "number"), ({"topK": True}, "integer"),
                         ({"noRepeatNgramSize": 10}, "unknown option"), ([1], "object")]:
            with self.assertRaisesRegex(ValueError, why):
                g.parse_options(bad)


class PromptTest(unittest.TestCase):
    def test_googles_asr_template_with_the_language(self):
        self.assertTrue(g.prompt("ru").startswith("Transcribe the following speech segment in Russian into Russian text."))
        self.assertIn("write the digits", g.prompt("ru"))

    def test_the_clients_prompt_with_the_language_filled_in(self):
        self.assertEqual(g.prompt("ru", "Say it in {LANGUAGE}."), "Say it in Russian.")
        self.assertEqual(g.prompt("xx", "Say it in {LANGUAGE}."), "Say it in its original language.")

    def test_unknown_language_uses_the_original_language_form(self):
        self.assertTrue(g.prompt("xx").startswith("Transcribe the following speech segment in its original language."))


class ProtocolTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.saved = recordings.input_info, g.SAVE_RECORDINGS
        recordings.input_info = lambda: {"inputVolume": 50, "device": None}  # no osascript or system_profiler in tests

    def tearDown(self):
        recordings.input_info, g.SAVE_RECORDINGS = self.saved

    async def run_stream(self, start, audio, path="", entries=ENTRIES, stop=None):
        stubs = {}
        models = stub_models(entries, make=lambda name, entry: stubs.setdefault(name, StubModel(name)))
        async with serve(lambda ws: g.handle(ws, models, ARGS), "127.0.0.1", 0, max_size=None) as server:
            port = server.sockets[0].getsockname()[1]
            got = []
            async with connect(f"ws://127.0.0.1:{port}{path}") as ws:
                try:  # a server that refuses the stream closes it while the client still sends
                    await ws.send(json.dumps(start))
                    for i in range(0, len(audio), 3200):
                        await ws.send(audio[i:i + 3200])
                    await ws.send(json.dumps(stop or {"type": "stop"}))
                except ConnectionClosed:
                    pass
                async for m in ws:
                    got.append(json.loads(m))
            self.loaded = sorted(stubs)
            return next(iter(stubs.values()), StubModel("none")), got

    async def test_speech_then_pieces_in_order_then_done(self):
        stub, got = await self.run_stream({"type": "start", "language": "ru", "sampleRate": 16000,
                                           "encoding": "pcm_s16le"}, LOUD + QUIET + LOUD)
        self.assertEqual(got[0], {"type": "speech"})
        self.assertEqual([m for m in got if m["type"] != "speech"],
                         [{"type": "text", "text": "gemma-e4b piece 1"}, {"type": "done"}])  # 3 s: one piece
        self.assertTrue(all(c[1].startswith("Transcribe the following speech segment in Russian") for c in stub.calls))

    async def test_each_recording_gets_a_folder_with_the_audio_and_adapter_json(self):
        stub, got = await self.run_stream({"type": "start", "model": "gemma-12b", "language": "ru", "client": "vscode"},
                                          LOUD * 2, stop={"type": "stop", "reason": "silence"})
        self.assertTrue(stub.save_dir.startswith(g.RECORDINGS))
        self.assertEqual(sorted(os.listdir(stub.save_dir)), ["adapter.json", "audio.json", "mic.wav"])
        self.assertEqual(os.path.getsize(os.path.join(stub.save_dir, "mic.wav")), 44 + 2 * 32000)
        a = json.load(open(os.path.join(stub.save_dir, "adapter.json")))
        self.assertEqual((a["model"], a["client"], a["language"], a["stopReason"], a["text"], a["audioSeconds"]),
                         ("gemma-12b", "vscode", "ru", "silence", "gemma-12b piece 1", 2.0))
        self.assertEqual(a["input"], {"inputVolume": 50, "device": None})
        self.assertIsNone(a["session"])  # no sessions named and no app: no chat context
        g.SAVE_RECORDINGS = False
        stub, got = await self.run_stream({"type": "start", "language": "ru"}, LOUD)
        self.assertIsNone(stub.save_dir)

    async def test_the_models_prompt_reaches_the_model_and_a_clients_prompt_overrides_it(self):
        entries = {"g": {"llamaServer": "http://127.0.0.1:9", "prompt": "Write {LANGUAGE} words."}}
        stub, got = await self.run_stream({"type": "start", "language": "ru"}, LOUD, entries=entries)
        stub2, got = await self.run_stream({"type": "start", "language": "ru", "prompt": "Mine in {LANGUAGE}."}, LOUD,
                                           entries=entries)
        self.assertEqual([c[1] for c in stub.calls + stub2.calls], ["Write Russian words.", "Mine in Russian."])

    async def test_the_start_message_chooses_the_model(self):
        start = {"type": "start", "language": "ru"}
        stub, got = await self.run_stream({**start, "model": "gemma-12b"}, LOUD)
        self.assertEqual(got[-2:], [{"type": "text", "text": "gemma-12b piece 1"}, {"type": "done"}])
        self.assertEqual(self.loaded, ["gemma-12b"])
        stub, got = await self.run_stream(start, LOUD, "/gemma-12b")  # the URL path of earlier clients
        self.assertEqual(got[-2]["text"], "gemma-12b piece 1")
        for legacy in ("", "/voice_stream"):  # no name: the default model
            stub, got = await self.run_stream(start, LOUD, legacy)
            self.assertEqual(got[-2]["text"], "gemma-e4b piece 1")
        stub, got = await self.run_stream({**start, "model": "gemma-99b"}, LOUD)
        self.assertEqual(got[0]["type"], "error")
        self.assertIn("gemma-e4b, gemma-12b", got[0]["message"])
        self.assertEqual(self.loaded, [])

    async def test_the_chat_context_comes_from_the_sessions_transcript(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "p"))
            reply = {"type": "assistant", "entrypoint": "claude-vscode",
                     "message": {"id": "m1", "stop_reason": "end_turn", "content": [{"type": "text", "text": "Готово."}]}}
            with open(os.path.join(d, "p", "s1.jsonl"), "w") as f:
                f.write(json.dumps(reply) + "\n")
            saved = context.PROJECTS
            context.PROJECTS = d
            try:
                stub, got = await self.run_stream({"type": "start", "language": "ru", "sessions": ["s1"]}, LOUD)
                stub2, got = await self.run_stream({"type": "start", "language": "ru",
                                                    "app": "com.microsoft.VSCode"}, LOUD)
            finally:
                context.PROJECTS = saved
        self.assertEqual(stub.contexts[0]["messages"], [{"role": "assistant", "text": "Готово."}])
        self.assertEqual(stub2.contexts[0]["session"], "s1")  # the app's newest session
        a = json.load(open(os.path.join(stub.save_dir, "adapter.json")))
        self.assertEqual(a["session"], {"id": "s1", "file": os.path.join(d, "p", "s1.jsonl")})

    async def test_a_recording_writes_its_metrics(self):
        saved = g.METRICS
        with tempfile.TemporaryDirectory() as d:
            g.METRICS = os.path.join(d, "metrics.jsonl")
            try:
                await self.run_stream({"type": "start", "language": "ru", "client": "menubar"}, LOUD + QUIET + LOUD)
                lines = [json.loads(l) for l in open(g.METRICS, encoding="utf-8")]
            finally:
                g.METRICS = saved
        self.assertEqual([l["event"] for l in lines], ["audio", "recording"])
        self.assertEqual(lines[0]["speech_fraction"], 0.68)
        self.assertEqual(lines[1]["audio_seconds"], 3.0)
        self.assertEqual((lines[1]["model"], lines[1]["client"], lines[1]["prompt"], lines[1]["stop_reason"]),
                         ("gemma-e4b", "menubar", "default", "user"))
        self.assertGreaterEqual(lines[1]["done_after_stop_seconds"], 0)

    async def test_the_models_options_reach_the_model_and_a_clients_options_override_them(self):
        entries = {"g": {"llamaServer": "http://127.0.0.1:9", "options": {"temperature": 0.5, "pieceSeconds": 5}}}
        stub, got = await self.run_stream({"type": "start", "language": "ru", "options": {"topK": 1, "temperature": 0}},
                                          LOUD * 12, entries=entries)
        self.assertEqual([c[0] for c in stub.calls], [6.0, 6.0])  # pieceSeconds 5: round(12 / 5) = 2 equal pieces
        self.assertEqual(stub.calls[0][2], {"temperature": 0.0, "top_k": 1, "piece_seconds": 5.0})
        stub, got = await self.run_stream({"type": "start", "options": {"topK": 0}}, LOUD)
        self.assertEqual(got[0]["type"], "error")
        self.assertIn("topK", got[0]["message"])

    async def test_another_audio_format_is_refused(self):
        stub, got = await self.run_stream({"type": "start", "sampleRate": 48000}, LOUD)
        self.assertEqual(got[0]["type"], "error")
        self.assertEqual(stub.calls, [])


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
        return g.LlamaModel("e4b", {"llamaServer": self.url})

    def completions(self):
        return [body for path, body in self.seen if path == "/v1/chat/completions"]

    def close(self):
        self.httpd.shutdown()


class DictationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.saved = g.METRICS
        g.METRICS = os.path.join(self.dir.name, "metrics.jsonl")
        self.fake = FakeLlamaServer()

    def tearDown(self):
        g.METRICS = self.saved
        self.fake.close()
        self.dir.cleanup()

    def metrics(self, event):
        return [m for m in (json.loads(l) for l in open(g.METRICS, encoding="utf-8")) if m["event"] == event]

    async def test_each_piece_is_one_request_with_the_text_then_the_audio(self):
        d = self.fake.model().dictation("PROMPT", {"chat_history_token_budget": 20, "seed": 3})
        await d.prepare({"messages": [{"role": "user", "text": "hello there"}], "terms": []})
        self.assertEqual(await d.piece(LOUD * 2, 1), "text from llama")
        await d.piece(LOUD, 2)
        bodies = self.fake.completions()
        self.assertEqual(len(bodies), 2)
        for body in bodies:  # the text, then one piece's audio; never an earlier answer
            parts = body["messages"][0]["content"]
            self.assertEqual([p["type"] for p in parts], ["text", "input_audio"])
            self.assertTrue(parts[0]["text"].endswith("---\n\nPROMPT") and "Speaker: hello there" in parts[0]["text"])
            self.assertEqual(base64.b64decode(parts[1]["input_audio"]["data"])[:4], b"RIFF")
            self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual((bodies[0]["max_tokens"], bodies[0]["cache_prompt"], bodies[0]["seed"]), (52, True, 3))
        m = self.metrics("piece")[0]
        self.assertEqual((m["prefill_tokens"], m["cached_tokens"], m["decode_tokens"]), (30, 6, 5))

    async def test_the_chat_context_fits_the_token_budget_newest_kept(self):
        d = self.fake.model().dictation("PROMPT", {"chat_history_token_budget": 12, "chat_terms_token_budget": 4})
        chat = {"messages": [{"role": "assistant", "text": "new reply here"},       # 4 tokens with the role
                             {"role": "user", "text": "a question asked"},          # 4
                             {"role": "assistant", "text": "an old long reply that does not fit"}],
                "terms": ["GitHub", "Kubernetes", "PostgreSQL"]}  # 2 tokens each with the separator
        await d.prepare(chat)
        self.assertIn("Terms: GitHub, Kubernetes\n", d.text)
        self.assertLess(d.text.index("Speaker: a question asked"), d.text.index("Assistant: new reply here"))
        self.assertNotIn("old long reply", d.text)
        self.assertTrue(d.text.endswith("---\n\nPROMPT"))
        self.assertEqual(self.metrics("prepare")[0]["chat_messages"], 2)

    async def test_a_budget_of_0_turns_the_chat_history_off(self):
        d = self.fake.model().dictation("PROMPT", {"chat_history_token_budget": 0})
        await d.prepare({"messages": [{"role": "user", "text": "hello"}], "terms": ["X"]})
        self.assertEqual(d.text, "PROMPT")

    async def test_the_text_is_limited_by_the_length_of_the_audio(self):
        await self.fake.model().dictation("PROMPT", {}).piece(LOUD * 20, 1)
        await self.fake.model().dictation("PROMPT", {"max_output_tokens": 50}).piece(LOUD * 20, 1)
        self.assertEqual([b["max_tokens"] for b in self.fake.completions()],
                         [20 * g.OUTPUT_TOKENS_PER_SECOND + g.OUTPUT_TOKENS_BASE, 50])
        self.assertEqual([(m["output_limit"], m["output_limit_hit"]) for m in self.metrics("piece")],
                         [(232, False), (50, False)])

    async def test_googles_sampler_unless_the_options_set_one(self):
        await self.fake.model().dictation("PROMPT", {}).piece(LOUD, 1)
        await self.fake.model().dictation("PROMPT", {"top_k": 1, "seed": 3}).piece(LOUD, 1)
        self.assertEqual([{k: b.get(k) for k in ("temperature", "top_k", "top_p", "seed")} for b in self.fake.completions()],
                         [{"temperature": 1.0, "top_k": 64, "top_p": 0.95, "seed": None},
                          {"temperature": 1.0, "top_k": 1, "top_p": 0.95, "seed": 3}])

    async def test_a_text_that_reaches_the_limit_is_logged(self):
        fake = FakeLlamaServer(decode=1000)
        try:
            with self.assertLogs("gemma_voice", "WARNING") as logs:
                await fake.model().dictation("PROMPT", {}).piece(LOUD * 2, 1)
        finally:
            fake.close()
        self.assertIn("reached the limit of 52 tokens", logs.output[0])
        self.assertTrue(self.metrics("piece")[0]["output_limit_hit"])

    async def test_a_named_recording_keeps_the_text_each_piece_and_its_text(self):
        d = self.fake.model().dictation("PROMPT", {}, save_dir=os.path.join(self.dir.name, "2026-10-14", "130152-abcdef"))
        await d.prepare()
        await d.piece(LOUD * 2, 1)
        await d.piece(LOUD, 2)
        files = sorted(os.listdir(d.save_dir))
        self.assertEqual(files, ["piece-1.wav", "piece-2.wav", "pieces.jsonl", "text-before-audio.txt"])
        self.assertEqual(open(os.path.join(d.save_dir, "text-before-audio.txt")).read(), "PROMPT")
        self.assertEqual(os.path.getsize(os.path.join(d.save_dir, "piece-1.wav")), 44 + 2 * 32000)
        lines = [json.loads(l) for l in open(os.path.join(d.save_dir, "pieces.jsonl"), encoding="utf-8")]
        self.assertEqual([(l["piece"], l["text"]) for l in lines], [(1, "text from llama"), (2, "text from llama")])

    async def test_a_cancelled_piece_closes_its_request_at_once(self):
        fake = FakeLlamaServer(delay=2.0)
        try:
            task = asyncio.create_task(fake.model().dictation("PROMPT", {}).piece(LOUD, 1))
            while not fake.seen:
                await asyncio.sleep(0.01)
            t = time.monotonic()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            took = time.monotonic() - t
        finally:
            fake.close()
        self.assertLess(took, 1.0)  # the connection was closed, not waited for (the fake answers after 2 s)
        self.assertEqual(len(self.metrics("cancelled")), 1)

    async def test_the_metrics_have_llama_servers_memory(self):
        m = self.fake.model()
        await m.dictation("PROMPT", {}).piece(LOUD, 1)
        mb = self.metrics("piece")[0]["llama_footprint_mb"]  # the fake runs in this process
        self.assertTrue(mb is None or 1 < mb < 100000, mb)
        self.assertEqual(m.pid, os.getpid())


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
    def dictation(self, text_prompt, options=None, meta=None, save_dir=None):
        return HangingDictation(self, text_prompt, options or {})


class ClientGivesUpTest(unittest.IsolatedAsyncioTestCase):
    async def test_the_last_piece_is_cancelled_when_the_client_closes(self):
        stub = HangingStub()
        models = stub_models({"gemma-e4b": {"llamaServer": "http://127.0.0.1:9"}}, make=lambda *a: stub)
        handled = asyncio.Event()

        async def handler(ws):
            try:
                await g.handle(ws, models, ARGS)
            finally:
                handled.set()

        async with asyncio.timeout(10):  # a server that keeps waiting for the model would hang the test
            async with serve(handler, "127.0.0.1", 0, max_size=None) as server:
                port = server.sockets[0].getsockname()[1]
                async with connect(f"ws://127.0.0.1:{port}") as ws:
                    await ws.send(json.dumps({"type": "start", "language": "ru"}))
                    await ws.send(LOUD)
                    await ws.send(json.dumps({"type": "stop"}))
                    while not stub.calls:
                        await asyncio.sleep(0.01)
                await handled.wait()
        self.assertTrue(getattr(stub, "cancelled", False))


class OneRecordingAtATimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_second_recording_waits_until_the_first_is_closed(self):
        events = []

        class SlowDictation(StubDictation):
            async def prepare(self, context=None):
                events.append(("prepare", self.prompt))

            async def piece(self, pcm, piece):
                await asyncio.sleep(0.2)
                return self.prompt

            def close(self):
                events.append(("close", self.prompt))

        class Stub(StubModel):
            def dictation(self, text_prompt, options=None, meta=None, save_dir=None):
                return SlowDictation(self, text_prompt, options or {})

        stub = Stub()
        models = stub_models({"gemma-e4b": {"llamaServer": "http://127.0.0.1:9"}}, make=lambda *a: stub)

        async def record(prompt, port):
            async with connect(f"ws://127.0.0.1:{port}") as ws:
                await ws.send(json.dumps({"type": "start", "language": "ru", "prompt": prompt}))
                await ws.send(LOUD)
                await ws.send(json.dumps({"type": "stop"}))
                return [json.loads(m) async for m in ws]

        async with asyncio.timeout(10):
            async with serve(lambda ws: g.handle(ws, models, ARGS), "127.0.0.1", 0, max_size=None) as server:
                port = server.sockets[0].getsockname()[1]
                first = asyncio.create_task(record("one", port))
                await asyncio.sleep(0.05)
                second = asyncio.create_task(record("two", port))
                await asyncio.gather(first, second)
        self.assertEqual(events, [("prepare", "one"), ("close", "one"), ("prepare", "two"), ("close", "two")])


class SettingsTest(unittest.IsolatedAsyncioTestCase):
    def cli(self, **given):
        names = {v[0] for v in g.SETTINGS.values() if v[0]}
        return types.SimpleNamespace(**{**{n: None for n in names}, **given})

    def write(self, f, **c):
        json.dump({"version": 2, **c}, open(f, "w"))
        os.utime(f, ns=(time.time_ns(), time.time_ns()))

    def test_the_command_line_wins_then_the_file_then_the_defaults(self):
        models = {"a": {"llamaServer": "http://h:1"}}
        now = g.resolve(self.cli(port=8091), {"port": 9000, "pieceSeconds": 25.0, "models": models})
        self.assertEqual((now["port"], now["pieceSeconds"], now["cutSearchSeconds"], now["models"]), (8091, 25.0, 3.0, models))
        self.assertEqual((g.resolve(self.cli(), {})["models"], g.resolve(self.cli(), {})["saveRecordings"]),
                         (g.MODEL_DEFAULT, True))

    def test_the_file_has_the_registry_at_the_top_and_the_server_in_its_section(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            models = {"a": {"llamaServer": "http://h:1", "launchd": "x.a", "prompt": "P", "options": {"topK": 5}}}
            self.write(f, model="a", models=models, saveRecordings=False, silenceStopSeconds=60,
                       server={"pieceSeconds": 25, "port": 9000})
            self.assertEqual(g.file_settings(f), {"models": models, "saveRecordings": False, "pieceSeconds": 25.0,
                                                  "port": 9000})

    def test_a_wrong_key_or_value_in_the_file_is_left_out(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            self.write(f, models={"a": {"llamaServer": "http://h", "options": {"noRepeatNgramSize": 10}}},
                       server={"pieceSeconds": 25, "outputTokensBase": "many", "colour": "red"})
            with self.assertLogs("gemma_voice", "ERROR") as logs:
                self.assertEqual(g.file_settings(f), {"pieceSeconds": 25.0})
        self.assertEqual(len(logs.output), 3)  # colour, outputTokensBase, models (an unknown option)

    def test_a_file_of_another_version_is_not_read(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            json.dump({"version": 1, "gemmaVoice": {"pieceSeconds": 25}}, open(f, "w"))
            with self.assertLogs("gemma_voice", "ERROR") as logs:
                self.assertIsNone(g.file_settings(f))
        self.assertIn("install.sh migrates", logs.output[0])

    async def test_changes_of_the_file_take_effect_by_their_level(self):
        g.CONFIG_CHECK_S = 0.02
        calls = []

        class FakeModels:
            recording = asyncio.Lock()

            def reconfigure(self, entries):
                calls.append(("reconfigure", entries))

        saved = g.RECORDINGS, g.METRICS, g.SAVE_RECORDINGS
        try:
            with tempfile.TemporaryDirectory() as d:
                f = os.path.join(d, "config.json")
                self.write(f)
                cli, st = self.cli(), types.SimpleNamespace()
                current = g.resolve(cli, {})
                g.apply_recording_settings(st, current)
                stop = asyncio.get_running_loop().create_future()
                task = asyncio.create_task(g.watch_config(cli, FakeModels(), st, current, f, stop, follow=False))
                await asyncio.sleep(0.05)
                self.write(f, server={"pieceSeconds": 25}, saveRecordings=False)  # recording settings
                await asyncio.sleep(0.1)
                self.assertEqual((st.piece_seconds, g.SAVE_RECORDINGS, calls), (25.0, False, []))
                models = {"b": {"llamaServer": "http://h:2"}}
                self.write(f, server={"pieceSeconds": 25}, saveRecordings=False, models=models)  # a model setting
                await asyncio.sleep(0.1)
                self.assertEqual(calls, [("reconfigure", models)])
                self.write(f, server={"pieceSeconds": 25, "port": 9999}, saveRecordings=False, models=models)
                await asyncio.wait_for(stop, 1)  # the process ends
                await task
        finally:
            g.RECORDINGS, g.METRICS, g.SAVE_RECORDINGS = saved


class SelectionTest(unittest.IsolatedAsyncioTestCase):
    async def test_only_the_model_chosen_in_the_menus_is_in_memory(self):
        with FakeAgents() as agents, tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            choose = lambda model: json.dump({"version": 2, "model": model}, open(f, "w"))
            models = g.Models({"e4b": {"llamaServer": "http://127.0.0.1:8093", "launchd": "x.e4b"},
                               "llama": {"llamaServer": "http://127.0.0.1:8092", "launchd": "x.llama"}}, make=StubModel)
            chosen = [object()]
            choose("e4b")
            await g.follow_selection(models, f, chosen)
            self.assertEqual(agents.calls, [("stop", "x.llama"), ("start", "x.e4b")])
            choose("llama")
            await g.follow_selection(models, f, chosen)
            self.assertEqual(agents.calls[-2:], [("stop", "x.e4b"), ("start", "x.llama")])
            choose("anthropic")  # Anthropic: no model in memory
            await g.follow_selection(models, f, chosen)
            self.assertEqual(agents.calls[-2:], [("stop", "x.e4b"), ("stop", "x.llama")])
            models.manage = False  # a test server never starts or stops the agents
            n = len(agents.calls)
            await models.get("llama")
            self.assertEqual(len(agents.calls), n)


if __name__ == "__main__":
    unittest.main()
