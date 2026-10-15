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
import metrics
from fakes import LOUD, FakeLlamaServer


class OptionsTest(unittest.TestCase):
    def test_known_options_are_checked_and_renamed(self):
        self.assertEqual(d.parse_options({"temperature": 0, "topK": 1, "maxOutputTokens": 200, "pieceSeconds": 10}),
                         {"temperature": 0.0, "top_k": 1, "max_output_tokens": 200, "piece_seconds": 10.0})
        self.assertEqual(d.parse_options(None), {})

    def test_unknown_or_wrong_options_are_refused(self):
        for bad, why in [({"tempreature": 0}, "unknown option"), ({"topK": 1.5}, "integer"), ({"topP": 2}, "out of range"),
                         ({"pieceSeconds": 45}, "out of range"), ({"temperature": "0"}, "number"), ({"topK": True}, "integer"),
                         ({"noRepeatNgramSize": 10}, "unknown option"), ([1], "object")]:
            with self.assertRaisesRegex(ValueError, why):
                d.parse_options(bad)


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
        self.saved = metrics.METRICS
        metrics.METRICS = os.path.join(self.dir.name, "metrics.jsonl")
        self.fake = FakeLlamaServer()

    def tearDown(self):
        metrics.METRICS = self.saved
        self.fake.close()
        self.dir.cleanup()

    def metrics(self, event):
        return [m for m in (json.loads(l) for l in open(metrics.METRICS, encoding="utf-8")) if m["event"] == event]

    async def test_each_piece_is_one_request_with_the_text_then_the_audio(self):
        d = self.fake.model().dictation("PROMPT", {"chat_history_token_budget": 20, "seed": 3})
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
        d = self.fake.model().dictation("PROMPT", {"chat_history_token_budget": 20})
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
        d = self.fake.model().dictation("PROMPT", {"chat_history_token_budget": 12, "chat_terms_token_budget": 4})
        chat = {"messages": [{"from": "Assistant", "text": "new reply here"},       # 4 tokens with the author
                             {"from": "Speaker", "text": "a question asked"},          # 4
                             {"from": "Assistant", "text": "an old long reply that does not fit"}],
                "terms": ["GitHub", "Kubernetes", "PostgreSQL"]}  # 2 tokens each with the separator
        await d.prepare(chat)
        self.assertIn("Terms: GitHub, Kubernetes\n", d.text)
        self.assertLess(d.text.index("Speaker: a question asked"), d.text.index("Assistant: new reply here"))
        self.assertNotIn("old long reply", d.text)
        self.assertTrue(d.text.endswith("---\n\nPROMPT"))
        self.assertEqual(self.metrics("prepare")[0]["chat_messages"], 2)

    async def test_a_budget_of_0_turns_the_chat_history_off(self):
        d = self.fake.model().dictation("PROMPT", {"chat_history_token_budget": 0})
        await d.prepare({"messages": [{"from": "Anna", "text": "hello"}], "terms": ["X"]})
        self.assertEqual(d.text, "PROMPT")

    async def test_the_text_is_limited_by_the_length_of_the_audio(self):
        await self.fake.model().dictation("PROMPT", {}).piece(LOUD * 20, 1)
        await self.fake.model().dictation("PROMPT", {"max_output_tokens": 50}).piece(LOUD * 20, 1)
        self.assertEqual([b["max_tokens"] for b in self.fake.completions()],
                         [20 * d.OUTPUT_TOKENS_PER_SECOND + d.OUTPUT_TOKENS_BASE, 50])
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

    async def test_a_cancel_stops_requests_that_have_not_connected_yet(self):
        import llama
        m = self.fake.model()
        d = m.dictation("PROMPT", {})
        m.cancel()  # before the piece's request connects
        with self.assertRaises(llama.Cancelled):
            await d.piece(LOUD, 1)
        self.assertEqual(self.fake.completions(), [])  # it never reached llama-server
        m.dictation("PROMPT", {})  # the next recording starts clean
        self.assertEqual(await m.dictation("PROMPT", {}).piece(LOUD, 1), "text from llama")

    async def test_the_metrics_have_llama_servers_memory(self):
        m = self.fake.model()
        await m.dictation("PROMPT", {}).piece(LOUD, 1)
        mb = self.metrics("piece")[0]["llama_footprint_mb"]  # the fake runs in this process
        self.assertTrue(mb is None or 1 < mb < 100000, mb)
        self.assertEqual(m.pid, os.getpid())


if __name__ == "__main__":
    unittest.main()
