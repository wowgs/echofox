"""Tests of audio.py: levels and cutting. Run: server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import array
import unittest

import audio as a
from fakes import LOUD, QUIET, seconds


def levels(pcm, chunk=None):
    lv = a.Levels()
    for i in range(0, len(pcm), chunk or len(pcm) or 1):
        lv.feed(pcm[i:i + (chunk or len(pcm))])
    return lv


def split(pcm, piece_s=20, pauses=(), min_s=8, max_s=25):
    lv = levels(pcm)
    return [round(seconds(p), 1) for p, _, _ in a.split(pcm, lv.rms, list(pauses), piece_s, min_s, max_s)]


class SplitTest(unittest.TestCase):
    def test_a_recording_near_the_wanted_length_is_one_piece(self):
        self.assertEqual(split(LOUD + QUIET + LOUD), [3.0])
        self.assertEqual(split(LOUD * 28), [28.0])  # round(28 / 20) = 1, and 28 s fits the model

    def test_the_pieces_cover_the_audio_and_say_where_they_are(self):
        lv = levels(LOUD * 45)
        pieces = a.split(LOUD * 45, lv.rms, [], 20, 8, 25)
        self.assertEqual([(s, e) for _, s, e in pieces], [(0.0, 22.5), (22.5, 45.0)])
        self.assertEqual(b"".join(p for p, _, _ in pieces), LOUD * 45)

    def test_pieces_are_equal_and_as_close_to_the_wanted_length_as_possible(self):
        self.assertEqual(split(LOUD * 45), [22.5, 22.5])  # 2 pieces of 22.5 s, not 20 + 20 + 5
        self.assertEqual(sorted(split(LOUD * 62)), [20.6, 20.7, 20.7])

    def test_none_is_longer_than_the_model_takes(self):
        self.assertTrue(all(x <= 30 for x in split(LOUD * 61, piece_s=30, max_s=30)))
        self.assertEqual(len(split(LOUD * 61, piece_s=30, max_s=30)), 3)  # round(61 / 30) = 2 makes 30.5 s pieces

    def test_without_a_pause_a_cut_moves_into_the_quietest_place(self):
        pieces = split(LOUD * 19 + QUIET + LOUD * 21)  # the equal point is 20.5 s, the quiet second 19 to 20 s
        self.assertEqual(len(pieces), 2)
        self.assertTrue(19.0 <= pieces[0] <= 20.0, pieces)

    def test_a_pause_wins_over_a_quieter_place_and_the_nearest_pause_to_the_equal_point_wins(self):
        pcm = LOUD * 20 + QUIET + LOUD * 24  # 45 s: the equal point 22.5 s; the level is lowest at 20 to 21 s
        self.assertEqual(split(pcm, pauses=[(16.0, 16.4), (24.0, 24.4)])[0], 24.2)  # 1.7 s from it, not 6.3 s
        self.assertEqual(split(pcm, pauses=[(5.0, 5.4)]), split(pcm))  # before 8 s: as without it

    def test_a_cut_leaves_the_shortest_piece_to_the_pieces_after_it(self):
        self.assertEqual(split(LOUD * 40, pauses=[(36.0, 36.5)]), [20.0, 20.0])  # 4 s after it would be too short


def tone(amplitude, seconds=1):
    return array.array("h", [amplitude, -amplitude] * int(a.RATE * seconds / 2)).tobytes()


class LiveCutTest(unittest.TestCase):
    def cut(self, pcm, pauses=(), start=0, piece_s=15, min_s=8, max_s=25, last_s=5):
        c = a.live_cut(levels(pcm).rms, list(pauses), start, piece_s, min_s, max_s, last_s)
        return None if c is None else round(c * a.FRAME_S, 2)

    def test_no_cut_before_the_piece_and_the_last_piece_are_heard(self):
        self.assertIsNone(self.cut(LOUD * 19, [(14.9, 15.1)]))
        self.assertIsNone(self.cut(LOUD * 20, [(14.9, 15.1)]))  # the pause goes on past the last 5 s: not all of it seen
        self.assertEqual(self.cut(LOUD * 21, [(14.9, 15.1)]), 15.0)  # the pause's middle

    def test_the_pause_nearest_to_the_wanted_length_once_no_nearer_one_can_come(self):
        pcm = LOUD * 20
        self.assertIsNone(self.cut(pcm, [(9.0, 9.4)]))  # 6 s before 15 s: one up to 21 s could be nearer
        self.assertEqual(self.cut(LOUD * 26, [(9.0, 9.4)]), 9.18)  # 21 s seen: no nearer pause came
        self.assertEqual(self.cut(LOUD * 26, [(9.0, 9.4), (17.0, 17.4)]), 17.19)  # 2.2 s after it, not 5.8 s before

    def test_without_a_pause_it_waits_for_the_longest_piece_then_takes_the_quietest_place(self):
        self.assertIsNone(self.cut(LOUD * 29))  # no pause in 8 to 24 s: a pause up to 25 s may still come
        self.assertEqual(self.cut(LOUD * 30), 15.0)  # none came: the quietest 300 ms, all equal, the nearest to 15 s
        self.assertTrue(20.0 <= self.cut(LOUD * 20 + QUIET + LOUD * 9) <= 21.0)  # the quiet second wins
        # 2026-11-05: a pause ended at 12.03 s, speech from 12.06 to 15 s. The pause is 3.15 s before 15 s, so it is
        # taken once 18.15 s are past the last 5 s, not a dip in the speech
        self.assertIsNone(self.cut(LOUD * 23, [(11.7, 12.03)]))
        self.assertEqual(self.cut(LOUD * 24, [(11.7, 12.03)]), 11.85)

    def test_the_next_cut_counts_from_the_cut_before(self):
        start = round(15 / a.FRAME_S)
        self.assertIsNone(a.live_cut(levels(LOUD * 34).rms, [], start, 15, 8, 25, 5))  # 19 s since the cut at 15 s
        c = a.live_cut(levels(LOUD * 45).rms, [(27.0, 27.4)], start, 15, 8, 25, 5)
        self.assertEqual(round(c * a.FRAME_S, 1), 27.2)  # the pause 12 s after the cut before


class LevelsTest(unittest.TestCase):
    def test_speech_and_noise_are_where_the_vad_says(self):
        noise, speech = tone(100), tone(2300)  # -50.3 and -23.1 dBFS
        r = levels(noise * 3 + speech).report(lambda t: t >= 3)
        self.assertEqual((r["noise_dbfs"], r["speech_dbfs"]), (-50.3, -23.1))
        self.assertAlmostEqual(r["speech_fraction"], 0.25, delta=0.01)
        self.assertEqual(levels(noise).report(lambda t: False)["speech_dbfs"], None)

    def test_speech_noise_clipping_and_digital_silence(self):
        clip = array.array("h", [32767, -32768] * (a.RATE // 2)).tobytes()
        r = levels(LOUD * 2 + QUIET + clip).report(lambda t: True)
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
