# Requirements

The target behavior of EchoFox. It is not a list of shipped features: the [reference](README.md) describes what works now, and the [plan](plan.md) lists what is left. The FR and NFR numbers stay stable for links. "Planned" means decided and not built; "proposed" means not decided yet. Related: [design](design.md).

## Dictation

- **FR-1. Dictation into the text box.** A key starts and stops the recording. The text goes into the current text box, else into the box of the start; if neither takes it, into the clipboard.
- **FR-2. Private dictation.** A key of its own. The app finds the text box but sends no context snapshot. No adapter runs; the audio and the text are not saved, and the text is not logged.
- **FR-3. Recognition while you speak.** Finished pieces are recognized before the stop, so that less is left to wait for.
- **FR-4. No invented text.** Pieces without speech do not go to the model. An answer that reaches the length limit is dropped.

## Context

- **FR-5. Optional adapters.** An adapter finds the current conversation and prepares its context. Without a matching enabled adapter, the dictation runs without context.
- **FR-6. Adapters in the settings.** The settings show the adapters, their state, their sources and their context settings. The user's values replace the defaults of the adapter's manifest.

## Model

- **FR-7. Local recognition.** The chosen model of the catalog runs on the Mac.
- **FR-8. Install from the app.** The server comes with the app. The model is downloaded with its progress, speed and time left. A variant that is not needed can be removed.
- **FR-9. Recognition settings.** The model, the prompt, the language and the recording limit are shown at once; sampling and context budgets under Advanced. Protective thresholds and the cutting stay constants.

## Interface

- **FR-10. A short menu.** The permissions while one is missing, the microphone and its volume, labeling, settings, quit. The icon shows the state.
- **FR-11. A settings window** with the other settings on pages.
- **FR-12. Keys** of their own for regular and private dictation, changeable.
- **FR-13. Permissions.** A missing permission opens its page in macOS; a granted one shows a gray check. The line disappears when all are granted.
- **FR-14. Recording indicator, planned.** A transparent animated character over the window of the dictation; the menu bar icon stays.
- **FR-15. First start, proposed.** Explain and ask for the permissions one by one, check the server and the model. The window that downloads the model exists.

## Recordings and data

- **FR-16. Saved recordings.** A regular dictation saves the audio, the text and the context used. Saving can be turned off; a private dictation is never saved. Showing the space used is proposed.
- **FR-17. Labeling.** Unlabeled pieces come in random order. The reference is the text the user meant to write, without hesitations and repeats.
- **FR-18. Fine-tuning, planned.** Automatic fine-tuning on the user's labeled recordings, on their Mac; see [training](research/training.md).
- **FR-19. History, proposed.** The latest results, to copy and insert again. Private dictations never appear in it; the behavior with saving turned off is open.

## System

- **FR-20. Diagnostics.** The server's state, the chosen model and the errors.
- **FR-21. Updates, planned.** Update the app, the server and the catalog without a terminal, through Sparkle.

## Non-functional

- **NFR-1. Privacy.** The audio and the text are processed on the Mac.
- **NFR-2. No terminal.** Installing and using the public version needs no terminal.
- **NFR-3. Extensible adapters.** A new plugin needs no vendor logic in the core.
- **NFR-4. A minimal snapshot.** The focus metadata has no values of text boxes and no terminal buffer. Screen content is taken only for enabled adapters that ask for it in their manifest. A config migration never enables such an adapter.
- **NFR-5. One source for a setting.** The owner defines a setting and its default, and the user's change is stored at the owner. Order: an experiment's option, the user's change, the default. New server settings appear in the interface from the server's description.
- **NFR-6. Latency, proposed.** Shorten the wait after the stop; the number is chosen after measurements on the supported models.
- **NFR-7. Memory.** One model runs at a time. Unloading on idle is open.
- **NFR-8. Focus, proposed.** The recording and the indicator do not get in the way. The return to the box of the start can bring its app to the front.
- **NFR-9. Recovering a result, proposed.** If the insertion fails, the text can be copied. Private results are never kept for this.
- **NFR-10. Data volume, proposed.** Keep only what review and training need. Explain that recordings contain the conversation's context and can be in backups.
- **NFR-11. Trust.** Readable source code, signing and notarization; network access only for features that say so.
- **NFR-12. One way to set a value.** A switch is its own field, not a special value of a budget. `--config` chooses the file and adds no second set of settings.
- **NFR-13. Clear labels.** A setting's title says what changes. Short help only when the title is not enough. The default shows in the field, the allowed range in the error. Natural English that needs no knowledge of the code.
- **NFR-14. No telemetry.** The app and the bundled parts send no analytics, metrics or identifiers. The only network access is the requested model download. An update mechanism must be described and checked before it ships.

## Open questions

- Which proposals go into the first public version?
- Unload the model on idle?
- Which Macs and macOS versions are checked before a release?
