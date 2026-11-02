"""Tests of the fixtures from live windows (server/tools/fixtures.py, docs/reference/8-fixtures.md): the tool on made-up
windows and snapshots, and every adapter on every accepted fixture of this Mac. Run:
server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import importlib.util
import json
import os
import pathlib
import tempfile
import unittest

from test_adapters import DESKTOP, TELEGRAM, TG_ROWS, chat_snapshot, code_tab, files_panel, reply, tg_row, tg_snapshot

_spec = importlib.util.spec_from_file_location("fixtures_tool", pathlib.Path(__file__).parent / "tools" / "fixtures.py")
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)

MARKED_ROW = tg_row(["Seen", "You", "EchoFox fixture", "Sent at 10:47"], ["Seen", "Sender", "Message", "Delivery", "Time"])


def window(snapshot, version="1.0"):
    """A test's snapshot ({"identity", "content": the parts read}) as a window of a running app, its version added."""
    identity = json.loads(json.dumps(snapshot["identity"]))
    identity["app"]["version"] = version
    return {"identity": identity, "content": snapshot.get("content") or {}}


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
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def code_session(self, marked=True):
        """A Claude Code session of Claude Desktop with the sandbox's notes.md open in the Files panel."""
        sandbox_dir = os.path.join(self.home, "echofox", "fixtures", "sandbox")
        self.put("echofox/fixtures/sandbox/notes.md", "# EchoFox fixture: notes\n\nТекст про `git rebase`.\n")
        self.put("Library/Application Support/Claude/claude-code-sessions/org/account/local_abc.json",
                 json.dumps({"sessionId": "local_abc", "cliSessionId": "s1", "cwd": sandbox_dir,
                             "title": "EchoFox fixture code" if marked else "Work"}))
        lines = ([{"type": "custom-title", "customTitle": "EchoFox fixture code"}] if marked else []) \
            + [reply("m1", f"## Ответ\n\nСмотри {self.home}/echofox/fixtures/sandbox/notes.md и `git log`.")]
        self.put(".claude/projects/p/s1.jsonl", "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lines))
        return window(code_tab("local_abc", "EchoFox fixture code" if marked else "Work", files_panel("notes.md")),
                      "4.4212.0")

    def files(self):
        return sorted(str(p.relative_to(self.fixtures)) for p in self.fixtures.rglob("*") if p.is_file())

    def test_the_marked_windows_of_the_chosen_surfaces_are_read_with_the_servers_read_request(self):
        apps = FakeApps({DESKTOP: [window(chat_snapshot([(False, ["Ответ."])], title="EchoFox fixture chat"))],
                         TELEGRAM: [window(tg_snapshot(TG_ROWS, "Anna")), window(tg_snapshot(TG_ROWS + [MARKED_ROW], "Saved Messages"))]})
        chosen = tool.selected(["claude-chat/desktop", "telegram/desktop", "claude-code/terminal"])
        found = tool.scan(chosen, apps, self.said.append)
        self.assertEqual({n: len(w) for n, w in found.items()},
                         {"claude-chat/desktop": 1, "telegram/desktop": 1, "claude-code/terminal": 0})
        self.assertEqual(found["telegram/desktop"][0].identity["window"]["title"], "Saved Messages")
        self.assertIn(f"telegram/desktop: window 0 of {TELEGRAM} has no 'EchoFox fixture': not read further", self.said)
        weights = json.loads(pathlib.Path(tool.catalog.PATH).read_text())["gemma-4-e4b"]["tokenWeights"]
        self.assertEqual(found["claude-chat/desktop"][0].request,
                         {"type": "read", "tokenWeights": weights, "surfaces": [{"surface": "claude-chat/desktop", "outline": {
                             "skip": ["AXButton", "sr-only", "group/morph", "group/tag"], "budget": 1000}}]})
        self.assertEqual(found["telegram/desktop"][0].request["surfaces"], [{"surface": "telegram/desktop", "lists": {"budget": 2000}}])
        lists = [c for c in apps.calls if c[0] == "list"]
        self.assertIn(("list", DESKTOP, True), lists)  # treeOnRequest: Claude Desktop is asked for its tree
        self.assertIn(("list", TELEGRAM, False), lists)
        self.assertIn(("list", "com.mitchellh.ghostty", False), lists)  # a terminal that does not run: nothing read

    def test_a_window_without_the_marker_is_never_written(self):
        apps = FakeApps({TELEGRAM: [window(tg_snapshot(TG_ROWS, "Anna"))]})
        self.assertEqual(tool.record(["telegram/desktop"], apps, self.said.append), 1)
        self.assertEqual(self.files(), [])
        self.assertIn("telegram/desktop: no window with 'EchoFox fixture' is on this surface", self.said)
        two = FakeApps({TELEGRAM: [window(tg_snapshot(TG_ROWS + [MARKED_ROW], "A"))] * 2})
        self.assertEqual(tool.record(["telegram/desktop"], two, self.said.append), 1)
        self.assertEqual(self.files(), [])  # two marked windows: which one is not certain

    def test_claude_desktop_gives_the_chat_and_then_the_code_tab_in_its_one_window(self):
        desktop = [window(chat_snapshot([(True, ["EchoFox fixture"]), (False, ["Ответ про `pyproject.toml`."])],
                                        title="EchoFox fixture chat"), "4.4212.0")]
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
        # The files the adapter read are kept, the home folder written ~, and a replay reads them, not the live disk
        self.assertEqual([s["path"] for s in code["sources"]],
                         ["~/.claude/projects/p/s1.jsonl",
                          "~/Library/Application Support/Claude/claude-code-sessions/org/account/local_abc.json",
                          "~/echofox/fixtures/sandbox/notes.md"])
        e = code["expected"]
        self.assertEqual((e["details"]["file"], e["documents"][0]["name"], e["messages"][0]["text"]),
                         ("~/.claude/projects/p/s1.jsonl", "notes.md",
                          "Ответ.\nСмотри ~/echofox/fixtures/sandbox/notes.md и git log."))
        self.assertNotIn(self.home, json.dumps(code["sources"]) + json.dumps(e))
        os.remove(os.path.join(self.home, ".claude/projects/p/s1.jsonl"))
        self.assertEqual(tool.replay(code), e)
        review = "\n".join(self.said)
        self.assertIn("claude-code/desktop: com.anthropic.claudefordesktop 4.4212.0, macOS", review)
        self.assertIn("    1. Claude:\n      Ответ", review)

    def test_a_parse_that_needs_a_file_without_the_marker_is_not_written(self):
        session = self.code_session(marked=False)
        session["identity"]["webArea"]["title"] = "EchoFox fixture code - Claude Code"  # only the page is marked
        self.assertEqual(tool.record(["claude-code/desktop"], FakeApps({DESKTOP: [session]}), self.said.append), 1)
        self.assertEqual(self.files(), [])
        self.assertTrue(any("not written: a replay from the kept files gives another parse" in s for s in self.said),
                        self.said)

    def test_accept_makes_the_versions_fixture_and_check_compares_with_the_newest_and_writes_nothing(self):
        apps = FakeApps({TELEGRAM: [window(tg_snapshot(TG_ROWS + [MARKED_ROW], "Saved Messages"), "7.9.1")]})
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
        rows = TG_ROWS + [tg_row(["Anna", "Новое сообщение", "Received at 11:00"], ["Sender", "Message", "Delivery", "Time"]), MARKED_ROW]
        apps.apps[TELEGRAM] = [window(tg_snapshot(rows, "Saved Messages"), "7.11.0")]
        self.said.clear()
        self.assertEqual(tool.check(["telegram/desktop"], apps, self.said.append), 1)
        self.assertEqual(self.said[0], "telegram/desktop: 7.11.0 now, 7.10.0 in 7.10.0.json: different")
        self.assertIn("Новое сообщение", "\n".join(self.said))
        self.assertEqual(self.files(), before)
        self.assertEqual(tool.check(["telegram/desktop"], FakeApps({}), self.said.append), 2)  # Telegram does not run
        with self.assertRaisesRegex(tool.Problem, "no pending fixture"):
            tool.accept(["telegram/desktop"])

    def test_the_loader_gives_the_versions_in_order_without_pending_sandbox_and_other_folders(self):
        for path, version in (("telegram/desktop/7.10.0.json", "7.10.0"), ("telegram/desktop/7.9.1.json", "7.9.1"),
                              ("telegram/desktop/pending.json", "8.0"), ("sandbox/.claude/x.json", "1"),
                              ("telegram/.hidden/1.json", "1")):
            (self.fixtures / path).parent.mkdir(parents=True, exist_ok=True)
            (self.fixtures / path).write_text(json.dumps({"app": {"version": version}}))
        (self.fixtures / "sandbox/notes.md").write_text("x")
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

    def test_the_sandbox_has_a_marked_markdown_file(self):
        self.assertEqual(tool.sandbox(self.said.append), 0)
        notes = (self.fixtures / "sandbox/notes.md").read_text(encoding="utf-8")
        self.assertIn(tool.MARKER, notes)
        self.assertEqual(tool.accepted(), [])


class AcceptedFixturesTest(unittest.TestCase):
    def test_every_adapter_gives_the_accepted_parse_of_every_fixture(self):
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
