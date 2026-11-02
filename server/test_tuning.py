"""Tests of tuning.py: a client's options, checked and renamed. Run:
server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import unittest

import tuning


class OptionsTest(unittest.TestCase):
    def test_known_options_are_checked_and_renamed(self):
        self.assertEqual(tuning.parse({"temperature": 0, "topK": 1, "maxTokensPerPiece": 15, "pieceSeconds": 10}),
                         {"temperature": 0.0, "top_k": 1, "max_tokens_per_piece": 15, "piece_seconds": 10.0})
        self.assertEqual(tuning.parse(None), {})

    def test_unknown_or_wrong_options_are_refused(self):
        for bad, why in [({"tempreature": 0}, "unknown option"), ({"topK": 1.5}, "integer"), ({"topP": 2}, "out of range"),
                         ({"pieceSeconds": 2}, "out of range"), ({"temperature": "0"}, "number"), ({"topK": True}, "integer"),
                         ({"noRepeatNgramSize": 10}, "unknown option"), ([1], "object")]:
            with self.assertRaisesRegex(ValueError, why):
                tuning.parse(bad)


if __name__ == "__main__":
    unittest.main()
