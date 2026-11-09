from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / "n8n" / "workflows" / "Versão9"
SCRIPT_DIR = ROOT / "avaliacao" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import conferir_gabarito as oracle  # noqa: E402


class _Response:
    status = 202

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class TestOraculoDeterministico(unittest.TestCase):
    def test_guard_fails_closed_before_reading_labels(self):
        valid = {
            "TEST_MODE": "true",
            "TEST_AUTO_HUMAN_CONFIRMATION": "true",
            "TEST_AUTO_REVIEW_TOKEN": "a" * 64,
        }
        cases = [
            ("x", valid, "run_id inválido"),
            (
                "VALIDACAO-ORACLE-001",
                {**valid, "TEST_MODE": "false"},
                "TEST_MODE não está ativo",
            ),
            (
                "VALIDACAO-ORACLE-001",
                {**valid, "TEST_AUTO_HUMAN_CONFIRMATION": "false"},
                "confirmação automática não está ativa",
            ),
            (
                "VALIDACAO-ORACLE-001",
                {**valid, "TEST_AUTO_REVIEW_TOKEN": "curto"},
                "token do assessor ausente ou inválido",
            ),
            (
                "VALIDACAO-ORACLE-001",
                {
                    **valid,
                    "FISCAL_WEBHOOK_URL": "http://n8n.test/webhook/outro-workflow",
                },
                "endpoint deve terminar exatamente",
            ),
        ]
        for run_id, env, message in cases:
            with self.subTest(message=message):
                with patch.object(oracle, "_project_env", return_value=env), patch.object(
                    oracle, "query"
                ) as query_mock:
                    with self.assertRaisesRegex(RuntimeError, message):
                        oracle._oracle_guard(run_id)
                    query_mock.assert_not_called()

    def test_guard_requires_authorized_synthetic_experiment(self):
        env = {
            "TEST_MODE": "true",
            "TEST_AUTO_HUMAN_CONFIRMATION": "true",
            "TEST_AUTO_REVIEW_TOKEN": "a" * 64,
        }
        authorized = {
            "status": "EXECUTANDO",
            "test_mode": True,
            "auto_human_confirmation": True,
            "total_realizacoes": 990,
            "realizacoes_invalidas": 0,
        }
        with patch.object(oracle, "_project_env", return_value=env), patch.object(
            oracle, "query", return_value=[authorized]
        ):
            self.assertEqual(oracle._oracle_guard("VALIDACAO-ORACLE-001"), env)

        for field, value in (
            ("status", "PLANEJADO"),
            ("test_mode", False),
            ("auto_human_confirmation", False),
            ("total_realizacoes", 0),
            ("realizacoes_invalidas", 1),
        ):
            row = {**authorized, field: value}
            with self.subTest(field=field), patch.object(
                oracle, "_project_env", return_value=env
            ), patch.object(oracle, "query", return_value=[row]):
                with self.assertRaisesRegex(RuntimeError, "ORACULO_BLOQUEADO"):
                    oracle._oracle_guard("VALIDACAO-ORACLE-001")

    def test_oracle_calls_the_same_wf04_and_wf05_endpoints(self):
        env = {
            "TEST_AUTO_REVIEW_TOKEN": "b" * 64,
            "FISCAL_WEBHOOK_URL": (
                "http://n8n.test/webhook/fiscal-decisao-fiscal-ic-2026"
            ),
            "AVALIACAO_HUMANA_WEBHOOK_URL": (
                "http://n8n.test/webhook/avaliacao-humana-v9"
            ),
        }
        common = {
            "auto_confirmacao_id": 1,
            "ticket_id": 321,
            "run_id": "VALIDACAO-ORACLE-001",
            "scenario_id": "D01",
            "realization_id": "CASO-001",
            "assessor_nonce": "c" * 32,
            "token_endpoint": "d" * 64,
        }
        fiscal = {
            **common,
            "tipo_confirmacao": "FISCAL_DUPLICIDADE",
            "decisao_webhook": "confirmar",
        }
        review = {
            **common,
            "auto_confirmacao_id": 2,
            "tipo_confirmacao": "AVALIACAO_METRICA",
            "decisao_webhook": "incorreta",
            "classe_correta_webhook": "NAO_DUPLICADO",
        }
        with patch.object(
            oracle.urllib.request, "urlopen", side_effect=[_Response(), _Response()]
        ) as urlopen_mock, patch.object(oracle, "_finish_oracle_action") as finish_mock:
            self.assertTrue(oracle._call_oracle_action(fiscal, env))
            self.assertTrue(oracle._call_oracle_action(review, env))

        requests = [call.args[0] for call in urlopen_mock.call_args_list]
        fiscal_url = urllib.parse.urlsplit(requests[0].full_url)
        review_url = urllib.parse.urlsplit(requests[1].full_url)
        self.assertEqual(f"{fiscal_url.scheme}://{fiscal_url.netloc}{fiscal_url.path}", env["FISCAL_WEBHOOK_URL"])
        self.assertEqual(f"{review_url.scheme}://{review_url.netloc}{review_url.path}", env["AVALIACAO_HUMANA_WEBHOOK_URL"])
        fiscal_params = urllib.parse.parse_qs(fiscal_url.query)
        review_params = urllib.parse.parse_qs(review_url.query)
        self.assertEqual(fiscal_params["fonte"], ["ORACULO_GABARITO"])
        self.assertEqual(fiscal_params["decisao"], ["confirmar"])
        self.assertEqual(review_params["fonte"], ["ORACULO_GABARITO"])
        self.assertEqual(review_params["resultado"], ["incorreta"])
        self.assertEqual(review_params["classe_correta"], ["NAO_DUPLICADO"])
        for request in requests:
            self.assertEqual(request.get_method(), "POST")
            headers = {key.lower(): value for key, value in request.header_items()}
            self.assertEqual(headers["x-test-mode"], "true")
            self.assertEqual(headers["x-test-auto-review-token"], "b" * 64)
            self.assertEqual(headers["x-test-auto-review-nonce"], "c" * 32)
        self.assertEqual(finish_mock.call_count, 2)

    def test_clear_and_legacy_cli_flags_enable_the_same_confirmation_path(self):
        run_id = "VALIDACAO-ORACLE-001"
        current = oracle.parse_args(
            ["--run-id", run_id, "--resolver-confirmacoes-automaticas"]
        )
        legacy = oracle.parse_args(["--run-id", run_id, "--resolver-fiscal"])
        self.assertTrue(current.resolver_confirmacoes_automaticas)
        self.assertTrue(legacy.resolver_confirmacoes_automaticas)
        self.assertEqual(vars(current), vars(legacy))

    def test_audit_update_never_persists_raw_endpoint_token(self):
        action = {
            "auto_confirmacao_id": 77,
            "assessor_nonce": "c" * 32,
            "token_endpoint": "segredo-endpoint-que-nao-deve-ir-ao-banco",
        }
        with patch.object(oracle, "execute") as execute_mock:
            oracle._finish_oracle_action(action, True, 202, None)
        sql, parameters = execute_mock.call_args.args
        self.assertIn("assessor_nonce_hash=encode(sha256", sql)
        self.assertNotIn(action["token_endpoint"], repr(parameters))
        self.assertNotIn(action["token_endpoint"], sql)

    @unittest.skipUnless(shutil.which("node"), "Node.js indisponível para testar webhooks")
    def test_human_paths_remain_valid_and_oracle_paths_fail_without_headers(self):
        workflows = {
            "wf04": json.loads(
                (WORKFLOW_DIR / "V9-WF04-Decisao-Fiscal.json").read_text(
                    encoding="utf-8"
                )
            ),
            "wf05": json.loads(
                (WORKFLOW_DIR / "V9-WF05-Metricas.json").read_text(encoding="utf-8")
            ),
        }
        sources = {
            "wf04": next(
                node
                for node in workflows["wf04"]["nodes"]
                if node["name"] == "Extrair Decisão"
            )["parameters"]["jsCode"],
            "wf05": next(
                node
                for node in workflows["wf05"]["nodes"]
                if node["name"] == "Extrair Avaliação Humana"
            )["parameters"]["jsCode"],
        }
        payloads = {
            "human04": {
                "query": {
                    "decisao": "confirmar",
                    "chamado_id": "321",
                    "token": "d" * 64,
                },
                "headers": {},
            },
            "oracle04": {
                "query": {
                    "fonte": "ORACULO_GABARITO",
                    "decisao": "confirmar",
                    "chamado_id": "321",
                    "token": "d" * 64,
                },
                "headers": {},
            },
            "human05": {
                "query": {"token": "e" * 64, "resultado": "correta"},
                "headers": {},
            },
            "oracle05": {
                "query": {
                    "fonte": "ORACULO_GABARITO",
                    "token": "e" * 64,
                    "resultado": "correta",
                },
                "headers": {},
            },
        }
        harness = f"""
const AsyncFunction=Object.getPrototypeOf(async function(){{}}).constructor;
const sources={json.dumps(sources)};
const payloads={json.dumps(payloads)};
console.log=()=>{{}};
const run=async(source,payload)=>{{
  const fn=new AsyncFunction('$json','$env',source);
  const result=await fn(payload,{{}});
  return result[0].json;
}};
const output={{
  human04:await run(sources.wf04,payloads.human04),
  oracle04:await run(sources.wf04,payloads.oracle04),
  human05:await run(sources.wf05,payloads.human05),
  oracle05:await run(sources.wf05,payloads.oracle05)
}};
process.stdout.write(JSON.stringify(output));
"""
        completed = subprocess.run(
            [shutil.which("node") or "node", "--input-type=module"],
            input=harness,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
            encoding="utf-8",
        )
        result = json.loads(completed.stdout)
        self.assertTrue(result["human04"]["ok"])
        self.assertFalse(result["human04"]["oraculo"])
        self.assertEqual(result["human04"]["origem_decisao"], "FISCAL_GLPI")
        self.assertTrue(result["human05"]["ok"])
        self.assertFalse(result["human05"]["oraculo"])
        self.assertEqual(result["human05"]["fonte_gabarito"], "REVISAO_HUMANA")
        self.assertFalse(result["oracle04"]["ok"])
        self.assertFalse(result["oracle05"]["ok"])

    def test_oracle_is_external_idempotent_and_never_enters_wf06(self):
        source = (ROOT / "avaliacao" / "scripts" / "conferir_gabarito.py").read_text(
            encoding="utf-8"
        )
        schema = (ROOT / "database" / "init_v9.sql").read_text(encoding="utf-8")
        table = schema.split("CREATE TABLE IF NOT EXISTS avaliacao_auto_confirmacoes", 1)[
            1
        ].split("CREATE INDEX IF NOT EXISTS idx_auto_confirmacoes_pendentes", 1)[0]
        wf02 = json.loads(
            (WORKFLOW_DIR / "V9-WF02-Triagem.json").read_text(encoding="utf-8")
        )
        wf06 = json.loads(
            (WORKFLOW_DIR / "V9-WF06-Fila-IA.json").read_text(encoding="utf-8")
        )

        self.assertIn("UNIQUE(run_id, realization_id, tipo_confirmacao, etapa)", table)
        self.assertIn("token_hash", table)
        self.assertIn("assessor_nonce_hash", table)
        self.assertIn("CREATE UNIQUE INDEX IF NOT EXISTS idx_auto_confirmacoes_nonce", schema)
        self.assertNotIn("token_endpoint", table)
        self.assertNotIn("assessor_nonce TEXT", table)
        self.assertIn("encode(sha256(convert_to(token_endpoint,'UTF8')),'hex')", source)
        self.assertIn("i.predicao='DUPLICADO'", source)
        self.assertIn("c.em_aprovacao_fiscal=TRUE", source)
        self.assertIn("c.fiscal_decision_token ~ '^[a-f0-9]{32,128}$'", source)
        self.assertIn("i.criado_em<=COALESCE(c.aprovacao_iniciada_em,NOW())", source)
        self.assertIn("d.criado_em<=COALESCE(ah.solicitado_em,NOW())", source)
        self.assertNotIn("fiscal_pending", source)

        fiscal_actions = source.split("acoes_fiscais AS (", 1)[1].split(
            "acoes_metricas AS (", 1
        )[0]
        # Falso negativo (predição NAO_DUPLICADO com gold DUPLICADO) não
        # possui link fiscal e permanece somente como erro métrico.
        self.assertIn("AND i.predicao='DUPLICADO'", fiscal_actions)
        self.assertNotIn("i.predicao='NAO_DUPLICADO'", fiscal_actions)

        self.assertEqual(
            wf02["connections"]["Normalizar Dedup"]["main"][0][0]["node"],
            "PG: Registrar IA Dedup",
        )
        self.assertEqual(
            wf02["connections"]["PG: Registrar IA Dedup"]["main"][0][0]["node"],
            "Decisão IA Persistida?",
        )
        serialized_wf06 = json.dumps(wf06, ensure_ascii=False).lower()
        self.assertNotIn("oraculo", serialized_wf06)
        self.assertNotIn("gabarito", serialized_wf06)
        self.assertNotIn("avaliacao_auto_confirmacoes", serialized_wf06)

        for filename in ("V9-WF04-Decisao-Fiscal.json", "V9-WF05-Metricas.json"):
            workflow_text = (WORKFLOW_DIR / filename).read_text(encoding="utf-8")
            self.assertIn("TEST_AUTO_HUMAN_CONFIRMATION", workflow_text)
            self.assertIn("sameSecret", workflow_text)
            self.assertIn("avaliacao_auto_confirmacoes", workflow_text)
            self.assertIn("sha256(convert_to", workflow_text)


if __name__ == "__main__":
    unittest.main()
