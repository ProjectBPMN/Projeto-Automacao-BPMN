from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "avaliacao" / "scripts" / "materializar_candidato_selecao.py"
SPEC = importlib.util.spec_from_file_location("materializar_candidato_selecao", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class MaterializationGuardTests(unittest.TestCase):
    def _fixture(self, root: Path, *, status: str = "VALID") -> Path:
        selection = root / "selection"
        selection.mkdir()
        validation = {
            "status": status,
            "development_only": True,
            "confirmatory_eligible": False,
            "configurations": 90,
            "classification_configurations": 35,
            "deduplication_configurations": 55,
            "run_fingerprint": "f" * 64,
            "protocol_sha256": "p" * 64,
        }
        results = {
            "run_fingerprint": "f" * 64,
            "protocol_sha256": "p" * 64,
            "development_only": True,
            "confirmatory_eligible": False,
            "winners": {"classification": None, "deduplication": None},
            "provisional_point_candidates": {
                "classification": "classification__hybrid__granite97m__linear_svm",
                "deduplication": "deduplication__hybrid__granite97m__logistic_regression",
            },
            "ranking": [
                {
                    "combination_id": "classification__hybrid__granite97m__linear_svm",
                    "task": "classification",
                    "rank": 1,
                    "representation": "hybrid",
                    "embedding": "granite97m",
                    "classifier": "linear_svm",
                    "evidence_status": "UNDERPOWERED",
                    "provisional_point_eligible": True,
                    "exclusion_reasons": ["confidence"],
                },
                {
                    "combination_id": "deduplication__hybrid__granite97m__logistic_regression",
                    "task": "deduplication",
                    "rank": 1,
                    "representation": "hybrid",
                    "embedding": "granite97m",
                    "classifier": "logistic_regression",
                    "evidence_status": "UNDERPOWERED",
                    "provisional_point_eligible": True,
                    "exclusion_reasons": ["confidence"],
                },
            ],
            "results": [
                {
                    "combination_id": "classification__hybrid__granite97m__linear_svm",
                    "status": "COMPLETED_DEVELOPMENT_OOF",
                    "metrics": {},
                },
                {
                    "combination_id": "deduplication__hybrid__granite97m__logistic_regression",
                    "status": "COMPLETED_DEVELOPMENT_OOF",
                    "metrics": {},
                },
            ],
        }
        protocol = {
            "protocol_sha256": "p" * 64,
            "config": {"schema": "fixture"},
        }
        for name, value in (
            ("validacao_resultados.json", validation),
            ("resultados.json", results),
            ("protocolo_congelado.json", protocol),
        ):
            (selection / name).write_text(json.dumps(value), encoding="utf-8")
        return selection

    def test_rejects_invalid_independent_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            selection = self._fixture(Path(temporary), status="INVALID")
            with self.assertRaises(module.MaterializationGuardError):
                module.validated_candidates(selection, allow_underpowered=True)

    def test_underpowered_candidate_requires_explicit_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            selection = self._fixture(Path(temporary))
            with self.assertRaises(module.MaterializationGuardError):
                module.validated_candidates(selection, allow_underpowered=False)
            _, _, _, candidates = module.validated_candidates(
                selection, allow_underpowered=True
            )
            self.assertEqual(
                candidates["classification"]["source"],
                "PROVISIONAL_POINT_CANDIDATE",
            )

    def test_runtime_contract_matches_validated_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            selection = self._fixture(Path(temporary))
            _, _, _, candidates = module.validated_candidates(
                selection, allow_underpowered=True
            )
            self.assertEqual(
                module.validate_runtime_compatibility(candidates), "granite97m"
            )

    def test_output_directory_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "candidate"
            module.prepare_output_dir(target)
            (target / "evidence.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(module.MaterializationGuardError):
                module.prepare_output_dir(target)


if __name__ == "__main__":
    unittest.main()
