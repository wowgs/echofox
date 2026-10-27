"""Tests of dictation.py and llama.LlamaModel against a fake llama-server. Run: server/.venv/bin/python -m unittest discover -s server"""
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
import llama
import metrics
import recordings
import settings
import tuning
from fakes import LOUD, FakeLlamaServer, StubModel, args


class OptionsTest(unittest.TestCase):
    def test_known_options_are_checked_and_renamed(self):
        self.assertEqual(tuning.parse_options({"temperature": 0, "topK": 1, "maxTokensPerPiece": 15,
                                               "pieceSeconds": 10}),
                         {"temperature": 0.0, "top_k": 1, "max_tokens_per_piece": 15, "piece_seconds": 10.0})
        self.assertEqual(tuning.parse_options(None), {})

    def test_unknown_or_wrong_options_are_refused(self):
        for bad, why in [({"tempreature": 0}, "unknown option"), ({"topK": 1.5}, "integer"), ({"topP": 2}, "out of range"),
                         ({"pieceSeconds": 2}, "out of range"), ({"temperature": "0"}, "number"), ({"topK": True}, "integer"),
                         ({"noRepeatNgramSize": 10}, "unknown option"), ([1], "object")]:
            with self.assertRaisesRegex(ValueError, why):
                tuning.parse_options(bad)


class PromptTest(unittest.TestCase):
    def test_the_catalogs_template_with_the_language(self):
        # Google's ASR prompt and the speech of software engineers; the English terms are in the notes
        self.assertTrue(d.prompt("ru").startswith("Transcribe the following speech segment in Russian into Russian "
                                                  "text."))
        self.assertIn("* The speech is Russian with English technical terms.", d.prompt("ru"))
        self.assertIn("write the digits", d.prompt("ru"))
        self.assertIn("You transcribe speech of software engineers.", d.prompt("ru"))

    def test_the_clients_prompt_with_the_language_filled_in(self):
        self.assertEqual(d.prompt("en", "Say it in {LANGUAGE}."), "Say it in English.")
        self.assertEqual(d.prompt("ru", "Say it in {LANGUAGE}."),  # the notes follow any template
                         "Say it in Russian.\n* The speech is Russian with English technical terms.\n"
                         "* Keep Russian words in the Russian script, also those made from English words with Russian "
                         "endings.\n* The speaker often uses the imperative mood (сделай, посмотри, проверь): keep it "
                         "as spoken.\n* Russian words made from English ones stay in Cyrillic, for example задеплоить, "
                         "закоммитил.")
        self.assertEqual(d.prompt("ru", "Say it.", configured={"*": {"notes": []}, "ru": {"notes": []}}),
                         "Say it.")  # the config's
        self.assertEqual(d.prompt("de", "Say it.", configured={"*": {"notes": ["Mind {LANGUAGE} names."]}}),
                         "Say it.\n* Mind German names.")  # the config's notes of every language, filled in
        self.assertEqual(d.prompt("en", "Say it."), "Say it.")  # English speech: no notes of English terms
        self.assertEqual(d.prompt("xx", "Say it in {LANGUAGE}."), "Say it in its original language.")

    def test_unknown_language_uses_the_original_language_form(self):
        self.assertTrue(d.prompt("xx").startswith("Transcribe the following speech segment in its original language."))


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

    def dictation(self, options=None, model=None, recording=None):
        # the model's options as a start message gives them: its catalog entry's, then these
        return d.Dictation(model or self.fake.model(), "PROMPT", {**settings.model_defaults({}), **(options or {})},
                           args(), {}, recording)

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
            self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})
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
        self.assertTrue(d.text.endswith("</context>\n\nPROMPT"))
        self.assertEqual(self.metrics("prepare")[0]["chat_messages"], 2)

    async def test_english_speech_gets_no_terms_since_every_word_of_it_is_one(self):
        chat = {"messages": [{"from": "Anna", "text": "hello there"}], "terms": ["GitHub"]}
        for language, terms in (("en-GB", False), ("ru", True)):
            dictation = d.Dictation(self.fake.model(), "PROMPT", settings.model_defaults({}), args(),
                                    {"language": language})
            await dictation.prepare(chat)
            self.assertEqual("Terms: GitHub" in dictation.text, terms, language)
            self.assertIn("Anna: hello there", dictation.text)

    async def test_a_piece_without_speech_never_goes_to_the_model(self):
        dictation = self.dictation({"min_speech_seconds": 0.3})
        self.assertEqual(await dictation.piece(LOUD, 1, 0.05), "")
        self.assertEqual(self.fake.completions(), [])
        self.assertEqual(self.metrics("piece_skipped")[0]["speech_seconds"], 0.05)

    def test_an_adapters_settings_come_from_its_manifest_then_the_config_then_the_client(self):
        server = args()
        budget = "chat_history_token_budget"
        server.adapter_options = {"claude-code": {budget: 2}}
        plain = d.Dictation(self.fake.model(), "PROMPT", {}, server, {})
        self.assertEqual(plain.adapter_options("claude-code")[budget], 2)                          # the user's entry
        self.assertEqual(plain.adapter_options("claude-code")["chat_terms_token_budget"], 200)    # the manifest's
        client = d.Dictation(self.fake.model(), "PROMPT", {}, server, {}, client_options={budget: 3})
        self.assertEqual(client.adapter_options("claude-code")[budget], 3)                         # the client's wins
        server.adapter_options = {}
        self.assertEqual(plain.adapter_options("claude-code")[budget], 1000)                       # the manifest's

    async def test_an_adapter_may_keep_the_lines_that_are_not_prose(self):
        context = {"messages": [{"from": "A", "text": "Готово.\n20–40 с: 4,38 / 5,70"}], "terms": []}
        prose = self.dictation({"chat_history_token_budget": 100})
        await prose.prepare(context)
        self.assertNotIn("4,38", prose.text)
        everything = self.dictation({"chat_history_token_budget": 100, "prose_only": False})
        await everything.prepare(context)
        self.assertIn("4,38", everything.text)

    def test_the_default_prompt_asks_for_punctuation_and_keeps_russian_imperatives(self):
        self.assertIn("punctuation and capital letters", d.prompt("en"))
        self.assertIn("imperative mood", d.prompt("ru"))
        self.assertNotIn("imperative mood", d.prompt("en"))

    async def test_an_adapters_entry_sets_the_budget_of_its_own_context(self):
        chat = {"adapter": "telegram", "messages": [{"from": "Anna", "text": "hello there"}], "terms": []}
        server = args(adapter_options={"telegram": {"chat_history_token_budget": 2}})
        small = d.Dictation(self.fake.model(), "PROMPT", {"chat_history_token_budget": 500}, server, {})
        await small.prepare(chat)
        self.assertEqual(small.text, "PROMPT")  # the adapter's 2 wins over the model's 500: no message fits
        on = d.Dictation(self.fake.model(), "PROMPT", {"chat_history_token_budget": 2},
                         args(adapter_options={"telegram": {"chat_history_token_budget": 500}}), {})
        await on.prepare(chat)
        self.assertIn("Anna: hello there", on.text)
        self.assertEqual(on.meta["chat_budget"], 500)
        other = d.Dictation(self.fake.model(), "PROMPT", {"chat_history_token_budget": 500}, server, {})
        await other.prepare({**chat, "adapter": "claude-code"})
        self.assertIn("Anna: hello there", other.text)  # another adapter keeps the model's budget

    async def test_the_text_of_a_piece_has_a_fixed_limit(self):
        await self.dictation({}).piece(LOUD * 20, 1, 12.3)
        await self.dictation({"max_tokens_per_piece": 5}).piece(LOUD, 1, 1)
        self.assertEqual([b["max_tokens"] for b in self.fake.completions()], [600, 5])  # the catalog's, the options'
        self.assertEqual([m["max_tokens_hit"] for m in self.metrics("piece")], [False, True])

    async def test_the_catalogs_sampler_unless_the_options_set_one(self):
        defaults = settings.model_defaults({})  # Gemma 4 E4B's catalog entry: Google's sampler
        await self.dictation(defaults).piece(LOUD, 1, 1)
        await self.dictation({**defaults, "top_k": 1, "seed": 3}).piece(LOUD, 1, 1)
        self.assertEqual([{k: b.get(k) for k in ("temperature", "top_k", "top_p", "seed")} for b in self.fake.completions()],
                         [{"temperature": 1.0, "top_k": 64, "top_p": 0.95, "seed": None},
                          {"temperature": 1.0, "top_k": 1, "top_p": 0.95, "seed": 3}])

    async def test_a_text_that_reaches_the_limit_stays(self):
        fake = FakeLlamaServer(decode=1000)
        try:
            with self.assertLogs("gemma_voice", "WARNING") as logs:
                text = await self.dictation(model=fake.model()).piece(LOUD * 2, 1, 2)
        finally:
            fake.close()
        self.assertEqual(text, "text from llama")
        self.assertIn("stopped at the limit of 600 tokens", logs.output[0])
        m = self.metrics("piece")[0]
        self.assertEqual((m["max_tokens_hit"], m["text_chars"]), (True, 15))

    async def test_a_named_recording_keeps_the_text_each_piece_and_its_text(self):
        rec = recordings.Recording(self.dir.name)
        self.addCleanup(rec.wav.close)  # the test does not finish() it
        d = self.dictation(recording=rec)
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
        rec = recordings.Recording(self.dir.name)
        self.addCleanup(rec.wav.close)  # the test does not finish() it
        dict_ = d.Dictation(Hesitant(), "PROMPT", settings.model_defaults({}), args(), {"language": "ru"}, rec)
        await dict_.prepare()
        self.assertEqual(await dict_.piece(LOUD, 1, 1), "Привет, мир")
        line = json.loads(pathlib.Path(rec.dir, "pieces.jsonl").read_text(encoding="utf-8"))
        self.assertEqual((line["text"], line["raw"]), ("Привет, мир", "Э, привет, мм, мир"))
        other = d.Dictation(Hesitant(), "PROMPT", settings.model_defaults({}), args(languages={"ru": {"fillers": []}}),
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

    async def test_a_cancel_stops_requests_that_have_not_connected_yet(self):
        m = self.fake.model()
        dic = self.dictation(model=m)
        m.cancel()  # before the piece's request connects
        with self.assertRaises(llama.Cancelled):
            await dic.piece(LOUD, 1, 1)
        self.assertEqual(self.fake.completions(), [])  # it never reached llama-server
        self.assertEqual(await self.dictation(model=m).piece(LOUD, 1, 1), "text from llama")  # the next one starts clean

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
        await self.dictation(model=m).piece(LOUD, 1, 1)
        mb = self.metrics("piece")[0]["llama_footprint_mb"]  # the fake runs in this process
        self.assertTrue(mb is not None and 1 < mb < 100000, mb)
        self.assertEqual(m.pid, os.getpid())


if __name__ == "__main__":
    unittest.main()
