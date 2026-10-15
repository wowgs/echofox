"""Tests of the chat context (context.py). Run: server/.venv/bin/python -m unittest discover -s server"""
import json
import os
import tempfile
import time
import unittest

import context


def reply(mid, text, stop="end_turn", **extra):
    return {"type": "assistant", **extra, "message": {"id": mid, "stop_reason": stop, "content": [{"type": "text", "text": text}]}}


class ChatContextTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.d = self.dir.name
        for p in ("a", "b"):
            os.makedirs(os.path.join(self.d, p))

    def tearDown(self):
        self.dir.cleanup()

    def put(self, project, session, lines, age=0, tail=""):
        f = os.path.join(self.d, project, f"{session}.jsonl")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lines) + tail)
        t = time.time() - age
        os.utime(f, (t, t))
        return f

    def test_only_claudes_final_replies_newest_first_from_the_newest_of_the_sessions(self):
        self.put("a", "old", [reply("m0", "старая сессия")], age=60)
        self.put("b", "new", [
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
        c = context.chat_context(["old", "new", "../x"], projects=self.d)
        self.assertEqual(c["session"], "new")
        self.assertEqual(c["messages"], [{"role": "assistant", "text": "Запушил в master."},
                                         {"role": "assistant", "text": "Тесты прошли: npm test, 38 из 38.\n\nКоммит в master готов."}])
        self.assertEqual(c["terms"], ["master", "test", "npm"])
        self.assertIsNone(context.chat_context(["none"], projects=self.d))
        self.assertIsNone(context.chat_context([], projects=self.d))

    def test_an_app_gets_its_newest_session_by_the_entrypoint_of_the_last_line(self):
        desk = self.put("a", "desk", [reply("m1", "из Desktop", entrypoint="claude-desktop")], age=30)
        self.put("b", "code", [reply("m2", "из VS Code", entrypoint="claude-vscode")], age=10)
        self.put("b", "moved", [reply("m3", "начало", entrypoint="claude-vscode"),
                                reply("m4", "продолжение", entrypoint="claude-desktop")], age=20)
        self.assertEqual(context.chat_context(app="com.microsoft.VSCode", projects=self.d)["session"], "code")
        c = context.chat_context(app="com.anthropic.claudefordesktop", projects=self.d)
        self.assertEqual(c["session"], "moved")  # newer than desk, and its last line came from Desktop
        self.assertIsNone(context.chat_context(app="com.example.unknown", projects=self.d))
        self.assertTrue(os.path.exists(desk))

    def test_terms_are_latin_script_words_the_most_frequent_first_without_common_english_words(self):
        self.assertEqual(context.terms(["the GitHub Actions and GitHub", "use node.js, CI/CD and /Users/x/y/z.js"]),
                         ["GitHub", "CI/CD", "node.js", "Actions"])


if __name__ == "__main__":
    unittest.main()
