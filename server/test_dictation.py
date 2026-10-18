"""Tests of dictation.py and llama.LlamaModel against a fake llama-server. Run: server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import asyncio
import base64
import json
import os
import tempfile
import time
import unittest

import dictation as d
import llama
import metrics
import recordings
import tuning
from fakes import LOUD, FakeLlamaServer, StubModel, args


class OptionsTest(unittest.TestCase):
    def test_known_options_are_checked_and_renamed(self):
        self.assertEqual(tuning.parse_options({"temperature": 0, "topK": 1, "maxOutputTokens": 200, "pieceSeconds": 10}),
                         {"temperature": 0.0, "top_k": 1, "max_output_tokens": 200, "piece_seconds": 10.0})
        self.assertEqual(tuning.parse_options(None), {})

    def test_unknown_or_wrong_options_are_refused(self):
        for bad, why in [({"tempreature": 0}, "unknown option"), ({"topK": 1.5}, "integer"), ({"topP": 2}, "out of range"),
                         ({"pieceSeconds": 45}, "out of range"), ({"temperature": "0"}, "number"), ({"topK": True}, "integer"),
                         ({"noRepeatNgramSize": 10}, "unknown option"), ([1], "object")]:
            with self.assertRaisesRegex(ValueError, why):
                tuning.parse_options(bad)


class PromptTest(unittest.TestCase):
    def test_googles_asr_template_with_the_language(self):
        self.assertTrue(d.prompt("ru").startswith("Transcribe the following speech segment in Russian into Russian text."))
        self.assertIn("write the digits", d.prompt("ru"))

    def test_the_clients_prompt_with_the_language_filled_in(self):
        self.assertEqual(d.prompt("ru", "Say it in {LANGUAGE}."), "Say it in Russian.")
        self.assertEqual(d.prompt("xx", "Say it in {LANGUAGE}."), "Say it in its original language.")

    def test_unknown_language_uses_the_original_language_form(self):
        self.assertTrue(d.prompt("xx").startswith("Transcribe the following speech segment in its original language."))


class DictationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.saved = metrics.path()
        metrics.configure(os.path.join(self.dir.name, "metrics.jsonl"))
        self.fake = FakeLlamaServer()

    def tearDown(self):
        metrics.configure(self.saved)
        self.fake.close()
        self.dir.cleanup()

    def metrics(self, event):
        return [m for m in (json.loads(l) for l in open(metrics.path(), encoding="utf-8")) if m["event"] == event]

    def dictation(self, options=None, model=None, recording=None):
        return d.Dictation(model or self.fake.model(), "PROMPT", options or {}, args(), {}, recording)

    async def test_each_piece_is_one_request_with_the_text_then_the_audio(self):
        d = self.dictation({"chat_history_token_budget": 20, "seed": 3})
        await d.prepare({"messages": [{"from": "Anna", "text": "hello there"}], "terms": []})
        self.assertEqual(await d.piece(LOUD * 2, 1), "text from llama")
        await d.piece(LOUD, 2)
        bodies = self.fake.completions()
        self.assertEqual(len(bodies), 2)
        for body in bodies:  # the text, then one piece's audio; never an earlier answer
            parts = body["messages"][0]["content"]
            self.assertEqual([p["type"] for p in parts], ["text", "input_audio"])
            self.assertTrue(parts[0]["text"].endswith("---\n\nPROMPT") and "Anna: hello there" in parts[0]["text"])
            self.assertEqual(base64.b64decode(parts[1]["input_audio"]["data"])[:4], b"RIFF")
            self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual((bodies[0]["max_tokens"], bodies[0]["cache_prompt"], bodies[0]["seed"]), (52, True, 3))
        m = self.metrics("piece")[0]
        self.assertEqual((m["prefill_tokens"], m["cached_tokens"], m["decode_tokens"]), (30, 6, 5))

    async def test_warm_sends_the_same_text_alone_to_the_slot_of_its_piece(self):
        d = self.dictation({"chat_history_token_budget": 20})
        await d.prepare({"messages": [{"from": "Claude", "text": "hello there"}], "terms": []})
        await d.warm(1)
        await d.piece(LOUD, 2, slot=1)
        warm, piece = self.fake.completions()
        self.assertEqual(warm["messages"][0]["content"], [{"type": "text", "text": d.text}])  # no audio
        self.assertEqual((warm["max_tokens"], warm["id_slot"], warm["cache_prompt"]), (0, 1, True))
        self.assertEqual(piece["messages"][0]["content"][0], warm["messages"][0]["content"][0])  # the same text first
        self.assertEqual(piece["id_slot"], 1)
        self.assertEqual(self.metrics("warm")[0]["slot"], 1)

    async def test_the_chat_context_fits_the_token_budget_newest_kept(self):
        d = self.dictation({"chat_history_token_budget": 12, "chat_terms_token_budget": 3})
        chat = {"messages": [{"from": "Assistant", "text": "new reply here"},       # 4 tokens with the author
                             {"from": "Speaker", "text": "a question asked"},          # 4
                             {"from": "Assistant", "text": "an old long reply that does not fit"}],
                "terms": ["GitHub", "Kubernetes", "PostgreSQL"]}  # "Terms:" and a token each
        await d.prepare(chat)
        self.assertIn("Terms: GitHub, Kubernetes\n", d.text)
        self.assertLess(d.text.index("Speaker: a question asked"), d.text.index("Assistant: new reply here"))
        self.assertNotIn("old long reply", d.text)
        self.assertTrue(d.text.endswith("---\n\nPROMPT"))
        self.assertEqual(self.metrics("prepare")[0]["chat_messages"], 2)

    async def test_a_budget_of_0_turns_the_chat_history_off(self):
        d = self.dictation({"chat_history_token_budget": 0})
        await d.prepare({"messages": [{"from": "Anna", "text": "hello"}], "terms": ["X"]})
        self.assertEqual(d.text, "PROMPT")

    async def test_the_text_is_limited_by_the_length_of_the_audio(self):
        await self.dictation({}).piece(LOUD * 20, 1)
        await self.dictation({"max_output_tokens": 50}).piece(LOUD * 20, 1)
        self.assertEqual([b["max_tokens"] for b in self.fake.completions()],
                         [20 * 10 + 32, 50])  # the defaults: 10 per second plus 32
        self.assertEqual([(m["output_limit"], m["output_limit_hit"]) for m in self.metrics("piece")],
                         [(232, False), (50, False)])

    async def test_googles_sampler_unless_the_options_set_one(self):
        await self.dictation({}).piece(LOUD, 1)
        await self.dictation({"top_k": 1, "seed": 3}).piece(LOUD, 1)
        self.assertEqual([{k: b.get(k) for k in ("temperature", "top_k", "top_p", "seed")} for b in self.fake.completions()],
                         [{"temperature": 1.0, "top_k": 64, "top_p": 0.95, "seed": None},
                          {"temperature": 1.0, "top_k": 1, "top_p": 0.95, "seed": 3}])

    async def test_a_text_that_reaches_the_limit_is_logged(self):
        fake = FakeLlamaServer(decode=1000)
        try:
            with self.assertLogs("gemma_voice", "WARNING") as logs:
                await self.dictation(model=fake.model()).piece(LOUD * 2, 1)
        finally:
            fake.close()
        self.assertIn("reached the limit of 52 tokens", logs.output[0])
        self.assertTrue(self.metrics("piece")[0]["output_limit_hit"])

    async def test_a_named_recording_keeps_the_text_each_piece_and_its_text(self):
        rec = recordings.Recording(self.dir.name)
        d = self.dictation(recording=rec)
        await d.prepare()
        await d.piece(LOUD * 2, 1)
        await d.piece(LOUD, 2)
        files = sorted(os.listdir(rec.dir))
        self.assertEqual(files, ["mic.wav", "piece-1.wav", "piece-2.wav", "pieces.jsonl", "text-before-audio.txt"])
        self.assertEqual(open(os.path.join(rec.dir, "text-before-audio.txt")).read(), "PROMPT")
        self.assertEqual(os.path.getsize(os.path.join(rec.dir, "piece-1.wav")), 44 + 2 * 32000)
        lines = [json.loads(l) for l in open(os.path.join(rec.dir, "pieces.jsonl"), encoding="utf-8")]
        self.assertEqual([(l["piece"], l["text"]) for l in lines], [(1, "text from llama"), (2, "text from llama")])

    async def test_hesitation_sounds_leave_the_text_and_the_record_keeps_the_models_own(self):
        class Hesitant(StubModel):
            def complete(self, text, pcm, limit, options, slot=None):
                return "Э, привет, мм, мир", {}
        rec = recordings.Recording(self.dir.name)
        dict_ = d.Dictation(Hesitant(), "PROMPT", {}, args(), {"language": "ru"}, rec)
        await dict_.prepare()
        self.assertEqual(await dict_.piece(LOUD, 1), "Привет, мир")
        line = json.loads(open(os.path.join(rec.dir, "pieces.jsonl"), encoding="utf-8").read())
        self.assertEqual((line["text"], line["raw"]), ("Привет, мир", "Э, привет, мм, мир"))
        other = d.Dictation(Hesitant(), "PROMPT", {}, args(fillers={"ru": []}), {"language": "ru"})
        await other.prepare()
        self.assertEqual(await other.piece(LOUD, 1), "Э, привет, мм, мир")  # the config turned it off

    async def test_a_cancelled_piece_closes_its_request_at_once(self):
        fake = FakeLlamaServer(delay=2.0)
        try:
            task = asyncio.create_task(self.dictation(model=fake.model()).piece(LOUD, 1))
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

    async def test_a_cancel_stops_requests_that_have_not_connected_yet(self):
        m = self.fake.model()
        dic = self.dictation(model=m)
        m.cancel()  # before the piece's request connects
        with self.assertRaises(llama.Cancelled):
            await dic.piece(LOUD, 1)
        self.assertEqual(self.fake.completions(), [])  # it never reached llama-server
        self.assertEqual(await self.dictation(model=m).piece(LOUD, 1), "text from llama")  # the next one starts clean

    async def test_slots_come_from_llama_servers_props_and_https_urls_keep_their_scheme(self):
        fake = FakeLlamaServer(slots=2)
        try:
            self.assertEqual(fake.model().slots(), 2)
        finally:
            fake.close()
        m = llama.LlamaModel("x", {"llamaServer": "https://llm.example.org/base/"})
        self.assertEqual((m.https, m.host, m.port, m.base), (True, "llm.example.org", 443, "/base"))

    async def test_the_metrics_have_llama_servers_memory(self):
        m = self.fake.model()
        await self.dictation(model=m).piece(LOUD, 1)
        mb = self.metrics("piece")[0]["llama_footprint_mb"]  # the fake runs in this process
        self.assertTrue(mb is not None and 1 < mb < 100000, mb)
        self.assertEqual(m.pid, os.getpid())


if __name__ == "__main__":
    unittest.main()
