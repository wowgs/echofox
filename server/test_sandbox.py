"""Tests of the tests' sandbox: every test module imports it first, and it keeps the tests off the working setup.
Run: server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import glob
import os
import re
import socket
import unittest

import metrics
import constants as places
import settings


class SandboxTest(unittest.TestCase):
    def test_every_test_module_imports_the_sandbox_first(self):
        for f in sorted(glob.glob(os.path.join(os.path.dirname(__file__), "test_*.py"))) + ["fakes.py"]:
            code = re.sub(r'^\s*"""[\s\S]*?"""\n', "", open(os.path.join(os.path.dirname(__file__), f) if f == "fakes.py" else f).read())
            first = next(l for l in code.splitlines() if l.startswith(("import ", "from ")))
            self.assertTrue(first.startswith("import sandbox"), f"{f}: the first import is {first!r}")

    def test_the_paths_are_the_sandboxs(self):
        for path in (os.path.expanduser("~"), settings.config_file(), metrics.path(),
                     os.environ["ECHOFOX_PLUGINS"], os.environ["ECHOFOX_PROJECTS"]):
            self.assertTrue(os.path.realpath(path).startswith(sandbox.ROOT), path)
        self.assertNotEqual(sandbox.ROOT, sandbox.REAL_HOME)

    def test_the_real_servers_ports_are_refused(self):
        for port in (places.WORKING_PORT, places.WORKING_LLAMA_PORT, places.TEST_PORT, places.TEST_LLAMA_PORT):
            with self.assertRaises(ConnectionRefusedError), socket.socket() as s:
                s.connect((places.HOST, port))

    def test_launchctl_is_a_fake(self):
        import llama
        self.assertEqual(llama.LAUNCHCTL, os.environ["ECHOFOX_LAUNCHCTL"])
        self.assertFalse(llama.agent_running("echofox.anything"))


if __name__ == "__main__":
    unittest.main()
