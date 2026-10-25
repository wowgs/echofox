"""The protocol's contract with the menu bar app: the examples in shared/protocol-examples.json, which the app's
checks (macos lv-tests) read too. Run: server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import json
import os
import unittest

import constants
import protocol
from fakes import args, stub_models

EXAMPLES = json.load(open(os.path.join(os.path.dirname(__file__), "..", "shared", "protocol-examples.json"),
                          encoding="utf-8"))


class ContractTest(unittest.TestCase):
    def test_the_servers_info_has_the_examples_fields_and_values(self):
        info = protocol.info(args())
        example = EXAMPLES["info"]
        self.assertEqual(set(info), set(example))
        for k in ("type", "interface", "sampleRate", "encoding", "textWaitSeconds", "languages"):
            self.assertEqual(info[k], example[k], k)
        self.assertEqual(set(info["adapters"][0]), set(example["adapters"][0]))
        fields = {"key", "owner", "group", "kind", "title", "advanced", "default", "value", "min", "max",
                  "minExclusive", "maxExclusive", "help"}
        for entry in info["settings"] + example["settings"]:  # a setting's description, as the settings window reads it
            self.assertLessEqual({"key", "owner", "group", "kind", "title", "default", "help"}, set(entry), entry)
            self.assertIn(entry["owner"], ("server", "model", "adapter"), entry)
            self.assertLessEqual(set(entry), fields, entry)
            self.assertIn(entry["kind"], ("number", "integer", "boolean", "string"), entry)
        self.assertEqual((protocol.INTERFACE, constants.RATE, constants.TEXT_WAIT_S),
                         (example["interface"], example["sampleRate"], example["textWaitSeconds"]))

    def test_the_apps_start_message_is_one_the_server_takes(self):
        start = protocol.parse_start(EXAMPLES["start"], stub_models({"gemma-e4b": {"llamaServer": "http://h:1"}}))
        self.assertEqual((start.model, start.language, start.client), ("gemma-e4b", "ru", "local-voice-mac"))
        self.assertEqual(EXAMPLES["stop"]["reason"], "user")
        self.assertIn(EXAMPLES["stop"]["reason"], protocol.STOP_REASONS)

    def test_the_server_sends_only_the_kinds_of_messages_of_the_examples(self):
        kinds = {m["type"] for m in EXAMPLES["server"]}
        source = open(protocol.__file__, encoding="utf-8").read()
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
