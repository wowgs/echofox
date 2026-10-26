"""Tests of settings.py and llama.Models: the config file, its changes, and one model in memory. Run: server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import asyncio
import json
import os
import plistlib
import tempfile
import time
import unittest
from unittest import mock

import catalog
import constants
import llama
import metrics
import info
import variants
import settings as s
import tuning
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


    async def test_an_agent_written_again_starts_again(self):
        entries = {"a": {"llamaServer": "http://h:1", "launchd": "x.a"}}
        with FakeAgents(rewrite={"x.a"}) as agents:  # another variant or models folder
            await llama.Models(entries, make=StubModel).get("a")
            self.assertEqual(agents.calls, [("stop", "x.a"), ("start", "x.a")])


class VariantTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="models-", dir=os.path.dirname(constants.path("~/x")))
        self.binary = os.path.join(self.folder, "llama-server")
        open(self.binary, "w").close()
        os.chmod(self.binary, 0o755)
        self.saved = constants.LLAMA_SERVER, llama.BUNDLED_LLAMA_SERVER
        constants.LLAMA_SERVER, llama.BUNDLED_LLAMA_SERVER = self.binary, os.path.join(self.folder, "none")

    def tearDown(self):
        constants.LLAMA_SERVER, llama.BUNDLED_LLAMA_SERVER = self.saved

    def test_the_bundles_llama_server_comes_first(self):
        self.assertEqual(llama.llama_server(), self.binary)  # no bundled one: the installed app's
        bundled = os.path.join(self.folder, "bundled-llama-server")
        open(bundled, "w").close()
        os.chmod(bundled, 0o755)
        llama.BUNDLED_LLAMA_SERVER = bundled
        self.assertEqual(llama.llama_server(), bundled)

    def put(self, *names):
        d = os.path.join(self.folder, "gemma-4-E4B-it-GGUF")
        os.makedirs(d, exist_ok=True)
        for n in names:
            open(os.path.join(d, n), "w").close()

    def test_a_registry_entry_has_its_catalogs_default_variant_unless_it_names_one(self):
        self.assertEqual(catalog.variant({"catalog": "gemma-4-e4b"})[0], "q8_0")
        vid, spec = catalog.variant({"catalog": "gemma-4-e4b", "variant": "q4_0"})
        self.assertEqual((vid, spec["files"]["model"]["file"]), ("q4_0", "gemma-4-E4B-it-Q4_0.gguf"))
        self.assertFalse(s.good_model({"llamaServer": "http://h:1", "variant": "q2_k"}))
        self.assertTrue(s.good_model({"llamaServer": "http://h:1", "variant": "q4_0"}))
        self.assertEqual(catalog.files({"variant": "q4_0"}, "/m"),
                         {"model": "/m/gemma-4-E4B-it-GGUF/gemma-4-E4B-it-Q4_0.gguf",
                          "mmproj": "/m/gemma-4-E4B-it-GGUF/mmproj-gemma-4-E4B-it-BF16.gguf"})
        self.assertEqual(catalog.url({}, "gemma-4-E4B-it-Q4_0.gguf"),
                         "https://huggingface.co/ggml-org/gemma-4-E4B-it-GGUF/resolve/"
                         "a69f018d7678a2b9f5e705f8903d6fb29b9b25dc/gemma-4-E4B-it-Q4_0.gguf")

    def test_the_agent_runs_the_variants_files_and_is_written_only_when_it_changes(self):
        entry = {"llamaServer": "http://127.0.0.1:8092", "launchd": "x.test", "catalog": "gemma-4-e4b"}
        with self.assertRaisesRegex(RuntimeError, "files of variant q8_0 are missing"):
            llama.agent(entry, self.folder)
        self.put("gemma-4-E4B-it-Q8_0.gguf", "gemma-4-E4B-it-Q4_0.gguf", "mmproj-gemma-4-E4B-it-BF16.gguf")
        a = llama.agent(entry, self.folder)["ProgramArguments"]
        self.assertEqual(a[:9], [self.binary, "-m", f"{self.folder}/gemma-4-E4B-it-GGUF/gemma-4-E4B-it-Q8_0.gguf",
                                 "--mmproj", f"{self.folder}/gemma-4-E4B-it-GGUF/mmproj-gemma-4-E4B-it-BF16.gguf",
                                 "--host", "127.0.0.1", "--port", "8092"])
        self.assertEqual(a[9:], catalog.of(entry)["llamaServer"]["args"])
        self.assertTrue(llama.write_agent(entry, self.folder))
        self.assertFalse(llama.write_agent(entry, self.folder))  # the same: not written again
        self.assertTrue(llama.write_agent({**entry, "variant": "q4_0"}, self.folder))
        with open(constants.path(f"{constants.LAUNCH_AGENTS}/x.test.plist"), "rb") as f:
            self.assertIn("gemma-4-E4B-it-Q4_0.gguf", plistlib.load(f)["ProgramArguments"][2])
        self.assertNotIn("EnvironmentVariables", llama.agent(entry, self.folder))  # from the repository: no version
        with mock.patch.dict(os.environ, {"ECHOFOX_APP_VERSION": "0.2 (180)"}):
            self.assertEqual(llama.agent(entry, self.folder)["EnvironmentVariables"], {"ECHOFOX_APP_VERSION": "0.2 (180)"})
            self.assertTrue(llama.write_agent({**entry, "variant": "q4_0"}, self.folder))  # a new app: written again

    def test_an_entry_of_the_default_models_name_gets_the_defaults_fields(self):
        f = os.path.join(self.folder, "config.json")
        with open(f, "w") as fh:
            json.dump({"version": constants.CONFIG_VERSION, "models": {"gemma-e4b": {"variant": "q4_0"}}}, fh)
        self.assertEqual(s.file_settings(f)["models"]["gemma-e4b"], {**s.MODEL_DEFAULT["gemma-e4b"], "variant": "q4_0"})

    def test_the_info_says_which_variants_are_downloaded(self):
        self.put("gemma-4-E4B-it-Q4_0.gguf", "mmproj-gemma-4-E4B-it-BF16.gguf")
        v = variants.variants({"catalog": "gemma-4-e4b"}, self.folder)
        self.assertEqual(v["variant"], "q8_0")
        self.assertEqual([(x["id"], x["downloaded"], x["bytes"]) for x in v["variants"]],
                         [("q4_0", True, 4590807392 + 991552256), ("q8_0", False, 8031242688 + 991552256)])


class SettingsTest(unittest.IsolatedAsyncioTestCase):
    def write(self, f, **c):
        json.dump({"version": constants.CONFIG_VERSION, **c}, open(f, "w"))
        os.utime(f, ns=(time.time_ns(), time.time_ns()))

    def test_the_file_wins_then_the_defaults(self):
        models = {"a": {"llamaServer": "http://h:1"}}
        now = s.resolve({"port": 9000, "maxRecordingMinutes": 25.0, "models": models})
        self.assertEqual((now["port"], now["maxRecordingMinutes"], now["saveRecordings"], now["models"]), (9000, 25.0, True, models))
        self.assertEqual((s.resolve({})["models"], s.resolve({})["saveRecordings"]), (s.MODEL_DEFAULT, True))

    def test_the_file_has_the_registry_at_the_top_and_the_server_in_its_section(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            models = {"a": {"llamaServer": "http://h:1", "launchd": "x.a", "prompt": "P", "options": {"topK": 5}}}
            self.write(f, model="a", models=models, silenceStopSeconds=60, languages={"ru": {"fillers": ["э"]}},
                       server={"maxRecordingMinutes": 25, "port": 9000, "saveRecordings": False})
            self.assertEqual(s.file_settings(f), {"models": models, "saveRecordings": False, "maxRecordingMinutes": 25.0,
                                                  "port": 9000, "languages": {"ru": {"fillers": ["э"]}}})

    def test_an_adapters_entry_may_set_its_context_budgets_and_nothing_else(self):
        now = s.resolve({"adapters": {"telegram": {"enabled": True, "chatHistoryTokenBudget": 600},
                                                  "claude": {"enabled": False}}})
        st = s.recording_settings(now)
        self.assertEqual((st.adapters, st.adapter_options), (["telegram"], {"telegram": {"chat_history_token_budget": 600},
                                                                            "claude": {}}))
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            for bad in ({"telegram": {"enabled": True, "chatHistoryTokens": 600}},
                        {"telegram": {"enabled": True, "chatHistoryTokenBudget": -1}}):
                self.write(f, adapters=bad)
                with self.assertLogs("gemma_voice", "ERROR"):
                    self.assertNotIn("adapters", s.file_settings(f))

    def test_a_wrong_key_or_value_in_the_file_is_left_out(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            self.write(f, models={"a": {"llamaServer": "http://h", "options": {"noRepeatNgramSize": 10}}},
                       server={"maxRecordingMinutes": 25, "pieceSeconds": 15, "saveRecordings": "many", "colour": "red"},
                       languages={"ru": {"fillers": "э"}})
            with self.assertLogs("gemma_voice", "ERROR") as logs:
                self.assertEqual(s.file_settings(f), {"maxRecordingMinutes": 25.0})
        # colour, pieceSeconds (a constant), saveRecordings, models (an unknown option), languages
        self.assertEqual(len(logs.output), 5)
        self.assertTrue(any("server.pieceSeconds is not a setting" in l for l in logs.output))

    def test_a_file_of_another_version_is_not_read(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            json.dump({"version": 1, "gemmaVoice": {"pieceSeconds": 25}}, open(f, "w"))
            with self.assertLogs("gemma_voice", "ERROR") as logs:
                self.assertIsNone(s.file_settings(f))
        self.assertIn(f"the server reads version {constants.CONFIG_VERSION}", logs.output[0])

    async def test_changes_of_the_file_take_effect_by_their_level(self):
        calls = []

        class FakeModels:
            recording = asyncio.Lock()

            def reconfigure(self, entries, models_folder=None):
                calls.append(("reconfigure", entries))

        saved = metrics.configure(constants.METRICS)  # the watcher sets it from the file; restored below
        try:
            with tempfile.TemporaryDirectory() as d:
                f = os.path.join(d, "config.json")
                self.write(f)
                current = s.resolve({})
                st = s.recording_settings(current)
                stop = asyncio.get_running_loop().create_future()
                w = s.ConfigWatcher(f, FakeModels(), st, current, stop, follow=False)
                self.write(f, server={"maxRecordingMinutes": 25, "saveRecordings": False})  # recording settings
                self.assertTrue(await w.check())
                self.assertEqual((st.max_recording_minutes, st.save_recordings, calls), (25.0, False, []))
                models = {"b": {"llamaServer": "http://h:2"}}
                self.write(f, server={"maxRecordingMinutes": 25, "saveRecordings": False}, models=models)  # a model setting
                self.assertTrue(await w.check())
                self.assertEqual(calls, [("reconfigure", models)])
                self.write(f, server={"maxRecordingMinutes": 25, "port": 9999, "saveRecordings": False}, models=models)
                self.assertFalse(await w.check())  # the process ends
                self.assertTrue(stop.done())
                self.write(f, server={"port": 9998})
                stop2 = asyncio.get_running_loop().create_future()
                stop2.set_result(None)  # already stopping (a signal): a second stop is no error
                w2 = s.ConfigWatcher(f, FakeModels(), st, dict(current), stop2, follow=False)
                self.write(f, server={"port": 9997})
                self.assertFalse(await w2.check())
        finally:
            metrics.configure(saved)

    async def test_a_change_made_while_the_first_model_loads_is_not_lost(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            self.write(f)
            current = s.resolve({})
            st = s.recording_settings(current)

            class SlowModels:
                recording = asyncio.Lock()
                entries, active = {}, llama.UNKNOWN

                async def activate(self, name):
                    await asyncio.sleep(0)
                    self_test.write(f, server={"maxRecordingMinutes": 26})  # while the model loads

            self_test = self
            w = s.ConfigWatcher(f, SlowModels(), st, current, asyncio.get_running_loop().create_future())
            await w.follow_selection()
            await w.check()
            self.assertEqual(st.max_recording_minutes, 26.0)


class SelectionTest(unittest.IsolatedAsyncioTestCase):
    async def test_the_info_names_the_menus_model_of_the_servers_own_config_file(self):
        # A server started with --config (the test server) reads its own file, not the default one
        with FakeAgents(), tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "other-config.json")
            json.dump({"version": constants.CONFIG_VERSION, "model": "big"}, open(f, "w"))
            models = llama.Models({"e4b": {"llamaServer": "http://h:1", "launchd": "x.e4b"},
                                   "big": {"llamaServer": "http://h:2", "launchd": "x.big"}}, make=StubModel)
            st = s.recording_settings(s.resolve({}))
            s.ConfigWatcher(f, models, st, {}, None, follow=False)
            self.assertEqual(info.info(st, models)["model"]["name"], "big")

    async def test_only_the_model_chosen_in_the_menus_is_in_memory(self):
        with FakeAgents() as agents, tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            choose = lambda model: json.dump({"version": constants.CONFIG_VERSION, "model": model}, open(f, "w"))
            models = llama.Models({"e4b": {"llamaServer": "http://h:1", "launchd": "x.e4b"},
                                   "big": {"llamaServer": "http://h:2", "launchd": "x.big"}}, make=StubModel)
            w = s.ConfigWatcher(f, models, s.recording_settings(s.resolve({})), {}, None)
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

    async def test_a_recording_on_the_active_model_runs_no_launchctl_and_the_menus_model_comes_back(self):
        with FakeAgents() as agents, tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            json.dump({"version": constants.CONFIG_VERSION, "model": "e4b"}, open(f, "w"))
            models = llama.Models({"e4b": {"llamaServer": "http://h:1", "launchd": "x.e4b"},
                                   "big": {"llamaServer": "http://h:2", "launchd": "x.big"}}, make=StubModel)
            w = s.ConfigWatcher(f, models, s.recording_settings(s.resolve({})), {}, None)
            await w.follow_selection()
            n = len(agents.calls)
            await models.get("e4b")
            await models.get("e4b")
            self.assertEqual(len(agents.calls), n)  # the active model: no launchctl for each recording
            await models.get("big")  # a client asked for another model
            self.assertEqual(agents.calls[-2:], [("stop", "x.e4b"), ("start", "x.big")])
            await w.follow_selection()  # the menu's model is not in memory any more: it comes back
            self.assertEqual(agents.calls[-2:], [("stop", "x.big"), ("start", "x.e4b")])


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
    def test_version_2_becomes_3_with_the_built_in_plugins_that_read_no_screen_enabled_and_the_order_kept(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            c, _ = s.from_2({"model": "m", "language": "ru", "models": {}, "version": 2}, f)
            self.assertEqual(list(c), ["model", "language", "adapters", "models", "version"])
            self.assertEqual((c["version"], c["adapters"]), (3, {}))  # claude and telegram read the screen
            with open(f, "w", encoding="utf-8") as fh:
                json.dump({"model": "m", "models": {}, "version": constants.CONFIG_VERSION}, fh, indent=2)
            mtime = os.stat(f).st_mtime_ns
            s.migrate(f)  # a file of this version is not written
            self.assertEqual(os.stat(f).st_mtime_ns, mtime)

    def test_version_3_becomes_7_with_each_setting_at_its_owner(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            v3 = {"model": "m", "adapters": {"claude": {"enabled": True, "chatHistoryTokenBudget": 1000},
                                             "telegram": {"enabled": True}},
                  "models": {"m": {"llamaServer": "http://h:1", "prompt": "P",
                                   "options": {"chatHistoryTokenBudget": 2000, "temperature": 1, "pieceSeconds": 12,
                                               "gone": 1}}},
                  "saveRecordings": False, "labeled": "~/l", "fillers": {"ru": ["э"]},
                  "server": {"port": 8090, "outputTokensBase": 40}, "version": 3}
            with open(f, "w", encoding="utf-8") as fh:
                json.dump(v3, fh)
            s.migrate(f)
            c = json.load(open(f, encoding="utf-8"))
            self.assertEqual(c["version"], 7)
            self.assertEqual(c["models"]["m"], {"llamaServer": "http://h:1", "prompt": "P",
                                                "options": {"temperature": 1}, "catalog": "gemma-4-e4b"})
            self.assertEqual(c["adapters"]["claude"]["chatHistoryTokenBudget"], 1000)   # its own value stays
            self.assertEqual(c["adapters"]["telegram"]["chatHistoryTokenBudget"], 2000)  # the model's was its value
            self.assertEqual(c["server"], {"port": 8090, "saveRecordings": False, "labeled": "~/l"})  # pieceSeconds: a constant
            self.assertEqual(c["languages"], {"ru": {"fillers": ["э"]}})
            self.assertNotIn("fillers", c)
            self.assertEqual(s.file_settings(f)["languages"], {"ru": {"fillers": ["э"]}})  # the server reads it

    def test_version_4_becomes_7_without_the_second_ways_and_the_order_kept(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            v4 = {"model": "m", "version": 4,
                  "adapters": {"claude": {"enabled": True, "chatHistoryTokenBudget": 0}, "telegram": {"enabled": True}},
                  "adapterDefaults": {"chatHistoryTokenBudget": 0, "proseOnly": False},
                  "models": {"m": {"llamaServer": "http://h:1", "options": {"outputTokensPerSecond": 8,
                                                                         "maxOutputTokens": 99, "topK": 5}},
                             "n": {"llamaServer": "http://h:2", "options": {"outputTokensBase": 40}}},
                  "server": {"thresholdDb": -45, "speechAboveNoiseDb": 12, "maxCharsPerSpeechSecond": 60,
                             "pieceSeconds": 15, "maxRecordingSeconds": 600}}
            with open(f, "w", encoding="utf-8") as fh:
                json.dump(v4, fh)
            with self.assertLogs("gemma_voice", "INFO") as logs:
                s.migrate(f)
            c = json.load(open(f, encoding="utf-8"))
            self.assertEqual(list(c), [k for k in v4 if k != "adapterDefaults"])
            self.assertEqual(c["version"], 7)
            self.assertEqual(c["server"], {"maxRecordingMinutes": 10})
            self.assertEqual(c["models"]["m"]["options"], {"topK": 5})
            self.assertNotIn("options", c["models"]["n"])
            # a budget of 0 was the switch; adapterDefaults' proseOnly went to every adapter
            self.assertEqual(c["adapters"], {"claude": {"enabled": False, "proseOnly": False},
                                             "telegram": {"enabled": True, "proseOnly": False}})
            self.assertIn("thresholdDb=-45", logs.output[0])
            self.assertEqual(s.file_settings(f)["maxRecordingMinutes"], 10.0)


    def test_version_6_becomes_7_with_adapter_defaults_in_each_adapter(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            v6 = {"version": 6, "adapters": {"claude": {"enabled": True, "chatTermsTokenBudget": 50},
                                             "telegram": {"enabled": True}},
                  "adapterDefaults": {"chatTermsTokenBudget": 150, "proseOnly": False}, "model": "m"}
            with open(f, "w", encoding="utf-8") as fh:
                json.dump(v6, fh)
            s.migrate(f)
            c = json.load(open(f, encoding="utf-8"))
            self.assertEqual(list(c), ["version", "adapters", "model"])
            self.assertEqual(c["version"], 7)
            self.assertEqual(c["adapters"], {"claude": {"enabled": True, "chatTermsTokenBudget": 50, "proseOnly": False},
                                             "telegram": {"enabled": True, "chatTermsTokenBudget": 150, "proseOnly": False}})

    def test_version_5_becomes_7_without_the_constants_and_with_minutes(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            v5 = {"version": 5, "server": {"port": 8090, "pieceSeconds": 15, "cutSearchSeconds": 3,
                                           "maxRecordingSeconds": 1800, "warmText": True},
                  "models": {"m": {"llamaServer": "http://h:1",
                                   "options": {"temperature": 1, "contextAsSystem": False,
                                               "maxTokensPerSpeechSecond": 20}},
                             "n": {"llamaServer": "http://h:2", "options": {"contextAsSystem": True}}}}
            with open(f, "w", encoding="utf-8") as fh:
                json.dump(v5, fh)
            s.migrate(f)
            c = json.load(open(f, encoding="utf-8"))
            self.assertEqual(c["version"], 7)
            self.assertEqual(c["server"], {"port": 8090, "maxRecordingMinutes": 30})
            self.assertEqual(c["models"]["m"]["options"], {"temperature": 1})
            self.assertNotIn("options", c["models"]["n"])
            self.assertEqual(s.file_settings(f)["maxRecordingMinutes"], 30.0)


class SchemaTest(unittest.TestCase):
    def test_the_constants_are_not_settings_and_the_tuning_ones_are_advanced(self):
        st = s.recording_settings(s.resolve({}))
        info = {e["key"]: e for e in s.schema(st, {"catalog": "gemma-4-e4b"})}
        for constant in ("pieceSeconds", "minSpeechSeconds", "warmText", "maxTokensPerSpeechSecond"):
            self.assertNotIn(constant, info)
        self.assertNotIn("advanced", info["maxRecordingMinutes"])
        for key in ("temperature", "topK", "topP", "seed", "chatHistoryTokenBudget", "chatTermsTokenBudget",
                    "proseOnly"):
            self.assertTrue(info[key]["advanced"], key)
        with self.assertRaisesRegex(ValueError, "unknown server key pieceSeconds"):
            tuning.parse({"pieceSeconds": 12}, "server", "server")  # not the user's to set
        self.assertEqual(tuning.parse_options({"pieceSeconds": 12}), {"piece_seconds": 12.0})  # an experiment's

    def test_every_catalog_entry_gives_the_models_constants(self):
        for name, entry in catalog.entries().items():
            self.assertIsNotNone(s.model_defaults({"catalog": name}).get("max_tokens_per_speech_second"), name)


if __name__ == "__main__":
    unittest.main()
