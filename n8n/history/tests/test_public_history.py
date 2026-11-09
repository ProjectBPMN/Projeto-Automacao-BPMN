from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
PROJECT_ROOT = HERE.parents[1]


def load_validator():
    path = HERE / "validate_history.py"
    spec = importlib.util.spec_from_file_location("validate_history", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class PublicHistoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.validator = load_validator()
        cls.manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))

    def test_manifest_and_hashes(self) -> None:
        failures, manifest = self.validator.validate_manifest()
        self.assertEqual([], failures)
        self.assertIsNotNone(manifest)

    def test_all_workflows_are_safe_and_inactive(self) -> None:
        files = sorted((HERE / "workflows").glob("*.json"))
        self.assertEqual(10, len(files))
        for path in files:
            with self.subTest(path=path.name):
                self.assertEqual([], self.validator.validate_workflow(path))

    def test_versions_v1_through_v8_are_covered(self) -> None:
        versions = {entry["version"] for entry in self.manifest["artifacts"]}
        self.assertEqual({f"V{number}" for number in range(1, 9)}, versions)

    def test_v6_and_v7_canonical_selection_is_explicit(self) -> None:
        by_version = {
            entry["version"]: entry for entry in self.manifest["artifacts"]
            if entry["version"] in {"V6", "V7"}
        }
        self.assertEqual(
            "AutoFinal20260422A",
            by_version["V6"]["source"]["selector_id"],
        )
        self.assertEqual(66, by_version["V7"]["node_count"])
        v7_variant_counts = {
            entry["node_count"] for entry in self.manifest["variants"]
            if entry["version"] == "V7"
        }
        self.assertTrue({63, 65}.issubset(v7_variant_counts))

    def test_private_sources_are_preserved_and_match_manifest(self) -> None:
        self.assertEqual([], self.validator.validate_sources(self.manifest))

    def test_archive_has_no_binary_or_unexpected_files(self) -> None:
        self.assertEqual([], self.validator.validate_filesystem())

    def test_rebuild_is_deterministic(self) -> None:
        process = subprocess.run(
            [sys.executable, str(HERE / "build_history.py"), "--check"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, process.returncode, process.stdout + process.stderr)

    def test_validator_rejects_runtime_data_and_literal_secret(self) -> None:
        unsafe = {
            "active": False,
            "connections": {},
            "name": "unsafe fixture",
            "nodes": [{
                "name": "request",
                "parameters": {
                    "headerParameters": {
                        "parameters": [{
                            "name": "Authorization",
                            "value": "Bearer this-must-never-be-public",
                        }]
                    }
                },
                "pinData": {"sample": "runtime"},
                "type": "n8n-nodes-base.httpRequest",
            }],
            "settings": {},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.json"
            path.write_text(json.dumps(unsafe), encoding="utf-8")
            failures = self.validator.validate_workflow(path)
        joined = "\n".join(failures)
        self.assertIn("literal authorization", joined)
        self.assertIn("forbidden field", joined)


if __name__ == "__main__":
    unittest.main()
