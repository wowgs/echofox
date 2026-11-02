"""Tests of the tests' sandbox: every test module imports it first, and it keeps the tests off the working setup.
Run: server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import glob
import os
import pathlib
import re
import socket
import unittest

import constants as places
import llama_process
import settings


class SandboxTest(unittest.TestCase):
    def test_every_test_module_imports_the_sandbox_first(self):
        for f in sorted(glob.glob(os.path.join(os.path.dirname(__file__), "test_*.py"))) + ["fakes.py"]:
            source = pathlib.Path(os.path.dirname(__file__), f).read_text(encoding="utf-8")
            code = re.sub(r'^\s*"""[\s\S]*?"""\n', "", source)
            first = next(l for l in code.splitlines() if l.startswith(("import ", "from ")))
            self.assertTrue(first.startswith("import sandbox"), f"{f}: the first import is {first!r}")

    def test_the_paths_are_the_sandboxs(self):
        for path in (os.path.expanduser("~"), settings.config_file(), places.path(places.METRICS),
                     os.environ["ECHOFOX_ADAPTERS"]):
            self.assertTrue(os.path.realpath(path).startswith(sandbox.ROOT), path)
        self.assertNotEqual(sandbox.ROOT, sandbox.REAL_HOME)

    def test_the_real_servers_ports_are_refused(self):
        for port in (places.WORKING_PORT, places.WORKING_LLAMA_PORT, places.TEST_PORT, places.TEST_LLAMA_PORT):
            with self.assertRaises(ConnectionRefusedError), socket.socket() as s:
                s.connect((places.HOST, port))

    def test_no_llama_server_starts_or_is_stopped(self):
        self.assertIs(llama_process.spawn, sandbox._spawn)
        self.assertIsInstance(llama_process.spawn(["llama-server"]), sandbox.FakeProcess)
        self.assertIsNone(llama_process.end_stale(places.WORKING_LLAMA_PORT))

    def test_no_module_imports_a_replaced_function_by_its_name(self):
        # The sandbox and fakes.py replace llama_process's and microphone's functions by attribute: a caller that
        # imported one by its name (from llama_process import spawn) would keep the real one and start a llama-server
        # or ask macOS in a test
        here = os.path.dirname(os.path.abspath(__file__))
        for f in sorted(glob.glob(os.path.join(here, "*.py")) + glob.glob(os.path.join(here, "adapters", "**", "*.py"),
                                                                           recursive=True)):
            source = pathlib.Path(f).read_text(encoding="utf-8")
            self.assertNotRegex(source, r"(?m)^\s*from (llama_process|microphone) import", f)


if __name__ == "__main__":
    unittest.main()
