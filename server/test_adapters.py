"""Tests of the adapters (adapters/): Claude Code transcripts, Claude Desktop, and the choice of an adapter.
Run: server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import json
import os
import tempfile
import time
import sys
import unittest

import adapters
from adapters import markdown, registry  # noqa: F401

DESKTOP = "com.anthropic.claudefordesktop"


def reply(mid, text, stop="end_turn", **extra):
    return {"type": "assistant", **extra, "message": {"id": mid, "stop_reason": stop, "content": [{"type": "text", "text": text}]}}


class Fixture(unittest.TestCase):
    """A temporary ~/.claude/projects and Desktop session store."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.projects, self.store = os.path.join(self.dir.name, "projects"), os.path.join(self.dir.name, "store")
        for p in ("a", "b"):
            os.makedirs(os.path.join(self.projects, p))
        os.makedirs(os.path.join(self.store, "org", "account"))
        self.saved = {k: os.environ.get(k) for k in ("ECHOFOX_PROJECTS", "ECHOFOX_DESKTOP_SESSIONS",
                                                      "ECHOFOX_ADAPTERS")}
        os.environ.update(ECHOFOX_PROJECTS=self.projects, ECHOFOX_DESKTOP_SESSIONS=self.store,
                          ECHOFOX_ADAPTERS=os.path.join(self.dir.name, "adapters"))

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

    def desktop_record(self, desktop_id, cli, title):
        with open(os.path.join(self.store, "org", "account", f"{desktop_id}.json"), "w") as fh:
            json.dump({"sessionId": desktop_id, "cliSessionId": cli, "cwd": "/x", "title": title}, fh)


def code_tab(desktop_id, title="Local Speech"):
    return {"app": {"bundleId": DESKTOP}, "webArea": {"url": f"https://claude.ai/epitaxy/{desktop_id}",
                                                     "title": f"{title} - Claude Code"}}


class ClaudeCodeTest(Fixture):
    def test_only_claudes_final_replies_newest_first_from_the_newest_of_the_sessions(self):
        self.put("a", "old", [reply("m0", "старая сессия")], age=60)
        self.put("b", "new", [
            {"type": "custom-title", "customTitle": "Тесты"},
            {"type": "user", "message": {"content": "Запусти тесты в CI"}},                       # the user: never
            reply("m1", "Запускаю npm test.", "tool_use"),                                        # between tool calls
            {"type": "assistant", "message": {"id": "m1", "stop_reason": "tool_use", "content": [{"type": "tool_use", "name": "Bash"}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "PASS 38 tests"}]}},
            reply("m2", "Тесты прошли: npm test, 38 из 38."),                                     # a final reply
            reply("m2", "<system-reminder>noise</system-reminder>Коммит в master готов."),         # same reply, next line
            reply("m3", "subagent", isSidechain=True),
            {"type": "user", "message": {"content": [{"type": "text", "text": "Закоммить в master"}]}},
            reply("m4", "Запушил в master."),
        ], tail="not json\n")
        c = adapters.context({}, {"sessions": ["old", "new", "../x"]})
        d = c["details"]
        self.assertEqual((c["adapter"], d["session"], d["how"], d["title"]), ("claude", "new", "named sessions", "Тесты"))
        self.assertTrue(c["about"] and c["source"].startswith("named sessions: "))
        self.assertEqual(c["messages"], [{"from": "Claude", "text": "Запушил в master."},
                                         {"from": "Claude", "text": "Тесты прошли: npm test, 38 из 38.\nКоммит в master готов."}])
        self.assertEqual(c["terms"], ["master", "test", "npm"])
        self.assertNotIn("messages", adapters.context({}, {"sessions": ["none"]}))  # claimed, but no such transcript

    def test_no_session_is_guessed_from_the_app_alone(self):
        self.put("b", "code", [reply("m2", "из VS Code", entrypoint="claude-vscode")])
        for app in ("com.microsoft.VSCode", "com.mitchellh.ghostty", "com.tdesktop.Telegram"):
            self.assertIsNone(adapters.context({"app": {"bundleId": app}}), app)
        self.assertIsNone(adapters.context({}))

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

    def test_a_word_with_a_small_letter_on_purpose_stays_small(self):
        md = "- iPhone можно подключить\n- macOS: тесты\n- a.py изменён\n- обычный пункт"
        self.assertEqual(adapters.markdown.plain(md), "iPhone можно подключить.\nmacOS: тесты.\na.py изменён.\nОбычный пункт.")

    def test_every_adapter_cleans_and_the_terms_come_from_clean_text(self):
        self.put("a", "s", [reply("m1", "Смотри `FocusSnapshot`:\n```\nlet secretVar = take()\n```"),
                            reply("m2", "```\nonlyCode()\n```")])
        c = adapters.context({}, {"sessions": ["s"]})
        self.assertEqual(c["messages"], [{"from": "Claude", "text": "Смотри FocusSnapshot:"}])  # code only: dropped
        self.assertEqual(c["terms"], ["FocusSnapshot"])
        for p in registry.packages().values():
            self.assertIsInstance(p.adapter, adapters.Adapter)

    def test_an_adapter_without_clean_cannot_be_made(self):
        class NoClean(adapters.Adapter):
            def claim(self, snapshot, sessions): return None
            def context(self, snapshot, sessions): return None
        with self.assertRaises(TypeError):
            NoClean()


class UserAdapterTest(Fixture):
    def install(self, name, manifest=None, code=None):
        d = os.path.join(os.environ["ECHOFOX_ADAPTERS"], name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "adapter.json"), "w") as f:
            json.dump(manifest if manifest is not None else {"name": name, "interface": 2, "apps": ["com.example.app"]}, f)
        with open(os.path.join(d, "adapter.py"), "w") as f:
            f.write(code if code is not None else (
                "from adapters import Adapter, Claim\n"
                "class Mine(Adapter):\n"
                "    def claim(self, focus, hints):\n"
                "        return Claim(self.name, 0.95, 'mine') if (focus.get('app') or {}).get('bundleId') == 'com.example.app' else None\n"
                "    def context(self, focus, hints):\n"
                "        return {'about': 'a chat with Anna', 'terms': ['Anna'], 'messages': [{'from': 'Anna', 'text': '**Hello** Kubernetes'}]}\n"
                "    def clean(self, text):\n"
                "        return text.replace('**', '')\n"))

    def test_a_users_adapter_in_the_folder_works_once_enabled(self):
        self.install("mine")
        snap = {"app": {"bundleId": "com.example.app"}}
        self.assertIsNone(adapters.context(snap, enabled=[]))  # the base mode: no adapter enabled
        self.assertIsNone(adapters.context(snap, enabled=["claude"]))
        c = adapters.context(snap, enabled=["mine"])
        self.assertEqual((c["adapter"], c["about"], c["messages"][0], c["terms"]),
                         ("mine", "a chat with Anna", {"from": "Anna", "text": "Hello Kubernetes"}, ["Anna", "Kubernetes", "Hello"]))
        self.assertEqual(registry.packages()["mine"].info({"mine"})["apps"], ["com.example.app"])

    def test_a_broken_adapter_stops_only_itself_and_says_why(self):
        self.install("old", {"name": "old", "interface": 0})
        self.install("twice", code="from adapters import Adapter\n")
        self.install("crash", code="raise RuntimeError('boom')\n")
        found = registry.packages()
        self.assertIn("interface 0", found["old"].error)
        self.assertIn("0 subclasses", found["twice"].error)
        self.assertIn("boom", found["crash"].error)
        self.assertIsNotNone(found["claude"].adapter)
        self.assertFalse(found["crash"].info({"crash"})["enabled"])

    def test_a_adapter_that_fails_stops_only_itself_and_the_error_is_kept(self):
        base = ("from adapters import Adapter, Claim\n"
                "class P(Adapter):\n"
                "    def claim(self, focus, hints):\n        {claim}\n"
                "    def context(self, focus, hints):\n        {context}\n"
                "    def clean(self, text):\n        {clean}\n")
        ok = "return Claim(self.name, 0.5, 'x')"
        msgs = "return {'about': 'a', 'messages': [{'from': 'A', 'text': 'one'}, {'from': 'A', 'text': 'two'}]}"
        self.install("badclaim", code=base.format(claim="raise RuntimeError('claim')", context=msgs, clean="return text"))
        self.install("good", code=base.format(claim="return Claim(self.name, 2.0, 'sure')", context=msgs, clean="return text"))
        c = adapters.context({}, enabled=["badclaim", "good"])
        self.assertEqual((c["adapter"], c["confidence"], len(c["messages"])), ("good", 1.0, 2))  # clamped to 1
        self.assertIn("badclaim.claim: RuntimeError: claim", c["errors"])
        self.install("badcontext", code=base.format(claim=ok, context="raise KeyError('k')", clean="return text"))
        c = adapters.context({}, enabled=["badcontext"])
        self.assertNotIn("messages", c)
        self.assertIn("badcontext.context: KeyError", c["errors"][0])
        self.install("badclean", code=base.format(claim=ok, context=msgs, clean="raise ValueError('v')"))
        c = adapters.context({}, enabled=["badclean"])
        self.assertEqual(c["messages"], [])
        self.assertIn("badclean.clean: ValueError: v", c["errors"])

    def test_a_users_adapter_replaces_a_built_in_one_of_the_same_name(self):
        self.install("claude", {"name": "claude", "interface": 2})
        self.assertFalse(registry.packages()["claude"].builtin)


class ClaudeDesktopTest(Fixture):
    def test_the_code_tab_url_leads_through_the_desktop_store_to_the_transcript(self):
        self.put("a", "cli-1", [{"type": "custom-title", "customTitle": "Local Speech"}, reply("m1", "Готово.")], age=60)
        self.put("b", "other", [reply("m2", "другая сессия", entrypoint="claude-desktop")])  # newer, but not on screen
        self.desktop_record("local_abc", "cli-1", "Local Speech")
        c = adapters.context(code_tab("local_abc"))
        d = c["details"]
        self.assertEqual((c["adapter"], c["confidence"], d["how"], d["session"], d["desktopSession"]),
                         ("claude", 1.0, "desktop store", "cli-1", "local_abc"))
        self.assertEqual(c["messages"], [{"from": "Claude", "text": "Готово."}])

    def test_without_a_record_the_title_finds_the_transcript(self):
        self.put("a", "cli-2", [{"type": "custom-title", "customTitle": "Local Speech"}, reply("m1", "По названию.")], age=60)
        self.put("b", "other", [reply("m2", "другая", entrypoint="claude-desktop")])
        c = adapters.context(code_tab("local_missing"))
        self.assertEqual((c["details"]["how"], c["details"]["session"]), ("title", "cli-2"))

    def test_desktop_without_the_code_tab_in_focus_is_not_claimed(self):
        self.put("b", "newest", [reply("m2", "свежая", entrypoint="claude-desktop")])
        self.assertIsNone(adapters.context({"app": {"bundleId": DESKTOP}}))  # no Accessibility, another window, …
        self.assertIsNone(adapters.context({"app": {"bundleId": DESKTOP}, "webArea": {"url": "https://claude.ai/chat/1"}}))

    def test_a_title_that_several_transcripts_share_gives_no_context(self):
        for n in ("t1", "t2"):
            self.put("a", n, [{"type": "custom-title", "customTitle": "Same"}, reply("m", "x")])
        c = adapters.context(code_tab("local_missing", title="Same"))
        self.assertEqual(c["adapter"], "claude")
        self.assertNotIn("messages", c)

    def test_the_surest_adapter_wins(self):
        ranked = adapters.claims(code_tab("local_abc"), {"sessions": ["s1"]})
        self.assertEqual([(c.adapter, c.confidence) for _, c in ranked], [("claude", 1.0)])  # one adapter: the Code tab wins over named sessions

    def test_a_bad_desktop_id_reads_no_file(self):
        self.assertIsNone(sys.modules["echofox_adapter_claude.desktop"].record("local_../../etc"))


CHAT = "0f8e2a6c-1b3d-4e5f-8a7b-9c0d1e2f3a4b"


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
    """A message of a Claude Desktop chat as its outline shows it (measured 2026-10-25, Claude Desktop 3.6556.2)."""
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


def chat_focus(messages, complete=True, title="Выгрузка данных"):
    nodes = [node(0, "AXWebArea"), node(1, "AXGroup", label="Sidebar"), node(2, "AXStaticText", text="Recents"),
             node(1, "AXGroup", label="Chat messages")]
    for i, (own, lines) in enumerate(messages, 1):
        nodes += chat_message(2, i, len(messages), own, lines)
    nodes += [node(1, "AXTextArea", ["ProseMirror"], "Write your prompt to Claude")]
    return {"app": {"bundleId": DESKTOP}, "webArea": {"url": f"https://claude.ai/chat/{CHAT}", "title": f"{title} - Claude"},
            "outline": {"root": "webArea", "complete": complete, "nodes": nodes}}


class ClaudeChatTest(Fixture):
    def test_a_chat_gives_claudes_replies_newest_first_without_hidden_parts_buttons_and_chips(self):
        c = adapters.context(chat_focus([(True, ["Как выгрузить данные?"]),
                                         (False, ["Напишите в поддержку.", "Пишите Data Protection Officer"]),
                                         (True, ["А кто уже пробовал?"]),
                                         (False, ["Отчётов нет."])]))
        self.assertEqual((c["adapter"], c["confidence"], c["details"]["replies"]), ("claude", 1.0, 2))
        self.assertEqual(c["messages"], [{"from": "Claude", "text": "Отчётов нет."},
                                         {"from": "Claude", "text": "Напишите в поддержку. • Пишите Data Protection Officer"}])  # clean joins the lines
        self.assertEqual(c["about"], "a chat with Claude, an AI assistant, titled “Выгрузка данных”")

    def test_the_speakers_messages_are_read_but_left_out_of_the_context(self):
        chat = sys.modules["echofox_adapter_claude.chat"]
        found = chat.messages(chat_focus([(True, ["Первая строка", "вторая"]), (False, ["Ответ."])])["outline"])
        self.assertEqual(found, [{"from": "the speaker", "text": "Первая строка\nвторая"}, {"from": "Claude", "text": "Ответ."}])

    def test_a_cut_outline_skips_the_message_it_starts_in(self):
        focus = chat_focus([(False, ["Старый ответ."]), (False, ["Новый ответ."])], complete=False)
        nodes = focus["outline"]["nodes"]
        start = next(i for i, n in enumerate(nodes) if n.get("description") == "Message 1 of 2")
        focus["outline"]["nodes"] = nodes[start + 3:]  # the walk stopped inside message 1
        c = adapters.context(focus)
        self.assertEqual(c["messages"], [{"from": "Claude", "text": "Новый ответ."}])
        self.assertFalse(c["details"]["outlineComplete"])

    def test_a_chat_without_an_outline_is_claimed_with_no_messages(self):
        focus = chat_focus([])
        del focus["outline"]
        c = adapters.context(focus)
        self.assertEqual((c["adapter"], c["details"]["replies"]), ("claude", 0))


if __name__ == "__main__":
    unittest.main()


TELEGRAM = "com.tdesktop.Telegram"


def tg_row(lines, columns):
    return {"text": "\n".join(lines), "columns": columns}


def tg_focus(rows, title="Anna – (3)", others=True):
    """A Telegram Desktop snapshot as the client sends it: the chat list on the left, the messages above the box."""
    lists = [{"frame": {"x": 540, "y": -847, "width": 972, "height": 1684}, "rowCount": len(rows) + 20, "rows": rows}]
    if others:
        lists.append({"frame": {"x": 0, "y": 124, "width": 540, "height": 26744}, "rowCount": 393,
                      "rows": [tg_row(["Bob", "see you", "Received at 9:00"], ["Sender", "Message", "Time"])] * 5})
    return {"app": {"bundleId": TELEGRAM}, "window": {"title": title},
            "focusedFrame": {"x": 590, "y": 847, "width": 826, "height": 31}, "lists": lists}


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
    def adapter(self):
        return registry.packages()["telegram"].adapter

    def test_the_rows_become_messages_with_the_speakers_own_and_without_the_status(self):
        self.adapter()  # loads the adapter's package
        from echofox_adapter_telegram import desktop
        self.assertEqual(desktop.messages(TG_ROWS), [
            {"from": "Anna", "text": "Привет! Как дела с Kubernetes?"},
            {"from": "the speaker", "text": "Всё ок, деплою"},
            {"from": "Anna", "text": "Photo\nСмотри, что вышло в 10:30"},
            {"from": "Anna", "text": "Первая строка\nвторая строка"},
            {"from": "the speaker", "text": "Ещё не прочитано"},
        ])

    def test_the_chat_name_comes_from_the_window_title(self):
        self.adapter()  # loads the adapter's package
        from echofox_adapter_telegram import desktop
        for title, name in [("Anna – (3)", "Anna"), ("(2) Anna", "Anna"), ("Anna @ Work (3)", "Anna"),
                            ("Telegram (5)", None), ("Telegram", None), ("", None), ("Dev team", "Dev team"),
                            ("\u2068Anna\u2069 \u2013 (3)", "Anna"), ("(2) \u2068Dev team\u2069", "Dev team")]:
            self.assertEqual(desktop.chat_name(title), name, title)

    def test_the_message_list_is_the_one_above_the_input_box(self):
        self.adapter()  # loads the adapter's package
        from echofox_adapter_telegram import desktop
        self.assertIs(desktop.message_list(tg_focus(TG_ROWS))["rows"], TG_ROWS)
        no_box = tg_focus(TG_ROWS)
        no_box.pop("focusedFrame")
        self.assertIs(desktop.message_list(no_box)["rows"], TG_ROWS)  # the widest list

    def test_telegram_claims_its_window_and_gives_the_open_chat_newest_first(self):
        found = adapters.context(tg_focus(TG_ROWS), {}, ["telegram", "claude"])
        self.assertEqual((found["adapter"], found["about"]), ("telegram", "a Telegram chat with Anna"))
        self.assertEqual([m["text"] for m in found["messages"]][:2], ["Ещё не прочитано", "Первая строка вторая строка"])
        self.assertEqual(found["terms"][:1], ["Anna"])
        self.assertEqual(found["details"]["messages"], 5)
        self.assertIsNone(adapters.context(tg_focus(TG_ROWS), {}, ["claude"]))  # not enabled: the base mode
        self.assertIsNone(adapters.context({"app": {"bundleId": TELEGRAM}}, {}, ["telegram"]))  # no lists sent
        self.assertIsNone(adapters.context({**tg_focus(TG_ROWS), "app": {"bundleId": "com.other"}}, {}, ["telegram"]))

    def test_a_manifest_may_ask_only_for_screen_parts_the_client_sends(self):
        info = registry.packages()["telegram"].info({"telegram"})
        self.assertEqual((info["screen"], info["enabled"]), (["lists"], True))
        d = os.path.join(os.environ["ECHOFOX_ADAPTERS"], "peek")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "adapter.json"), "w") as f:
            json.dump({"name": "peek", "interface": 2, "apps": ["x"], "screen": ["everything"]}, f)
        with open(os.path.join(d, "adapter.py"), "w") as f:
            f.write("from adapters import Adapter\nclass P(Adapter):\n    def claim(self, f, h): pass\n"
                    "    def context(self, f, h): pass\n    def clean(self, t): return t\n")
        self.assertIn("screen", registry.packages()["peek"].error)


class HungAdapterTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_hung_adapter_keeps_only_its_own_thread_and_the_next_dictations_skip_it(self):
        release, threads = __import__("threading").Event(), []

        def hung(focus, hints=None, enabled=None):
            threads.append(__import__("threading").current_thread().name)
            release.wait(5)
            return {"adapter": "slow"}

        saved = adapters.context
        adapters.context = hung
        try:
            self.assertEqual(await adapters.context_within({}, timeout=0.05), {"errors": ["no context in 0 s"]})
            self.assertEqual(await adapters.context_within({}, timeout=0.05),
                             {"errors": ["the adapters still run for an earlier dictation"]})  # no second thread
            release.set()
            adapters._running.result(5)
            self.assertEqual(await adapters.context_within({}, timeout=1), {"adapter": "slow"})
            self.assertTrue(all(t.startswith("adapters") for t in threads), threads)  # not the loop's default pool
        finally:
            release.set()
            adapters.context = saved
