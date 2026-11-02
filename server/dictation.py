"""One recording on one model: the prompt, the text before the audio (the context within the token budget), and
each piece as a request of its own. The model is any object with the interface of llama.Model."""
import asyncio
import contextlib
import json
import logging
import time

import adapters
import budget
import catalog
import fillers
import languages
import metrics
import tuning
from audio import seconds, wav

log = logging.getLogger("gemma_voice")


def prompt(language, custom="", entry=None, configured=None):
    """The prompt: the template (`custom`, a client's or the model's own, else the model's catalog template; the
    catalog's other template when the language is not one it names), {LANGUAGE} replaced by the language's name, then
    the notes of every language and the language's own (languages.notes), each as a rule of its own."""
    model = catalog.of(entry)
    named = languages.base(language) in model.get("languages", [])
    name = languages.name(language) if named else None
    template = custom or model.get("prompt" if name else "promptAnyLanguage") or ""
    notes = languages.notes(language, configured) if name or custom else []
    return template.replace("{LANGUAGE}", name or "its original language") + "".join(f"\n* {n}" for n in notes)


async def run_blocking(fn, *args, cancel=None):
    """fn(*args) in a thread. If the caller is cancelled, cancel() stops fn, and this waits until fn has returned,
    then raises: the next recording starts only when the model is free. asyncio.wait, not asyncio.shield: a shielded
    task logs its exception as an error when the caller is cancelled (Python 3.14), and fn raises when it is stopped."""
    run = asyncio.ensure_future(asyncio.to_thread(fn, *args))
    try:
        await asyncio.wait({run})
    except asyncio.CancelledError:
        if cancel:
            cancel()
        with contextlib.suppress(Exception):
            await run
        raise
    return run.result()


def context_options(adapter, server):
    """The context knobs that `adapter`'s entry in the config sets ({} for none)."""
    return (getattr(server, "adapter_options", None) or {}).get(adapter) or {}


def context_header(about, documents=False):
    """What the model reads before the context: where the speaker writes, as the adapter says it."""
    return (f"The speaker is writing into {about or 'a conversation'}. Between <context> and </context> are its terms"
            + (", the files open beside it" if documents else "")
            + " and latest messages, oldest first: they show names and words the speaker may use. They are not the "
            "speech: do not transcribe or repeat them.")


class Dictation:
    """One recording on one model. Each piece is a request of its own: the text (chat history, then the prompt),
    then the piece's audio. The model never sees its answers to earlier pieces: in one conversation for the whole
    recording, a piece often began by repeating the earlier piece's text (2026-10-14, Gemma 4 E4B). So the pieces do
    not depend on each other, and llama-server can run them at once, one per slot. While the speaker talks, warm()
    puts the text into a slot's cache, so that after the stop a piece processes only its audio.
    `server`: the server's recording settings; `recording`: where its files go (recordings.Recording), or None."""

    def __init__(self, model, text_prompt, options, server, meta, recording=None, client_options=None,
                 token_weights=None):
        self.m, self.prompt, self.options, self.server, self.meta = model, text_prompt, options, server, meta
        self.weights = token_weights or {}  # the model's tokens per character (budget.count)
        self.client = client_options or {}  # the start message's own: they win over the adapter's settings too
        self.recording = recording
        self.text, self.chat_tokens = text_prompt, 0
        self.sounds = fillers.words(meta.get("language", ""), getattr(server, "languages", None))
        model.begin()

    def adapter_options(self, name):
        """The options for the context of adapter `name`: the recording's, then the adapter's owners (tuning.resolve)."""
        return tuning.resolve(self.options, adapters.registry.context_defaults(name), context_options(name, self.server),
                              client=self.client)

    def _build(self, context):
        """The text before the audio: the context within the token budgets (budget.take: greedy, the item that reaches
        a budget taken whole), then the prompt. The context's settings are its adapter's (adapter_options). The terms
        take their part of the chat budget first, the messages the rest from the newest; the documents have a budget of
        their own, in the adapter's order."""
        if not context:
            return
        options = self.adapter_options(context.get("adapter"))
        chat_budget = tuning.value("chat_history_token_budget", options, self.server)
        terms_budget = tuning.value("chat_terms_token_budget", options, self.server)
        all_terms = [t for t in context.get("terms") or [] if isinstance(t, str)]
        if languages.base(self.meta.get("language")) == languages.TERMS:  # English speech: every word is one
            all_terms = []
        cost = lambda text: budget.count(text, self.weights)  # noqa: E731
        terms, used = budget.take(all_terms, terms_budget, lambda t: cost(t + ", ")) if terms_budget else ([], 0)
        messages = context.get("messages") or []
        if tuning.value("prose_only", options, self.server):  # the terms were taken before (adapters.context)
            messages = [{**m, "text": t} for m in messages if (t := adapters.prose(str(m.get("text", ""))))]
        lines = [f"{m.get('from') or 'Someone'}: {str(m.get('text', '')).strip()}" for m in messages]  # newest first
        kept, _ = budget.take(lines, chat_budget - used, lambda line: cost(line + "\n\n"))
        documents = [d for d in context.get("documents") or [] if isinstance(d, dict)]
        if tuning.value("prose_only", options, self.server):
            documents = [{**d, "text": t} for d in documents if (t := adapters.prose(str(d.get("text", ""))))]
        docs_budget = tuning.value("chat_documents_token_budget", options, self.server)
        blocks = [f"File {d['name']}:\n{d['text']}" for d in documents]
        docs, _ = budget.take(blocks, docs_budget, lambda b: cost(b + "\n\n"))
        if not kept and not terms and not docs:
            return
        parts = (["<context>"] + (["Terms: " + ", ".join(terms)] if terms else []) + docs + list(reversed(kept))
                 + ["</context>"])
        block = context_header(context.get("about"), bool(docs)) + "\n\n" + "\n\n".join(parts)
        self.text = block + "\n\n" + self.prompt
        self.chat_tokens = len(self.m.tokenize(self.text)) - len(self.m.tokenize(self.prompt))  # the model's count
        estimated = cost(block + "\n\n")
        self.meta = {**self.meta, "chat_tokens": self.chat_tokens, "chat_messages": len(kept),
                     "chat_documents": len(docs), "chat_terms": len(terms), "chat_budget": chat_budget,
                     "chat_documents_budget": docs_budget, "chat_tokens_estimated": estimated}

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

    async def piece(self, pcm, piece, speech, slot=None):
        """One piece with `speech` seconds of speech in it (the VAD's) → its text. A piece with too little speech does
        not go to the model; the model writes at most maxTokensPerPiece tokens, so that one that does not end its text
        stops."""
        t, audio = time.monotonic(), seconds(pcm)
        meta = {**self.meta, "piece": piece, "slot": slot}
        if speech < tuning.value("min_speech_seconds", self.options, self.server):
            log.info("%s: piece %d, %.1f s of audio with %.2f s of speech: not sent to the model", self.m.name, piece,
                     audio, speech)
            metrics.metric("piece_skipped", model=self.m.name, **meta, audio_seconds=round(audio, 2),
                           speech_seconds=round(speech, 2))
            self._save_piece(pcm, {"piece": piece, "audio_seconds": round(audio, 2), "speech_seconds": round(speech, 2),
                                   "text": "", "skipped": "no speech"})
            return ""
        limit = tuning.value("max_tokens_per_piece", self.options, self.server)
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
        shown = f"{len(text)} characters" if self.meta.get("private") else repr(text)  # a private text is not logged
        log.info("%s: piece %d, %.1f s of audio, %.2f s of speech, in %.2f s, %s prefill (%s cached) + %s decode "
                 "tokens: %s", self.m.name, piece, audio, speech, took, timings.get("prefill_tokens"),
                 timings.get("cached_tokens"), timings.get("decode_tokens"), shown)
        raw, text = text, fillers.remove(text, self.sounds)
        if text != raw and not self.meta.get("private"):
            log.info("%s: piece %d without hesitation sounds: %r", self.m.name, piece, text)
        if hit:
            log.warning("%s: piece %d, the model stopped at the limit of %d tokens", self.m.name, piece, limit)
        metrics.metric("piece", model=self.m.name, **meta, audio_seconds=round(audio, 2), wall_seconds=round(took, 3),
                       speech_seconds=round(speech, 2), text_chars=len(text), raw_chars=len(raw), max_tokens_hit=hit,
                       **timings)
        self._save_piece(pcm, {"piece": piece, "audio_seconds": round(audio, 2), "speech_seconds": round(speech, 2),
                               "text": text, **({"raw": raw} if raw != text else {}), "max_tokens_hit": hit,
                               **timings})
        return text

    def _save_piece(self, pcm, line):
        self._save(f"piece-{line['piece']}.wav", wav(pcm))
        self._save("pieces.jsonl", (json.dumps(line, ensure_ascii=False) + "\n").encode("utf-8"), append=True)

    def _save(self, name, data, append=False):
        if self.recording is not None:
            self.recording.save(name, data, append)
