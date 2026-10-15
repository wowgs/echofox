"""Sends a WAV file to the dictation server the way a client does, and prints what comes back.

The audio goes in 100 ms chunks at real-time speed, then the stop message. The script prints each message with
its time, and the time from the stop until the server says done.
Usage: try_wav.py <16 kHz mono 16-bit WAV> [--url URL] [--working] [--model NAME] [--language ru]
                  [--session ID]... [--snapshot FILE] [--app BUNDLE_ID] [--fast]
It goes to the test dictation server (server/test_server.sh, places.TEST_URL) unless --url says otherwise. The working
server, the one your dictation uses, it reaches only with --working: a run there would wait behind your dictation,
make yours wait, and add to your recordings and metrics.
"""
import argparse
import asyncio
import json
import time
import urllib.parse
import wave

from websockets.asyncio.client import connect

import places


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("wav")
    p.add_argument("--url", default=places.TEST_URL, help=f"the dictation server (default the test one, {places.TEST_URL})")
    p.add_argument("--working", action="store_true", help=f"allow the working server ({places.WORKING_URL})")
    p.add_argument("--language", default="ru")
    p.add_argument("--model", help="a model of the registry (default: the server's first)")
    p.add_argument("--session", action="append", default=[], help="a session id that the client knows, for the chat context")
    p.add_argument("--app", help="the bundle id of the app with the input box, for the chat context")
    p.add_argument("--snapshot", help="a focus snapshot (macos lv-snapshot), for the chat context")
    p.add_argument("--fast", action="store_true", help="send without waiting between chunks")
    args = p.parse_args()
    if urllib.parse.urlparse(args.url).port == places.WORKING_PORT and not args.working:
        p.error(f"{args.url} is the working dictation server; use the test one (server/test_server.sh start) or add --working")
    with wave.open(args.wav) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000), "need 16 kHz mono 16-bit"
        pcm = w.readframes(w.getnframes())
    t0 = time.monotonic()
    texts, stop, done = [], None, None
    try:
        ws = await connect(args.url, max_size=None)
    except OSError as e:
        raise SystemExit(f"cannot reach {args.url} ({e}); for the test server: server/test_server.sh start")
    async with ws:
        await ws.send(json.dumps({"type": "start", "language": args.language, "sampleRate": 16000,
                                  "encoding": "pcm_s16le", "client": "try_wav", "hints": {"sessions": args.session} if args.session else {},
                                  **({"model": args.model} if args.model else {}), **({"app": args.app} if args.app else {}),
                                  **({"snapshot": json.load(open(args.snapshot))} if args.snapshot else {})}))

        async def receive():
            nonlocal done
            speech = 0
            async for m in ws:
                d = json.loads(m)
                if d["type"] == "speech":
                    speech += 1
                    continue
                print(f"{time.monotonic() - t0:6.2f} s  {d}")
                if d["type"] == "text":
                    texts.append(d["text"])
                if d["type"] == "done":
                    done = time.monotonic()
            print(f"speech events: {speech}")

        reader = asyncio.create_task(receive())
        for i in range(0, len(pcm), 3200):  # 100 ms
            await ws.send(pcm[i:i + 3200])
            if not args.fast:
                await asyncio.sleep(0.1)
        stop = time.monotonic()
        await ws.send(json.dumps({"type": "stop", "reason": "user"}))
        await reader
    print(f"audio {len(pcm) / 32000:.1f} s; done {done - stop:.2f} s after the stop" if done else "no done message")
    print("text:", " ".join(texts))


if __name__ == "__main__":
    asyncio.run(main())
