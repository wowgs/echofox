# Fixtures from live windows

A fixture is a real snapshot of one adapter surface, taken of an app on this Mac, with the parse that the adapter gave and that you accepted. The fixtures show when an app update changes what the adapters read. Related docs: [development](7-development.md), [the chat context](3-context.md), [adapter surfaces](../adapter-surfaces.md).

The fixtures hold the test conversations' text as the apps show it. They are not anonymized and they never leave this Mac: git leaves the folder out. The hand-written snapshots in `server/test_adapters.py` stay, and CI runs them.

## Where the fixtures are

The fixtures are in `fixtures/` at the repository's root, which `.gitignore` lists. The tool and the tests use `$ECHOFOX_FIXTURES` instead when it is set. A git worktree has a root of its own, so set `ECHOFOX_FIXTURES=~/echofox/fixtures` in a worktree to use the main checkout's fixtures.

| Path | What |
|---|---|
| `fixtures/<adapter>/<surface id>/<app version>.json` | The accepted fixture of that version of the app, for example `fixtures/claude-chat/desktop/4.4212.0.json`. |
| `fixtures/<adapter>/<surface id>/pending.json` | The last recording of the surface, until you accept it. |
| `fixtures/sandbox/` | The folder of the Claude Code test sessions, with `notes.md`. |

A fixture file has these fields:

| Field | What |
|---|---|
| `surface` | `<adapter>/<id>`. |
| `app` | `bundleId` and `version` of the app. |
| `macos`, `date` | The macOS version and the time of the recording. |
| `marker` | The marker text that the window carried. |
| `identity` | The identity, as the start message carries it. |
| `read` | The read request of this surface, as the server sends it. |
| `content` | What the app read for this surface, as the content message carries it. |
| `sources` | The files that the adapter read and that carry the marker: `path` from `~/`, `mtime` and `text`. |
| `expected` | The core's context of the window: `adapter`, `surface`, `about`, `source`, `details`, `messages`, `documents` and `terms`. |

In `expected` and in the kept files, the home folder is written `~`. In `expected`, the process ids of the snapshot are written `<pid>`, because they change with every run of a program.

## The marker

A window becomes a fixture only when the text `EchoFox fixture` is in its window title, in its page title, or in the text that the app read there. Case does not matter. The tool reads the windows of your real conversations too, but it never writes a window without the marker. So a real conversation never becomes a fixture. Before you accept a fixture, read its review: a real conversation that mentions the marker is recorded too.

## The tool

`server/tools/fixtures.py` runs without questions, so an agent can run it from a shell:

```
server/.venv/bin/python server/tools/fixtures.py sandbox
server/.venv/bin/python server/tools/fixtures.py record [SURFACE ...]
server/.venv/bin/python server/tools/fixtures.py accept SURFACE ...
server/.venv/bin/python server/tools/fixtures.py check [SURFACE ...]
```

`SURFACE` is `<adapter>/<id>`, for example `claude-chat/desktop`. Without surfaces, `record` and `check` take every surface of every working adapter. `check` then takes every surface that has a fixture.

The tool needs `macos/.build/release/echofox-snapshot` or the debug build, or the path in `$ECHOFOX_SNAPSHOT`. Build it with `swift build -c release --package-path macos --product echofox-snapshot`. The app that runs the tool, the terminal, needs the Accessibility permission. Without it the tool stops and says so.

`record` does these steps for each running app of the surfaces:

1. `echofox-snapshot --app <bundle id> --list` lists the app's windows with each window's identity. Nothing comes to the front.
2. The server's matching (`server/adapters/surfaces.py`) tells which surfaces each window is on.
3. The tool builds the read request as the server does (`resolve.budget`), with the default config. So your own settings never change a fixture.
4. `echofox-snapshot --app <bundle id> --window <N> --read <file>` reads the content of that window.
5. A window without the marker goes no further.
6. The core runs the surface's adapter with its `clean` (`adapters.context`). The tool watches which files the adapter opens, and keeps those that carry the marker.
7. The tool runs the adapter again on the kept files, under a new home folder. If that replay gives another parse, the adapter needed a file without the marker, and the tool writes nothing for the surface. Otherwise it writes `pending.json` and prints it for review: the window, what was read, `about`, `source`, `details`, the terms, every message and every document in full, and the kept files.

When more than one window with the marker is on a surface, the tool writes nothing for it. Claude Desktop shows a chat or the Code tab in its one window. So record `claude-chat/desktop` while the window shows the chat, then switch to the Code tab and record `claude-code/desktop`.

`accept` renames each surface's `pending.json` to `<app version>.json`. A fixture of the same version is replaced.

`check` reads and parses each surface as `record` does, and compares the parse with the fixture of the newest app version of that surface. It writes nothing. It prints, for each surface, the app's version now and in the fixture, `same` or `different`, whether the read request and the content read are the fixture's, and the differences of the parse.

| Exit code | Meaning |
|---|---|
| 0 | `record` wrote every surface that you named (any surface when you named none), `accept` and `sandbox` did their work, or `check` found every surface the same. |
| 1 | A surface was not recorded, `check` found a difference, or the tool stopped with an error. |
| 2 | `check` found no difference, but it could not check a surface: no window with the marker, or no fixture. |

## The tests

`server/test_fixtures.py` runs the adapter of each accepted fixture, every version, on the fixture's snapshot. The adapter reads the fixture's kept files under a new home folder, not the live disk. The test compares the parse with `expected`. Without the fixtures folder the test is skipped with a message: CI on GitHub has no fixtures. The same module tests the tool on made-up windows and snapshots.

## Set up the test conversations once

Make the sandbox first:

```
server/.venv/bin/python server/tools/fixtures.py sandbox
```

It makes `fixtures/sandbox/notes.md`, a Markdown file with the marker, headings, a list, inline code, a code block, a link, and Russian with English terms.

### A Claude chat

In Claude Desktop, start a new chat and send these three messages:

1. `EchoFox fixture. Ответь по-русски в Markdown: два заголовка второго уровня, под первым маркированный список из трёх пунктов о разнице git rebase и git merge, команды в inline code.`
2. `Покажи пример .gitignore для Python-проекта в блоке кода и дай ссылку на документацию: https://git-scm.com/docs/gitignore`
3. `Одним абзацем: чем pyproject.toml отличается от requirements.txt? Термины оставь на английском.`

Rename the chat to `EchoFox fixture chat`.

### A Claude Code session in Claude Desktop

1. In the Code tab, start a session in the folder `fixtures/sandbox`.
2. Send `Прочитай notes.md и ответь по-русски: заголовок и список из трёх пунктов о том, что в нём.`
3. Send `Покажи команду git, которая выводит лог одной строкой на коммит, в блоке кода.`
4. Rename the session to `EchoFox fixture code`.
5. Open `notes.md` in the Files panel.

### Telegram's Saved Messages

Open Saved Messages in Telegram Desktop and post these messages in this order:

1. `Надо задеплоить новую версию на staging до пятницы.`
2. `Проверь, что pyproject.toml и requirements.txt не расходятся.`
3. `EchoFox fixture`

The marker goes last, so that it is among the newest messages that the budget reads.

### A terminal tab with claude

In Ghostty, open a tab in the sandbox and start a named session:

```
cd fixtures/sandbox
claude -n "EchoFox fixture terminal"
```

Trust the folder when claude asks. Send `Ответь по-русски одним списком: три команды git для работы с ветками, каждая в inline code.` Keep the tab the active tab of its window, and keep claude running: the surface reads the running sessions.

## Record and accept

Tell the agent what is open. It runs `record` for the surfaces on the screen:

```
server/.venv/bin/python server/tools/fixtures.py record claude-chat/desktop telegram/desktop claude-code/terminal
```

Then switch Claude Desktop to the Code tab session and record that surface:

```
server/.venv/bin/python server/tools/fixtures.py record claude-code/desktop
```

Read each review. Accept the surfaces whose parse is right:

```
server/.venv/bin/python server/tools/fixtures.py accept claude-chat/desktop claude-code/desktop telegram/desktop claude-code/terminal
```

## After an app update

1. Open the test conversation of that app's surfaces.
2. Run `check` for those surfaces.
3. `same`: record and accept the surface, so that the new version has its fixture too.
4. `different`: read the differences. When the app shows the conversation in another way, change the adapter until the new version's parse is right, then record and accept it. The tests still run the fixtures of the older versions. If the adapter no longer needs to read an older version, delete that version's fixture.

A restarted claude in the terminal has another process id, which the fixture writes `<pid>`. A new session has another session id, so record the terminal surface again after you start a new session.
