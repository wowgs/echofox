import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import unittest

import fillers

RU = fillers.words("ru")


class FillersTest(unittest.TestCase):
    def test_hesitation_sounds_go_with_their_marks_and_the_phrase_stays_whole(self):
        for said, written in [
            ("Э, ну это не точно.", "Ну это не точно."),
            ("какой-нибудь э markdown", "какой-нибудь markdown"),
            ("повторение возникает, а-а, у меня", "повторение возникает, у меня"),
            ("Во-вторых, а-а Типа, давай", "Во-вторых, Типа, давай"),
            ("Да, давай, м, начинай", "Да, давай, начинай"),
            ("сделай, э.", "сделай."),
            ("что от, блять. Ммм. Наша задача", "что от, блять. Наша задача"),
            ("другой есть? Мм?", "другой есть?"),
            ("Мм, память ограничена.", "Память ограничена."),
            ("Хм. Слушай", "Слушай"),
            ("типа микрофон хм подумай", "типа микрофон подумай"),
            ("Так, э… а дальше", "Так… а дальше"),
        ]:
            self.assertEqual(fillers.remove(said, RU), written, said)

    def test_a_sound_said_longer_or_repeated_counts_as_its_form(self):
        self.assertEqual(fillers.remove("Ээээ, подожди. Э-э-э версии, а-а-а-а и хмм", RU), "Подожди. Версии, и")
        self.assertEqual(fillers.remove("Мм.", RU), "")
        self.assertEqual(fillers.remove("э э э", RU), "")

    def test_words_of_the_language_and_units_after_numbers_stay(self):
        for kept in ["а ты мне, а потом", "ага, эмоции, амбар, хмель, эмм-модуль", "до 100 м от дома и 5 мм",
                     "М2 и Э-1", "Ну типа вот так"]:
            self.assertEqual(fillers.remove(kept, RU), kept)

    def test_the_lists_by_language_and_the_configs_own(self):
        self.assertEqual(fillers.words("ru-RU"), RU)
        self.assertEqual((fillers.words(""), fillers.words("en")), (set(), set()))  # no list: nothing goes
        self.assertEqual(fillers.words("ru", {"ru": []}), set())  # the config turns it off
        self.assertEqual(fillers.words("ru", {"ru": ["Ммм", "ну"]}), {"м", "ну"})
        self.assertEqual(fillers.words("ru", {"en": ["um"]}), RU)


if __name__ == "__main__":
    unittest.main()
