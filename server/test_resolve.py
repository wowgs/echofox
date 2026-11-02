"""Tests of resolve.py: the options of a recording and of an adapter's context from their owners. Run:
server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import argparse
import unittest

import constants
import resolve
from fakes import args


class ResolveTest(unittest.TestCase):
    def test_a_models_options_are_its_catalogs_then_the_users_then_the_clients(self):
        entry = {"options": {"temperature": 0.5}}
        self.assertEqual(resolve.model_defaults(entry)["top_k"], 64)  # Gemma 4 E4B's catalog
        self.assertEqual(resolve.model(entry)["top_k"], 64)
        self.assertEqual(resolve.model(entry)["temperature"], 0.5)  # the user's over the catalog
        client = resolve.client({"temperature": 0.1})
        self.assertEqual(resolve.model(entry, client)["temperature"], 0.1)  # the client's over both
        with self.assertRaisesRegex(ValueError, "unknown"):
            resolve.model_config({"options": {"pieceSeconds": 10}})  # a constant is not the user's to set

    def test_an_adapters_options_come_from_its_manifest_then_the_config_then_the_client(self):
        server = args()
        budget = "chat_history_token_budget"
        server.adapter_config = {"claude-code": resolve.adapter_config({"enabled": True, "chatHistoryTokenBudget": 2})}
        code = resolve.adapter("claude-code", {}, server)
        self.assertEqual((code[budget], code["chat_terms_token_budget"]), (2, 200))  # the user's entry, the manifest's
        self.assertEqual(resolve.adapter("claude-code", {}, server, {budget: 3})[budget], 3)  # the client's wins
        server.adapter_config = {}
        self.assertEqual(resolve.adapter("claude-code", {budget: 7}, server)[budget], 1000)  # the manifest's, not 7
        telegram = resolve.adapter("telegram", {}, server)
        self.assertNotIn("chat_documents_token_budget", telegram)  # no owner gives it: the table's fallback
        self.assertEqual(resolve.value("chat_documents_token_budget", telegram, server), 1000)
        self.assertEqual(resolve.adapter(None, {budget: 7}, server)[budget], 7)  # no adapter: the recording's

    def test_a_knobs_value_is_the_options_else_the_servers_else_the_fallback(self):
        server = argparse.Namespace(piece_seconds=12.0)
        self.assertEqual(resolve.value("piece_seconds", {"piece_seconds": 9.0}, server), 9.0)
        self.assertEqual(resolve.value("piece_seconds", {}, server), 12.0)
        self.assertEqual(resolve.value("piece_seconds", {}, argparse.Namespace()), 15.0)

    def test_the_prompt_is_the_clients_else_the_models_own_else_none(self):
        self.assertEqual(resolve.own_prompt("  Mine  ", {"prompt": "The model's"}), "Mine")
        self.assertEqual(resolve.own_prompt(None, {"prompt": "The model's"}), "The model's")
        self.assertEqual(resolve.own_prompt("", {"prompt": "The model's"}), "")  # the client's empty one: the catalog's
        self.assertEqual(resolve.own_prompt(None, None), "")
        self.assertEqual(len(resolve.own_prompt("x" * (constants.MAX_PROMPT + 10), {})), constants.MAX_PROMPT)


if __name__ == "__main__":
    unittest.main()
