import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import unittest

import budget
import catalog


class BudgetTest(unittest.TestCase):
    def test_the_estimate_weighs_each_kind_of_character(self):
        self.assertEqual(budget.counts("Да, ok 42!\n"),
                         {"cyrillic": 2, "latin": 2, "digit": 2, "space": 3, "other": 2})
        w = {"cyrillic": 0.5, "latin": 0.25, "digit": 1, "space": 0, "other": 1}
        self.assertEqual(budget.count("Да, ok 42!", w), 6)  # 1 + 0.5 + 2 + 2 = 5.5, up to a whole token
        self.assertEqual(budget.count("", w), 0)

    def test_a_model_without_weights_gets_the_plain_ratio(self):
        self.assertEqual(budget.count("a" * 100, {}), budget.count("a" * 100, budget.FALLBACK))
        self.assertTrue(catalog.token_weights({"catalog": "gemma-4-e4b"}))

    def test_the_item_that_reaches_the_budget_is_taken_whole_and_is_the_last(self):
        self.assertEqual(budget.take([3, 4, 5], 6, lambda n: n), ([3, 4], 7))
        self.assertEqual(budget.take([10, 1], 6, lambda n: n), ([10], 10))  # one item over the budget: whole
        self.assertEqual(budget.take([3, 3, 1], 6, lambda n: n), ([3, 3], 6))
        self.assertEqual(budget.take([1], 0, lambda n: n), ([], 0))  # no budget: nothing


if __name__ == "__main__":
    unittest.main()
