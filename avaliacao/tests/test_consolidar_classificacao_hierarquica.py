import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "avaliacao" / "scripts" / "consolidar_classificacao_hierarquica.py"


def load_module():
    spec = importlib.util.spec_from_file_location("classificacao_hierarquica", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Nao foi possivel carregar o consolidador")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConsolidarClassificacaoHierarquicaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()
        cls.report = cls.module.build_report(
            cls.module.DEFAULT_RUN_DIR,
            cls.module.DEFAULT_ARTIFACT_MANIFEST,
            cls.module.DEFAULT_MODEL_MANIFEST,
        )

    def test_recalcula_resultados_hierarquicos_exatos(self):
        hierarchy = self.report["hierarchical_operational_classification"]
        phase_one = hierarchy["obra_vs_manutencao"]
        phase_two = hierarchy["maintenance_demo_vs_sob_demanda"]

        self.assertEqual(phase_one["eligible_records"], 480)
        self.assertEqual(phase_one["automatic_records"], 400)
        self.assertEqual(phase_one["human_review_records"], 80)
        self.assertAlmostEqual(phase_one["automatic_coverage"], 400 / 480)
        self.assertEqual(phase_one["selective_accuracy"], 1.0)
        self.assertEqual(phase_one["critical_maintenance_as_obra"]["count"], 0)
        self.assertEqual(phase_one["obra_as_maintenance"], 0)

        self.assertEqual(phase_two["eligible_records"], 320)
        self.assertEqual(phase_two["automatic_records"], 299)
        self.assertEqual(phase_two["human_review_records"], 21)
        self.assertAlmostEqual(phase_two["automatic_coverage"], 299 / 320)
        self.assertEqual(phase_two["selective_accuracy"], 1.0)
        self.assertEqual(phase_two["demo_as_sob_demanda"], 0)
        self.assertEqual(phase_two["sob_demanda_as_demo"], 0)

    def test_preserva_limitacoes_e_erro_global(self):
        data = self.report["dataset_structure"]
        four = self.report["four_class_classification"]
        safety = self.report["hierarchical_operational_classification"][
            "safety_across_all_four_gold_classes"
        ]

        self.assertEqual(data["classification_records"], 640)
        self.assertEqual(data["distinct_narrative_cores"], 128)
        self.assertEqual(data["realizations_per_core"], 5.0)
        self.assertEqual(four["operational_abstentions"], 182)
        self.assertEqual(four["routed_to_human"], 239)
        self.assertEqual(four["semantic_errors_on_covered_records"], 2)
        self.assertEqual(safety["straight_through_automatic_errors"], 1)
        self.assertFalse(self.report["scientific_interpretation"]["confirmatory_result"])

    def test_renderiza_relatorio_sem_alterar_fontes(self):
        with tempfile.TemporaryDirectory() as directory:
            text = self.module.render_markdown(self.report)
            output = Path(directory) / "RELATORIO.md"
            output.write_text(text, encoding="utf-8")
            self.assertIn("400/480", text)
            self.assertIn("299/320", text)
            self.assertIn("nao confirmatorio", text)
            self.assertGreater(output.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
