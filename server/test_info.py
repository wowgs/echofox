"""Tests of info.py: which model's settings the info describes, and its languages. Run:
server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import unittest

import catalog
import info
import languages
from fakes import args, stub_models

ENTRIES = {"gemma-e4b": {"llamaServer": "http://h:1", "variant": "q8_0"},
           "other": {"llamaServer": "http://h:2", "options": {"temperature": 0.2}}}


def setting(got, key):
    return next(s for s in got["settings"] if s["key"] == key)


class InfoTest(unittest.TestCase):
    def test_the_menus_model_with_its_variants_and_its_settings(self):
        got = info.info(args(), stub_models(ENTRIES, chosen="other"))
        self.assertEqual(got["models"], ["gemma-e4b", "other"])
        self.assertEqual((got["model"]["name"], got["model"]["catalog"], got["model"]["variant"]),
                         ("other", "gemma-4-e4b", "q4_0"))  # the catalog's default variant
        self.assertEqual(setting(got, "temperature")["value"], 0.2)  # its own option, over the catalog's 1.0
        self.assertEqual(setting(got, "temperature")["default"], 1.0)

    def test_without_a_model_of_the_menu_on_this_server_the_default_one(self):
        got = info.info(args(), stub_models(ENTRIES, chosen="gone"))
        self.assertEqual((got["model"]["name"], got["model"]["variant"]), ("gemma-e4b", "q8_0"))
        self.assertNotIn("value", setting(got, "temperature"))  # the catalog's value is in force

    def test_the_languages_are_the_ones_the_models_prompt_names_with_the_tables_defaults(self):
        got = info.info(args(languages={"ru": {"fillers": ["ну"]}}), stub_models(ENTRIES))
        self.assertEqual({l["code"] for l in got["languages"]}, set(catalog.of(ENTRIES["gemma-e4b"])["languages"]))
        names = [l["name"] for l in got["languages"]]
        self.assertEqual(names, sorted(names))
        ru = next(l for l in got["languages"] if l["code"] == "ru")
        self.assertIn("э", ru["fillers"])  # the table's, not the config's
        self.assertEqual(got["commonNotes"], languages.table()[languages.ALL]["notes"])

    def test_without_models_no_model(self):
        got = info.info(args())
        self.assertEqual((got["models"], got["model"]["name"]), ([], None))
        self.assertNotIn("variants", got["model"])


if __name__ == "__main__":
    unittest.main()
