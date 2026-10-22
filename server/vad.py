"""Speech in audio, by Silero VAD (github.com/snakers4/silero-vad, MIT license, release v6.2.3: vad/silero_vad.onnx,
sha256 1a153a22…8788e3, and vad/LICENSE), run in onnxruntime without torch. As OnnxWrapper in the release's
src/silero_vad/utils_vad.py does: the model takes 512 samples at 16 kHz with the 64 samples before them and its
recurrent state, and gives the probability that the chunk is speech; a chunk is speech from 0.5 (the library's
default threshold). A piece of the recording with no speech never goes to the model: on silence, Gemma wrote text
of its own or copied the chat context (2026-10-15 to 2026-10-22, 12 of 17 recordings with under 0.3 s of speech by
the loudness threshold)."""
import os
import threading

import numpy as np
import onnxruntime

from constants import RATE

MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vad", "silero_vad.onnx")
CHUNK = 512        # samples per model call at 16 kHz: 32 ms
CONTEXT = 64       # samples of the chunk before, given with each chunk
THRESHOLD = 0.5    # the library's default: a chunk is speech from this probability
CHUNK_S = CHUNK / RATE


class Vad:
    """One model session; probabilities() runs a whole stretch of audio from a fresh state."""

    def __init__(self, path=MODEL):
        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = opts.intra_op_num_threads = 1
        self.session = onnxruntime.InferenceSession(path, sess_options=opts, providers=["CPUExecutionProvider"])
        self.sr = np.array(RATE, dtype=np.int64)

    def probabilities(self, pcm):
        """16-bit mono PCM at 16 kHz → the speech probability of each 32 ms chunk (the last one padded with zeros)."""
        x = np.frombuffer(bytes(pcm), dtype="<i2").astype(np.float32) / 32768.0
        if len(x) % CHUNK:
            x = np.concatenate([x, np.zeros(CHUNK - len(x) % CHUNK, np.float32)])
        state, context, out = np.zeros((2, 1, 128), np.float32), np.zeros(CONTEXT, np.float32), []
        for i in range(0, len(x), CHUNK):
            chunk = x[i:i + CHUNK]
            p, state = self.session.run(None, {"input": np.concatenate([context, chunk])[None, :], "state": state,
                                               "sr": self.sr})
            out.append(float(p[0][0]))
            context = chunk[-CONTEXT:]
        return out


def speech_seconds(probabilities, threshold=THRESHOLD):
    """Seconds of the chunks that are speech."""
    return sum(p >= threshold for p in probabilities) * CHUNK_S


_shared, _lock = None, threading.Lock()


def speech_in(pcm):
    """Seconds of speech in the audio, by one model session for the whole server: the calls take turns (31 ms a piece
    on average: 63 s for the 2038 saved pieces, Apple M5)."""
    global _shared
    with _lock:
        if _shared is None:
            _shared = Vad()
        return speech_seconds(_shared.probabilities(pcm))
