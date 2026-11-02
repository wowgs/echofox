# Conversation context and adapters

An adapter supplies recent conversation text to help the speech model recognize names and terms. Dictation also works without an adapter. If the conversation cannot be identified reliably, the server proceeds without context. The adapters run while you speak, on a thread of their own. Their context is waited for until the recording stops; if they are still running then, the dictation goes without context. The log gives the adapters' time of each dictation (`adapters: 0.042 s`), also when they end after the stop.

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
- The files open beside the conversation, if the adapter gives them, in the adapter's order. They have a budget of their own.
- The newest messages, arranged from oldest to newest.

Every budget is taken the same way (`server/budget.py`): greedily and not strictly. The items are taken in their order (the terms most frequent first, the messages newest first, the files as the adapter gives them) until their sum reaches the budget. The item that reaches it is taken whole and is the last. So a long reply or file goes in whole, and the context can be bigger than its budget.

Tokens are estimated, not counted by the model: the characters of each kind (Cyrillic, Latin, digit, whitespace, other) times the model's tokens per character of that kind (`tokenWeights` in its catalog entry). The estimate needs no running model, so the adapters and the app use it too. `server/calibrate_tokens.py` fits the weights against llama.cpp's own tokenizer, and the record of each dictation gives the model's count beside the estimate (`chat_tokens`, `chat_tokens_estimated`). The weights of Gemma 4 E4B were fitted on Russian dictations with English terms; for other scripts the estimate is not measured.

Adapters clean app-specific formatting first. The server then removes lines made mostly of digits and symbols, such as table rows. Terms from those lines can still appear in the term list.

## Adapter settings

Each adapter supplies defaults in its manifest. Override them in its config entry: `"adapters": {"telegram": {"enabled": true, "chatHistoryTokenBudget": 600}}`.

| Setting | What it sets | Claude | Telegram |
|---|---|---|---|
| `chatHistoryTokenBudget` | Total context budget in tokens; at least 1 | 1000 | 2000 |
| `chatTermsTokenBudget` | The largest part of the total budget that terms may use; the rest goes to messages | 200 | 200 |
| `chatDocumentsTokenBudget` | The budget of the open files, apart from the total budget | 1000 | 1000 |
| `proseOnly` | Exclude lines made mostly of digits and symbols, from the messages and the files | on | on |

Use `enabled` to turn an adapter on or off; both built-in adapters are off in a new config. Budgets are in the selected model's tokens, estimated as above.

The app reads the screen (the rows of lists, the outline of a page) from its end, up to the chat budget of the enabled adapters that ask for it, with the same estimate; the element or row whose text reaches the budget is the last one. No count of rows, elements or characters limits it. An adapter keeps less text than the screen shows (claude-chat keeps only Claude's replies), so its context can be smaller than its budget. The structure is limited instead: 80 levels of the outline, 80 ancestors of the focused element, 6 lists within 4 levels of the window, 12 DOM classes of an element and 40 processes of the app.

## The built-in adapters

The built-in adapters are split by where their context comes from, not by the company or the app: one Claude app can be served by two of them. Each one is enabled, set up and failing on its own, and the client takes the screen data that only the enabled ones ask for (the outline of a Claude Desktop page only for `claude-chat` and `claude-code`, the rows of lists only for `telegram`). A manifest may give a `title` for people ("Claude Code"); without one the app shows the name.

| Adapter | Supported app | Context source |
|---|---|---|
| `claude-code` | Claude Code sessions: the Code tab of Claude Desktop, and a tab of Ghostty, Terminal, iTerm2 or Warp | The local transcript of the session in focus. Only Claude's completed responses are used. In the Code tab, also the Markdown file open in the Files panel, read from the disk. |
| `claude-chat` | Claude Desktop's chats (claude.ai) | The messages that the window shows, read from the outline of the page. Only Claude's replies are used. |
| `telegram` | Telegram Desktop | Messages loaded in the open chat, read from the accessibility snapshot. |

### Claude Code session matching (`claude-code`)

The Code tab exposes a URL of the form `https://claude.ai/epitaxy/local_<id>`. The adapter uses it to find a session record in `~/Library/Application Support/Claude/claude-code-sessions/`, which identifies the transcript.

If the record is missing, the adapter uses the web-area title only when exactly one transcript matches. This storage format is undocumented and may change.

User messages, tool calls, tool results, thinking, and system tags are excluded. Earlier user dictations were sometimes copied into new results, which is why the adapter uses only final assistant responses.

### The open file in the Code tab (`claude-code`)

The Files panel of the Code tab shows one file: the active tab, as a preview or as source. The adapter gives a Markdown file (`.md`, `.markdown`) as a document of the context, whole, under the documents' budget like any document. Other files are left out.

- The panel names the file's path under the session's folder above the file: one pop-up button for each part (`docs`, `reference`, `4-app.md`), then the "View source" button, then the page of the file, a group with the DOM class `epitaxy-document-page`. The adapter takes the pop-up buttons just before that group, at its level.
- The session's folder is the `cwd` of Desktop's session record. The adapter reads the file there, not the preview on the screen: the preview has lost the Markdown, and the snapshot reads the screen up to the budget. A path with `..`, or one that leads out of the folder through a link, is not read.
- So the adapter asks for the outline of Claude Desktop only (`"screen": ["outline"]`, `"screenApps"` with Claude Desktop alone): the outline of a terminal is never taken. Its `outlineSkip` leaves out the page of the file (`epitaxy-document-page`), the panel's file tree (`group/file-tree`) and the chat (`epitaxy-chat-panel-body`), whose messages the transcript has.

The panel's structure is Claude Desktop's own and not documented; it was measured on 2026-11-02 (see [observations](../observations.md#token-estimate-and-screen-reading)). The source view was not measured: if it puts the file's text in another element, that text is read before the path, from the end, and can use the budget up.

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

This is interface 2. The next interface, with surfaces, is designed in [Adapter surfaces](../adapter-surfaces.md) and not built yet.

An adapter is a Python package with two required files.

`adapter.json` describes the adapter:

| Fields | Purpose |
|---|---|
| `name`, `version`, `author`, `source`, `description` | Identity and source information. |
| `title` | Optional: the adapter's name for people ("Claude Code"); the app shows `name` without it. |
| `interface` | Adapter API version; currently `2`. |
| `apps` | Bundle IDs of supported apps. |
| `electronTree` | Whether its apps build their accessibility tree only on request (Electron): `true` for all of them, or the list of those among `apps` that do. |
| `reads` | Declared file access. |
| `screen` | Additional screen data: `lists`, the rows of the lists in the focused window, or `outline`, the tree of the focused web page or window. |
| `screenApps` | Optional: those among `apps` whose screen data it needs. Without it, all of them. |
| `outlineSkip` | Names of the outline's elements that go in without their children: an element whose AX role (`AXButton`) or one of whose DOM classes (`sr-only`) is a name. The client never reads the children, so their text is not in the snapshot. The app gives the names of the enabled adapters of the app to the snapshot (`SnapshotPlan.outlineSkip`). The element itself is marked `"skipped": true`. |
| `context` | This adapter's default context settings. |

For the Electron apps of an enabled adapter (the info's `electronApps`), and for no other app, the app sets two attributes of the app's accessibility element (`ElectronTree.swift`): `AXManualAccessibility`, Electron's switch for assistive apps, and always `AXEnhancedUserInterface`, which VoiceOver sets and Chromium watches. It sets them when such an app starts or comes to the front, and again at a snapshot that finds no focused element.

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
