"""Speech in audio, by Silero VAD (github.com/snakers4/silero-vad, MIT license, release v6.2.3: vad/silero_vad.onnx,
sha256 1a153a22…8788e3, and vad/LICENSE), run in onnxruntime without torch. As OnnxWrapper in the release's
src/silero_vad/utils_vad.py does: the model takes 512 samples at 16 kHz with the 64 samples before them and its
recurrent state, and gives the probability that the chunk is speech; a chunk is speech from 0.5 (the library's
default threshold). It is the server's only judge of speech: a piece of the recording with no speech never goes to
the model (on silence, Gemma wrote text of its own or copied the chat context: 2026-10-15 to 2026-10-22, 12 of 17
recordings with under 0.3 s of speech by the loudness threshold of that time), and the client hears "speech" from it.
One Stream runs a whole recording as it arrives, with one state: 0.1 ms per 32 ms chunk (Apple M5, 2.3 s of speech,
3 runs). In 275 saved pieces (2026-10-22 to 2026-10-25), its speech in a piece's stretch gave the same answer at
0.3 s as a run on the piece alone in every one."""
import os
import threading

# ONNX Runtime's Microsoft telemetry (1DS, to mobile.events.data.microsoft.com) is on by default on macOS too: with
# only this session loaded, a process kept a TLS connection to Microsoft's address 20.42.65.85, and with the switch it
# had none (onnxruntime 1.31.0, lsof, 2026-10-25). The switch must be set before onnxruntime loads; the call below
# also turns off its events.
os.environ["ORT_DISABLE_TELEMETRY"] = "1"

import numpy as np  # noqa: E402
import onnxruntime  # noqa: E402

onnxruntime.disable_telemetry_events()

from constants import RATE

MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vad", "silero_vad.onnx")
CHUNK = 512        # samples per model call at 16 kHz: 32 ms
CONTEXT = 64       # samples of the chunk before, given with each chunk
THRESHOLD = 0.5    # the library's default: a chunk is speech from this probability
CHUNK_S = CHUNK / RATE


class Vad:
    """One model session, for the whole server: the calls take turns."""

    def __init__(self, path=MODEL):
        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = opts.intra_op_num_threads = 1
        self.session = onnxruntime.InferenceSession(path, sess_options=opts, providers=["CPUExecutionProvider"])
        self.sr = np.array(RATE, dtype=np.int64)
        self.lock = threading.Lock()

    def run(self, chunk, context, state):
        """One chunk of CHUNK samples → (its speech probability, the next state)."""
        with self.lock:
            p, state = self.session.run(None, {"input": np.concatenate([context, chunk])[None, :], "state": state,
                                               "sr": self.sr})
        return float(p[0][0]), state


_shared, _shared_lock = None, threading.Lock()


def shared():
    """The server's one Vad, made at its first use."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = Vad()
        return _shared


class Stream:
    """The speech in one recording as its audio arrives: the probability of each 32 ms chunk."""

    def __init__(self, vad=None):
        self.vad = vad or shared()
        self.probabilities, self.rest = [], np.zeros(0, np.float32)
        self.state, self.context = np.zeros((2, 1, 128), np.float32), np.zeros(CONTEXT, np.float32)

    def feed(self, pcm):
        """Runs the whole chunks of the new audio; True if one of them is speech."""
        x = np.concatenate([self.rest, np.frombuffer(bytes(pcm), dtype="<i2").astype(np.float32) / 32768.0])
        n = len(x) // CHUNK * CHUNK
        self.rest, heard = x[n:], False
        for i in range(0, n, CHUNK):
            heard = self._run(x[i:i + CHUNK]) >= THRESHOLD or heard
        return heard

    def flush(self):
        """The rest of the audio, padded with zeros to a whole chunk."""
        if len(self.rest):
            self._run(np.concatenate([self.rest, np.zeros(CHUNK - len(self.rest), np.float32)]))
            self.rest = np.zeros(0, np.float32)

    def _run(self, chunk):
        p, self.state = self.vad.run(chunk, self.context, self.state)
        self.context = chunk[-CONTEXT:]
        self.probabilities.append(p)
        return p

    def at(self, t):
        """Whether the moment t seconds into the recording is speech."""
        k = int(t / CHUNK_S)
        return k < len(self.probabilities) and self.probabilities[k] >= THRESHOLD

    def seconds(self, start_s=0.0, end_s=None):
        """Seconds of speech between two times of the recording: the chunks that start in that stretch."""
        a = round(start_s / CHUNK_S)
        b = len(self.probabilities) if end_s is None else round(end_s / CHUNK_S)
        return speech_seconds(self.probabilities[a:b])


def speech_seconds(probabilities, threshold=THRESHOLD):
    """Seconds of the chunks that are speech."""
    return sum(p >= threshold for p in probabilities) * CHUNK_S
