"""Tests of settings.py: the config file, its changes, and what the watcher hands to the model registry. Run:
server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import asyncio
import json
import os
import pathlib
import tempfile
import time
import unittest

import constants
import metrics
import settings as s
import tuning
from fakes import FakeLlama, StubModel
from model_registry import Models


A, B = "http://127.0.0.1:1", "http://127.0.0.1:2"  # llama-servers on this Mac, which the server starts


class SettingsTest(unittest.IsolatedAsyncioTestCase):
    def write(self, f, **c):
        pathlib.Path(f).write_text(json.dumps({"version": constants.CONFIG_VERSION, **c}))
        os.utime(f, ns=(time.time_ns(), time.time_ns()))

    def test_a_wrong_variant_leaves_the_model_without_it(self):
        problems = []
        models = {"a": {"llamaServer": "http://h:1", "variant": "q2_k"}, "b": {"llamaServer": "http://h:1", "variant": "q4_0"}}
        self.assertEqual(s.clean_models(models, lambda *p: problems.append(p)),
                         {"a": {"llamaServer": "http://h:1"}, "b": {"llamaServer": "http://h:1", "variant": "q4_0"}})
        self.assertEqual([wrong for _, wrong in problems], [True])  # a wrong variant: the model stays, without it

    def test_an_entry_of_the_default_models_name_gets_the_defaults_fields(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            self.write(f, models={"gemma-e4b": {"variant": "q4_0"}})
            self.assertEqual(s.file_settings(f)["models"]["gemma-e4b"], {**s.MODEL_DEFAULT["gemma-e4b"], "variant": "q4_0"})

    def test_the_file_wins_then_the_defaults(self):
        models = {"a": {"llamaServer": "http://h:1"}}
        now = s.resolve({"port": 9000, "maxRecordingSeconds": 25.0, "models": models})
        self.assertEqual((now["port"], now["maxRecordingSeconds"], now["saveRecordings"], now["models"]), (9000, 25.0, True, models))
        self.assertEqual((s.resolve({})["models"], s.resolve({})["saveRecordings"]), (s.MODEL_DEFAULT, True))

    def test_the_file_has_the_registry_at_the_top_and_the_server_in_its_section(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            models = {"a": {"llamaServer": "http://h:1", "prompt": "P", "options": {"topK": 5}}}
            self.write(f, model="a", models=models, silenceStopSeconds=60, languages={"ru": {"fillers": ["э"]}},
                       server={"maxRecordingSeconds": 25, "port": 9000, "saveRecordings": False})
            self.assertEqual(s.file_settings(f), {"model": "a", "models": models, "saveRecordings": False,
                                                  "maxRecordingSeconds": 25.0, "port": 9000,
                                                  "languages": {"ru": {"fillers": ["э"]}}})

    def test_an_adapters_entry_may_set_its_context_budgets_and_nothing_else(self):
        now = s.resolve({"adapters": {"telegram": {"enabled": True, "chatHistoryTokenBudget": 600},
                                                  "claude": {"enabled": False}}})
        st = s.recording_settings(now)
        self.assertEqual((st.adapters, st.adapter_options), (["telegram"], {"telegram": {"chat_history_token_budget": 600},
                                                                            "claude": {}}))
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            # an unknown key (a newer version's) or a wrong budget leaves out that key only: the adapter stays on
            for bad, level in (({"telegram": {"enabled": True, "chatHistoryTokens": 600}}, "WARNING"),
                               ({"telegram": {"enabled": True, "chatHistoryTokenBudget": -1}}, "ERROR")):
                self.write(f, adapters=bad)
                with self.assertLogs("gemma_voice", "WARNING") as logs:
                    self.assertEqual(s.file_settings(f)["adapters"], {"telegram": {"enabled": True}})
                self.assertEqual([r.levelname for r in logs.records], [level])

    def test_a_wrong_key_or_value_in_the_file_is_left_out(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            self.write(f, models={"a": {"llamaServer": "http://h", "options": {"noRepeatNgramSize": 10}}},
                       server={"maxRecordingSeconds": 25, "pieceSeconds": 15, "saveRecordings": "many", "colour": "red"},
                       languages={"ru": {"fillers": "э"}})
            with self.assertLogs("gemma_voice", "WARNING") as logs:
                self.assertEqual(s.file_settings(f), {"maxRecordingSeconds": 25.0, "languages": {"ru": {}},
                                                      "models": {"a": {"llamaServer": "http://h", "options": {}}}})
        # unknown: colour, pieceSeconds (a constant), the model's option; wrong: saveRecordings, the fillers
        self.assertEqual(sorted(r.levelname for r in logs.records), ["ERROR", "ERROR", "WARNING", "WARNING", "WARNING"])
        self.assertTrue(any("server.pieceSeconds is not a setting" in l for l in logs.output))

    def test_a_file_of_a_newer_format_is_read_key_by_key_and_not_written(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            text = json.dumps({"version": constants.CONFIG_VERSION + 1, "adapters": {"telegram": {"enabled": True}},
                               "newThing": {"x": 1}, "server": {"port": 9000, "newKnob": 2}})
            pathlib.Path(f).write_text(text)
            with self.assertLogs("gemma_voice", "WARNING"):
                self.assertEqual(s.file_settings(f), {"adapters": {"telegram": {"enabled": True}}, "port": 9000})
            s.migrate(f)
            self.assertEqual(pathlib.Path(f).read_text(), text)  # nothing of it written over
            self.assertEqual(os.listdir(d), ["config.json"])

    def test_a_file_of_an_older_format_is_brought_up_once_and_kept_as_it_was(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            old = json.dumps({"version": 9, "language": "ru", "adapters": {"claude-code": {"enabled": True}}})
            pathlib.Path(f).write_text(old)
            self.assertEqual(s.file_settings(f)["adapters"], {"claude-code": {"enabled": True}})
            self.assertEqual(json.loads(pathlib.Path(f).read_text())["version"], constants.CONFIG_VERSION)
            self.assertEqual(pathlib.Path(f + ".v9.bak").read_text(), old)

    async def test_changes_of_the_file_take_effect_by_their_level(self):
        calls = []

        class FakeModels:
            recording = asyncio.Lock()

            def configure(self, entries, models_folder, chosen):
                calls.append(("configure", entries, models_folder, chosen))

        saved = metrics.configure(constants.METRICS)  # the watcher sets it from the file; restored below
        try:
            with tempfile.TemporaryDirectory() as d:
                f = os.path.join(d, "config.json")
                self.write(f)
                current = s.resolve({})
                st = s.recording_settings(current)
                stop = asyncio.get_running_loop().create_future()
                w = s.ConfigWatcher(f, FakeModels(), st, current, stop)
                self.write(f, server={"maxRecordingSeconds": 25, "saveRecordings": False})  # recording settings
                self.assertTrue(await w.check())
                self.assertEqual((st.max_recording_seconds, st.save_recordings, calls), (25.0, False, []))
                models = {"b": {"llamaServer": "http://h:2"}}
                self.write(f, server={"maxRecordingSeconds": 25, "saveRecordings": False}, models=models)  # a model setting
                self.assertTrue(await w.check())
                self.assertEqual(calls, [("configure", models, constants.MODELS_FOLDER, None)])
                self.write(f, server={"maxRecordingSeconds": 25, "saveRecordings": False}, models=models, model="b")
                self.assertTrue(await w.check())  # the menu's model: a model setting too
                self.assertEqual(calls[-1], ("configure", models, constants.MODELS_FOLDER, "b"))
                self.write(f, server={"maxRecordingSeconds": 25, "port": 9999, "saveRecordings": False}, models=models,
                           model="b")
                self.assertFalse(await w.check())  # the process ends
                self.assertTrue(stop.done())
                self.write(f, server={"port": 9998})
                stop2 = asyncio.get_running_loop().create_future()
                stop2.set_result(None)  # already stopping (a signal): a second stop is no error
                w2 = s.ConfigWatcher(f, FakeModels(), st, dict(current), stop2)
                self.write(f, server={"port": 9997})
                self.assertFalse(await w2.check())
        finally:
            metrics.configure(saved)

    async def test_the_registry_follows_the_menus_model_and_keeps_it_when_the_file_cannot_be_read(self):
        with FakeLlama() as llamas, tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            entries = {"e4b": {"llamaServer": A}, "big": {"llamaServer": B}}
            self.write(f, model="e4b", models=entries)
            current = s.resolve(s.file_settings(f))
            models = Models(current["models"], make=StubModel, chosen=current["model"])
            w = s.ConfigWatcher(f, models, s.recording_settings(current), current, None)
            await models.follow_menu()
            self.write(f, model="big", models=entries)
            await w.check()
            await models.follow_menu()
            self.assertEqual(llamas.calls, [("start", A), ("stop", A), ("start", B)])
            pathlib.Path(f).write_text("{not JSON")  # a hand edit gone wrong: the settings stay, the model too
            os.utime(f, ns=(time.time_ns() + 10**9, time.time_ns() + 10**9))
            with self.assertLogs("gemma_voice", "ERROR"):
                self.assertTrue(await w.check())
            await models.follow_menu()
            self.assertEqual((models.selected, llamas.calls[-1]), ("big", ("start", B)))


class MigrateTest(unittest.TestCase):
    def test_version_2_becomes_3_with_the_adapter_of_its_time_enabled_and_the_order_kept(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            c, _ = s.from_2({"model": "m", "language": "ru", "models": {}, "version": 2}, f)
            self.assertEqual(list(c), ["model", "language", "adapters", "models", "version"])
            # Only claude, the one adapter of version 2: a built-in adapter that came later is not turned on
            self.assertEqual((c["version"], c["adapters"]), (3, {"claude": {"enabled": True}}))
            with open(f, "w", encoding="utf-8") as fh:
                json.dump({"model": "m", "models": {}, "version": constants.CONFIG_VERSION}, fh, indent=2)
            mtime = os.stat(f).st_mtime_ns
            s.migrate(f)  # a file of this version is not written
            self.assertEqual(os.stat(f).st_mtime_ns, mtime)

    def test_version_3_becomes_11_with_each_setting_at_its_owner(self):
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
            c = json.loads(pathlib.Path(f).read_text(encoding="utf-8"))
            self.assertEqual(c["version"], 11)
            self.assertEqual(c["models"]["m"], {"llamaServer": "http://h:1", "prompt": "P",
                                                "options": {"temperature": 1}, "catalog": "gemma-4-e4b"})
            self.assertEqual(c["adapters"]["claude-code"]["chatHistoryTokenBudget"], 1000)  # its own value stays
            self.assertNotIn("claude-chat", c["adapters"])  # new in version 8, and it reads the screen
            self.assertEqual(c["adapters"]["telegram"]["chatHistoryTokenBudget"], 2000)  # the model's was its value
            self.assertEqual(c["server"], {"port": 8090, "saveRecordings": False, "labeled": "~/l"})  # pieceSeconds: a constant
            self.assertEqual(c["languages"], {"ru": {"fillers": ["э"]}})
            self.assertNotIn("fillers", c)
            self.assertEqual(s.file_settings(f)["languages"], {"ru": {"fillers": ["э"]}})  # the server reads it

    def test_version_4_becomes_11_without_the_second_ways_and_the_order_kept(self):
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
            c = json.loads(pathlib.Path(f).read_text(encoding="utf-8"))
            self.assertEqual(list(c), [k for k in v4 if k != "adapterDefaults"])
            self.assertEqual(c["version"], 11)
            self.assertEqual(c["server"], {"maxRecordingSeconds": 600})
            self.assertEqual(c["models"]["m"]["options"], {"topK": 5})
            self.assertNotIn("options", c["models"]["n"])
            # a budget of 0 was the switch; adapterDefaults' proseOnly went to every adapter
            self.assertEqual(c["adapters"], {"claude-code": {"enabled": False, "proseOnly": False},
                                             "telegram": {"enabled": True, "proseOnly": False}})
            self.assertIn("thresholdDb=-45", logs.output[0])
            self.assertEqual(s.file_settings(f)["maxRecordingSeconds"], 600.0)


    def test_version_6_becomes_11_with_adapter_defaults_in_each_adapter(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            v6 = {"version": 6, "adapters": {"claude": {"enabled": True, "chatTermsTokenBudget": 50},
                                             "telegram": {"enabled": True}},
                  "adapterDefaults": {"chatTermsTokenBudget": 150, "proseOnly": False}, "model": "m"}
            with open(f, "w", encoding="utf-8") as fh:
                json.dump(v6, fh)
            s.migrate(f)
            c = json.loads(pathlib.Path(f).read_text(encoding="utf-8"))
            self.assertEqual(list(c), ["version", "adapters", "model"])
            self.assertEqual(c["version"], 11)
            self.assertEqual(c["adapters"], {"claude-code": {"enabled": True, "chatTermsTokenBudget": 50, "proseOnly": False},
                                             "telegram": {"enabled": True, "chatTermsTokenBudget": 150, "proseOnly": False}})

    def test_version_10_becomes_11_without_a_models_launchd_agent(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "config.json")
            pathlib.Path(f).write_text(json.dumps({
                "version": 10, "model": "gemma-e4b",
                "models": {"gemma-e4b": {"catalog": "gemma-4-e4b", "llamaServer": "http://127.0.0.1:8092",
                                         "launchd": "echofox.llama-server", "variant": "q4_0"}}}))
            s.migrate(f)
            c = json.loads(pathlib.Path(f).read_text())
            self.assertEqual((c["version"], c["models"]),
                             (11, {"gemma-e4b": {"catalog": "gemma-4-e4b", "llamaServer": "http://127.0.0.1:8092",
                                                 "variant": "q4_0"}}))

    def test_version_9_becomes_10_without_the_copies_of_version_9s_defaults(self):
        old = {"version": 9, "models": {"gemma-e4b": {"prompt": s.V9_PROMPT, "variant": "q8_0"},
                                        "mine": {"prompt": "Say it."}},
               "languages": {"ru": {"notes": list(s.V9_RU_NOTES)}, "de": {"notes": ["Mine."]}}}
        c, what = s.from_9(old, None)
        self.assertEqual(c, {"version": 10, "models": {"gemma-e4b": {"variant": "q8_0"}, "mine": {"prompt": "Say it."}},
                             "languages": {"de": {"notes": ["Mine."]}}})  # a copy goes, a changed one stays
        self.assertIn("models.gemma-e4b.prompt, languages.ru.notes", what)
        kept = {"version": 9, "languages": {"ru": {"notes": ["Mine."], "fillers": ["э"]}}}
        self.assertEqual(s.from_9(kept, None)[0]["languages"], {"ru": {"notes": ["Mine."], "fillers": ["э"]}})
        self.assertNotIn("languages", s.from_9({"version": 9, "languages": {"ru": {"notes": list(s.V9_RU_NOTES)}}},
                                               None)[0])  # nothing left of it

    def test_the_notes_of_every_language_are_only_notes(self):
        problems = []
        keep = {"*": {"notes": ["The speech is {LANGUAGE}."]}, "ru": {"fillers": ["э"]}}
        self.assertEqual(s.clean_languages(keep, lambda *p: problems.append(p)), keep)
        self.assertEqual(s.clean_languages({"*": {"fillers": ["э"]}}, lambda *p: problems.append(p)), {"*": {}})
        self.assertEqual(problems, [("languages.*.fillers is not known to this version", False)])

    def test_version_8_becomes_9_with_the_time_limit_in_seconds(self):
        c, _ = s.from_8({"version": 8, "server": {"port": 8090, "maxRecordingMinutes": 2.5}}, None)
        self.assertEqual(c, {"version": 9, "server": {"port": 8090, "maxRecordingSeconds": 150}})
        self.assertEqual(s.from_8({"version": 8}, None)[0], {"version": 9})

    def test_version_7_becomes_8_with_claude_renamed_claude_code_in_its_place(self):
        c, what = s.from_7({"version": 7, "adapters": {"claude": {"enabled": True, "chatHistoryTokenBudget": 300},
                                                      "telegram": {"enabled": False}}}, None)
        self.assertEqual((c["version"], c["adapters"]),
                         (8, {"claude-code": {"enabled": True, "chatHistoryTokenBudget": 300},
                              "telegram": {"enabled": False}}))
        self.assertEqual(list(c["adapters"]), ["claude-code", "telegram"])
        self.assertEqual(what, "adapters.claude became claude-code")
        self.assertEqual(s.from_7({"version": 7}, None)[0], {"version": 8})  # no adapters: nothing to rename

    def test_version_5_becomes_11_without_the_constants_and_with_seconds(self):
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
            c = json.loads(pathlib.Path(f).read_text(encoding="utf-8"))
            self.assertEqual(c["version"], 11)
            self.assertEqual(c["server"], {"port": 8090, "maxRecordingSeconds": 1800})
            self.assertEqual(c["models"]["m"]["options"], {"temperature": 1})
            self.assertNotIn("options", c["models"]["n"])
            self.assertEqual(s.file_settings(f)["maxRecordingSeconds"], 1800.0)


class SchemaTest(unittest.TestCase):
    def test_the_constants_are_not_settings_and_the_tuning_ones_are_advanced(self):
        st = s.recording_settings(s.resolve({}))
        info = {e["key"]: e for e in s.schema(st, {"catalog": "gemma-4-e4b"})}
        for constant in ("pieceSeconds", "minSpeechSeconds", "warmText", "maxTokensPerPiece"):
            self.assertNotIn(constant, info)
        self.assertNotIn("advanced", info["maxRecordingSeconds"])
        for key in ("temperature", "topK", "topP", "seed", "chatHistoryTokenBudget", "chatTermsTokenBudget",
                    "proseOnly"):
            self.assertTrue(info[key]["advanced"], key)
        with self.assertRaisesRegex(ValueError, "unknown server key pieceSeconds"):
            tuning.parse({"pieceSeconds": 12}, "server", "server")  # not the user's to set
        self.assertEqual(tuning.parse({"pieceSeconds": 12}), {"piece_seconds": 12.0})  # an experiment's

    def test_the_models_folder_in_force_is_the_registrys(self):
        st = s.recording_settings(s.resolve({}))
        folder = {e["key"]: e for e in s.schema(st)}["modelsFolder"]
        self.assertEqual((folder["default"], "value" in folder), (constants.MODELS_FOLDER, False))
        folder = {e["key"]: e for e in s.schema(st, models_folder="/elsewhere")}["modelsFolder"]
        self.assertEqual(folder["value"], "/elsewhere")
        self.assertFalse(hasattr(st, "models_folder"))  # one copy of it: the registry's


if __name__ == "__main__":
    unittest.main()
