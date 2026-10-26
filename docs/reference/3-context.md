# Conversation context and adapters

An adapter supplies recent conversation text to help the speech model recognize names and terms. Dictation also works without an adapter. If the conversation cannot be identified reliably, the server proceeds without context.

Private dictation never sends a context snapshot or runs an adapter.

See also: [configuration](2-config.md), [saved context](5-recordings.md), and [adapter design decisions](../design.md#adapters).

## How the server finds the conversation

1. At the start of a regular dictation, the app captures the focused app, window, input element, nearby accessibility metadata, web page information, and child-process working folders. Input-field values are excluded.
2. Enabled adapters inspect the snapshot and report whether they can handle it, with a confidence score.
3. The server asks the most confident adapter to retrieve the conversation.
4. If no adapter claims the snapshot or the conversation is ambiguous, recognition uses only the normal prompt.

The app collects additional screen content only for enabled adapters that request it. The server does not choose a conversation just because it is the newest session in an app.

## What the model gets

Context is placed before the recognition prompt, between `<context>` and `</context>`:

- A short description of where you are writing, such as “a Telegram chat with Anna”, with instructions not to repeat the context.
- Likely terms: Latin-script words and names in other alphabets, ranked by frequency.
- The newest messages that fit the adapter's budget, arranged from oldest to newest.

Adapters clean app-specific formatting first. The server then removes lines made mostly of digits and symbols, such as table rows. Terms from those lines can still appear in the term list.

## Adapter settings

Each adapter supplies defaults in its manifest. Override them in its config entry: `"adapters": {"telegram": {"enabled": true, "chatHistoryTokenBudget": 600}}`.

| Setting | What it sets | Claude | Telegram |
|---|---|---|---|
| `chatHistoryTokenBudget` | Total context budget in tokens; at least 1 | 1000 | 2000 |
| `chatTermsTokenBudget` | Budget reserved for terms | 200 | 200 |
| `proseOnly` | Exclude lines made mostly of digits and symbols | on | on |

Use `enabled` to turn an adapter on or off. Budgets use the selected model’s tokenizer.

## The built-in adapters

| Adapter | Supported app | Context source |
|---|---|---|
| `claude` | Claude Desktop: the Code tab and chats | In the Code tab, the local transcript of the open session. In a chat, the messages that the window shows, read from the accessibility tree. Only Claude's completed responses are used. |
| `telegram` | Telegram Desktop | Messages loaded in the open chat, read from the accessibility snapshot. Enable this adapter yourself in Settings. |

### Claude session matching

The Code tab exposes a URL of the form `https://claude.ai/epitaxy/local_<id>`. The adapter uses it to find a session record in `~/Library/Application Support/Claude/claude-code-sessions/`, which identifies the transcript.

If the record is missing, the adapter uses the web-area title only when exactly one transcript matches. This storage format is undocumented and may change.

User messages, tool calls, tool results, thinking, and system tags are excluded. Earlier user dictations were sometimes copied into new results, which is why the adapter uses only final assistant responses.

### Claude chats

A chat (`https://claude.ai/chat/<id>`) has no transcript on the Mac. Claude Desktop keeps only the web app's cache, in an undocumented binary format. So the manifest requests `"screen": ["outline"]`, and the adapter reads the messages from the outline of the page.

In the outline, each message is a group labelled "Message N of M". Claude's replies are in a container with the DOM class `group/message-row`. The adapter keeps their paragraphs, list items and link texts. It leaves out hidden headings, buttons, the status rows of tools such as "Searched the web", and the source chips after sentences. It can use only the messages that the window has loaded. This page structure is not documented and may change.

### Telegram screen access

The manifest requests `"screen": ["lists"]`. The adapter reads the message list above the input box and takes the chat name from the window title. It can use only messages currently loaded in the window.

Config migrations never enable a screen-reading adapter automatically. Adapters for Codex, ChatGPT, Antigravity, and Gemini remain planned.

## Write an adapter

An adapter is a Python plugin with two required files.

`adapter.json` describes the plugin:

| Fields | Purpose |
|---|---|
| `name`, `version`, `author`, `source`, `description` | Identity and source information. |
| `interface` | Adapter API version; currently `2`. |
| `apps` | Bundle IDs of supported apps. |
| `electronTree` | Whether the app needs to enable the Electron accessibility tree. |
| `reads` | Declared file access. |
| `screen` | Additional screen data: `lists`, the rows of the lists in the focused window, or `outline`, the tree of the focused web page or window. |
| `context` | This adapter's default context settings. |

`adapter.py` contains a subclass of `adapters.Adapter`:

```
claim(focus, hints)   -> Claim(adapter, confidence 0..1, reason) | None
context(focus, hints) -> {about, messages: [{from, text}] newest first, terms?, source?, details?} | None
clean(text)           -> str   ("" drops the message)
```

`focus` contains the snapshot; `hints` contains client-supplied information. `about` tells the model where you write. `from` is who wrote each message. `terms` are the names and words of the conversation. `source` and `details` are saved as recording metadata, not sent to the model.

Put plugins in `~/Library/Application Support/EchoFox/adapters/`, or set `ECHOFOX_PLUGINS` to use another folder. A plugin with the same name as a built-in one replaces it. Enable it in the config; the server reloads changed plugin files automatically.

The loader checks the manifest, interface version, and adapter class. It does not isolate the code: plugins run with your user permissions, so only install code you trust.

`adapters/markdown.py` converts Markdown to plain text. It removes code blocks, HTML, and bare links, but keeps inline terms such as identifiers, filenames, flags, and short commands.

## Inspect the selected conversation

Build the snapshot tool, then run it and focus a text field within 5 seconds. The process running the tool needs Accessibility permission.

```
swift build -c release --package-path macos
macos/.build/release/echofox-snapshot --delay 5 | server/.venv/bin/python server/which_session.py
```

For an adapter that reads the screen, `--lists` adds the rows of the lists, and `--outline` adds the outline of the page. `--app <bundle id>` takes the snapshot of that app at once, without bringing it to the front: `echofox-snapshot --app com.tdesktop.Telegram --lists --out snapshot.json`. These snapshots contain window text; treat them as conversation data.
