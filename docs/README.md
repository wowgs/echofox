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

The reference pages describe the current implementation. The pages below explain why it is built this way and what comes next.

## Decisions and plans

- [Design](design.md): who EchoFox is for, the decisions, the architecture, who owns each setting, the interface and the adapters.
- [Requirements](requirements.md): the target behavior, with stable FR and NFR numbers.
- [Observations](observations.md): dated measurements and observations behind the decisions.
- [Plan](plan.md): the work that is left.

## Research

Proposed work, not product features:

- [Training on your recordings](research/training.md): automatic fine-tuning (LoRA) on your own labels.
- [Term dictionary](research/terms.md): suggesting the conversation's terms to the model.

## Keeping these docs useful

Start each page with its purpose and implementation status. Explain the user outcome before the mechanism. Put a useful diagram near the top of an overview; keep exact fields and commands in the reference pages.

Use natural, plain language. Keep technical names when they are needed to configure or build something, and explain them on first use. Record measurements with their date and conditions; label estimates and proposals explicitly. Link to the page that owns a fact instead of repeating a table or implementation plan.

This approach follows [GOV.UK guidance on clear language](https://guidance.publishing.service.gov.uk/writing-to-gov-uk-standards/writing-guidelines/clear-language/) and [Nielsen Norman Group's guidance on communicating purpose](https://www.nngroup.com/articles/homepage-design-principles/). Product descriptions should state useful, supported benefits without promising unmeasured improvements.
