"""Tests of settings.py and llama.Models: the config file, its changes, and one model in memory. Run: server/.venv/bin/python -m unittest discover -s server"""
import asyncio
import json
import os
import tempfile
import time
import types
import unittest

import llama
import metrics
import settings as s
from fakes import FakeAgents, StubModel


class ModelsTest(unittest.IsolatedAsyncioTestCase):
    async def test_one_model_in_memory_at_a_time(self):
        entries = {"a": {"llamaServer": "http://h:1", "launchd": "x.a"}, "b": {"llamaServer": "http://h:2", "launchd": "x.b"}}
        with FakeAgents() as agents:
            models = llama.Models(entries, make=StubModel)
            a = await models.get("a")
            self.assertIs(await models.get("a"), a)  # made once
            self.assertEqual(agents.calls[:2], [("stop", "x.b"), ("start", "x.a")])
            await models.get("b")
            self.assertEqual(agents.calls[-2:], [("stop", "x.a"), ("start", "x.b")])


class SettingsTest(unittest.IsolatedAsyncioTestCase):
    def cli(self, **given):
        names = {v[0] for v in s.SETTINGS.values() if v[0]}
        return types.SimpleNamespace(**{**{n: None for n in names}, **given})

    def write(self, f, **c):
        json.dump({"version": 2, **c}, open(f, "w"))
        os.utime(f, ns=(time.time_ns(), time.time_ns()))

    def test_the_command_line_wins_then_the_file_then_the_defaults(self):
        models = {"a": {"llamaServer": "http://h:1"}}
        now = s.resolve(self.cli(port=8091), {"port": 9000, "pieceSeconds": 25.0, "models": models})
        self.assertEqual((now["port"], now["pieceSeconds"], now["cutSearchSeconds"], now["models"]), (8091, 25.0, 3.0, models))
        self.assertEqual((s.resolve(self.cli(), {})["models"], s.resolve(self.cli(), {})["saveRecordings"]),
                         (s.MODEL_DEFAULT, True))

    def test_the_file_has_the_registry_at_the_top_and_the_server_in_its_section(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            models = {"a": {"llamaServer": "http://h:1", "launchd": "x.a", "prompt": "P", "options": {"topK": 5}}}
            self.write(f, model="a", models=models, saveRecordings=False, silenceStopSeconds=60,
                       server={"pieceSeconds": 25, "port": 9000})
            self.assertEqual(s.file_settings(f), {"models": models, "saveRecordings": False, "pieceSeconds": 25.0,
                                                  "port": 9000})

    def test_a_wrong_key_or_value_in_the_file_is_left_out(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            self.write(f, models={"a": {"llamaServer": "http://h", "options": {"noRepeatNgramSize": 10}}},
                       server={"pieceSeconds": 25, "outputTokensBase": "many", "colour": "red"})
            with self.assertLogs("gemma_voice", "ERROR") as logs:
                self.assertEqual(s.file_settings(f), {"pieceSeconds": 25.0})
        self.assertEqual(len(logs.output), 3)  # colour, outputTokensBase, models (an unknown option)

    def test_a_file_of_another_version_is_not_read(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            json.dump({"version": 1, "gemmaVoice": {"pieceSeconds": 25}}, open(f, "w"))
            with self.assertLogs("gemma_voice", "ERROR") as logs:
                self.assertIsNone(s.file_settings(f))
        self.assertIn("install.sh migrates", logs.output[0])

    async def test_changes_of_the_file_take_effect_by_their_level(self):
        s.CONFIG_CHECK_S = 0.02
        calls = []

        class FakeModels:
            recording = asyncio.Lock()

            def reconfigure(self, entries):
                calls.append(("reconfigure", entries))

        saved = metrics.METRICS
        try:
            with tempfile.TemporaryDirectory() as d:
                f = os.path.join(d, "config.json")
                self.write(f)
                cli, st = self.cli(), types.SimpleNamespace()
                current = s.resolve(cli, {})
                s.apply_recording_settings(st, current)
                stop = asyncio.get_running_loop().create_future()
                task = asyncio.create_task(s.watch_config(cli, FakeModels(), st, current, f, stop, follow=False))
                await asyncio.sleep(0.05)
                self.write(f, server={"pieceSeconds": 25}, saveRecordings=False)  # recording settings
                await asyncio.sleep(0.1)
                self.assertEqual((st.piece_seconds, st.save_recordings, calls), (25.0, False, []))
                models = {"b": {"llamaServer": "http://h:2"}}
                self.write(f, server={"pieceSeconds": 25}, saveRecordings=False, models=models)  # a model setting
                await asyncio.sleep(0.1)
                self.assertEqual(calls, [("reconfigure", models)])
                self.write(f, server={"pieceSeconds": 25, "port": 9999}, saveRecordings=False, models=models)
                await asyncio.wait_for(stop, 1)  # the process ends
                await task
        finally:
            metrics.METRICS = saved


class SelectionTest(unittest.IsolatedAsyncioTestCase):
    async def test_only_the_model_chosen_in_the_menus_is_in_memory(self):
        with FakeAgents() as agents, tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            choose = lambda model: json.dump({"version": 2, "model": model}, open(f, "w"))
            models = llama.Models({"e4b": {"llamaServer": "http://127.0.0.1:8093", "launchd": "x.e4b"},
                               "llama": {"llamaServer": "http://127.0.0.1:8092", "launchd": "x.llama"}}, make=StubModel)
            chosen = [object()]
            choose("e4b")
            await s.follow_selection(models, f, chosen)
            self.assertEqual(agents.calls, [("stop", "x.llama"), ("start", "x.e4b")])
            choose("llama")
            await s.follow_selection(models, f, chosen)
            self.assertEqual(agents.calls[-2:], [("stop", "x.e4b"), ("start", "x.llama")])
            choose("anthropic")  # Anthropic: no model in memory
            await s.follow_selection(models, f, chosen)
            self.assertEqual(agents.calls[-2:], [("stop", "x.e4b"), ("stop", "x.llama")])
            models.manage = False  # a test server never starts or stops the agents
            n = len(agents.calls)
            await models.get("llama")
            self.assertEqual(len(agents.calls), n)


if __name__ == "__main__":
    unittest.main()
