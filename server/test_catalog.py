"""Tests of catalog.py and catalog.json: the variants, their files and sources, a model's defaults. Run:
server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import os
import tempfile
import unittest

import catalog
import resolve


class CatalogTest(unittest.TestCase):
    def test_a_registry_entry_has_its_catalogs_default_variant_unless_it_names_one(self):
        self.assertEqual(catalog.variant({"catalog": "gemma-4-e4b"})[0], "q4_0")
        vid, spec = catalog.variant({"catalog": "gemma-4-e4b", "variant": "q8_0"})
        self.assertEqual((vid, spec["files"]["model"]["file"]), ("q8_0", "gemma-4-E4B-it-Q8_0.gguf"))

    def test_the_variant_in_force_is_one_whose_files_are_there(self):
        with tempfile.TemporaryDirectory() as folder:
            def download(vid):
                for p in catalog.files({"variant": vid}, folder).values():
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    open(p, "w").close()

            def in_force(entry):
                return catalog.in_force({"catalog": "gemma-4-e4b", **entry}, folder)["variant"]

            self.assertEqual((in_force({}), in_force({"variant": "q8_0"})), ("q4_0", "q8_0"))  # none: it waits for it
            download("q8_0")  # an install from before Q4_0 became the default: the new default is not downloaded
            self.assertEqual((in_force({}), in_force({"variant": "q4_0"})), ("q8_0", "q8_0"))
            download("q4_0")
            self.assertEqual((in_force({}), in_force({"variant": "q8_0"})), ("q4_0", "q8_0"))  # the choice, then the default
            for p in catalog.files({"variant": "q8_0"}, folder).values():
                os.remove(p)  # the chosen variant removed: the other one runs, not nothing
            self.assertEqual(in_force({"variant": "q8_0"}), "q4_0")

    def test_a_variants_own_source_else_the_entrys(self):
        # Google's QAT for Q4_0, ggml-org's for Q8_0
        self.assertEqual(catalog.files({"variant": "q4_0"}, "/m"),
                         {"model": "/m/gemma-4-E4B-it-qat-q4_0-gguf/gemma-4-E4B_q4_0-it.gguf",
                          "mmproj": "/m/gemma-4-E4B-it-qat-q4_0-gguf/gemma-4-E4B-it-mmproj.gguf"})
        self.assertEqual(catalog.url({}, "gemma-4-E4B_q4_0-it.gguf"),
                         "https://huggingface.co/google/gemma-4-E4B-it-qat-q4_0-gguf/resolve/"
                         "4b4a2c1d584be7264f87aac328a1bc739ce81b6c/gemma-4-E4B_q4_0-it.gguf")
        self.assertEqual(catalog.url({"variant": "q8_0"}, "gemma-4-E4B-it-Q8_0.gguf"),
                         "https://huggingface.co/ggml-org/gemma-4-E4B-it-GGUF/resolve/"
                         "a69f018d7678a2b9f5e705f8903d6fb29b9b25dc/gemma-4-E4B-it-Q8_0.gguf")

    def test_every_catalog_entry_gives_the_models_constants(self):
        for name in catalog.entries():
            self.assertIsNotNone(resolve.model_defaults({"catalog": name}).get("max_tokens_per_piece"), name)


if __name__ == "__main__":
    unittest.main()
