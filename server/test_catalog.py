"""Tests of catalog.py and catalog.json: the variants, their files and sources, a model's defaults. Run:
server/.venv/bin/python -m unittest discover -s server"""
import sandbox  # noqa: F401  (before any other import: see sandbox.py)
import unittest

import catalog


class CatalogTest(unittest.TestCase):
    def test_a_registry_entry_has_its_catalogs_default_variant_unless_it_names_one(self):
        self.assertEqual(catalog.variant({"catalog": "gemma-4-e4b"})[0], "q4_0")
        vid, spec = catalog.variant({"catalog": "gemma-4-e4b", "variant": "q8_0"})
        self.assertEqual((vid, spec["files"]["model"]["file"]), ("q8_0", "gemma-4-E4B-it-Q8_0.gguf"))

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
            self.assertIsNotNone(catalog.model_defaults({"catalog": name}).get("max_tokens_per_piece"), name)


if __name__ == "__main__":
    unittest.main()
