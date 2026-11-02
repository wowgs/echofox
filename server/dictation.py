"""One recording on one model: the text before the audio (prompt.py), and each piece as a request of its own. The
model is any object with the interface of llama_client.Model."""
import asyncio
import logging
import time

import blocking
import fillers
import metrics
import prompt
import recordings
import resolve
from audio import seconds

log = logging.getLogger("echofox-server")
CONTEXT_TOO_BIG = "exceed_context_size_error"
TAIL_MARGIN = 32  # the tail's tags, its last word over its budget, and the estimate's error on it (prompt.said_before)  # llama-server's error type for a request over a slot's context


class Dictation:
    """One recording on one model. Each piece is a request of its own: the text (chat history, then the prompt),
    then the piece's audio. The model never sees its answers to earlier pieces: in one conversation for the whole
    recording, a piece often began by repeating the earlier piece's text (2026-10-14, Gemma 4 E4B). So the pieces do
    not depend on each other, and a llama-server with several slots runs them at once (the catalog gives one). While the speaker talks, warm()
    puts the text into a slot's cache, so that after the stop a piece processes only its audio.
    `server`: the server's recording settings; `files`: where its files go (recordings.Folder), else nothing is
    saved."""

    def __init__(self, model, text_prompt, options, server, meta, files=None, client_options=None,
                 token_weights=None, text_room=None):
        self.m, self.prompt, self.options, self.server, self.meta = model, text_prompt, options, server, meta
        self.weights = token_weights or {}  # the model's tokens per character (budget.count)
        self.room = text_room  # the tokens a request's text may take beside the longest audio (catalog.text_room)
        self.client = client_options or {}  # the start message's own: they win over the adapter's settings too
        self.files = files or recordings.Unsaved()
        self.text, self.block, self.chat_tokens = text_prompt, None, 0  # the text before the audio; its context block
        self.sounds = fillers.words(meta.get("language", ""), getattr(server, "languages", None))
        model.begin()

    def _build(self, context):
        """The text before the audio: the context within the token budgets of its adapter's options
        (resolve.adapter), then the prompt."""
        if not context:
            return
        options = resolve.adapter(context.get("adapter"), self.options, self.server, self.client)
        fits = None
        if self.room is not None:
            # the answer's limit, and the tail of the pieces before (previousTextTokens, a word over it and its tags)
            room = (self.room - resolve.value("max_tokens_per_piece", self.options, self.server)
                    - resolve.value("previous_text_tokens", self.options, self.server) - TAIL_MARGIN)
            fits = lambda block: len(self.m.tokenize(block + "\n\n" + self.prompt)) <= room  # noqa: E731  the model's count
        block, holds = prompt.context(context, options, self.server, self.meta.get("language"), self.weights, fits)
        if block is None:
            return
        self.block, self.text = block, block + "\n\n" + self.prompt
        self.chat_tokens = len(self.m.tokenize(self.text)) - len(self.m.tokenize(self.prompt))  # the model's count
        self.meta = {**self.meta, "chat_tokens": self.chat_tokens, **holds}

    async def prepare(self, context=None):
        """Builds the text before the audio."""
        t = time.monotonic()
        await blocking.run(self._build, context)
        took = time.monotonic() - t
        log.info("%s: text before the audio ready in %.2f s, %d tokens of chat history and terms", self.m.name,
                 took, self.chat_tokens)
        metrics.metric("prepare", model=self.m.name, **self.meta, seconds=round(took, 3))
        self.files.text_before_audio(self.text)

    def slots(self):
        """How many pieces the model runs at once."""
        return self.m.slots()

    async def warm(self, slot=None):
        """The text before the audio into the cache of llama-server's slot `slot`, before any audio."""
        t = time.monotonic()
        timings = await blocking.run(self.m.warm, self.text, self.options, slot, cancel=self.m.cancel)
        took = time.monotonic() - t
        log.info("%s: text before the audio warmed in slot %s in %.2f s, %s prefill (%s cached)", self.m.name, slot,
                 took, timings.get("prefill_tokens"), timings.get("cached_tokens"))
        metrics.metric("warm", model=self.m.name, **self.meta, slot=slot, wall_seconds=round(took, 3), **timings)

    async def piece(self, pcm, piece, speech, slot=None, said=""):
        """One piece with `speech` seconds of speech in it (the VAD's) → its text. A piece with too little speech does
        not go to the model; the model writes at most maxTokensPerPiece tokens, so that one that does not end its text
        stops. `said`: the end of the pieces' text before it (prompt.said_before), which goes after the text before
        the audio."""
        t, audio = time.monotonic(), seconds(pcm)
        meta = {**self.meta, "piece": piece, "slot": slot}
        if speech < resolve.value("min_speech_seconds", self.options, self.server):
            log.info("%s: piece %d, %.1f s of audio with %.2f s of speech: not sent to the model", self.m.name, piece,
                     audio, speech)
            metrics.metric("piece_skipped", model=self.m.name, **meta, audio_seconds=round(audio, 2),
                           speech_seconds=round(speech, 2))
            self.files.piece(pcm, {"piece": piece, "audio_seconds": round(audio, 2), "speech_seconds": round(speech, 2),
                                   "text": "", "skipped": "no speech"})
            return ""
        limit = resolve.value("max_tokens_per_piece", self.options, self.server)
        try:
            try:
                text, timings = await blocking.run(self.m.complete, prompt.with_said(self.block, self.prompt, said), pcm,
                                                   limit, self.options, slot, cancel=self.m.cancel)
            except RuntimeError as e:
                if CONTEXT_TOO_BIG not in str(e) or self.text == self.prompt:
                    raise
                # A text over the model's room (catalog.text_room is computed, not asked of llama-server): the
                # dictation goes on without its context rather than fail
                log.warning("%s: piece %d did not fit the model with its context: again without it", self.m.name, piece)
                self.block, self.text = None, self.prompt
                self.meta = {**self.meta, "context_dropped": "too big for the model"}
                meta = {**meta, "context_dropped": "too big for the model"}
                text, timings = await blocking.run(self.m.complete, prompt.with_said(self.block, self.prompt, said), pcm,
                                                   limit, self.options, slot, cancel=self.m.cancel)
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
        self.files.piece(pcm, {"piece": piece, "audio_seconds": round(audio, 2), "speech_seconds": round(speech, 2),
                               "text": text, **({"raw": raw} if raw != text else {}), **({"said": said} if said else {}),
                               "max_tokens_hit": hit,
                               **timings})
        return text
