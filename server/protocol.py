"""One client connection: the protocol of gemma_voice.py (see its text), the recording's audio, levels and pieces."""
import asyncio
import contextlib
import json
import logging
import os
import time
import urllib.parse

import adapters
import metrics
import recordings
from audio import RATE, Levels, split
from dictation import CHAT_HISTORY_TOKEN_BUDGET, LANGUAGES, MAX_PROMPT, parse_options, prompt, sampler_of

SPEECH_EVERY_S = 0.3
log = logging.getLogger("gemma_voice")


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
    metrics.metric("audio", recording=recording, **{k: v for k, v in report.items() if k != "dbfs_per_second"})
    if save_dir:
        try:
            os.makedirs(save_dir, exist_ok=True)
            with open(os.path.join(save_dir, "audio.json"), "w", encoding="utf-8") as f:
                json.dump(report, f, indent=1)
        except OSError:
            log.exception("cannot save audio.json")


STOP_REASONS = ("user", "silence", "max_duration", "error")


async def handle(ws, models, args):
    """One connection. `args`: the recording settings (settings.apply_recording_settings)."""
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
    snapshot = adapters.snapshot_of(start)
    log.info("recording: model %s, client %s, language=%s (%s), %s prompt: %r, options %s, sampler %s", name,
             client or "unknown", language, LANGUAGES.get(language.split("-")[0], "no name"),
             "own" if own.strip() else "default", text_prompt[:120], options or "none", sampler_of(options))
    recording = os.urandom(4).hex()
    rec = None
    if args.save_recordings:
        try:
            rec = recordings.Recording(args.recordings)
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
                dictation = (await models.get(name)).dictation(
                    text_prompt, options, meta, save_dir, limits=(args.output_tokens_per_second, args.output_tokens_base))
                chat = None
                if options.get("chat_history_token_budget", CHAT_HISTORY_TOKEN_BUDGET) > 0:
                    found = await asyncio.to_thread(adapters.context, snapshot, sessions)
                    if found:
                        chat_info.update({k: found[k] for k in ("adapter", "confidence", "reason", "how", "session",
                                                                "file", "title", "desktopSession") if found.get(k)})
                    if found and "messages" in found:
                        chat = found
                        chat_info.update(messages=len(found["messages"]), terms=len(found["terms"]))
                    log.info("recording %s: adapter %s (%s), context %s", recording,
                             found["adapter"] if found else "none", found["reason"] if found else "no adapter claims it",
                             f"{found['how']}: {found['file']}, {len(found['messages'])} replies" if chat else "none")
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
        metrics.metric("recording", model=name, client=client, recording=recording, language=language, prompt=meta["prompt"],
               options=options, audio_seconds=round(audio_bytes / 2 / RATE, 2), stop_reason=stop_reason,
               adapter=chat_info.get("adapter"), context_how=chat_info.get("how"),
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
                            "session": {"id": chat_info["session"], "file": chat_info["file"]}
                            if chat_info.get("file") else None,
                            "input": mic_info})
            except OSError:
                log.exception("cannot finish the recording folder %s", rec.dir)
