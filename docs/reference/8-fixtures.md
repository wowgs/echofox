# Fixtures from live windows

A fixture is a real snapshot of one adapter surface, taken of an app on this Mac, with the context that the adapter gave and that you accepted. The fixtures show when an app update changes what the adapters read. Related docs: [development](7-development.md), [the chat context](3-context.md), [adapter surfaces](../adapter-surfaces.md).

The fixtures come from your real conversations as they are open on the screen. They hold the conversations' text and the files that the adapters read. They are not anonymized, and they never leave this Mac: git leaves the folder out. The hand-written snapshots in `server/test_adapters.py` stay, and CI runs them.

## Where the fixtures are

The fixtures are in `fixtures/` at the repository's root, which `.gitignore` lists. The tool and the tests use `$ECHOFOX_FIXTURES` instead when it is set. A git worktree has a root of its own, so set `ECHOFOX_FIXTURES=~/echofox/fixtures` in a worktree to use the main checkout's fixtures.

| Path | What |
|---|---|
| `fixtures/<adapter>/<surface id>/<app version>.json` | The accepted fixture of that version of the app, for example `fixtures/claude-chat/desktop/4.4212.0.json`. |
| `fixtures/<adapter>/<surface id>/pending.json` | The last recording of the surface, until you accept it. |

A fixture file has these fields:

| Field | What |
|---|---|
| `surface` | `<adapter>/<id>`. |
| `app` | `bundleId` and `version` of the app. |
| `macos`, `date` | The macOS version and the time of the recording. |
| `home` | The home folder at the recording. A replay puts the kept files under the same path in a new folder. |
| `identity` | The identity, as the start message carries it. |
| `read` | The read request of this surface, as the server sends it. |
| `content` | What the app read for this surface, as the content message carries it. |
| `sources` | The files that the adapter read: `path` from `~/`, `mtime` and `text`. A file that was cut has `linesLeftOut`, the number of its first lines that the fixture does not keep. |
| `expected` | What of the context reaches the model: `about`, `source`, `details`, and the `terms`, `messages` and `documents` that the budgets keep. |

In `expected` and in the kept files, the home folder is written `~`. In `expected`, the process ids of the snapshot are written `<pid>`, because they change with every run of a program.

## What a fixture compares

`expected` is the context as the prompt takes it, not the adapter's whole parse. The tool gives the core's context (`adapters.context`) to the same function that builds the prompt's context block (`prompt.held` in `server/prompt.py`). That function keeps the terms, the messages from the newest and the documents within the token budgets. The budgets and the token weights are those of the default config, resolved as for the read request (`resolve.adapter`). So your own settings never change a fixture. The language is not set: with English speech, the prompt leaves out the terms. The home folder is written `~` before the budgets are taken, so that a replay under another folder keeps the same items.

## The tool

`server/tools/fixtures.py` runs without questions, so an agent can run it from a shell:

```
server/.venv/bin/python server/tools/fixtures.py record [SURFACE ...]
server/.venv/bin/python server/tools/fixtures.py accept SURFACE ...
server/.venv/bin/python server/tools/fixtures.py check [SURFACE ...]
```

`SURFACE` is `<adapter>/<id>`, for example `claude-chat/desktop`. Without surfaces, `record` takes every surface of every working adapter. `check` then takes every surface that has a fixture.

The tool needs `macos/.build/release/echofox-snapshot` or the debug build, or the path in `$ECHOFOX_SNAPSHOT`. Build it with `swift build -c release --package-path macos --product echofox-snapshot`. The app that runs the tool, the terminal, needs the Accessibility permission. Without it the tool stops and says so.

`record` does these steps for each running app of the surfaces:

1. `echofox-snapshot --app <bundle id> --list` lists the app's windows with each window's identity. Nothing comes to the front.
2. The server's matching (`server/adapters/surfaces.py`) tells which surfaces each window is on.
3. The tool builds the read request as the server does (`resolve.budget`), with the default config.
4. `echofox-snapshot --app <bundle id> --window <N> --read <file>` reads the content of that window.
5. The core runs the surface's adapter with its `clean` (`adapters.context`). The tool watches which files the adapter opens.
6. The tool takes the first window on the surface whose adapter gives a context. It names the other windows with a context that it left. When no window gives a context, the tool says why for each window and writes nothing for the surface.
7. The tool keeps every file that the adapter opened, except Python's modules and files that are not UTF-8 text.
8. The tool runs the adapter again on the kept files, under a new home folder. If that replay gives another `expected`, the adapter needed a file that is not kept, and the tool writes nothing for the surface.
9. Each kept file over 1 MB keeps only a tail, as the next section says.
10. The tool writes `pending.json` and prints it for review: the window, what was read, `about`, `source`, `details`, the terms, every message and every document that the budgets keep, and the kept files.

The order of the windows is the order of the surface's apps in its manifest, then the order of each app's windows. That is the order that `echofox-snapshot --list` prints. `FocusSnapshot.windows` (`macos/Sources/FocusSnapshot/FocusSnapshot.swift`) gives the app's `AXWindows` attribute in its own order and does not sort it. Apple's documentation does not say what that order is. That it puts the front-most window first is not verified.

Claude Desktop shows one view at a time in its window: a chat or the Code tab. So its two surfaces are recorded one after the other: record `claude-chat/desktop` while the window shows the chat, then switch to the Code tab and record `claude-code/desktop`.

`accept` renames each surface's `pending.json` to `<app version>.json`. A fixture of the same version is replaced.

`check` reads and parses each surface as `record` does, takes the first window with a context, and compares its `expected` with the fixture of the newest app version of that surface. It writes nothing. It prints, for each surface, the app's version now and in the fixture, `same` or `different`, whether the read request and the content read are the fixture's, and the differences. When windows are on the surface but none gives a context, `check` prints `different: no context`.

| Exit code | Meaning |
|---|---|
| 0 | `record` wrote every surface that you named (any surface when you named none), `accept` did its work, or `check` found every surface the same. |
| 1 | A surface was not recorded, `check` found a difference, or the tool stopped with an error. |
| 2 | `check` found no difference, but it could not check a surface: no window on it, or no fixture. |

## Big files

A file that the adapter read and that is over 1 MB (`LIMIT` in the tool) keeps only a tail: its last lines. The tool looks for the fewest last lines with which the replay gives the same `expected`, among the tails of at most 1 MB. It halves the number of lines at each step. It takes that a longer tail works when a shorter one does. When that does not hold, the tail that it keeps still gives the same `expected`, but it is not always the shortest one. If the longest tail within 1 MB gives another `expected`, the tool writes nothing for the surface and prints the difference.

A Claude Code transcript is the log of a whole session, with tool output and images in it. On 2026-11-02, the transcript of a long session had 182 MB in 32,494 lines. Its last three replies, about the chat budget, were in its last 0.26 MB. Its `expected` needed more of it. The title comes from the transcript's first `custom-title` line, and the session was renamed at line 9,384. The core counts the terms in every reply. Halving found 32,421 last lines (181.5 MB) as the fewest that gave the same `expected`. This was measured with the transcript reader and the core's functions in memory, not with `record`. By it, no tail within 1 MB of that session gives the same `expected`, so `record` would write nothing for it.

## The tests

`server/test_fixtures.py` replays each accepted fixture, every version: it runs the adapter on the fixture's snapshot and on the fixture's kept files under a new home folder, not the live disk. The test compares the result with `expected`. Without the fixtures folder the test is skipped with a message: CI on GitHub has no fixtures. The same module tests the tool on made-up windows, snapshots and files.

## Record and accept

Open the real conversation of each surface that you want to record:

- a Claude chat in Claude Desktop,
- the Code tab of Claude Desktop with a file open in the Files panel,
- a chat in Telegram Desktop,
- a terminal tab with claude running in it, the active tab of its window.

Tell the agent what is open. It runs `record` for the surfaces that are open, for example:

```
server/.venv/bin/python server/tools/fixtures.py record claude-chat/desktop telegram/desktop claude-code/terminal
```

Then switch Claude Desktop to the Code tab, and the agent records that surface:

```
server/.venv/bin/python server/tools/fixtures.py record claude-code/desktop
```

Read each review. Accept the surfaces whose context is right:

```
server/.venv/bin/python server/tools/fixtures.py accept claude-chat/desktop claude-code/desktop telegram/desktop claude-code/terminal
```

## After an app update

1. Open a conversation of that app's surfaces.
2. Run `check` for those surfaces.
3. `same`: record and accept the surface, so that the new version has its fixture too.
4. `different`: read the differences. A conversation that changed since the recording differs too, so open the conversation of the fixture. When the app shows the conversation in another way, change the adapter until the new version's context is right, then record and accept it. The tests still run the fixtures of the older versions. If the adapter no longer needs to read an older version, delete that version's fixture.

A restarted claude in the terminal has another process id, which the fixture writes `<pid>`. A new session has another session id, so record the terminal surface again after you start a new session.
