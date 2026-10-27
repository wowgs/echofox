# Term dictionary

A research idea: suggest to the model the names, titles and technical words that are likely in the current conversation. **An automatic dictionary is not built.** Now the server takes terms from the adapter's context by simple rules; see the [context reference](../reference/3-context.md#what-the-model-gets). Related: [plan](../plan.md), [training](training.md).

A dictionary differs from [training](training.md): it gives a hint at recognition time and changes no weights. It fits words that change between projects and conversations. The gain of the current term list for Gemma is not measured; measure it before making the selection smarter.

## Proposed path (2026-10-14)

1. After a finished turn, an adapter reads that turn's transcript.
2. A language model picks the terms from the messages and the code.
3. The adapter updates a local base: spellings, frequency and source.
4. Before a dictation, a short list that fits the conversation is chosen from the base.

The base keeps everything useful; only a small selection goes into the prompt. A possible signal is the frequency over the last hour, the last few turns or a number of tokens; the window is not chosen. A cloud model for the dictionary would break the promise of local processing, so it is not an option without a separate decision.

## What to check first

The same recordings in three conditions:

- without a term list;
- with the right terms, known in advance (the possible gain);
- with the right terms and extra words (robustness).

Count both the errors in names and the false insertions of listed words: the model has already copied context into the recognized text, and better terms must not hide that.

## Reading

[BR-ASR](https://arxiv.org/abs/2505.19179) studies choosing fitting words from a large base for contextual recognition; it is a reason to test a separate selection step, but its results do not carry over to Gemma. Earlier reading, to check before using any number from it: [Whisper: Courtside Edition](https://arxiv.org/html/2602.18966v1), [How to Recognize New Words](https://arxiv.org/html/2608.05759), [Contextual Biasing with Hotword Retrieval and RL](https://arxiv.org/abs/2512.21828).

## Open questions

- Does a list give a measurable gain on our set?
- How to find rare Russian words written in lower case?
- Which local model can keep the dictionary, at what cost?
- Which window and which list budget?
- How to use the project and the user's corrections in the selection?
- What to keep about a term's source, and how to show it to the user?
