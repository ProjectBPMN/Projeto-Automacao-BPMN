from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from avaliacao.confirmatorio.amostra import (
    clopper_pearson_upper_unilateral,
    planejar_zero_eventos,
    tamanho_minimo_zero_eventos,
)
from avaliacao.confirmatorio.avaliar import (
    executar_avaliacao_confirmatoria,
    reservar_abertura_confirmatoria,
    status_execucao,
)
from avaliacao.confirmatorio.familias import import_registry, validate_family
from avaliacao.confirmatorio.preregistro import (
    congelar_preregistro,
    criar_rascunho,
    verificar_preregistro_congelado,
)
from avaliacao.confirmatorio.util import sha256_file


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def family(index: int, label: str) -> dict:
    record_a = f"ticket-{index}-a"
    record_b = f"ticket-{index}-b"
    return {
        "schema_version": "dedup-independent-family-v1",
        "family_id": f"family-{index:04d}",
        "evidence_tier": "REAL_INSTITUTIONAL",
        "source_dependency_group_sha256": digest(f"group-{index}"),
        "provenance": {
            "source_system": "GLPI",
            "source_instance_id": "campus-test",
            "extraction_id": "extract-test",
            "query_or_export_ref": "audit-export-test",
            "collector_id": "custodian-a",
            "chain_of_custody_ref": "custody-test",
            "collected_at": "2026-01-02T12:00:00+00:00",
            "raw_export_sha256": digest("raw-export-test"),
        },
        "independence": {
            "attested_independent": True,
            "development_overlap_checked": True,
            "other_holdout_overlap_checked": True,
            "known_related_family_ids": [],
            "auditor_id": "auditor-a",
            "method": "hashes e revisão institucional",
            "attestation_ref": f"attestation-{index}",
            "reviewed_at": "2026-01-05T12:00:00+00:00",
        },
        "records": [
            {
                "source_record_id": record_a,
                "occurred_at": "2025-12-01T12:00:00+00:00",
                "content_sha256": digest(f"content-{index}-a"),
                "protected_payload_ref": f"vault://{record_a}",
            },
            {
                "source_record_id": record_b,
                "occurred_at": "2025-12-02T12:00:00+00:00",
                "content_sha256": digest(f"content-{index}-b"),
                "protected_payload_ref": f"vault://{record_b}",
            },
        ],
        "primary_anchor_id": record_a,
        "primary_challenge_id": record_b,
        "adjudication": {
            "protocol_version": "review-v1",
            "reviewer_1": {
                "reviewer_id": "reviewer-a",
                "label": label,
                "reviewed_at": "2026-01-03T12:00:00+00:00",
                "blind_to_model": True,
                "blind_to_other_reviewer": True,
            },
            "reviewer_2": {
                "reviewer_id": "reviewer-b",
                "label": label,
                "reviewed_at": "2026-01-03T13:00:00+00:00",
                "blind_to_model": True,
                "blind_to_other_reviewer": True,
            },
            "final_label": label,
            "finalized_at": "2026-01-04T12:00:00+00:00",
        },
        "subgroups": {"campus": "A" if index % 2 else "B"},
    }


def evaluation_config() -> dict:
    return {
        "schema_version": "confirmatory-evaluation-config-v1",
        "protocol_id": "dedup-confirmatory-test-v1",
        "hypotheses": [
            {
                "id": "H1",
                "primary": True,
                "statement": "O candidato cumpre todos os gates congelados.",
                "endpoint": "ALL_PRE_REGISTERED_GATES",
                "null_hypothesis": "ao menos um gate não é cumprido",
                "decision_rule": "ALL_GATES_PASS",
            }
        ],
        "candidate": {
            "id": "candidate-test-v1",
            "task": "deduplication",
            "selection_evidence_ref": "development-evidence-test",
            "frozen_no_retraining": True,
            "trained_without_holdout": True,
        },
        "metrics": [
            "brier",
            "log_loss",
            "ece",
            "risk_coverage",
            "subgroups",
            "critical_errors",
        ],
        "decision_policy": {
            "automatic_duplicate_min_probability": 0.9,
            "automatic_nonduplicate_max_probability": 0.1,
            "abstain_between_thresholds": True,
        },
        "analysis": {
            "confidence": 0.95,
            "ece_bins": 10,
            "missing_prediction_policy": "FAIL_CLOSED",
            "single_confirmatory_execution": True,
            "count_abstention_as_correct": False,
        },
        "gates": {
            "minimum_independent_families": 298,
            "maximum_technical_failures": 0,
            "minimum_automatic_coverage": 0.9,
            "maximum_selective_risk": 0.01,
            "maximum_ece": 0.05,
            "maximum_brier": 0.05,
        },
        "subgroups": ["campus"],
        "critical_errors": [
            {
                "id": "FN",
                "true_label": "DUPLICADO",
                "automatic_predicted_label": "NAO_DUPLICADO",
                "maximum_events": 0,
                "confidence": 0.95,
                "maximum_upper_exclusive": 0.02,
                "minimum_independent_exposures": 149,
            },
            {
                "id": "FP",
                "true_label": "NAO_DUPLICADO",
                "automatic_predicted_label": "DUPLICADO",
                "maximum_events": 0,
                "confidence": 0.95,
                "maximum_upper_exclusive": 0.02,
                "minimum_independent_exposures": 149,
            },
        ],
        "approvals": {
            "institutional_responsible_id": "responsible-a",
            "scientific_reviewer_id": "scientist-b",
            "approved_at": "2026-01-06T12:00:00+00:00",
            "approval_ref": "approval-test",
        },
    }


class ConfirmatoryPipelineTests(unittest.TestCase):
    def make_frozen(self, root: Path) -> tuple[Path, Path, list[dict]]:
        rows = [family(i, "DUPLICADO" if i < 149 else "NAO_DUPLICADO") for i in range(298)]
        source = root / "source.jsonl"
        source.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
        dataset = root / "holdout.jsonl"
        manifest = root / "holdout.manifest.json"
        import_registry(source, dataset, manifest)
        candidate = root / "candidate.bin"
        candidate.write_bytes(b"frozen-candidate-test")
        config = root / "config.json"
        config.write_text(json.dumps(evaluation_config()), encoding="utf-8")
        draft = root / "prereg.draft.json"
        criar_rascunho(
            evaluation_config_path=config,
            dataset_path=dataset,
            dataset_manifest_path=manifest,
            candidate_artifact_path=candidate,
            output_path=draft,
        )
        frozen = root / "prereg.frozen.json"
        congelar_preregistro(draft_path=draft, output_path=frozen)
        return frozen, candidate, rows

    def prediction_bundle(
        self, root: Path, frozen: Path, rows: list[dict], reservation: dict
    ) -> Path:
        document = verificar_preregistro_congelado(frozen)
        predictions = []
        for row in rows:
            label = row["adjudication"]["final_label"]
            predictions.append(
                {
                    "family_id": row["family_id"],
                    "status": "OK",
                    "duplicate_probability": 0.99 if label == "DUPLICADO" else 0.01,
                }
            )
        bundle = {
            "schema_version": "confirmatory-predictions-v1",
            "protocol_id": document["protocol_id"],
            "preregistration_sha256": sha256_file(frozen),
            "dataset_sha256": document["artifacts"]["dataset"]["sha256"],
            "candidate_sha256": document["artifacts"]["candidate"]["sha256"],
            "attempt_id": reservation["attempt_id"],
            "reservation_contract_sha256": reservation["contract_sha256"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "candidate_execution_id": "execution-test",
            "predictions": predictions,
        }
        path = root / "predictions.json"
        path.write_text(json.dumps(bundle), encoding="utf-8")
        return path

    def test_exact_zero_event_sample_is_149_for_strict_two_percent(self) -> None:
        self.assertEqual(tamanho_minimo_zero_eventos(0.02, 0.95), 149)
        self.assertGreaterEqual(clopper_pearson_upper_unilateral(0, 148), 0.02)
        self.assertLess(clopper_pearson_upper_unilateral(0, 149), 0.02)
        self.assertEqual(
            planejar_zero_eventos(
                maximum_upper=0.02,
                confidence=0.95,
                expected_exposure_fraction=1.0,
            )["minimum_recruited_independent_families"],
            149,
        )
        plan = planejar_zero_eventos(
            maximum_upper=0.02,
            confidence=0.95,
            expected_exposure_fraction=0.5,
            attrition_fraction=0.1,
            design_effect=1.2,
        )
        self.assertEqual(plan["minimum_effective_independent_exposures"], 149)
        self.assertGreater(plan["minimum_recruited_independent_families"], 298)

    def test_real_provenance_and_two_distinct_blind_reviewers_are_required(self) -> None:
        row = family(1, "DUPLICADO")
        row["evidence_tier"] = "SYNTHETIC"
        with self.assertRaisesRegex(ValueError, "dados sintéticos"):
            validate_family(row)
        row = family(1, "DUPLICADO")
        row["adjudication"]["reviewer_2"]["reviewer_id"] = "reviewer-a"
        with self.assertRaisesRegex(ValueError, "dois revisores distintos"):
            validate_family(row)

    def test_primary_claim_is_structurally_bound_to_all_frozen_gates(self) -> None:
        from avaliacao.confirmatorio.preregistro import validate_evaluation_config

        config = evaluation_config()
        config["hypotheses"][0]["endpoint"] = "texto livre incompatível"
        with self.assertRaisesRegex(ValueError, "ALL_PRE_REGISTERED_GATES"):
            validate_evaluation_config(config)

    def test_disagreement_requires_independent_third_adjudicator(self) -> None:
        row = family(2, "DUPLICADO")
        row["adjudication"]["reviewer_2"]["label"] = "NAO_DUPLICADO"
        with self.assertRaisesRegex(ValueError, "adjudicator"):
            validate_family(row)
        row["adjudication"]["adjudicator"] = {
            "reviewer_id": "reviewer-c",
            "label": "DUPLICADO",
            "reviewed_at": "2026-01-03T14:00:00+00:00",
            "blind_to_model": True,
        }
        validate_family(row)

    def test_frozen_preregistration_detects_candidate_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frozen, candidate, _ = self.make_frozen(root)
            verificar_preregistro_congelado(frozen)
            candidate.write_bytes(b"changed-after-freeze")
            with self.assertRaisesRegex(ValueError, "adulterado"):
                verificar_preregistro_congelado(frozen)

    def test_confirmatory_evaluation_reports_all_metrics_and_is_one_shot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frozen, _, rows = self.make_frozen(root)
            reservation = reservar_abertura_confirmatoria(
                preregistration_path=frozen,
                confirm_irreversible_open=True,
            )
            self.assertEqual(
                reservation["state"], "RESERVED_READY_FOR_BLINDED_INFERENCE"
            )
            predictions = self.prediction_bundle(root, frozen, rows, reservation)
            result = executar_avaliacao_confirmatoria(
                preregistration_path=frozen,
                predictions_path=predictions,
                confirm_predictions_registration_once=True,
            )
            self.assertEqual(result["confirmatory_status"], "PASS")
            self.assertLess(result["calibration"]["brier"], 0.001)
            self.assertIn("campus", result["subgroups"])
            self.assertEqual(result["critical_errors"]["FN"]["independent_exposures"], 149)
            self.assertLess(
                result["critical_errors"]["FN"]["clopper_pearson_upper_unilateral"],
                0.02,
            )
            self.assertEqual(status_execucao(frozen)["state"], "COMPLETED")
            with self.assertRaisesRegex(RuntimeError, "reserva não está disponível"):
                executar_avaliacao_confirmatoria(
                    preregistration_path=frozen,
                    predictions_path=predictions,
                    confirm_predictions_registration_once=True,
                )

    def test_structural_failure_consumes_attempt_and_blocks_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frozen, _, rows = self.make_frozen(root)
            reservation = reservar_abertura_confirmatoria(
                preregistration_path=frozen,
                confirm_irreversible_open=True,
            )
            predictions = self.prediction_bundle(root, frozen, rows, reservation)
            bundle = json.loads(predictions.read_text(encoding="utf-8"))
            bundle["predictions"].pop()
            predictions.write_text(json.dumps(bundle), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "1:1"):
                executar_avaliacao_confirmatoria(
                    preregistration_path=frozen,
                    predictions_path=predictions,
                    confirm_predictions_registration_once=True,
                )
            self.assertEqual(
                status_execucao(frozen)["state"], "FAILED_PREDICTIONS_CONSUMED"
            )
            with self.assertRaisesRegex(RuntimeError, "reserva não está disponível"):
                executar_avaliacao_confirmatoria(
                    preregistration_path=frozen,
                    predictions_path=predictions,
                    confirm_predictions_registration_once=True,
                )

    def test_predictions_cannot_be_registered_before_atomic_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frozen, _, _ = self.make_frozen(root)
            missing = root / "not-generated-before-reservation.json"
            with self.assertRaisesRegex(RuntimeError, "ainda não foi reservado"):
                executar_avaliacao_confirmatoria(
                    preregistration_path=frozen,
                    predictions_path=missing,
                    confirm_predictions_registration_once=True,
                )
            self.assertEqual(status_execucao(frozen)["status"], "NOT_RESERVED")

    def test_replacing_frozen_contract_after_reservation_consumes_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frozen, _, _ = self.make_frozen(root)
            alternate = root / "prereg.alternate.frozen.json"
            congelar_preregistro(
                draft_path=root / "prereg.draft.json", output_path=alternate
            )
            reservar_abertura_confirmatoria(
                preregistration_path=frozen,
                confirm_irreversible_open=True,
            )
            frozen.write_bytes(alternate.read_bytes())
            dummy = root / "bundle.json"
            dummy.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "substituído após a reserva"):
                executar_avaliacao_confirmatoria(
                    preregistration_path=frozen,
                    predictions_path=dummy,
                    confirm_predictions_registration_once=True,
                )
            self.assertEqual(
                status_execucao(frozen)["state"], "FAILED_PREDICTIONS_CONSUMED"
            )


if __name__ == "__main__":
    unittest.main()
