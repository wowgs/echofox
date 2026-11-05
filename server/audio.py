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


def frames(s):
    """The 30 ms frame nearest to `s` seconds."""
    return round(s / FRAME_S)


def pause_cuts(pauses, lo, hi):
    """The frame in the middle of each pause, of its part within frames lo..hi. `pauses`: [(start, end)] in seconds
    from frame 0, the stretches without speech (vad.pauses)."""
    out = []
    for start, end in pauses:
        a, b = max(lo, math.ceil(start / FRAME_S)), min(hi, math.floor(end / FRAME_S))
        if a <= b:
            out.append((a + b) // 2)
    return out


def quietest(rms, lo, hi, ideal):
    """The frame of lo..hi whose 300 ms are the quietest, the one nearest to `ideal` of equal ones."""
    return min(range(lo, hi + 1), key=lambda c: (quietness(rms, c), abs(c - ideal)))


def live_cut(rms, pauses, start, piece_s, min_s, max_s, last_s):
    """While the speaker talks, the length of a recording is not known: where to cut the next piece, a frame, or None
    for not yet. `start` is the frame of the cut before. Nothing is cut before `piece_s` + `last_s` seconds were heard
    since that cut, so that the audio after a cut is never shorter than `last_s`. The cut goes into the pause nearest
    to `piece_s` from `start` within `min_s` to `max_s`, once no pause still to be heard can be nearer; with no pause
    there, once `max_s` + `last_s` were heard, into the quietest 300 ms of that stretch. A pause is a stretch without
    speech by Silero VAD (vad.pauses): between words in a phrase there is none, and a dip of the level there may be the
    closure of a "п" or a "т" inside a word. (2026-11-05: in 12 to 15 s after the cut, VAD heard speech in every
    chunk; the quietest 300 ms fell between "посмотри" and "по", and the next piece began "Я этим" for "по этим"; a
    pause of 300 ms ended at 12.03 s.) `rms`: the RMS of each 30 ms frame (Levels)."""
    if len(rms) - start < int((piece_s + last_s) / FRAME_S):  # whole frames: 20 s are 666 of them
        return None
    lo, top, ideal = start + frames(min_s), start + frames(max_s), start + frames(piece_s)
    hi = min(top, len(rms) - frames(last_s))
    cuts = pause_cuts(pauses, lo, hi)
    if cuts:
        c = min(cuts, key=lambda c: (abs(c - ideal), c))
        return c if hi >= min(top, ideal + abs(c - ideal)) else None  # a pause still to come could be nearer
    return quietest(rms, lo, hi, ideal) if hi >= top else None


def split(pcm, rms, pauses, piece_s, min_s, max_s, max_audio=30):
    """Cuts audio whose length is known (what is left of a recording at the stop) into pieces for the model. The number
    of pieces makes them as close to `piece_s` as possible, and none longer than the model takes (`max_audio`, its
    catalog entry's maxAudioSeconds): round(length / piece_s), at least ceil(length / max_audio). Each cut goes into the
    pause nearest to its equal point, within `min_s` to `max_s` of the cut before and leaving `min_s` to each piece
    after it, else into the quietest 300 ms there (live_cut has why). → [(the piece, its start and end in seconds from
    the start of `pcm`)]. `rms`: the RMS of each 30 ms frame (Levels); `pauses`: as for live_cut, from the start of
    `pcm`."""
    n_frames = len(rms)
    if n_frames == 0:
        return [(pcm, 0.0, seconds(pcm))] if pcm else []
    total = n_frames * FRAME_S
    n = max(1, math.ceil(total / max_audio), math.floor(total / piece_s + 0.5))
    most, shortest, longest = frames(max_audio), frames(min_s), min(frames(max_s), frames(max_audio))
    cuts = [0]
    for k in range(1, n):
        ideal = round(k * n_frames / n)
        lo = max(cuts[-1] + 1, cuts[-1] + shortest, n_frames - (n - k) * most)
        hi = min(n_frames - 1, cuts[-1] + longest, n_frames - (n - k) * shortest)
        if lo > hi:
            lo = hi = min(max(ideal, cuts[-1] + 1), n_frames - 1)
        found = pause_cuts(pauses, lo, hi)
        cuts.append(min(found, key=lambda c: (abs(c - ideal), c)) if found else quietest(rms, lo, hi, ideal))
    cuts.append(n_frames)
    return [(pcm[a * FRAME_BYTES:(b * FRAME_BYTES if b < n_frames else len(pcm))], a * FRAME_S,
             b * FRAME_S if b < n_frames else seconds(pcm)) for a, b in zip(cuts, cuts[1:])]


def wav_header(data_bytes):
    """The 44-byte header of a WAV file with `data_bytes` of this audio (16 kHz, 16-bit, mono, PCM)."""
    return (b"RIFF" + struct.pack("<I", 36 + data_bytes) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 1, 1, RATE, RATE * SAMPLE_BYTES, SAMPLE_BYTES, 8 * SAMPLE_BYTES) + b"data" +
            struct.pack("<I", data_bytes))


def wav(pcm):
    """The audio as a WAV file."""
    return wav_header(len(pcm)) + bytes(pcm)
