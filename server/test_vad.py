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


def speech_in(pcm):
    return vad.speech_seconds(vad.shared().probabilities(pcm))


class VadTest(unittest.TestCase):
    def test_speech_is_found_and_silence_and_a_tone_are_not(self):
        self.assertGreater(speech_in(speech()), 1.0)
        self.assertEqual(speech_in(b"\0\0" * 32000), 0)
        self.assertEqual(speech_in(array.array("h", [8000, -8000] * 16000).tobytes()), 0)

    def test_onnxruntime_telemetry_is_off(self):
        self.assertEqual(os.environ.get("ORT_DISABLE_TELEMETRY"), "1")

    def test_audio_of_any_length_works(self):
        self.assertEqual(len(vad.shared().probabilities(b"\0\0" * 100)), 1)  # padded to one chunk
        self.assertEqual(speech_in(b""), 0)

    def test_a_stream_in_any_parts_finds_what_one_run_finds(self):
        whole = vad.shared().probabilities(speech())
        s = vad.Stream()
        audio = b"\0\0" * 16000 + speech()  # 1 s of silence, then the speech
        heard = [s.feed(audio[i:i + 3200]) for i in range(0, len(audio), 3200)]  # 100 ms at a time, as the app sends
        s.flush()
        self.assertFalse(any(heard[:10]))
        self.assertTrue(any(heard[10:]))
        self.assertEqual(s.seconds(0, 1), 0)
        self.assertAlmostEqual(s.seconds(1), vad.speech_seconds(whole), delta=0.1)
