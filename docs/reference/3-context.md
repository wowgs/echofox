# The chat context

The model hears your speech better when it knows the names and words of the conversation that you write into. An adapter finds that conversation and reads its latest messages. The server puts them before the prompt.

Without an adapter that works, the model gets only the prompt. This is the base mode.

Related docs: [the dictation server](1-server.md), [the config file](2-config.md), [the adapter design](../adapters/1-idea.md).

## How the server finds the conversation

1. At the tap of the key, the app takes a focus snapshot. The snapshot holds the app in front, its window, the element with the cursor and the elements around it, the address and title of the nearest web page, and the working folders of the app's child processes. It holds no text of input boxes.
2. The server asks every adapter that works whether the snapshot is its own, and how sure the adapter is.
3. The surest adapter reads the conversation.
4. If no adapter claims the snapshot, or no conversation is found exactly, the dictation runs without context. An adapter never guesses the conversation from the app alone, because the newest session of an app is often another one.

A private dictation gets no context. The app sends no snapshot, and the server runs no adapter.

## What the model gets

The server builds a block of context from what the adapter gives:

1. A header that says where you write, for example "a Telegram chat with Anna". It also says that the context is not speech and that the model must not repeat it.
2. The terms: words in Latin letters, and names in other alphabets (words with a capital letter inside a sentence). The most frequent come first.
3. The newest messages that fit, oldest first.

The block goes between `<context>` and `</context>`, before the prompt.

Before a message goes into the block, the adapter cleans it. For example, the Claude adapter turns Markdown into plain sentences. Then the server leaves out the lines that are mostly digits and symbols, such as table rows and file paths. Their terms still go to the list.

## The settings of an adapter

Each adapter has three advanced settings. Its manifest gives their defaults, and its entry in the config file changes them: `"adapters": {"telegram": {"enabled": true, "chatHistoryTokenBudget": 600}}`.

| Setting | What it sets | Claude | Telegram |
|---|---|---|---|
| `chatHistoryTokenBudget` | The size of the whole block in tokens, at least 1 | 1000 | 2000 |
| `chatTermsTokenBudget` | The part of the block for the terms | 200 | 200 |
| `proseOnly` | Leave out the lines that are mostly digits and symbols | on | on |

`enabled` turns the adapter on and off. A tokens count is in the tokens of the model.

## The built-in adapters

- `claude` (`server/plugins/claude/`) reads the Claude Code session that is open in the Code tab of Claude Desktop.
  - The web area of the Code tab has the address `https://claude.ai/epitaxy/local_<id>`. Claude Desktop keeps a record of that session in `~/Library/Application Support/Claude/claude-code-sessions/`, and the record names the transcript of the session. This format is Claude Desktop's own and has no documentation.
  - If there is no record, the adapter looks for a transcript with the title of the web area. It uses the transcript only if exactly one transcript has that title.
  - From the transcript, only the last text of each finished answer of Claude goes to the model. Your own messages do not go: the model copied an earlier dictation into the next text. Tool calls, their results, thinking and system tags do not go either.
- `telegram` (`server/plugins/telegram/`) reads the open chat in Telegram Desktop. Its manifest asks the app for the rows of the lists in the window (`"screen": ["lists"]`). The messages of the chat are the list above the input box. The name of the chat comes from the title of the window. The context is what the window has loaded. An update of the config never turns on an adapter that reads the screen. You turn it on in the settings window.

Adapters for the apps of OpenAI (Codex, ChatGPT) and Google (Antigravity, Gemini) are planned. Each gets the same kind of plugin.

## Write an adapter

An adapter is a plugin: a folder with two files.

- `adapter.json`, its manifest: `name`, `version`, `author`, `source`, `description`, `interface` (2), `apps` (the bundle IDs of the apps whose focus it reads), `electronTree` (the app builds its accessibility tree only on request), `reads` (the files it reads), `screen` (what of the screen it needs: only `lists` is possible), and `context` (the defaults of its settings).
- `adapter.py`, a module with one subclass of `adapters.Adapter`:

```
claim(focus, hints)   -> Claim(adapter, confidence 0..1, reason) | None
context(focus, hints) -> {about, messages: [{from, text}] newest first, terms?, source?, details?} | None
clean(text)           -> str   ("" drops the message)
```

`focus` is the snapshot, and `hints` is what the client sent. `about` tells the model where you write. `from` is who wrote each message. `terms` are the names and words of the conversation. `source` and `details` go only to the record of the recording.

Put your own plugins in `~/Library/Application Support/Local Voice/adapters/`. The environment variable `LOCAL_VOICE_PLUGINS` sets another folder. A plugin with the name of a built-in one replaces it. A plugin works only when the config turns it on. The server checks only that the manifest reads, that its interface is 2 and that the module has its class. A plugin that you add runs with your rights, so add only code that you trust. The server loads the plugins again when their files change.

`adapters/markdown.py` turns Markdown into plain sentences, for any adapter of a chat app. Code blocks, HTML and bare links go. Inline code stays only when it is a term: a name in code, a file, a flag or a short command.

## See which conversation a dictation gets

Build the snapshot tool once. Then run it and put the cursor in an input box within 5 seconds. The process that runs it needs the Accessibility permission.

```
swift build -c release --package-path macos
macos/.build/release/lv-snapshot --delay 5 | server/.venv/bin/python server/which_session.py
```

For an adapter that reads the screen, `--lists` adds the rows of the lists. `--app <bundle id>` takes the snapshot of that app at once, without bringing it to the front: `lv-snapshot --app com.tdesktop.Telegram --lists --out snapshot.json`. Such a snapshot holds the text of the window, so keep it private.
