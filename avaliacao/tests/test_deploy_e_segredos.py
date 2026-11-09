from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / "n8n" / "workflows" / "Versão9"
SCRIPT_DIR = ROOT / "avaliacao" / "scripts"
for path in (WORKFLOW_DIR, SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import deploy as deploy_v9  # noqa: E402
import gerar_dataset_avaliacao as dataset_generator  # noqa: E402
import helpers as workflow_helpers  # noqa: E402
import project_env  # noqa: E402
import validate_v9_static as static_validator  # noqa: E402


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class CredentialFailureSession:
    def get(self, _url):
        return FakeResponse(500, text="database unavailable")


class UpdateFailureSession:
    def get(self, _url):
        return FakeResponse(200, {"data": [{"name": "Teste", "id": "wf-1"}]})

    def put(self, _url, json=None):
        return FakeResponse(500, text="update rejected")


class TestDeployESegredos(unittest.TestCase):
    def test_gateway_preserves_external_port_for_websocket_origin(self):
        config = (ROOT / 'n8n/proxies/n8n-gateway.conf.template').read_text(encoding='utf-8')
        self.assertEqual(config.count('proxy_set_header Host $http_host;'), 2)
        self.assertEqual(config.count('proxy_set_header X-Forwarded-Host $http_host;'), 2)
        self.assertNotIn('proxy_set_header Host $host;', config)
        self.assertIn('proxy_set_header Upgrade $http_upgrade;', config)

    def test_env_normalizer_uses_runner_process_env_and_is_idempotent(self):
        source = (
            "const one=(typeof process !== 'undefined' && process.env.FOO) || 'x';\n"
            "const two=process.env.BAR;\n"
            "const dynamic=(typeof process!=='undefined' && process.env[name]) || '';"
        )
        normalized = workflow_helpers.normalize_n8n_env_access(source)
        self.assertNotIn("$env", normalized)
        self.assertIn("typeof process !== 'undefined' && process.env.FOO", normalized)
        self.assertIn("process.env.BAR", normalized)
        self.assertIn("typeof process!=='undefined' && process.env[name]", normalized)
        self.assertEqual(
            workflow_helpers.normalize_n8n_env_access(normalized), normalized
        )

    def test_recursive_sanitizer_converts_weak_glpi_fallbacks(self):
        workflow = {
            "headers": [
                "={{ $env.GLPI_APP_TOKEN || '' }}",
                "={{ $env.GLPI_AUTH_BASIC || 'Basic ' }}",
            ],
            "code": (
                "const appToken = String((typeof process !== 'undefined' && "
                "process.env.GLPI_APP_TOKEN) || '');\n"
                "const sessionToken = String($('GLPI: Sessão').first().json.session_token || '');"
            ),
        }
        workflow_helpers.sanitize_workflow_secrets(workflow)
        rendered = json.dumps(workflow)
        self.assertIn("GLPI_APP_TOKEN ausente", rendered)
        self.assertIn("GLPI_AUTH_BASIC ausente", rendered)
        self.assertNotIn("={{ $env.GLPI_APP_TOKEN || '' }}", rendered)
        self.assertNotIn("={{ $env.GLPI_AUTH_BASIC || 'Basic ' }}", rendered)
        self.assertIn("GLPI session_token ausente", rendered)
        self.assertLess(
            rendered.index("$env.GLPI_APP_TOKEN"),
            rendered.index("process.env.GLPI_APP_TOKEN"),
        )

    def test_public_bundle_has_no_predictable_credential(self):
        self.assertEqual(
            static_validator.forbidden_credential_occurrences(
                static_validator.PUBLIC_CREDENTIAL_SCAN_FILES
            ),
            [],
        )

    def test_forbidden_credential_scanner_detects_regression(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "unsafe.txt"
            path.write_text("Seed" + "Token2024CampusRP", encoding="utf-8")
            self.assertEqual(
                static_validator.forbidden_credential_occurrences([path]),
                [str(path)],
            )

    def test_project_database_config_fails_closed_without_environment(self):
        with patch.dict(project_env.os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "PGPORT"):
                project_env.postgres_connection_kwargs()

    def test_operational_dataset_role_defaults_to_local(self):
        role, model = dataset_generator.selected_model_config()
        self.assertEqual(role, "LOCAL")
        self.assertEqual(model["provider"], "local-native")

    def test_env_example_supports_static_validation_in_a_clean_clone(self):
        values = static_validator.parse_env_values(
            (ROOT / "n8n" / ".env.example").read_text(encoding="utf-8")
        )
        self.assertTrue(set(static_validator.REQUIRED_ENV_VARS).issubset(values))

    def test_local_only_does_not_require_remote_credentials(self):
        values = static_validator.parse_env_values(
            "IA_OPERATIONAL_SEQUENCE=LOCAL\n"
            "GEMINI_API_KEY_PRIMARY=\n"
            "GEMINI_API_KEY_SECONDARY=CHANGE_ME\n"
        )
        self.assertEqual(
            static_validator.invalid_configured_remote_secrets(values), []
        )

    def test_configured_remote_credential_is_validated(self):
        self.assertEqual(
            static_validator.invalid_configured_remote_secrets(
                {"GEMINI_API_KEY_SECONDARY": "curta"}
            ),
            ["GEMINI_API_KEY_SECONDARY"],
        )
        self.assertEqual(
            static_validator.invalid_configured_remote_secrets(
                {"GEMINI_API_KEY_SECONDARY": "credencial-comprida-de-teste"}
            ),
            [],
        )

    def test_env_local_overrides_env_but_not_process_environment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / ".env"
            local = Path(temp_dir) / ".env.local"
            base.write_text(
                "VALUE=base\nEXPLICIT=arquivo\nWF03_ID=wf-base\n",
                encoding="utf-8",
            )
            local.write_text(
                "VALUE=local\nWF03_ID=wf-local\n", encoding="utf-8"
            )
            with patch.dict(os.environ, {"EXPLICIT": "processo"}, clear=False):
                os.environ.pop("VALUE", None)
                os.environ.pop("WF03_ID", None)
                deploy_v9.load_project_env((base, local))
                self.assertEqual(os.environ["VALUE"], "local")
                self.assertEqual(os.environ["EXPLICIT"], "processo")
                self.assertEqual(
                    deploy_v9.workflow_ids()["V9-WF03-Classificacao.json"],
                    "wf-local",
                )

    def test_credential_listing_failure_stops_deploy(self):
        with self.assertRaisesRegex(RuntimeError, "Falha ao listar credenciais"):
            deploy_v9.ensure_credential(
                CredentialFailureSession(),
                {"name": "Postgres Triagem", "type": "postgres", "data": {}},
            )

    def test_workflow_update_failure_stops_deploy(self):
        workflow = {
            "name": "Teste",
            "nodes": [],
            "connections": {},
            "settings": {},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            workflow_path = Path(temp_dir) / "workflow.json"
            workflow_path.write_text(json.dumps(workflow), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "Falha ao atualizar Teste"):
                deploy_v9.deploy_workflow(
                    UpdateFailureSession(), workflow_path, "pg", "smtp"
                )


if __name__ == "__main__":
    unittest.main()
