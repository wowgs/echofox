"""Tests of languages.py: the language table and the config's changes of it. Run:
server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import unittest

import languages


class LanguagesTest(unittest.TestCase):
    def test_a_code_with_a_region_is_its_language(self):
        self.assertEqual((languages.base("ru-RU"), languages.base("EN"), languages.base(None)), ("ru", "en", ""))
        self.assertEqual((languages.name("ru-RU"), languages.name("xx"), languages.name("*")), ("Russian", None, None))

    def test_the_codes_are_the_tables_without_the_entry_of_every_language(self):
        self.assertIn("ru", languages.codes())
        self.assertNotIn(languages.ALL, languages.codes())
        self.assertEqual(len(languages.codes()), len(languages.table()) - 1)

    def test_the_notes_of_every_language_come_first_with_the_language_named(self):
        notes = languages.notes("ru")
        self.assertEqual(notes[0], "The speech is Russian with English technical terms.")
        self.assertIn("imperative mood", notes[-2])  # then Russian's own
        self.assertEqual(languages.notes("de")[0], "The speech is German with English technical terms.")

    def test_english_and_an_unnamed_language_get_no_notes_of_english_terms(self):
        self.assertEqual(languages.notes("en"), [])
        self.assertEqual(languages.notes("xx"), [])

    def test_the_configs_lists_replace_the_tables_and_an_empty_list_turns_them_off(self):
        configured = {"*": {"notes": ["Mind {LANGUAGE} names."]}, "ru": {"notes": [], "fillers": ["ну"]}}
        self.assertEqual(languages.notes("ru", configured), ["Mind Russian names."])
        self.assertEqual(languages.fillers("ru", configured), ["ну"])
        self.assertIn("э", languages.fillers("ru"))  # the table's
        self.assertEqual(languages.fillers("*"), [])


if __name__ == "__main__":
    unittest.main()
