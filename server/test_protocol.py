"""Tests of protocol.py: the client protocol, with stub models. Run: server/.venv/bin/python -m unittest discover -s server"""
import asyncio
import json
import os
import tempfile
import unittest

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

import metrics
import protocol
import recordings
from fakes import ENTRIES, LOUD, QUIET, HangingStub, StubDictation, StubModel, args, seconds, stub_models


class ProtocolTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.saved = recordings.input_info
        recordings.input_info = lambda: {"inputVolume": 50, "device": None}  # no osascript or system_profiler in tests
        self.args = args()

    def tearDown(self):
        recordings.input_info = self.saved

    async def run_stream(self, start, audio, path="", entries=ENTRIES, stop=None, model=StubModel):
        stubs = {}
        models = stub_models(entries, make=lambda name, entry: stubs.setdefault(name, model(name)))
        async with serve(lambda ws: protocol.handle(ws, models, self.args), "127.0.0.1", 0, max_size=None) as server:
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

    async def test_the_text_is_warmed_while_the_speaker_talks_and_pieces_run_at_once_in_order(self):
        order = []

        class Unordered(StubDictation):
            async def piece(self, pcm, piece, slot=None):
                order.append(("start", piece, slot))
                await asyncio.sleep(0.3 if piece == 1 else 0.05)  # the first piece ends last
                order.append(("end", piece))
                return f"p{piece}"

        class TwoSlots(StubModel):
            def __init__(self, name):
                super().__init__(name)
                self.slots = 2

            def dictation(self, text_prompt, options=None, meta=None, save_dir=None, **kw):
                return Unordered(self, text_prompt, options or {})

        self.args.piece_seconds = 5  # 12 s: two pieces; the second slot is warmed once 5 s are heard
        stub, got = await self.run_stream({"type": "start"}, (LOUD + QUIET) * 6, model=TwoSlots)
        self.assertEqual([m["text"] for m in got if m["type"] == "text"], ["p1", "p2"])
        self.assertEqual(stub.warmed, [0, 1])
        self.assertEqual(order[:2], [("start", 1, 0), ("start", 2, 1)])  # both at once, one per slot
        self.assertEqual(order[2:], [("end", 2), ("end", 1)])

    async def test_the_app_asks_which_adapters_there_are(self):
        self.args.adapters = ["claude-desktop"]
        async with serve(lambda ws: protocol.handle(ws, stub_models(), self.args), "127.0.0.1", 0) as server:
            async with connect(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}") as ws:
                await ws.send(json.dumps({"type": "adapters"}))
                got = json.loads(await ws.recv())
        by = {a["name"]: a for a in got["adapters"]}
        self.assertEqual((got["type"], got["interface"]), ("adapters", 1))
        self.assertTrue(by["claude-desktop"]["enabled"] and by["claude-desktop"]["electronTree"])
        self.assertEqual(by["claude-desktop"]["apps"], ["com.anthropic.claudefordesktop"])
        self.assertFalse(by["claude-code"]["enabled"])

    async def test_without_warm_text_nothing_is_warmed(self):
        self.args.warm_text = False
        stub, got = await self.run_stream({"type": "start"}, LOUD)
        self.assertEqual(stub.warmed, [])
        self.assertEqual(stub.calls and len(stub.calls), 1)

    async def test_each_recording_gets_a_folder_with_the_audio_and_adapter_json(self):
        stub, got = await self.run_stream({"type": "start", "model": "gemma-12b", "language": "ru", "client": "vscode"},
                                          LOUD * 2, stop={"type": "stop", "reason": "silence"})
        self.assertTrue(stub.save_dir.startswith(self.args.recordings))
        self.assertEqual(sorted(os.listdir(stub.save_dir)), ["adapter.json", "audio.json", "mic.wav"])
        self.assertEqual(os.path.getsize(os.path.join(stub.save_dir, "mic.wav")), 44 + 2 * 32000)
        a = json.load(open(os.path.join(stub.save_dir, "adapter.json")))
        self.assertEqual((a["model"], a["client"], a["language"], a["stopReason"], a["text"], a["audioSeconds"]),
                         ("gemma-12b", "vscode", "ru", "silence", "gemma-12b piece 1", 2.0))
        self.assertEqual(a["input"], {"inputVolume": 50, "device": None})
        self.assertIsNone(a["session"])  # no sessions named and no app: no chat context
        self.args.save_recordings = False
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

    async def test_the_chat_context_comes_from_the_adapter_that_claims_the_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "projects", "p"))
            os.makedirs(os.path.join(d, "store", "o", "a"))
            reply = {"type": "assistant", "entrypoint": "claude-desktop",
                     "message": {"id": "m1", "stop_reason": "end_turn", "content": [{"type": "text", "text": "Готово."}]}}
            with open(os.path.join(d, "projects", "p", "s1.jsonl"), "w") as f:
                f.write(json.dumps(reply) + "\n")
            with open(os.path.join(d, "store", "o", "a", "local_abc.json"), "w") as f:
                json.dump({"cliSessionId": "s1"}, f)
            saved = os.environ.get("LOCAL_VOICE_PROJECTS"), os.environ.get("LOCAL_VOICE_DESKTOP_SESSIONS")
            os.environ.update(LOCAL_VOICE_PROJECTS=os.path.join(d, "projects"),
                              LOCAL_VOICE_DESKTOP_SESSIONS=os.path.join(d, "store"))
            snapshot = {"app": {"bundleId": "com.anthropic.claudefordesktop"},
                        "webArea": {"url": "https://claude.ai/epitaxy/local_abc", "title": "X - Claude Code"}}
            try:
                stub, got = await self.run_stream({"type": "start", "language": "ru", "snapshot": snapshot}, LOUD)
                stub2, got = await self.run_stream({"type": "start", "language": "ru", "sessions": ["s1"]}, LOUD)
            finally:
                for k, v in zip(("LOCAL_VOICE_PROJECTS", "LOCAL_VOICE_DESKTOP_SESSIONS"), saved):
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
        self.assertEqual(stub.contexts[0]["messages"], [{"role": "assistant", "text": "Готово."}])
        self.assertEqual(stub2.contexts[0]["session"], "s1")
        a = json.load(open(os.path.join(stub.save_dir, "adapter.json")))
        self.assertEqual(a["session"], {"id": "s1", "file": os.path.join(d, "projects", "p", "s1.jsonl")})
        self.assertEqual((a["chat"]["adapter"], a["chat"]["how"], a["chat"]["desktopSession"]),
                         ("claude-desktop", "desktop store", "local_abc"))

    async def test_a_recording_writes_its_metrics(self):
        saved = metrics.METRICS
        with tempfile.TemporaryDirectory() as d:
            metrics.METRICS = os.path.join(d, "metrics.jsonl")
            try:
                await self.run_stream({"type": "start", "language": "ru", "client": "menubar"}, LOUD + QUIET + LOUD)
                lines = [json.loads(l) for l in open(metrics.METRICS, encoding="utf-8")]
            finally:
                metrics.METRICS = saved
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


class ClientGivesUpTest(unittest.IsolatedAsyncioTestCase):
    async def test_the_last_piece_is_cancelled_when_the_client_closes(self):
        stub = HangingStub()
        models = stub_models({"gemma-e4b": {"llamaServer": "http://127.0.0.1:9"}}, make=lambda *a: stub)
        handled = asyncio.Event()

        async def handler(ws):
            try:
                await protocol.handle(ws, models, args())
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

            async def piece(self, pcm, piece, slot=None):
                await asyncio.sleep(0.2)
                return self.prompt

            def close(self):
                events.append(("close", self.prompt))

        class Stub(StubModel):
            def dictation(self, text_prompt, options=None, meta=None, save_dir=None, **kw):
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
            async with serve(lambda ws: protocol.handle(ws, models, args()), "127.0.0.1", 0, max_size=None) as server:
                port = server.sockets[0].getsockname()[1]
                first = asyncio.create_task(record("one", port))
                await asyncio.sleep(0.05)
                second = asyncio.create_task(record("two", port))
                await asyncio.gather(first, second)
        self.assertEqual(events, [("prepare", "one"), ("close", "one"), ("prepare", "two"), ("close", "two")])


if __name__ == "__main__":
    unittest.main()
