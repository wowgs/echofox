# Conversation context and adapters

An adapter supplies recent conversation text to help the speech model recognize names and terms. Dictation also works without an adapter. If the conversation cannot be identified reliably, the server proceeds without context.

Private dictation never sends a context snapshot or runs an adapter.

See also: [configuration](2-config.md), [saved context](5-recordings.md), and [adapter design decisions](../design.md#adapters).

## How the server finds the conversation

1. At the start of a regular dictation, the app captures the focused app and input element. For an app that an enabled adapter supports, it also captures the window, the accessibility metadata above the input element, the web page, and the working folders of the app's child processes. Input-field values are excluded.
2. Enabled adapters inspect the snapshot and report whether they can handle it, with a confidence score.
3. The server asks the most confident adapter to retrieve the conversation.
4. If no adapter claims the snapshot or the conversation is ambiguous, recognition uses only the normal prompt.

The app collects additional screen content only for enabled adapters that request it. The server does not choose a conversation just because it is the newest session in an app.

## What the model gets

Context is placed before the recognition prompt, between `<context>` and `</context>`:

- A short description of where you are writing, such as “a Telegram chat with Anna”, with instructions not to repeat the context.
- Likely terms: first the names the adapter supplies, such as chat members, then Latin-script words and names in other alphabets, ranked by frequency. English speech gets no terms: every English word would be one.
- The files open beside the conversation, if the adapter gives them. They have a budget of their own. Each file is read from its start, in the adapter's order, until the budget ends; the last file can be cut.
- The newest messages that fit the adapter's budget, arranged from oldest to newest.

Adapters clean app-specific formatting first. The server then removes lines made mostly of digits and symbols, such as table rows. Terms from those lines can still appear in the term list.

## Adapter settings

Each adapter supplies defaults in its manifest. Override them in its config entry: `"adapters": {"telegram": {"enabled": true, "chatHistoryTokenBudget": 600}}`.

| Setting | What it sets | Claude | Telegram |
|---|---|---|---|
| `chatHistoryTokenBudget` | Total context budget in tokens; at least 1 | 1000 | 2000 |
| `chatTermsTokenBudget` | The largest part of the total budget that terms may use; the rest goes to messages | 200 | 200 |
| `chatDocumentsTokenBudget` | The budget of the open files, apart from the total budget | 1000 | 1000 |
| `proseOnly` | Exclude lines made mostly of digits and symbols, from the messages and the files | on | on |

Use `enabled` to turn an adapter on or off; both built-in adapters are off in a new config. Budgets use the selected model’s tokenizer.

## The built-in adapters

The built-in adapters are split by where their context comes from, not by the company or the app: one Claude app can be served by two of them. Each one is enabled, set up and failing on its own, and the client takes the screen data that only the enabled ones ask for (the outline of a Claude Desktop chat only for `claude-chat`). A manifest may give a `title` for people ("Claude Code"); without one the app shows the name.

| Adapter | Supported app | Context source |
|---|---|---|
| `claude-code` | Claude Code sessions: the Code tab of Claude Desktop, and a tab of Ghostty, Terminal, iTerm2 or Warp | The local transcript of the session in focus. Only Claude's completed responses are used. |
| `claude-chat` | Claude Desktop's chats (claude.ai) | The messages that the window shows, read from the outline of the page. Only Claude's replies are used. |
| `telegram` | Telegram Desktop | Messages loaded in the open chat, read from the accessibility snapshot. |

### Claude Code session matching (`claude-code`)

The Code tab exposes a URL of the form `https://claude.ai/epitaxy/local_<id>`. The adapter uses it to find a session record in `~/Library/Application Support/Claude/claude-code-sessions/`, which identifies the transcript.

If the record is missing, the adapter uses the web-area title only when exactly one transcript matches. This storage format is undocumented and may change.

User messages, tool calls, tool results, thinking, and system tags are excluded. Earlier user dictations were sometimes copied into new results, which is why the adapter uses only final assistant responses.

### Claude Code in a terminal (`claude-code`)

Claude Code in a tab of Ghostty, Terminal, iTerm2 or Warp gets the context of its session. Inside tmux or screen it gets none, for now: there the session is not found for sure.

- Each running `claude` writes `~/.claude/sessions/<pid>.json` with its `sessionId`, `name` (the session's title) and `entrypoint` (`cli` in a terminal). These files are Claude Code's own and not documented; they may change.
- The client's snapshot of a terminal has the focused window's title and the terminal's processes. The candidates are the `cli` sessions among those processes; a `claude` in tmux or screen belongs to the multiplexer's server, so it is never one.
- Claude Code sets the terminal's title to `✳ <name>`, and the terminals show it in the window's title (Terminal adds the folder, the command and the size). The session is the one candidate whose `name` the title contains; its transcript is `~/.claude/projects/*/<sessionId>.jsonl`. No candidate, or more than one: no claim.
- A new session before its first message has no transcript, and so no messages.

The measurements behind it are in [observations](../observations.md#target-apps-and-accessibility): the title found the focused tab's session in 20 of 20 steps in the four terminals; the words of the visible text chose a wrong pane in tmux, so the text is not used.

### Claude chats (`claude-chat`)

A chat (`https://claude.ai/chat/<id>`) has no transcript on the Mac. Claude Desktop keeps only the web app's cache, in an undocumented binary format. So the manifest requests `"screen": ["outline"]`, and the adapter reads the messages from the outline of the page.

In the outline, each message is a group labelled "Message N of M". Claude's replies are in a container with the DOM class `group/message-row`. The adapter keeps their paragraphs, list items and link texts. It leaves out hidden headings, buttons, the status rows of tools such as "Searched the web", and the source chips after sentences. Its `outlineSkip` names them (`AXButton`, `sr-only`, `group/morph`, `group/tag`), so their text does not enter the snapshot at all. It can use only the messages that the window has loaded. This page structure is not documented and may change.

### Telegram screen access

The manifest requests `"screen": ["lists"]`. The adapter reads the message list above the input box and takes the chat name from the window title. It can use only messages currently loaded in the window.

Config migrations never turn on an adapter that the user did not have on: a new built-in adapter stays off. Adapters for Codex, ChatGPT, Antigravity, and Gemini remain planned.

## Write an adapter

An adapter is a Python package with two required files.

`adapter.json` describes the adapter:

| Fields | Purpose |
|---|---|
| `name`, `version`, `author`, `source`, `description` | Identity and source information. |
| `title` | Optional: the adapter's name for people ("Claude Code"); the app shows `name` without it. |
| `interface` | Adapter API version; currently `2`. |
| `apps` | Bundle IDs of supported apps. |
| `electronTree` | Whether its apps build their accessibility tree only on request (Electron): `true` for all of them, or the list of those among `apps` that do. |

For these apps of an enabled adapter (the info's `electronApps`), and for no other app, the app sets two attributes of the app's accessibility element (`ElectronTree.swift`): `AXManualAccessibility`, Electron's switch for assistive apps, and always `AXEnhancedUserInterface`, which VoiceOver sets and Chromium watches. It sets them when such an app starts or comes to the front, and again at a snapshot that finds no focused element.
| `reads` | Declared file access. |
| `screen` | Additional screen data: `lists`, the rows of the lists in the focused window, or `outline`, the tree of the focused web page or window. |
| `outlineSkip` | Names of the outline's elements that go in without their children: an element whose AX role (`AXButton`) or one of whose DOM classes (`sr-only`) is a name. The client never reads the children, so their text is not in the snapshot. The app gives the names of the enabled adapters of the app to the snapshot (`SnapshotPlan.outlineSkip`). The element itself is marked `"skipped": true`. |
| `context` | This adapter's default context settings. |

`adapter.py` contains a subclass of `adapters.Adapter`:

```
claim(focus, hints)   -> Claim(adapter, confidence 0..1, reason) | None
context(focus, hints) -> {about, messages: [{from, text}] newest first, documents?: [{name, text}],
                          terms?, source?, details?} | None
clean(text)           -> str   ("" drops the message or the document)
```

`focus` contains the snapshot; `hints` contains client-supplied information. `about` tells the model where you write. `from` is who wrote each message. `documents` are the files open beside the conversation, the most relevant first, and `name` is the file's name, told to the model. `clean` cleans each message and each document. The server leaves out a document that is not an object, has no name, or is empty after `clean`. If `clean` fails, the error goes to the recording's errors, and the documents after it are left out; the messages are handled the same way. `terms` are the names and words of the conversation; they reach the model even when there are no messages. `source` and `details` are saved as recording metadata, not sent to the model.

Put adapters in `~/Library/Application Support/EchoFox/adapters/`, or set `ECHOFOX_ADAPTERS` to use another folder. An adapter with the same name as a built-in one replaces it. Enable it in the config; the server reloads changed adapter files automatically.

The loader checks the manifest, interface version, and adapter class. It does not isolate the code: adapters run with your user permissions, so only install code you trust.

`adapters/markdown.py` converts Markdown to plain text. It removes code blocks, HTML, and bare links, but keeps inline terms such as identifiers, filenames, flags, and short commands. A link of any scheme keeps only its text. A link to a file (a `file:` URL or a path without a scheme) also gives the name of the file when its text does not name it: the name takes the place of an empty text, or follows the text in brackets. The name is the last part of the path, with `%`-escapes decoded and without the query, the fragment (`#L12`) and a line suffix (`:12`). For example, `[план](file:///Users/a/My%20Plan.md#L3)` becomes "план (My Plan.md)".

## Inspect the selected conversation

Build the snapshot tool, then run it and focus a text field within 5 seconds. The process running the tool needs Accessibility permission.

```
swift build -c release --package-path macos
macos/.build/release/echofox-snapshot --delay 5 | server/.venv/bin/python server/which_session.py
```

`--electron` asks an Electron app for its accessibility tree, as the app does for an enabled adapter's Electron apps; without it the tool sets no attribute of the app. For an adapter that reads the screen, `--lists` adds the rows of the lists, and `--outline` adds the outline of the page. `--outline-skip AXButton,sr-only` takes the outline as the app does for an adapter with that `outlineSkip`. `--app <bundle id>` takes the snapshot of that app at once, without bringing it to the front: `echofox-snapshot --app com.tdesktop.Telegram --lists --out snapshot.json`. These snapshots contain window text; treat them as conversation data.
