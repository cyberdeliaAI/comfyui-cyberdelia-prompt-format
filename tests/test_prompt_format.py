from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
folder_paths = types.ModuleType("folder_paths")
folder_paths.get_folder_paths = lambda _kind: []
sys.modules.setdefault("folder_paths", folder_paths)

spec = importlib.util.spec_from_file_location("prompt_format", ROOT / "prompt_format.py")
prompt_format = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = prompt_format
spec.loader.exec_module(prompt_format)


class PromptFormatTests(unittest.TestCase):
    def test_pipeline_removes_networks_normalizes_and_deduplicates(self):
        protected = prompt_format.ProtectedNames(exact=[], wildcard_patterns=[])
        result = prompt_format.PromptFormatter.format_pipeline(
            "blue_hair, blue_hair, <lora:example:1.0>",
            dedupe=True,
            rm_underscore=True,
            append_comma=False,
            protected=protected,
            aliases=[],
        )
        self.assertEqual(result, "blue hair")

    def test_protected_embedding_keeps_underscores(self):
        protected = prompt_format.ProtectedNames(exact=["my_embedding"], wildcard_patterns=[])
        result = prompt_format.PromptFormatter.format_pipeline(
            "my_embedding, blue_hair",
            dedupe=False,
            rm_underscore=True,
            append_comma=False,
            protected=protected,
            aliases=[],
        )
        self.assertEqual(result, "my_embedding, blue hair")


if __name__ == "__main__":
    unittest.main()
