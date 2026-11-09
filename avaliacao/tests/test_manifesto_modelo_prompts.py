from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "avaliacao" / "scripts" / "sincronizar_manifesto.py"
SPEC = importlib.util.spec_from_file_location("sincronizar_manifesto", SCRIPT)
sync = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(sync)


class ManifestoModeloPromptsTests(unittest.TestCase):
    def test_frozen_manifest_matches_current_generated_gateways(self) -> None:
        files, expected, contract_errors = sync.expected_artifacts()
        self.assertEqual(contract_errors, [])
        for path, content in files.items():
            self.assertTrue(path.exists(), path)
            self.assertEqual(path.read_text(encoding="utf-8"), content)
        actual = json.loads(sync.MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
