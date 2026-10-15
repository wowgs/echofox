"""Sends a WAV file to the dictation server the way a client does, and prints what comes back.

The audio goes in 100 ms chunks at real-time speed, then the stop message. The script prints each message with
its time, and the time from the stop until the server says done.
Usage: try_wav.py <16 kHz mono 16-bit WAV> [--url ws://127.0.0.1:8090] [--model NAME] [--language ru]
                  [--session ID]... [--app BUNDLE_ID] [--fast]
"""
import argparse
import asyncio
import json
import time
import wave

from websockets.asyncio.client import connect


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("wav")
    p.add_argument("--url", default="ws://127.0.0.1:8090")
    p.add_argument("--language", default="ru")
    p.add_argument("--model", help="a model of the registry (default: the server's first)")
    p.add_argument("--session", action="append", default=[], help="a Claude Code session id for the chat context")
    p.add_argument("--app", help="the bundle id of the app with the input box, for the chat context")
    p.add_argument("--fast", action="store_true", help="send without waiting between chunks")
    args = p.parse_args()
    with wave.open(args.wav) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000), "need 16 kHz mono 16-bit"
        pcm = w.readframes(w.getnframes())
    t0 = time.monotonic()
    texts, stop, done = [], None, None
    async with connect(args.url, max_size=None) as ws:
        await ws.send(json.dumps({"type": "start", "language": args.language, "sampleRate": 16000,
                                  "encoding": "pcm_s16le", "client": "try_wav", "sessions": args.session,
                                  **({"model": args.model} if args.model else {}), **({"app": args.app} if args.app else {})}))

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
