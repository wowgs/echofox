# Plan

The work that is left, without promised dates; reviewed on 2026-10-26. The [reference](README.md) describes what works now. Related: [requirements](requirements.md), [design](design.md).

## Measurable quality first

| Task | Why | Next step |
|---|---|---|
| A labeled test set | Without a reference, no change can be shown to improve recognition. | Prepare about 50 recordings and fix the comparison rules. |
| Q4_0 against Q8_0 | Choose between memory, waiting and errors. | Run one set on both variants; one run is not a comparison. |
| Sampling | Unstable text, transliteration and punctuation. | Compare the current settings with a low temperature and greedy decoding on the same recordings. |
| Context and terms | Separate the gain from false copying of words. | Compare without context, with context, and with extra terms. |
| Rules of clean text | Consistent labels. | Decide when to keep "ну", "типа", "вот", and how to treat repeats and self-corrections. |

## Releases

v0.4.0 (2026-10-26) is the first release with updates through Sparkle; v0.3.x carried the structural fixes and the clean install, and the author's own dictation runs on the release since v0.3. Next:

- Try an update from v0.4.0 to the next release on the author's Mac, with a local feed while the repository is private ([updates](reference/7-development.md#updates)). Not tried yet on the live app: the update window, the install, the restart of the app and the server.
- Open the repository. Its releases and its update feed are not public before that: GitHub answers 404 to a download without a login.

Before the repository opens:

- Installation, permissions, the launchd agents and a restart on a clean Mac.
- A full model download from the source, and its recovery after a break.
- The oldest supported macOS: everything is built for 26, but the app has run only on 27.
- The terms of use and distribution of the Gemma model.
- Quality, speed and memory of Q4_0 against Q8_0 on one labeled set.

## Next features

| Feature | State |
|---|---|
| Adapters for Codex, ChatGPT, Antigravity, Gemini, Telegram Web | Planned; each needs a reliable way to find the current conversation. |
| Dictation history | Proposed; storage, recovery of the text and the privacy settings are open. |
| Recording indicator (a fox over the window) | A prototype of the transparent rendering exists; no character or indicator yet. A text preview is put off. |
| Automatic fine-tuning (LoRA) on the user's labels | Planned; needs a checked set and a first short experiment. See [training](research/training.md). |
| Faster labeling | Proposals: short series and choosing doubtful pieces, in [training](research/training.md#easier-labeling). |
| A plugin catalog and install from GitHub | Install from a folder works. Plugins in other languages only on a real need. |
| Update reminders | The menu's first line says that an update is ready. Proposed: a mark on the menu bar fox (approved art, needs a drawing) and release notes in the update window (a signed feed needs them signed too). |
| Claude Code sessions named by the client | The Claude plugin takes the sessions a client names in `hints`. No client sends them now; only `try_wav.py --hint` reaches this path. Open: keep it for a future client, or remove it. |

## Experiments without a chosen answer

- Unloading the model on idle: free memory against the delay of the next dictation.
- Other quantizations and the MLX engine: compatibility, speed and errors.
- Speculative decoding E2B → E4B and MTP: first check that the engine version supports audio with it.
- Long tails of a recording: does one more cut help the latency and transliteration?
- A term dictionary, including rare Russian words: see [terms](research/terms.md).
- The WH-1000XM4 microphone and clipping: repeat the observation at 76% volume with a level check.

Priorities change after measurements.
