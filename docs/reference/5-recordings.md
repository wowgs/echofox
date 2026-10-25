# Recordings and labels

**Regular dictations are saved by default.** They include audio, transcripts, and any conversation context sent to the model. Private dictation saves none of these files.

To stop saving future recordings, turn off **Save recordings** in Settings, or set `server.saveRecordings` to `false` in the [config file](2-config.md). Existing recordings are not deleted. EchoFox does not automatically remove old recordings.

See also: [review recordings in the app](4-app.md#label-recordings) and [the proposed training feature](../lora-training/1-idea.md).

## Recording files

Each saved recording has a folder at `~/speech/recordings/<YYYY-MM-DD>/<HHMMSS>-<id>/`. Change the root with `server.recordings`.

| File | Contents |
|---|---|
| `mic.wav` | The original recording: 16 kHz, 16-bit, mono. |
| `piece-N.wav` | The audio sent in each model request. |
| `pieces.jsonl` | The text of each piece, token counts, detected speech duration, and the raw text before hesitation removal (`raw`). |
| `text-before-audio.txt` | The conversation context and recognition prompt. |
| `adapter.json` | Model, client, stop reason, errors, transcripts, context source, and microphone settings. |
| `audio.json` | Audio levels: speech and noise loudness, peak level, clipping, and digital silence. |

The recordings take about 231 MB for each hour of speech (365 recordings, 2026-10-22 to 2026-10-25). The audio is there twice: once in `mic.wav` and once in the pieces.

## Labels

**Label Recordings…** saves reviewed pieces separately, under `~/speech/labeled/<day>/<id>/piece-N/`. Change this root with `server.labeled`. Because the audio is copied, a label remains usable after its original recording is deleted.

| File | Contents |
|---|---|
| `audio.wav` | A copy of the audio piece. |
| `text-before-audio.txt` | A copy of the context and prompt used for recognition. |
| `label.json` | Corrected and original text, raw model output, status (`verified` or `unusable`), model, language, and timestamp. |

`"convention": "clean"` means the reference text omits hesitation sounds and repeated words. Labels prepare data for future training; they do not change the running model.

The proposed training process uses audio, a recognition prompt, and the corrected text. Saved conversation context is retained for analysis but is not intended as training input.

## Developer correction tool

With the Claude adapter, `adapter.json` identifies the session transcript. The developer's external tool `~/speech/tools/link_corrections.py` can link the next user message to the recording as `correction.json`. This tool is outside this repository.

A sent message can contain edits to meaning, so it is not automatically a verified transcription label.
