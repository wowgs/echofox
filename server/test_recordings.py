"""Tests of recordings.py. Run: server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import os
import tempfile
import unittest
import wave

import recordings
from fakes import LOUD


class RecordingTest(unittest.TestCase):
    def test_the_audio_plays_even_if_the_server_dies_before_the_end(self):
        with tempfile.TemporaryDirectory() as d:
            rec = recordings.Recording(d)
            for _ in range(6):  # 6 s: the header is brought up to date every 5 s
                rec.write(LOUD)
            rec.wav.flush()
            with wave.open(os.path.join(rec.dir, "mic.wav")) as w:  # read as it is, without finish()
                self.assertGreaterEqual(w.getnframes() / w.getframerate(), 5)

    def test_a_file_that_cannot_be_written_is_given_up_and_the_dictation_goes_on(self):
        with tempfile.TemporaryDirectory() as d:
            rec = recordings.Recording(d)
            rec.wav.close()  # as if the disk were full: every write fails
            with self.assertLogs("gemma_voice", "ERROR"):
                rec.write(LOUD)
            rec.write(LOUD)  # no error any more: the audio is given up
            os.chmod(rec.dir, 0o500)
            try:
                with self.assertLogs("gemma_voice", "ERROR"):
                    rec.save("pieces.jsonl", b"x")
            finally:
                os.chmod(rec.dir, 0o700)
            rec.finish({"text": "t"})
            self.assertTrue(os.path.exists(os.path.join(rec.dir, "adapter.json")))


if __name__ == "__main__":
    unittest.main()
