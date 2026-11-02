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
            rec = recordings.Folder(d)
            self.addCleanup(rec.wav.close)
            for _ in range(6):  # 6 s: the header is brought up to date every 5 s
                rec.audio(LOUD)
            rec.wav.flush()
            with wave.open(os.path.join(rec.dir, "mic.wav")) as w:  # read as it is, without finish()
                self.assertGreaterEqual(w.getnframes() / w.getframerate(), 5)

    def test_a_file_that_cannot_be_written_is_given_up_and_the_dictation_goes_on(self):
        with tempfile.TemporaryDirectory() as d:
            rec = recordings.Folder(d)
            rec.wav.close()  # as if the disk were full: every write fails
            with self.assertLogs("echofox-server", "ERROR"):
                rec.audio(LOUD)
            rec.audio(LOUD)  # no error any more: the audio is given up
            os.chmod(rec.dir, 0o500)
            try:
                with self.assertLogs("echofox-server", "ERROR"):
                    rec.levels({"seconds": 1})
            finally:
                os.chmod(rec.dir, 0o700)
            rec.finish({"text": "t"})
            self.assertTrue(os.path.exists(os.path.join(rec.dir, "adapter.json")))


    def test_a_recording_that_is_not_saved_or_whose_folder_cannot_be_made_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            off = recordings.start(d, save=False)
            self.assertFalse(off.saved)
            self.assertRegex(off.id, r"^\d{4}-\d\d-\d\d/\d{6}-unsaved$")
            root = os.path.join(d, "a-file")
            open(root, "w").close()
            with self.assertLogs("echofox-server", "ERROR"):
                broken = recordings.start(root)  # its root is a file: no folder under it
            for files in (off, broken):
                self.assertIsInstance(files, recordings.Unsaved)
                files.audio(LOUD)
                files.levels({})
                files.text_before_audio("t")
                files.piece(LOUD, {"piece": 1})
                files.finish({"text": "t"})
            self.assertEqual(os.listdir(d), ["a-file"])

    def test_each_file_of_a_recording_has_its_name(self):
        with tempfile.TemporaryDirectory() as d:
            rec = recordings.start(d)
            rec.audio(LOUD)
            rec.levels({"seconds": 1})
            rec.text_before_audio("PROMPT")
            rec.piece(LOUD, {"piece": 1, "text": "a"})
            rec.piece(LOUD, {"piece": 2, "text": "b"})
            rec.finish({"text": "a b"})
            self.assertEqual(sorted(os.listdir(rec.dir)), ["adapter.json", "audio.json", "mic.wav", "piece-1.wav",
                                                           "piece-2.wav", "pieces.jsonl", "text-before-audio.txt"])
            with open(os.path.join(rec.dir, "pieces.jsonl"), encoding="utf-8") as f:
                self.assertEqual(len(f.readlines()), 2)


if __name__ == "__main__":
    unittest.main()
