"""Audio of a recording: loudness per 30 ms frame, the cutting into pieces for the model, WAV."""
import array
import bisect
import math
import struct

from constants import MODEL_MAX_SECONDS, RATE, SAMPLE_BYTES

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
    """The loudness of a recording as it arrives, in 30 ms frames: RMS per frame, the peak, clipped samples, and runs
    of digital silence (all-zero frames: a microphone that is closed, muted or gone gives zeros, not quiet noise).
    A frame is speech when it is louder than the threshold: the higher of `threshold_db` dBFS and the noise floor plus
    `above_noise_db`, but never above the 90th percentile less 6 dB, so speech without pauses (whose 10th percentile
    is speech too) still counts. The noise floor is the 10th percentile of the frames' RMS so far (all-zero frames
    left out), so the threshold follows the microphone's gain: at a high input volume the room noise alone can pass
    -45 dBFS.
    `heard` tells whether the last feed() had speech."""

    def __init__(self, threshold_db, above_noise_db=12.0):
        self.floor_threshold = 32768 * 10 ** (threshold_db / 20)
        self.above = 10 ** (above_noise_db / 20)
        self.rms, self.sorted, self.rest, self.heard = [], [], b"", False
        self.peak, self.clipped, self.zero_run, self.longest_zero = 0, 0, 0, 0

    def noise_floor(self):
        """The 10th percentile of the non-zero frames' RMS, or None before 1 s of them."""
        return self.sorted[len(self.sorted) // 10] if len(self.sorted) >= 33 else None

    @property
    def threshold(self):
        floor = self.noise_floor()
        if not floor:
            return self.floor_threshold
        loud = self.sorted[len(self.sorted) * 9 // 10] / 2  # the 90th percentile less 6 dB
        return max(self.floor_threshold, min(floor * self.above, loud))

    def feed(self, pcm):
        self.heard = False
        data = self.rest + pcm
        n = len(data) // (FRAME_BYTES) * FRAME_BYTES
        self.rest = data[n:]
        for i in range(0, n, FRAME_BYTES):
            samples = array.array("h", data[i:i + FRAME_BYTES])
            rms = math.sqrt(sum(x * x for x in samples) / len(samples))
            self.rms.append(rms)
            if rms > 0:
                bisect.insort(self.sorted, rms)
            self.heard = self.heard or rms > self.threshold
            peak = max(-min(samples), max(samples))
            self.peak = max(self.peak, peak)
            self.clipped += sum(1 for x in samples if x >= 32767 or x <= -32768)
            self.zero_run = self.zero_run + 1 if peak == 0 else 0
            self.longest_zero = max(self.longest_zero, self.zero_run)

    def report(self):
        """The recording's levels, for audio.json and the metrics."""
        threshold, floor = self.threshold, self.noise_floor()
        speech = [r for r in self.rms if r > threshold]
        rest = sorted(r for r in self.rms if r <= threshold)
        by_second = {}
        for k, r in enumerate(self.rms):  # frame k starts at FRAME_S k seconds
            by_second.setdefault(int(k * FRAME_S), []).append(r)
        per_second = [db(math.sqrt(sum(r * r for r in v) / len(v))) for _, v in sorted(by_second.items())]
        return {"seconds": round(len(self.rms) * FRAME_S, 2), "peak_dbfs": db(self.peak),
                "speech_dbfs": db(math.sqrt(sum(r * r for r in speech) / len(speech))) if speech else None,
                "noise_dbfs": db(rest[len(rest) // 2]) if rest else None,
                "speech_fraction": round(len(speech) / len(self.rms), 3) if self.rms else 0,
                "clipped_samples": self.clipped, "longest_digital_silence_s": round(self.longest_zero * FRAME_S, 2),
                "noise_floor_dbfs": db(floor) if floor else None, "threshold_dbfs": db(threshold),
                "dbfs_per_second": per_second}


def split(pcm, rms, threshold, piece_s, search_s):
    """Cuts a whole recording into pieces for the model, after the stop, when its length is known. The number of
    pieces makes them as close to `piece_s` as possible, and none longer than the model takes (30 s): round(length /
    piece_s), at least ceil(length / 30). The pieces are equal, except that each cut moves to the quietest 300 ms
    within `search_s` of its equal point, so no cut falls inside a word. Pieces without speech are dropped.
    `rms`: the RMS of each 30 ms frame (Levels)."""
    frames = len(rms)
    if frames == 0:
        return [pcm] if pcm else []
    total = frames * FRAME_S
    n = max(1, math.ceil(total / MODEL_MAX_SECONDS), math.floor(total / piece_s + 0.5))
    most, search = int(MODEL_MAX_SECONDS / FRAME_S), max(1, int(search_s / FRAME_S))
    smooth = [sum(rms[max(0, k - 5):k + 5]) / len(rms[max(0, k - 5):k + 5]) for k in range(frames)]
    cuts = [0]
    for k in range(1, n):
        ideal = round(k * frames / n)
        lo = max(cuts[-1] + 1, ideal - search, frames - (n - k) * most)
        hi = min(frames - 1, ideal + search, cuts[-1] + most)
        if lo > hi:
            lo = hi = min(max(ideal, cuts[-1] + 1), frames - 1)
        cuts.append(min(range(lo, hi + 1), key=lambda c: (smooth[c], abs(c - ideal))))
    cuts.append(frames)
    pieces = []
    for a, b in zip(cuts, cuts[1:]):
        if any(r > threshold for r in rms[a:b]):
            pieces.append(pcm[a * FRAME_BYTES:(b * FRAME_BYTES if b < frames else len(pcm))])
    return pieces


def wav_header(data_bytes):
    """The 44-byte header of a WAV file with `data_bytes` of this audio (16 kHz, 16-bit, mono, PCM)."""
    return (b"RIFF" + struct.pack("<I", 36 + data_bytes) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 1, 1, RATE, RATE * SAMPLE_BYTES, SAMPLE_BYTES, 8 * SAMPLE_BYTES) + b"data" +
            struct.pack("<I", data_bytes))


def wav(pcm):
    """The audio as a WAV file."""
    return wav_header(len(pcm)) + bytes(pcm)
