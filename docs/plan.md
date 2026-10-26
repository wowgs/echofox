# Plan

The work that is left, without promised dates; reviewed on 2026-10-26. The [reference](README.md) describes what works now. Structural fixes of the code are listed apart, in [refactoring](refactoring.md). Related: [requirements](requirements.md), [design](design.md).

## Measurable quality first

| Task | Why | Next step |
|---|---|---|
| A labeled test set | Without a reference, no change can be shown to improve recognition. | Prepare about 50 recordings and fix the comparison rules. |
| Q4_0 against Q8_0 | Choose between memory, waiting and errors. | Run one set on both variants; one run is not a comparison. |
| Sampling | Unstable text, transliteration and punctuation. | Compare the current settings with a low temperature and greedy decoding on the same recordings. |
| Context and terms | Separate the gain from false copying of words. | Compare without context, with context, and with extra terms. |
| Rules of clean text | Consistent labels. | Decide when to keep "ну", "типа", "вот", and how to treat repeats and self-corrections. |

## Releases

v0.1 is out. Before v0.2, the release blockers of the 2026-10-26 review are being fixed: the oldest macOS the bundle runs on, the server agent's path and its restart on update, the first launch on the main thread, bytecode written into the signed bundle, a silent ad hoc signature in CI, and a double model download. Before a public release, the checks in [distribution](distribution.md#check-before-a-public-release). Open decisions: opening the repository, updates through Sparkle.

## Next features

| Feature | State |
|---|---|
| Adapters for Codex, ChatGPT, Antigravity, Gemini, Telegram Web | Planned; each needs a reliable way to find the current conversation. |
| Dictation history | Proposed; storage, recovery of the text and the privacy settings are open. |
| Recording indicator (a fox over the window) | A prototype of the transparent rendering exists; no character or indicator yet. A text preview is put off. |
| Automatic fine-tuning (LoRA) on the user's labels | Planned; needs a checked set and a first short experiment. See [training](research/training.md). |
| Faster labeling | Proposals: short series and choosing doubtful pieces, in [training](research/training.md#easier-labeling). |
| A plugin catalog and install from GitHub | Install from a folder works. Plugins in other languages only on a real need. |

## Experiments without a chosen answer

- Unloading the model on idle: free memory against the delay of the next dictation.
- Other quantizations and the MLX engine: compatibility, speed and errors.
- Speculative decoding E2B → E4B and MTP: first check that the engine version supports audio with it.
- Long tails of a recording: does one more cut help the latency and transliteration?
- A term dictionary, including rare Russian words: see [terms](research/terms.md).
- The WH-1000XM4 microphone and clipping: repeat the observation at 76% volume with a level check.

Priorities change after measurements.
