"""Audio of a recording: loudness per 30 ms frame, the cutting into pieces for the model, WAV."""
import array
import math
import struct

from constants import RATE, SAMPLE_BYTES

FRAME_S = 0.03                      # the loudness is measured per 30 ms
FRAME = round(RATE * FRAME_S)       # samples in a frame
FRAME_BYTES = FRAME * SAMPLE_BYTES


def seconds(pcm_or_bytes):
    """Seconds of 16-bit mono audio, from the audio or its length in bytes."""
    n = pcm_or_bytes if isinstance(pcm_or_bytes, int) else len(pcm_or_bytes)
    return n / SAMPLE_BYTES / RATE


def db(rms):
    """dBFS of an RMS or peak of 16-bit samples; -120 for digital silence."""
    return round(20 * math.log10(rms / 32768), 1) if rms > 0 else -120.0


class Levels:
    """The loudness of a recording as it arrives, in 30 ms frames: RMS per frame (where the cuts go: quietness), the
    peak, clipped samples, and runs of digital silence (all-zero frames: a microphone that is closed, muted or gone
    gives zeros, not quiet noise). What is speech is Silero VAD's (vad.py)."""

    def __init__(self):
        self.rms, self.rest = [], b""
        self.peak, self.clipped, self.zero_run, self.longest_zero = 0, 0, 0, 0

    def feed(self, pcm):
        data = self.rest + pcm
        n = len(data) // (FRAME_BYTES) * FRAME_BYTES
        self.rest = data[n:]
        for i in range(0, n, FRAME_BYTES):
            samples = array.array("h", data[i:i + FRAME_BYTES])
            self.rms.append(math.sqrt(sum(x * x for x in samples) / len(samples)))
            peak = max(-min(samples), max(samples))
            self.peak = max(self.peak, peak)
            self.clipped += sum(1 for x in samples if x >= 32767 or x <= -32768)
            self.zero_run = self.zero_run + 1 if peak == 0 else 0
            self.longest_zero = max(self.longest_zero, self.zero_run)

    def report(self, is_speech):
        """The recording's levels, for audio.json and the metrics. `is_speech(t)`: whether the moment t seconds
        into the recording is speech (the VAD's)."""
        speech, rest = [], []
        for k, r in enumerate(self.rms):
            (speech if is_speech((k + 0.5) * FRAME_S) else rest).append(r)
        rest.sort()
        by_second = {}
        for k, r in enumerate(self.rms):  # frame k starts at FRAME_S k seconds
            by_second.setdefault(int(k * FRAME_S), []).append(r)
        per_second = [db(math.sqrt(sum(r * r for r in v) / len(v))) for _, v in sorted(by_second.items())]
        return {"seconds": round(len(self.rms) * FRAME_S, 2), "peak_dbfs": db(self.peak),
                "speech_dbfs": db(math.sqrt(sum(r * r for r in speech) / len(speech))) if speech else None,
                "noise_dbfs": db(rest[len(rest) // 2]) if rest else None,
                "speech_fraction": round(len(speech) / len(self.rms), 3) if self.rms else 0,
                "clipped_samples": self.clipped, "longest_digital_silence_s": round(self.longest_zero * FRAME_S, 2),
                "dbfs_per_second": per_second}


def quietness(rms, k):
    """How loud the 300 ms around frame k are: the mean RMS of its 10 frames (fewer at the ends)."""
    around = rms[max(0, k - 5):k + 5]
    return sum(around) / len(around)


def live_cut(rms, start, piece_s, search_s, last_s):
    """While the speaker talks, the length of a recording is not known: where to cut the next piece, a frame, or None
    for not yet. `start` is the frame of the cut before. A piece is cut once `piece_s` + `last_s` seconds were heard
    since that cut, at the quietest 300 ms within `search_s` before `piece_s` from it. So the piece is
    `piece_s` - `search_s` to `piece_s` long, and the audio after it is never shorter than `last_s`, the piece after
    the stop included. `rms`: the RMS of each 30 ms frame (Levels)."""
    if len(rms) - start < int((piece_s + last_s) / FRAME_S):  # whole frames: 20 s are 666 of them
        return None
    ideal = start + round(piece_s / FRAME_S)
    lo = max(start + 1, ideal - max(1, int(search_s / FRAME_S)))
    return min(range(lo, ideal + 1), key=lambda c: (quietness(rms, c), ideal - c))


def split(pcm, rms, piece_s, search_s, max_s=30):
    """Cuts audio whose length is known (a whole recording, or what is left of it at the stop) into pieces for the
    model. The number of pieces makes them as close to `piece_s` as possible, and none longer than the model takes
    (`max_s`, its catalog entry's maxAudioSeconds): round(length / piece_s), at least ceil(length / max_s). The pieces
    are equal, except that each cut moves to the quietest 300 ms within `search_s` of its equal point, so no cut falls
    inside a word. → [(the piece, its start and end in seconds from the start of `pcm`)].
    `rms`: the RMS of each 30 ms frame (Levels)."""
    frames = len(rms)
    if frames == 0:
        return [(pcm, 0.0, seconds(pcm))] if pcm else []
    total = frames * FRAME_S
    n = max(1, math.ceil(total / max_s), math.floor(total / piece_s + 0.5))
    most, search = int(max_s / FRAME_S), max(1, int(search_s / FRAME_S))
    smooth = [quietness(rms, k) for k in range(frames)]
    cuts = [0]
    for k in range(1, n):
        ideal = round(k * frames / n)
        lo = max(cuts[-1] + 1, ideal - search, frames - (n - k) * most)
        hi = min(frames - 1, ideal + search, cuts[-1] + most)
        if lo > hi:
            lo = hi = min(max(ideal, cuts[-1] + 1), frames - 1)
        cuts.append(min(range(lo, hi + 1), key=lambda c: (smooth[c], abs(c - ideal))))
    cuts.append(frames)
    return [(pcm[a * FRAME_BYTES:(b * FRAME_BYTES if b < frames else len(pcm))], a * FRAME_S,
             b * FRAME_S if b < frames else seconds(pcm)) for a, b in zip(cuts, cuts[1:])]


def wav_header(data_bytes):
    """The 44-byte header of a WAV file with `data_bytes` of this audio (16 kHz, 16-bit, mono, PCM)."""
    return (b"RIFF" + struct.pack("<I", 36 + data_bytes) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 1, 1, RATE, RATE * SAMPLE_BYTES, SAMPLE_BYTES, 8 * SAMPLE_BYTES) + b"data" +
            struct.pack("<I", data_bytes))


def wav(pcm):
    """The audio as a WAV file."""
    return wav_header(len(pcm)) + bytes(pcm)
