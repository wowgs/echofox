"""The protocol's contract with the menu bar app: the examples in shared/protocol-examples.json, which the app's
checks (macos echofox-tests) read too. Run: server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import json
import os
import pathlib
import unittest

import constants
import info
import settings
import tuning
import session
import variants
from fakes import args, stub_models

SHARED = os.path.join(os.path.dirname(__file__), "..", "shared")
EXAMPLES = json.loads(pathlib.Path(SHARED, "protocol-examples.json").read_text(encoding="utf-8"))
CONSTANTS = json.loads(pathlib.Path(SHARED, "constants.json").read_text(encoding="utf-8"))


class ContractTest(unittest.TestCase):
    def test_the_servers_info_has_the_examples_fields_and_values(self):
        got = info.info(args())
        example = EXAMPLES["info"]
        self.assertEqual(set(got), set(example))
        for k in ("type", "interface", "sampleRate", "encoding", "textWaitSeconds", "languages", "commonNotes"):
            self.assertEqual(got[k], example[k], k)
        self.assertEqual(set(got["adapters"][0]), set(example["adapters"][0]))
        fields = {"key", "owner", "group", "kind", "title", "advanced", "default", "value", "min", "max",
                  "minExclusive", "maxExclusive", "unit", "help"}
        for entry in got["settings"] + example["settings"]:  # a setting's description, as the settings window reads it
            self.assertLessEqual({"key", "owner", "group", "kind", "title", "default", "help"}, set(entry), entry)
            self.assertIn(entry["owner"], ("server", "model", "adapter"), entry)
            self.assertLessEqual(set(entry), fields, entry)
            self.assertIn(entry["kind"], ("number", "integer", "boolean", "string", "folder"), entry)
        self.assertEqual((constants.PROTOCOL_INTERFACE, constants.RATE, constants.TEXT_WAIT_S),
                         (example["interface"], example["sampleRate"], example["textWaitSeconds"]))

    def test_the_config_schema_has_the_servers_settings_with_their_types(self):
        schema = json.loads(pathlib.Path(SHARED, "config.schema.json").read_text(encoding="utf-8"))
        json_type = {str: "string", int: "integer", float: "number", bool: "boolean", dict: "object"}
        top, server = schema["properties"], schema["properties"]["server"]["properties"]
        for st in settings.SETTINGS:
            place = server if st.section == "server" else top
            self.assertIn(st.key, place, st.key)
            self.assertEqual(place[st.key]["type"], json_type[st.kind], st.key)
        entries = {"model": top["models"]["additionalProperties"]["properties"]["options"]["properties"],
                   "adapter": top["adapters"]["additionalProperties"]["properties"]}
        for knob in tuning.KNOBS:
            if knob.user and knob.owner in entries:
                self.assertEqual(entries[knob.owner][knob.key]["type"], json_type[knob.kind], knob.key)
        self.assertEqual(top["version"]["type"], "integer")
        self.assertIn(str(constants.CONFIG_VERSION), top["version"]["description"])

    def test_the_shared_values_are_the_servers(self):
        c = constants
        mine = {"interface": c.PROTOCOL_INTERFACE, "configVersion": c.CONFIG_VERSION, "config": c.CONFIG, "host": c.HOST,
                "workingPort": c.WORKING_PORT, "sampleRate": c.RATE, "encoding": c.ENCODING,
                "serverLog": c.SERVER_LOG, "configCheckSeconds": c.CONFIG_CHECK_S,
                "recordings": c.RECORDINGS, "labeled": c.LABELED}
        self.assertEqual(mine, {k: v for k, v in CONSTANTS.items() if k != "about"})

    def test_the_apps_start_message_is_one_the_server_takes(self):
        start = session.parse_start(EXAMPLES["start"], stub_models({"gemma-e4b": {"llamaServer": "http://h:1"}}))
        self.assertEqual((start.model, start.language, start.client), ("gemma-e4b", "ru", "echofox-mac"))
        self.assertEqual(EXAMPLES["stop"]["reason"], "user")
        self.assertIn(EXAMPLES["stop"]["reason"], session.STOP_REASONS)

    def test_the_server_sends_only_the_kinds_of_messages_of_the_examples(self):
        kinds = {m["type"] for m in EXAMPLES["server"]}
        source = "".join(pathlib.Path(m.__file__).read_text(encoding="utf-8") for m in (session, info, variants))
        for kind in ("speech", "text", "error", "stopped", "done", "info"):
            self.assertIn(f'type="{kind}"' if kind != "info" else '"type": "info"', source)
        self.assertEqual(kinds, {"speech", "text", "error", "stopped", "done"})
        models = {m["type"] for m in EXAMPLES["models"]}  # the answers to download and remove
        for kind in ("progress", "downloaded", "removed"):
            self.assertIn(f'type="{kind}"', source)
        self.assertEqual(models, {"progress", "downloaded", "removed", "error"})
        self.assertEqual({EXAMPLES[k]["type"] for k in ("download", "remove", "cancel")}, {"download", "remove", "cancel"})


if __name__ == "__main__":
    unittest.main()
