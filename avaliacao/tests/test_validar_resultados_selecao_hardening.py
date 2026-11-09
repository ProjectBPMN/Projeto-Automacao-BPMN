from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

import numpy as np

from avaliacao.scripts import selecionar_modelos_supervisionados as selection
from avaliacao.scripts import validar_resultados_selecao as validation


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = (
    ROOT / "avaliacao" / "config" / "selecao_modelos_supervisionados_v1.json"
)


class HardenedResultValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    def test_boolean_parser_only_accepts_canonical_csv_values(self) -> None:
        self.assertTrue(validation.parse_bool("True", context="test"))
        self.assertFalse(validation.parse_bool("False", context="test"))
        for invalid in ("true", "false", "1", "0", "yes", ""):
            with self.subTest(invalid=invalid), self.assertRaises(
                validation.ResultValidationError
            ):
                validation.parse_bool(invalid, context="test")

    def test_prediction_row_is_rederived_from_probability_and_policy(self) -> None:
        row = {
            "combination_id": "classification__tfidf__none__logistic_regression",
            "task": "classification",
            "representation": "tfidf",
            "embedding": "",
            "classifier": "logistic_regression",
            "fold": "0",
            "unit_id": "case-1",
            "group": "core-1",
            "gold": "DEMO",
            "prediction": "DEMO",
            "semantic_prediction": "DEMO",
            "covered": "True",
            "correct": "True",
            "confidence": "0.80",
            "review_reason": "AUTOMATIC_DECISION",
            "p_obra": "0.05",
            "p_demo": "0.80",
            "p_sob_demanda": "0.10",
            "p_triagem_manual": "0.05",
        }
        parsed = validation._validate_probability_row(
            row,
            combination_id=row["combination_id"],
            fold_policy={"threshold": 0.70, "obra_threshold": 0.90},
        )
        self.assertTrue(parsed["covered_bool"])
        self.assertEqual(parsed["semantic_index"], 1)

        for key, value in (
            ("semantic_prediction", "OBRA"),
            ("covered", "true"),
            ("review_reason", "LOW_CONFIDENCE"),
            ("p_extra", "0"),
        ):
            tampered = dict(row)
            tampered[key] = value
            with self.subTest(key=key), self.assertRaises(
                validation.ResultValidationError
            ):
                validation._validate_probability_row(
                    tampered,
                    combination_id=row["combination_id"],
                    fold_policy={"threshold": 0.70, "obra_threshold": 0.90},
                )

    def test_classification_metrics_and_bootstrap_match_executor(self) -> None:
        config = copy.deepcopy(self.config)
        config["cross_validation"]["bootstrap_group_resamples"] = 80
        labels = np.asarray([0, 0, 1, 1, 2, 2, 3, 3], dtype=int)
        probabilities = np.asarray(
            [
                [0.90, 0.04, 0.03, 0.03],
                [0.55, 0.30, 0.10, 0.05],
                [0.04, 0.86, 0.05, 0.05],
                [0.10, 0.62, 0.20, 0.08],
                [0.04, 0.04, 0.87, 0.05],
                [0.05, 0.20, 0.65, 0.10],
                [0.05, 0.05, 0.10, 0.80],
                [0.10, 0.10, 0.30, 0.50],
            ]
        )
        predictions = np.argmax(probabilities, axis=1)
        covered = np.asarray([True, False, True, True, True, True, False, False])
        groups = [f"group-{index // 2}" for index in range(len(labels))]
        rows = [
            {
                "gold_index": int(labels[index]),
                "semantic_index": int(predictions[index]),
                "covered_bool": bool(covered[index]),
                "probabilities": probabilities[index],
                "group": groups[index],
            }
            for index in range(len(labels))
        ]
        observed = validation._classification_metrics(
            rows, config=config, cache=validation.BootstrapCache()
        )
        expected = selection.classification_summary(
            labels,
            probabilities,
            predictions,
            covered,
            groups,
            bootstrap_resamples=80,
            seed=int(config["cross_validation"]["outer_seed"]),
            confidence_level=float(config["cross_validation"]["confidence_level"]),
        )
        validation.assert_close(observed, expected, context="classification")

    def test_dedup_metrics_and_bootstrap_match_executor(self) -> None:
        config = copy.deepcopy(self.config)
        config["cross_validation"]["bootstrap_group_resamples"] = 80
        labels = np.asarray([0, 0, 0, 1, 1, 1, 0, 1], dtype=int)
        p_duplicate = np.asarray([0.02, 0.10, 0.55, 0.98, 0.75, 0.48, 0.03, 0.99])
        probabilities = np.column_stack([1.0 - p_duplicate, p_duplicate])
        decisions = np.asarray([0, 0, -1, 1, 1, -1, 0, 1], dtype=int)
        covered = decisions >= 0
        semantic = np.argmax(probabilities, axis=1)
        groups = [f"episode-{index // 2}" for index in range(len(labels))]
        rows = [
            {
                "gold_index": int(labels[index]),
                "semantic_index": int(semantic[index]),
                "decision_index": int(decisions[index]),
                "covered_bool": bool(covered[index]),
                "probabilities": probabilities[index],
                "group": groups[index],
            }
            for index in range(len(labels))
        ]
        observed = validation._dedup_metrics(
            rows, config=config, cache=validation.BootstrapCache()
        )
        expected = selection.dedup_summary(
            labels,
            probabilities,
            decisions,
            covered,
            groups,
            false_negative_cost=5.0,
            false_positive_cost=1.0,
            bootstrap_resamples=80,
            seed=int(config["cross_validation"]["outer_seed"]),
            confidence_level=float(config["cross_validation"]["confidence_level"]),
        )
        validation.assert_close(observed, expected, context="deduplication")

    def test_xai_requires_complete_class_coverage_and_valid_fractions(self) -> None:
        config = copy.deepcopy(self.config)
        config["xai"]["explained_records_per_task"] = 4
        config["xai"]["background_groups"] = 2
        selected = {
            "classification": "classification__tfidf__none__logistic_regression",
            "deduplication": "deduplication__metadata__none__logistic_regression",
        }
        payload = []
        for task, labels in (
            ("classification", [0, 1, 2, 3]),
            ("deduplication", [0, 1, 0, 1]),
        ):
            groups = [f"{task}-g1", f"{task}-g2"]
            payload.append(
                {
                    "status": "COMPLETED_FALLBACK",
                    "task": task,
                    "combination_id": selected[task],
                    "method": "GroupedPermutationImportance",
                    "selection_evidence_status": "PROVISIONAL_POINT_CANDIDATE",
                    "causal_interpretation": False,
                    "feature_count": 10,
                    "background_groups": groups,
                    "background_groups_sha256": validation.canonical_sha256(groups),
                    "explained_unit_ids": [f"{task}-{index}" for index in range(4)],
                    "explained_labels": labels,
                    "family_importance": [
                        {
                            "family": "tfidf_word",
                            "baseline_macro_f1": 0.8,
                            "mean_permuted_macro_f1": 0.6,
                            "macro_f1_drop": 0.2,
                            "repeats": 5,
                            "fraction": 1.0,
                        }
                    ],
                    "global_top_features": [],
                    "local_explanations": [],
                }
            )
        family_csv = [
            {
                "task": item["task"],
                "combination_id": item["combination_id"],
                **{key: str(value) for key, value in item["family_importance"][0].items()},
            }
            for item in payload
        ]
        self.assertEqual(
            validation._validate_xai(
                payload,
                config=config,
                selected=selected,
                evidence_status={
                    "classification": "PROVISIONAL_POINT_CANDIDATE",
                    "deduplication": "PROVISIONAL_POINT_CANDIDATE",
                },
                family_csv=family_csv,
            ),
            2,
        )
        payload[0]["explained_labels"] = [0, 0, 1, 1]
        with self.assertRaises(validation.ResultValidationError):
            validation._validate_xai(
                payload,
                config=config,
                selected=selected,
                evidence_status={
                    "classification": "PROVISIONAL_POINT_CANDIDATE",
                    "deduplication": "PROVISIONAL_POINT_CANDIDATE",
                },
                family_csv=family_csv,
            )

    def test_duplicate_identifiers_are_rejected_before_dictionary_coercion(self) -> None:
        rows = [{"id": "same"}, {"id": "same"}]
        with self.assertRaises(validation.ResultValidationError):
            validation.unique_by(rows, "id", context="test")

    def test_task_rows_filters_mixed_artifacts_before_scope_checks(self) -> None:
        payload = [
            {"task": "classification", "id": "classification-row"},
            {"task": "deduplication", "id": "deduplication-row"},
        ]
        self.assertEqual(
            validation.task_rows(
                payload,
                ("classification",),
                context="test",
            ),
            [payload[0]],
        )
        for invalid in (None, {}, ["not-an-object"]):
            with self.subTest(invalid=invalid), self.assertRaises(
                validation.ResultValidationError
            ):
                validation.task_rows(
                    invalid,
                    ("classification",),
                    context="test",
                )

    def test_independent_ranking_reproduces_executor_selection(self) -> None:
        def result(combination_id: str, macro_f1: float, fit_seconds: float) -> dict:
            return {
                "combination_id": combination_id,
                "task": "classification",
                "representation": "tfidf",
                "embedding": None,
                "classifier": "logistic_regression",
                "status": "COMPLETED_DEVELOPMENT_OOF",
                "folds": [{"fit_seconds": fit_seconds}],
                "metrics": {
                    "automatic_non_obra_as_obra": 0,
                    "automatic_non_obra_as_obra_group_rate_upper": 0.01,
                    "automatic_risk": 0.02,
                    "automatic_coverage": 0.70,
                    "macro_f1": macro_f1,
                    "obra_recall": 0.90,
                    "log_loss": 0.30,
                    "confidence_intervals_group_bootstrap": {
                        "selective_risk": [0.0, 0.05],
                        "coverage": [0.60, 0.80],
                    },
                },
            }

        results = [
            result("classification__tfidf__none__a", 0.90, 1.0),
            result("classification__tfidf__none__b", 0.91, 2.0),
        ]
        executor_rows, executor_winner, executor_provisional = selection.selection_rank(
            results,
            task="classification",
            policy=self.config["operating_policy"],
        )
        validator_rows, validator_winner, validator_provisional = (
            validation._independent_rank(
                results,
                {item["combination_id"]: item["metrics"] for item in results},
                task="classification",
                policy=self.config["operating_policy"],
            )
        )
        self.assertEqual(
            [row["combination_id"] for row in validator_rows],
            [row["combination_id"] for row in executor_rows],
        )
        self.assertEqual(validator_winner, executor_winner["combination_id"])
        self.assertEqual(
            validator_provisional, executor_provisional["combination_id"]
        )

    def test_latency_validator_requires_raw_tfidf_for_non_embedding_dedup(self) -> None:
        selected = {
            "classification": "classification__tfidf__none__logistic_regression",
            "deduplication": "deduplication__metadata__none__logistic_regression",
        }

        def row(task: str, scenario: str) -> dict:
            return {
                "status": "COMPLETED",
                "task": task,
                "combination_id": selected[task],
                "scenario": scenario,
                "measurement_scope": "raw_text_to_base_classifier_prediction_before_calibration_and_threshold",
                "device": "cpu",
                "precision": "fp32",
                "seed": 20260804,
                "records": 20,
                "warmup_records": 3,
                "encoder_calls_per_record": 0,
                "reference_cache_precompute_seconds": 0.0,
                "cold_encoder_load_seconds": 0.0,
                "cold_encoder_load_peak_rss_mb": None,
                "final_base_fit_seconds": 0.1,
                "latency_ms_p50": 1.0,
                "latency_ms_p95": 2.0,
                "throughput_records_per_second": 100.0,
                "peak_process_rss_mb": 200.0,
            }

        payload = [
            row("classification", "classification_raw_text"),
            row("deduplication", "deduplication_raw_text_tfidf"),
        ]
        csv_rows = [
            {key: "" if value is None else str(value) for key, value in item.items()}
            for item in payload
        ]
        self.assertEqual(
            validation._validate_performance(
                payload,
                csv_rows,
                config=self.config,
                selected=selected,
            ),
            2,
        )
        payload[0]["latency_ms_p95"] = 0.5
        with self.assertRaises(validation.ResultValidationError):
            validation._validate_performance(
                payload,
                csv_rows,
                config=self.config,
                selected=selected,
            )

    def test_latency_validator_requires_two_scenarios_for_embedding_dedup(self) -> None:
        selected = {
            "classification": "classification__tfidf__none__logistic_regression",
            "deduplication": "deduplication__hybrid_metadata__granite97m__logistic_regression",
        }

        def row(task: str, scenario: str, encoder_calls: int) -> dict:
            return {
                "status": "COMPLETED",
                "task": task,
                "combination_id": selected[task],
                "scenario": scenario,
                "measurement_scope": "raw_text_to_base_classifier_prediction_before_calibration_and_threshold",
                "device": "cpu",
                "precision": "fp32",
                "seed": 20260804,
                "records": 20,
                "warmup_records": 3,
                "encoder_calls_per_record": encoder_calls,
                "reference_cache_precompute_seconds": 0.0,
                "cold_encoder_load_seconds": 0.1,
                "cold_encoder_load_peak_rss_mb": 500.0,
                "final_base_fit_seconds": 0.1,
                "latency_ms_p50": 10.0,
                "latency_ms_p95": 20.0,
                "throughput_records_per_second": 50.0,
                "peak_process_rss_mb": 600.0,
            }

        payload = [
            row("classification", "classification_raw_text", 0),
            row(
                "deduplication",
                "deduplication_reference_embedding_cached",
                1,
            ),
            row("deduplication", "deduplication_no_embedding_cache", 2),
        ]
        # O finalista de classificação não usa embedding.
        payload[0]["cold_encoder_load_seconds"] = 0.0
        payload[0]["cold_encoder_load_peak_rss_mb"] = None
        csv_rows = [
            {key: "" if value is None else str(value) for key, value in item.items()}
            for item in payload
        ]
        self.assertEqual(
            validation._validate_performance(
                payload,
                csv_rows,
                config=self.config,
                selected=selected,
            ),
            3,
        )


if __name__ == "__main__":
    unittest.main()
