"""Tests of audio.py: levels and cutting. Run: server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import array
import unittest

import audio as a
from fakes import LOUD, QUIET, seconds


def levels(pcm, chunk=None):
    lv = a.Levels(-45)
    for i in range(0, len(pcm), chunk or len(pcm) or 1):
        lv.feed(pcm[i:i + (chunk or len(pcm))])
    return lv


def split(pcm, piece_s=20, search_s=3):
    lv = levels(pcm)
    return [round(seconds(p), 1) for p in a.split(pcm, lv.rms, lv.threshold, piece_s, search_s)]


class SplitTest(unittest.TestCase):
    def test_a_recording_near_the_wanted_length_is_one_piece(self):
        self.assertEqual(split(LOUD + QUIET + LOUD), [3.0])
        self.assertEqual(split(LOUD * 28), [28.0])  # round(28 / 20) = 1, and 28 s fits the model

    def test_silence_never_becomes_a_piece(self):
        self.assertEqual(split(QUIET * 3), [])

    def test_pieces_are_equal_and_as_close_to_the_wanted_length_as_possible(self):
        self.assertEqual(split(LOUD * 45), [22.5, 22.5])  # 2 pieces of 22.5 s, not 20 + 20 + 5
        self.assertEqual(sorted(split(LOUD * 62)), [20.6, 20.7, 20.7])

    def test_none_is_longer_than_the_model_takes(self):
        self.assertTrue(all(x <= 30 for x in split(LOUD * 61, piece_s=30)))
        self.assertEqual(len(split(LOUD * 61, piece_s=30)), 3)  # round(61 / 30) = 2 would make 30.5 s pieces

    def test_a_cut_moves_into_the_nearest_pause(self):
        pieces = split(LOUD * 19 + QUIET + LOUD * 21)  # the equal point is 20.5 s, the pause 19 to 20 s
        self.assertEqual(len(pieces), 2)
        self.assertTrue(19.0 <= pieces[0] <= 20.0, pieces)


def tone(amplitude, seconds=1):
    return array.array("h", [amplitude, -amplitude] * int(a.RATE * seconds / 2)).tobytes()


class LiveCutTest(unittest.TestCase):
    def cut(self, pcm, start=0, piece_s=15, search_s=3, last_s=5):
        c = a.live_cut(levels(pcm).rms, start, piece_s, search_s, last_s)
        return None if c is None else round(c * a.FRAME_S, 1)

    def test_no_cut_before_the_piece_and_the_last_piece_are_heard(self):
        self.assertIsNone(self.cut(LOUD * 19))
        self.assertEqual(self.cut(LOUD * 20), 15.0)  # no pause: at the wanted length

    def test_a_cut_moves_back_into_a_pause_never_forward(self):
        self.assertTrue(13.0 <= self.cut(LOUD * 13 + QUIET + LOUD * 6) <= 14.0)  # the pause 13 to 14 s
        self.assertEqual(self.cut(LOUD * 15 + QUIET + LOUD * 4), 15.0)  # a pause after 15 s is not taken

    def test_what_follows_a_cut_is_never_shorter_than_the_last_piece(self):
        pcm = LOUD * 12 + QUIET + LOUD * 7  # 20 s; the pause 12 to 13 s is within the 3 s before 15 s
        c = self.cut(pcm)
        self.assertTrue(12.0 <= c <= 13.0 and 20 - c >= 5, c)

    def test_the_next_cut_counts_from_the_cut_before(self):
        rms = levels(LOUD * 34).rms
        self.assertIsNone(a.live_cut(rms, round(15 / a.FRAME_S), 15, 3, 5))  # 19 s since the cut at 15 s
        self.assertEqual(a.live_cut(levels(LOUD * 35).rms, round(15 / a.FRAME_S), 15, 3, 5), round(30 / a.FRAME_S))


class LevelsTest(unittest.TestCase):
    def test_the_threshold_follows_the_noise_floor_of_a_loud_microphone(self):
        noise, speech = tone(100), tone(2300)  # -50.3 and -23.1 dBFS: a microphone at full input volume
        lv = levels(noise * 3 + speech + noise * 3 + speech)
        r = lv.report()
        self.assertEqual(r["noise_floor_dbfs"], -50.3)
        self.assertEqual(r["threshold_dbfs"], -38.3)  # the floor + 12 dB, above -45
        self.assertAlmostEqual(r["speech_fraction"], 0.25, delta=0.01)  # the noise is not speech
        self.assertEqual(split(noise * 3), [])  # and alone never becomes a piece

    def test_a_quiet_microphone_keeps_the_lowest_threshold(self):
        r = levels(tone(20) * 3 + tone(500)).report()  # noise -64.3, speech -36.3 dBFS
        self.assertEqual(r["threshold_dbfs"], -45.0)
        self.assertAlmostEqual(r["speech_fraction"], 0.25, delta=0.01)

    def test_speech_without_pauses_still_counts(self):
        self.assertEqual(levels(LOUD * 5).report()["speech_fraction"], 1.0)  # the cap: 6 dB under the 90th percentile
        self.assertEqual(split(LOUD * 5), [5.0])


    def test_speech_noise_clipping_and_digital_silence(self):
        clip = array.array("h", [32767, -32768] * (a.RATE // 2)).tobytes()
        r = levels(LOUD * 2 + QUIET + clip).report()
        self.assertEqual(r["seconds"], 3.99)
        self.assertEqual(r["peak_dbfs"], 0.0)
        self.assertEqual(r["clipped_samples"], 33 * a.FRAME)  # whole 30 ms frames; the last 10 ms wait for more
        self.assertGreaterEqual(r["longest_digital_silence_s"], 0.96)  # the 1 s of zeros
        self.assertEqual(len(r["dbfs_per_second"]), 4)

    def test_chunks_of_any_size_give_the_same_levels(self):
        data = LOUD + QUIET + LOUD
        self.assertEqual(levels(data, 999).rms, levels(data).rms)  # frames and samples split across chunks


if __name__ == "__main__":
    unittest.main()
