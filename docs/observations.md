# Observations

Measurements and observations that shaped EchoFox, with their date and conditions. A number here holds only on its machine and versions; it is not a promise for other Macs. Newer entries go at the end of their section. Related: [design](design.md), [development](reference/7-development.md).

The development Mac: Apple M5 with a 10-core GPU, 24 GB of memory, macOS 27.0.1. llama-server 0.6.0, build 11429 (`d81235049`), with Metal.

## Model and memory

- The Q8_0 file of ggml-org is about 8.0 GB and its Q4_0 file 4.6 GB. Their shared BF16 audio projector adds 0.99 GB. Google's quantization-aware trained (QAT) Q4_0 file is 5.15 GB, with its own audio projector of 0.99 GB. The measurements below, before 2026-11-02, are of ggml-org's files.
- 2026-10-19: about 7.6 GB of the Q8_0 weights were mapped from the file (mmap). macOS can drop clean pages and read them again, so the model still weighs on memory.
- The process's own memory after start was about 0.66 GB. With the prompt cache in RAM on (8 GiB), it grew to 8.85 GB in 27 hours and the system swapped. So the RAM cache is off: `--cache-ram 0`.
- One snapshot of the working Mac had 23 of 24 GB in use and 9.2 GB of swap. That is the state of a busy computer, not a requirement.
- 2026-10-25: the whole Q8 stack took about 9.7 GiB (7.46 GiB of weights resident plus 2.13 GiB of llama-server's footprint); decoding ran at 22.8 tokens/s; a 13 s piece took 2.35 s. One Q4_0 run recognized a 15.7 s recording in 2.89 s, with a footprint of 2194 MB.

## Token estimate and screen reading

- 2026-11-02, llama.cpp `llama-tokenize` (commit d81235049, vocabulary only) on the Q8_0 file: 11 KB of text, 1988 tokens. The first run took 4.56 s (the file not in the cache), the next two 0.29 s each; about 207 MB resident each time. A process per count is too slow for every budget, so the context uses an estimate.
- 2026-11-02, the estimate of `server/budget.py`, fitted on 100 random saved texts before the audio and measured on 100 others (460 to 4181 tokens, Russian dictations with English terms, 54 % of the letters Cyrillic): |error| median 1.8 %, 90th percentile 4.8 %, largest 7.5 %. Characters / 3.4 alone, on an earlier sample: median 4.6 %, 90th percentile 10.7 %, largest 16.9 %.
- 2026-10-28 to 2026-11-02, the app's log, Claude Desktop with the outline: 192 snapshots, 198 ms on average, 562 ms at most; the old cap of 3000 elements took about 530 ms. Telegram with lists: 80 snapshots, 157 ms on average, 244 ms at most.
- 2026-11-02, Claude Desktop's Code tab with the files panel open, `echofox-snapshot --app … --outline`: the whole window, 1212 elements, 5436 estimated tokens of text, 170 ms; up to 1000 tokens, 173 elements, 1006 tokens, 49 ms. One image of the README preview had its picture as a `data:` URL in `AXURL`; the snapshot leaves such URLs out.
- 2026-11-02, the same session, its Files panel. With `README.md` open, one pop-up button "README.md" before the "View source" button and the page of the file (`epitaxy-document-page`). With `docs/reference/4-app.md` opened from the file tree, it replaced the README's tab (one tab, "4-app.md , preview"), and the pop-up buttons were "docs", "reference", "4-app.md". Desktop's session record has the folder (`cwd`) and no open files. With the outlineSkip of claude-chat and claude-code and a budget of 1000 tokens, the snapshot took 64 ms and 123 elements, the whole window; the adapter read the file from `/Users/alex/echofox`: 9655 characters after clean, 2477 estimated tokens, which go in whole over the documents' budget of 1000.
- 2026-11-02, `echofox-snapshot --app com.anthropic.claudefordesktop --electron --outline` (debug build), three runs each. The Code tab of a long session, the whole window: 3538 elements, 439 to 447 ms, about 0.12 ms an element. The same with claude-code's skip list: 125 elements, 15 to 16 ms. This is the largest tree measured, so the walks' bound of 10,000 elements is about three times it.
- 2026-11-02, Claude Desktop with no focused element (another app in front) and Finder: the focused window that Accessibility gave was the application element (role `AXApplication`), and that element was its own first child (`CFEqual`). In Finder the desktop's group also had the application element 63 times among its children. Before the walks left such repeats out, Claude Desktop's outline repeated the app's menus down to 80 levels: 20117 elements in 2304 ms (one run). Finder's outline ran for minutes and was stopped. With the repeats left out, Claude Desktop gave 264 elements in 56 to 68 ms (six runs) and Finder 366 elements in 43 to 57 ms (three runs, `--budget 20`), each outline complete.

## Recognition

| Observation | Consequence |
|---|---|
| Gemma takes at most 30 s of audio per request in the current catalog. | Long recordings are cut into pieces. |
| The llama.cpp build in use marks audio input as experimental in its logs. | An engine update is checked on recordings. |
| Of 2038 pieces, all 35 that had almost no speech gave invented text or copied the context. | A speech detector runs before the model. |
| 2026-10-18–19: generation took 78% of the wait after the stop for one-piece recordings; median 21 tokens/s. | Speed-ups are judged by latency and quality on our set. |
| Generation sometimes does not stop in time. | The server limits the answer's length and drops an answer that reaches it. |
| 2026-10-19–21: transliteration fell from 2.1% to 0% on a bench of 120 pieces; 95% of pieces had punctuation. | Behavior checks, not a quality measurement on a fixed reference. |
| 2026-10-14: with the whole recording as one conversation, in which the model saw its answers to the earlier pieces as its own turns, a piece often began by repeating the earlier piece's text. | Each piece is a request of its own. |
| 2026-11-02: each piece took the end of the earlier pieces' text, about 100 tokens, at temperature 1.0. Of 5 recordings with such a piece, in 2 the second piece repeated the first one whole: once with the tail as a sentence after the prompt (193407-f87c32), once as a `<previous_speech>` block between the context and the prompt (200014-85ab71). In a third, the second piece came without punctuation and capital letters (193834-85edb8). | A piece gets no text of the pieces before it. |
| 2026-11-05: the cut was the quietest 300 ms within 12 to 15 s. In 002540-c22418, VAD heard speech in every chunk from 12.06 to 15 s; the cut fell between "посмотри" and "по", and the next piece began "Я этим" for "по этим". A pause of 300 ms had ended at 12.03 s. Replayed on the 25 recordings of several pieces from 2026-11-02 to 2026-11-05: 40 of the 49 cuts were in a pause; with a pause of at least 0.2 s within 8 to 25 s, 41 of 41. Some pieces grow to 18–20 s, which turned Russian words into Latin letters more often on 2026-10-19. | A cut goes into the pause nearest to 15 s; the length of the pieces is watched. |

## Target apps and Accessibility

These hold for the versions named; check them again when an app updates.

- 2026-10-15, Claude Desktop 2.37337.1: the text box appeared only after `AXManualAccessibility` was set, about 2.1 s later (2087–2104 ms, three runs). So the app sets it ahead for the apps that need it. The Code tab's URL led to Desktop's local record of the session.
- Claude Desktop, Telegram and Ghostty gave no usable caret position. A future indicator can use the window frame.
- A Claude Code transcript alone does not prove that its session is the one on screen; a link to the current window is needed.
- 2026-10-18, Codex Desktop: error −25205 when enabling the accessibility tree.
- Telegram's window title gave the chat's name, and the list above the text box its messages. Ghostty gave the working folder through `AXDocument`, Chrome the tab's URL.
- 2026-10-18: the right Command key was taken by a voice feature of Claude Desktop in the version checked then.
- 2026-10-25, Claude Desktop 3.6556.2: a regular chat (`claude.ai/chat/<id>`) has no local transcript, only the web app's cache in IndexedDB, in an undocumented binary format. The accessibility tree marks each message with a group "Message N of M". A 4-message chat gave 532 elements; the snapshot with the outline took 93 ms (one run).
- 2026-10-26: a chat of 18 messages had only messages 16–18 in the tree; only 18 was on the screen, 16 and 17 were drawn above it with a 1 pt frame. A chat of 10 had all 10. The Code tab of a long session (87 messages) had only messages 86 and 87. So the screen gives the newest replies of a chat, and the Code tab keeps reading transcripts.
- EchoFox changes no app's package. Their internal formats, such as Claude's session store, can change without notice.
- 2026-10-27, Claude Code in a terminal (Claude Code 2.1.300, macOS 27, M5): each running `claude` writes `~/.claude/sessions/<pid>.json` with `sessionId`, `cwd`, `name` (the session's title), `status` and `entrypoint` (`cli` in a terminal, `claude-desktop` in Claude Desktop); it is an internal file of Claude Code, not documented. The file appears only once the folder is trusted, and not for a `claude` started inside another Claude Code session (it inherits `CLAUDE_CODE_CHILD_SESSION` and saves no transcript). A new session has no transcript file until its first message. Claude Code sets the terminal's title to `✳ <name>`; a new session's title is `✳ Claude Code` while its `name` is derived from the folder (`echofox-cc`). In Ghostty, Terminal, iTerm2 and Warp, one window with four tabs (sessions A and B in one folder, C in another, a shell), five focus changes each: matching the focused window's title from Accessibility against the sessions' `name` gave the focused tab's session, or none on the shell tab, in 20 of 20 steps (Terminal adds the folder, the command and the size; iTerm2 drops the `✳`); the words of the visible text matched the session's last replies in 12 of 20 and found nothing in the other 8, never a wrong one; "the only `claude` under the terminal app" decided nothing once two tabs had one. Finding the `claude` processes under the app and reading their files took 25 to 45 ms, the window's text through Accessibility 35 to 55 ms (one run each). Ghostty opens a new tab next to the current one, not at the end. Warp's tab bar is not in Accessibility, so there the focused tab was not checked apart from the title. Not checked: two tabs with the same session name, and the title after a new session's first message.
- 2026-10-27, multiplexers in Ghostty (tmux 3.8 from Homebrew, macOS's screen 4.00.03): a `claude` in tmux or screen is a child of the multiplexer's server, not of the terminal app. tmux with its defaults (`set-titles off`): the window's title is the command that started the client (`tmux attach -t t1`), so the title says nothing of the session; the visible text holds every pane of the window, and with two `claude` side by side the text match chose the pane that was not active (wrong in 2 of 3 steps with panes). The status line shows the tmux session (`[t1]`), and `tmux display -p -t t1 '#{pane_tty}'` gave the tty of the active pane, whose `claude` was the right one in 3 of 3 steps, also after a pane change. tmux with `set-titles on`: the title is `t1:0:<command> - "✳ <name>"`, and the title match was right in 2 of 2. screen: it would not attach in Ghostty without `TERM=xterm-256color` (no terminfo for `xterm-ghostty`), its title is the command that started it, and its text came out garbled (UTF-8), so neither the title nor the text named the session.
- 2026-10-27, a terminal's processes in the snapshot (Terminal and iTerm2, macOS 27): a tab runs `login`, owned by root, between the terminal and its shell; `proc_pidinfo` refused it, so the snapshot's process list was empty and the tab's `claude` was not found. With the parents from the kernel's process table (`sysctl` KERN_PROC_ALL) the list was `login`, `zsh`, `claude`, and `claude-code` claimed the tab by its title in both terminals (one run each).

## Distribution

- 2026-10-25: the package was about 217 MB; the stack from the package recognized a 49 s recording on the test server with no outside connections.
- 2026-10-25: onnxruntime 1.31 connected to Microsoft telemetry (20.42.65.85, by whois) at the start of the VAD. 2026-10-26: bare onnxruntime opened a connection to 4.150.223.99 (Microsoft) within 25 s of creating the VAD model; through `vad.py`, with the switch, no outside connection in 25 s.
- 2026-10-25: the first notarization request of the new team was still `In Progress` after 5 minutes, and the run that waited for it was cancelled; it was `Accepted` when checked about two hours later, at an unknown time in between. 2026-10-26: two submissions were accepted in about 72 s and 66 s (from the submission to the webhook's start of `staple.yml`). A tag push to a published release took about 4 minutes.
- 2026-10-26, compression of one package on the M5; the open time is the best of three copies of the app out of the mounted image:

| Format | Size | Open |
|---|---|---|
| UDZO (zlib), from `hdiutil create` | 115.4 MB | — |
| UDZO (zlib), `hdiutil convert` | 79.0 MB | 1.35 s |
| ULFO (lzfse) | 69.0 MB | 1.20 s |
| ULMO (lzma) | 53.3 MB | 2.79 s |
| UDBZ (bzip2) | 65.0 MB | 4.53 s |

  The dmg from dmgbuild with ULMO was 58.8 MB, as the package by then had the icon's `Assets.car`.
- 2026-10-26, model download from Hugging Face on the home link: 192 MB of the Q4_0 file per try, each try its own part of the file, 3 rounds in random order. One connection: 73.4, 78.8 and 71.7 MB/s; four: 64.4, 70.3 and 75.8 MB/s; eight: 60.5, 61.8 and 78.2 MB/s. No gain from more connections was measured. Another link can differ.
- 2026-10-26, `otool -l`: the bundled llama-server had `minos 27.0` (cmake had no deployment target), and 21 of the bundled Python libraries `minos 14.0`, while `Info.plist` claimed macOS 13.
- 2026-10-26, M5, macOS 27.0.1: the v0.1 package, run without `PYTHONDONTWRITEBYTECODE`, wrote `__pycache__` into `Resources/server` and the standard library, and its signature check failed; the stripped Python build carries bytecode only for the pip packages (944 of 2005 `.py` files). The new package, bytecode compiled before signing: the test server without the variable recognized `speech-ru.wav`, wrote no file into the package, and the check passed. Importing the server's modules took 0.26 s without the standard library's bytecode and 0.07 s with it (5 runs each). The cost: the app grew by 20.8 MB, the dmg from 58.9 to 64.6 MB.
- 2026-10-26, macOS 27.0.1, test agents, about 2 minutes: after its program was deleted, launchd ended the agent once with exit code 78 (EX_CONFIG) and did not start it again, with `KeepAlive` true and with `KeepAlive.PathState`. Older macOS not checked.
- 2026-10-27, a local build (config format 11) opened on the development Mac brought `~/.echofox/config.json` from version 9 to 11; the only change in the file was the number. The installed 0.5.0, whose server read only version 9, then ignored the whole file: every adapter was off, and five dictations went without context until it was noticed. This led to the rules in [the design](design.md#the-config-file-over-versions).
- 2026-10-26, macOS 27.0.1: an app icon from a plain `.icns` was drawn small on a gray tile, whatever its layout; an Icon Composer icon compiled by `actool` into `Assets.car` filled the system's shape.

## Recordings

- Recordings take about 231 MB per hour of speech (365 recordings, 2026-10-22 to 2026-10-25); the audio is stored twice, in `mic.wav` and in the pieces.
- The labeled history on the development Mac: 659 pieces, 167 minutes, over five days.
