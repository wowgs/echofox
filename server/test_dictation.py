"""Tests of dictation.py and prompt.py's context against a fake llama-server. Run: server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import asyncio
import base64
import json
import os
import pathlib
import tempfile
import time
import unittest

import dictation as d
import metrics
import recordings
import resolve
from fakes import LOUD, FakeLlamaServer, StubModel, args


ONE_A_CHAR = dict.fromkeys(("cyrillic", "latin", "digit", "space", "other"), 1.0)


class DictationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.file = os.path.join(self.dir.name, "metrics.jsonl")
        self.saved = metrics.configure(self.file)
        self.fake = FakeLlamaServer()

    def tearDown(self):
        metrics.configure(self.saved)
        self.fake.close()
        self.dir.cleanup()

    def metrics(self, event):
        lines = pathlib.Path(self.file).read_text(encoding="utf-8").splitlines()
        return [m for m in map(json.loads, lines) if m["event"] == event]

    def dictation(self, options=None, model=None, files=None, weights=None, room=None):
        # the model's options as a start message gives them: its catalog entry's, then these
        return d.Dictation(model or self.fake.model(), "PROMPT", {**resolve.model_defaults({}), **(options or {})},
                           args(), {}, files, token_weights=weights, text_room=room)

    async def test_the_context_fits_the_models_room_whatever_its_budgets_say(self):
        # A token a word for the model (the fake's /tokenize). The file goes whole by its budget, but the text with it
        # would not fit beside the audio and the answer: the file goes first, then the oldest messages
        long = " ".join(["word"] * 300)
        chat = {"messages": [{"from": "Claude", "text": "the newest reply"}, {"from": "Claude", "text": "an older one"}],
                "documents": [{"name": "big.md", "text": long}], "terms": ["GitHub"]}
        limit = resolve.model_defaults({})["max_tokens_per_piece"]
        d = self.dictation({"chat_documents_token_budget": 10}, room=limit + 60)
        await d.prepare(chat)
        self.assertNotIn("File big.md", d.text)
        self.assertIn("Claude: the newest reply", d.text)
        self.assertLessEqual(len(d.text.split()), 60)
        m = self.metrics("prepare")[0]
        self.assertEqual((m["chat_documents"], m["chat_left_for_room"]["documents"]), (0, 1))
        d = self.dictation({"chat_documents_token_budget": 10}, room=limit + 20)  # room for the prompt and a little
        await d.prepare(chat)
        self.assertNotIn("an older one", d.text)
        self.assertLessEqual(len(d.text.split()), 20)

    async def test_a_piece_that_does_not_fit_with_its_context_goes_again_without_it(self):
        self.fake.close()
        self.fake = FakeLlamaServer(context=20)  # its slot takes 20 words of text
        d = self.dictation({"chat_history_token_budget": 1000})  # no room known: the context goes as the budget says
        await d.prepare({"messages": [{"from": "Claude", "text": " ".join(["word"] * 50)}]})
        self.assertEqual(await d.piece(LOUD, 1, 1), "text from llama")
        first, again = self.fake.completions()
        self.assertIn("<context>", first["messages"][0]["content"][0]["text"])
        self.assertEqual(again["messages"][0]["content"][0]["text"], "PROMPT")
        self.assertEqual(self.metrics("piece")[0]["context_dropped"], "too big for the model")

    async def test_each_piece_is_one_request_with_the_text_then_the_audio(self):
        d = self.dictation({"chat_history_token_budget": 20, "seed": 3})
        await d.prepare({"messages": [{"from": "Anna", "text": "hello there"}], "terms": []})
        self.assertEqual(await d.piece(LOUD * 2, 1, 2), "text from llama")
        await d.piece(LOUD, 2, 1)
        bodies = self.fake.completions()
        self.assertEqual(len(bodies), 2)
        for body in bodies:  # the text, then one piece's audio; never an earlier answer
            parts = body["messages"][0]["content"]
            self.assertEqual([p["type"] for p in parts], ["text", "input_audio"])
            self.assertTrue(parts[0]["text"].endswith("</context>\n\nPROMPT") and "Anna: hello there" in parts[0]["text"])
            self.assertEqual(len(body["messages"]), 1)  # no system turn by default
            self.assertEqual(base64.b64decode(parts[1]["input_audio"]["data"])[:4], b"RIFF")
        self.assertEqual((bodies[0]["max_tokens"], bodies[0]["cache_prompt"], bodies[0]["seed"]), (600, True, 3))
        m = self.metrics("piece")[0]
        self.assertEqual((m["prefill_tokens"], m["cached_tokens"], m["decode_tokens"]), (30, 6, 5))

    async def test_warm_sends_the_same_text_alone_to_the_slot_of_its_piece(self):
        d = self.dictation({"chat_history_token_budget": 20})
        await d.prepare({"messages": [{"from": "Claude", "text": "hello there"}], "terms": []})
        await d.warm(1)
        await d.piece(LOUD, 2, 1, slot=1)
        warm, piece = self.fake.completions()
        self.assertEqual(warm["messages"][0]["content"], [{"type": "text", "text": d.text}])  # no audio
        self.assertEqual((warm["max_tokens"], warm["id_slot"], warm["cache_prompt"]), (0, 1, True))
        self.assertEqual(piece["messages"][0]["content"][0], warm["messages"][0]["content"][0])  # the same text first
        self.assertEqual(piece["id_slot"], 1)
        self.assertEqual(self.metrics("warm")[0]["slot"], 1)

    async def test_the_chat_context_is_taken_greedily_the_item_that_reaches_a_budget_whole(self):
        # A token a character, so that the costs are the lengths
        d = self.dictation({"chat_history_token_budget": 40, "chat_terms_token_budget": 10}, weights=ONE_A_CHAR)
        chat = {"messages": [{"from": "Assistant", "text": "new reply here"},  # 27 with its author and its break
                             {"from": "Speaker", "text": "a question asked"},
                             {"from": "Assistant", "text": "an old reply"}],
                "terms": ["GitHub", "Kubernetes", "PostgreSQL"]}  # 8 and 12 with their commas: 20 of the 10
        await d.prepare(chat)
        self.assertIn("Terms: GitHub, Kubernetes\n", d.text)  # Kubernetes reaches the terms' budget: whole, the last
        self.assertIn("Assistant: new reply here", d.text)  # 27 of the 20 left: whole, the last
        self.assertNotIn("a question asked", d.text)
        self.assertTrue(d.text.endswith("</context>\n\nPROMPT"))
        self.assertEqual(self.metrics("prepare")[0]["chat_messages"], 1)
    async def test_documents_have_their_own_budget_and_the_one_that_reaches_it_goes_whole(self):
        d = self.dictation({"chat_history_token_budget": 40, "chat_terms_token_budget": 10,
                            "chat_documents_token_budget": 30}, weights=ONE_A_CHAR)
        long = " ".join(["word"] * 100)
        chat = {"messages": [{"from": "Assistant", "text": "new reply here"}],
                "documents": [{"name": "a.md", "text": "first file text"},  # 28 with its header and its break
                              {"name": "b.md", "text": long}, {"name": "c.md", "text": "never reached"}]}
        await d.prepare(chat)
        self.assertIn("File a.md:\nfirst file text\n\nFile b.md:\n" + long + "\n\n", d.text)  # b.md whole
        self.assertNotIn("never reached", d.text)
        self.assertLess(d.text.index("File b.md"), d.text.index("Assistant: new reply here"))
        self.assertIn("the files open beside it", d.text)
        self.assertEqual(self.metrics("prepare")[0]["chat_documents"], 2)
        # Only terms: the context still goes
        d = self.dictation({"chat_history_token_budget": 12, "chat_terms_token_budget": 3})
        await d.prepare({"terms": ["GitHub"]})
        self.assertIn("Terms: GitHub", d.text)
        self.assertNotIn("files open", d.text)
    async def test_english_speech_gets_no_terms_since_every_word_of_it_is_one(self):
        chat = {"messages": [{"from": "Anna", "text": "hello there"}], "terms": ["GitHub"]}
        for language, terms in (("en-GB", False), ("ru", True)):
            dictation = d.Dictation(self.fake.model(), "PROMPT", resolve.model_defaults({}), args(),
                                    {"language": language})
            await dictation.prepare(chat)
            self.assertEqual("Terms: GitHub" in dictation.text, terms, language)
            self.assertIn("Anna: hello there", dictation.text)

    async def test_a_piece_without_speech_never_goes_to_the_model(self):
        dictation = self.dictation({"min_speech_seconds": 0.3})
        self.assertEqual(await dictation.piece(LOUD, 1, 0.05), "")
        self.assertEqual(self.fake.completions(), [])
        self.assertEqual(self.metrics("piece_skipped")[0]["speech_seconds"], 0.05)

    async def test_an_adapter_may_keep_the_lines_that_are_not_prose(self):
        context = {"messages": [{"from": "A", "text": "Готово.\n20–40 с: 4,38 / 5,70"}], "terms": []}
        prose = self.dictation({"chat_history_token_budget": 100})
        await prose.prepare(context)
        self.assertNotIn("4,38", prose.text)
        everything = self.dictation({"chat_history_token_budget": 100, "prose_only": False})
        await everything.prepare(context)
        self.assertIn("4,38", everything.text)

    async def test_an_adapters_entry_sets_the_budget_of_its_own_context(self):
        chat = {"adapter": "telegram", "terms": [],
                "messages": [{"from": "Anna", "text": "hello there"}, {"from": "Bob", "text": "older message"}]}
        server = args(adapter_config={"telegram": {"chat_history_token_budget": 2}})
        small = d.Dictation(self.fake.model(), "PROMPT", {"chat_history_token_budget": 500}, server, {})
        await small.prepare(chat)
        self.assertEqual(small.meta["chat_budget"], 2)  # the adapter's 2 wins over the model's 500
        self.assertIn("Anna: hello there", small.text)  # the newest reaches the 2: whole, and the last
        self.assertNotIn("older message", small.text)
        on = d.Dictation(self.fake.model(), "PROMPT", {"chat_history_token_budget": 2},
                         args(adapter_config={"telegram": {"chat_history_token_budget": 500}}), {})
        await on.prepare(chat)
        self.assertIn("older message", on.text)
        self.assertEqual(on.meta["chat_budget"], 500)
        other = d.Dictation(self.fake.model(), "PROMPT", {"chat_history_token_budget": 500}, server, {})
        await other.prepare({**chat, "adapter": "claude-code"})
        self.assertEqual(other.meta["chat_budget"], 1000)  # another adapter: its own manifest's, not telegram's entry
    async def test_the_text_of_a_piece_has_a_fixed_limit(self):
        await self.dictation({}).piece(LOUD * 20, 1, 12.3)
        await self.dictation({"max_tokens_per_piece": 5}).piece(LOUD, 1, 1)
        self.assertEqual([b["max_tokens"] for b in self.fake.completions()], [600, 5])  # the catalog's, the options'
        self.assertEqual([m["max_tokens_hit"] for m in self.metrics("piece")], [False, True])

    async def test_a_text_that_reaches_the_limit_stays(self):
        fake = FakeLlamaServer(decode=1000)
        try:
            with self.assertLogs("echofox-server", "WARNING") as logs:
                text = await self.dictation(model=fake.model()).piece(LOUD * 2, 1, 2)
        finally:
            fake.close()
        self.assertEqual(text, "text from llama")
        self.assertIn("stopped at the limit of 600 tokens", logs.output[0])
        m = self.metrics("piece")[0]
        self.assertEqual((m["max_tokens_hit"], m["text_chars"]), (True, 15))

    async def test_a_named_recording_keeps_the_text_each_piece_and_its_text(self):
        rec = recordings.Folder(self.dir.name)
        self.addCleanup(rec.wav.close)  # the test does not finish() it
        d = self.dictation(files=rec)
        await d.prepare()
        await d.piece(LOUD * 2, 1, 2)
        await d.piece(LOUD, 2, 1)
        files = sorted(os.listdir(rec.dir))
        self.assertEqual(files, ["mic.wav", "piece-1.wav", "piece-2.wav", "pieces.jsonl", "text-before-audio.txt"])
        self.assertEqual(pathlib.Path(rec.dir, "text-before-audio.txt").read_text(encoding="utf-8"), "PROMPT")
        self.assertEqual(os.path.getsize(os.path.join(rec.dir, "piece-1.wav")), 44 + 2 * 32000)
        lines = [json.loads(l) for l in pathlib.Path(rec.dir, "pieces.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(l["piece"], l["text"]) for l in lines], [(1, "text from llama"), (2, "text from llama")])

    async def test_hesitation_sounds_leave_the_text_and_the_record_keeps_the_models_own(self):
        class Hesitant(StubModel):
            def complete(self, text, pcm, limit, options, slot=None):
                return "Э, привет, мм, мир", {}
        rec = recordings.Folder(self.dir.name)
        self.addCleanup(rec.wav.close)  # the test does not finish() it
        dict_ = d.Dictation(Hesitant(), "PROMPT", resolve.model_defaults({}), args(), {"language": "ru"}, rec)
        await dict_.prepare()
        self.assertEqual(await dict_.piece(LOUD, 1, 1), "Привет, мир")
        line = json.loads(pathlib.Path(rec.dir, "pieces.jsonl").read_text(encoding="utf-8"))
        self.assertEqual((line["text"], line["raw"]), ("Привет, мир", "Э, привет, мм, мир"))
        other = d.Dictation(Hesitant(), "PROMPT", resolve.model_defaults({}), args(languages={"ru": {"fillers": []}}),
                            {"language": "ru"})
        await other.prepare()
        self.assertEqual(await other.piece(LOUD, 1, 1), "Э, привет, мм, мир")  # the config turned it off

    async def test_a_cancelled_piece_closes_its_request_at_once(self):
        fake = FakeLlamaServer(delay=2.0)
        try:
            task = asyncio.create_task(self.dictation(model=fake.model()).piece(LOUD, 1, 1))
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

    async def test_a_new_dictation_starts_clean_after_a_cancel(self):
        m = self.fake.model()
        m.cancel()  # the recording before was cancelled
        self.assertEqual(await self.dictation(model=m).piece(LOUD, 1, 1), "text from llama")

    async def test_the_metrics_have_llama_servers_memory(self):
        m = self.fake.model()
        await self.dictation(model=m).piece(LOUD, 1, 1)
        mb = self.metrics("piece")[0]["llama_footprint_mb"]  # the fake runs in this process
        self.assertTrue(mb is not None and 1 < mb < 100000, mb)
        self.assertEqual(m.pid, os.getpid())


if __name__ == "__main__":
    unittest.main()
