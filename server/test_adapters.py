"""Tests of the adapters (adapters/): Claude Code transcripts, Claude Desktop, and the choice of an adapter.
Run: server/.venv/bin/python -m unittest discover -s server"""
import json
import os
import tempfile
import time
import unittest

import adapters
from adapters import claude_code, claude_desktop

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
        self.saved = claude_code.PROJECTS, claude_desktop.STORE
        claude_code.PROJECTS, claude_desktop.STORE = self.projects, self.store

    def tearDown(self):
        claude_code.PROJECTS, claude_desktop.STORE = self.saved
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
        c = adapters.context({}, ["old", "new", "../x"])
        self.assertEqual((c["adapter"], c["session"], c["how"], c["title"]), ("claude-code", "new", "named sessions", "Тесты"))
        self.assertEqual(c["messages"], [{"role": "assistant", "text": "Запушил в master."},
                                         {"role": "assistant", "text": "Тесты прошли: npm test, 38 из 38.\n\nКоммит в master готов."}])
        self.assertEqual(c["terms"], ["master", "test", "npm"])
        self.assertNotIn("messages", adapters.context({}, ["none"]))  # claimed, but no such transcript

    def test_a_host_app_gets_its_newest_session_by_the_entrypoint_of_the_last_line(self):
        self.put("b", "code", [reply("m2", "из VS Code", entrypoint="claude-vscode")], age=10)
        self.put("b", "moved", [reply("m3", "начало", entrypoint="claude-vscode"),
                                reply("m4", "продолжение", entrypoint="claude-desktop")], age=5)
        c = adapters.context({"app": {"bundleId": "com.microsoft.VSCode"}})
        self.assertEqual((c["adapter"], c["confidence"], c["session"]), ("claude-code", 0.3, "code"))

    def test_an_unknown_app_gets_no_adapter(self):
        self.assertIsNone(adapters.context({"app": {"bundleId": "com.tdesktop.Telegram"}}))
        self.assertIsNone(adapters.context({}))

    def test_terms_are_latin_script_words_the_most_frequent_first_without_common_english_words(self):
        self.assertEqual(adapters.terms(["the GitHub Actions and GitHub", "use node.js, CI/CD and /Users/x/y/z.js"]),
                         ["GitHub", "CI/CD", "node.js", "Actions"])


class ClaudeDesktopTest(Fixture):
    def test_the_code_tab_url_leads_through_the_desktop_store_to_the_transcript(self):
        self.put("a", "cli-1", [{"type": "custom-title", "customTitle": "Local Speech"}, reply("m1", "Готово.")], age=60)
        self.put("b", "other", [reply("m2", "другая сессия", entrypoint="claude-desktop")])  # newer, but not on screen
        self.desktop_record("local_abc", "cli-1", "Local Speech")
        c = adapters.context(code_tab("local_abc"))
        self.assertEqual((c["adapter"], c["confidence"], c["how"], c["session"], c["desktopSession"]),
                         ("claude-desktop", 1.0, "desktop store", "cli-1", "local_abc"))
        self.assertEqual(c["messages"], [{"role": "assistant", "text": "Готово."}])

    def test_without_a_record_the_title_finds_the_transcript(self):
        self.put("a", "cli-2", [{"type": "custom-title", "customTitle": "Local Speech"}, reply("m1", "По названию.")], age=60)
        self.put("b", "other", [reply("m2", "другая", entrypoint="claude-desktop")])
        c = adapters.context(code_tab("local_missing"))
        self.assertEqual((c["how"], c["session"]), ("title", "cli-2"))

    def test_desktop_without_the_code_tab_falls_back_to_its_newest_session_less_surely(self):
        self.put("b", "newest", [reply("m2", "свежая", entrypoint="claude-desktop")])
        c = adapters.context({"app": {"bundleId": DESKTOP}})
        self.assertEqual((c["confidence"], c["how"], c["session"]), (0.5, "newest session of the app", "newest"))

    def test_the_surest_adapter_wins(self):
        ranked = adapters.claims(code_tab("local_abc"), ["s1"])
        self.assertEqual([(c.adapter, c.confidence) for _, c in ranked], [("claude-desktop", 1.0), ("claude-code", 0.9)])

    def test_a_bad_desktop_id_reads_no_file(self):
        self.assertIsNone(claude_desktop.record("local_../../etc"))

    def test_old_clients_send_a_bundle_id(self):
        self.assertEqual(adapters.snapshot_of({"app": DESKTOP}), {"app": {"bundleId": DESKTOP}})
        self.assertEqual(adapters.snapshot_of({"snapshot": {"x": 1}, "app": DESKTOP}), {"x": 1})


if __name__ == "__main__":
    unittest.main()
