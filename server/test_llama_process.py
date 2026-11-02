"""Tests of llama_process.py: where llama-server is, its command, its end, the wait until it answers. Run:
server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import catalog
import constants
import llama_process
from fakes import real_wait_healthy


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="models-", dir=sandbox.ROOT)
        self.binary = os.path.join(self.folder, "llama-server")
        open(self.binary, "w").close()
        os.chmod(self.binary, 0o755)
        self.saved = constants.LLAMA_SERVER, llama_process.BUNDLED_LLAMA_SERVER
        constants.LLAMA_SERVER, llama_process.BUNDLED_LLAMA_SERVER = self.binary, os.path.join(self.folder, "none")

    def tearDown(self):
        constants.LLAMA_SERVER, llama_process.BUNDLED_LLAMA_SERVER = self.saved

    def put(self, *names, repo="gemma-4-E4B-it-GGUF"):
        d = os.path.join(self.folder, repo)
        os.makedirs(d, exist_ok=True)
        for n in names:
            open(os.path.join(d, n), "w").close()

    def test_the_bundles_llama_server_comes_first(self):
        self.assertEqual(llama_process.llama_server(), self.binary)  # no bundled one: the installed app's
        bundled = os.path.join(self.folder, "bundled-llama-server")
        open(bundled, "w").close()
        os.chmod(bundled, 0o755)
        llama_process.BUNDLED_LLAMA_SERVER = bundled
        self.assertEqual(llama_process.llama_server(), bundled)

    def test_the_command_runs_the_variants_files(self):
        entry = {"llamaServer": "http://127.0.0.1:8092", "catalog": "gemma-4-e4b"}
        with self.assertRaisesRegex(RuntimeError, "files of variant q4_0 are missing"):
            llama_process.command(entry, self.folder)
        self.put("gemma-4-E4B-it-Q8_0.gguf", "mmproj-gemma-4-E4B-it-BF16.gguf")
        self.put("gemma-4-E4B_q4_0-it.gguf", "gemma-4-E4B-it-mmproj.gguf", repo="gemma-4-E4B-it-qat-q4_0-gguf")
        a = llama_process.command({**entry, "variant": "q8_0"}, self.folder)
        self.assertEqual(a[:9], [self.binary, "-m", f"{self.folder}/gemma-4-E4B-it-GGUF/gemma-4-E4B-it-Q8_0.gguf",
                                 "--mmproj", f"{self.folder}/gemma-4-E4B-it-GGUF/mmproj-gemma-4-E4B-it-BF16.gguf",
                                 "--host", "127.0.0.1", "--port", "8092"])
        self.assertEqual(a[9:], catalog.of(entry)["llamaServer"]["args"])
        self.assertEqual(llama_process.command(entry, self.folder)[2],
                         f"{self.folder}/gemma-4-E4B-it-qat-q4_0-gguf/gemma-4-E4B_q4_0-it.gguf")

    def test_only_a_llama_server_on_this_mac_is_started(self):
        self.assertTrue(llama_process.local({"llamaServer": "http://localhost:8092"}))
        self.assertFalse(llama_process.local({"llamaServer": "http://ubu.example:8080"}))


class ProcessTest(unittest.TestCase):
    def test_a_wait_for_a_loading_model_ends_when_the_server_ends(self):
        closing = threading.Event()
        threading.Timer(0.2, closing.set).start()
        t = time.monotonic()
        with mock.patch.object(llama_process.urllib.request, "urlopen", side_effect=OSError("not yet")):
            self.assertFalse(real_wait_healthy("http://127.0.0.1:9", 60, closing))
        self.assertLess(time.monotonic() - t, 2)

    def test_end_stops_a_child_that_ignores_sigterm(self):
        saved = llama_process.TERM_WAIT_S
        llama_process.TERM_WAIT_S = 0.5
        try:
            proc = subprocess.Popen([sys.executable, "-c", "import signal, time; "
                                     "signal.signal(signal.SIGTERM, signal.SIG_IGN); print(1, flush=True); time.sleep(60)"],
                                    stdout=subprocess.PIPE)
            proc.stdout.readline()  # it ignores SIGTERM from now on
            llama_process.end(proc)
            self.assertEqual(proc.returncode, -9)
            proc.stdout.close()
        finally:
            llama_process.TERM_WAIT_S = saved


if __name__ == "__main__":
    unittest.main()
