"""The dictation server's metrics: written here (metric()), one JSON object per line, and summarised by this file run
as a script. "event" is "prepare" (the text before the audio), "piece" (one model request: tokens, speeds, times,
llama-server's memory), "cancelled", "audio" (a recording's levels) or "recording" (one connection: the model, the
client, the audio, the stop reason, the wait after the stop).

Usage: server/.venv/bin/python server/metrics.py [--since 2026-10-14T05:00] [--last N] [file]
Prints, per model: requests, audio, wall time per second of audio, prefill and decode tokens and speeds, time to
the first token, the wait after the stop, and llama-server's memory. Then the last N pieces, one line each.
"""
import argparse
import json
import logging
import os
import statistics
import time

import constants

log = logging.getLogger("gemma_voice")
_path = constants.path(constants.METRICS)


def configure(path):
    """Where metric() writes from now on (the server's setting "metrics"); returns where it wrote before."""
    global _path
    before, _path = _path, constants.path(path)
    return before


def metric(event, **fields):
    try:
        os.makedirs(os.path.dirname(_path), exist_ok=True)
        with open(_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event, **fields},
                               ensure_ascii=False) + "\n")
    except OSError:
        log.exception("cannot write the metrics")  # metrics never stop a transcription


def med(xs):
    xs = [x for x in xs if x is not None]
    return f"{statistics.median(xs):.2f}" if xs else "-"


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("file", nargs="?", default=_path)
    p.add_argument("--since", default="", help="only lines at or after this time, as in the file (2026-10-14T05:00)")
    p.add_argument("--last", type=int, default=10, help="how many recent pieces to list (default 10)")
    a = p.parse_args()
    rows = [json.loads(l) for l in open(a.file, encoding="utf-8") if l.strip()]
    rows = [r for r in rows if r["time"] >= a.since]
    pieces = [r for r in rows if r["event"] == "piece"]
    recordings = [r for r in rows if r["event"] == "recording"]
    print(f"{'model':<12} {'pieces':>6} {'audio s':>8} {'wall/audio':>10} {'prefill tok':>11} {'prefill t/s':>11} "
          f"{'decode tok':>10} {'decode t/s':>10} {'ttft s':>7} {'wait s':>7} {'memory MB':>9}")
    for m in sorted({r["model"] for r in pieces}):
        ps = [r for r in pieces if r["model"] == m]
        waits = [r.get("done_after_stop_seconds") for r in recordings if r["model"] == m]
        print(f"{m:<12} {len(ps):>6} {sum(r['audio_seconds'] for r in ps):>8.1f} "
              f"{med([r['wall_seconds'] / r['audio_seconds'] for r in ps if r['audio_seconds']]):>10} "
              f"{med([r.get('prefill_tokens') for r in ps]):>11} {med([max(r.get('prefill_tps') or [0]) for r in ps]):>11} "
              f"{med([r.get('decode_tokens') for r in ps]):>10} {med([max(r.get('decode_tps') or [0]) for r in ps]):>10} "
              f"{med([r.get('ttft_seconds') for r in ps]):>7} {med(waits):>7} "
              f"{max((r.get('llama_footprint_mb') or 0) for r in ps):>9}")
    print("(medians; memory: llama-server's physical footprint, the highest seen)\n")
    for r in pieces[-a.last:]:
        print(f"{r['time']} {r['model']:<10} {r['audio_seconds']:>5.1f} s audio, {r['wall_seconds']:>5.2f} s, "
              f"prefill {r.get('prefill_tokens')} ({r.get('cached_tokens')} cached), decode {r.get('decode_tokens')}, "
              f"ttft {r.get('ttft_seconds')} s, {r.get('llama_footprint_mb')} MB, prompt {r.get('prompt')} {r.get('prompt_chars')} chars")


if __name__ == "__main__":
    main()
