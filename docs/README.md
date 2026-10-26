# EchoFox documentation

Choose a guide for the task you want to complete. For a visual introduction and installation options, start with the [project README](../README.md).

## Use and configure the app

| Task | Guide |
|---|---|
| Dictate, change keys, or review recordings | [Mac app guide](reference/4-app.md) |
| Edit settings directly | [Configuration](reference/2-config.md) |
| Understand what is saved and where | [Recordings and labels](reference/5-recordings.md) |
| Enable context or write an adapter | [Conversation context and adapters](reference/3-context.md) |

## Develop and troubleshoot

| Task | Guide |
|---|---|
| Follow audio through the server and model | [Speech processing](reference/1-server.md) |
| Build a client or inspect messages | [WebSocket protocol](reference/6-protocol.md) |
| Build from source, run checks, or test recognition | [Development guide](reference/7-development.md) |
| Deploy the Worker that finishes releases after Apple's check | [Notary relay](../ci/notary-relay/README.md) |

The reference pages describe the current implementation. Design and research pages below are in Russian and distinguish implemented behavior from proposals.

## Product decisions

- [Purpose and audience](design/1-what-and-why.md): the problem EchoFox solves and how to explain it.
- [Requirements](design/2-requirements.md): target behavior, including features not yet implemented.
- [Constraints](design/3-constraints.md): dated observations that influenced the design.
- [Architecture](design/4-hld.md): component responsibilities and data flow.
- [Interface](design/5-ui.md): menu, settings, and their implementation.
- [Distribution](design/7-distribution.md): packaging, downloads, and release checks.
- [Adapter decisions](adapters/1-idea.md): why adapters are optional and how the plugin boundary works.
- [Work plan](ideas.md): remaining tasks and experiments.

## Research and future features

These pages describe proposed work, not available product features:

- **Personal training:** [idea](lora-training/1-idea.md), [requirements](lora-training/2-requirements.md), and [implementation plan](lora-training/3-hld.md).
- **Term dictionary:** [question, experiment, and open decisions](dictation-terms/1-untitled.md).

## Keeping these docs useful

Start each page with its purpose and implementation status. Explain the user outcome before the mechanism. Put a useful diagram near the top of an overview; keep exact fields and commands in the reference pages.

Use natural, plain language. Keep technical names when they are needed to configure or build something, and explain them on first use. Record measurements with their date and conditions; label estimates and proposals explicitly. Link to the page that owns a fact instead of repeating a table or implementation plan.

This approach follows [GOV.UK guidance on clear language](https://guidance.publishing.service.gov.uk/writing-to-gov-uk-standards/writing-guidelines/clear-language/) and [Nielsen Norman Group's guidance on communicating purpose](https://www.nngroup.com/articles/homepage-design-principles/). Product descriptions should state useful, supported benefits without promising unmeasured improvements.
