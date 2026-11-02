"""Tests of session.py: the start message and the files of a recording (the recording itself, over a connection, is
in test_protocol.py). Run: server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import json
import os
import pathlib
import unittest

import microphone
import session
from fakes import args, stub_models

MODELS = {"gemma-e4b": {"llamaServer": "http://h:1"},
          "own": {"llamaServer": "http://h:2", "prompt": "Model's {LANGUAGE}."}}
IDENTITY = {"app": {"bundleId": "com.example.app", "pid": 1, "name": "App"}}


def start(**m):
    return session.parse_start({"type": "start", **m}, stub_models(MODELS), args())


class StartTest(unittest.TestCase):
    def test_a_start_that_cannot_run_is_refused_with_the_reason(self):
        for m, why in (({"type": "stop"}, "expected a start message"),
                       ({"type": "start", "sampleRate": 48000}, "16000 Hz"),
                       ({"type": "start", "encoding": "f32"}, "pcm_s16le"),
                       ({"type": "start", "model": "nope"}, "this server has: gemma-e4b, own"),
                       ({"type": "start", "options": {"pieceSeconds": 1}}, "out of range")):
            with self.assertRaisesRegex(ValueError, why):
                session.parse_start(m, stub_models(MODELS))

    def test_the_model_its_options_and_the_clients_apart(self):
        s = start(options={"temperature": 0.3}, client="x" * 100)
        self.assertEqual(s.model, "gemma-e4b")  # no model named: the registry's first
        self.assertEqual((s.options["temperature"], s.options["top_k"]), (0.3, 64))  # the client's, the catalog's
        self.assertEqual(s.client_options, {"temperature": 0.3})
        self.assertEqual(s.client, "x" * session.CLIENT_NAME_CHARS)

    def test_the_prompt_is_the_clients_else_the_models_with_the_language(self):
        german = start(model="own", language="de")
        self.assertEqual(german.own_prompt, "Model's {LANGUAGE}.")
        self.assertEqual(german.text_prompt, "Model's German.\n* The speech is German with English technical terms.\n"
                         "* Keep German words in the German script, also those made from English words with German "
                         "endings.")
        self.assertEqual(start(model="own", language="en", prompt="Mine.").text_prompt, "Mine.")
        self.assertEqual(start(language="en").own_prompt, "")  # the catalog's template

    def test_a_private_start_drops_the_identity(self):
        self.assertEqual(start(identity=IDENTITY).identity, IDENTITY)
        private = start(identity=IDENTITY, private=True)
        self.assertEqual((private.identity, private.private), ({}, True))
        self.assertFalse(start(private="yes").private)  # only true is private


class FilesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.saved = microphone.state
        microphone.state = lambda: {"inputVolume": 40, "device": None}

    def tearDown(self):
        microphone.state = self.saved

    def session(self, save=True, **m):
        a = args(save_recordings=save)
        return session.Session(None, None, None, a, session.parse_start({"type": "start", **m}, stub_models(MODELS), a),
                               make_stream=object), a

    async def test_a_saved_recording_gets_its_folder_and_its_record_with_the_microphone(self):
        s, a = self.session(language="ru")
        self.assertTrue(s.files.saved)
        self.assertEqual(s.id, os.path.relpath(s.files.dir, a.recordings))
        s.texts, s.stop_reason = ["one", "two"], "user"
        await s.finish()
        record = json.loads(pathlib.Path(s.files.dir, "adapter.json").read_text(encoding="utf-8"))
        self.assertEqual((record["id"], record["language"], record["text"], record["stopReason"], record["input"]),
                         (s.id, "ru", "one two", "user", {"inputVolume": 40, "device": None}))

    async def test_a_private_or_unsaved_recording_writes_no_folder_and_asks_nothing_of_macos(self):
        for s, a in (self.session(private=True), self.session(save=False)):
            self.assertFalse(s.files.saved)
            self.assertTrue(s.id.endswith("-unsaved"), s.id)
            self.assertIsNone(s.mic)
            await s.finish()
            self.assertEqual(os.listdir(a.recordings), [])


if __name__ == "__main__":
    unittest.main()
