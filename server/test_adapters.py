"""Tests of the adapters (adapters/): the surfaces and their matching, the snapshot's helpers, Claude Code transcripts,
Claude Desktop, Claude chats, Telegram, and the check tool. Run: server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import asyncio
import importlib.util
import json
import os
import pathlib
import tempfile
import threading
import time
import sys
import unittest

import adapters
from adapters import markdown, registry, screen, surfaces  # noqa: F401

DESKTOP = "com.anthropic.claudefordesktop"
TELEGRAM = "com.tdesktop.Telegram"


def reply(mid, text, stop="end_turn", **extra):
    return {"type": "assistant", **extra, "message": {"id": mid, "stop_reason": stop, "content": [{"type": "text", "text": text}]}}


def as_file(snapshot):
    """A test's snapshot ({"identity", "content": the parts read}) as macos echofox-snapshot prints it when its flags
    say what to read: the parts under the surface "snapshot"."""
    return {"identity": snapshot.get("identity") or {}, "content": {"surfaces": {"snapshot": snapshot.get("content") or {}}}}


def found(snapshot, enabled=None):
    """What the server finds for a test's snapshot ({"identity", "content": the parts read}): the identity matched with
    the surfaces of the enabled adapters (None: every working one), each given the parts, as the app sends them for
    each surface."""
    identity, content = snapshot.get("identity") or {}, snapshot.get("content") or {}
    matched = adapters.match(identity, enabled if enabled is not None else list(registry.packages()))
    return adapters.context(identity, matched, {s.name: content for s in matched})


def merged(snapshot):
    """The snapshot an adapter gets: the identity and the content."""
    return {**snapshot.get("content", {}), **snapshot["identity"]}


def as_sent(nodes, skip):
    """The outline's nodes as the app sends them for a surface with this skip list: an element whose role or one of
    whose DOM classes is in it goes in marked "skipped", without its children."""
    out, under = [], None
    for n in nodes:
        if under is not None and n["depth"] > under:
            continue
        under = None
        if n.get("role") in skip or set(n.get("domClasses") or []) & set(skip):
            n, under = {**n, "skipped": True}, n["depth"]
        out.append(n)
    return out


class Fixture(unittest.TestCase):
    """A temporary ~/.claude/projects and Desktop session store."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.projects, self.store = os.path.join(self.dir.name, "projects"), os.path.join(self.dir.name, "store")
        for p in ("a", "b"):
            os.makedirs(os.path.join(self.projects, p))
        os.makedirs(os.path.join(self.store, "org", "account"))
        self.running = os.path.join(self.dir.name, "sessions")
        os.makedirs(self.running)
        self.saved = {k: os.environ.get(k) for k in ("ECHOFOX_PROJECTS", "ECHOFOX_DESKTOP_SESSIONS",
                                                      "ECHOFOX_ADAPTERS", "ECHOFOX_CLAUDE_SESSIONS")}
        os.environ.update(ECHOFOX_PROJECTS=self.projects, ECHOFOX_DESKTOP_SESSIONS=self.store,
                          ECHOFOX_ADAPTERS=os.path.join(self.dir.name, "adapters"), ECHOFOX_CLAUDE_SESSIONS=self.running)

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.dir.cleanup()

    def put(self, project, session, lines, age=0, tail=""):
        f = os.path.join(self.projects, project, f"{session}.jsonl")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lines) + tail)
        t = time.time() - age
        os.utime(f, (t, t))
        return f

    def desktop_record(self, desktop_id, cli, title, cwd="/x"):
        with open(os.path.join(self.store, "org", "account", f"{desktop_id}.json"), "w") as fh:
            json.dump({"sessionId": desktop_id, "cliSessionId": cli, "cwd": cwd, "title": title}, fh)

    def claude_running(self, pid, session, name, entrypoint="cli"):
        """A running claude's file in ~/.claude/sessions, as Claude Code 2.1.300 writes it (the fields used)."""
        with open(os.path.join(self.running, f"{pid}.json"), "w", encoding="utf-8") as fh:
            json.dump({"pid": pid, "sessionId": session, "cwd": "/x", "kind": "interactive", "entrypoint": entrypoint,
                       "name": name, "status": "idle"}, fh, ensure_ascii=False)

    def install(self, name, manifest=None, code=None):
        """A user's adapter in the adapters' folder; by default one surface in com.example.app."""
        d = os.path.join(os.environ["ECHOFOX_ADAPTERS"], name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "adapter.json"), "w") as f:
            json.dump(manifest if manifest is not None else user_manifest(name), f)
        with open(os.path.join(d, "adapter.py"), "w") as f:
            f.write(code if code is not None else (
                "from adapters import Adapter\n"
                "class Mine(Adapter):\n"
                "    def context(self, surface, snapshot):\n"
                "        return {'about': 'a chat with Anna', 'terms': ['Anna'], 'messages': [{'from': 'Anna', 'text': '**Hello** Kubernetes'}]}\n"
                "    def clean(self, text):\n"
                "        return text.replace('**', '')\n"))


def user_manifest(name, **surface):
    return {"name": name, "version": "1.0", "interface": 3,
            "surfaces": [{"id": "main", "title": "Main", "apps": ["com.example.app"], **surface}]}


EXAMPLE = {"identity": {"app": {"bundleId": "com.example.app"}}}


def terminal(title, pids, bundle="com.mitchellh.ghostty"):
    """A recorded snapshot of a terminal: the focused window's title and the app's processes."""
    return {"identity": {"app": {"bundleId": bundle, "pid": 100}, "window": {"title": title}},
            "content": {"processes": [{"pid": 101, "name": "zsh"}] + [{"pid": p, "name": "claude"} for p in pids]}}


def code_tab(desktop_id, title="Local Speech", panel=None):
    tab = {"identity": {"app": {"bundleId": DESKTOP}, "webArea": {"url": f"https://claude.ai/epitaxy/{desktop_id}",
                                                                  "title": f"{title} - Claude Code"}},
           "content": {}}
    if panel is not None:
        tab["content"]["outline"] = {"root": "webArea", "complete": True, "nodes": panel}
    return tab


def files_panel(*path):
    """The end of the Code tab's outline with the Files panel showing the file at `path` under the session's folder, as
    in a snapshot of Claude Desktop (2026-11-02), with the claude-code surface's skip list: the file tree and the page
    go in without their children."""
    return [{"depth": 15, "role": "AXGroup", "subrole": "AXLandmarkRegion", "description": "Files"},
            {"depth": 16, "role": "AXGroup"},
            {"depth": 17, "role": "AXOutline", "description": "Project files", "domClasses": ["group/file-tree"], "skipped": True},
            {"depth": 17, "role": "AXSplitter", "description": "Resize file tree"},
            {"depth": 16, "role": "AXGroup"}] \
        + [{"depth": 17, "role": "AXPopUpButton", "title": p} for p in path] \
        + [{"depth": 17, "role": "AXButton", "description": "View source"},
           {"depth": 17, "role": "AXGroup", "domClasses": ["flex-1", "select-text", "epitaxy-document-page"], "skipped": True},
           {"depth": 2, "role": "AXGroup", "subrole": "AXEmptyGroup"}]


class SurfacesTest(Fixture):
    def test_a_pattern_matches_the_whole_value_and_only_star_is_special(self):
        m = surfaces.matches
        self.assertTrue(m("https://claude.ai/chat/*", "https://claude.ai/chat/0f8e"))
        self.assertTrue(m("https://claude.ai/chat/*", "https://claude.ai/chat/"))       # * may be empty
        self.assertFalse(m("https://claude.ai/chat/*", "https://claude.ai/chats/1"))
        self.assertFalse(m("https://claude.ai/chat/*", "x https://claude.ai/chat/1"))   # the whole value
        self.assertFalse(m("claude.ai", "claudeXai"))                                    # . is a dot
        self.assertTrue(m("✳ *(1)?", "✳ Radio\nline(1)?"))                               # ( ) ? are themselves
        self.assertTrue(m("*", ""))
        self.assertFalse(m("*", None))

    def test_the_identity_matches_the_surfaces_of_the_enabled_adapters_by_app_address_and_title(self):
        self.install("titled", user_manifest("titled", match={"title": "✳ *"}))
        on = list(registry.packages())
        names = lambda identity, enabled=on: [s.name for s in adapters.match(identity, enabled)]  # noqa: E731
        code = {"app": {"bundleId": DESKTOP}, "webArea": {"url": "https://claude.ai/epitaxy/local_1"}}
        self.assertEqual(names(code), ["claude-code/desktop"])                   # not claude-chat's, another address
        self.assertEqual(names({**code, "webArea": {"url": "https://claude.ai/chat/1"}}), ["claude-chat/desktop"])
        self.assertEqual(names({"app": {"bundleId": DESKTOP}}), [])                # a rule without its value fails
        self.assertEqual(names({"app": {"bundleId": "com.apple.Terminal"}}), ["claude-code/terminal"])
        self.assertEqual(names(code, ["claude-chat", "telegram"]), [])             # claude-code is not enabled
        self.assertEqual(names({}), [])
        self.assertEqual(names({"app": {"bundleId": "com.example.app"}, "window": {"title": "✳ Radio"}}),
                         ["titled/main"])
        self.assertEqual(names({"app": {"bundleId": "com.example.app"}, "window": {"title": "Radio"}}), [])

    def test_the_read_request_resolves_each_budget_and_names_what_is_read(self):
        identity = lambda bundle, url=None: {"app": {"bundleId": bundle}, **({"webArea": {"url": url}} if url else {})}  # noqa: E731
        on = ["claude-code", "claude-chat", "telegram"]
        budget = lambda adapter, key: f"{adapter}.{key}"  # noqa: E731
        self.assertEqual(adapters.read(adapters.match(identity(DESKTOP, "https://claude.ai/epitaxy/local_1"), on), budget),
                         [{"surface": "claude-code/desktop", "outline": {
                             "skip": ["epitaxy-document-page", "group/file-tree", "epitaxy-chat-panel-body"],
                             "budget": None}}])  # no budget key: only the structural limits
        self.assertEqual(adapters.read(adapters.match(identity(DESKTOP, "https://claude.ai/chat/1"), on), budget),
                         [{"surface": "claude-chat/desktop", "outline": {
                             "skip": ["AXButton", "sr-only", "group/morph", "group/tag"],
                             "budget": "claude-chat.chatHistoryTokenBudget"}}])
        self.assertEqual(adapters.read(adapters.match(identity(TELEGRAM), on), budget),
                         [{"surface": "telegram/desktop", "lists": {"budget": "telegram.chatHistoryTokenBudget"}}])
        self.assertEqual(adapters.read(adapters.match(identity("com.mitchellh.ghostty"), on), budget),
                         [{"surface": "claude-code/terminal", "processes": {}}])

    def test_a_surface_gets_only_the_parts_it_declares_and_the_identity_wins(self):
        tg = adapters.match({"app": {"bundleId": TELEGRAM}}, ["telegram"])[0]
        sent = {"lists": [], "focusedFrame": {"x": 1}, "outline": {"nodes": []}, "processes": [], "app": {"bundleId": "x"}}
        self.assertEqual(tg.snapshot({"app": {"bundleId": TELEGRAM}}, sent),
                         {"app": {"bundleId": TELEGRAM}, "lists": [], "focusedFrame": {"x": 1}})
        asked = [{"surface": "a/b", "lists": {"budget": 5}}, {"surface": "c/d", "processes": {}}]
        self.assertEqual(surfaces.answer(asked, {"surfaces": {"snapshot": sent}}),  # read by echofox-snapshot's flags
                         {"a/b": {"lists": [], "focusedFrame": {"x": 1}}, "c/d": {"processes": []}})
        self.assertEqual(surfaces.answer(asked, {"surfaces": {"c/d": sent}}),  # read by surface (--read)
                         {"a/b": {}, "c/d": {"processes": []}})

    def test_more_than_one_context_is_no_context_and_the_errors_name_the_surfaces(self):
        self.install("one")
        self.install("two")
        c = found(EXAMPLE, ["one", "two"])
        self.assertNotIn("messages", c)
        self.assertIn("one/main, two/main", c["errors"][0])
        self.assertEqual(found(EXAMPLE, ["one"])["surface"], "one/main")


class ScreenTest(unittest.TestCase):
    NODES = [{"depth": 0, "role": "AXWebArea"}, {"depth": 1, "role": "AXGroup"}, {"depth": 2, "text": "a"},
             {"depth": 1, "role": "AXButton", "skipped": True}, {"depth": 1, "role": "AXGroup"},
             {"depth": 2, "text": "b"}, {"depth": 3, "text": "c"}, {"depth": 2, "skipped": True}, {"depth": 3, "text": "x"}]

    def test_the_outlines_walk_by_depth(self):
        n = self.NODES
        self.assertEqual((screen.end(n, 1), screen.end(n, 4), screen.end(n, 0)), (3, 9, 9))
        self.assertEqual(screen.children(n, 0), [1, 3, 4])
        self.assertEqual(screen.children(n, 4), [5, 7])
        self.assertEqual(screen.siblings_before(n, 4), [3, 1])
        self.assertEqual(screen.siblings_before(n, 7), [5])
        self.assertEqual([x.get("text") for x in screen.shown(n, 4) if x.get("text")], ["b", "c"])  # not under a skipped one

    def test_the_identitys_fields_and_a_broken_part_reads_as_empty(self):
        s = {"app": {"bundleId": "b"}, "window": {"title": "T"}, "webArea": {"url": "u", "title": "w"},
             "processes": [{"pid": 3}, "x", {"pid": "4"}], "lists": [{"rows": []}, {"rows": [1]}]}
        self.assertEqual((screen.bundle(s), screen.window_title(s), screen.web_url(s), screen.web_title(s)),
                         ("b", "T", "u", "w"))
        self.assertEqual((screen.pids(s), screen.lists(s)), ({3}, [{"rows": [1]}]))
        broken = {"app": "x", "window": None, "webArea": 1, "outline": [], "processes": "p"}
        self.assertEqual((screen.bundle(broken), screen.window_title(broken), screen.web_area(broken),
                          screen.nodes(broken), screen.processes(broken)), (None, "", {}, [], []))


class ClaudeCodeTest(Fixture):
    def test_only_claudes_final_replies_newest_first(self):
        self.put("b", "new", [
            {"type": "custom-title", "customTitle": "Тесты"},
            {"type": "user", "message": {"content": "Запусти тесты в CI"}},                       # the user: never
            reply("m1", "Запускаю npm test.", "tool_use"),                                        # between tool calls
            {"type": "assistant", "message": {"id": "m1", "stop_reason": "tool_use", "content": [{"type": "tool_use", "name": "Bash"}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "PASS 38 tests"}]}},
            reply("m2", "Тесты прошли: npm test, 38 из 38."),                                     # a final reply
            reply("m2", "<system-reminder>noise</system-reminder>Коммит в master готов."),         # same reply, next line
            reply("m3", "subagent", isSidechain=True),
            reply("m5", "<task-notification>done</task-notification>"),                          # only a tag: cleaned away
            {"type": "user", "message": {"content": [{"type": "text", "text": "Закоммить в master"}]}},
            reply("m4", "Запушил в master."),
        ], tail="not json\n")
        self.claude_running(201, "new", "Тесты")
        c = found(terminal("✳ Тесты", [201]))
        d = c["details"]
        self.assertEqual((c["adapter"], c["surface"], d["session"], d["how"], d["title"]),
                         ("claude-code", "claude-code/terminal", "new", "terminal title", "Тесты"))
        self.assertTrue(c["about"] and c["source"].startswith("terminal title: "))
        self.assertEqual(c["messages"], [{"from": "Claude", "text": "Запушил в master."},
                                         {"from": "Claude", "text": "Тесты прошли: npm test, 38 из 38.\nКоммит в master готов."}])
        self.assertEqual(c["terms"], ["master", "test", "npm"])

    def test_clean_takes_out_claude_codes_tags(self):
        clean = registry.packages()["claude-code"].adapter.clean
        self.assertEqual(clean("<system-reminder>x</system-reminder>**Готово**<ide_opened_file>a</ide_opened_file>"),
                         "Готово")
        self.assertEqual(clean("<command-name>/x</command-name>"), "")

    def test_no_session_is_guessed_from_the_app_alone(self):
        self.put("b", "code", [reply("m2", "из VS Code", entrypoint="claude-vscode")])
        for app in ("com.microsoft.VSCode", "com.mitchellh.ghostty", TELEGRAM, DESKTOP):
            self.assertIsNone(found({"identity": {"app": {"bundleId": app}}}), app)
        self.assertIsNone(found({}))

    def test_terms_are_latin_script_words_the_most_frequent_first_without_common_english_words(self):
        self.assertEqual(adapters.terms(["the GitHub Actions and GitHub", "use node.js, CI/CD and /Users/x/y/z.js"]),
                         ["GitHub", "CI/CD", "node.js", "Actions"])


class CleanTest(Fixture):
    def test_markdown_becomes_plain_prose(self):
        md = ("## Пропала пунктуация\n\n"
              "**Настройки перенесены.** Промпт совпадает, `options` те же: [README](README.md:12), https://x.y/z.\n"
              "Вторая строка абзаца.\n\n"
              "- **Окно.** Без рамки, `NSPanel`\n"
              "- второй пункт;\n"
              "1. третий\n\n"
              "| Контекст | Знаки |\n|---|---|\n| без контекста | 5 из 5 |\n\n"
              "```bash\nopen ~/x.app\n```\n"
              "> цитата _важная_ и snake_case_name\n\n---\n")
        self.assertEqual(adapters.markdown.plain(md), "\n".join([
            "Пропала пунктуация.",
            "Настройки перенесены. Промпт совпадает, options те же: README. Вторая строка абзаца.",
            "Окно. Без рамки, NSPanel.", "Второй пункт;", "Третий.",
            "Без контекста: 5 из 5.",
            "цитата важная и snake_case_name"]))
        self.assertEqual(adapters.markdown.plain("Следы (`**`, `|`, `- `) убраны, `a.py` остался."),
                         "Следы убраны, a.py остался.")

    def test_a_url_or_a_mark_in_inline_code_leaves_no_backticks(self):
        plain = adapters.markdown.plain
        self.assertEqual(plain("Страница на **`http://host.local:9000`**. Проверил."), "Страница на. Проверил.")
        self.assertEqual(plain("`rp-monitor` работает на `http://h:1`, флаг `--spec-type ngram-*`."),
                         "rp-monitor работает на, флаг --spec-type ngram-*.")
        self.assertEqual(plain("Открывай *http://a.b/c*, или *http://d.e*, а `https://…` как пример."),
                         "Открывай, или, а как пример.")
        self.assertEqual(plain("Код ``a `b` c`` и `x`."), "Код и x.")

    def test_inline_code_that_is_kept_stays_as_written(self):
        plain = adapters.markdown.plain
        # a real reply before the audio, 2026-11-02: it was "только.md и.markdown", and `..` was gone
        self.assertEqual(plain("только `.md` и `.markdown`"), "только .md и .markdown")
        self.assertEqual(plain("не Markdown, не `..` и не ссылка из папки"), "не Markdown, не .. и не ссылка из папки")
        self.assertEqual(plain("Файл: `.zshrc`, папка `~/`, корень `/`, здесь `.`."),
                         "Файл: .zshrc, папка ~/, корень /, здесь ..")
        self.assertEqual(plain("- `.md` и [`a.py`](a.py)"), ".md и a.py.")

    def test_names_in_other_scripts_are_terms_but_not_the_first_word_of_a_sentence(self):
        got = adapters.terms(["Поставь Убунту на ubu. Потом проверь Флинт и роутер.\nДальше Флинт снова."])
        self.assertEqual(got[0], "Флинт")  # twice; the others once
        self.assertIn("ubu", got)
        self.assertIn("Убунту", got)
        self.assertNotIn("Поставь", got)
        self.assertNotIn("Потом", got)
        self.assertNotIn("Дальше", got)

    def test_only_prose_lines_stay_in_a_message(self):
        text = "Ожидание упало заметно.\n20–40 с: 4,38 / 5,70 (n 158), 3,66 / 4,80 (n 47).\nДальше проверим."
        self.assertEqual(adapters.prose(text), "Ожидание упало заметно.\nДальше проверим.")

    def test_inline_code_that_is_code_goes_and_terms_stay(self):
        self.assertEqual(adapters.markdown.plain(
            'Шлёт `POST /cmd` с `{"text": "..."}`, потом `close()`, `a = 1` и `sudo apt install glances`; '
            'а `llama-server`, `~/.zshrc` и `push --force` — термины.'),
            "Шлёт POST /cmd с, потом, и; а llama-server, ~/.zshrc и push --force — термины.")

    def test_code_blocks_of_every_kind_and_html_go(self):
        md = ("Текст.\n\n````md\n```\nвнутри\n```\n````\n\n    отступ кода\n\n<details>\nблок html\n</details>\n\n"
              "- пункт\n\n  ```sh\n  rm -rf x\n  ```\n\n~~~\nтильды\n~~~\nКонец <b>жирный</b> ![схема](a.png) <http://x.y>.")
        self.assertEqual(adapters.markdown.plain(md), "Текст.\nПункт.\nКонец жирный схема.")

    def test_escapes_and_escaped_pipes_in_tables(self):
        md = ("| Команда | Аргументы |\n|---|---|\n| `media` | `action: pause\\|play` |\n"
              "| Звук \\| громкость | вверх\\|вниз |\n\n\\*Звёздочка\\* и X\\_C.")
        self.assertEqual(adapters.markdown.plain(md), "Media.\nЗвук | громкость: вверх|вниз.\n*Звёздочка* и X_C.")

    def test_links_of_any_scheme_keep_their_text_and_file_links_name_their_file(self):
        plain = adapters.markdown.plain
        self.assertEqual(plain("[Сайт](https://a.b/c?d=1), [почта](mailto:a@b.c), [код](javascript:x()), [верх](#top)."),
                         "Сайт, почта, код, верх.")
        # The file's name: without the query, the fragment and the line, %-escapes decoded; in brackets after a text
        # that does not name it, in place of no text
        self.assertEqual(plain("Смотри [план](file:///Users/a/My%20Plan.md#L3-L9), [](server/x.py:12:5), "
                               "[конфиг](~/.echofox/config.json?raw=1) и [папку](docs/)."),
                         "Смотри план (My Plan.md), x.py, конфиг (config.json) и папку (docs).")
        self.assertEqual(plain("Правка в [`settings.py`](server/settings.py#L40) и [docs/a.md:5](docs/a.md#L5)."),
                         "Правка в settings.py и docs/a.md:5.")
        # Bare URLs go, as before; a file: URL too
        self.assertEqual(plain("Ссылка <https://q.r>, https://s.t и <file:///tmp/a.txt>."), "Ссылка, и.")

    def test_a_word_with_a_small_letter_on_purpose_stays_small(self):
        md = "- iPhone можно подключить\n- macOS: тесты\n- a.py изменён\n- обычный пункт"
        self.assertEqual(adapters.markdown.plain(md), "iPhone можно подключить.\nmacOS: тесты.\na.py изменён.\nОбычный пункт.")

    def test_every_adapter_cleans_and_the_terms_come_from_clean_text(self):
        self.put("a", "s", [reply("m1", "Смотри `FocusSnapshot`:\n```\nlet secretVar = take()\n```"),
                            reply("m2", "```\nonlyCode()\n```")])
        self.claude_running(201, "s", "Код")
        c = found(terminal("✳ Код", [201]))
        self.assertEqual(c["messages"], [{"from": "Claude", "text": "Смотри FocusSnapshot:"}])  # code only: dropped
        self.assertEqual(c["terms"], ["FocusSnapshot"])
        for p in registry.packages().values():
            self.assertIsInstance(p.adapter, adapters.Adapter)

    def test_documents_are_cleaned_and_terms_stay_without_messages(self):
        class Docs(adapters.Adapter):
            name = "docs"
            def context(self, surface, snapshot): return self.found
            def clean(self, t):
                if t == "boom":
                    raise RuntimeError("boom")
                return t.strip()
        a = Docs()
        on = [surfaces.Surface("docs", "main", {"id": "main", "title": "Main", "apps": ["x"]}, a)]
        a.found = {"terms": ["Anna"], "documents": [
            {"name": " a.md ", "text": " One. "}, {"text": "no name"}, {"name": "", "text": "empty name"}, "a string",
            {"name": "empty.md", "text": "   "}, {"name": "b.md", "text": "Two."}]}
        c = adapters.context({}, on)
        self.assertEqual(c["documents"], [{"name": "a.md", "text": "One."}, {"name": "b.md", "text": "Two."}])
        self.assertEqual(c["terms"], ["Anna"])  # no messages: the adapter's terms stay
        self.assertNotIn("messages", c)
        a.found = {"documents": [{"name": "a.md", "text": "One."}, {"name": "x", "text": "boom"},
                                 {"name": "c.md", "text": "Three."}]}
        with self.assertLogs("echofox-server", "ERROR"):
            c = adapters.context({}, on)
        self.assertEqual(c["documents"], [{"name": "a.md", "text": "One."}])  # none after the failed clean
        self.assertIn("docs.clean: RuntimeError: boom", c["errors"])

    def test_an_adapter_without_clean_cannot_be_made(self):
        class NoClean(adapters.Adapter):
            def context(self, surface, snapshot): return None
        with self.assertRaises(TypeError):
            NoClean()


class ClaudeTerminalTest(Fixture):
    """Claude Code in a terminal's tab: the session whose name the window's title shows, among the terminal's
    processes (docs/observations.md, 2026-10-27)."""

    def test_the_tab_in_focus_gives_its_session_by_the_title(self):
        self.put("a", "s-radio", [reply("m1", "Антенна готова.")])
        self.put("a", "s-map", [reply("m2", "Карта собрана.")])
        self.claude_running(201, "s-radio", "Radio Physics")
        self.claude_running(202, "s-map", "Карта эфира")
        c = found(terminal("✳ Карта эфира", [201, 202]))
        self.assertEqual((c["adapter"], c["details"]["session"], c["details"]["how"], c["messages"][0]["text"]),
                         ("claude-code", "s-map", "terminal title", "Карта собрана."))
        # Terminal adds the folder, the command and the size around the title
        c = found(terminal("alex — ✳ Radio Physics — claude --resume s-radio — 120×30", [201, 202], "com.apple.Terminal"))
        self.assertEqual(c["details"]["session"], "s-radio")

    def test_no_sure_session_is_no_context(self):
        self.put("a", "s1", [reply("m1", "x")])
        self.claude_running(201, "s1", "Radio")
        self.claude_running(202, "s2", "Radio Physics")
        self.claude_running(203, "s3", "Desk", entrypoint="claude-desktop")
        self.assertIsNone(found(terminal("✳ Radio Physics", [201, 202])))  # both names are in the title
        self.assertIsNone(found(terminal("~", [201])))                     # a shell tab
        self.assertIsNone(found(terminal("✳ Radio", [])))                  # in tmux: not the app's process
        self.assertIsNone(found(terminal("✳ Desk", [203])))                # Desktop's, not a terminal's
        self.assertIsNone(found(terminal("✳ Radio", [201], "com.example.editor")))  # not a terminal

    def test_a_new_session_without_a_transcript_is_found_with_no_messages(self):
        self.claude_running(201, "fresh", "echofox-cc")
        c = found(terminal("✳ echofox-cc", [201]))
        self.assertEqual((c["adapter"], c["details"]["session"]), ("claude-code", "fresh"))
        self.assertNotIn("messages", c)


class UserAdapterTest(Fixture):
    def test_a_users_adapter_in_the_folder_works_once_enabled(self):
        self.install("mine")
        self.assertIsNone(found(EXAMPLE, enabled=[]))  # the base mode: no adapter enabled
        self.assertIsNone(found(EXAMPLE, enabled=["claude-code"]))
        c = found(EXAMPLE, enabled=["mine"])
        self.assertEqual((c["adapter"], c["surface"], c["about"], c["messages"][0], c["terms"]),
                         ("mine", "mine/main", "a chat with Anna", {"from": "Anna", "text": "Hello Kubernetes"},
                          ["Anna", "Kubernetes", "Hello"]))
        self.assertEqual(registry.packages()["mine"].info({"mine"})["surfaces"], user_manifest("mine")["surfaces"])

    def test_a_broken_adapter_stops_only_itself_and_says_why(self):
        self.install("old", {"name": "old", "version": "1.0", "interface": 2, "apps": ["com.example.app"]})
        self.install("twice", code="from adapters import Adapter\n")
        self.install("crash", code="raise RuntimeError('boom')\n")
        found_ = registry.packages()
        self.assertIn("interface 2", found_["old"].error)
        self.assertEqual(found_["old"].info({"old"})["surfaces"], [])
        self.assertIn("0 subclasses", found_["twice"].error)
        self.assertIn("boom", found_["crash"].error)
        self.assertIsNotNone(found_["claude-code"].adapter)
        self.assertFalse(found_["crash"].info({"crash"})["enabled"])
        self.assertEqual(found(EXAMPLE, ["crash", "old"]), None)  # a broken adapter's surfaces never match

    def test_a_manifest_follows_the_schemas_rules(self):
        base = user_manifest("peek")
        cases = [({**base, "surfaces": []}, "surfaces"),
                 ({**base, "version": 1}, "version"),
                 ({**base, "surfaces": [{"id": "Main", "title": "M", "apps": ["x"]}]}, "id"),
                 ({**base, "surfaces": [{"id": "m", "apps": ["x"]}]}, "title"),
                 ({**base, "surfaces": [{"id": "m", "title": "M", "apps": []}]}, "apps"),
                 ({**base, "surfaces": [{"id": "m", "title": "M", "apps": ["x"], "outlineSkip": []}]}, "outlineSkip"),
                 ({**base, "surfaces": [{"id": "m", "title": "M", "apps": ["x"]}] * 2}, "repeat"),
                 (user_manifest("peek", match={"address": "x"}), "address"),
                 (user_manifest("peek", screen={"everything": {}}), "everything"),
                 (user_manifest("peek", screen={"outline": {"skip": "AXButton"}}), "skip"),
                 (user_manifest("peek", screen={"lists": {"budget": "proseOnly"}}), "proseOnly"),  # not a token budget
                 (user_manifest("peek", screen={"lists": {"budget": "pieceSeconds"}}), "pieceSeconds"),  # not the adapter's
                 (user_manifest("peek", screen={"processes": {"cwd": True}}), "cwd"),
                 (user_manifest("peek", reads=["~/x"]), "reads"),
                 (user_manifest("peek", reads=[{"path": "~/x"}]), "what"),
                 ({**base, "context": {"pieceSeconds": 5}}, "pieceSeconds")]
        for manifest, why in cases:
            self.install("peek", manifest)
            self.assertIn(why, registry.packages()["peek"].error or "", manifest)
        self.install("peek", user_manifest("peek", treeOnRequest=True, match={"url": "https://x/*", "title": "*"},
                                           screen={"outline": {"skip": ["AXButton"], "budget": "chatHistoryTokenBudget"},
                                                   "lists": {}, "processes": {}},
                                           reads=[{"what": "a file"}, {"path": "~/x", "what": "x"}]))
        self.assertIsNone(registry.packages()["peek"].error)

    def test_an_adapter_that_fails_stops_only_itself_and_the_error_is_kept(self):
        base = ("from adapters import Adapter\n"
                "class P(Adapter):\n"
                "    def context(self, surface, snapshot):\n        {context}\n"
                "    def clean(self, text):\n        {clean}\n")
        msgs = "return {'about': 'a', 'messages': [{'from': 'A', 'text': 'one'}, {'from': 'A', 'text': 'two'}]}"
        self.install("badcontext", code=base.format(context="raise KeyError('k')", clean="return text"))
        self.install("good", code=base.format(context=msgs, clean="return text"))
        with self.assertLogs("echofox-server", "ERROR") as logs:
            c = found(EXAMPLE, ["badcontext", "good"])
        self.assertIn("adapter badcontext: context failed", logs.output[0])
        self.assertEqual((c["adapter"], len(c["messages"])), ("good", 2))
        self.assertIn("badcontext.context: KeyError", c["errors"][0])
        with self.assertLogs("echofox-server", "ERROR"):
            self.assertEqual(found(EXAMPLE, ["badcontext"]), {"errors": ["badcontext.context: KeyError: 'k'"]})
        self.install("badclean", code=base.format(context=msgs, clean="raise ValueError('v')"))
        with self.assertLogs("echofox-server", "ERROR") as logs:
            c = found(EXAMPLE, ["badclean"])
        self.assertIn("adapter badclean: clean failed", logs.output[0])
        self.assertEqual(c["messages"], [])
        self.assertIn("badclean.clean: ValueError: v", c["errors"])

    def test_a_users_adapter_replaces_a_built_in_one_of_the_same_name(self):
        self.install("claude-code", user_manifest("claude-code"))
        self.assertFalse(registry.packages()["claude-code"].builtin)


class ClaudeDesktopTest(Fixture):
    def test_the_code_tab_url_leads_through_the_desktop_store_to_the_transcript(self):
        self.put("a", "cli-1", [{"type": "custom-title", "customTitle": "Local Speech"}, reply("m1", "Готово.")], age=60)
        self.put("b", "other", [reply("m2", "другая сессия", entrypoint="claude-desktop")])  # newer, but not on screen
        self.desktop_record("local_abc", "cli-1", "Local Speech")
        c = found(code_tab("local_abc"))
        d = c["details"]
        self.assertEqual((c["adapter"], c["surface"], d["how"], d["session"], d["desktopSession"]),
                         ("claude-code", "claude-code/desktop", "desktop store", "cli-1", "local_abc"))
        self.assertEqual(c["messages"], [{"from": "Claude", "text": "Готово."}])

    def test_without_a_record_the_title_finds_the_transcript(self):
        self.put("a", "cli-2", [{"type": "custom-title", "customTitle": "Local Speech"}, reply("m1", "По названию.")], age=60)
        self.put("b", "other", [reply("m2", "другая", entrypoint="claude-desktop")])
        c = found(code_tab("local_missing"))
        self.assertEqual((c["details"]["how"], c["details"]["session"]), ("title", "cli-2"))

    def test_desktop_without_the_code_tab_in_focus_gives_no_context(self):
        self.put("b", "newest", [reply("m2", "свежая", entrypoint="claude-desktop")])
        self.assertIsNone(found({"identity": {"app": {"bundleId": DESKTOP}}}))  # no Accessibility, another window, …
        self.assertIsNone(found({"identity": {"app": {"bundleId": DESKTOP}, "webArea": {"url": "https://claude.ai/chat/1"}}},
                                enabled=["claude-code"]))  # a chat is claude-chat's
        self.assertIsNone(found({"identity": {"app": {"bundleId": DESKTOP},
                                              "webArea": {"url": "https://claude.ai/epitaxy/new"}}}))  # no session id

    def test_a_title_that_several_transcripts_share_gives_no_messages(self):
        for n in ("t1", "t2"):
            self.put("a", n, [{"type": "custom-title", "customTitle": "Same"}, reply("m", "x")])
        c = found(code_tab("local_missing", title="Same"))
        self.assertEqual(c["adapter"], "claude-code")
        self.assertNotIn("messages", c)

    def test_the_markdown_file_that_the_files_panel_shows_goes_in_whole_from_the_session_folder(self):
        folder = os.path.join(self.dir.name, "repo")
        os.makedirs(os.path.join(folder, "docs", "reference"))
        with open(os.path.join(folder, "docs", "reference", "4-app.md"), "w", encoding="utf-8") as fh:
            fh.write("# Use the Mac app\n\nTap **right Option** to start.\n")
        with open(os.path.join(folder, "main.swift"), "w") as fh:
            fh.write("let x = 1\n")
        self.put("a", "cli-1", [reply("m1", "Готово.")])
        self.desktop_record("local_abc", "cli-1", "Local Speech", cwd=folder)
        c = found(code_tab("local_abc", panel=files_panel("docs", "reference", "4-app.md")))
        self.assertEqual(c["documents"], [{"name": "docs/reference/4-app.md",
                                           "text": "Use the Mac app.\nTap right Option to start."}])
        self.assertEqual((c["details"]["openFile"], c["messages"][0]["text"]), ("docs/reference/4-app.md", "Готово."))
        for panel in (files_panel("main.swift"),             # not Markdown
                      files_panel("docs", "gone.md"),         # no such file
                      files_panel("..", "repo", "x.md"),      # not under the folder
                      files_panel(),                          # no path before the page
                      files_panel("docs", "reference", "4-app.md")[:-3]):  # no page: the panel shows no file
            self.assertNotIn("documents", found(code_tab("local_abc", panel=panel)), panel[-3:])

    def test_a_link_out_of_the_session_folder_is_not_followed(self):
        folder, outside = os.path.join(self.dir.name, "repo"), os.path.join(self.dir.name, "secret.md")
        os.makedirs(folder)
        with open(outside, "w") as fh:
            fh.write("secret\n")
        os.symlink(outside, os.path.join(folder, "notes.md"))
        self.desktop_record("local_abc", "cli-1", "Local Speech", cwd=folder)
        self.assertNotIn("documents", found(code_tab("local_abc", panel=files_panel("notes.md"))))

    def test_a_bad_desktop_id_reads_no_file(self):
        registry.packages()  # loads the adapter's package
        self.assertIsNone(sys.modules["echofox_adapter_claude_code.desktop"].record("local_../../etc"))


CHAT = "0f8e2a6c-1b3d-4e5f-8a7b-9c0d1e2f3a4b"
CHAT_SKIP = ["AXButton", "sr-only", "group/morph", "group/tag"]  # the claude-chat surface's skip list


def node(depth, role, classes=(), label=None, text=None):
    n = {"depth": depth, "role": role}
    if classes:
        n["domClasses"] = list(classes)
    if label:
        n["description"] = label
    if text is not None:
        n["text"] = text
    return n


def chat_message(depth, n, total, own, lines):
    """A message of a Claude Desktop chat as its outline has it (measured 2026-10-25, Claude Desktop 3.6556.2)."""
    out = [node(depth, "AXGroup", ["rounded-lg"], f"Message {n} of {total}")]
    heading = ("You said: " if own else "Claude responded: ") + lines[0][:20]
    if own:
        out += [node(depth + 1, "AXHeading", ["sr-only", "select-none"]), node(depth + 2, "AXStaticText", text=heading),
                node(depth + 1, "AXGroup", ["relative", "flex"]),
                node(depth + 2, "AXGroup", ["whitespace-pre-wrap", "break-words"]),
                node(depth + 3, "AXStaticText", text="\n".join(lines))]
    else:
        d = depth + 1
        out += [node(d, "AXGroup", ["group/message-row", "relative"]),
                node(d + 1, "AXHeading", ["sr-only", "select-none"]), node(d + 2, "AXStaticText", text=heading),
                node(d + 1, "AXGroup", ["flex", "text-start"]),  # a tool's status row
                node(d + 2, "AXGroup", ["group/morph", "inline-grid"]), node(d + 3, "AXStaticText", text="Searched the web"),
                node(d + 2, "AXButton", ["cds-reset"], "Searched the web"),
                node(d + 1, "AXGroup", ["sr-only"]), node(d + 2, "AXStaticText", text="Searched the web"),
                node(d + 1, "AXGroup"), node(d + 2, "AXStaticText", text=lines[0])]
        if len(lines) > 1:
            out.append(node(d + 1, "AXList"))
            for item in lines[1:]:
                out += [node(d + 2, "AXGroup"), node(d + 3, "AXListMarker", text="• "),
                        node(d + 3, "AXStaticText", text=item[:6]),
                        node(d + 3, "AXGroup"), node(d + 4, "AXLink", ["underline"], item[6:]),
                        node(d + 5, "AXStaticText", text=item[6:]),
                        node(d + 3, "AXGroup", ["inline-flex"]), node(d + 4, "AXLink", ["group/tag"], "source"),
                        node(d + 5, "AXStaticText", text="source")]
        out.append(node(d, "AXButton", ["sr-only"], "Show message actions"))
    out.append(node(depth + 1, "AXButton", ["sr-only"], "Show message actions"))
    return out


def chat_snapshot(messages, complete=True, title="Выгрузка данных"):
    """A recorded snapshot of a Claude Desktop chat, its outline as the app sends it for the claude-chat surface."""
    nodes = [node(0, "AXWebArea"), node(1, "AXGroup", label="Sidebar"), node(2, "AXStaticText", text="Recents"),
             node(1, "AXGroup", label="Chat messages")]
    for i, (own, lines) in enumerate(messages, 1):
        nodes += chat_message(2, i, len(messages), own, lines)
    nodes += [node(1, "AXTextArea", ["ProseMirror"], "Write your prompt to Claude")]
    return {"identity": {"app": {"bundleId": DESKTOP},
                         "webArea": {"url": f"https://claude.ai/chat/{CHAT}", "title": f"{title} - Claude"}},
            "content": {"outline": {"root": "webArea", "complete": complete, "nodes": as_sent(nodes, CHAT_SKIP)}}}


class ClaudeChatTest(Fixture):
    def chat(self):
        registry.packages()  # loads the adapter's package
        return sys.modules["echofox_adapter_claude_chat.chat"]

    def test_a_chat_gives_claudes_replies_newest_first_without_hidden_parts_buttons_and_chips(self):
        c = found(chat_snapshot([(True, ["Как выгрузить данные?"]),
                              (False, ["Напишите в поддержку.", "Пишите Data Protection Officer"]),
                              (True, ["А кто уже пробовал?"]),
                              (False, ["Отчётов нет."])]))
        self.assertEqual((c["adapter"], c["surface"], c["details"]["replies"]), ("claude-chat", "claude-chat/desktop", 2))
        self.assertEqual(c["messages"], [{"from": "Claude", "text": "Отчётов нет."},
                                         {"from": "Claude", "text": "Напишите в поддержку. • Пишите Data Protection Officer"}])  # clean joins the lines
        self.assertEqual(c["about"], "a chat with Claude, an AI assistant, titled “Выгрузка данных”")

    def test_the_speakers_messages_are_read_but_left_out_of_the_context(self):
        snapshot = merged(chat_snapshot([(True, ["Первая строка", "вторая"]), (False, ["Ответ."])]))
        self.assertEqual(self.chat().messages(screen.nodes(snapshot)),
                         [{"from": "the speaker", "text": "Первая строка\nвторая"}, {"from": "Claude", "text": "Ответ."}])

    def test_the_parser_leaves_out_what_the_app_marked_skipped(self):
        nodes = merged(chat_snapshot([(False, ["Ответ."])]))["outline"]["nodes"]
        at = next(i for i, n in enumerate(nodes) if n.get("text") == "Ответ.")
        nodes[at - 1]["skipped"] = True  # the paragraph's group, as if the skip list named it; its text stays here
        self.assertEqual(self.chat().messages(nodes), [])

    def test_a_cut_outline_skips_the_message_it_starts_in(self):
        focus = chat_snapshot([(False, ["Старый ответ."]), (False, ["Новый ответ."])], complete=False)
        nodes = focus["content"]["outline"]["nodes"]
        start = next(i for i, n in enumerate(nodes) if n.get("description") == "Message 1 of 2")
        focus["content"]["outline"]["nodes"] = nodes[start + 3:]  # the walk stopped inside message 1
        c = found(focus)
        self.assertEqual(c["messages"], [{"from": "Claude", "text": "Новый ответ."}])
        self.assertFalse(c["details"]["outlineComplete"])

    def test_a_chat_without_an_outline_is_found_with_no_messages(self):
        focus = chat_snapshot([])
        del focus["content"]["outline"]
        c = found(focus)
        self.assertEqual((c["adapter"], c["details"]["replies"]), ("claude-chat", 0))


def tg_row(lines, columns):
    return {"text": "\n".join(lines), "columns": columns}


def tg_snapshot(rows, title="Anna – (3)", others=True):
    """A recorded snapshot of Telegram Desktop: the chat list on the left, the messages above the box."""
    lists = [{"frame": {"x": 540, "y": -847, "width": 972, "height": 1684}, "rowCount": len(rows) + 20, "rows": rows}]
    if others:
        lists.append({"frame": {"x": 0, "y": 124, "width": 540, "height": 26744}, "rowCount": 393,
                      "rows": [tg_row(["Bob", "see you", "Received at 9:00"], ["Sender", "Message", "Time"])] * 5})
    return {"identity": {"app": {"bundleId": TELEGRAM}, "window": {"title": title}},
            "content": {"focusedFrame": {"x": 590, "y": 847, "width": 826, "height": 31}, "lists": lists}}


# Rows as Telegram Desktop's MessageAccessibilityName writes them (see adapters/builtin/telegram/desktop.py).
IN = ["Sender", "Message", "Delivery", "Time"]
OUT = ["Seen", "Sender", "Message", "Delivery", "Time"]
TG_ROWS = [
    {"text": "Anna joined the group"},  # a service message: one line, no cells
    tg_row(["Anna", "Привет! Как дела с Kubernetes?", "Received at 10:42"], IN),
    tg_row(["Seen", "You", "Всё ок, деплою", "Sent at 10:43"], OUT),
    tg_row(["Anna", "Photo", "Смотри, что вышло в 10:30", "Received at 10:44"], ["Sender", "Media type", "Message", "Delivery", "Time"]),
    tg_row(["Anna", "Первая строка", "вторая строка", "Received edited at 10:45", "👍 2"], IN + ["Reactions"]),
    tg_row(["Not seen", "You", "Ещё не прочитано", "Sent at 10:46"], OUT),
]


class TelegramTest(Fixture):
    def desktop(self):
        registry.packages()  # loads the adapter's package
        return sys.modules["echofox_adapter_telegram.desktop"]

    def test_the_rows_become_messages_with_the_speakers_own_and_without_the_status(self):
        self.assertEqual(self.desktop().messages(TG_ROWS), [
            {"from": "Anna", "text": "Привет! Как дела с Kubernetes?"},
            {"from": "the speaker", "text": "Всё ок, деплою"},
            {"from": "Anna", "text": "Photo\nСмотри, что вышло в 10:30"},
            {"from": "Anna", "text": "Первая строка\nвторая строка"},
            {"from": "the speaker", "text": "Ещё не прочитано"},
        ])

    def test_the_chat_name_comes_from_the_window_title(self):
        desktop = self.desktop()
        for title, name in [("Anna – (3)", "Anna"), ("(2) Anna", "Anna"), ("Anna @ Work (3)", "Anna"),
                            ("Telegram (5)", None), ("Telegram", None), ("", None), ("Dev team", "Dev team"),
                            ("⁨Anna⁩ – (3)", "Anna"), ("(2) ⁨Dev team⁩", "Dev team")]:
            self.assertEqual(desktop.chat_name(title), name, title)

    def test_the_message_list_is_the_one_above_the_input_box(self):
        desktop = self.desktop()
        self.assertIs(desktop.message_list(merged(tg_snapshot(TG_ROWS)))["rows"], TG_ROWS)
        no_box = tg_snapshot(TG_ROWS)
        no_box["content"].pop("focusedFrame")
        self.assertIs(desktop.message_list(merged(no_box))["rows"], TG_ROWS)  # the widest list

    def test_telegram_gives_the_open_chat_newest_first(self):
        c = found(tg_snapshot(TG_ROWS), ["telegram", "claude-code", "claude-chat"])
        self.assertEqual((c["adapter"], c["about"]), ("telegram", "a Telegram chat with Anna"))
        self.assertEqual([m["text"] for m in c["messages"]][:2], ["Ещё не прочитано", "Первая строка вторая строка"])
        self.assertEqual(c["terms"][:1], ["Anna"])
        self.assertEqual(c["details"]["messages"], 5)
        self.assertIsNone(found(tg_snapshot(TG_ROWS), ["claude-code", "claude-chat"]))  # not enabled: the base mode
        self.assertIsNone(found({"identity": {"app": {"bundleId": TELEGRAM}}}, ["telegram"]))  # no lists sent
        self.assertIsNone(found({**tg_snapshot(TG_ROWS), "identity": {"app": {"bundleId": "com.other"}}}, ["telegram"]))
        self.assertIsNone(found(tg_snapshot([TG_ROWS[0]], others=False), ["telegram"]))  # no message in the window

    def test_the_info_gives_each_adapter_by_its_surfaces(self):
        info = registry.packages()["telegram"].info({"telegram"})
        self.assertEqual((info["surfaces"][0]["screen"], info["enabled"]), ({"lists": {"budget": "chatHistoryTokenBudget"}}, True))
        code = registry.packages()["claude-code"].info(set())
        self.assertEqual(([s["id"] for s in code["surfaces"]], code["enabled"]), (["desktop", "terminal"], False))


class WhichSessionTest(Fixture):
    def tool(self):
        spec = importlib.util.spec_from_file_location(
            "which_session", pathlib.Path(__file__).parent / "tools" / "which_session.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_it_prints_errors_files_and_no_terms_without_failing(self):
        report = self.tool().report
        self.install("broken", code="from adapters import Adapter\nclass B(Adapter):\n"
                                    "    def context(self, s, n): raise KeyError('x')\n    def clean(self, t): return t\n")
        with self.assertLogs("echofox-server", "ERROR"):
            lines = report(EXAMPLE)
        self.assertIn("error: broken.context: KeyError: 'x'", lines)  # errors only: no context to print
        folder = os.path.join(self.dir.name, "repo")
        os.makedirs(folder)
        with open(os.path.join(folder, "a.md"), "w") as fh:
            fh.write("Только текст.\n")
        self.desktop_record("local_abc", "none", "X", cwd=folder)
        lines = report(as_file(code_tab("local_abc", panel=files_panel("a.md"))))  # no messages and no terms
        self.assertIn("content: snapshot (outline)", lines)
        self.assertIn("surfaces: claude-code/desktop (reads outline)", lines)
        self.assertIn("  0 messages, terms: ", lines)
        self.assertIn("  open file: a.md, 13 characters", lines)
        self.assertEqual(report({})[-1], "surfaces: none: the dictation runs without context")


class HungAdapterTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_hung_adapter_keeps_only_its_own_thread_and_the_next_dictations_skip_it(self):
        release, threads = threading.Event(), []

        def hung(identity, matched, content=None):
            threads.append(threading.current_thread().name)
            release.wait(5)
            return {"adapter": "slow"}

        saved = adapters.context
        adapters.context = hung
        try:
            stop = asyncio.Event()
            asyncio.get_running_loop().call_later(0.05, stop.set)
            got = await adapters.context_until({}, [], stop=stop)
            self.assertTrue(got["errors"][0].startswith("no context by the stop"), got)
            self.assertEqual(await adapters.context_until({}, [], stop=stop),
                             {"errors": ["the adapters still run for an earlier dictation"]})  # no second thread
            release.set()
            adapters._running.result(5)
            with self.assertLogs("echofox-server", "INFO") as logs:
                self.assertEqual(await adapters.context_until({}, [], stop=asyncio.Event()), {"adapter": "slow"})
                await asyncio.sleep(0.01)
            self.assertTrue(any("adapters:" in line for line in logs.output), logs.output)
            self.assertTrue(all(t.startswith("adapters") for t in threads), threads)  # not the loop's default pool
        finally:
            release.set()
            adapters.context = saved


if __name__ == "__main__":
    unittest.main()
