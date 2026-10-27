"""Tests of downloads.py and of the download and remove messages: a local HTTP server stands for Hugging Face. Run:
server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import hashlib
import http.server
import json
import os
import pathlib
import tempfile
import threading
import unittest

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

import catalog
import constants
import downloads
import llama
import protocol
import variants
from fakes import FakeLlama, StubModel, args, stub_models

MODEL, MMPROJ = os.urandom(300_000), os.urandom(100_000)


def spec(data, name, sha=None):
    return {"file": name, "bytes": len(data), "sha256": sha or hashlib.sha256(data).hexdigest()}


class Source(http.server.BaseHTTPRequestHandler):
    """The files of the test catalog, with HTTP Range as Hugging Face's CDN answers it."""
    files = {"m.gguf": MODEL, "mm.gguf": MMPROJ, "big.gguf": MODEL, "bad.gguf": MODEL}
    ranges = []

    def do_GET(self):
        data = self.files[self.path.lstrip("/")]
        start = 0
        if self.headers.get("Range"):
            start = int(self.headers["Range"].split("=")[1].split("-")[0])
            Source.ranges.append(start)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(len(data) - start))
        self.end_headers()
        self.wfile.write(data[start:])

    def log_message(self, *a):
        pass


class DownloadTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.http = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Source)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        port = self.http.server_address[1]
        self.folder = tempfile.mkdtemp(prefix="models-", dir=sandbox.ROOT)
        self.catalog = {"tiny": {"name": "Tiny", "source": {"repo": "x/tiny-GGUF", "revision": "r1"},
                                 "defaultVariant": "a", "llamaServer": {"args": []},
                                 "variants": {"a": {"name": "A", "files": {"model": spec(MODEL, "m.gguf"),
                                                                           "mmproj": spec(MMPROJ, "mm.gguf")}},
                                              "b": {"name": "B", "files": {"model": spec(MODEL, "big.gguf"),
                                                                           "mmproj": spec(MMPROJ, "mm.gguf")}},
                                              "bad": {"name": "Bad", "files": {"model": spec(MODEL, "bad.gguf", "0" * 64),
                                                                               "mmproj": spec(MMPROJ, "mm.gguf")}}}}}
        self.saved = catalog.entries, catalog.url
        catalog.entries = lambda: self.catalog
        catalog.url = lambda entry, name: f"http://127.0.0.1:{port}/{name}"
        Source.ranges = []

    def tearDown(self):
        catalog.entries, catalog.url = self.saved
        self.http.shutdown()
        self.http.server_close()

    def path(self, name):
        return os.path.join(self.folder, "tiny-GGUF", name)

    def run_job(self, variant):
        job = downloads.start("tiny", variant, self.folder)
        self.assertTrue(job.finished.wait(10))
        return job

    def test_the_files_of_a_variant_come_whole_and_checked(self):
        job = self.run_job("a")
        self.assertIsNone(job.error)
        self.assertEqual(job.done, job.total)
        self.assertEqual(tuple(pathlib.Path(self.path(n)).read_bytes() for n in ("m.gguf", "mm.gguf")),
                         (MODEL, MMPROJ))
        self.assertFalse(os.path.exists(self.path("m.gguf.part")))

    def test_a_part_is_continued_from_where_it_stopped(self):
        os.makedirs(os.path.dirname(self.path("m.gguf")))
        with open(self.path("m.gguf.part"), "wb") as f:
            f.write(MODEL[:120_000])
        job = self.run_job("a")
        self.assertIsNone(job.error)
        self.assertIn(120_000, Source.ranges)
        self.assertEqual(pathlib.Path(self.path("m.gguf")).read_bytes(), MODEL)

    def test_a_wrong_sha256_deletes_the_part_and_stops(self):
        job = self.run_job("bad")
        self.assertIn("SHA-256", job.error)
        self.assertFalse(os.path.exists(self.path("bad.gguf")) or os.path.exists(self.path("bad.gguf.part")))

    def test_a_download_too_big_for_the_disk_is_refused(self):
        saved, downloads.FREE_MARGIN = downloads.FREE_MARGIN, 10 ** 18
        try:
            job = self.run_job("a")
        finally:
            downloads.FREE_MARGIN = saved
        self.assertIn("not enough free disk", job.error)

    def test_remove_keeps_the_files_another_downloaded_variant_uses(self):
        self.run_job("a")
        self.run_job("b")
        with self.assertRaisesRegex(ValueError, "in force"):
            downloads.remove("tiny", "a", self.folder, in_force="a")
        self.assertEqual(downloads.remove("tiny", "a", self.folder), len(MODEL))  # mm.gguf stays for b
        self.assertTrue(os.path.exists(self.path("mm.gguf")) and os.path.exists(self.path("big.gguf")))
        self.assertFalse(os.path.exists(self.path("m.gguf")))

    async def test_the_variant_in_use_is_removed_after_its_model_leaves_memory(self):
        self.run_job("a")
        url = "http://127.0.0.1:1"
        models = llama.Models({"m": {"catalog": "tiny", "variant": "a", "llamaServer": url}},
                              make=StubModel, models_folder=self.folder)
        models.selected = "m"
        sent = []
        async def send(**m): sent.append(m)
        with FakeLlama() as llamas:
            await models.get("m")
            await variants.remove(None, send, {"catalog": "tiny", "variant": "a"}, models, args(models_folder=self.folder))
        self.assertEqual(sent[0]["type"], "removed")
        self.assertEqual((llamas.calls, models.active), ([("start", url), ("stop", url)], None))
        self.assertFalse(os.path.exists(self.path("m.gguf")))

    async def test_the_download_message_sends_progress_then_downloaded(self):
        a = args(models_folder=self.folder)
        async with serve(lambda ws: protocol.handle(ws, stub_models(), a), "127.0.0.1", 0) as server:
            async with connect(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}") as ws:
                await ws.send(json.dumps({"type": "download", "catalog": "tiny", "variant": "a"}))
                got = [json.loads(m) async for m in ws]
        self.assertEqual(got[-1], {"type": "downloaded"})
        self.assertEqual(got[-2], {"type": "progress", "bytes": len(MODEL) + len(MMPROJ),
                                   "total": len(MODEL) + len(MMPROJ)})
        v = variants.variants({"catalog": "tiny"}, self.folder)["variants"]
        self.assertEqual([(x["id"], x["downloaded"]) for x in v], [("a", True), ("b", False), ("bad", False)])


if __name__ == "__main__":
    unittest.main()
