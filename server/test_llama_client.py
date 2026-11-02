"""Tests of llama_client.py against a fake llama-server: the requests' bodies, the slots, a cancel. Run:
server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import unittest

import catalog
import llama_client
import resolve
import tuning
from fakes import LOUD, FakeLlamaServer


class LlamaModelTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeLlamaServer()
        self.addCleanup(self.fake.close)

    def test_every_sampler_knob_has_its_request_field(self):
        self.assertEqual(set(tuning.SAMPLER), set(llama_client.SAMPLER_FIELDS))

    def test_the_sampler_knobs_go_under_llama_servers_fields(self):
        m = self.fake.model()
        defaults = resolve.model_defaults({})  # Gemma 4 E4B's catalog entry: Google's sampler
        m.complete("PROMPT", LOUD, 5, defaults)
        m.complete("PROMPT", LOUD, 5, {**defaults, "top_k": 1, "seed": 3})
        first, second = self.fake.completions()
        self.assertEqual({k: first.get(k) for k in ("temperature", "top_k", "top_p", "seed")},
                         {"temperature": 1.0, "top_k": 64, "top_p": 0.95, "seed": None})
        self.assertEqual({k: second.get(k) for k in ("temperature", "top_k", "top_p", "seed")},
                         {"temperature": 1.0, "top_k": 1, "top_p": 0.95, "seed": 3})
        # Only llama-server's fields: no knob's own name, and the limit and the cache
        self.assertEqual(set(second) - {"messages", "chat_template_kwargs"},
                         {"max_tokens", "stream", "cache_prompt", "temperature", "top_k", "top_p", "seed"})
        self.assertEqual((second["max_tokens"], second["cache_prompt"]), (5, True))

    def test_the_catalog_entry_gives_the_models_own_request_fields(self):
        self.fake.model().warm("PROMPT", {})
        self.assertEqual(self.fake.completions()[-1]["chat_template_kwargs"], {"enable_thinking": False})  # Gemma 4's
        saved = catalog.entries
        catalog.entries = lambda: {"plain": {"llamaServer": {"args": []}}}
        try:
            llama_client.LlamaModel("p", {"llamaServer": self.fake.url, "catalog": "plain"}).warm("PROMPT", {})
        finally:
            catalog.entries = saved
        self.assertNotIn("chat_template_kwargs", self.fake.completions()[-1])

    def test_a_cancel_stops_requests_that_have_not_connected_yet(self):
        m = self.fake.model()
        m.cancel()  # before the request connects
        with self.assertRaises(llama_client.Cancelled):
            m.complete("PROMPT", LOUD, 5, {})
        self.assertEqual(self.fake.completions(), [])  # it never reached llama-server
        m.begin()  # the next recording starts clean
        self.assertEqual(m.complete("PROMPT", LOUD, 5, {})[0], "text from llama")

    def test_slots_come_from_llama_servers_props_and_https_urls_keep_their_scheme(self):
        fake = FakeLlamaServer(slots=2)
        try:
            self.assertEqual(fake.model().slots(), 2)
        finally:
            fake.close()
        m = llama_client.LlamaModel("x", {"llamaServer": "https://llm.example.org/base/"})
        self.assertEqual((m.https, m.host, m.port, m.base), (True, "llm.example.org", 443, "/base"))


if __name__ == "__main__":
    unittest.main()
