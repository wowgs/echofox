# Training on your recordings

Planned: automatic fine-tuning of the model on the user's own labels, on their Mac. **Nothing of the training is built yet.** The app saves recordings and has the labeling window; the rest of this page is a proposal. Related: [requirements](../requirements.md) (FR-18), [recordings and labels](../reference/5-recordings.md), [plan](../plan.md).

The goal is to check whether training helps with the user's own words, mixed speech and text without hesitations. An improvement counts only on recordings that were not used in the training.

## For the user

1. Regular dictations are saved, if the user keeps saving on.
2. In **Label Recordings…**, the user listens to pieces and corrects the text to what they meant to write.
3. The training runs on the Mac. Proposed: first a command for the developer, then a button with progress and a stop.
4. The user sees the comparison with the base model and can go back to it.

The audio, the texts and the trained weights stay on the Mac. Private dictations never become training data.

## What is trained

LoRA: small extra matrices on chosen layers of the model's language part. The base weights do not change, and the resulting file can be turned on and off. (A "LoRA adapter" is a file of trained weights, not a context [adapter](../design.md#adapters).)

A training example is the audio, the recognition prompt with its language notes, and the corrected text. The chat context is not part of it: it changes between conversations and is checked apart in the evaluation. The reference is clean text without hesitations and repeats; after a self-correction, the corrected wording stays (`"convention": "clean"` in the label).

## Requirements

- Only `verified` pieces with the `clean` convention; `unusable` ones are left out.
- The test set is split off by recording day, never overlaps the training set, and stays fixed between runs.
- The loss covers only the answer, not the prompt or the audio tokens.
- Only the language part is trained; the audio encoder and the projector are frozen.
- The base and the LoRA are compared in llama.cpp, on the same model and projector variant: word error rate against the clean reference, hesitations and repeats left, Russian speech and dictation with context apart.
- A LoRA is turned on only after a paired statistical comparison shows an improvement; the test and the threshold are chosen before the final comparison, after the noise is measured.
- The LoRA is exported to GGUF without changing the base weights, and turned on and off in the model's config.
- A learning curve: proposed points 15, 30, 60 and 120 minutes of labels.
- Each experiment keeps its example lists, settings, seed, versions, metrics, time and peak memory.
- On the Mac: hours, not days, as a target, measured first on the M5; checkpoints, so that a run can stop and resume; a clear pause of dictation if both do not fit in memory; an unknown or unsupported option is an error before the start.

## Proposed implementation

Labels → fixed train and test sets → LoRA in MLX → GGUF export → comparison in llama.cpp → turned on if better.

| Proposed part | Job |
|---|---|
| `lora/dataset.py` | Read `verified`/`clean` labels, split by day, write `train.jsonl` and `heldout.jsonl` with audio hashes. |
| `lora/train.py` | Train the LoRA and save checkpoints. |
| `lora/export.py` | Convert names and matrix layout for llama.cpp's converter, then make the GGUF. |
| `lora/eval.py` | Compare base and LoRA on the test server, count errors, run the paired comparison. |
| Model config and agent | Load a checked file with `--lora`, and go back to the base. |

A small layer of our own over a pinned mlx-vlm, in its own Python environment: load the model and the audio processor; LoRA on `q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj`; batch size 1 with gradient accumulation; the answer's boundary from the built template, not guessed; AdamW, a schedule, a seed. The choice of mlx-vlm is preliminary: its audio support and the export must be checked on the pinned version. A 2026-10-18 reading of mlx-tune found ignored options and problems in audio batching and the loss mask; that was an older version and was not reproduced.

## First experiment

- One example through MLX and the reference implementation: audio preparation, tokens, numbers.
- A short run of 20–50 steps: time, peak memory, and only the intended weights change.
- Export a small adapter and compare MLX with llama.cpp.
- The test set stays unchanged and does not overlap the training.

Only then the full set. Experiments use the [test server](../reference/7-development.md#test-recognition-on-a-separate-server), which pauses the working dictation while it runs. An early estimate of 50 minutes to 3 hours on the M5 for 167 minutes of data and three epochs assumed 30–70% of the forward pass's speed; it is not a measurement.

## Risks

| Risk | Check |
|---|---|
| Familiar cases get worse | Separate slices of the test set. |
| A porting or audio batching error | One example against the reference; a test that each audio matches its text. |
| Quality lost in export or another quantization | MLX against llama.cpp on the same examples. |
| Too few labels | The learning curve. |
| Not enough memory, or too slow | The short run before the full one. |

Research gives reasons to try, not proof for Gemma on our data: [Shor et al., 2019](https://arxiv.org/abs/1907.13511) on adapting recognition to atypical speech and accents; [Bannò et al., 2023](https://arxiv.org/abs/2311.05550) on cleaning spoken language, including removing disfluencies with Whisper.

## Easier labeling

Proposals, not the current app: offer a short series when the user is ready, not windows in the middle of work; confirm after listening, to avoid accidental clicks; pick doubtful pieces instead of random ones, if token probabilities turn out to be a useful signal. A message sent in a chat is not a correct label by itself: the user may have changed its meaning.

## Open questions

- Remove "ну", "типа", "вот"? Proposal: remove them as hesitations, keep them when they carry meaning, and be consistent.
- How well does training on a 4-bit base carry over to the working Q8_0?
- Which rank, learning rate and number of epochs?
- What improvement is enough to turn a LoRA on?
