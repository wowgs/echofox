"""One recording on one connection (docs/reference/1-server.md, "From a recording to text"): the start message
parsed (Start), then the Session: the read request for the surfaces that the start's identity is on, at once; the
audio arrives and is saved, and the client's content of those surfaces between its messages; while the speaker talks, a piece is cut and goes to
the model each time enough audio is heard (audio.live_cut); at the stop, the rest is cut into pieces; one model request
per piece, each as soon as it is cut, on llama-server's slots, after the text before the audio (the adapters'
context, then the prompt) was warmed in the slots while the speaker talked; the texts go to the client in the order
of the pieces."""
import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass, field

from websockets.exceptions import ConnectionClosed

import adapters
import catalog
import constants
import languages
import metrics
import recordings
import tuning
from audio import FRAME_BYTES, FRAME_S, Levels, live_cut, seconds, split
from dictation import Dictation, adapter_options, prompt
from vad import Stream

SPEECH_EVERY_S = 0.3        # at most one "speech" message per this long
WARM_POLL_S = 0.2           # how often the warm-up looks whether the recording got long enough for one more slot
MIC_INFO_WAIT_S = 15        # for the input device's description at the end
CLIENT_NAME_CHARS = 40
STOP_REASONS = ("user", "silence", "max_duration", "error")
log = logging.getLogger("gemma_voice")


@dataclass
class Start:
    """A checked start message."""
    model: str
    entry: dict
    options: dict
    language: str
    own_prompt: str
    text_prompt: str
    client: str
    identity: dict = field(default_factory=dict)  # of the focused app, window and page (IDENTITY, adapters/__init__.py)
    private: bool = False   # a private dictation: nothing saved, no read request, no adapter, no text in the log
    client_options: dict = field(default_factory=dict)  # the start message's own options: they win over every owner


def parse_start(m, models, args=None):
    """A start message → Start; raises ValueError with what the client is told. The options: the model's catalog
    defaults, then the user's options of the model, then the client's (an experiment)."""
    if not isinstance(m, dict) or m.get("type") != "start":
        raise ValueError(f"expected a start message, got {str(m)[:200]}")
    if m.get("sampleRate", constants.RATE) != constants.RATE or m.get("encoding", constants.ENCODING) != constants.ENCODING:
        raise ValueError(f"the audio must be {constants.RATE} Hz {constants.ENCODING}")
    name = models.name_for(m.get("model") if isinstance(m.get("model"), str) else None)
    if name is None:
        raise ValueError(f"no model {m.get('model')}; this server has: {', '.join(models.entries)}")
    entry = models.entries[name]
    client = tuning.parse(m.get("options"))
    options = tuning.resolve(catalog.model_defaults(entry), tuning.parse(entry.get("options"), "model"), client=client)
    language = str(m.get("language") or "")
    own = (m["prompt"] if isinstance(m.get("prompt"), str) else entry.get("prompt") or "").strip()[:constants.MAX_PROMPT]
    return Start(model=name, entry=entry, options=options, language=language, own_prompt=own,
                 text_prompt=prompt(language, own, entry, getattr(args, "languages", None)),
                 client=str(m.get("client") or "")[:CLIENT_NAME_CHARS], client_options=client,
                 identity=m["identity"] if isinstance(m.get("identity"), dict) and m.get("private") is not True else {},
                 private=m.get("private") is True)


class Session:
    """One recording on one connection."""

    def __init__(self, ws, send, models, args, start, make_stream=None):
        """`make_stream`: what makes the speech detector of the recording (vad.Stream; tests give another)."""
        self.ws, self.send, self.models, self.args, self.start = ws, send, models, args, start
        self.rec = None
        if args.save_recordings and not start.private:
            try:
                self.rec = recordings.Recording(args.recordings)
            except OSError:
                log.exception("cannot start the recording folder")
        self.id = self.rec.id if self.rec else time.strftime("%Y-%m-%d/%H%M%S-") + "unsaved"
        opts = start.options
        self.cut = {n: tuning.value(n, opts, args) for n in ("piece_seconds", "cut_search_seconds", "cut_while_speaking",
                                                             "min_last_piece_seconds")}
        self.max_audio = catalog.max_audio_seconds(start.entry)  # what the model takes in one request
        self.cut["piece_seconds"] = min(self.cut["piece_seconds"], self.max_audio)
        self.cut_frame, self.live_pieces = 0, 0  # the audio before cut_frame (a 30 ms frame) went into pieces
        self.meta = {"recording": self.id, "language": start.language,
                     "prompt": "own" if start.own_prompt else "default", "prompt_chars": len(start.text_prompt),
                     "options": opts, **({"private": True} if start.private else {})}
        self.levels, self.speech = Levels(), (make_stream or Stream)()
        self.audio, self.pending = bytearray(), asyncio.Queue()
        self.texts, self.errors, self.chat = [], [], {}
        self.stopped_at, self.stop_reason = None, None
        self.stopped = asyncio.Event()  # set at the stop: the adapters' context is waited for until then
        self.surfaces, self.content = [], None  # the matched surfaces; what the client read there, by surface name
        self.content_came = asyncio.Event()  # set when the content message came, or when no surface needs one
        self.mic = asyncio.ensure_future(asyncio.to_thread(recordings.input_info)) if self.rec else None
        log.info("recording %s: model %s, client %s, language=%s (%s), %s prompt: %r, options %s, sampler %s",
                 self.id, start.model, start.client or "unknown", start.language,
                 languages.name(start.language) or "no name", self.meta["prompt"], start.text_prompt[:120],
                 opts or "none", tuning.sampler(opts))

    @property
    def heard_seconds(self):
        return seconds(len(self.audio))

    async def fail(self, message):
        self.errors.append(message)
        with contextlib.suppress(Exception):
            await self.send(type="error", message=message)

    # The audio

    async def receive(self):
        """The audio until the stop, the end of the connection (None), or the longest recording."""
        try:
            return await self._receive()
        except ConnectionClosed:
            return None

    async def _receive(self):
        last_speech = 0.0
        limit = self.args.max_recording_seconds
        async for message in self.ws:
            if isinstance(message, (bytes, bytearray)):
                self.audio += message
                if self.rec:
                    self.rec.write(message)
                self.levels.feed(message)
                heard = self.speech.feed(message)
                self.cut_live()
                if heard and time.monotonic() - last_speech >= SPEECH_EVERY_S:
                    last_speech = time.monotonic()
                    await self.send(type="speech")
                if self.heard_seconds >= limit:
                    log.warning("recording %s reached the longest recording, %.0f s: stopped", self.id, limit)
                    await self.send(type="stopped", reason="max_duration")
                    return "max_duration"
                continue
            try:
                m = json.loads(message)
            except ValueError:
                m = None
            if not isinstance(m, dict):
                await self.fail(f"a message that is not a JSON object: {str(message)[:100]!r}")
                continue
            if m.get("type") == "content":
                await self.take_content(m)
            elif m.get("type") == "stop":
                return m.get("reason") if m.get("reason") in STOP_REASONS else "user"
        return None  # the connection ended without a stop

    async def take_content(self, m):
        """The content message: what the client read for the matched surfaces. Only the first one counts, and only for
        a recording whose surfaces need one; of it, only the matched surfaces' parts."""
        if self.content_came.is_set():
            log.warning("recording %s: a content message that was not asked for, or a second one: ignored", self.id)
            return
        if not isinstance(m.get("surfaces"), dict):
            await self.fail("a content message without its surfaces")
            return
        self.content = {s.name: m["surfaces"][s.name] for s in self.surfaces if isinstance(m["surfaces"].get(s.name), dict)}
        log.info("recording %s: the client read %s in %s ms", self.id, ", ".join(self.content) or "nothing",
                 m.get("tookMs"))
        self.content_came.set()

    def cut_live(self):
        """While the speaker talks: each piece that can be cut goes to the model now, with its seconds of speech, so
        that after the stop only the rest is left."""
        if not self.cut["cut_while_speaking"]:
            return
        while (c := live_cut(self.levels.rms, self.cut_frame, self.cut["piece_seconds"], self.cut["cut_search_seconds"],
                             self.cut["min_last_piece_seconds"])) is not None:
            self.pending.put_nowait((bytes(self.audio[self.cut_frame * FRAME_BYTES:c * FRAME_BYTES]),
                                     self.speech.seconds(self.cut_frame * FRAME_S, c * FRAME_S)))
            self.live_pieces += 1
            self.cut_frame = c

    # The context and the pieces

    def read_request(self):
        """The surfaces of the enabled adapters that the start's identity is on, and the read request's surfaces: what
        the client reads there, with the budgets of the adapter's options (dictation.adapter_options), the same as its
        context's."""
        surfaces = adapters.match(self.start.identity, self.args.adapters)

        def budget(adapter, key):
            options = adapter_options(adapter, self.start.options, self.args, self.start.client_options)
            return tuning.value(tuning.BY_KEY[key].name, options, self.args)
        return surfaces, adapters.read(surfaces, budget)

    async def ask_to_read(self):
        """The read request, at once, before the model loads: the client reads the matched surfaces while the speaker
        talks. With no surface that reads anything, the adapters need no content message. A private dictation gets no
        read request."""
        if not self.start.private:
            self.surfaces, read = await asyncio.to_thread(self.read_request)
            log.info("recording %s: app %s, surfaces %s", self.id, adapters.screen.bundle(self.start.identity) or "unknown",
                     ", ".join(s.name for s in self.surfaces) or "none")
            with contextlib.suppress(Exception):  # a closed connection ends the recording in receive()
                await self.send(type="read", surfaces=read, tokenWeights=catalog.token_weights(self.start.entry))
        if not adapters.needs_content(self.surfaces):
            self.content_came.set()

    async def context(self):
        """The adapters' context, or None; what it was goes to the record. The adapters run once the client's content
        came (or at once for surfaces that read nothing), until the stop. A private dictation has none: no adapter
        runs."""
        if self.start.private:
            log.info("recording %s: private, no context", self.id)
            return None
        if not self.surfaces:
            return None
        if not self.content_came.is_set():
            came, stopped = asyncio.ensure_future(self.content_came.wait()), asyncio.ensure_future(self.stopped.wait())
            await asyncio.wait({came, stopped}, return_when=asyncio.FIRST_COMPLETED)
            came.cancel()
            stopped.cancel()
            if not self.content_came.is_set():
                self.chat["errors"] = ["no content by the stop"]
                log.error("recording %s: no context: the client sent no content by the stop", self.id)
                return None
        # Adapters still running at the stop: the dictation goes on without context
        found = await adapters.context_until(self.start.identity, self.surfaces, self.content, self.stopped) or {}
        if not found.get("adapter") and found.get("errors"):
            log.error("recording %s: no context: %s", self.id, "; ".join(found["errors"]))
        self.chat.update({k: found[k] for k in ("adapter", "surface", "about", "source", "details", "errors")
                          if found.get(k)})
        chat = found if found.get("messages") or found.get("documents") or found.get("terms") else None
        if chat:
            self.chat.update(messages=len(chat.get("messages") or []), documents=len(chat.get("documents") or []),
                             terms=len(chat.get("terms") or []))
        log.info("recording %s: surface %s, context %s", self.id, found.get("surface", "none"),
                 f"{found.get('source') or found.get('about')}, {self.chat['messages']} messages, "
                 f"{self.chat['documents']} files, {self.chat['terms']} terms" if chat else "none")
        return chat

    async def warm_slots(self, dictation, slots):
        # Slot 0 at once; slot k once the recording is long enough for a (k+1)th piece, so that every piece finds
        # its text in its slot's cache. A failed warm-up only costs time: the piece then processes the text itself.
        for k in range(slots):
            while k and self.stopped_at is None and self.heard_seconds < k * self.cut["piece_seconds"]:
                await asyncio.sleep(WARM_POLL_S)
            if k and self.heard_seconds < k * self.cut["piece_seconds"]:
                return
            try:
                await dictation.warm(k if slots > 1 else None)
            except Exception:
                log.exception("recording %s: warming slot %d failed", self.id, k)

    async def transcribe(self):
        if self.models.recording.locked():
            log.info("recording %s waits for the recording before it", self.id)
        async with self.models.recording:  # one recording at a time on the model
            dictation, warming, tasks, context = None, None, [], None
            try:
                # The context is read now, while the model loads if it left memory (Models.unload_when_idle); the
                # audio keeps coming meanwhile, and its pieces wait for the model
                context = asyncio.ensure_future(self.context())
                try:
                    model = await self.models.get(self.start.model)
                    entry = (getattr(self.models, "entries", None) or {}).get(getattr(model, "name", None))
                    dictation = Dictation(model, self.start.text_prompt, self.start.options, self.args, self.meta,
                                          self.rec, client_options=self.start.client_options,
                                          token_weights=catalog.token_weights(entry))
                    await dictation.prepare(await context)
                except Exception as e:
                    log.exception("recording %s: preparing failed", self.id)
                    await self.fail(str(e))
                slots = await asyncio.to_thread(dictation.slots) if dictation else 1
                if dictation and tuning.value("warm_text", self.start.options, self.args):
                    warming = asyncio.ensure_future(self.warm_slots(dictation, slots))
                # Every piece goes to llama-server as soon as it is cut, piece i to slot (i - 1) % slots.
                piece = 0
                while (item := await self.pending.get()) is not None:
                    piece += 1
                    if dictation:
                        pcm, speech = item
                        tasks.append(asyncio.ensure_future(
                            dictation.piece(pcm, piece, speech, slot=(piece - 1) % slots if slots > 1 else None)))
                for task in tasks:  # in the order of the pieces
                    try:
                        text = await task
                    except Exception as e:  # one failed piece does not end the recording
                        log.exception("recording %s: a piece failed", self.id)
                        await self.fail(str(e))
                        continue
                    if text:
                        self.texts.append(text)
                        await self.send(type="text", text=text)
            finally:
                others = [t for t in (warming, context) if t]
                for t in tasks + others:
                    t.cancel()
                for t in tasks + others:
                    with contextlib.suppress(BaseException):
                        await t

    # The whole recording

    def levels_report(self):
        report = self.levels.report(self.speech.at)
        if report["longest_digital_silence_s"] >= 0.5:
            log.warning("recording %s: %.2f s of digital silence (all zeros): the microphone may have been closed or "
                        "muted", self.id, report["longest_digital_silence_s"])
        if report["clipped_samples"]:
            log.warning("recording %s: %d clipped samples: the input is too loud", self.id, report["clipped_samples"])
        log.info("recording %s: %.1f s, speech %s dBFS, noise %s dBFS, peak %s dBFS, speech in %.0f%% of the time",
                 self.id, report["seconds"], report["speech_dbfs"], report["noise_dbfs"], report["peak_dbfs"],
                 100 * report["speech_fraction"])
        metrics.metric("audio", recording=self.id, **{k: v for k, v in report.items() if k != "dbfs_per_second"})
        if self.rec:
            self.rec.save("audio.json", report)

    async def run(self):
        await self.ask_to_read()
        worker = asyncio.create_task(self.transcribe())
        try:
            self.stop_reason = await self.receive()
            self.stopped_at = time.monotonic()
            self.stopped.set()
            if self.stop_reason is None:
                log.warning("recording %s: the client closed the connection before the stop", self.id)
                self.errors.append("the client closed the connection before the stop")
                return
            # The recording is whole: cut what is left of it now, into pieces as equal as the pauses allow.
            rest, start = self.cut_frame * FRAME_BYTES, self.cut_frame * FRAME_S
            self.speech.flush()
            for pcm, a, b in split(bytes(self.audio[rest:]), self.levels.rms[self.cut_frame:],
                                   self.cut["piece_seconds"], self.cut["cut_search_seconds"], self.max_audio):
                self.pending.put_nowait((pcm, self.speech.seconds(start + a, start + b)))
            if self.live_pieces:
                log.info("recording %s: %d pieces cut while the speaker talked, %.1f s left at the stop", self.id,
                         self.live_pieces, seconds(len(self.audio) - rest))
            self.pending.put_nowait(None)
            self.levels_report()
            # The client may give up before the last piece; then the running requests are closed.
            closed = asyncio.ensure_future(self.ws.wait_closed())
            await asyncio.wait({worker, closed}, return_when=asyncio.FIRST_COMPLETED)
            if not worker.done():
                log.warning("recording %s: the client closed the connection before the last piece", self.id)
                self.errors.append("the client closed the connection before the last piece")
                return
            closed.cancel()
            await worker
            with contextlib.suppress(Exception):
                await self.send(type="done")
                await self.ws.close()
            metrics.metric("recording", model=self.start.model, client=self.start.client, recording=self.id,
                           language=self.start.language, prompt=self.meta["prompt"], options=self.start.options,
                           audio_seconds=round(self.heard_seconds, 2), stop_reason=self.stop_reason,
                           adapter=self.chat.get("adapter"), context_messages=self.chat.get("messages"),
                           context_documents=self.chat.get("documents"),
                           pieces_while_speaking=self.live_pieces,
                           seconds_left_at_stop=round(seconds(len(self.audio) - self.cut_frame * FRAME_BYTES), 2),
                           done_after_stop_seconds=round(time.monotonic() - self.stopped_at, 3))
        finally:
            if not worker.done():
                self.pending.put_nowait(None)
                worker.cancel()
                with contextlib.suppress(BaseException):
                    await worker
            await self.finish()

    async def finish(self):
        if not self.rec:
            return
        mic_info = None
        if self.mic is not None:
            with contextlib.suppress(Exception):
                mic_info = await asyncio.wait_for(asyncio.shield(self.mic), MIC_INFO_WAIT_S)
        self.rec.finish({"model": self.start.model, "language": self.start.language, "client": self.start.client,
                         "stopReason": self.stop_reason or "connection closed", "error": "; ".join(self.errors) or None,
                         "identity": self.start.identity or None, "surfaces": [s.name for s in self.surfaces],
                         "content": self.content, "chat": self.chat or None, "pieces": self.texts,
                         "text": " ".join(self.texts),
                         "input": mic_info})

