"""Tests of prompt.py: the prompt of a language (its context is tested with the dictation, test_dictation.py). Run:
server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import unittest

import prompt


class PromptTest(unittest.TestCase):
    def test_the_catalogs_template_with_the_language(self):
        # Google's ASR prompt and the speech of software engineers; the English terms are in the notes
        self.assertTrue(prompt.text("ru").startswith("Transcribe the following speech segment in Russian into Russian "
                                                     "text."))
        self.assertIn("* The speech is Russian with English technical terms.", prompt.text("ru"))
        self.assertIn("write the digits", prompt.text("ru"))
        self.assertIn("You transcribe speech of software engineers.", prompt.text("ru"))

    def test_the_clients_prompt_with_the_language_filled_in(self):
        self.assertEqual(prompt.text("en", "Say it in {LANGUAGE}."), "Say it in English.")
        self.assertEqual(prompt.text("ru", "Say it in {LANGUAGE}."),  # the notes follow any template
                         "Say it in Russian.\n* The speech is Russian with English technical terms.\n"
                         "* Keep Russian words in the Russian script, also those made from English words with Russian "
                         "endings.\n* The speaker often uses the imperative mood (сделай, посмотри, проверь): keep it "
                         "as spoken.\n* Russian words made from English ones stay in Cyrillic, for example задеплоить, "
                         "закоммитил.")
        self.assertEqual(prompt.text("ru", "Say it.", configured={"*": {"notes": []}, "ru": {"notes": []}}),
                         "Say it.")  # the config's
        self.assertEqual(prompt.text("de", "Say it.", configured={"*": {"notes": ["Mind {LANGUAGE} names."]}}),
                         "Say it.\n* Mind German names.")  # the config's notes of every language, filled in
        self.assertEqual(prompt.text("en", "Say it."), "Say it.")  # English speech: no notes of English terms
        self.assertEqual(prompt.text("xx", "Say it in {LANGUAGE}."), "Say it in its original language.")

    def test_unknown_language_uses_the_original_language_form(self):
        self.assertTrue(prompt.text("xx").startswith("Transcribe the following speech segment in its original language."))

    def test_the_default_prompt_asks_for_punctuation_and_keeps_russian_imperatives(self):
        self.assertIn("punctuation and capital letters", prompt.text("en"))
        self.assertIn("imperative mood", prompt.text("ru"))
        self.assertNotIn("imperative mood", prompt.text("en"))


if __name__ == "__main__":
    unittest.main()
