import importlib.util
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "n8n" / "workflows" / "Versão9" / "deploy_rest_session.py"
SPEC = importlib.util.spec_from_file_location("deploy_rest_session", MODULE_PATH)
deploy = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(deploy)

DEPLOY_MODULE_PATH = MODULE_PATH.with_name("deploy.py")
DEPLOY_SPEC = importlib.util.spec_from_file_location("deploy_v9", DEPLOY_MODULE_PATH)
deploy_v9 = importlib.util.module_from_spec(DEPLOY_SPEC)
assert DEPLOY_SPEC and DEPLOY_SPEC.loader
DEPLOY_SPEC.loader.exec_module(deploy_v9)


class DeployWorkflowSelectionTests(unittest.TestCase):
    def test_rest_session_is_preferred_when_ui_credentials_exist(self):
        with patch.dict(
            os.environ,
            {
                "N8N_BASIC_AUTH_USER": "pesquisador@example.invalid",
                "N8N_BASIC_AUTH_PASSWORD": "senha-local",
            },
            clear=False,
        ):
            self.assertTrue(deploy_v9.rest_session_configured())

    def test_placeholder_ui_credentials_do_not_enable_rest_session(self):
        with patch.dict(
            os.environ,
            {
                "N8N_BASIC_AUTH_USER": "CHANGE_ME",
                "N8N_BASIC_AUTH_PASSWORD": "CHANGE_ME",
            },
            clear=False,
        ):
            self.assertFalse(deploy_v9.rest_session_configured())

    def test_canonical_id_wins_over_homonymous_legacy_copy(self):
        canonical = json.loads(
            (MODULE_PATH.parent / "V9-WF06-Fila-IA.json").read_text(encoding="utf-8")
        )
        workflows = [
            {"id": "legacy-copy", "name": canonical["name"], "active": False},
            {
                "id": canonical["id"],
                "name": canonical["name"],
                "active": True,
                "isArchived": True,
            },
        ]
        resolved = deploy.resolve_workflow_ids(workflows)
        self.assertEqual(resolved[canonical["name"]], canonical["id"])


if __name__ == "__main__":
    unittest.main()
