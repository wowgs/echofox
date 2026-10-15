"""One recording on one model: the prompt, the text before the audio (the context within the token budget), and
each piece as a request of its own. The model is any object with the interface of llama.Model."""
import asyncio
import contextlib
import json
import logging
import math
import time

import metrics
import tuning
from audio import seconds, wav

MAX_PROMPT = 4000  # characters of a prompt, the model's or a client's
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
NEWEST_TAIL_MIN_TOKENS = 32  # the newest message alone too long for the budget: its end, if this much fits
log = logging.getLogger("gemma_voice")


def prompt(language, custom=""):
    """The client's prompt, if it sent one, with {LANGUAGE} replaced by the language's name; otherwise Google's."""
    name = LANGUAGES.get(language.split("-")[0])
    if custom:
        return custom.replace("{LANGUAGE}", name or "its original language")
    if name:
        return f"Transcribe the following speech segment in {name} into {name} text.\n\n{FORMAT}"
    return f"Transcribe the following speech segment in its original language.\n{FORMAT}"


def output_limit(audio_seconds, options, server):
    """The limit of a piece's text, in tokens."""
    fixed = tuning.value("max_output_tokens", options, server)
    if fixed is not None:
        return fixed
    return math.ceil(tuning.value("output_tokens_per_second", options, server) * audio_seconds) \
        + tuning.value("output_tokens_base", options, server)


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


def context_header(about):
    """What the model reads before the context: where the speaker writes, as the adapter says it."""
    return (f"The speaker is writing into {about or 'a conversation'}. Its earlier messages follow, oldest first. "
            "They show names and terms the speaker may use. Do not transcribe them.")


class Dictation:
    """One recording on one model. Each piece is a request of its own: the text (chat history, then the prompt),
    then the piece's audio. The model never sees its answers to earlier pieces: in one conversation for the whole
    recording, a piece often began by repeating the earlier piece's text (2026-10-14, Gemma 4 E4B). So the pieces do
    not depend on each other, and llama-server can run them at once, one per slot. While the speaker talks, warm()
    puts the text into a slot's cache, so that after the stop a piece processes only its audio.
    `server`: the server's recording settings; `recording`: where its files go (recordings.Recording), or None."""

    def __init__(self, model, text_prompt, options, server, meta, recording=None):
        self.m, self.prompt, self.options, self.server, self.meta = model, text_prompt, options, server, meta
        self.recording = recording
        self.text, self.chat_tokens = text_prompt, 0
        model.begin()

    def _fit(self, items, budget, render):
        """The longest start of `items` whose rendering fits `budget` tokens: (count, tokens), by bisection, so it
        takes a few tokenize calls, not one per item."""
        lo, hi, used = 0, len(items), 0
        while lo < hi:
            mid = (lo + hi + 1) // 2
            n = len(self.m.tokenize(render(items[:mid])))
            if n <= budget:
                lo, used = mid, n
            else:
                hi = mid - 1
        return lo, used

    def _build(self, context):
        """The text before the audio: the context within the token budget, then the prompt."""
        budget = tuning.value("chat_history_token_budget", self.options, self.server)
        if not context or budget <= 0:
            return
        terms_budget = tuning.value("chat_terms_token_budget", self.options, self.server)
        terms_budget = budget // 10 if terms_budget is None else terms_budget
        all_terms = [t for t in context.get("terms") or [] if isinstance(t, str)]
        n_terms, used = self._fit(all_terms, terms_budget, lambda ts: "Terms: " + ", ".join(ts))
        terms = all_terms[:n_terms]
        lines = [f"{m.get('from') or 'Someone'}: {str(m.get('text', '')).strip()}"
                 for m in context.get("messages") or []]  # newest first
        left = budget - used
        n_lines, _ = self._fit(lines, left, lambda ls: "\n\n".join(ls))
        kept = lines[:n_lines]
        if not kept and lines and left > NEWEST_TAIL_MIN_TOKENS:  # the newest message alone is too long: its end
            ids = self.m.tokenize(lines[0])
            kept = ["…" + self.m.detokenize(ids[-(left - 2):])]
        if not kept and not terms:
            return
        parts = [context_header(context.get("about"))]
        if terms:
            parts.append("Terms: " + ", ".join(terms))
        parts += reversed(kept)
        self.text = "\n\n".join(parts) + "\n\n---\n\n" + self.prompt
        self.chat_tokens = len(self.m.tokenize(self.text)) - len(self.m.tokenize(self.prompt))
        self.meta = {**self.meta, "chat_tokens": self.chat_tokens, "chat_messages": len(kept),
                     "chat_terms": len(terms)}

    async def prepare(self, context=None):
        """Builds the text before the audio."""
        t = time.monotonic()
        await run_blocking(self._build, context)
        took = time.monotonic() - t
        log.info("%s: text before the audio ready in %.2f s, %d tokens of chat history and terms", self.m.name,
                 took, self.chat_tokens)
        metrics.metric("prepare", model=self.m.name, **self.meta, seconds=round(took, 3))
        self._save("text-before-audio.txt", self.text.encode("utf-8"))

    def slots(self):
        """How many pieces the model runs at once."""
        return self.m.slots()

    async def warm(self, slot=None):
        """The text before the audio into the cache of llama-server's slot `slot`, before any audio."""
        t = time.monotonic()
        timings = await run_blocking(self.m.warm, self.text, self.options, slot, cancel=self.m.cancel)
        took = time.monotonic() - t
        log.info("%s: text before the audio warmed in slot %s in %.2f s, %s prefill (%s cached)", self.m.name, slot,
                 took, timings.get("prefill_tokens"), timings.get("cached_tokens"))
        metrics.metric("warm", model=self.m.name, **self.meta, slot=slot, wall_seconds=round(took, 3), **timings)

    async def piece(self, pcm, piece, slot=None):
        t, audio = time.monotonic(), seconds(pcm)
        limit = output_limit(audio, self.options, self.server)
        meta = {**self.meta, "piece": piece, "slot": slot}
        try:
            text, timings = await run_blocking(self.m.complete, self.text, pcm, limit, self.options, slot,
                                               cancel=self.m.cancel)
        except asyncio.CancelledError:
            log.warning("%s: the transcription of %.1f s of audio was cancelled after %.2f s", self.m.name, audio,
                        time.monotonic() - t)
            metrics.metric("cancelled", model=self.m.name, **meta, audio_seconds=round(audio, 2),
                           wall_seconds=round(time.monotonic() - t, 3))
            raise
        took = time.monotonic() - t
        timings["llama_footprint_mb"] = await asyncio.to_thread(self.m.footprint_mb)
        hit = timings.get("decode_tokens") is not None and timings["decode_tokens"] >= limit
        log.info("%s: piece %d, %.1f s of audio in %.2f s, %s prefill (%s cached) + %s decode tokens: %r", self.m.name,
                 piece, audio, took, timings.get("prefill_tokens"), timings.get("cached_tokens"),
                 timings.get("decode_tokens"), text)
        if hit:
            log.warning("%s: the text reached the limit of %d tokens for %.1f s of audio and was cut", self.m.name,
                        limit, audio)
        metrics.metric("piece", model=self.m.name, **meta, audio_seconds=round(audio, 2), wall_seconds=round(took, 3),
                       text_chars=len(text), output_limit=limit, output_limit_hit=hit, **timings)
        self._save(f"piece-{piece}.wav", wav(pcm))
        self._save("pieces.jsonl", (json.dumps({"piece": piece, "audio_seconds": round(audio, 2), "text": text,
                                                "output_limit": limit, "output_limit_hit": hit, **timings},
                                               ensure_ascii=False) + "\n").encode("utf-8"), append=True)
        return text

    def _save(self, name, data, append=False):
        if self.recording is not None:
            self.recording.save(name, data, append)
