"""The dictation server's metrics: metric() writes one JSON object per line (server/tools/metrics_summary.py
summarises them). "event" is "prepare" (the text before the audio), "warm" (the text before the audio into the cache
of a llama-server slot, before any audio), "piece" (one model request: tokens, speeds, times, llama-server's memory),
"piece_skipped" (a piece with too little speech, not sent to the model), "cancelled", "audio" (a recording's levels)
or "recording" (one connection: the model, the client, the audio, the stop reason, the wait after the stop).
"""
import json
import logging
import os
import time

import constants

log = logging.getLogger("echofox-server")
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
