import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import json
import os
import unittest

import budget
import catalog

# The examples that the app's checks read too (macos echofox-tests)
EXAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared", "token-examples.json")


class BudgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(EXAMPLES, encoding="utf-8") as f:
            cls.examples = json.load(f)

    def test_the_estimate_weighs_each_kind_of_character(self):
        w = {"cyrillic": 0.5, "latin": 0.25, "digit": 1, "space": 0, "other": 1}
        self.assertEqual(budget.count("Да, ok 42!", w), 6)  # 1 + 0.5 + 2 + 2 = 5.5, up to a whole token

    def test_the_shared_examples_of_the_estimate(self):
        gemma = self.examples["weights"]["gemma-4-e4b"]
        self.assertEqual(gemma, catalog.token_weights({"catalog": "gemma-4-e4b"}), "the examples use the catalog's")
        for e in self.examples["estimates"]:
            with self.subTest(e["about"]):
                self.assertEqual(budget.counts(e["text"]), e["counts"])
                self.assertEqual(budget.count(e["text"], gemma), e["tokens"]["gemma-4-e4b"])
                self.assertEqual(budget.count(e["text"], {}), e["tokens"]["fallback"])  # a model without weights

    def test_the_shared_examples_of_the_budget(self):
        for e in self.examples["take"]:
            with self.subTest(e["about"]):
                kept, used = budget.take(e["costs"], e["budget"], lambda n: n)
                self.assertEqual((len(kept), used), (e["kept"], e["used"]))
                self.assertEqual(kept, e["costs"][:e["kept"]])


if __name__ == "__main__":
    unittest.main()
