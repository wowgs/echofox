import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import array
import os
import unittest
import wave

import vad

HERE = os.path.dirname(os.path.abspath(__file__))


def speech():
    """2.25 s of Russian speech (macOS say, voice Milena: «Проверь, пожалуйста, коммит.»), 16 kHz mono 16-bit."""
    with wave.open(os.path.join(HERE, "testdata", "speech-ru.wav")) as w:
        return w.readframes(w.getnframes())


class VadTest(unittest.TestCase):
    def test_speech_is_found_and_silence_and_a_tone_are_not(self):
        self.assertGreater(vad.speech_in(speech()), 1.0)
        self.assertEqual(vad.speech_in(b"\0\0" * 32000), 0)
        self.assertEqual(vad.speech_in(array.array("h", [8000, -8000] * 16000).tobytes()), 0)

    def test_audio_of_any_length_works(self):
        self.assertEqual(len(vad.Vad().probabilities(b"\0\0" * 100)), 1)  # padded to one chunk
        self.assertEqual(vad.speech_in(b""), 0)
