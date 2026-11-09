import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "avaliacao" / "scripts" / "comparar_versoes_locais.py"


def load_module():
    spec = importlib.util.spec_from_file_location("comparar_versoes_locais", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Nao foi possivel carregar o comparador")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CompararVersoesLocaisTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()
        cls.report = cls.module.build_comparison()

    def test_valida_pareamento_integral_e_hashes(self):
        pairing = self.report["pairing_validation"]
        self.assertTrue(pairing["passed"])
        self.assertEqual(pairing["baseline_unique_unit_ids"], 1240)
        self.assertEqual(pairing["candidate_unique_unit_ids"], 1240)
        self.assertTrue(pairing["unit_files_byte_identical"])
        self.assertTrue(pairing["shared_input_sha256_identical_for_all_units"])
        self.assertTrue(pairing["gold_identical_for_all_units"])
        self.assertTrue(pairing["task_identical_for_all_units"])
        self.assertTrue(pairing["standardized_summary_metrics_reproduced"])
        self.assertEqual(
            self.report["sources"]["baseline"]["dataset_sha256"],
            self.report["sources"]["candidate"]["dataset_sha256"],
        )

    def test_reproduz_metricas_gerais_exatas(self):
        metrics = self.report["comparisons"]["overall"][
            "marginal_descriptive_metrics"
        ]
        baseline = metrics["baseline"]
        candidate = metrics["candidate"]
        self.assertEqual(baseline["availability"]["numerator"], 195)
        self.assertEqual(candidate["availability"]["numerator"], 1240)
        self.assertEqual(baseline["semantic_coverage"]["numerator"], 87)
        self.assertEqual(candidate["semantic_coverage"]["numerator"], 671)
        self.assertEqual(baseline["straight_through_automation"]["numerator"], 73)
        self.assertEqual(candidate["straight_through_automation"]["numerator"], 505)
        self.assertEqual(baseline["selective_accuracy"]["numerator"], 87)
        self.assertEqual(candidate["selective_accuracy"]["numerator"], 669)
        self.assertAlmostEqual(baseline["selective_accuracy"]["value"], 1.0)
        self.assertAlmostEqual(candidate["selective_accuracy"]["value"], 669 / 671)
        self.assertLess(
            candidate["latency_ms_available_only"]["mean"],
            baseline["latency_ms_available_only"]["mean"],
        )

    def test_contagens_pareadas_somam_total(self):
        transitions = self.report["comparisons"]["overall"][
            "exact_paired_transition_counts"
        ]
        for cells in transitions.values():
            self.assertEqual(sum(cells.values()), 1240)
        self.assertEqual(transitions["availability"]["candidate_only"], 1045)
        self.assertEqual(transitions["availability"]["baseline_only"], 0)

    def test_bloqueia_alegacoes_confirmatorias(self):
        scope = self.report["scientific_scope"]
        self.assertFalse(scope["confirmatory_result"])
        self.assertFalse(scope["generalization_claim_allowed"])
        self.assertFalse(scope["significance_test_performed"])
        self.assertFalse(scope["noninferiority_test_performed"])
        self.assertTrue(
            self.report["engineering_interpretation"][
                "not_proven_superior_in_generalization"
            ]
        )
        recommendation = self.report["engineering_interpretation"][
            "recommendation"
        ]
        self.assertEqual(
            recommendation["status"],
            "CANDIDATE_RECOMMENDED_FOR_NEXT_ENGINEERING_STAGE",
        )
        self.assertTrue(recommendation["recommended_for_next_engineering_stage"])
        self.assertFalse(recommendation["scientific_superiority_claim_allowed"])
        self.assertTrue(all(item["passed"] for item in recommendation["criteria"]))

    def test_recomendacao_muda_quando_criterio_explicito_nao_e_atendido(self):
        policy = self.module.RecommendationPolicy(
            min_semantic_coverage_delta=0.50,
        )
        report = self.module.build_comparison(recommendation_policy=policy)
        recommendation = report["engineering_interpretation"]["recommendation"]
        self.assertEqual(recommendation["status"], "CANDIDATE_NOT_RECOMMENDED")
        self.assertFalse(recommendation["recommended_for_next_engineering_stage"])
        self.assertIn("semantic_coverage_delta", recommendation["failed_criteria"])

    def test_recomendacao_fica_inconclusiva_sem_metrica_obrigatoria(self):
        comparisons = {
            "overall": {
                "marginal_descriptive_metrics": {
                    "records": 10,
                    "delta_candidate_minus_baseline": {
                        "availability": 0.1,
                        "semantic_coverage": 0.1,
                        "straight_through_automation": 0.1,
                    },
                },
                "selective_accuracy_on_common_covered_units": {
                    "delta_candidate_minus_baseline": None,
                    "common_covered_records": 10,
                },
                "latency_on_common_available_units": {
                    "paired_difference_candidate_minus_baseline_ms": {"mean": -1.0}
                },
                "exact_paired_transition_counts": {
                    "strict_correctness": {
                        "both_positive": 5,
                        "baseline_only": 0,
                        "candidate_only": 1,
                        "both_negative": 4,
                    }
                },
            }
        }
        recommendation = self.module.evaluate_engineering_recommendation(
            comparisons,
            candidate_version="candidate-x",
            policy=self.module.RecommendationPolicy(min_common_covered_units=1),
        )
        self.assertEqual(recommendation["status"], "INCONCLUSIVE_MISSING_METRICS")
        self.assertFalse(recommendation["recommended_for_next_engineering_stage"])

    def test_recomendacao_fica_inconclusiva_com_suporte_insuficiente(self):
        policy = self.module.RecommendationPolicy(min_common_covered_units=81)
        report = self.module.build_comparison(recommendation_policy=policy)
        recommendation = report["engineering_interpretation"]["recommendation"]
        self.assertEqual(
            recommendation["status"], "INCONCLUSIVE_INSUFFICIENT_SUPPORT"
        )
        self.assertFalse(recommendation["recommended_for_next_engineering_stage"])

    def test_detecta_divergencia_de_identidade(self):
        left = {
            "U1": {
                "shared_input_sha256": "a",
                "task": "classification",
                "gold": {"decision": "DEMO"},
            }
        }
        right = {
            "U1": {
                "shared_input_sha256": "b",
                "task": "classification",
                "gold": {"decision": "DEMO"},
            }
        }
        mismatch = self.module.compare_identity_fields(
            left, right, ("shared_input_sha256", "task", "gold")
        )
        self.assertEqual(
            mismatch, [{"unit_id": "U1", "field": "shared_input_sha256"}]
        )

    def test_escreve_json_csv_e_markdown(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self.module.write_outputs(self.report, Path(directory))
            self.assertTrue(all(path.is_file() for path in paths.values()))
            markdown = paths["markdown"].read_text(encoding="utf-8")
            baseline_version = self.report["sources"]["baseline"]["model_version"]
            candidate_version = self.report["sources"]["candidate"]["model_version"]
            self.assertIn(
                f"Comparação local {baseline_version} versus {candidate_version}",
                markdown,
            )
            self.assertIn("Critérios da recomendação de engenharia", markdown)
            self.assertNotIn("A v1.8 é a melhor candidata", markdown)
            self.assertIn("não confirmatória", markdown)
            self.assertGreater(paths["csv"].stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
