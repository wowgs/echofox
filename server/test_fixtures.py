"""Tests of the fixtures from live windows (server/tools/fixtures.py, docs/reference/8-fixtures.md): the tool on made-up
windows, snapshots and files, and every adapter on every accepted fixture of this Mac. Run:
server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import importlib.util
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

import budget
import resolve
from test_adapters import DESKTOP, TELEGRAM, TG_ROWS, chat_snapshot, code_tab, files_panel, reply, tg_row, tg_snapshot

_spec = importlib.util.spec_from_file_location("fixtures_tool", pathlib.Path(__file__).parent / "tools" / "fixtures.py")
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)

SESSION_RECORD = "Library/Application Support/Claude/claude-code-sessions/org/account/local_abc.json"
TRANSCRIPT = ".claude/projects/p/s1.jsonl"


def window(snapshot, version="1.0"):
    """A test's snapshot ({"identity", "content": the parts read}) as a window of a running app, its version added."""
    identity = json.loads(json.dumps(snapshot["identity"]))
    identity["app"]["version"] = version
    return {"identity": identity, "content": snapshot.get("content") or {}}


def title(text):
    return {"type": "custom-title", "customTitle": text}


def tool_output(n):
    """A line of a transcript that is no reply: the output of a tool, 100 characters or more."""
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": f"{n:04} " + "x" * 95}]}}


class FakeApps:
    """The running apps' windows, as echofox-snapshot gives them: {bundle id: [window()]}; an app that is not here
    does not run. Each read answers every surface of the request with the window's parts."""

    def __init__(self, apps):
        self.apps, self.calls = apps, []

    def windows(self, bundle, electron):
        self.calls.append(("list", bundle, electron))
        return [w["identity"] for w in self.apps[bundle]] if bundle in self.apps else None

    def read(self, bundle, index, request, electron):
        self.calls.append(("read", bundle, index, request))
        w = self.apps[bundle][index]
        return {"identity": w["identity"],
                "content": {"type": "content", "tookMs": 1, "surfaces": {r["surface"]: w["content"] for r in request["surfaces"]}}}


class ToolTest(unittest.TestCase):
    """A home folder and a fixtures folder of the test's own."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.home = os.path.realpath(os.path.join(self.dir.name, "home"))
        self.fixtures = pathlib.Path(self.dir.name, "fixtures")
        self.saved = {k: os.environ.get(k) for k in ("HOME", "ECHOFOX_FIXTURES")}
        os.makedirs(self.home)
        os.environ.update(HOME=self.home, ECHOFOX_FIXTURES=str(self.fixtures))
        self.said = []

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.dir.cleanup()

    def put(self, path, text):
        p = os.path.join(self.home, path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w" if isinstance(text, str) else "wb", **({"encoding": "utf-8"} if isinstance(text, str) else {})) as f:
            f.write(text)
        return p

    def code_session(self, lines=None, notes="# Notes\n\nТекст про `git rebase`.\n"):
        """A Claude Code session of Claude Desktop, its transcript of `lines`, with notes.md of its folder open in the
        Files panel."""
        folder = os.path.join(self.home, "work")
        self.put("work/notes.md", notes)
        self.put(SESSION_RECORD, json.dumps({"sessionId": "local_abc", "cliSessionId": "s1", "cwd": folder, "title": "Work"}))
        if lines is None:
            lines = [title("Work"), reply("m1", f"## Ответ\n\nСмотри {self.home}/work/notes.md и `git log`.")]
        self.put(TRANSCRIPT, "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lines))
        return window(code_tab("local_abc", "Work", files_panel("notes.md")), "4.4212.0")

    def files(self):
        return sorted(str(p.relative_to(self.fixtures)) for p in self.fixtures.rglob("*") if p.is_file())

    def test_every_window_of_the_chosen_surfaces_is_read_with_the_servers_read_request(self):
        apps = FakeApps({DESKTOP: [window(chat_snapshot([(False, ["Ответ."])]))],
                         TELEGRAM: [window(tg_snapshot(TG_ROWS, "Anna")), window(tg_snapshot(TG_ROWS, "Saved Messages"))]})
        chosen = tool.selected(["claude-chat/desktop", "telegram/desktop", "claude-code/terminal"])
        found = tool.scan(chosen, apps)
        self.assertEqual({n: [str(w) for w in ws] for n, ws in found.items()},
                         {"claude-chat/desktop": [f"window 0 of {DESKTOP} ('')"],
                          "telegram/desktop": [f"window 0 of {TELEGRAM} ('Anna')", f"window 1 of {TELEGRAM} ('Saved Messages')"],
                          "claude-code/terminal": []})
        weights = json.loads(pathlib.Path(tool.catalog.PATH).read_text())["gemma-4-e4b"]["tokenWeights"]
        self.assertEqual(found["claude-chat/desktop"][0].request,
                         {"type": "read", "tokenWeights": weights, "surfaces": [{"surface": "claude-chat/desktop", "outline": {
                             "skip": ["AXButton", "sr-only", "group/morph", "group/tag"], "budget": 1000}}]})
        self.assertEqual(found["telegram/desktop"][0].request["surfaces"], [{"surface": "telegram/desktop", "lists": {"budget": 2000}}])
        lists = [c for c in apps.calls if c[0] == "list"]
        self.assertIn(("list", DESKTOP, True), lists)  # treeOnRequest: Claude Desktop is asked for its tree
        self.assertIn(("list", TELEGRAM, False), lists)
        self.assertIn(("list", "com.mitchellh.ghostty", False), lists)  # a terminal that does not run: nothing read

    def test_the_first_window_with_a_context_is_recorded_and_the_others_are_named(self):
        empty = window(tg_snapshot([], "Telegram", others=False))  # no chat open: no list, no context
        anna, saved = window(tg_snapshot(TG_ROWS, "Anna")), window(tg_snapshot(TG_ROWS, "Saved Messages"))
        apps = FakeApps({TELEGRAM: [empty, anna, saved]})
        self.assertEqual(tool.record(["telegram/desktop"], apps, self.said.append), 0)
        self.assertEqual(self.files(), ["telegram/desktop/pending.json"])
        fixture = tool.load(self.fixtures / "telegram/desktop/pending.json")
        self.assertEqual(fixture["identity"]["window"]["title"], "Anna")
        self.assertIn(f"telegram/desktop: window 1 of {TELEGRAM} ('Anna') is taken, the first with a context. "
                      f"Left: window 2 of {TELEGRAM} ('Saved Messages')", self.said)

        self.said.clear()
        self.assertEqual(tool.record(["telegram/desktop"], FakeApps({TELEGRAM: [empty]}), self.said.append), 1)
        self.assertEqual(self.said, [f"telegram/desktop: no window on this surface gives a context: window 0 of {TELEGRAM} "
                                     "('Telegram'): no context: the adapter did not find the conversation"])
        self.said.clear()
        self.assertEqual(tool.record(["telegram/desktop"], FakeApps({}), self.said.append), 1)
        self.assertEqual(self.said, ["telegram/desktop: no window is on this surface"])
        self.assertEqual(self.files(), ["telegram/desktop/pending.json"])

    def test_claude_desktop_gives_the_chat_and_then_the_code_tab_in_its_one_window(self):
        desktop = [window(chat_snapshot([(True, ["Вопрос"]), (False, ["Ответ про `pyproject.toml`."])]), "4.4212.0")]
        apps = FakeApps({DESKTOP: desktop})
        self.assertEqual(tool.record(["claude-chat/desktop", "claude-code/desktop"], apps, self.said.append), 1)
        self.assertEqual(self.files(), ["claude-chat/desktop/pending.json"])  # the Code tab is not on the screen
        desktop[0] = self.code_session()  # the owner switches the window to the Code tab
        self.assertEqual(tool.record(["claude-code/desktop"], apps, self.said.append), 0)
        self.assertEqual(self.files(), ["claude-chat/desktop/pending.json", "claude-code/desktop/pending.json"])
        chat = tool.load(self.fixtures / "claude-chat/desktop/pending.json")
        self.assertEqual((chat["app"], chat["expected"]["messages"]),
                         ({"bundleId": DESKTOP, "version": "4.4212.0"}, [{"from": "Claude", "text": "Ответ про pyproject.toml."}]))
        code = tool.load(self.fixtures / "claude-code/desktop/pending.json")
        # Every file the adapter read is kept, the home folder written ~, and a replay reads them, not the live disk
        self.assertEqual([s["path"] for s in code["sources"]], ["~/" + TRANSCRIPT, "~/" + SESSION_RECORD, "~/work/notes.md"])
        e = code["expected"]
        self.assertEqual(sorted(e), ["about", "details", "documents", "messages", "source", "terms"])
        self.assertEqual((e["details"]["file"], e["documents"][0]["name"], e["messages"][0]["text"]),
                         ("~/" + TRANSCRIPT, "notes.md", "Ответ.\nСмотри ~/work/notes.md и git log."))
        self.assertNotIn(self.home, json.dumps(code["sources"]) + json.dumps(e))
        os.remove(os.path.join(self.home, TRANSCRIPT))
        self.assertEqual(tool.replay(code), e)
        review = "\n".join(self.said)
        self.assertIn("claude-code/desktop: com.anthropic.claudefordesktop 4.4212.0, macOS", review)
        self.assertIn("    1. Claude:\n      Ответ", review)

    def test_a_path_under_the_replays_home_folder_gives_the_words_of_the_live_one(self):
        def text(home_dir):
            return f"Смотри {home_dir}/top.md, {home_dir}/work/notes.md и {home_dir}."

        live = tool.adapters.terms([text("/Users/alex")])
        self.assertIn("Users/alex", live)
        with tool.replay_folder() as folder:
            self.assertEqual(tool.adapters.terms([text(tool.replay_home(folder, "/Users/alex/"))]), live)
            self.assertNotIn("_", folder)
            self.assertEqual(os.listdir(folder), [])
        self.assertFalse(os.path.exists(folder))

    def test_a_parse_that_needs_a_file_the_fixture_cannot_keep_is_not_written(self):
        session = self.code_session(notes=b"# Notes\n\n\xff not UTF-8 text\n")  # the adapter reads it with errors="replace"
        self.assertEqual(tool.record(["claude-code/desktop"], FakeApps({DESKTOP: [session]}), self.said.append), 1)
        self.assertEqual(self.files(), [])
        self.assertTrue(any("not written: a replay from the kept files gives another expected value. The adapter read "
                            f"files that are not kept: {self.home}/work/notes.md" in s for s in self.said), self.said)

    def test_a_big_file_keeps_its_fewest_last_lines_that_give_the_same_expected_value(self):
        lines = ([title("Work")] + [tool_output(n) for n in range(40)]
                 + [reply("m1", "Первый ответ про `Kubernetes`."), tool_output(41), reply("m2", "Второй ответ."), title("Work"),
                    reply("m3", "Третий ответ про `Kubernetes`.")])
        session = self.code_session(lines)
        with mock.patch.object(tool, "LIMIT", 1000):
            self.assertEqual(tool.record(["claude-code/desktop"], FakeApps({DESKTOP: [session]}), self.said.append), 0)
        code = tool.load(self.fixtures / "claude-code/desktop/pending.json")
        transcript = code["sources"][0]
        # The tail from the first reply on: one line fewer loses a message, and its "custom-title" line keeps the title
        self.assertEqual((transcript["path"], transcript["linesLeftOut"], len(transcript["text"].splitlines())),
                         ("~/" + TRANSCRIPT, 41, 5))
        self.assertTrue(transcript["text"].startswith(json.dumps(lines[41], ensure_ascii=False)))
        self.assertEqual([len(s["text"]) < 1000 and "linesLeftOut" not in s for s in code["sources"][1:]], [True, True])
        self.assertEqual(code["expected"]["details"]["title"], "Work")
        self.assertEqual(len(code["expected"]["messages"]), 3)
        self.assertEqual(tool.replay(code), code["expected"])
        self.assertIn(f"  files kept: ~/{TRANSCRIPT} (its last lines, 41 left out), ~/{SESSION_RECORD}, ~/work/notes.md",
                      "\n".join(self.said))

    def test_a_big_file_whose_tails_within_the_limit_give_another_expected_value_is_not_written(self):
        lines = [title("Work")] + [tool_output(n) for n in range(40)] + [reply("m1", "Ответ.")]  # the title only at the start
        session = self.code_session(lines)
        with mock.patch.object(tool, "LIMIT", 1000):
            self.assertEqual(tool.record(["claude-code/desktop"], FakeApps({DESKTOP: [session]}), self.said.append), 1)
        self.assertEqual(self.files(), [])
        self.assertEqual(len(self.said), 1)
        self.assertRegex(self.said[0], f"^claude-code/desktop: not written: ~/{TRANSCRIPT} has 0.0 MB, over the 0.001 MB "
                                       r"limit of a kept file, and its last \d of 42 lines, the most within the limit, "
                                       "give another expected value:\n--- live\n")
        self.assertIn('\n-  "title": "Work"\n+  "title": null\n', self.said[0])  # the difference says why

    def test_the_tail_search_halves(self):
        calls = []

        def works(n):
            calls.append(n)
            return n >= 37

        self.assertEqual(tool.fewest(1000, works), 37)
        self.assertLessEqual(len(calls), 10)  # log2(1001), not 1000 tries
        self.assertEqual(tool.fewest(10, lambda n: n >= 10), 10)
        self.assertEqual(tool.fewest(10, lambda n: True), 0)

    def test_the_expected_value_is_what_the_default_budgets_keep(self):
        messages = [{"from": "Anna", "text": f"Сообщение {i} " + "слово " * 60} for i in range(30)]
        terms = [f"Term{i}" for i in range(200)]
        documents = [{"name": f"doc{i}.md", "text": "Текст документа. " * 200} for i in range(3)]
        found = {"adapter": "telegram", "surface": "telegram/desktop", "about": "a chat", "source": "the list",
                 "details": {"chat": "Anna", "pid": 501, "home": f"{self.home}/x"}, "messages": messages, "terms": terms,
                 "documents": documents}
        got = tool.expected(found, self.home, {501})
        self.assertEqual(sorted(got), ["about", "details", "documents", "messages", "source", "terms"])
        self.assertEqual(got["details"], {"chat": "Anna", "pid": "<pid>", "home": "~/x"})
        server, entry, options = tool.defaults()
        options = resolve.adapter("telegram", options, server)
        weights = tool.catalog.token_weights(entry)

        def reached(items, cost, limit):
            """Every item but the last costs less than `limit`, and all of them reach it: the greedy rule."""
            spent = [budget.count(cost(x), weights) for x in items]
            return sum(spent[:-1]) < limit <= sum(spent)

        terms_budget = resolve.value("chat_terms_token_budget", options, server)
        self.assertEqual(got["terms"], terms[:len(got["terms"])])
        self.assertLess(len(got["terms"]), len(terms))
        self.assertTrue(reached(got["terms"], lambda t: t + ", ", terms_budget))
        used = sum(budget.count(t + ", ", weights) for t in got["terms"])
        self.assertEqual(got["messages"], [{"from": "Anna", "text": m["text"].strip()} for m in messages[:len(got["messages"])]])
        self.assertLess(len(got["messages"]), len(messages))
        self.assertTrue(reached(got["messages"], lambda m: f"{m['from']}: {m['text']}\n\n",
                                resolve.value("chat_history_token_budget", options, server) - used))
        self.assertEqual(got["documents"], documents[:len(got["documents"])])
        self.assertLess(len(got["documents"]), len(documents))
        self.assertTrue(reached(got["documents"], lambda d: f"File {d['name']}:\n{d['text']}\n\n",
                                resolve.value("chat_documents_token_budget", options, server)))
        self.assertIsNone(tool.expected(None, self.home))
        self.assertEqual(tool.expected({"errors": ["x"]}, self.home), {"errors": ["x"]})

    def test_accept_makes_the_versions_fixture_and_check_compares_with_the_newest_and_writes_nothing(self):
        apps = FakeApps({TELEGRAM: [window(tg_snapshot(TG_ROWS, "Saved Messages"), "7.9.1")]})
        self.assertEqual(tool.record(["telegram/desktop"], apps, self.said.append), 0)
        self.assertEqual(tool.accept(["telegram/desktop"], self.said.append), 0)
        self.assertEqual(self.files(), ["telegram/desktop/7.9.1.json"])
        apps.apps[TELEGRAM][0]["identity"]["app"]["version"] = "7.10.0"
        tool.record(["telegram/desktop"], apps, self.said.append)
        tool.accept(["telegram/desktop"], self.said.append)
        self.assertEqual(tool.newest("telegram/desktop"), ("7.10.0", self.fixtures / "telegram/desktop/7.10.0.json"))

        self.said.clear()
        self.assertEqual(tool.check([], apps, self.said.append), 0)
        self.assertEqual(self.said[0], "telegram/desktop: 7.10.0 now, 7.10.0 in 7.10.0.json: same")
        before = self.files()
        rows = TG_ROWS + [tg_row(["Anna", "Новое сообщение", "Received at 11:00"], ["Sender", "Message", "Delivery", "Time"])]
        apps.apps[TELEGRAM] = [window(tg_snapshot(rows, "Saved Messages"), "7.11.0")]
        self.said.clear()
        self.assertEqual(tool.check(["telegram/desktop"], apps, self.said.append), 1)
        self.assertEqual(self.said[0], "telegram/desktop: 7.11.0 now, 7.10.0 in 7.10.0.json: different")
        self.assertIn("Новое сообщение", "\n".join(self.said))
        self.said.clear()
        empty = FakeApps({TELEGRAM: [window(tg_snapshot([], "Telegram", others=False), "7.11.0")]})
        self.assertEqual(tool.check(["telegram/desktop"], empty, self.said.append), 1)  # on the surface, no context
        self.assertEqual(self.said[-1], "telegram/desktop: 7.11.0 now, 7.10.0 in 7.10.0.json: different: no context")
        self.assertEqual(self.files(), before)
        self.assertEqual(tool.check(["telegram/desktop"], FakeApps({}), self.said.append), 2)  # Telegram does not run
        with self.assertRaisesRegex(tool.Problem, "no pending fixture"):
            tool.accept(["telegram/desktop"])

    def test_the_loader_gives_the_versions_in_order_without_pending_and_other_folders(self):
        for path, version in (("telegram/desktop/7.10.0.json", "7.10.0"), ("telegram/desktop/7.9.1.json", "7.9.1"),
                              ("telegram/desktop/pending.json", "8.0"), ("other/.claude/x.json", "1"),
                              ("telegram/.hidden/1.json", "1")):
            (self.fixtures / path).parent.mkdir(parents=True, exist_ok=True)
            (self.fixtures / path).write_text(json.dumps({"app": {"version": version}}))
        self.assertEqual([(n, v) for n, v, _ in tool.accepted()],
                         [("telegram/desktop", "7.9.1"), ("telegram/desktop", "7.10.0")])
        self.assertEqual(tool.file_name("1.2 (3)"), "1.2__3_.json")
        self.assertEqual(tool.accepted(pathlib.Path(self.dir.name, "none")), [])

    def test_the_home_folder_and_the_process_ids_are_written_alike_in_every_run(self):
        got = tool.normalized({"file": f"{self.home}/.claude/x", "cwd": self.home, "pid": 501, "count": 3, "on": True,
                               "list": [f"see {self.home}/a and {self.home}x"]}, self.home, {501, 1})
        self.assertEqual(got, {"file": "~/.claude/x", "cwd": "~", "pid": "<pid>", "count": 3, "on": True,
                               "list": [f"see ~/a and {self.home}x"]})
        self.assertEqual(tool.pids_of({"app": {"pid": 7}}, {"processes": [{"pid": 8}, {"pid": True}]}), {7, 8})

    def test_the_tool_says_what_to_do_without_the_accessibility_permission_and_skips_an_app_that_does_not_run(self):
        script = os.path.join(self.dir.name, "echofox-snapshot")
        saved = os.environ.get("ECHOFOX_SNAPSHOT")
        os.environ["ECHOFOX_SNAPSHOT"] = script
        try:
            for code, check in ((3, "Accessibility"), (4, None), (1, "exit code 1: broken")):
                with open(script, "w") as f:
                    f.write(f"#!/bin/sh\necho broken >&2\nexit {code}\n")
                os.chmod(script, 0o755)
                if check:
                    with self.assertRaisesRegex(tool.Problem, check):
                        tool.Snapshots().windows(TELEGRAM, False)
                else:
                    self.assertIsNone(tool.Snapshots().windows(TELEGRAM, False))
        finally:
            if saved is None:
                os.environ.pop("ECHOFOX_SNAPSHOT")
            else:
                os.environ["ECHOFOX_SNAPSHOT"] = saved
        with self.assertRaisesRegex(tool.Problem, "no working surface telegram/web"):
            tool.selected(["telegram/web"])


class AcceptedFixturesTest(unittest.TestCase):
    def test_every_adapter_gives_the_accepted_expected_value_of_every_fixture(self):
        root = tool.folder()
        if not root.is_dir():
            self.skipTest(f"no fixtures folder {root}: the fixtures from live windows are only on the Mac that "
                          "recorded them (docs/reference/8-fixtures.md)")
        found = tool.accepted(root)
        if not found:
            self.skipTest(f"no accepted fixture in {root}")
        surfaces = {s.name for s in tool.working_surfaces()}
        for name, version, path in found:
            with self.subTest(surface=name, version=version):
                if name not in surfaces:
                    self.skipTest(f"{name}: no working adapter has this surface here")
                fixture = tool.load(path)
                self.assertEqual(tool.replay(fixture), fixture["expected"])


if __name__ == "__main__":
    unittest.main()
