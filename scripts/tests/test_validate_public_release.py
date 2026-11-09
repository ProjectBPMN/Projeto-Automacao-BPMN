from __future__ import annotations

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import validate_public_release as release_guard


def minimal_manifest(*allowed: str) -> dict:
    return {
        "schema_version": 1,
        "policy_id": "unit-test",
        "allowed_paths": {"exact": list(allowed), "globs": []},
        "required_files": [],
        "canonical_n8n_workflows": [],
        "forbidden_paths": [
            "docs/**",
            "avaliacao/datasets/**",
            "avaliacao/resultados/**",
            "n8n/credentials/**",
        ],
        "forbidden_extensions": [".zip", ".sqlite", ".sql", ".db"],
        "forbidden_basenames": [".env", ".env.local", "credentials.json"],
        "max_file_bytes": 1024 * 1024,
        "n8n_policy": {
            "reject_nonempty_pin_data": True,
            "reject_static_data": True,
            "allow_symbolic_credential_references_only_in_canonical_v9": True,
            "symbolic_credential_id_pattern": "^[A-Z][A-Z0-9_]{2,63}$",
        },
    }


class PublicReleaseGuardTests(unittest.TestCase):
    def validate_one(self, path: str, content: str | bytes, manifest: dict) -> list:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                target.write_bytes(content)
            else:
                target.write_text(content, encoding="utf-8")
            return release_guard.validate_release(
                root,
                [path],
                manifest,
                require_required=False,
            )

    def test_repository_manifest_is_well_formed(self) -> None:
        manifest = release_guard.load_manifest()
        self.assertEqual(release_guard.validate_manifest_policy(manifest), [])

    def test_clean_allowlisted_text_passes(self) -> None:
        manifest = minimal_manifest("README.md")
        self.assertEqual(self.validate_one("README.md", "Projeto publico\n", manifest), [])

    def test_path_outside_allowlist_is_rejected(self) -> None:
        manifest = minimal_manifest("README.md")
        issues = self.validate_one("unexpected.txt", "x\n", manifest)
        self.assertIn("PATH_NOT_ALLOWED", {issue.code for issue in issues})

    def test_internal_paths_are_rejected_even_if_added_to_allowlist(self) -> None:
        for path in (
            "docs/relatorio.md",
            "avaliacao/datasets/corpus.json",
            "avaliacao/resultados/metricas.json",
            "n8n/credentials/export.json",
        ):
            with self.subTest(path=path):
                manifest = minimal_manifest(path)
                issues = self.validate_one(path, "{}\n", manifest)
                self.assertIn("MANIFEST_ALLOW_FORBIDDEN", {issue.code for issue in issues})
                self.assertIn("PATH_FORBIDDEN", {issue.code for issue in issues})

    def test_sensitive_file_types_are_rejected(self) -> None:
        for path in (".env", "bundle.zip", "state.sqlite", "schema.sql", "cache.db"):
            with self.subTest(path=path):
                manifest = minimal_manifest(path)
                issues = self.validate_one(path, b"not-a-real-artifact", manifest)
                self.assertIn("PATH_FORBIDDEN", {issue.code for issue in issues})

    def test_secret_shape_is_reported_without_echoing_value(self) -> None:
        path = "config.txt"
        manifest = minimal_manifest(path)
        secret = "AI" + "za" + ("Q" * 35)
        issues = self.validate_one(path, f"API_KEY={secret}\n", manifest)
        self.assertIn("SECRET_GOOGLE_API_KEY", {issue.code for issue in issues})
        self.assertNotIn(secret, "\n".join(issue.render() for issue in issues))

    def test_literal_sensitive_header_is_rejected(self) -> None:
        path = "workflow.json"
        manifest = minimal_manifest(path)
        token = "Z" * 40
        document = {
            "nodes": [
                {
                    "name": "HTTP",
                    "parameters": {
                        "headerParameters": {
                            "parameters": [{"name": "App-Token", "value": token}]
                        }
                    },
                }
            ],
            "connections": {},
        }
        issues = self.validate_one(path, json.dumps(document), manifest)
        self.assertIn("SECRET_HEADER_LITERAL", {issue.code for issue in issues})
        self.assertNotIn(token, "\n".join(issue.render() for issue in issues))

    def test_empty_pin_data_and_symbolic_references_are_allowed_for_canonical_v9(self) -> None:
        path = "n8n/workflows/Versão9/V9-WF01.json"
        manifest = minimal_manifest(path)
        manifest["required_files"] = [path]
        manifest["canonical_n8n_workflows"] = [path]
        workflow = {
            "name": "WF01",
            "nodes": [
                {
                    "name": "Postgres",
                    "credentials": {
                        "postgres": {"id": "PG_TRIAGEM", "name": "Postgres Triagem"}
                    },
                }
            ],
            "connections": {},
            "pinData": {},
        }
        issues = self.validate_one(path, json.dumps(workflow), manifest)
        self.assertEqual(issues, [])

    def test_runtime_state_and_non_symbolic_credentials_are_rejected(self) -> None:
        path = "n8n/workflows/Versão9/V9-WF01.json"
        manifest = minimal_manifest(path)
        manifest["required_files"] = [path]
        manifest["canonical_n8n_workflows"] = [path]
        workflow = {
            "name": "WF01",
            "nodes": [
                {
                    "name": "Postgres",
                    "credentials": {
                        "postgres": {"id": "real-instance-id-123", "name": "Private DB"}
                    },
                }
            ],
            "connections": {},
            "pinData": {"Postgres": [{"json": {"ticket": 123}}]},
            "staticData": {"lastExecution": 123},
        }
        issues = self.validate_one(path, json.dumps(workflow), manifest)
        codes = {issue.code for issue in issues}
        self.assertIn("N8N_PIN_DATA", codes)
        self.assertIn("N8N_STATIC_DATA", codes)
        self.assertIn("N8N_CREDENTIAL_ID", codes)

    def test_credential_reference_is_rejected_outside_canonical_v9(self) -> None:
        path = "workflow.json"
        manifest = minimal_manifest(path)
        workflow = {
            "name": "Export",
            "nodes": [
                {
                    "name": "SMTP",
                    "credentials": {
                        "smtp": {"id": "SMTP_PUBLIC", "name": "SMTP Placeholder"}
                    },
                }
            ],
            "connections": {},
        }
        issues = self.validate_one(path, json.dumps(workflow), manifest)
        self.assertIn("N8N_CREDENTIAL_REFERENCE", {issue.code for issue in issues})


if __name__ == "__main__":
    unittest.main()
