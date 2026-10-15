"""Tests of settings.py and llama.Models: the config file, its changes, and one model in memory. Run: server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
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
        return types.SimpleNamespace(**{**{x.name: None for x in s.SETTINGS if x.flag}, **given})

    def write(self, f, **c):
        json.dump({"version": 3, **c}, open(f, "w"))
        os.utime(f, ns=(time.time_ns(), time.time_ns()))

    def test_the_command_line_wins_then_the_file_then_the_defaults(self):
        models = {"a": {"llamaServer": "http://h:1"}}
        now = s.resolve(self.cli(port=8091), {"port": 9000, "pieceSeconds": 25.0, "models": models})
        self.assertEqual((now["port"], now["pieceSeconds"], now["cutSearchSeconds"], now["models"]), (8091, 25.0, 3.0, models))
        self.assertEqual((s.resolve(self.cli(), {})["models"], s.resolve(self.cli(), {})["saveRecordings"]),
                         (s.MODEL_DEFAULT, True))

    def test_every_setting_with_a_flag_has_it_and_a_command_line_value_out_of_range_is_refused(self):
        import argparse
        p = argparse.ArgumentParser()
        s.add_flags(p)
        cli = p.parse_args(["--piece-seconds", "25", "--port", "9000", "--max-recording-seconds", "60"])
        now = s.resolve(cli, {})
        self.assertEqual((now["pieceSeconds"], now["port"], now["maxRecordingSeconds"]), (25.0, 9000, 60.0))
        with self.assertRaisesRegex(ValueError, "pieceSeconds"):
            s.resolve(p.parse_args(["--piece-seconds", "99"]), {})

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
        self.assertIn("the server reads version 3", logs.output[0])

    async def test_changes_of_the_file_take_effect_by_their_level(self):
        calls = []

        class FakeModels:
            recording = asyncio.Lock()

            def reconfigure(self, entries):
                calls.append(("reconfigure", entries))

        saved = metrics.path()
        try:
            with tempfile.TemporaryDirectory() as d:
                f = os.path.join(d, "config.json")
                self.write(f)
                cli = self.cli()
                current = s.resolve(cli, {})
                st = s.recording_settings(current)
                stop = asyncio.get_running_loop().create_future()
                w = s.ConfigWatcher(f, cli, FakeModels(), st, current, stop, follow=False)
                self.write(f, server={"pieceSeconds": 25}, saveRecordings=False)  # recording settings
                self.assertTrue(await w.check())
                self.assertEqual((st.piece_seconds, st.save_recordings, calls), (25.0, False, []))
                models = {"b": {"llamaServer": "http://h:2"}}
                self.write(f, server={"pieceSeconds": 25}, saveRecordings=False, models=models)  # a model setting
                self.assertTrue(await w.check())
                self.assertEqual(calls, [("reconfigure", models)])
                self.write(f, server={"pieceSeconds": 25, "port": 9999}, saveRecordings=False, models=models)
                self.assertFalse(await w.check())  # the process ends
                self.assertTrue(stop.done())
                self.write(f, server={"port": 9998})
                stop2 = asyncio.get_running_loop().create_future()
                stop2.set_result(None)  # already stopping (a signal): a second stop is no error
                w2 = s.ConfigWatcher(f, cli, FakeModels(), st, dict(current), stop2, follow=False)
                self.write(f, server={"port": 9997})
                self.assertFalse(await w2.check())
        finally:
            metrics.configure(saved)

    async def test_a_change_made_while_the_first_model_loads_is_not_lost(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            self.write(f)
            cli = self.cli()
            current = s.resolve(cli, {})
            st = s.recording_settings(current)

            class SlowModels:
                recording = asyncio.Lock()
                entries = {}

                async def activate(self, name):
                    await asyncio.sleep(0)
                    self_test.write(f, server={"pieceSeconds": 26})  # while the model loads

            self_test = self
            w = s.ConfigWatcher(f, cli, SlowModels(), st, current, asyncio.get_running_loop().create_future())
            await w.follow_selection()
            await w.check()
            self.assertEqual(st.piece_seconds, 26.0)


class SelectionTest(unittest.IsolatedAsyncioTestCase):
    async def test_only_the_model_chosen_in_the_menus_is_in_memory(self):
        with FakeAgents() as agents, tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            choose = lambda model: json.dump({"version": 3, "model": model}, open(f, "w"))
            models = llama.Models({"e4b": {"llamaServer": "http://h:1", "launchd": "x.e4b"},
                                   "big": {"llamaServer": "http://h:2", "launchd": "x.big"}}, make=StubModel)
            w = s.ConfigWatcher(f, self.cli(), models, s.recording_settings(s.resolve(self.cli(), {})), {}, None)
            choose("e4b")
            await w.follow_selection()
            self.assertEqual(agents.calls, [("stop", "x.big"), ("start", "x.e4b")])
            choose("big")
            await w.follow_selection()
            self.assertEqual(agents.calls[-2:], [("stop", "x.e4b"), ("start", "x.big")])
            choose("none of them")  # a name not in the registry: no model in memory
            await w.follow_selection()
            self.assertEqual(agents.calls[-2:], [("stop", "x.e4b"), ("stop", "x.big")])
            models.manage = False  # a test server never starts or stops the agents
            n = len(agents.calls)
            await models.get("big")
            self.assertEqual(len(agents.calls), n)

    def cli(self):
        return types.SimpleNamespace(**{x.name: None for x in s.SETTINGS if x.flag})


class LaunchdTest(unittest.TestCase):
    def test_a_refused_bootstrap_is_an_error_and_bootout_waits_until_the_agent_is_gone(self):
        state = {"loaded": True, "prints": 0}

        def fake(*args):
            if args[0] == "print":
                state["prints"] += 1
                return (0 if state["loaded"] else 113), ""
            if args[0] == "bootout":
                return 0, ""  # returns at once; the agent goes a moment later
            return 5, "Bootstrap failed: 5: Input/output error"

        saved = llama.launchd
        llama.launchd = fake
        try:
            import threading
            threading.Timer(0.3, lambda: state.update(loaded=False)).start()
            llama.stop_agent("x.a")
            self.assertFalse(state["loaded"])
            self.assertGreater(state["prints"], 2)  # it waited
            with self.assertRaisesRegex(RuntimeError, "bootstrap x.b: exit 5"):
                llama.start_agent("x.b")
        finally:
            llama.launchd = saved


class MigrateTest(unittest.TestCase):
    def test_version_2_becomes_3_with_every_built_in_plugin_enabled_and_the_order_kept(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            with open(f, "w", encoding="utf-8") as fh:
                json.dump({"model": "m", "language": "ru", "models": {}, "version": 2}, fh, indent=2)
            s.migrate(f)
            c = json.load(open(f, encoding="utf-8"))
            self.assertEqual(list(c), ["model", "language", "adapters", "models", "version"])
            self.assertEqual((c["version"], c["adapters"]), (3, {"claude": {"enabled": True}}))  # every built-in one
            s.migrate(f)  # a version-3 file stays as it is
            self.assertEqual(json.load(open(f, encoding="utf-8")), c)


if __name__ == "__main__":
    unittest.main()
