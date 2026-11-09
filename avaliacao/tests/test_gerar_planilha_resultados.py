import json
import unittest
from pathlib import Path

from avaliacao.scripts.gerar_planilha_resultados import (
    derive_metrics,
    read_jsonl,
    record_view,
)


ROOT = Path(__file__).resolve().parents[2]


class SpreadsheetMetricSemanticsTest(unittest.TestCase):
    def test_triagem_semantica_nao_e_abstencao_operacional(self):
        row = {
            "ok": True,
            "task": "classification",
            "decision": "TRIAGEM_MANUAL",
            "decision_path": "HYBRID_MODEL",
            "abstained": True,
            "gold": {"decision": "TRIAGEM_MANUAL"},
        }

        view = record_view(row)

        self.assertFalse(view["operational_abstention"])
        self.assertEqual(view["predicted_class"], "TRIAGEM_MANUAL")
        self.assertTrue(view["covered"])
        self.assertTrue(view["correct"])
        self.assertTrue(view["routed_to_human"])
        self.assertFalse(view["straight_through"])

    def test_gate_de_informacao_insuficiente_e_abstencao(self):
        row = {
            "ok": True,
            "task": "classification",
            "decision": "TRIAGEM_MANUAL",
            "decision_path": "DETERMINISTIC_INSUFFICIENT_INFORMATION",
            "abstained": True,
            "gold": {"decision": "TRIAGEM_MANUAL"},
        }

        view = record_view(row)

        self.assertTrue(view["operational_abstention"])
        self.assertIsNone(view["predicted_class"])
        self.assertEqual(view["evaluated_label"], "ABSTENCAO")
        self.assertFalse(view["covered"])
        self.assertFalse(view["correct"])
        self.assertTrue(view["routed_to_human"])

    def test_duplicidade_positiva_preserva_confirmacao_humana(self):
        row = {
            "ok": True,
            "task": "deduplication",
            "decision": "DUPLICADO",
            "decision_path": "HYBRID_MODEL",
            "abstained": False,
            "reference_id": 42,
            "gold": {"decision": "DUPLICADO", "reference_id": 42},
        }

        view = record_view(row)

        self.assertTrue(view["covered"])
        self.assertTrue(view["correct"])
        self.assertTrue(view["routed_to_human"])
        self.assertFalse(view["straight_through"])

    def test_metricas_v18_reconciliam_com_resumo_corrigido(self):
        directory = (
            ROOT
            / "avaliacao"
            / "resultados"
            / "local-only-desenvolvimento-v1.8.0-20260716"
        )
        predictions = read_jsonl(directory / "local_only_predictions.jsonl")
        corrected = json.loads(
            (directory / "local_only_summary_metrics_v1.1.json").read_text(
                encoding="utf-8"
            )
        )["metrics"]["all_contract_valid"]

        observed = derive_metrics(predictions)

        mapping = {
            "operational_abstentions": "abstention_count",
            "semantic_triage_predictions": "predicted_class_triagem_manual",
            "routed_to_human_total": "routed_to_human_total",
            "semantic_coverage": "semantic_coverage",
            "straight_through_coverage": "straight_through_automation_coverage",
            "selective_accuracy": "selective_accuracy",
        }
        for observed_key, expected_key in mapping.items():
            with self.subTest(metric=observed_key):
                self.assertAlmostEqual(
                    observed[observed_key], corrected[expected_key], places=12
                )


if __name__ == "__main__":
    unittest.main()
