"""Every recording is kept, never deleted by local-voice:
  <root>/<YYYY-MM-DD>/<HHMMSS>-<id>/mic.wav       the whole recording as the client sent it (16 kHz, 16-bit, mono),
                                                  before any cutting
  <root>/<YYYY-MM-DD>/<HHMMSS>-<id>/adapter.json  the model, the language, the client, the stop reason, the errors,
                                                  each piece's text and the whole text, the context
                                                  (adapter, what it read, its details), and the Mac's input
                                                  volume and input device at the start
gemma_voice.py also writes each piece's audio, the text before the audio, each piece's text (pieces.jsonl) and the
levels (audio.json) into the folder. ~/speech/tools/link_corrections.py reads chat.details (session, file) and "text" of adapter.json.
16 kHz 16-bit mono is 32 KB per second, about 115 MB per hour of speech.
"""
import datetime
import json
import os
import struct
import subprocess

RATE = 16000


def header(data_bytes):
    return (b"RIFF" + struct.pack("<I", 36 + data_bytes) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 1, 1, RATE, RATE * 2, 2, 16) + b"data" + struct.pack("<I", data_bytes))


class Recording:
    """A new recording folder: `id` ("YYYY-MM-DD/HHMMSS-xxxxxx", relative to the root), `dir`, write(pcm),
    finish(info)."""

    def __init__(self, root, now=None):
        now = now or datetime.datetime.now()
        self.started = now
        self.id = f"{now:%Y-%m-%d}/{now:%H%M%S}-{os.urandom(3).hex()}"
        self.dir = os.path.join(root, *self.id.split("/"))
        os.makedirs(self.dir, exist_ok=True)
        self.wav = open(os.path.join(self.dir, "mic.wav"), "wb")
        self.wav.write(header(0))
        self.bytes = 0

    def write(self, pcm):
        if self.wav:
            self.wav.write(pcm)
            self.bytes += len(pcm)

    def finish(self, info):
        if not self.wav:
            return
        self.wav.seek(0)
        self.wav.write(header(self.bytes))
        self.wav.close()
        self.wav = None
        with open(os.path.join(self.dir, "adapter.json"), "w", encoding="utf-8") as f:
            json.dump({"id": self.id, "started": self.started.astimezone().isoformat(),
                       "audioSeconds": self.bytes / 2 / RATE, **info}, f, ensure_ascii=False, indent=2)
            f.write("\n")


def _run(cmd, timeout):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def input_info():
    """The Mac's microphone settings now: {"inputVolume": 0..100 or None, "device": {...} or None}. The input volume
    (System Settings, Sound, Input) moves speech and room noise up or down together."""
    volume = _run(["osascript", "-e", "input volume of (get volume settings)"], 5)
    profile = _run(["system_profiler", "SPAudioDataType", "-json"], 10)
    device = None
    try:
        items = json.loads(profile)["SPAudioDataType"][0].get("_items") or []
        d = next((i for i in items if i.get("coreaudio_default_audio_input_device") == "spaudio_yes"), None)
        if d:
            device = {"name": d.get("_name"), "sampleRate": d.get("coreaudio_device_srate"),
                      "inputChannels": d.get("coreaudio_device_input"),
                      "transport": str(d.get("coreaudio_device_transport") or "").replace("coreaudio_device_type_", ""),
                      "manufacturer": d.get("coreaudio_device_manufacturer")}
    except (TypeError, ValueError, KeyError, IndexError):
        pass
    try:
        volume = float(volume)
        volume = int(volume) if volume.is_integer() else volume
    except (TypeError, ValueError):
        volume = None
    return {"inputVolume": volume, "device": device}
