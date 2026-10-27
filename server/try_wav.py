"""Sends a WAV file to the dictation server the way a client does, and prints what comes back.

The audio goes in 100 ms chunks at real-time speed, then the stop message. The script prints each message with
its time, and the time from the stop until the server says done.
Usage: try_wav.py <16 kHz mono 16-bit WAV> [--url URL] [--working] [--model NAME] [--language ru]
                  [--hint KEY=VALUE]... [--snapshot FILE] [--options JSON] [--prompt TEXT] [--fast]
It goes to the test dictation server (server/test_server.sh, constants.TEST_URL) unless --url says otherwise. The working
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

import constants



async def main():
    p = argparse.ArgumentParser()
    p.add_argument("wav")
    p.add_argument("--url", default=constants.TEST_URL, help=f"the dictation server (default the test one, {constants.TEST_URL})")
    p.add_argument("--working", action="store_true", help=f"allow the working server ({constants.WORKING_URL})")
    p.add_argument("--language", default="ru")
    p.add_argument("--model", help="a model of the registry (default: the server's first)")
    p.add_argument("--hint", action="append", default=[], metavar="KEY=VALUE",
                   help="a hint for the adapters, sent in the start message's hints; VALUE is JSON, or else text "
                        "(e.g. sessions='[\"<id>\"]' for an adapter that reads named sessions)")
    p.add_argument("--snapshot", help="a focus snapshot (macos echofox-snapshot), for the chat context")
    p.add_argument("--options", type=json.loads, help='the start message\'s options, e.g. \'{"cutWhileSpeaking": false}\'')
    p.add_argument("--prompt", help="the start message's own prompt, instead of the model's")
    p.add_argument("--fast", action="store_true", help="send without waiting between chunks")
    args = p.parse_args()
    hints = {}
    for h in args.hint:
        key, sep, value = h.partition("=")
        if not sep or not key:
            p.error(f"--hint {h!r}: write KEY=VALUE")
        try:
            hints[key] = json.loads(value)
        except ValueError:
            hints[key] = value
    if urllib.parse.urlparse(args.url).port == constants.WORKING_PORT and not args.working:
        p.error(f"{args.url} is the working dictation server; use the test one (server/test_server.sh start) or add --working")
    with wave.open(args.wav) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, constants.SAMPLE_BYTES, constants.RATE), \
            f"need {constants.RATE} Hz mono 16-bit"
        pcm = w.readframes(w.getnframes())
    t0 = time.monotonic()
    texts, stop, done = [], None, None
    try:
        ws = await connect(args.url, max_size=None)
    except OSError as e:
        raise SystemExit(f"cannot reach {args.url} ({e}); for the test server: server/test_server.sh start")
    async with ws:
        await ws.send(json.dumps({"type": "start", "language": args.language, "sampleRate": constants.RATE,
                                  "encoding": constants.ENCODING, "client": "try_wav", "hints": hints,
                                  **({"model": args.model} if args.model else {}),
                                  **({"options": args.options} if args.options else {}),
                                  **({"prompt": args.prompt} if args.prompt else {}),
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
