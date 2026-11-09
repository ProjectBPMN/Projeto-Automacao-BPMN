from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "avaliacao" / "scripts" / "validar_webhooks_confirmacao_e2e.py"
SPEC = importlib.util.spec_from_file_location("validar_webhooks_confirmacao_e2e", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def negative_state() -> dict:
    return {
        "ticket": {
            "triagem_status": "PENDENTE_FILA_IA",
            "classificacao": None,
            "classificacao_final": None,
            "duplicado_de_id": None,
            "em_aprovacao_fiscal": False,
            "decisao_fiscal": "REJEITOU_DUP",
            "token_presente": False,
            "motivo_classificacao": None,
            "fila_etapa": "CLASSIFICACAO",
            "fila_enfileirada_em": "2026-08-18T00:00:00+00:00",
            "fila_reservada_em": None,
            "ultima_acao_workflow": "WF04_ENFILEIROU_CLASSIFICACAO",
        },
        "eventos_wf04_rejeitado": 1,
    }


class FiscalOutcomeTests(unittest.TestCase):
    def test_workflow_manifest_covers_only_the_six_canonical_exports(self) -> None:
        manifest = MODULE.workflow_artifact_manifest()
        self.assertEqual(set(manifest), set(MODULE.CANONICAL_V9_WORKFLOWS))
        self.assertEqual(len(manifest), 6)
        for filename, item in manifest.items():
            self.assertRegex(item["sha256"], r"^[a-f0-9]{64}$", filename)
            self.assertGreater(item["node_count"], 0, filename)
            self.assertTrue(item["workflow_id"], filename)

    def test_accepts_positive_terminal_state(self) -> None:
        state = {
            "ticket": {
                "triagem_status": "DUPLICADO_FECHADO",
                "decisao_fiscal": "CONFIRMOU_DUP",
            },
            "eventos_wf04_confirmado": 1,
        }
        MODULE.assert_fiscal_outcome(state, "confirmar")

    def test_rejects_positive_state_with_duplicate_transition_event(self) -> None:
        state = {
            "ticket": {
                "triagem_status": "DUPLICADO_FECHADO",
                "decisao_fiscal": "CONFIRMOU_DUP",
            },
            "eventos_wf04_confirmado": 2,
        }
        with self.assertRaisesRegex(AssertionError, "uma única"):
            MODULE.assert_fiscal_outcome(state, "confirmar")

    def test_accepts_negative_handoff_state(self) -> None:
        MODULE.assert_fiscal_outcome(negative_state(), "nao_duplicado")

    def test_rejects_negative_state_with_residual_duplicate(self) -> None:
        state = negative_state()
        state["ticket"]["duplicado_de_id"] = 123
        with self.assertRaisesRegex(AssertionError, "duplicado_de_id"):
            MODULE.assert_fiscal_outcome(state, "nao_duplicado")

    def test_metric_oracle_sends_correct_class_for_false_positive(self) -> None:
        action = {
            "tipo_confirmacao": "AVALIACAO_METRICA",
            "run_id": "VALIDACAO-POSTS-E2E-20260818T000000Z",
            "scenario_id": "E2E01",
            "realization_id": "E2E-REALIZATION-001",
            "token_endpoint": "a" * 64,
            "decisao_webhook": "incorreta",
            "classe_correta_webhook": "NAO_DUPLICADO",
            "assessor_nonce": "c" * 32,
        }
        with patch.object(MODULE, "request", return_value={"http_status": 200}) as mocked:
            MODULE.oracle_request(
                action,
                {
                    "AVALIACAO_HUMANA_WEBHOOK_URL": "http://127.0.0.1/test",
                    "TEST_AUTO_REVIEW_TOKEN": "b" * 64,
                },
            )
        params = mocked.call_args.kwargs["params"]
        self.assertEqual(params["resultado"], "incorreta")
        self.assertEqual(params["classe_correta"], "NAO_DUPLICADO")

    def test_invalid_decision_fails_before_external_access(self) -> None:
        with self.assertRaisesRegex(ValueError, "decision"):
            MODULE.validate.__wrapped__(
                "VALIDACAO-POSTS-E2E-20260818T000000Z", ROOT, "talvez"
            )

    def test_expired_token_is_restored_even_when_request_raises(self) -> None:
        action = {"token_endpoint": "a" * 64}
        expired = {
            "ticket": {
                "fiscal_token_expirado": True,
                "token_presente": True,
            }
        }
        with (
            patch.object(MODULE, "set_fiscal_token_expiry") as set_expiry,
            patch.object(MODULE, "snapshot", return_value=expired),
            patch.object(
                MODULE,
                "oracle_request",
                side_effect=RuntimeError("falha simulada"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "falha simulada"):
                MODULE.probe_expired_fiscal_token(
                    action,
                    {},
                    "VALIDACAO-POSTS-E2E-20260818T000000Z",
                    321,
                )
        self.assertEqual(
            [call.args for call in set_expiry.call_args_list],
            [(321, True), (321, False)],
        )

    def test_expired_token_probe_records_immutable_state_and_restore(self) -> None:
        expired = {
            "ticket": {
                "id": 321,
                "fiscal_token_expirado": True,
                "token_presente": True,
                "decisao_fiscal": None,
            }
        }
        restored = {
            "ticket": {
                **expired["ticket"],
                "fiscal_token_expirado": False,
            }
        }
        with (
            patch.object(MODULE, "set_fiscal_token_expiry") as set_expiry,
            patch.object(
                MODULE,
                "snapshot",
                side_effect=[expired, expired, restored],
            ),
            patch.object(
                MODULE,
                "oracle_request",
                return_value={"http_status": 409},
            ),
        ):
            evidence = MODULE.probe_expired_fiscal_token(
                {"token_endpoint": "a" * 64},
                {},
                "VALIDACAO-POSTS-E2E-20260818T000000Z",
                321,
            )
        self.assertTrue(evidence["ticket_immutable"])
        self.assertTrue(evidence["validity_restored"])
        self.assertEqual(
            [call.args for call in set_expiry.call_args_list],
            [(321, True), (321, False)],
        )

    def test_invalid_token_probe_uses_other_validly_formatted_token(self) -> None:
        state = {"ticket": {"id": 321, "decisao_fiscal": None}}
        action = {"token_endpoint": "a" * 64}
        with (
            patch.object(MODULE, "snapshot", return_value=state),
            patch.object(
                MODULE,
                "oracle_request",
                return_value={"http_status": 409},
            ) as request,
        ):
            evidence = MODULE.probe_invalid_fiscal_token(
                action,
                {},
                "VALIDACAO-POSTS-E2E-20260818T000000Z",
                321,
            )
        submitted = request.call_args.args[0]["token_endpoint"]
        self.assertNotEqual(submitted, action["token_endpoint"])
        self.assertRegex(submitted, r"^[a-f0-9]{64}$")
        self.assertTrue(evidence["ticket_immutable"])

    def test_concurrent_posts_require_one_accepted_and_one_idempotent(self) -> None:
        accepted, competing = MODULE.validate_concurrent_fiscal_responses(
            [{"http_status": 200}, {"http_status": 202}]
        )
        self.assertEqual(accepted["http_status"], 202)
        self.assertEqual(competing["http_status"], 200)

        with self.assertRaisesRegex(AssertionError, "exatamente um HTTP 202"):
            MODULE.validate_concurrent_fiscal_responses(
                [{"http_status": 202}, {"http_status": 202}]
            )
        with self.assertRaisesRegex(AssertionError, "somente 200 ou 409"):
            MODULE.validate_concurrent_fiscal_responses(
                [{"http_status": 202}, {"http_status": 500}]
            )


if __name__ == "__main__":
    unittest.main()
