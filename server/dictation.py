"""One recording on one model: the prompt, the text before the audio (chat context within the token budget), and
each piece as a request of its own. The model is duck-typed: name, tokenize(), detokenize(), complete(), and
optionally cancel() and footprint_mb() (llama.LlamaModel)."""
import asyncio
import contextlib
import json
import logging
import math
import os
import time

import metrics
from audio import MODEL_MAX_SECONDS, RATE, wav

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


def prompt(language, custom=""):
    """The client's prompt, if it sent one, with {LANGUAGE} replaced by the language's name; otherwise Google's."""
    name = LANGUAGES.get(language.split("-")[0])
    if custom:
        return custom.replace("{LANGUAGE}", name or "its original language")
    if name:
        return f"Transcribe the following speech segment in {name} into {name} text.\n\n{FORMAT}"
    return f"Transcribe the following speech segment in its original language.\n{FORMAT}"


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


def sampler_of(options):
    """The sampler of a recording: SAMPLER, with temperature, top_k, top_p and seed from the options."""
    return {**SAMPLER, **{k: options[k] for k in ("temperature", "top_k", "top_p", "seed") if k in options}}


def output_limit(audio_seconds, options, per_second=OUTPUT_TOKENS_PER_SECOND, base=OUTPUT_TOKENS_BASE):
    if "max_output_tokens" in options:
        return options["max_output_tokens"]
    return math.ceil(per_second * audio_seconds) + base


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


CONTEXT_HEADER = ("The speaker is talking with an AI assistant about software. The assistant's earlier replies "
                  "follow, oldest first. They show names and terms the speaker may use. Do not transcribe them.")


ROLES = {"user": "Speaker", "assistant": "Assistant"}


class Dictation:
    """One recording on one model. Each piece is a request of its own: the text (chat history, then the prompt),
    then the piece's audio. The model never sees its answers to earlier pieces: in one conversation for the whole
    recording, a piece often began by repeating the earlier piece's text (2026-10-14, Gemma 4 E4B)."""

    def __init__(self, model, text_prompt, options, meta, save_dir=None, limits=(OUTPUT_TOKENS_PER_SECOND, OUTPUT_TOKENS_BASE)):
        self.m, self.prompt, self.options, self.meta, self.save_dir = model, text_prompt, options, meta, save_dir
        self.limits = limits  # a piece's text: tokens per second of its audio, plus a base
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
        metrics.metric("prepare", model=self.m.name, **self.meta, seconds=round(seconds, 3))
        self._save("text-before-audio.txt", self.text.encode("utf-8"))

    async def piece(self, pcm, piece):
        t, audio = time.monotonic(), len(pcm) / 2 / RATE
        limit = output_limit(audio, self.options, *self.limits)
        meta = {**self.meta, "piece": piece}
        try:
            text, timings = await run_blocking(self.m.complete, self.text, pcm, limit, self.options,
                                               cancel=getattr(self.m, "cancel", None))
        except asyncio.CancelledError:
            log.warning("%s: the transcription of %.1f s of audio was cancelled after %.2f s", self.m.name, audio,
                        time.monotonic() - t)
            metrics.metric("cancelled", model=self.m.name, **meta, audio_seconds=round(audio, 2),
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
        metrics.metric("piece", model=self.m.name, **meta, audio_seconds=round(audio, 2), wall_seconds=round(seconds, 3),
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
