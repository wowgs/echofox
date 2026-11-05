"""Tests of the client protocol (protocol.py, session.py, variants.py, recordings.py), with stub models. Run: server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import asyncio
import glob
import json
import os
import pathlib
import tempfile
import threading
import time
import unittest
from unittest import mock

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

import adapters
import metrics
import microphone
import constants
import prompt
from fakes import ENTRIES, LOUD, QUIET, HangingStub, StubModel, args, handle, stub_models

START = {"type": "start", "language": "ru"}
# The identity of Claude Desktop's Code tab, and the content the app sends for its surface claude-code/desktop
CODE_TAB = {"app": {"bundleId": "com.anthropic.claudefordesktop", "pid": 1, "name": "Claude"}, "window": {"title": "Claude"},
            "webArea": {"url": "https://claude.ai/epitaxy/local_abc", "title": "X - Claude Code"}}
CODE_OUTLINE = {"root": "webArea", "complete": True, "nodes": [{"depth": 0, "role": "AXWebArea"}]}
CONTENT = json.dumps({"type": "content", "tookMs": 5, "surfaces": {"claude-code/desktop": {"outline": CODE_OUTLINE},
                                                                  "other/x": {"outline": {}}}})


SPEAKS_S = 0.2  # how long a test recording lasts before its stop, for the adapters to end

class ProtocolTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.saved = microphone.state
        microphone.state = lambda: {"inputVolume": 50, "device": None}  # no osascript or system_profiler in tests
        self.args = args()

    def tearDown(self):
        microphone.state = self.saved

    async def run_stream(self, start, audio, entries=ENTRIES, stop=None, model=StubModel, between=None):
        stubs = {}
        models = stub_models(entries, make=lambda name, entry: stubs.setdefault(name, model(name)))
        async with serve(lambda ws: handle(ws, models, self.args), "127.0.0.1", 0, max_size=None) as server:
            got = []
            async with connect(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}") as ws:
                try:  # a server that refuses the stream closes it while the client still sends
                    await ws.send(json.dumps(start))
                    for i in range(0, len(audio), 3200):
                        await ws.send(audio[i:i + 3200])
                        if between and i == 0:
                            await ws.send(between)
                    await asyncio.sleep(SPEAKS_S)  # the speaker talks; the adapters' context is waited for until the stop
                    await ws.send(json.dumps(stop or {"type": "stop"}))
                except ConnectionClosed:
                    pass
                async for m in ws:
                    got.append(json.loads(m))
            self.loaded = sorted(stubs)
            self.reads = [m for m in got if m["type"] == "read"]  # the read request, apart from the recording's messages
            return next(iter(stubs.values()), StubModel("none")), [m for m in got if m["type"] != "read"]

    def latest(self):
        """The newest recording folder and its adapter.json."""
        d = max(glob.glob(os.path.join(self.args.recordings, "*", "*")), key=os.path.getmtime)
        return d, json.loads(pathlib.Path(d, "adapter.json").read_text(encoding="utf-8"))

    async def ask_info(self):
        async with serve(lambda ws: handle(ws, stub_models(), self.args), "127.0.0.1", 0) as server:
            async with connect(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}") as ws:
                await ws.send(json.dumps({"type": "info"}))
                return json.loads(await ws.recv())

    async def test_silence_is_never_speech_and_never_goes_to_the_model(self):
        stub, got = await self.run_stream(START, QUIET * 25)  # 25 s: a piece cut while "speaking", and the rest
        self.assertEqual([m["type"] for m in got], ["done"])
        self.assertEqual(stub.calls, [])

    async def test_speech_then_pieces_in_order_then_done(self):
        stub, got = await self.run_stream({**START, "sampleRate": 16000, "encoding": "pcm_s16le"}, LOUD + QUIET + LOUD)
        self.assertEqual(got[0], {"type": "speech"})
        self.assertEqual([m for m in got if m["type"] != "speech"],
                         [{"type": "text", "text": "gemma-e4b piece 1"}, {"type": "done"}])  # 3 s: one piece
        self.assertTrue(stub.calls[0][1].startswith("Transcribe the following speech segment in Russian"))
        self.assertEqual(stub.begun, 1)

    async def test_the_text_is_warmed_while_the_speaker_talks_and_pieces_run_at_once_in_order(self):
        class TwoSlots(StubModel):
            def __init__(self, name):
                super().__init__(name, slots_n=2)

            def complete(self, text, pcm, limit, options, slot=None):
                with self.lock:
                    self.order.append(("start", slot))
                time.sleep(0.3 if slot == 0 else 0.05)  # the first piece ends last
                with self.lock:
                    self.order.append(("end", slot))
                return f"slot {slot}", {}

        self.args.piece_seconds = 5  # 12 s: two pieces; the second slot is warmed once 5 s are heard
        self.args.cut_while_speaking = False  # both pieces are cut at the stop
        stub, got = await self.run_stream(START, (LOUD + QUIET) * 6, model=TwoSlots)
        self.assertEqual([m["text"] for m in got if m["type"] == "text"], ["slot 0", "slot 1"])  # the pieces' order
        self.assertEqual(stub.warmed, [0, 1])
        self.assertEqual(sorted(stub.order[:2]), [("start", 0), ("start", 1)])  # both at once, one per slot
        self.assertEqual(stub.order[2:], [("end", 1), ("end", 0)])

    async def test_pieces_are_cut_while_the_speaker_talks_and_the_rest_at_the_stop(self):
        self.args.piece_seconds, self.args.min_last_piece_seconds = 5, 5
        self.args.min_piece_seconds = self.args.max_piece_seconds = 5  # no pause in a tone: each cut at 5 s
        with tempfile.TemporaryDirectory() as d:
            file = os.path.join(d, "metrics.jsonl")
            saved = metrics.configure(file)
            try:
                stub, got = await self.run_stream(START, LOUD * 22)
                lines = [json.loads(l) for l in pathlib.Path(file).read_text(encoding="utf-8").splitlines()]
            finally:
                metrics.configure(saved)
        # Cuts once 10, 15 and 20 s are heard, at 5, 10 and 15 s; the 7 s left are one piece at the stop.
        self.assertEqual(sorted(c[0] for c in stub.calls), [5.0, 5.0, 5.0, 7.0])  # the calls run at once
        self.assertEqual(len([m for m in got if m["type"] == "text"]), 4)
        r = next(l for l in lines if l["event"] == "recording")
        self.assertEqual(r["pieces_while_speaking"], 3)
        self.assertAlmostEqual(r["seconds_left_at_stop"], 7.0, delta=0.1)  # cuts fall on 30 ms frames

    async def test_a_recording_too_short_for_a_cut_is_cut_at_the_stop(self):
        self.args.piece_seconds, self.args.min_last_piece_seconds = 5, 5
        self.args.min_piece_seconds = self.args.max_piece_seconds = 5  # no pause in a tone: each cut at 5 s
        stub, got = await self.run_stream(START, LOUD * 7)  # 7 s < 5 + 5: no cut while speaking
        self.assertEqual([c[0] for c in stub.calls], [7.0])  # and at the stop round(7 / 5) = 1 piece

    async def test_a_private_dictation_saves_nothing_has_no_context_and_logs_no_text(self):
        with tempfile.TemporaryDirectory() as d:  # a session the Claude adapter would find, as in the test below
            os.makedirs(os.path.join(d, "projects", "p"))
            os.makedirs(os.path.join(d, "store", "o", "a"))
            reply = {"type": "assistant",
                     "message": {"id": "m1", "stop_reason": "end_turn", "content": [{"type": "text", "text": "Готово."}]}}
            with open(os.path.join(d, "projects", "p", "s1.jsonl"), "w") as f:
                f.write(json.dumps(reply) + "\n")
            with open(os.path.join(d, "store", "o", "a", "local_abc.json"), "w") as f:
                json.dump({"cliSessionId": "s1"}, f)
            env = mock.patch.dict(os.environ, {"ECHOFOX_PROJECTS": os.path.join(d, "projects"),
                                               "ECHOFOX_DESKTOP_SESSIONS": os.path.join(d, "store")})
            env.start()
            before = set(glob.glob(os.path.join(self.args.recordings, "*", "*")))
            try:
                with self.assertLogs("echofox-server", level="INFO") as logs:
                    stub, got = await self.run_stream({**START, "private": True, "identity": CODE_TAB}, LOUD,
                                                      between=CONTENT)
            finally:
                env.stop()
        self.assertEqual(self.reads, [])  # no read request
        self.assertEqual([m["text"] for m in got if m["type"] == "text"], ["gemma-e4b piece 1"])
        self.assertEqual(set(glob.glob(os.path.join(self.args.recordings, "*", "*"))), before)  # no recording folder
        self.assertNotIn("Готово.", stub.calls[0][1])  # no context before the prompt
        self.assertFalse(any("gemma-e4b piece 1" in line for line in logs.output))

    async def test_a_client_asks_what_the_server_offers(self):
        self.args.adapters = ["claude-code", "claude-chat"]
        got = await self.ask_info()
        self.assertEqual((got["type"], got["interface"], got["sampleRate"], got["encoding"], got["textWaitSeconds"]),
                         ("info", constants.PROTOCOL_INTERFACE, 16000, "pcm_s16le", 180))
        by = {a["name"]: a for a in got["adapters"]}
        code, chat = by["claude-code"], by["claude-chat"]
        self.assertTrue(code["enabled"] and code["builtin"] and chat["enabled"])
        desktop, terminal = code["surfaces"]
        self.assertEqual((code["title"], desktop["apps"], desktop["treeOnRequest"], desktop["match"], list(desktop["screen"]),
                          chat["surfaces"][0]["match"]),
                         ("Claude Code", ["com.anthropic.claudefordesktop"], True, {"url": "https://claude.ai/epitaxy/*"},
                          ["outline"], {"url": "https://claude.ai/chat/*"}))
        self.assertIn("com.mitchellh.ghostty", terminal["apps"])  # a terminal, which builds its tree without asking
        self.assertNotIn("treeOnRequest", terminal)
        self.args.adapters = []
        self.assertFalse(any(a["enabled"] for a in (await self.ask_info())["adapters"]))

    async def test_adapters_still_running_at_the_stop_cost_the_context_not_the_dictation(self):
        saved, release = adapters.context, threading.Event()
        adapters.context = lambda *a: release.wait(5)
        try:
            stub, got = await self.run_stream({**START, "identity": CODE_TAB}, LOUD, between=CONTENT)
        finally:
            release.set()  # the hung call ends, so that the next tests' dictations get their context
            adapters._running.result(5)
            adapters.context = saved
        self.assertEqual([m["type"] for m in got if m["type"] != "speech"], ["text", "done"])
        self.assertIn("no context by the stop", self.latest()[1]["chat"]["errors"][0])

    async def test_without_warm_text_nothing_is_warmed(self):
        self.args.warm_text = False
        stub, got = await self.run_stream(START, LOUD)
        self.assertEqual((stub.warmed, len(stub.calls)), ([], 1))

    async def test_each_recording_gets_a_folder_with_the_audio_and_adapter_json(self):
        stub, got = await self.run_stream({**START, "model": "gemma-12b", "client": "menubar"}, LOUD * 2,
                                          stop={"type": "stop", "reason": "silence"})
        d, a = self.latest()
        self.assertTrue(d.startswith(self.args.recordings))
        self.assertEqual(sorted(os.listdir(d)), ["adapter.json", "audio.json", "mic.wav", "piece-1.wav", "pieces.jsonl",
                                                 "text-before-audio.txt"])
        self.assertEqual(os.path.getsize(os.path.join(d, "mic.wav")), 44 + 2 * 32000)
        self.assertEqual((a["model"], a["client"], a["language"], a["stopReason"], a["text"], a["audioSeconds"]),
                         ("gemma-12b", "menubar", "ru", "silence", "gemma-12b piece 1", 2.0))
        self.assertEqual(a["input"], {"inputVolume": 50, "device": None})
        self.assertEqual((a["chat"], a["identity"], a["surfaces"]), (None, None, []))  # no app
        self.assertEqual([r["surfaces"] for r in self.reads], [[]])  # a read request without surfaces
        self.args.save_recordings = False
        n = len(glob.glob(os.path.join(self.args.recordings, "*", "*")))
        await self.run_stream(START, LOUD)
        self.assertEqual(len(glob.glob(os.path.join(self.args.recordings, "*", "*"))), n)

    async def test_the_models_prompt_reaches_the_model_and_a_clients_prompt_overrides_it(self):
        entries = {"g": {"llamaServer": "http://127.0.0.1:9", "prompt": "Write {LANGUAGE} words."}}
        english = {**START, "language": "en"}  # English has no notes to add
        stub, got = await self.run_stream(english, LOUD, entries=entries)
        stub2, got = await self.run_stream({**english, "prompt": "Mine in {LANGUAGE}."}, LOUD, entries=entries)
        self.assertEqual([c[1] for c in stub.calls + stub2.calls], ["Write English words.", "Mine in English."])

    async def test_the_start_message_chooses_the_model(self):
        stub, got = await self.run_stream({**START, "model": "gemma-12b"}, LOUD)
        self.assertEqual(got[-2:], [{"type": "text", "text": "gemma-12b piece 1"}, {"type": "done"}])
        self.assertEqual(self.loaded, ["gemma-12b"])
        stub, got = await self.run_stream(START, LOUD)  # no name: the default model
        self.assertEqual(got[-2]["text"], "gemma-e4b piece 1")
        stub, got = await self.run_stream({**START, "model": "gemma-99b"}, LOUD)
        self.assertEqual(got[0]["type"], "error")
        self.assertIn("gemma-e4b, gemma-12b", got[0]["message"])
        self.assertEqual(self.loaded, [])

    async def test_the_context_comes_from_the_surface_the_identity_is_on_once_its_content_came(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "projects", "p"))
            os.makedirs(os.path.join(d, "store", "o", "a"))
            reply = {"type": "assistant",
                     "message": {"id": "m1", "stop_reason": "end_turn", "content": [{"type": "text", "text": "Готово."}]}}
            with open(os.path.join(d, "projects", "p", "s1.jsonl"), "w") as f:
                f.write(json.dumps(reply) + "\n")
            with open(os.path.join(d, "store", "o", "a", "local_abc.json"), "w") as f:
                json.dump({"cliSessionId": "s1"}, f)
            env = mock.patch.dict(os.environ, {"ECHOFOX_PROJECTS": os.path.join(d, "projects"),
                                               "ECHOFOX_DESKTOP_SESSIONS": os.path.join(d, "store")})
            env.start()
            self.args.adapter_config = {"claude-chat": {"chat_history_token_budget": 300}}
            try:
                stub, got = await self.run_stream({**START, "identity": CODE_TAB}, LOUD, between=CONTENT)
                read, a = self.reads, self.latest()[1]
                await self.run_stream({**START, "identity": CODE_TAB}, LOUD)  # the app sent no content by the stop
                late = self.latest()[1]
                chat = {**CODE_TAB, "webArea": {"url": "https://claude.ai/chat/1"}}
                await self.run_stream({**START, "identity": chat}, LOUD)
                chat_read = self.reads
            finally:
                env.stop()
        self.assertEqual(read, [{"type": "read", "tokenWeights": read[0]["tokenWeights"], "surfaces": [
            {"surface": "claude-code/desktop",
             "outline": {"skip": ["epitaxy-document-page", "group/file-tree", "epitaxy-chat-panel-body"], "budget": None}}]}])
        self.assertTrue(read[0]["tokenWeights"]["cyrillic"] > 0)  # the model's, for the app's estimate
        self.assertEqual(chat_read[0]["surfaces"][0]["outline"]["budget"], 300)  # the config's entry
        self.assertIn("Claude: Готово.", stub.calls[0][1])
        self.assertTrue(stub.calls[0][1].endswith("</context>\n\n" + prompt.text("ru")))  # the context, then the prompt
        self.assertEqual((a["chat"]["adapter"], a["chat"]["surface"], a["chat"]["details"]["how"],
                          a["chat"]["details"]["desktopSession"], a["chat"]["details"]["session"]),
                         ("claude-code", "claude-code/desktop", "desktop store", "local_abc", "s1"))
        # The record keeps the identity and the matched surfaces, never what the app read on the screen
        self.assertEqual((a["identity"], a["surfaces"], "content" in a), (CODE_TAB, ["claude-code/desktop"], False))
        self.assertEqual(late["chat"], {"errors": ["no content by the stop"]})

    async def test_the_read_request_comes_at_once_while_another_recording_holds_the_model(self):
        models = stub_models(ENTRIES, make=lambda name, entry: HangingStub(name))
        async with asyncio.timeout(10):
            async with serve(lambda ws: handle(ws, models, self.args), "127.0.0.1", 0, max_size=None) as server:
                url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
                async with connect(url) as first, connect(url) as second:
                    await first.send(json.dumps(START))
                    await first.send(LOUD)
                    await first.send(json.dumps({"type": "stop"}))
                    while not models.in_use.locked():
                        await asyncio.sleep(0.01)
                    await second.send(json.dumps({**START, "identity": CODE_TAB}))
                    self.assertEqual(json.loads(await second.recv())["surfaces"][0]["surface"], "claude-code/desktop")
                    self.assertTrue(models.in_use.locked())  # the first recording still holds the model

    async def test_a_recording_writes_its_metrics_under_the_id_of_its_folder(self):
        with tempfile.TemporaryDirectory() as d:
            file = os.path.join(d, "metrics.jsonl")
            saved = metrics.configure(file)
            try:
                await self.run_stream({**START, "client": "menubar"}, LOUD + QUIET + LOUD)
                lines = [json.loads(l) for l in pathlib.Path(file).read_text(encoding="utf-8").splitlines()]
            finally:
                metrics.configure(saved)
        by = {l["event"]: l for l in lines}
        # "warm" only if the warm-up ended before the piece: once the pieces are done, it is cancelled
        self.assertEqual(sorted(set(by) - {"warm"}), ["audio", "piece", "prepare", "recording"])
        self.assertEqual(by["audio"]["speech_fraction"], 0.68)
        r = by["recording"]
        self.assertEqual((r["audio_seconds"], r["model"], r["client"], r["prompt"], r["stop_reason"]),
                         (3.0, "gemma-e4b", "menubar", "default", "user"))
        self.assertGreaterEqual(r["done_after_stop_seconds"], 0)
        self.assertEqual(r["recording"], self.latest()[1]["id"])

    async def test_the_models_options_reach_the_model_and_a_clients_options_override_them(self):
        entries = {"g": {"llamaServer": "http://127.0.0.1:9", "options": {"temperature": 0.5, "topP": 0.9}}}
        stub, got = await self.run_stream({**START, "options": {"topK": 1, "temperature": 0, "pieceSeconds": 5,
                                                                    "minPieceSeconds": 5, "maxPieceSeconds": 5}},
                                          LOUD * 12, entries=entries)
        self.assertEqual(sorted(c[0] for c in stub.calls), [5.0, 7.0])  # pieceSeconds 5: a cut at 10 s heard, 7 s left
        options = stub.calls[0][2]  # the catalog's defaults, the model's options over them, the client's over both
        self.assertEqual({k: options[k] for k in ("temperature", "top_k", "top_p")},
                         {"temperature": 0.0, "top_k": 1, "top_p": 0.9})
        stub, got = await self.run_stream(START, LOUD, entries={"g": {"llamaServer": "http://127.0.0.1:9",
                                                                      "options": {"pieceSeconds": 5}}})
        self.assertEqual(got[0]["type"], "error")  # a server's setting is not the model's to set
        self.assertIn("pieceSeconds", got[0]["message"])
        stub, got = await self.run_stream({"type": "start", "options": {"topK": 0}}, LOUD)
        self.assertEqual(got[0]["type"], "error")
        self.assertIn("topK", got[0]["message"])

    async def test_another_audio_format_is_refused(self):
        stub, got = await self.run_stream({"type": "start", "sampleRate": 48000}, LOUD)
        self.assertEqual((got[0]["type"], stub.calls), ("error", []))

    async def test_the_server_stops_a_recording_at_the_longest_length_and_says_so(self):
        self.args.max_recording_seconds = 2
        stub, got = await self.run_stream(START, LOUD * 4)
        types = [m["type"] for m in got if m["type"] != "speech"]
        self.assertEqual(types, ["stopped", "text", "done"])
        self.assertEqual(got[[m["type"] for m in got].index("stopped")]["reason"], "max_duration")
        self.assertEqual((stub.calls[0][0], self.latest()[1]["stopReason"]), (2.0, "max_duration"))

    async def test_a_message_that_is_not_json_is_an_error_and_the_recording_goes_on(self):
        stub, got = await self.run_stream(START, LOUD * 2, between="not json")
        self.assertEqual([m["type"] for m in got if m["type"] != "speech"], ["error", "text", "done"])
        self.assertIn("not a JSON object", got[[m["type"] for m in got].index("error")]["message"])


class ClientGivesUpTest(unittest.IsolatedAsyncioTestCase):
    async def test_the_last_piece_is_cancelled_when_the_client_closes(self):
        stub = HangingStub()
        models = stub_models({"gemma-e4b": {"llamaServer": "http://127.0.0.1:9"}}, make=lambda *a: stub)
        handled = asyncio.Event()

        async def handler(ws):
            try:
                await handle(ws, models, args())
            finally:
                handled.set()

        async with asyncio.timeout(10):  # a server that keeps waiting for the model would hang the test
            async with serve(handler, "127.0.0.1", 0, max_size=None) as server:
                async with connect(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}") as ws:
                    await ws.send(json.dumps(START))
                    await ws.send(LOUD)
                    await ws.send(json.dumps({"type": "stop"}))
                    while not stub.calls:
                        await asyncio.sleep(0.01)
                await handled.wait()
        self.assertTrue(stub.cancelled)

    async def test_a_connection_that_ends_without_a_stop_is_recorded_and_frees_the_model(self):
        stub = StubModel()
        models = stub_models({"gemma-e4b": {"llamaServer": "http://127.0.0.1:9"}}, make=lambda *a: stub)
        a = args()
        async with asyncio.timeout(10):
            async with serve(lambda ws: handle(ws, models, a), "127.0.0.1", 0, max_size=None) as server:
                async with connect(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}") as ws:
                    await ws.send(json.dumps(START))
                    await ws.send(LOUD)
                while models.in_use.locked():
                    await asyncio.sleep(0.01)
        d = max(glob.glob(os.path.join(a.recordings, "*", "*")), key=os.path.getmtime)
        rec = json.loads(pathlib.Path(d, "adapter.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["stopReason"], "connection closed")
        self.assertIn("before the stop", rec["error"])


class OneRecordingAtATimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_second_recording_waits_until_the_first_is_closed(self):
        events = []

        class Slow(StubModel):
            def complete(self, text, pcm, limit, options, slot=None):
                events.append(("start", text))
                time.sleep(0.2)
                events.append(("end", text))
                return text, {}

        stub = Slow()
        models = stub_models({"gemma-e4b": {"llamaServer": "http://127.0.0.1:9"}}, make=lambda *a: stub)

        async def record(prompt, port):
            async with connect(f"ws://127.0.0.1:{port}") as ws:
                await ws.send(json.dumps({**START, "language": "en", "prompt": prompt}))  # English: no notes
                await ws.send(LOUD)
                await ws.send(json.dumps({"type": "stop"}))
                return [json.loads(m) async for m in ws]

        async with asyncio.timeout(10):
            async with serve(lambda ws: handle(ws, models, args()), "127.0.0.1", 0, max_size=None) as server:
                port = server.sockets[0].getsockname()[1]
                first = asyncio.create_task(record("one", port))
                await asyncio.sleep(0.05)
                second = asyncio.create_task(record("two", port))
                await asyncio.gather(first, second)
        self.assertEqual(events, [("start", "one"), ("end", "one"), ("start", "two"), ("end", "two")])


if __name__ == "__main__":
    unittest.main()
