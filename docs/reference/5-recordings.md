# The recordings and labels

The server keeps each recording, so that you can listen to it, label it and later train the model on your own voice ([LoRA training](../lora-training/1-idea.md)). It never deletes a recording. A private dictation is never saved. To stop saving, turn off Save recordings in the settings window (`"saveRecordings": false` in the section `server` of [the config file](2-config.md)).

Related docs: [the dictation server](1-server.md), [the menu bar app](4-app.md).

## The folder of a recording

Each recording gets the folder `~/speech/recordings/<YYYY-MM-DD>/<HHMMSS>-<id>/`. The setting `recordings` sets another root.

| File | What it holds |
|---|---|
| `mic.wav` | The whole recording as the app sent it: 16 kHz, 16-bit, mono. |
| `piece-N.wav` | The audio of each piece as the model got it. |
| `pieces.jsonl` | The text of each piece, its tokens, its seconds of speech, and the model's own text before the hesitation sounds went out (`raw`). |
| `text-before-audio.txt` | The chat context and the prompt that the model got before the audio. |
| `adapter.json` | The model, the client, the reason of the stop, the errors, the texts, the chat context (which adapter, what it read), and the input volume and device of the Mac at the start. |
| `audio.json` | The levels: the loudness of speech and noise, the peak, clipped samples, digital silence. |

The recordings take about 231 MB for each hour of speech (365 recordings, 2026-10-22 to 2026-10-25). The audio is there twice: once in `mic.wav` and once in the pieces.

With the Claude adapter, `adapter.json` names the Claude Code session and its transcript. The text that you correct and send is your next message in that transcript. `~/speech/tools/link_corrections.py` writes it to `correction.json` in the folder of the recording.

## The labels

Label Recordings… in the menu writes each labeled piece to `~/speech/labeled/<day>/<id>/piece-N/`. The setting `labeled` sets another folder. The labels are apart from the recordings, so that a piece stays whole when you delete recordings.

| File | What it holds |
|---|---|
| `audio.wav` | A copy of the audio of the piece. |
| `text-before-audio.txt` | A copy of the context and the prompt. |
| `label.json` | Your text, the text of the model and its text before the hesitation sounds went out, the status (`verified` or `unusable`), the model, the language and the time. `"convention": "clean"` says that the text has no hesitation sounds and no repeated words. |
