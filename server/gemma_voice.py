"""A dictation server for local-voice: speech to text with Gemma 4 E4B in llama.cpp, for its clients (the menu bar
app; server/try_wav.py).

Clients are thin: they send the audio and show the text. The server has the rest: the model registry with each
model's prompt and options, the chat context, and the recordings. The protocol, on one WebSocket:
  client → server  {"type":"start","model":"<name>","language":"ru","sampleRate":16000,"encoding":"pcm_s16le",
                   "client":"<name>","sessions":["<session id>",…] or "app":"<bundle id>"}, then binary audio (16-bit
                   little-endian PCM, 16 kHz, mono), then {"type":"stop","reason":"user"|"silence"|"max_duration"}.
                   "sessions": the Claude Code sessions the text may go into, if the client knows them; "app": the app
                   with the input box, when the client knows no session (context.py). An experiment may also send
                   "prompt" and "options", which override the model's.
  server → client  {"type":"speech"} while it hears speech; {"type":"text","text":…} for each finished piece,
                   in order; {"type":"error","message":…}; {"type":"done"} after the last piece, then it closes

Gemma 4 takes at most 30 s of audio per request (model card and processor_config.json: 25 tokens per second,
750 tokens). The recording is cut after the stop, when its length is known: into pieces as close to --piece-seconds
as possible and equal, none longer than 30 s, each cut moved to the quietest moment near its equal point. Each piece
then goes to the model in a request of its own, so the model never sees its answers to earlier pieces (with them in
the conversation it repeated them). The prompt is Google's ASR template from the model card, unless the model has
its own, with the text before the audio, as the card advises.

The models run in llama.cpp's llama-server (server/llama_launchd.sh), through its OpenAI-compatible
/v1/chat/completions with the audio as "input_audio". The model's "options": sampling (temperature, topK, topP,
seed), maxOutputTokens, the chat history (chatHistoryTokenBudget, chatTermsTokenBudget) and the cutting
(pieceSeconds, cutSearchSeconds, thresholdDb, speechAboveNoiseDb). The server logs each recording's levels (speech,
noise, peak, clipping, digital silence) and keeps them in audio.json.

A piece's request holds the text before the audio (Claude's final replies in the session, within the option
chatHistoryTokenBudget, default 1000, terms within chatTermsTokenBudget, default a tenth of it, then the prompt) and
the piece's audio. llama-server keeps the text's prefix in its cache between requests (cache_prompt).

The text of a piece is limited to --output-tokens-per-second tokens per second of its audio plus
--output-tokens-base (maxOutputTokens overrides it): without a limit, a model that never writes its end token
decodes until the context is full.

Each recording gets a folder in --recordings (recordings.py): the whole audio (mic.wav), adapter.json, each piece's
audio, the text before the audio, each piece's text (pieces.jsonl) and the levels (audio.json); "saveRecordings":
false in the config turns this off.
"""
import argparse
import array
import base64
import asyncio
import bisect
import contextlib
import ctypes
import ctypes.util
import http.client
import io
import json
import logging
import math
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
import wave

from websockets.asyncio.server import serve

import context
import recordings

RATE = 16000
FRAME = RATE * 30 // 1000  # 30 ms of samples
MODEL_MAX_SECONDS = 30  # Gemma 4: at most 30 s of audio per request
SPEECH_EVERY_S = 0.3
MAX_PROMPT = 4000  # the menu allows the same
# The default limit of a piece's text: tokens per second of audio, plus a base. The densest piece in the metrics so
# far had 95 tokens for 20.6 s (4.6 per second); 10 per second leaves twice that.
OUTPUT_TOKENS_PER_SECOND = 10
OUTPUT_TOKENS_BASE = 32
# Tokens of the Claude Code chat history before the audio, when the options do not set chatHistoryTokenBudget.
CHAT_HISTORY_TOKEN_BUDGET = 1000
# The sampler when the options do not set it: Google's for Gemma 4 (generation_config.json of google/gemma-4-E4B-it
# and google/gemma-4-12B-it: do_sample, temperature 1.0, top_k 64, top_p 0.95; the model card: "Use the following
# standardized sampling configuration across all use cases"). It goes with every request, so llama-server's own
# defaults never apply.
SAMPLER = {"temperature": 1.0, "top_k": 64, "top_p": 0.95}
RECORDINGS = os.path.expanduser("~/speech/recordings")  # set from the settings in main()
SAVE_RECORDINGS = True
LANGUAGES = {"cs": "Czech", "da": "Danish", "nl": "Dutch", "en": "English", "fr": "French", "de": "German",
             "el": "Greek", "hi": "Hindi", "id": "Indonesian", "it": "Italian", "ja": "Japanese", "ko": "Korean",
             "no": "Norwegian", "pl": "Polish", "pt": "Portuguese", "ru": "Russian", "es": "Spanish",
             "sv": "Swedish", "tr": "Turkish", "uk": "Ukrainian"}
# Google's ASR prompt for Gemma 4 (model card, "Audio"); the second form, for an unknown language, is the
# one in the card's code example.
FORMAT = ("Follow these specific instructions for formatting the answer:\n"
          "* Only output the transcription, with no newlines.\n"
          "* When transcribing numbers, write the digits, i.e. write 1.7 and not one point seven, "
          "and write 3 instead of three.")
log = logging.getLogger("gemma_voice")

# Metrics: one JSON object per line in METRICS, for server/metrics.py or any JSON tool. "event" is "prepare" (the
# text before the audio), "piece" (one model request: tokens, speeds, times, llama-server's memory), "cancelled", "audio" (a recording's
# levels) or "recording" (one connection: pieces, audio, the wait after the stop).
METRICS = os.path.expanduser("~/Library/Logs/local-voice/gemma-voice-metrics.jsonl")


def metric(event, **fields):
    try:
        os.makedirs(os.path.dirname(METRICS), exist_ok=True)
        with open(METRICS, "a", encoding="utf-8") as f:
            f.write(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event, **fields},
                               ensure_ascii=False) + "\n")
    except OSError:
        log.exception("cannot write the metrics")  # metrics never stop a transcription


def prompt(language, custom=""):
    """The client's prompt, if it sent one, with {LANGUAGE} replaced by the language's name; otherwise Google's."""
    name = LANGUAGES.get(language.split("-")[0])
    if custom:
        return custom.replace("{LANGUAGE}", name or "its original language")
    if name:
        return f"Transcribe the following speech segment in {name} into {name} text.\n\n{FORMAT}"
    return f"Transcribe the following speech segment in its original language.\n{FORMAT}"


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
        n = len(data) // (FRAME * 2) * FRAME * 2
        self.rest = data[n:]
        for i in range(0, n, FRAME * 2):
            samples = array.array("h", data[i:i + FRAME * 2])
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
        seconds = {}
        for k, r in enumerate(self.rms):  # frame k starts at 0.03 k s
            seconds.setdefault(int(k * 3 / 100), []).append(r)
        per_second = [db(math.sqrt(sum(r * r for r in v) / len(v))) for _, v in sorted(seconds.items())]
        return {"seconds": round(len(self.rms) * 0.03, 2), "peak_dbfs": db(self.peak),
                "speech_dbfs": db(math.sqrt(sum(r * r for r in speech) / len(speech))) if speech else None,
                "noise_dbfs": db(rest[len(rest) // 2]) if rest else None,
                "speech_fraction": round(len(speech) / len(self.rms), 3) if self.rms else 0,
                "clipped_samples": self.clipped, "longest_digital_silence_s": round(self.longest_zero * 0.03, 2),
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
    seconds = frames * 0.03
    n = max(1, math.ceil(seconds / MODEL_MAX_SECONDS), math.floor(seconds / piece_s + 0.5))
    most, search = int(MODEL_MAX_SECONDS / 0.03), max(1, int(search_s / 0.03))
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
            pieces.append(pcm[a * FRAME * 2:(b * FRAME * 2 if b < frames else len(pcm))])
    return pieces


def wav(pcm):
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return out.getvalue()


def sampler_of(options):
    """The sampler of a recording: SAMPLER, with temperature, top_k, top_p and seed from the options."""
    return {**SAMPLER, **{k: options[k] for k in ("temperature", "top_k", "top_p", "seed") if k in options}}


def output_limit(audio_seconds, options):
    if "max_output_tokens" in options:
        return options["max_output_tokens"]
    return math.ceil(OUTPUT_TOKENS_PER_SECOND * audio_seconds) + OUTPUT_TOKENS_BASE


def llama_post(url, path, body, timeout):
    req = urllib.request.Request(url + path, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


async def run_blocking(fn, *args, cancel=None):
    """fn(*args) in a thread. If the caller is cancelled, cancel() stops fn, and this waits until fn has returned,
    then raises: the next recording starts only when the model is free."""
    run = asyncio.ensure_future(asyncio.to_thread(fn, *args))
    try:
        return await asyncio.shield(run)
    except asyncio.CancelledError:
        if cancel:
            cancel()
        with contextlib.suppress(Exception):
            await run
        raise


_libproc = ctypes.CDLL(ctypes.util.find_library("proc")) if ctypes.util.find_library("proc") else None


def footprint_mb(pid):
    """A process's physical footprint in MB, as macOS counts it (proc_pid_rusage, rusage_info_v0: ri_phys_footprint
    is the 8th 64-bit field after the 16-byte uuid; the same number as `footprint <pid>`). None if unknown."""
    if not _libproc or not pid:
        return None
    buf = (ctypes.c_uint64 * 12)()
    if _libproc.proc_pid_rusage(int(pid), 0, ctypes.byref(buf)) != 0:
        return None
    return round(buf[2 + 7] / 2**20)


def listening_pid(port):
    """The process listening on this TCP port of this Mac, or None (lsof)."""
    try:
        out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True,
                             timeout=5).stdout.split()
        return int(out[0]) if out else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


class LlamaModel:
    """A model behind llama.cpp's llama-server. Its model, quantization and context are set where llama-server
    starts (server/llama_launchd.sh)."""

    def __init__(self, name, entry):
        self.name, self.url = name, entry["llamaServer"].rstrip("/")
        self.connection, self.pid = None, None  # the connection of the running request; llama-server's process
        log.info("model %s: llama-server at %s", name, self.url)

    def cancel(self):
        """Stops the running request: closing its connection makes llama-server stop decoding (llama-server 0.6.0,
        build 11429: with the connection closed after 1 s, the next request got its answer 0.2 s later; without,
        136 s later)."""
        conn = self.connection
        if conn is not None and conn.sock is not None:
            with contextlib.suppress(OSError):
                conn.sock.shutdown(2)

    def footprint_mb(self):
        """llama-server's physical footprint in MB, for the metrics; None if its process is not found."""
        if self.pid:
            with contextlib.suppress(OSError):
                os.kill(self.pid, 0)
                return footprint_mb(self.pid)
        url = urllib.parse.urlparse(self.url)
        self.pid = listening_pid(url.port or 80) if url.hostname in ("127.0.0.1", "localhost") else None
        return footprint_mb(self.pid)

    def tokenize(self, text):
        return llama_post(self.url, "/tokenize", {"content": text}, 30)["tokens"]

    def detokenize(self, ids):
        return llama_post(self.url, "/detokenize", {"tokens": list(ids)}, 30)["content"]

    def complete(self, text, pcm, limit, options):
        """One piece: the text, then the audio, in one request. (text, timings for the metrics)."""
        audio = base64.b64encode(wav(pcm)).decode("ascii")
        body = {"messages": [{"role": "user", "content": [
                    {"type": "text", "text": text},
                    {"type": "input_audio", "input_audio": {"data": audio, "format": "wav"}}]}],
                "max_tokens": limit, "stream": False, "cache_prompt": True, **sampler_of(options),
                # Gemma 4's template in llama.cpp lets the model think first (reasoning_content), which spent a
                # piece's whole token limit on "Here's a thinking process…" and left no text.
                "chat_template_kwargs": {"enable_thinking": False}}
        url = urllib.parse.urlparse(self.url)
        conn = self.connection = http.client.HTTPConnection(url.hostname, url.port or 80, timeout=300)
        try:
            conn.request("POST", "/v1/chat/completions", json.dumps(body).encode("utf-8"),
                         {"Content-Type": "application/json"})
            reply = conn.getresponse()
            if reply.status != 200:
                raise RuntimeError(f"llama-server: HTTP {reply.status}: {reply.read()[:300]!r}")
            r = json.loads(reply.read().decode("utf-8"))
        finally:
            self.connection = None
            conn.close()
        t = r.get("timings") or {}
        return (r["choices"][0]["message"]["content"] or "").strip(), {
            "ttft_seconds": round(t["prompt_ms"] / 1000, 3) if "prompt_ms" in t else None,
            "prefill_tokens": t.get("prompt_n"), "cached_tokens": t.get("cache_n"),
            "prefill_tps": [round(t["prompt_per_second"], 1)] if "prompt_per_second" in t else [],
            "decode_tokens": t.get("predicted_n", (r.get("usage") or {}).get("completion_tokens")),
            "decode_tps": [round(t["predicted_per_second"], 1)] if "predicted_per_second" in t else []}

    def dictation(self, text_prompt, options=None, meta=None, save_dir=None):
        return Dictation(self, text_prompt, options or {}, meta or {}, save_dir)


CONTEXT_HEADER = ("The speaker is talking with an AI assistant about software. The assistant's earlier replies "
                  "follow, oldest first. They show names and terms the speaker may use. Do not transcribe them.")
ROLES = {"user": "Speaker", "assistant": "Assistant"}


class Dictation:
    """One recording on one model. Each piece is a request of its own: the text (chat history, then the prompt),
    then the piece's audio. The model never sees its answers to earlier pieces: in one conversation for the whole
    recording, a piece often began by repeating the earlier piece's text (2026-10-14, Gemma 4 E4B)."""

    def __init__(self, model, text_prompt, options, meta, save_dir=None):
        self.m, self.prompt, self.options, self.meta, self.save_dir = model, text_prompt, options, meta, save_dir
        self.text, self.chat_tokens = text_prompt, 0

    def _build(self, context):
        """The text before the audio: the chat context within the token budget, then the prompt."""
        budget = self.options.get("chat_history_token_budget", CHAT_HISTORY_TOKEN_BUDGET)
        if not context or budget <= 0:
            return
        tokens = lambda s: len(self.m.tokenize(s))
        terms_budget = self.options.get("chat_terms_token_budget", budget // 10)
        terms, used = [], 0
        for term in context.get("terms") or []:
            n = tokens(term) + 1
            if used + n > terms_budget:
                break
            terms.append(term)
            used += n
        lines, left = [], budget - used
        for m in context.get("messages") or []:  # newest first
            line = f"{ROLES.get(m.get('role'), 'Speaker')}: {str(m.get('text', '')).strip()}"
            ids = self.m.tokenize(line)
            if len(ids) > left:
                if not lines and left > 32:  # the newest message alone is too long: its end
                    lines.append("…" + self.m.detokenize(ids[-(left - 2):]))
                    left = 0
                break
            lines.append(line)
            left -= len(ids)
        if not lines and not terms:
            return
        parts = [CONTEXT_HEADER]
        if terms:
            parts.append("Terms: " + ", ".join(terms))
        parts += reversed(lines)
        self.text = "\n\n".join(parts) + "\n\n---\n\n" + self.prompt
        self.chat_tokens = tokens(self.text) - tokens(self.prompt)
        self.meta = {**self.meta, "chat_tokens": self.chat_tokens, "chat_messages": len(lines),
                     "chat_terms": len(terms)}

    async def prepare(self, context=None):
        """Builds the text before the audio."""
        t = time.monotonic()
        await run_blocking(self._build, context)
        seconds = time.monotonic() - t
        log.info("%s: text before the audio ready in %.2f s, %d tokens of chat history and terms", self.m.name,
                 seconds, self.chat_tokens)
        metric("prepare", model=self.m.name, **self.meta, seconds=round(seconds, 3))
        self._save("text-before-audio.txt", self.text.encode("utf-8"))

    async def piece(self, pcm, piece):
        t, audio = time.monotonic(), len(pcm) / 2 / RATE
        limit = output_limit(audio, self.options)
        meta = {**self.meta, "piece": piece}
        try:
            text, timings = await run_blocking(self.m.complete, self.text, pcm, limit, self.options,
                                               cancel=getattr(self.m, "cancel", None))
        except asyncio.CancelledError:
            log.warning("%s: the transcription of %.1f s of audio was cancelled after %.2f s", self.m.name, audio,
                        time.monotonic() - t)
            metric("cancelled", model=self.m.name, **meta, audio_seconds=round(audio, 2),
                   wall_seconds=round(time.monotonic() - t, 3))
            raise
        seconds = time.monotonic() - t
        timings["llama_footprint_mb"] = await asyncio.to_thread(self.m.footprint_mb) if hasattr(self.m, "footprint_mb") \
            else None
        hit = timings.get("decode_tokens") is not None and timings["decode_tokens"] >= limit
        log.info("%s: piece %d, %.1f s of audio in %.2f s, %s prefill (%s cached) + %s decode tokens: %r", self.m.name,
                 piece, audio, seconds, timings.get("prefill_tokens"), timings.get("cached_tokens"),
                 timings.get("decode_tokens"), text)
        if hit:
            log.warning("%s: the text reached the limit of %d tokens for %.1f s of audio and was cut", self.m.name,
                        limit, audio)
        metric("piece", model=self.m.name, **meta, audio_seconds=round(audio, 2), wall_seconds=round(seconds, 3),
               text_chars=len(text), output_limit=limit, output_limit_hit=hit, **timings)
        self._save(f"piece-{piece}.wav", wav(pcm))
        self._save("pieces.jsonl", (json.dumps({"piece": piece, "audio_seconds": round(audio, 2), "text": text,
                                                "output_limit": limit, "output_limit_hit": hit, **timings},
                                               ensure_ascii=False) + "\n").encode("utf-8"), append=True)
        return text

    def _save(self, name, data, append=False):
        if not self.save_dir:
            return
        try:
            os.makedirs(self.save_dir, exist_ok=True)
            with open(os.path.join(self.save_dir, name), "ab" if append else "wb") as f:
                f.write(data)
        except OSError:
            log.exception("cannot save %s", name)

    def close(self):
        pass


def audio_levels(recording, report, save_dir):
    """Logs a recording's levels, warns about signs of a bad microphone, and keeps them in audio.json."""
    if report["longest_digital_silence_s"] >= 0.5:
        log.warning("recording %s: %.2f s of digital silence (all zeros): the microphone may have been closed or muted",
                    recording, report["longest_digital_silence_s"])
    if report["clipped_samples"]:
        log.warning("recording %s: %d clipped samples: the input is too loud", recording, report["clipped_samples"])
    log.info("recording %s: %.1f s, speech %s dBFS, noise %s dBFS (floor %s), threshold %s dBFS, peak %s dBFS, "
             "speech in %.0f%% of the time", recording, report["seconds"], report["speech_dbfs"], report["noise_dbfs"],
             report["noise_floor_dbfs"], report["threshold_dbfs"], report["peak_dbfs"], 100 * report["speech_fraction"])
    metric("audio", recording=recording, **{k: v for k, v in report.items() if k != "dbfs_per_second"})
    if save_dir:
        try:
            os.makedirs(save_dir, exist_ok=True)
            with open(os.path.join(save_dir, "audio.json"), "w", encoding="utf-8") as f:
                json.dump(report, f, indent=1)
        except OSError:
            log.exception("cannot save audio.json")


LAUNCHCTL = os.environ.get("LOCAL_VOICE_LAUNCHCTL", "launchctl")  # tests put a fake here


def launchd(*args):
    """launchctl … in this user's GUI domain; True when it exits 0."""
    import subprocess
    return subprocess.run([LAUNCHCTL, *args], capture_output=True).returncode == 0


def agent_running(label):
    return launchd("print", f"gui/{os.getuid()}/{label}")


def start_agent(label):
    if not agent_running(label):
        launchd("bootstrap", f"gui/{os.getuid()}", os.path.expanduser(f"~/Library/LaunchAgents/{label}.plist"))
        log.info("started the launchd agent %s", label)


def stop_agent(label):
    if agent_running(label):
        launchd("bootout", f"gui/{os.getuid()}/{label}")
        log.info("stopped the launchd agent %s", label)


def wait_healthy(url, seconds=180):
    """Waits until a llama-server answers /health with 200 (it loads its model first)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            with urllib.request.urlopen(url + "/health", timeout=5) as r:
                if r.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(1)
    return False


def selected_model(config_path, models):
    """The model chosen in the menus ("model" in the config), if this server has it; None for Anthropic or none."""
    try:
        with open(config_path, encoding="utf-8") as f:
            name = (json.load(f) or {}).get("model")
    except (OSError, ValueError, AttributeError):
        return None
    return name if isinstance(name, str) and name in models.entries else None


class Models:
    """The models of the config's registry, by name; the first is the default. Only one is in memory at a time: its
    llama-server's launchd agent runs, the others' agents are stopped. `make(name, entry)` makes the model object
    (tests put a stub here)."""

    def __init__(self, entries, make=LlamaModel):
        self.entries, self.make, self.models = dict(entries), make, {}
        # Whether this server starts and stops the launchd agents (the test server does not).
        self.manage = True
        # One recording at a time: llama-server runs one request at a time (-np 1), and loading or switching a model
        # waits for the running recording. A second recording waits.
        self.recording = asyncio.Lock()

    def reconfigure(self, entries):
        """New model entries: the next recording, or the menu's choice, starts its model again."""
        self.entries, self.models = dict(entries), {}

    def name_for(self, name):
        """The model a client asks for by name; no name (or the URL path /voice_stream of earlier clients): the
        default."""
        name = (name or "").strip("/")
        if name in ("", "voice_stream"):
            return next(iter(self.entries))
        return name if name in self.entries else None

    async def get(self, name):
        """The model, the only one in memory."""
        await self.activate(name)
        if name not in self.models:
            self.models[name] = self.make(name, self.entries[name])
        return self.models[name]

    async def activate(self, name):
        """Makes `name` the only model in memory; None: no model at all (Anthropic is chosen)."""
        entry = self.entries.get(name) if name else None
        if self.manage:
            for n, e in self.entries.items():
                if e.get("launchd") and n != name:
                    await asyncio.to_thread(stop_agent, e["launchd"])
            if entry is not None and entry.get("launchd"):
                await asyncio.to_thread(start_agent, entry["launchd"])
        if entry is not None and not await asyncio.to_thread(wait_healthy, entry["llamaServer"].rstrip("/")):
            raise RuntimeError(f"llama-server of {name} at {entry['llamaServer']} does not answer")


# Per-recording options: a model's "options" in the registry, and options a client sends for an experiment, which
# override them. client name → (server name, type, check).
OPTIONS = {
    "temperature": ("temperature", float, lambda v: v >= 0),
    "topK": ("top_k", int, lambda v: v > 0),
    "topP": ("top_p", float, lambda v: 0 <= v <= 1),
    "seed": ("seed", int, lambda v: True),
    "maxOutputTokens": ("max_output_tokens", int, lambda v: v > 0),
    "pieceSeconds": ("piece_seconds", float, lambda v: 5 <= v <= MODEL_MAX_SECONDS),
    "cutSearchSeconds": ("cut_search_seconds", float, lambda v: 0 < v <= 10),
    "thresholdDb": ("threshold_db", float, lambda v: v < 0),
    "speechAboveNoiseDb": ("speech_above_noise_db", float, lambda v: v >= 0),
    "chatHistoryTokenBudget": ("chat_history_token_budget", int, lambda v: v >= 0),
    "chatTermsTokenBudget": ("chat_terms_token_budget", int, lambda v: v >= 0),
}


def parse_options(raw):
    """The options, checked: {server name: value}. Raises ValueError for an unknown or wrong one."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("options must be an object")
    out = {}
    for key, value in raw.items():
        if key not in OPTIONS:
            raise ValueError(f"unknown option {key}; known: {', '.join(OPTIONS)}")
        name, kind, ok = OPTIONS[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or (kind is int and value != int(value)):
            raise ValueError(f"option {key} must be a{'n integer' if kind is int else ' number'}")
        value = kind(value)
        if not ok(value):
            raise ValueError(f"option {key}: {value} is out of range")
        out[name] = value
    return out


STOP_REASONS = ("user", "silence", "max_duration", "error")


async def handle(ws, models, args):
    async def send(**m):
        await ws.send(json.dumps(m, ensure_ascii=False))

    try:
        start = json.loads(await ws.recv())
    except (ValueError, TypeError):
        start = {}
    if not isinstance(start, dict) or start.get("type") != "start" or start.get("sampleRate", 16000) != RATE \
            or start.get("encoding", "pcm_s16le") != "pcm_s16le":
        await send(type="error", message=f"expected a start message for 16 kHz pcm_s16le, got {start}")
        await ws.close()
        return
    asked = start.get("model") if isinstance(start.get("model"), str) else urllib.parse.urlparse(ws.request.path).path
    name = models.name_for(asked)
    if name is None:
        await send(type="error", message=f"no model {asked}; this server has: {', '.join(models.entries)}")
        await ws.close()
        return
    entry = models.entries[name]
    try:
        options = {**parse_options(entry.get("options")), **parse_options(start.get("options"))}
    except ValueError as e:
        await send(type="error", message=f"gemma_voice: {e}")
        await ws.close()
        return
    language = str(start.get("language") or "")
    own = start["prompt"] if isinstance(start.get("prompt"), str) else entry.get("prompt") or ""
    text_prompt = prompt(language, own.strip()[:MAX_PROMPT])
    client = str(start.get("client") or "")[:40]
    sessions = [s for s in start.get("sessions") or [] if isinstance(s, str)][:50]
    app = start.get("app") if isinstance(start.get("app"), str) else None
    log.info("recording: model %s, client %s, language=%s (%s), %s prompt: %r, options %s, sampler %s", name,
             client or "unknown", language, LANGUAGES.get(language.split("-")[0], "no name"),
             "own" if own.strip() else "default", text_prompt[:120], options or "none", sampler_of(options))
    recording = os.urandom(4).hex()
    rec = None
    if SAVE_RECORDINGS:
        try:
            rec = recordings.Recording(RECORDINGS)
        except OSError:
            log.exception("cannot start the recording folder")
    save_dir = rec.dir if rec else None
    meta = {"recording": recording, "language": language, "prompt": "own" if own.strip() else "default",
            "prompt_chars": len(text_prompt), "options": options}
    cut = {k: options.get(k, getattr(args, k)) for k in ("threshold_db", "speech_above_noise_db", "piece_seconds",
                                                         "cut_search_seconds")}
    levels, audio = Levels(cut["threshold_db"], cut["speech_above_noise_db"]), bytearray()
    pending = asyncio.Queue()
    texts, errors, chat_info = [], [], {}
    mic = asyncio.ensure_future(asyncio.to_thread(recordings.input_info)) if rec else None

    async def fail(message):
        errors.append(message)
        with contextlib.suppress(Exception):
            await send(type="error", message=f"gemma_voice: {message}")

    async def transcribe_pieces():
        # The text first, then the pieces in order, so the text arrives in the order it was spoken.
        if models.recording.locked():
            log.info("recording %s waits for the recording before it", recording)
        async with models.recording:
            await run_pieces()

    async def run_pieces():
        dictation, piece = None, 0
        try:
            try:
                dictation = (await models.get(name)).dictation(text_prompt, options, meta, save_dir)
                chat = None
                if options.get("chat_history_token_budget", CHAT_HISTORY_TOKEN_BUDGET) > 0:
                    chat = await asyncio.to_thread(context.chat_context, sessions, app)
                    if chat:
                        chat_info.update(session=chat["session"], file=chat["file"], messages=len(chat["messages"]),
                                         terms=len(chat["terms"]))
                    log.info("recording %s: chat context %s", recording,
                             f"from {chat['file']}, {len(chat['messages'])} replies" if chat else "none")
                await dictation.prepare(chat)
            except Exception as e:
                log.exception("preparing the recording failed")
                await fail(str(e))
            while (pcm := await pending.get()) is not None:
                piece += 1
                if dictation is None:
                    continue
                try:
                    text = await dictation.piece(pcm, piece)
                    if text:
                        texts.append(text)
                        await send(type="text", text=text)
                except Exception as e:  # one failed piece does not end the recording
                    log.exception("transcription failed")
                    await fail(str(e))
        finally:
            if dictation is not None:
                dictation.close()

    worker = asyncio.create_task(transcribe_pieces())
    last_speech, audio_bytes, stopped, stop_reason = 0.0, 0, None, None
    try:
        async for message in ws:
            if isinstance(message, bytes):
                audio_bytes += len(message)
                audio += message
                if rec:
                    rec.write(message)
                levels.feed(message)
                if levels.heard and time.monotonic() - last_speech >= SPEECH_EVERY_S:
                    last_speech = time.monotonic()
                    await send(type="speech")
            else:
                m = json.loads(message)
                if m.get("type") == "stop":
                    stopped = time.monotonic()
                    stop_reason = m.get("reason") if m.get("reason") in STOP_REASONS else "user"
                    break
        # The recording is whole: cut it now, into pieces as equal as the pauses allow.
        report = levels.report()
        for piece in split(bytes(audio), levels.rms, levels.threshold, cut["piece_seconds"], cut["cut_search_seconds"]):
            pending.put_nowait(piece)
        pending.put_nowait(None)
        audio_levels(recording, report, save_dir)
        # The client may give up before the last piece; then the running request
        # is closed and no more pieces go out.
        closed = asyncio.ensure_future(ws.wait_closed())
        await asyncio.wait({worker, closed}, return_when=asyncio.FIRST_COMPLETED)
        if not worker.done():
            log.warning("recording %s: the client closed the connection before the last piece", recording)
            errors.append("the client closed the connection before the last piece")
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
            return
        closed.cancel()
        await worker
        await send(type="done")
        metric("recording", model=name, client=client, recording=recording, language=language, prompt=meta["prompt"],
               options=options, audio_seconds=round(audio_bytes / 2 / RATE, 2), stop_reason=stop_reason,
               done_after_stop_seconds=round(time.monotonic() - stopped, 3) if stopped else None)
        await ws.close()
    finally:
        if not worker.done():
            worker.cancel()
        if rec:
            mic_info = None
            if mic is not None:
                with contextlib.suppress(Exception):
                    mic_info = await asyncio.wait_for(asyncio.shield(mic), 15)
            try:
                rec.finish({"model": name, "language": language, "client": client,
                            "stopReason": stop_reason or "connection closed", "error": "; ".join(errors) or None,
                            "chat": chat_info or None, "pieces": texts, "text": " ".join(texts),
                            "session": {"id": chat_info["session"], "file": chat_info["file"]} if chat_info else None,
                            "input": mic_info})
            except OSError:
                log.exception("cannot finish the recording folder %s", rec.dir)


# The config, ~/.local-voice/config.json ($LOCAL_VOICE_CONFIG), version 2, shared with the menus:
#   {"version": 2, "model": "<name>" | "anthropic",
#    "models": {"<name>": {"llamaServer": "http://127.0.0.1:8092", "launchd": "<label>", "prompt": "…", "options": {…}}},
#    "silenceStopSeconds": 60, "saveRecordings": true,
#    "server": {"host": …, "port": …, "pieceSeconds": …, …}}
# models: the registry; each a llama.cpp llama-server, started and stopped through its launchd agent. Only the model
# chosen in the menus ("model") is in memory; Anthropic chosen: none. The server's settings: built-in defaults, then
# the file, then the command line, which wins (the test server keeps its own port, log and metrics). The server
# watches the file:
#   "recording" settings take effect at the next recording;
#   "model" settings (models) take effect after the running recording;
#   "process" settings (host, port) end the process after the running recording; launchd starts it again.
# config key → (command-line name, kind, check, default, level, where in the file); command-line name None: only in
# the file.
MODEL_DEFAULT = {"gemma-e4b": {"llamaServer": "http://127.0.0.1:8092", "launchd": "local-voice.llama-server"}}
CONFIG_VERSION = 2


def good_model(m):
    """A registry entry: llamaServer, and optionally launchd, prompt and options that parse_options accepts."""
    if not isinstance(m, dict) or not str(m.get("llamaServer", "")).startswith("http") \
            or not isinstance(m.get("launchd", ""), str) or not isinstance(m.get("prompt", ""), str) \
            or len(m.get("prompt", "")) > MAX_PROMPT:
        return False
    try:
        parse_options(m.get("options"))
        return True
    except ValueError:
        return False


SETTINGS = {
    "host": ("host", str, lambda v: bool(v), "127.0.0.1", "process", "server"),
    "port": ("port", int, lambda v: 0 < v < 65536, 8090, "process", "server"),
    "models": (None, dict, lambda v: bool(v) and all(good_model(m) for m in v.values()), MODEL_DEFAULT, "model", None),
    "saveRecordings": (None, bool, lambda v: True, True, "recording", None),
    "thresholdDb": ("threshold_db", float, lambda v: v < 0, -45.0, "recording", "server"),
    "speechAboveNoiseDb": ("speech_above_noise_db", float, lambda v: v >= 0, 12.0, "recording", "server"),
    "pieceSeconds": ("piece_seconds", float, lambda v: 5 <= v <= MODEL_MAX_SECONDS, 20.0, "recording", "server"),
    "cutSearchSeconds": ("cut_search_seconds", float, lambda v: 0 < v <= 10, 3.0, "recording", "server"),
    "outputTokensPerSecond": ("output_tokens_per_second", float, lambda v: v > 0, 10.0, "recording", "server"),
    "outputTokensBase": ("output_tokens_base", int, lambda v: v >= 0, 32, "recording", "server"),
    "recordings": ("recordings", str, lambda v: bool(v), "~/speech/recordings", "recording", "server"),
    "metrics": ("metrics", str, lambda v: bool(v), "~/Library/Logs/local-voice/gemma-voice-metrics.jsonl",
                "recording", "server"),
}
CONFIG_CHECK_S = 2


def config_file():
    return os.environ.get("LOCAL_VOICE_CONFIG") or os.path.expanduser("~/.local-voice/config.json")


def file_settings(path):
    """The server's settings in the config file, checked: {config key: value}. A wrong key or value is logged and left
    out; None if the file cannot be read or is of another version."""
    try:
        with open(path, encoding="utf-8") as f:
            c = json.load(f) or {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.error("config %s: cannot read it (%s); the server keeps its settings", path, e)
        return None
    if not isinstance(c, dict) or c.get("version") != CONFIG_VERSION:
        log.error("config %s: version %s, the server reads version %d; install.sh migrates the file", path,
                  c.get("version") if isinstance(c, dict) else None, CONFIG_VERSION)
        return None
    server = c.get("server") if isinstance(c.get("server"), dict) else {}
    known = {k for k, v in SETTINGS.items() if v[5] == "server"}
    for key in server:
        if key not in known:
            log.error("config %s: server.%s is not a setting; known: %s", path, key, ", ".join(sorted(known)))
    out = {}
    for key, (_, kind, ok, _, _, where) in SETTINGS.items():
        source = server if where == "server" else c
        if key not in source:
            continue
        value = source[key]
        try:
            if kind is dict:
                good = isinstance(value, dict) and ok(value)
            elif kind is bool:
                good = isinstance(value, bool)
            else:
                good = not isinstance(value, bool) and ok(kind(value)) and (kind is not int or value == int(value))
                value = kind(value) if good else value
        except (TypeError, ValueError):
            good = False
        if not good:
            log.error("config %s: %s%s = %r is not valid; it is left out", path, f"{where}." if where else "", key,
                      value)
            continue
        out[key] = value
    return out


def resolve(cli, from_file):
    """The settings in force: the command line, then the file, then the defaults. {config key: value}."""
    out = {}
    for key, (name, _, _, default, _, _) in SETTINGS.items():
        given = getattr(cli, name, None) if name else None
        out[key] = given if given is not None else from_file.get(key, default)
    return out


def apply_recording_settings(st, now):
    """Puts the "recording" settings where the code reads them. `st`: the namespace that handle() reads."""
    global METRICS, OUTPUT_TOKENS_PER_SECOND, OUTPUT_TOKENS_BASE, RECORDINGS, SAVE_RECORDINGS
    st.threshold_db, st.speech_above_noise_db = now["thresholdDb"], now["speechAboveNoiseDb"]
    st.piece_seconds, st.cut_search_seconds = now["pieceSeconds"], now["cutSearchSeconds"]
    OUTPUT_TOKENS_PER_SECOND, OUTPUT_TOKENS_BASE = now["outputTokensPerSecond"], now["outputTokensBase"]
    RECORDINGS, METRICS = os.path.expanduser(now["recordings"]), os.path.expanduser(now["metrics"])
    SAVE_RECORDINGS = now["saveRecordings"]


async def follow_selection(models, path, chosen):
    """Keeps in memory only the model chosen in the menus (see selected_model), after the running recording."""
    now = selected_model(path, models)
    if now == chosen[0]:
        return
    async with models.recording:
        log.info("the menu's model is %s: only it stays in memory", now or "not on this server")
        try:
            await models.activate(now)
            chosen[0] = now
        except Exception:
            log.exception("cannot make %s the model in memory", now)


async def watch_config(cli, models, st, current, path, stop, follow=True):
    """Applies changes of the config file; see SETTINGS. With `follow`, also keeps in memory only the model chosen in
    the menus."""
    seen, chosen = None, [object()]
    if follow:
        await follow_selection(models, path, chosen)
    while True:
        await asyncio.sleep(CONFIG_CHECK_S)
        try:
            mtime = os.stat(path).st_mtime_ns
        except OSError:
            mtime = None
        if mtime == seen:
            continue
        first, seen = seen is None, mtime
        if first:
            continue
        from_file = file_settings(path)
        if from_file is not None:
            now = resolve(cli, from_file)
            changed = {k for k in SETTINGS if now[k] != current[k]}
            if changed:
                levels = {SETTINGS[k][4] for k in changed}
                log.info("config %s changed: %s", path, ", ".join(f"{k} {current[k]!r} -> {now[k]!r}"
                                                                 for k in sorted(changed)))
                async with models.recording:  # after the running recording
                    if "process" in levels:
                        log.info("host or port changed: the server ends; launchd starts it again with the new "
                                 "settings")
                        stop.set_result(None)
                        return
                    apply_recording_settings(st, now)
                    if "model" in levels:
                        models.reconfigure(now["models"])
                        chosen[0] = object()  # start the chosen model again, with the new entries
                        log.info("models: %s", ", ".join(now["models"]))
                    current.clear()
                    current.update(now)
        if follow:
            await follow_selection(models, path, chosen)


async def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                epilog="Each setting can also be set in the section 'server' of the config file; the "
                                       "command line wins. The models are set only in the file. The server watches "
                                       "the file.")
    p.add_argument("--config", default=None, help=f"the config file (default {config_file()})")
    p.add_argument("--ignore-selection", action="store_true",
                   help="do not follow the model chosen in the menus, and never start or stop llama-server agents "
                        "(for a test server)")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--recordings", help="where the recordings are saved (default ~/speech/recordings)")
    p.add_argument("--metrics", help="the metrics file, JSON lines")
    p.add_argument("--output-tokens-per-second", type=float,
                   help="the limit of a piece's text: tokens per second of its audio (default 10)")
    p.add_argument("--output-tokens-base", type=int,
                   help="plus this many tokens (default 32); maxOutputTokens in the options overrides both")
    p.add_argument("--threshold-db", type=float, help="the lowest loudness of speech, dBFS (default -45, not tuned)")
    p.add_argument("--speech-above-noise-db", type=float,
                   help="speech is at least this much louder than the recording's noise floor (default 12, not tuned)")
    p.add_argument("--piece-seconds", type=float,
                   help="the wanted length of a piece; a recording is cut, after the stop, into pieces as close to it "
                        f"as possible and equal, none longer than {MODEL_MAX_SECONDS} s (default 20)")
    p.add_argument("--cut-search-seconds", type=float,
                   help="how far from its equal point a cut may move to the quietest moment (default 3)")
    cli = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    path = cli.config or config_file()
    current = resolve(cli, file_settings(path) or {})
    if not 5 <= current["pieceSeconds"] <= MODEL_MAX_SECONDS:
        p.error(f"pieceSeconds: from 5 to {MODEL_MAX_SECONDS}")
    st = argparse.Namespace()
    apply_recording_settings(st, current)
    models = Models(current["models"])
    models.manage = not cli.ignore_selection
    if cli.ignore_selection:
        await models.get(next(iter(current["models"])))  # the default model answers before the first recording
    log.info("settings: %s", json.dumps(current, ensure_ascii=False))
    stop = asyncio.get_running_loop().create_future()
    watcher = asyncio.create_task(watch_config(cli, models, st, current, path, stop, follow=not cli.ignore_selection))
    async with serve(lambda ws: handle(ws, models, st), current["host"], current["port"], max_size=None):
        log.info("listening on ws://%s:%d, models: %s (default %s), config %s", current["host"], current["port"],
                 ", ".join(current["models"]), next(iter(current["models"])), path)
        await stop
    watcher.cancel()


if __name__ == "__main__":
    asyncio.run(main())
