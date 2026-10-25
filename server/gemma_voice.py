"""A dictation server for echofox: speech to text with Gemma 4 E4B in llama.cpp, for its clients (the menu bar
app; server/try_wav.py).

Clients are thin: they send the audio and show the text. The server has the rest: the model registry with each
model's prompt and options, the adapters that give the chat context, and the recordings. The protocol, on one WebSocket:
  client → server  {"type":"info"}: the server answers {"type":"info","interface","adapterInterface","sampleRate",
                   "encoding","textWaitSeconds","maxRecordingSeconds","adapters":[…]} and closes; or
                   {"type":"start","model":"<name>","language":"ru","sampleRate":16000,"encoding":"pcm_s16le",
                   "client":"<name>","snapshot":{…},"hints":{…}}, then binary audio (16-bit little-endian PCM, 16 kHz,
                   mono), then {"type":"stop","reason":"user"|"silence"|"max_duration"|"error"}.
                   "snapshot": the focus at the start of the dictation (adapters/__init__.py has its fields); the
                   adapter that claims it gives the context. "hints": what the client knows, passed to the adapters
                   as it is. An experiment may also send "prompt" and "options", which override the model's.
  server → client  {"type":"speech"} while it hears speech; {"type":"stopped","reason":"max_duration"} if the
                   recording reached its time limit, maxRecordingMinutes (the server stops taking audio); {"type":"text","text":…} for
                   each finished piece, in order; {"type":"error","message":…}; {"type":"done"} after the last piece,
                   then it closes

A model takes at most its catalog entry's maxAudioSeconds of audio per request (catalog.json; Gemma 4: 30 s). While
the speaker talks, a piece is cut each time pieceSeconds plus minLastPieceSeconds are heard since the cut before, at
the quietest moment shortly before pieceSeconds, and goes to the model at once; at the stop, the rest is cut into
pieces as close to pieceSeconds as possible and equal, none longer than the model takes, each cut moved to the
quietest moment near its equal point. What is speech is Silero VAD's (vad.py), on the whole recording as it arrives:
it sends the client "speech", and a piece with less than minSpeechSeconds of it does not go to the model. Each piece then goes to the model in a request of its own, so the model
never sees its answers to earlier pieces (with them in the conversation it repeated them). The prompt is the model's
template (its catalog entry's, or its own in the config) with the notes of the dictation's language (languages.json),
with the text before the audio, as Gemma's model card advises.

The models run in llama.cpp's llama-server (its launchd agent: llama.write_agent), through its OpenAI-compatible
/v1/chat/completions with the audio as "input_audio". Each knob has one owner (tuning.py, settings.py): the
server's (the recording's time limit, the storage; its constants: the cutting, the speech), a model's (its sampler;
its constant: the length of its text; the defaults in its catalog entry), an adapter's (its context; the defaults
in its manifest). The server logs each recording's levels (speech, noise, peak, clipping, digital silence) and keeps them in audio.json.

A piece's request holds the text before the audio (the messages of the place that an enabled adapter found, within
its chatHistoryTokenBudget, terms within its chatTermsTokenBudget, then the prompt) and the piece's audio. The text is
warmed in llama-server's cache while the speaker talks (cache_prompt).

The text of a piece is limited to the model's maxTokensPerSpeechSecond tokens per second of the piece's speech: a
text that reaches it is the model's own and is dropped, and a model that never writes its end token stops there.

Each recording gets a folder in the config's recordings folder (recordings.py): the whole audio (mic.wav), adapter.json, each piece's
audio, the text before the audio, each piece's text (pieces.jsonl) and the levels (audio.json); "saveRecordings":
false in the config turns this off.
"""
import argparse
import asyncio
import json
import logging
import signal

from websockets.asyncio.server import serve

import constants
import protocol
import settings
from llama import Models

log = logging.getLogger("gemma_voice")


async def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                epilog="The settings are in the config file only. The server watches the file.")
    p.add_argument("--config", default=None, help=f"the config file (default {settings.config_file()})")
    p.add_argument("--ignore-selection", action="store_true",
                   help="do not follow the model chosen in the menus, and never start or stop llama-server agents "
                        "(for a test server)")
    cli = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    path = cli.config or settings.config_file()
    settings.migrate(path)
    current = settings.resolve(settings.file_settings(path) or {})
    st = settings.apply(current)
    models = Models(current["models"], manage=not cli.ignore_selection,
                    models_folder=constants.path(current["modelsFolder"]))
    if cli.ignore_selection:
        await models.get(next(iter(current["models"])))  # the default model answers before the first recording
    log.info("settings: %s", json.dumps(current, ensure_ascii=False))
    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: stop.done() or stop.set_result(None))
    watcher = settings.ConfigWatcher(path, models, st, current, stop, follow=not cli.ignore_selection)
    watching = asyncio.create_task(watcher.run())
    async with serve(lambda ws: protocol.handle(ws, models, st), current["host"], current["port"],
                     max_size=None) as server:
        log.info("listening on ws://%s:%d, models: %s (default %s), config %s", current["host"], current["port"],
                 ", ".join(current["models"]), next(iter(current["models"])), path)
        await stop
        # A restart (launchd, a changed host or port) lets the running recordings end: no new connections, the open
        # ones go on until their text is sent. launchd waits for it (ExitTimeOut in server/launchd.sh).
        server.close(close_connections=False)
        try:
            await asyncio.wait_for(server.wait_closed(), constants.STOP_WAIT_S)
        except TimeoutError:
            log.warning("recordings still running after %d s: the server ends anyway", constants.STOP_WAIT_S)
        log.info("the server ends")
    watching.cancel()


if __name__ == "__main__":
    asyncio.run(main())
