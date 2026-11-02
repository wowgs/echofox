"""Tests of model_registry.py: one model in memory, the menu's model, the idle unload. Run:
server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import asyncio
import logging
import os
import tempfile
import time
import unittest

import catalog
import constants
import info
import model_registry
import settings
from fakes import FakeLlama, StubModel
from model_registry import Models

A, B = "http://127.0.0.1:1", "http://127.0.0.1:2"  # llama-servers on this Mac, which the server starts
ENTRIES = {"e4b": {"llamaServer": A}, "big": {"llamaServer": B}}


class ModelsTest(unittest.IsolatedAsyncioTestCase):
    async def test_one_model_in_memory_at_a_time(self):
        entries = {"a": {"llamaServer": A}, "b": {"llamaServer": B}}
        with FakeLlama() as llamas:
            models = Models(entries, make=StubModel)
            a = await models.get("a")
            self.assertIs(await models.get("a"), a)  # made once, started once
            self.assertEqual(llamas.calls, [("start", A)])
            await models.get("b")
            self.assertEqual(llamas.calls[-2:], [("stop", A), ("start", B)])
            models.close()  # the server ends: its llama-server too
            self.assertEqual(llamas.calls[-1], ("stop", B))

    async def test_another_variant_starts_again_and_one_that_ended_starts_again(self):
        entries = {"a": {"llamaServer": A}}
        with FakeLlama() as llamas:
            models = Models(entries, make=StubModel)
            await models.get("a")
            models.configure({"a": {"llamaServer": A, "variant": "q4_0"}}, constants.MODELS_FOLDER, None)
            await models.get("a")
            self.assertEqual(llamas.calls, [("start", A), ("stop", A), ("start", A)])
            llamas.procs[-1].returncode = 1  # it crashed
            await models.get("a")
            self.assertEqual(llamas.calls[-2:], [("stop", A), ("start", A)])

    async def test_an_idle_model_leaves_memory_and_the_next_recording_loads_it_first(self):
        saved = constants.IDLE_POLL_S
        constants.IDLE_POLL_S = 0.01
        try:
            with FakeLlama() as llamas:
                models = Models({"a": {"llamaServer": A}}, make=StubModel)
                await models.get("a")
                idle = asyncio.create_task(models.unload_when_idle(lambda: 0.05))
                await asyncio.sleep(0.2)
                self.assertEqual(llamas.calls, [("start", A), ("stop", A)])
                self.assertEqual(models.active, "a")  # still the chosen one: the menu's choice loads nothing again
                await models.follow_menu()
                self.assertEqual(llamas.calls[-1], ("stop", A))
                await models.get("a")  # a recording: the model loads first
                self.assertEqual(llamas.calls[-1], ("start", A))
                idle.cancel()
                never = asyncio.create_task(models.unload_when_idle(lambda: 0))  # 0: it stays
                await asyncio.sleep(0.1)
                never.cancel()
                self.assertEqual(llamas.calls[-1], ("start", A))
        finally:
            constants.IDLE_POLL_S = saved

    async def test_a_model_on_another_computer_is_only_asked(self):
        with FakeLlama() as llamas:
            await Models({"far": {"llamaServer": "http://ubu.example:8080"}}, make=StubModel).get("far")
            self.assertEqual(llamas.calls, [])


class MenuTest(unittest.IsolatedAsyncioTestCase):
    async def test_only_the_model_chosen_in_the_menus_is_in_memory(self):
        with FakeLlama() as llamas:
            models = Models(ENTRIES, make=StubModel, chosen="e4b")
            choose = lambda name: models.configure(ENTRIES, constants.MODELS_FOLDER, name)
            await models.follow_menu()
            self.assertEqual(llamas.calls, [("start", A)])
            choose("big")
            await models.follow_menu()
            self.assertEqual(llamas.calls[-2:], [("stop", A), ("start", B)])
            choose("none of them")  # a name not in the registry: no model in memory
            await models.follow_menu()
            self.assertEqual((models.selected, llamas.calls[-1]), (None, ("stop", B)))
            choose(None)  # the config names none (no config yet, the first start): the default, the registry's first
            await models.follow_menu()
            self.assertEqual((models.selected, llamas.calls[-1]), ("e4b", ("start", A)))
            models.manage = False  # a test server never starts or stops a llama-server
            n = len(llamas.calls)
            await models.get("big")
            choose("big")
            await models.follow_menu()
            self.assertEqual(len(llamas.calls), n)

    async def test_a_recording_on_the_active_model_starts_nothing_and_the_menus_model_comes_back(self):
        with FakeLlama() as llamas:
            models = Models(ENTRIES, make=StubModel, chosen="e4b")
            await models.follow_menu()
            n = len(llamas.calls)
            await models.get("e4b")
            await models.get("e4b")
            self.assertEqual(len(llamas.calls), n)  # the active model: nothing started for each recording
            await models.get("big")  # a client asked for another model
            self.assertEqual(llamas.calls[-2:], [("stop", A), ("start", B)])
            await models.follow_menu()  # the menu's model is not in memory any more: it comes back
            self.assertEqual(llamas.calls[-2:], [("stop", B), ("start", A)])

    async def test_a_menus_model_without_files_is_logged_once_and_starts_when_they_come(self):
        # The real command: the variant's files are looked for in the models folder (2026-10-28: the error and its
        # traceback came every 2 s, 88 times, while the chosen model had no files)
        folder = tempfile.mkdtemp(prefix="models-", dir=sandbox.ROOT)
        binary = os.path.join(folder, "llama-server")
        open(binary, "w").close()
        os.chmod(binary, 0o755)
        saved = constants.LLAMA_SERVER
        constants.LLAMA_SERVER = binary
        self.addCleanup(setattr, constants, "LLAMA_SERVER", saved)
        entry = {"llamaServer": A, "catalog": "gemma-4-e4b"}
        models = Models({"e4b": entry}, make=StubModel, models_folder=folder, chosen="e4b")
        with self.assertLogs("echofox-server", "INFO") as logs:
            for _ in range(3):
                await models.follow_menu()
        errors = [r.getMessage() for r in logs.records if r.levelno >= logging.ERROR]
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("the files of variant q4_0 are missing", errors[0])
        self.assertEqual(len([r for r in logs.records if "only it stays in memory" in r.getMessage()]), 1)
        for path in catalog.files(entry, folder).values():
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").close()
        n = len(sandbox.SPAWNED)
        with self.assertNoLogs("echofox-server", "ERROR"):
            await models.follow_menu()
        self.assertEqual((models.active, models.failed, len(sandbox.SPAWNED)), ("e4b", None, n + 1))

    async def test_the_loop_follows_a_change_at_once(self):
        with FakeLlama() as llamas:
            models = Models(ENTRIES, make=StubModel, chosen="e4b")
            loop = asyncio.create_task(models.run(lambda: 0))
            try:
                async def until(call):
                    t = time.monotonic()
                    while llamas.calls[-1:] != [call]:
                        await asyncio.sleep(0.01)
                    return time.monotonic() - t
                await asyncio.wait_for(until(("start", A)), 1)
                models.configure(ENTRIES, constants.MODELS_FOLDER, "big")
                self.assertLess(await asyncio.wait_for(until(("start", B)), 1), model_registry.RETRY_S / 2)
            finally:
                loop.cancel()

    async def test_the_info_names_the_menus_model_else_the_default(self):
        with FakeLlama():
            st = settings.recording_settings(settings.resolve({}))
            models = Models(ENTRIES, make=StubModel, chosen="big")
            self.assertEqual(info.info(st, models)["model"]["name"], "big")
            # A model this server does not have: none in memory, and the settings window shows the default's
            models.configure(ENTRIES, constants.MODELS_FOLDER, "other")
            self.assertEqual((models.selected, info.info(st, models)["model"]["name"]), (None, "e4b"))


if __name__ == "__main__":
    unittest.main()
