"""The files of a recording: Folder writes every file of a recording's folder, and no other module writes there.
Every recording is kept, never deleted by echofox:
  <root>/<YYYY-MM-DD>/<HHMMSS>-<id>/mic.wav       the whole recording as the client sent it (16 kHz, 16-bit, mono),
                                                  before any cutting (Folder.audio)
  <root>/<YYYY-MM-DD>/<HHMMSS>-<id>/audio.json    its levels (Folder.levels, audio.Levels.report)
  <root>/<YYYY-MM-DD>/<HHMMSS>-<id>/text-before-audio.txt  the text the model read before each piece's audio: the
                                                  context, then the prompt (Folder.text_before_audio)
  <root>/<YYYY-MM-DD>/<HHMMSS>-<id>/piece-N.wav   the audio of piece N (Folder.piece)
  <root>/<YYYY-MM-DD>/<HHMMSS>-<id>/pieces.jsonl  one line for each piece: its audio, speech, text and timings
  <root>/<YYYY-MM-DD>/<HHMMSS>-<id>/adapter.json  the record of the whole recording (Folder.finish): the model, the
                                                  language, the client, the stop reason, the errors, each piece's
                                                  text and the whole text, the identity of the focused app, the
                                                  matched surfaces (not what the app read for them), the context
                                                  (adapter, what it read, its details), and the Mac's input volume and
                                                  input device at the start
~/speech/tools/link_corrections.py reads chat.details (session, file) and "text" of adapter.json.
16 kHz 16-bit mono is 32 KB per second, about 115 MB per hour of speech.
"""
import contextlib
import datetime
import json
import logging
import os

from audio import seconds, wav, wav_header
from constants import RATE, SAMPLE_BYTES

HEADER_EVERY_BYTES = 5 * RATE * SAMPLE_BYTES  # the WAV header is brought up to date every 5 s of audio
log = logging.getLogger("echofox-server")


def start(root, save=True, now=None):
    """The files of a new recording: a Folder under `root`, or Unsaved when the recording is not saved (`save` off: a
    private dictation, or the setting saveRecordings) or its folder cannot be made."""
    now = now or datetime.datetime.now()
    if save:
        try:
            return Folder(root, now)
        except OSError:
            log.exception("cannot start the recording folder")
    return Unsaved(now)


class Folder:
    """A new recording folder: `id` ("YYYY-MM-DD/HHMMSS-xxxxxx", relative to the root; the metrics name the
    recording by it too), `dir`. Each file of the recording has its own call; finish(record) closes it. A file that
    cannot be written is logged and given up; the dictation goes on."""
    saved = True

    def __init__(self, root, now=None):
        now = now or datetime.datetime.now()
        self.started = now
        self.id = f"{now:%Y-%m-%d}/{now:%H%M%S}-{os.urandom(3).hex()}"
        self.dir = os.path.join(root, *self.id.split("/"))
        os.makedirs(self.dir, exist_ok=True)
        self.wav = open(os.path.join(self.dir, "mic.wav"), "wb")
        self.wav.write(wav_header(0))
        self.bytes, self.header_at = 0, 0

    def audio(self, pcm):
        """Appends the client's audio to mic.wav."""
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

    def levels(self, report):
        self._save("audio.json", report)

    def text_before_audio(self, text):
        self._save("text-before-audio.txt", text.encode("utf-8"))

    def piece(self, pcm, line):
        """A piece's audio, and its line of pieces.jsonl (`line["piece"]` is its number)."""
        self._save(f"piece-{line['piece']}.wav", wav(pcm))
        self._save("pieces.jsonl", (json.dumps(line, ensure_ascii=False) + "\n").encode("utf-8"), append=True)

    def finish(self, record):
        """Closes mic.wav and writes the record of the whole recording."""
        if self.wav:
            self._close_wav()
        self._save("adapter.json", {"id": self.id, "started": self.started.astimezone().isoformat(),
                                    "audioSeconds": seconds(self.bytes), **record})

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

    def _save(self, name, data, append=False):
        """Writes (or appends to) one file of the recording: bytes, or an object as JSON."""
        if not isinstance(data, (bytes, bytearray)):
            data = (json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        try:
            with open(os.path.join(self.dir, name), "ab" if append else "wb") as f:
                f.write(data)
        except OSError:
            log.exception("cannot save %s of recording %s", name, self.id)


class Unsaved:
    """A recording that is not saved: Folder's calls, which write nothing. Its `id` names it in the log and the
    metrics."""
    saved = False

    def __init__(self, now=None):
        now = now or datetime.datetime.now()
        self.id = f"{now:%Y-%m-%d}/{now:%H%M%S}-unsaved"

    def audio(self, pcm):
        pass

    def levels(self, report):
        pass

    def text_before_audio(self, text):
        pass

    def piece(self, pcm, line):
        pass

    def finish(self, record):
        pass
