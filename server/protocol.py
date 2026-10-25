"""One client connection (the protocol is in gemma_voice.py's text): an info request, or one recording.

A recording (Session): the audio arrives and is saved; while the speaker talks, a piece is cut and goes to the model
each time enough audio is heard (audio.live_cut); at the stop, the rest is cut into pieces; one model request per
piece, each as soon as it is cut, on llama-server's slots, after the text before the audio (the adapters' context,
then the prompt) was warmed in the slots while the speaker talked; the texts go to the client in the order of the
pieces."""
import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass, field

from websockets.exceptions import ConnectionClosed

import adapters
import constants
import metrics
import recordings
import settings
import tuning
from audio import FRAME_BYTES, Levels, has_speech, live_cut, seconds, split
from dictation import LANGUAGES, MAX_PROMPT, Dictation, prompt

SPEECH_EVERY_S = 0.3        # at most one "speech" message per this long
WARM_POLL_S = 0.2           # how often the warm-up looks whether the recording got long enough for one more slot
MIC_INFO_WAIT_S = 15        # for the input device's description at the end
CLIENT_NAME_CHARS = 40
STOP_REASONS = ("user", "silence", "max_duration", "error")
INTERFACE = 2  # of the protocol; the app checks it
log = logging.getLogger("gemma_voice")


def info(args):
    """What a client needs to know of this server: the protocol, the audio, the waits, the languages the prompt names,
    the adapters, and the settings it may show and change (settings.schema)."""
    enabled = set(getattr(args, "adapters", None) or [])
    return {"type": "info", "interface": INTERFACE, "adapterInterface": adapters.registry.INTERFACE,
            "sampleRate": constants.RATE, "encoding": constants.ENCODING,
            "textWaitSeconds": constants.TEXT_WAIT_S, "maxRecordingSeconds": args.max_recording_seconds,
            "languages": [{"code": c, "name": n} for c, n in sorted(LANGUAGES.items(), key=lambda i: i[1])],
            "adapters": [p.info(enabled) for p in adapters.registry.plugins().values()],
            "settings": settings.schema(args)}


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
    hints: dict = field(default_factory=dict)
    snapshot: dict = field(default_factory=dict)
    private: bool = False   # a private dictation: nothing saved, no adapter, no text in the log


def parse_start(m, models):
    """A start message → Start; raises ValueError with what the client is told."""
    if not isinstance(m, dict) or m.get("type") != "start":
        raise ValueError(f"expected a start message, got {str(m)[:200]}")
    if m.get("sampleRate", constants.RATE) != constants.RATE or m.get("encoding", constants.ENCODING) != constants.ENCODING:
        raise ValueError(f"the audio must be {constants.RATE} Hz {constants.ENCODING}")
    name = models.name_for(m.get("model") if isinstance(m.get("model"), str) else None)
    if name is None:
        raise ValueError(f"no model {m.get('model')}; this server has: {', '.join(models.entries)}")
    entry = models.entries[name]
    options = {**tuning.parse_options(entry.get("options")), **tuning.parse_options(m.get("options"))}
    language = str(m.get("language") or "")
    own = m["prompt"] if isinstance(m.get("prompt"), str) else entry.get("prompt") or ""
    return Start(model=name, entry=entry, options=options, language=language, own_prompt=own.strip()[:MAX_PROMPT],
                 text_prompt=prompt(language, own.strip()[:MAX_PROMPT]), client=str(m.get("client") or "")[:CLIENT_NAME_CHARS],
                 hints=m["hints"] if isinstance(m.get("hints"), dict) else {},
                 snapshot=m["snapshot"] if isinstance(m.get("snapshot"), dict) else {},
                 private=m.get("private") is True)


async def handle(ws, models, args):
    """One connection. `args`: the recording settings (settings.recording_settings)."""
    async def send(**m):
        await ws.send(json.dumps(m, ensure_ascii=False))

    try:
        first = json.loads(await ws.recv())
    except (ValueError, TypeError):
        first = None
    if isinstance(first, dict) and first.get("type") == "info":
        await send(**await asyncio.to_thread(info, args))
        await ws.close()
        return
    try:
        start = parse_start(first, models)
    except ValueError as e:
        await send(type="error", message=str(e))
        await ws.close()
        return
    await Session(ws, send, models, args, start).run()


class Session:
    """One recording on one connection."""

    def __init__(self, ws, send, models, args, start):
        self.ws, self.send, self.models, self.args, self.start = ws, send, models, args, start
        self.rec = None
        if args.save_recordings and not start.private:
            try:
                self.rec = recordings.Recording(args.recordings)
            except OSError:
                log.exception("cannot start the recording folder")
        self.id = self.rec.id if self.rec else time.strftime("%Y-%m-%d/%H%M%S-") + "unsaved"
        opts = start.options
        self.cut = {n: tuning.value(n, opts, args) for n in ("threshold_db", "speech_above_noise_db", "piece_seconds",
                                                             "cut_search_seconds", "cut_while_speaking",
                                                             "min_last_piece_seconds")}
        self.cut_frame, self.live_pieces = 0, 0  # the audio before cut_frame (a 30 ms frame) went into pieces
        self.meta = {"recording": self.id, "language": start.language,
                     "prompt": "own" if start.own_prompt else "default", "prompt_chars": len(start.text_prompt),
                     "options": opts, **({"private": True} if start.private else {})}
        self.levels = Levels(self.cut["threshold_db"], self.cut["speech_above_noise_db"])
        self.audio, self.pending = bytearray(), asyncio.Queue()
        self.texts, self.errors, self.chat = [], [], {}
        self.stopped_at, self.stop_reason = None, None
        self.mic = asyncio.ensure_future(asyncio.to_thread(recordings.input_info)) if self.rec else None
        log.info("recording %s: model %s, client %s, language=%s (%s), %s prompt: %r, options %s, sampler %s",
                 self.id, start.model, start.client or "unknown", start.language,
                 LANGUAGES.get(start.language.split("-")[0], "no name"), self.meta["prompt"], start.text_prompt[:120],
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
                self.cut_live()
                if self.levels.heard and time.monotonic() - last_speech >= SPEECH_EVERY_S:
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
            if m.get("type") == "stop":
                return m.get("reason") if m.get("reason") in STOP_REASONS else "user"
        return None  # the connection ended without a stop

    def cut_live(self):
        """While the speaker talks: each piece that can be cut goes to the model now, so that after the stop only the
        rest is left. A piece without speech is dropped."""
        if not self.cut["cut_while_speaking"]:
            return
        while (c := live_cut(self.levels.rms, self.cut_frame, self.cut["piece_seconds"], self.cut["cut_search_seconds"],
                             self.cut["min_last_piece_seconds"])) is not None:
            if has_speech(self.levels.rms[self.cut_frame:c], self.levels.threshold):
                self.pending.put_nowait(bytes(self.audio[self.cut_frame * FRAME_BYTES:c * FRAME_BYTES]))
                self.live_pieces += 1
            self.cut_frame = c

    # The context and the pieces

    async def context(self):
        """The adapters' context, or None; what it was goes to the record. A private dictation has none: the client
        sent no snapshot, and no adapter runs."""
        if self.start.private:
            log.info("recording %s: private, no context", self.id)
            return None
        own = [o.get("chat_history_token_budget") for o in (getattr(self.args, "adapter_options", None) or {}).values()]
        if tuning.value("chat_history_token_budget", self.start.options, self.args) <= 0 and not any(own):
            return None  # the context is off, and no adapter turns it on for itself
        try:
            found = await asyncio.wait_for(asyncio.to_thread(adapters.context, self.start.snapshot, self.start.hints,
                                                             self.args.adapters), adapters.CONTEXT_TIMEOUT_S)
        except TimeoutError:  # a plugin hangs: the dictation goes on without context
            log.error("recording %s: the adapters gave no context in %.0f s", self.id, adapters.CONTEXT_TIMEOUT_S)
            found = {"errors": [f"no context in {adapters.CONTEXT_TIMEOUT_S:.0f} s"]}
        found = found or {}
        self.chat.update({k: found[k] for k in ("adapter", "confidence", "reason", "about", "source", "details",
                                                "errors") if found.get(k)})
        chat = found if found.get("messages") else None
        if chat:
            self.chat.update(messages=len(chat["messages"]), terms=len(chat["terms"]))
        log.info("recording %s: adapter %s (%s), context %s", self.id, found.get("adapter", "none"),
                 found.get("reason", "no adapter claims it"),
                 f"{found.get('source') or found.get('about')}, {len(chat['messages'])} messages" if chat else "none")
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
            dictation, warming, tasks = None, None, []
            try:
                try:
                    dictation = Dictation(await self.models.get(self.start.model), self.start.text_prompt,
                                          self.start.options, self.args, self.meta, self.rec)
                    await dictation.prepare(await self.context())
                except Exception as e:
                    log.exception("recording %s: preparing failed", self.id)
                    await self.fail(str(e))
                slots = await asyncio.to_thread(dictation.slots) if dictation else 1
                if dictation and self.args.warm_text:
                    warming = asyncio.ensure_future(self.warm_slots(dictation, slots))
                # Every piece goes to llama-server as soon as it is cut, piece i to slot (i - 1) % slots.
                piece = 0
                while (pcm := await self.pending.get()) is not None:
                    piece += 1
                    if dictation:
                        tasks.append(asyncio.ensure_future(
                            dictation.piece(pcm, piece, slot=(piece - 1) % slots if slots > 1 else None)))
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
                for t in tasks + ([warming] if warming else []):
                    t.cancel()
                for t in tasks + ([warming] if warming else []):
                    with contextlib.suppress(BaseException):
                        await t

    # The whole recording

    def levels_report(self):
        report = self.levels.report()
        if report["longest_digital_silence_s"] >= 0.5:
            log.warning("recording %s: %.2f s of digital silence (all zeros): the microphone may have been closed or "
                        "muted", self.id, report["longest_digital_silence_s"])
        if report["clipped_samples"]:
            log.warning("recording %s: %d clipped samples: the input is too loud", self.id, report["clipped_samples"])
        log.info("recording %s: %.1f s, speech %s dBFS, noise %s dBFS (floor %s), threshold %s dBFS, peak %s dBFS, "
                 "speech in %.0f%% of the time", self.id, report["seconds"], report["speech_dbfs"],
                 report["noise_dbfs"], report["noise_floor_dbfs"], report["threshold_dbfs"], report["peak_dbfs"],
                 100 * report["speech_fraction"])
        metrics.metric("audio", recording=self.id, **{k: v for k, v in report.items() if k != "dbfs_per_second"})
        if self.rec:
            self.rec.save("audio.json", report)

    async def run(self):
        worker = asyncio.create_task(self.transcribe())
        try:
            self.stop_reason = await self.receive()
            self.stopped_at = time.monotonic()
            if self.stop_reason is None:
                log.warning("recording %s: the client closed the connection before the stop", self.id)
                self.errors.append("the client closed the connection before the stop")
                return
            # The recording is whole: cut what is left of it now, into pieces as equal as the pauses allow.
            rest = self.cut_frame * FRAME_BYTES
            for pcm in split(bytes(self.audio[rest:]), self.levels.rms[self.cut_frame:], self.levels.threshold,
                             self.cut["piece_seconds"], self.cut["cut_search_seconds"]):
                self.pending.put_nowait(pcm)
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
                         "chat": self.chat or None, "pieces": self.texts, "text": " ".join(self.texts),
                         "input": mic_info})
