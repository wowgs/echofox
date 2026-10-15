"""Every recording is kept, never deleted by local-voice:
  <root>/<YYYY-MM-DD>/<HHMMSS>-<id>/mic.wav       the whole recording as the client sent it (16 kHz, 16-bit, mono),
                                                  before any cutting
  <root>/<YYYY-MM-DD>/<HHMMSS>-<id>/adapter.json  the model, the language, the client, the stop reason, the errors,
                                                  each piece's text and the whole text, the context
                                                  (adapter, what it read, its details), and the Mac's input
                                                  volume and input device at the start
The recording also gets each piece's audio, the text before the audio, each piece's text (pieces.jsonl) and the
levels (audio.json), all through Recording.save. ~/speech/tools/link_corrections.py reads chat.details (session,
file) and "text" of adapter.json.
16 kHz 16-bit mono is 32 KB per second, about 115 MB per hour of speech.
"""
import contextlib
import datetime
import json
import logging
import os
import subprocess

from audio import seconds, wav_header
from constants import RATE, SAMPLE_BYTES

HEADER_EVERY_BYTES = 5 * RATE * SAMPLE_BYTES  # the WAV header is brought up to date every 5 s of audio
log = logging.getLogger("gemma_voice")


class Recording:
    """A new recording folder: `id` ("YYYY-MM-DD/HHMMSS-xxxxxx", relative to the root; the metrics name the
    recording by it too), `dir`; write(pcm) appends audio, save(name, data) writes any other file of the recording,
    finish(info) closes it. A file that cannot be written is logged and given up; the dictation goes on."""

    def __init__(self, root, now=None):
        now = now or datetime.datetime.now()
        self.started = now
        self.id = f"{now:%Y-%m-%d}/{now:%H%M%S}-{os.urandom(3).hex()}"
        self.dir = os.path.join(root, *self.id.split("/"))
        os.makedirs(self.dir, exist_ok=True)
        self.wav = open(os.path.join(self.dir, "mic.wav"), "wb")
        self.wav.write(wav_header(0))
        self.bytes, self.header_at = 0, 0

    def write(self, pcm):
        if not self.wav:
            return
        try:
            self.wav.write(pcm)
            self.bytes += len(pcm)
            if self.bytes - self.header_at >= HEADER_EVERY_BYTES:  # a server that dies leaves a playable file
                self._header()
        except (OSError, ValueError):  # a full disk, a file that went away
            log.exception("cannot write the audio of recording %s; it is not saved from here on", self.id)
            self._close_wav()

    def _header(self):
        pos = self.wav.tell()
        self.wav.seek(0)
        self.wav.write(wav_header(self.bytes))
        self.wav.seek(pos)
        self.header_at = self.bytes

    def _close_wav(self):
        with contextlib.suppress(OSError, ValueError):
            self._header()
        with contextlib.suppress(OSError, ValueError):
            self.wav.close()
        self.wav = None

    def save(self, name, data, append=False):
        """Writes (or appends to) one more file of the recording: bytes, or an object as JSON."""
        if not isinstance(data, (bytes, bytearray)):
            data = (json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        try:
            with open(os.path.join(self.dir, name), "ab" if append else "wb") as f:
                f.write(data)
        except OSError:
            log.exception("cannot save %s of recording %s", name, self.id)

    def finish(self, info):
        if self.wav:
            self._close_wav()
        self.save("adapter.json", {"id": self.id, "started": self.started.astimezone().isoformat(),
                                   "audioSeconds": seconds(self.bytes), **info})


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
