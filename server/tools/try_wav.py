"""Sends a WAV file to the dictation server the way a client does, and prints what comes back.

The audio goes in 100 ms chunks at real-time speed, then the stop message. The script prints each message with
its time, and the time from the stop until the server says done.
Usage: try_wav.py <16 kHz mono 16-bit WAV> [--url URL] [--working] [--model NAME] [--language CODE]
                  [--snapshot FILE] [--options JSON] [--prompt TEXT] [--fast]
With --snapshot, a recorded snapshot ({"identity", "content": {"surfaces"}}, as macos echofox-snapshot prints it), the
start message carries its identity, and the script answers the server's read request with the parts that each surface
asks for of what the file read for it (or for the surface "snapshot", when echofox-snapshot read by its flags), as the
app answers with what it reads.
It goes to the test dictation server (server/tools/test_server.sh, constants.TEST_URL) unless --url says otherwise.
The working server, the one your dictation uses, it reaches only with --working: a run there would wait behind your
dictation, make yours wait, and add to your recordings and metrics.
"""
import argparse
import asyncio
import json
import pathlib
import sys
import time
import urllib.parse
import wave

from websockets.asyncio.client import connect

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # the server's modules: a tool is in server/tools

import constants  # noqa: E402
import settings  # noqa: E402
from adapters import surfaces  # noqa: E402


def config_language():
    """The config's language ("" if it names none, or cannot be read)."""
    try:
        with open(settings.config_file(), encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError):
        return ""
    return (c.get("language") or "") if isinstance(c, dict) else ""


def recorded(path):
    """A recorded snapshot: {"identity", "content": {"surfaces"}}; raises ValueError when the file has no identity."""
    with open(path, encoding="utf-8") as f:
        snapshot = json.load(f)
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("identity"), dict):
        raise ValueError(f"{path} has no \"identity\": record it with macos echofox-snapshot")
    return snapshot


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("wav")
    p.add_argument("--url", default=constants.TEST_URL, help=f"the dictation server (default the test one, {constants.TEST_URL})")
    p.add_argument("--working", action="store_true", help=f"allow the working server ({constants.WORKING_URL})")
    p.add_argument("--language", default=config_language(),
                   help="the speech's language (default: the config's, as the app sends it)")
    p.add_argument("--model", help="a model of the registry (default: the server's first)")
    p.add_argument("--snapshot", help="a recorded snapshot (macos echofox-snapshot), for the chat context")
    p.add_argument("--options", type=json.loads, help='the start message\'s options, e.g. \'{"cutWhileSpeaking": false}\'')
    p.add_argument("--prompt", help="the start message's own prompt, instead of the model's")
    p.add_argument("--fast", action="store_true", help="send without waiting between chunks")
    args = p.parse_args()
    try:
        snapshot = recorded(args.snapshot) if args.snapshot else {}
    except (OSError, ValueError) as e:
        p.error(str(e))
    if urllib.parse.urlparse(args.url).port == constants.WORKING_PORT and not args.working:
        p.error(f"{args.url} is the working dictation server; use the test one (server/tools/test_server.sh start) or add --working")
    with wave.open(args.wav) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, constants.SAMPLE_BYTES, constants.RATE), \
            f"need {constants.RATE} Hz mono 16-bit"
        pcm = w.readframes(w.getnframes())
    t0 = time.monotonic()
    texts, stop, done, answered = [], None, None, asyncio.Event()
    try:
        ws = await connect(args.url, max_size=None)
    except OSError as e:
        raise SystemExit(f"cannot reach {args.url} ({e}); for the test server: server/tools/test_server.sh start")
    async with ws:
        await ws.send(json.dumps({"type": "start", "language": args.language, "sampleRate": constants.RATE,
                                  "encoding": constants.ENCODING, "client": "try_wav",
                                  **({"model": args.model} if args.model else {}),
                                  **({"options": args.options} if args.options else {}),
                                  **({"prompt": args.prompt} if args.prompt else {}),
                                  **({"identity": snapshot["identity"]} if snapshot else {})}))

        async def receive():
            nonlocal done
            speech = 0
            async for m in ws:
                d = json.loads(m)
                if d["type"] == "speech":
                    speech += 1
                    continue
                print(f"{time.monotonic() - t0:6.2f} s  {d}")
                if d["type"] == "read":  # the content, between the audio's messages
                    if d["surfaces"]:
                        await ws.send(json.dumps({"type": "content", "tookMs": 0,
                                                  "surfaces": surfaces.answer(d["surfaces"], snapshot.get("content"))}))
                    answered.set()
                if d["type"] == "text":
                    texts.append(d["text"])
                if d["type"] == "done":
                    done = time.monotonic()
            answered.set()  # a server that ended the connection sends no read
            print(f"speech events: {speech}")

        reader = asyncio.create_task(receive())
        for i in range(0, len(pcm), 3200):  # 100 ms
            await ws.send(pcm[i:i + 3200])
            if not args.fast:
                await asyncio.sleep(0.1)
        if snapshot:  # with --fast the audio can end first; the server takes the content only before the stop
            await answered.wait()
        stop = time.monotonic()
        await ws.send(json.dumps({"type": "stop", "reason": "user"}))
        await reader
    print(f"audio {len(pcm) / 32000:.1f} s; done {done - stop:.2f} s after the stop" if done else "no done message")
    print("text:", " ".join(texts))


if __name__ == "__main__":
    asyncio.run(main())
