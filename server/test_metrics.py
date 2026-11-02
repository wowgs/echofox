"""Tests of metrics.py, the metrics file, and of its summary (tools/metrics_summary.py). Run:
server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

import metrics

SUMMARY = pathlib.Path(__file__).resolve().parent / "tools" / "metrics_summary.py"


class MetricsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(dir=sandbox.ROOT)
        self.file = os.path.join(self.dir.name, "logs", "metrics.jsonl")  # its folder does not exist yet
        self.saved = metrics.configure(self.file)

    def tearDown(self):
        metrics.configure(self.saved)
        self.dir.cleanup()

    def lines(self):
        return [json.loads(l) for l in pathlib.Path(self.file).read_text(encoding="utf-8").splitlines()]

    def test_each_metric_is_one_line_with_its_time_and_event(self):
        metrics.metric("piece", model="m", text_chars=3, note="привет")
        metrics.metric("recording", model="m")
        lines = self.lines()
        self.assertEqual([(l["event"], l["model"]) for l in lines], [("piece", "m"), ("recording", "m")])
        self.assertRegex(lines[0]["time"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d{4}$")
        self.assertEqual(lines[0]["note"], "привет")
        self.assertEqual(metrics.configure(self.saved), self.file)  # configure gives where it wrote before
        metrics.configure(self.file)

    def test_a_file_that_cannot_be_written_is_logged_and_the_dictation_goes_on(self):
        blocked = os.path.join(self.dir.name, "file")
        pathlib.Path(blocked).write_text("")
        metrics.configure(os.path.join(blocked, "metrics.jsonl"))  # its folder is a file
        with self.assertLogs("echofox-server", "ERROR"):
            metrics.metric("piece", model="m")

    def test_the_summary_lists_each_model_and_the_last_pieces(self):
        piece = {"audio_seconds": 10.0, "wall_seconds": 2.0, "prefill_tokens": 300, "decode_tokens": 20,
                 "prefill_tps": [900.0], "decode_tps": [40.0], "ttft_seconds": 0.4, "llama_footprint_mb": 2100}
        metrics.metric("piece", model="gemma-e4b", **piece)
        metrics.metric("recording", model="gemma-e4b", done_after_stop_seconds=1.5)
        out = subprocess.run([sys.executable, str(SUMMARY), self.file], capture_output=True, text=True,
                             check=True).stdout
        row = next(l for l in out.splitlines() if l.startswith("gemma-e4b"))
        self.assertEqual(row.split()[:4], ["gemma-e4b", "1", "10.0", "0.20"])  # pieces, audio, wall per audio second
        self.assertIn("1.50", row)  # the wait after the stop
        self.assertIn("10.0 s audio", out.splitlines()[-1])


if __name__ == "__main__":
    unittest.main()
