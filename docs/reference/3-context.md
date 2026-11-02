# Conversation context and adapters

An adapter supplies recent conversation text to help the speech model recognize names and terms. Dictation also works without an adapter. If the conversation cannot be identified reliably, the server proceeds without context. The adapters run while you speak, on a thread of their own. Their context is waited for until the recording stops; if they are still running then, the dictation goes without context. The log gives the adapters' time of each dictation (`adapters: 0.042 s`), also when they end after the stop.

Private dictation sends no identity, gets no read request and runs no adapter.

See also: [configuration](2-config.md), [saved context](5-recordings.md), and [adapter design decisions](../design.md#adapters).

## How the server finds the conversation

1. At the start of a regular dictation, the app captures the focused app and input element. For an app of an enabled adapter's surfaces, it also reads the identity: the app, the focused window's title, and the address and title of the web page. It sends the identity in the start message. Then the server asks for what the matched surfaces read, and the app reads only that ([What the app reads](#what-the-app-reads)). Input-field values are excluded.
2. The server matches the identity with the surfaces of the enabled adapters (`server/adapters/surfaces.py`). A surface matches when the app is one of its `apps` and each of its `match` patterns holds. The server answers at once, before it loads the model, with a read request: for each matched surface, what the app reads there. With no matched surface, the request has no surfaces.
3. The app sends what it read in a content message, between the audio's messages. Then the adapter of each matched surface looks for the conversation, on the adapters' thread. A surface that reads nothing besides the identity needs no content message, and its adapter runs at once.
4. If no adapter gives a context, or more than one does, recognition uses only the normal prompt. If the content has not come by the stop, the dictation goes without context too, and the recording's errors say "no content by the stop". With more than one context, the errors name the surfaces.

The app reads screen content only when the server's read request asks for it. The server does not choose a conversation just because it is the newest session in an app.

A pattern of `match` is the whole value: `*` is any text, possibly empty, and every other character is itself. So `https://claude.ai/chat/*` matches every chat's address and no other page. A rule whose value the identity does not have fails, for example `url` on a window without a web area.

The read request gives each budget as a number: the user's value in the adapter's config entry, else the manifest's `context`, else the setting's default. These are the same values that limit the adapter's context. A part without a `budget` key gets `null`, and only its structural limits apply. The request also carries the model's `tokenWeights`, for the app's token estimate.

## What the app reads

The app reads the screen through Accessibility (`macos/Sources/FocusSnapshot`), in two phases ([Adapter surfaces](../adapter-surfaces.md#the-flow)).

At the hotkey, the app reads the identity of an app of an enabled adapter's surfaces, and of no other app:

| Field | What |
|---|---|
| `app` | `bundleId`, `pid`, `name`, and `version`: its `CFBundleShortVersionString`, read from its `Info.plist` on the disk |
| `window` | `title` of the focused window |
| `webArea` | `url` and `title` of the nearest web area above the focused element, if any |

The app walks up from the focused element to find the web area, at most 80 ancestors. It does not send the ancestors. In the settings window, one line under an adapter's switch tells the user about the identity, in the same words for every adapter.

The apps of the enabled adapters' surfaces with `treeOnRequest` build their accessibility tree only on request (Electron, Chromium). For them, and for no other app, the app sets two attributes of the app's accessibility element (`ElectronTree.swift`): `AXManualAccessibility`, Electron's switch for assistive apps, and always `AXEnhancedUserInterface`, which VoiceOver sets and Chromium watches. It sets them when such an app starts or comes to the front, and again at a hotkey that finds no focused element.

The server answers with a read request. For each surface in it, the app reads what the request asks, of the window and web area found at the hotkey, on a queue of its own while the audio goes on. It sends one content message, keyed by the surface:

- `outline`: `{"root": "webArea" or "window", "complete", "nodes": [{"depth", "role", "subrole", "title", "description", "identifier", "domClasses", "url", "text", "skipped"}]}`. It is the tree under the web area, or under the focused window without one, flat in the tree's order, with the depth under the root. `text` is the shown text of a static text or a list marker, and never the value of an input field. An element whose AX role or one of whose DOM classes is in the request's `skip` goes in with `"skipped": true`, without its children. The app checks `skip` against all DOM classes of an element, and the element sent keeps the first 12 of them. `complete` says whether the outline has the whole tree.
- `lists` and `focusedFrame`: the lists of the focused window in the tree's order, at most 6 within 4 levels of the window. Each list has its `frame`, its `rowCount` and its last `rows` (oldest first), with a row's `text` and the titles of its cells (`columns`). `focusedFrame` is the place of the focused element on the screen.
- `processes`: the app's child processes, `pid` and `name`, breadth first, at most 40.

The outline and the lists are read from their end, up to the request's budget, with the token estimate below and the same rule (`TokenBudget`): the element or row whose text reaches the budget is the last one. When the budget stops the outline, the ancestors of the last element read still go in, without their text, so the place of that element is known. Without a budget only the structural limits apply: 80 levels of the outline, and the bound of elements below.

The budget counts only text, so a tree of elements without text never reaches it. So each walk also stops after 10,000 elements (`FocusSnapshot.maxElements`): the outline, or the search for the lists with their rows and cells. The outline stops as it does at the budget, with the ancestors of the last element read. The bound is a protection, not a limit of the content. The largest tree measured, a whole window of Claude Desktop's Code tab, had 3538 elements ([observations](../observations.md#token-estimate-and-screen-reading)).

An accessibility tree can hold a cycle: an element can be its own descendant. On 2026-11-02 the application element of Claude Desktop and of Finder was its own child. So a walk leaves out a child that is one of its own ancestors. Nothing is missing then, because that element and its subtree are read once.

The content message has no field for the reason a part is not whole. The outline's `complete` is false when the budget, the 80 levels or the bound of elements stopped it. A list's `rows` are fewer than its `rowCount` when the budget or the bound stopped it. The app's log names the reason at each dictation, for example `outline 10000 elements (left out: what is past 10000 elements)`. `echofox-snapshot` prints the same words to its error output.

## What the model gets

Context is placed before the recognition prompt, between `<context>` and `</context>`:

- A short description of where you are writing, such as “a Telegram chat with Anna”, with instructions not to repeat the context.
- Likely terms: first the names the adapter supplies, such as chat members, then Latin-script words and names in other alphabets, ranked by frequency. English speech gets no terms: every English word would be one.
- The files open beside the conversation, if the adapter gives them, in the adapter's order. They have a budget of their own.
- The newest messages, arranged from oldest to newest.

Every budget is taken the same way (`server/budget.py`): greedily and not strictly. The items are taken in their order (the terms most frequent first, the messages newest first, the files as the adapter gives them) until their sum reaches the budget. The item that reaches it is taken whole and is the last. So a long reply or file goes in whole, and the context can be bigger than its budget.

Tokens are estimated, not counted by the model: the characters of each kind (Cyrillic, Latin, digit, whitespace, other) times the model's tokens per character of that kind (`tokenWeights` in its catalog entry), rounded up. A character is a Unicode scalar. Cyrillic is U+0400 to U+04FF, Latin letters and digits are ASCII only, and whitespace is Unicode's White_Space property. The estimate needs no running model, so the adapters and the app use it too. The server (`server/budget.py`) and the app (`TokenEstimate`) each have a copy of it, and the tests of both check the same examples (`shared/token-examples.json`). `server/tools/calibrate_tokens.py` fits the weights against llama.cpp's own tokenizer, and the record of each dictation gives the model's count beside the estimate (`chat_tokens`, `chat_tokens_estimated`). The weights of Gemma 4 E4B were fitted on Russian dictations with English terms; for other scripts the estimate is not measured.

Adapters clean app-specific formatting first. The server then removes lines made mostly of digits and symbols, such as table rows. Terms from those lines can still appear in the term list.

## Adapter settings

Each adapter supplies defaults in its manifest. Override them in its config entry: `"adapters": {"telegram": {"enabled": true, "chatHistoryTokenBudget": 600}}`.

| Setting | What it sets | claude-code, claude-chat | telegram |
|---|---|---|---|
| `chatHistoryTokenBudget` | Total context budget in tokens; at least 1 | 1000 | 2000 |
| `chatTermsTokenBudget` | The largest part of the total budget that terms may use; the rest goes to messages | 200 | 200 |
| `chatDocumentsTokenBudget` | The budget of the open files, apart from the total budget | 1000 | 1000 |
| `proseOnly` | Exclude lines made mostly of digits and symbols, from the messages and the files | on | on |

Use `enabled` to turn an adapter on or off. The three built-in adapters are off in a new config. Budgets are in the selected model's tokens, estimated as above.

A surface's outline and lists are read up to the setting that its manifest names as their `budget`. The server sends the value in force in its read request ([What the app reads](#what-the-app-reads)). An adapter keeps less text than the screen shows (claude-chat keeps only Claude's replies), so its context can be smaller than its budget.

## The built-in adapters

The built-in adapters are split by where their context comes from, not by the company or the app: one Claude app can be served by two of them. Each one is enabled, set up and failing on its own. The app reads only what a matched surface of an enabled one declares: the outline of a Claude Desktop page for the Code tab or a chat, by its address, the processes of a terminal, and the rows of lists for Telegram. A manifest may give a `title` for people ("Claude Code"); without one the app shows the name.

| Surface | Apps | Match | Reads |
|---|---|---|---|
| `claude-code/desktop` | Claude Desktop | `url` `https://claude.ai/epitaxy/*` | The outline, without a budget |
| `claude-code/terminal` | Ghostty, Terminal, iTerm2, Warp | none | The processes |
| `claude-chat/desktop` | Claude Desktop | `url` `https://claude.ai/chat/*` | The outline, up to `chatHistoryTokenBudget` |
| `telegram/desktop` | Telegram Desktop | none | The lists, up to `chatHistoryTokenBudget` |

| Adapter | Supported app | Context source |
|---|---|---|
| `claude-code` | Claude Code sessions: the Code tab of Claude Desktop, and a tab of Ghostty, Terminal, iTerm2 or Warp | The local transcript of the session in focus. Only Claude's completed responses are used. In the Code tab, also the Markdown file open in the Files panel, read from the disk. |
| `claude-chat` | Claude Desktop's chats (claude.ai) | The messages that the window shows, read from the outline of the page. Only Claude's replies are used. |
| `telegram` | Telegram Desktop | Messages loaded in the open chat, read from the accessibility snapshot. |

### Claude Code session matching (`claude-code`)

The Code tab exposes a URL of the form `https://claude.ai/epitaxy/local_<id>`. The adapter uses it to find a session record in `~/Library/Application Support/Claude/claude-code-sessions/`, which identifies the transcript.

If the record is missing, the adapter uses the web-area title only when exactly one transcript matches. This storage format is undocumented and may change.

User messages, tool calls, tool results and thinking are excluded. Earlier user dictations were sometimes copied into new results, which is why the adapter uses only final assistant responses. The adapter's `clean` takes out the tags that Claude Code adds (`<system-reminder>` and others) before it makes the Markdown plain, in the messages and in the open file.

### The open file in the Code tab (`claude-code`)

The Files panel of the Code tab shows one file: the active tab, as a preview or as source. The adapter gives a Markdown file (`.md`, `.markdown`) as a document of the context, whole, under the documents' budget like any document. Other files are left out.

- The panel names the file's path under the session's folder above the file: one pop-up button for each part (`docs`, `reference`, `4-app.md`), then the "View source" button, then the page of the file, a group with the DOM class `epitaxy-document-page`. The adapter takes the pop-up buttons just before that group, at its level.
- The session's folder is the `cwd` of Desktop's session record. The adapter reads the file there, not the preview on the screen: the preview has lost the Markdown, and the snapshot reads the screen up to the budget. A path with `..`, or one that leads out of the folder through a link, is not read.
- So the surface `desktop` reads the outline of the Code tab, without a budget: the path must not depend on the length of the chat. The surface `terminal` never reads an outline. The outline's `skip` leaves out the page of the file (`epitaxy-document-page`), the panel's file tree (`group/file-tree`) and the chat (`epitaxy-chat-panel-body`), whose messages the transcript has.

The panel's structure is Claude Desktop's own and not documented; it was measured on 2026-11-02 (see [observations](../observations.md#token-estimate-and-screen-reading)). The source view was not measured: if it puts the file's text in another element, that text is read before the path, from the end, and can use the budget up.

### Claude Code in a terminal (`claude-code`)

Claude Code in a tab of Ghostty, Terminal, iTerm2 or Warp gets the context of its session. Inside tmux or screen it gets none, for now: there the session is not found for sure.

- Each running `claude` writes `~/.claude/sessions/<pid>.json` with its `sessionId`, `name` (the session's title) and `entrypoint` (`cli` in a terminal). These files are Claude Code's own and not documented; they may change.
- The identity of a terminal has the focused window's title, and the surface `terminal` reads the terminal's processes. The candidates are the `cli` sessions among those processes; a `claude` in tmux or screen belongs to the multiplexer's server, so it is never one.
- Claude Code sets the terminal's title to `✳ <name>`, and the terminals show it in the window's title (Terminal adds the folder, the command and the size). The session is the one candidate whose `name` the title contains; its transcript is `~/.claude/projects/*/<sessionId>.jsonl`. No candidate, or more than one: no context.
- A new session before its first message has no transcript, and so no messages.

The measurements behind it are in [observations](../observations.md#target-apps-and-accessibility): the title found the focused tab's session in 20 of 20 steps in the four terminals; the words of the visible text chose a wrong pane in tmux, so the text is not used.

### Claude chats (`claude-chat`)

A chat (`https://claude.ai/chat/<id>`) has no transcript on the Mac. Claude Desktop keeps only the web app's cache, in an undocumented binary format. So its surface reads the outline of the page, and the adapter reads the messages from it. It gives a context only for an address with the chat's id.

In the outline, each message is a group labelled "Message N of M". Claude's replies are in a container with the DOM class `group/message-row`. The adapter keeps their paragraphs, list items and link texts. It leaves out hidden headings, buttons, the status rows of tools such as "Searched the web", and the source chips after sentences. The outline's `skip` names them (`AXButton`, `sr-only`, `group/morph`, `group/tag`), so their text does not enter the snapshot at all. The adapter leaves out every element marked `"skipped": true` and does not decide again by role or class. It can use only the messages that the window has loaded. This page structure is not documented and may change.

### Telegram screen access

The surface reads the lists of the window. The adapter reads the message list above the input box and takes the chat name from the window title. It can use only messages currently loaded in the window. Without a message in the window, it gives no context.

Config migrations never turn on an adapter that the user did not have on: a new built-in adapter stays off. Adapters for Codex, ChatGPT, Antigravity, and Gemini remain planned.

## Write an adapter

This is interface 3: an adapter is a product, and its surfaces say where the product is on the screen and what is read there ([Adapter surfaces](../adapter-surfaces.md)).

An adapter is a Python package with two required files.

`adapter.json` describes the adapter. `shared/adapter.schema.json` has its fields, and the server checks each manifest against its rules:

| Fields | Purpose |
|---|---|
| `name`, `version`, `author`, `source`, `description` | Identity and source information. `name` and `version` are required. |
| `title` | Optional: the adapter's name for people ("Claude Code"); the app shows `name` without it. |
| `interface` | Adapter API version: `3`. The server refuses another one. |
| `surfaces` | The places of the product on the screen, at least one, each with the fields below. |
| `context` | This adapter's default context settings. |

| Fields of a surface | Purpose |
|---|---|
| `id` | Unique within the adapter: small letters, digits and `-`. The server names the surface `<adapter>/<id>`. |
| `title` | For people, in the settings window: "Claude Desktop, Code tab". |
| `apps` | Bundle IDs of the apps the surface is in, at least one. |
| `treeOnRequest` | Optional: the apps build their accessibility tree only on request (Electron, Chromium). |
| `match` | Optional patterns of the identity: `url` of the web area's address, `title` of the focused window's title. |
| `screen` | Optional: what the app reads after a match. `outline` with `skip` (the names of elements whose children are left out) and `budget`. `lists` with `budget`. `processes`, an empty object. A `budget` names one of the adapter's token budgets, such as `chatHistoryTokenBudget`. |
| `reads` | The files the adapter reads for this surface, for people: `{"path": a fixed place, "what": what it is}`, `path` optional. |

`adapter.py` contains a subclass of `adapters.Adapter`:

```
context(surface, snapshot) -> {about, messages: [{from, text}] newest first, documents?: [{name, text}],
                               terms?, source?, details?} | None
clean(text)                -> str   ("" drops the message or the document)
```

`surface` is the `id` of the matched surface. `snapshot` holds the identity and the parts of the content that the surface declares, as the app sends them ([What the app reads](#what-the-app-reads)). `context` returns None when it does not find the conversation for sure. `adapters.screen` reads the snapshot for an adapter: the window's title, the web area, the outline's nodes, the subtree, children and earlier siblings of a node, the nodes that are not skipped, the lists and the processes. `adapters.SPEAKER` names the speaker's own messages, and `adapters.place` gives a fixed place on the disk that a test can move with an environment variable. `about` tells the model where you write. `from` is who wrote each message. `documents` are the files open beside the conversation, the most relevant first, and `name` is the file's name, told to the model. `clean` cleans each message and each document, and it is the one place where an adapter changes a text. The server leaves out a document that is not an object, has no name, or is empty after `clean`. If `clean` fails, the error goes to the recording's errors, and the documents after it are left out; the messages are handled the same way. `terms` are the names and words of the conversation; they reach the model even when there are no messages. `source` and `details` are saved as recording metadata, not sent to the model.

Put adapters in `~/Library/Application Support/EchoFox/adapters/`, or set `ECHOFOX_ADAPTERS` to use another folder. An adapter with the same name as a built-in one replaces it. Enable it in the config; the server reloads changed adapter files automatically.

The loader checks the manifest, interface version, and adapter class. A broken adapter's surfaces never match, and the info gives its error. It does not isolate the code: adapters run with your user permissions, so only install code you trust.

`adapters/markdown.py` converts Markdown to plain text. It removes code blocks, HTML, and bare links, but keeps inline terms such as identifiers, filenames, flags, and short commands. A link of any scheme keeps only its text. A link to a file (a `file:` URL or a path without a scheme) also gives the name of the file when its text does not name it: the name takes the place of an empty text, or follows the text in brackets. The name is the last part of the path, with `%`-escapes decoded and without the query, the fragment (`#L12`) and a line suffix (`:12`). For example, `[план](file:///Users/a/My%20Plan.md#L3)` becomes "план (My Plan.md)".

## Inspect the selected conversation

Build the snapshot tool, then run it and focus a text field within 5 seconds. The process running the tool needs Accessibility permission.

```
swift build -c release --package-path macos
macos/.build/release/echofox-snapshot --delay 5 | server/.venv/bin/python server/tools/which_session.py
```

The tool takes the snapshot with the app's own code, in its two phases, and prints `{"identity": …, "content": …}`: the identity of the start message, and the content message that answers a read request. Recorded snapshots for the adapters' tests come from it.

- `--read <file>` executes a read message as the server sends it: `echofox-snapshot --app com.anthropic.claudefordesktop --read read.json --out snapshot.json`.
- Flags build a read of one surface, named `snapshot`, instead. `--outline` reads the outline of the page or window, and `--outline-skip AXButton,sr-only` leaves out the children of those elements. `--lists` reads the rows of the lists, and `--processes` the app's child processes. `--budget <tokens>` limits the outline and the lists, counted with `--weights '<the model's tokenWeights>'`.
- Without `--read` and these flags, the tool prints the identity only.
- `--electron` asks the app for its accessibility tree first, as the app does for a surface with `treeOnRequest`. Without it the tool sets no attribute of the app.
- `--app <bundle id>` takes the snapshot of that running app at once, without bringing it to the front.
- `--app <bundle id> --list` prints every window of that app with its identity, `{"windows": [identity, …]}`, in the app's order of its windows. Nothing comes to the front.
- `--app <bundle id> --window <N>` takes the snapshot of the window at index `N` of that list instead of the focused one, for example with `--read`. The window that holds the app's focused element gets its web area as at the hotkey: the nearest one above that element. Another window gets the first web area of its tree, breadth first, that is not empty: one with an element two levels under it. In Claude Desktop 4.4212.0 (2026-11-02), the window's first web area was the app's own empty page (a `file:` address), and the page of claude.ai came after it in another branch. The search looks at 10,000 elements at most and at each element once.
- The exit code is 2 for a wrong usage, 3 when `--list` or `--window` has no Accessibility permission, and 4 when the `--app` is not running.

Snapshots with an outline or lists contain window text. Treat them as conversation data.

`server/tools/fixtures.py` reads the windows of the adapters' apps with `--list` and `--window`, and keeps the snapshots of your real conversations as fixtures ([fixtures from live windows](8-fixtures.md)).

`which_session.py` reads such a snapshot from a file or from its input. It matches the identity with the surfaces of every working adapter, enabled or not. It gives each surface what the snapshot read for it, or for the surface `snapshot` when the tool read by its flags. Then it prints what was found: the surface, what it is, where it was read, the adapter's details, the number of messages, the open files with their length, the first terms and the errors. It never prints the texts. The test client `try_wav.py --snapshot <file>` sends the same snapshot with a recording ([development](7-development.md#test-recognition-on-a-separate-server)).
