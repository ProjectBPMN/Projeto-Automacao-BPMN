from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

import numpy as np

from avaliacao.scripts import selecionar_modelos_supervisionados as selection
from avaliacao.scripts import validar_resultados_selecao as result_validation


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = (
    ROOT / "avaliacao" / "config" / "selecao_modelos_supervisionados_v2.json"
)
CLASSIFICATION_CONFIG_PATH = (
    ROOT
    / "avaliacao"
    / "config"
    / "selecao_classificacao_supervisionada_v2_1.json"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SelectionProtocolTests(unittest.TestCase):
    def test_v2_groups_every_source_template_before_resampling(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        selection.validate_protocol_config(config)
        dataset = ROOT / config["dataset"]["path"]
        self.assertEqual(_sha256(dataset), config["dataset"]["sha256"])
        self.assertEqual(
            config["dataset"]["classification_group_field"],
            "source_dependency_group_sha256",
        )
        self.assertEqual(
            config["dataset"]["deduplication_group_field"],
            "source_dependency_group_sha256",
        )
        forbidden = " ".join(config["dataset"]["forbidden_paths"])
        self.assertIn("corpus_v3_teste.jsonl", forbidden)
        self.assertIn("dataset_avaliacao_v2.jsonl", forbidden)

        records = [
            json.loads(line)
            for line in dataset.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        classification = [
            row for row in records if row["dimension"] == "CLASSIFICACAO"
        ]
        dedup_challenges = [
            row
            for row in records
            if row["dimension"] == "DEDUPLICACAO"
            and row.get("pair_role") == "CHALLENGE"
        ]
        class_groups = {
            row["source_dependency_group_sha256"] for row in classification
        }
        dedup_groups = {
            row["source_dependency_group_sha256"] for row in dedup_challenges
        }
        self.assertEqual(len(class_groups), 4 * 32)
        self.assertEqual(len(dedup_groups), 12)

        for rows, label_field in (
            (classification, "expected_classification"),
            (dedup_challenges, "expected_dedup"),
        ):
            labels_by_group: dict[str, set[object]] = {}
            for row in rows:
                labels_by_group.setdefault(
                    row["source_dependency_group_sha256"], set()
                ).add(row[label_field])
            self.assertTrue(
                all(len(labels) == 1 for labels in labels_by_group.values())
            )

    def test_frozen_development_corpus_and_reserved_sets(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        dataset = ROOT / config["dataset"]["path"]

        self.assertTrue(config["development_only"])
        self.assertFalse(config["scientific_result"])
        self.assertFalse(config["confirmatory_eligible"])
        self.assertEqual(_sha256(dataset), config["dataset"]["sha256"])
        self.assertEqual(
            config["dataset"]["classification_group_field"],
            "source_dependency_group_sha256",
        )
        self.assertEqual(
            config["dataset"]["deduplication_group_field"],
            "source_dependency_group_sha256",
        )

    def test_current_protocol_is_the_cli_and_launcher_default(self) -> None:
        self.assertEqual(selection.DEFAULT_CONFIG.resolve(), CONFIG_PATH.resolve())
        self.assertEqual(
            result_validation.DEFAULT_CONFIG.resolve(), CONFIG_PATH.resolve()
        )
        launcher = (
            ROOT / "avaliacao" / "scripts" / "executar_selecao_modelos.ps1"
        ).read_text(encoding="utf-8-sig")
        self.assertIn("selecao_modelos_supervisionados_v2.json", launcher)
        self.assertIn("'--config'", launcher)
        self.assertIn("$LASTEXITCODE", launcher)
        self.assertIn("$ErrorActionPreference = 'Continue'", launcher)
        self.assertIn("validar_viabilidade_protocolo_selecao.py", launcher)

    def test_explicit_classification_scope_is_valid_and_dedup_remains_blocked(self) -> None:
        config = json.loads(CLASSIFICATION_CONFIG_PATH.read_text(encoding="utf-8"))
        selection.validate_protocol_config(config)
        self.assertEqual(config["execution_tasks"], ["classification"])

        invalid = dict(config)
        invalid["execution_tasks"] = ["classification", "unknown"]
        with self.assertRaises(selection.SelectionGuardError):
            selection.validate_protocol_config(invalid)

    def test_dedup_split_feasibility_fails_with_six_groups_per_class(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        labels: list[int] = []
        groups: list[str] = []
        for label in (0, 1):
            for group_index in range(6):
                labels.extend([label] * 10)
                groups.extend([f"label-{label}-group-{group_index}"] * 10)

        with self.assertRaises(selection.SelectionGuardError):
            selection.validate_task_split_feasibility(
                task="deduplication",
                labels=labels,
                groups=groups,
                config=config,
            )

    def test_requested_embeddings_representations_and_classifiers_are_frozen(
        self,
    ) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

        self.assertEqual(
            {item["id"] for item in config["embeddings"]},
            {
                "granite97m",
                "multilingual_e5_small",
                "multilingual_minilm_l12",
            },
        )
        self.assertTrue(
            {"tfidf", "embedding", "hybrid"}.issubset(
                config["representations"]
            )
        )
        self.assertEqual(
            config["representations"]["metadata"]["tasks"],
            ["deduplication"],
        )
        self.assertEqual(
            {item["id"] for item in config["classifiers"]},
            {
                "logistic_regression",
                "decision_tree",
                "linear_svm",
                "mlp",
                "xgboost",
            },
        )
        for embedding in config["embeddings"]:
            self.assertEqual(embedding["dimension"], 384)
            self.assertRegex(embedding["revision"], r"^[0-9a-f]{40}$")
            self.assertRegex(embedding["tree_sha256"], r"^[0-9a-f]{64}$")

        combinations = result_validation.expected_combinations(config)
        by_task = {
            task: sum(
                combination.startswith(f"{task}__")
                for combination in combinations
            )
            for task in ("classification", "deduplication")
        }
        self.assertEqual(by_task, {"classification": 35, "deduplication": 55})
        self.assertEqual(len(combinations), 90)

    def test_grouped_folds_never_mix_narrative_cores(self) -> None:
        labels: list[int] = []
        groups: list[str] = []
        for class_index in range(4):
            for group_index in range(10):
                labels.extend([class_index, class_index])
                groups.extend(
                    [
                        f"class-{class_index}-core-{group_index}",
                        f"class-{class_index}-core-{group_index}",
                    ]
                )

        splits = selection.safe_stratified_group_splits(
            labels,
            groups,
            n_splits=5,
            seed=20260804,
            context="unit-test",
        )

        self.assertEqual(len(splits), 5)
        for train_index, test_index in splits:
            train_groups = set(np.asarray(groups)[train_index])
            test_groups = set(np.asarray(groups)[test_index])
            self.assertFalse(train_groups & test_groups)
            self.assertEqual(set(np.asarray(labels)[test_index]), {0, 1, 2, 3})

    def test_ablation_feature_spaces_are_distinct_and_dimensionally_valid(
        self,
    ) -> None:
        samples = [
            {
                "unit_id": "A",
                "text": "lâmpada queimada na sala 12",
                "embedding": np.ones(384, dtype=np.float32)
                / np.sqrt(384),
            },
            {
                "unit_id": "B",
                "text": "vazamento no banheiro do bloco central",
                "embedding": -np.ones(384, dtype=np.float32)
                / np.sqrt(384),
            },
        ]
        dimensions: dict[str, int] = {}
        for representation, use_tfidf, use_embedding in (
            ("tfidf", True, False),
            ("embedding", False, True),
            ("hybrid", True, True),
        ):
            builder = selection.TextFeatureBuilder(
                use_tfidf=use_tfidf,
                use_embedding=use_embedding,
                embedding_dimension=384,
            )
            matrix = builder.fit_transform(samples)
            dimensions[representation] = matrix.shape[1]
            self.assertEqual(matrix.shape[0], 2)
            self.assertEqual(
                matrix.shape[1],
                len(builder.get_feature_names_out()),
            )

        self.assertEqual(dimensions["embedding"], 384)
        self.assertGreater(dimensions["tfidf"], 0)
        self.assertEqual(
            dimensions["hybrid"],
            dimensions["tfidf"] + dimensions["embedding"],
        )

    def test_classification_policy_blocks_maintenance_as_obra(self) -> None:
        demo = selection.CLASS_LABELS.index("DEMO")
        obra = selection.CLASS_LABELS.index("OBRA")
        sob_demanda = selection.CLASS_LABELS.index("SOB_DEMANDA")
        triagem = selection.CLASS_LABELS.index("TRIAGEM_MANUAL")
        labels = [demo, obra, sob_demanda, triagem]
        probabilities = np.full((4, len(selection.CLASS_LABELS)), 0.05 / 3)
        probabilities[0, :] = 0.11 / 3
        probabilities[0, obra] = 0.89
        probabilities[1, obra] = 0.95
        probabilities[2, sob_demanda] = 0.95
        probabilities[3, triagem] = 0.95

        policy = selection.select_classification_policy(
            probabilities,
            labels,
            max_risk=0.10,
            min_coverage=0.50,
            obra_min_confidence=0.90,
        )

        self.assertTrue(policy["eligible"])
        self.assertEqual(policy["automatic_maintenance_as_obra"], 0)
        self.assertEqual(policy["automatic_non_obra_as_obra"], 0)
        _, covered = selection.apply_classification_policy(
            probabilities,
            policy,
        )
        self.assertFalse(covered[0])
        self.assertTrue(covered[1])
        self.assertTrue(covered[2])
        self.assertFalse(covered[3])

    def test_triagem_manual_never_counts_as_automatic_coverage(self) -> None:
        triage = selection.CLASS_LABELS.index("TRIAGEM_MANUAL")
        demo = selection.CLASS_LABELS.index("DEMO")
        probabilities = np.full((2, len(selection.CLASS_LABELS)), 0.01)
        probabilities[0, triage] = 0.97
        probabilities[1, demo] = 0.97
        policy = {
            "threshold": 0.90,
            "obra_threshold": 0.90,
        }

        predictions, covered = selection.apply_classification_policy(
            probabilities,
            policy,
        )

        self.assertEqual(predictions.tolist(), [triage, demo])
        self.assertEqual(covered.tolist(), [False, True])

    def test_summary_rejects_triagem_marked_as_automatic(self) -> None:
        triage = selection.CLASS_LABELS.index("TRIAGEM_MANUAL")
        demo = selection.CLASS_LABELS.index("DEMO")
        probabilities = np.full((2, len(selection.CLASS_LABELS)), 0.01)
        probabilities[0, triage] = 0.97
        probabilities[1, demo] = 0.97

        with self.assertRaises(selection.SelectionGuardError):
            selection.classification_summary(
                [triage, demo],
                probabilities,
                [triage, demo],
                [True, True],
                ["triage-core", "demo-core"],
                bootstrap_resamples=10,
                seed=20260804,
                confidence_level=0.95,
            )

    def test_dedup_policy_keeps_ambiguous_band_for_human_review(self) -> None:
        policy = {
            "positive_threshold": 0.80,
            "negative_threshold": 0.20,
        }
        probabilities = np.asarray(
            [
                [0.90, 0.10],
                [0.50, 0.50],
                [0.10, 0.90],
            ],
            dtype=np.float64,
        )

        decisions, covered = selection.apply_dedup_policy(
            probabilities,
            policy,
        )

        np.testing.assert_array_equal(decisions, [0, -1, 1])
        np.testing.assert_array_equal(covered, [True, False, True])

    def test_zero_coverage_classifier_cannot_win(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        result = {
            "combination_id": "classification__embedding__x__linear_svm",
            "task": "classification",
            "representation": "embedding",
            "embedding": "x",
            "classifier": "linear_svm",
            "status": "COMPLETED_DEVELOPMENT_OOF",
            "elapsed_seconds": 1.0,
            "folds": [],
            "metrics": {
                "automatic_non_obra_as_obra": 0,
                "automatic_risk": None,
                "automatic_coverage": 0.0,
                "macro_f1": 1.0,
                "obra_recall": 1.0,
                "log_loss": 0.01,
            },
        }

        ranking, winner, provisional = selection.selection_rank(
            [result],
            task="classification",
            policy=config["operating_policy"],
        )

        self.assertFalse(ranking[0]["eligible"])
        self.assertIn(
            "classification_coverage",
            ranking[0]["exclusion_reasons"],
        )
        self.assertIsNone(winner)
        self.assertIsNone(provisional)

    def test_point_candidate_is_explicitly_underpowered(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        result = {
            "combination_id": "classification__tfidf__none__linear_svm",
            "task": "classification",
            "representation": "tfidf",
            "embedding": None,
            "classifier": "linear_svm",
            "status": "COMPLETED_DEVELOPMENT_OOF",
            "elapsed_seconds": 1.0,
            "folds": [],
            "metrics": {
                "automatic_non_obra_as_obra": 0,
                "automatic_non_obra_as_obra_group_rate_upper": 0.05,
                "automatic_risk": 0.02,
                "automatic_coverage": 0.60,
                "macro_f1": 0.85,
                "obra_recall": 0.90,
                "log_loss": 0.30,
                "confidence_intervals_group_bootstrap": {
                    "selective_risk": [0.00, 0.05],
                    "coverage": [0.55, 0.65],
                },
            },
        }

        ranking, winner, provisional = selection.selection_rank(
            [result], task="classification", policy=config["operating_policy"]
        )

        self.assertIsNone(winner)
        self.assertEqual(provisional, result)
        self.assertEqual(ranking[0]["evidence_status"], "UNDERPOWERED")
        self.assertFalse(ranking[0]["confidence_qualified"])
        self.assertTrue(ranking[0]["provisional_point_eligible"])

    def test_paired_objective_detects_unsafe_automatic_negative(self) -> None:
        def row(
            unit_id: str,
            group: str,
            gold: str,
            prediction: str,
            semantic: str,
            covered: bool,
        ) -> dict[str, object]:
            return {
                "unit_id": unit_id,
                "group": group,
                "fold": 0 if group == "g1" else 1,
                "gold": gold,
                "prediction": prediction,
                "semantic_prediction": semantic,
                "covered": covered,
            }

        baseline_id = "deduplication__hybrid__granite97m__logistic_regression"
        candidate_id = "deduplication__tfidf__none__logistic_regression"
        common = [
            row("u2", "g2", "NAO_DUPLICADO", "NAO_DUPLICADO", "NAO_DUPLICADO", True),
        ]
        baseline = {
            "combination_id": baseline_id,
            "task": "deduplication",
            "status": "COMPLETED_DEVELOPMENT_OOF",
            "predictions": [
                row("u1", "g1", "DUPLICADO", "ABSTENCAO", "DUPLICADO", False),
                *common,
            ],
        }
        candidate = {
            "combination_id": candidate_id,
            "task": "deduplication",
            "status": "COMPLETED_DEVELOPMENT_OOF",
            "predictions": [
                row("u1", "g1", "DUPLICADO", "NAO_DUPLICADO", "DUPLICADO", True),
                *common,
            ],
        }

        comparisons = selection.paired_objective_rows(
            [baseline, candidate],
            baseline_ids={"deduplication": baseline_id, "classification": "missing"},
            comparison_candidates={
                "deduplication": {candidate_id: "unsafe_negative"},
                "classification": {},
            },
            resamples=100,
            confidence_level=0.95,
            seed=20260804,
            false_negative_cost=5.0,
            false_positive_cost=1.0,
        )
        by_metric = {item["metric"]: item for item in comparisons}

        self.assertEqual(by_metric["semantic_accuracy"]["difference_candidate_minus_baseline"], 0.0)
        self.assertGreater(
            by_metric["weighted_error_fn5_fp1_per_record"][
                "difference_candidate_minus_baseline"
            ],
            0.0,
        )
        self.assertGreater(
            by_metric["automatic_false_negative_rate"][
                "difference_candidate_minus_baseline"
            ],
            0.0,
        )

    def test_calibration_split_enforces_independent_groups_per_class(self) -> None:
        labels: list[int] = []
        groups: list[str] = []
        for class_index in range(4):
            for group_index in range(12):
                labels.extend([class_index, class_index])
                groups.extend(
                    [
                        f"class-{class_index}-group-{group_index}",
                        f"class-{class_index}-group-{group_index}",
                    ]
                )
        indices = np.arange(len(labels))

        fit_index, calibration_index, audit = selection.fit_calibration_split(
            indices,
            labels,
            groups,
            fraction=0.40,
            seed=20260804,
            attempts=512,
            context="unit-test",
            min_fit_groups_per_class=5,
            min_calibration_groups_per_class=4,
        )

        self.assertFalse(
            set(np.asarray(groups)[fit_index])
            & set(np.asarray(groups)[calibration_index])
        )
        self.assertGreaterEqual(
            min(audit["fit_group_counts_by_label"].values()), 5
        )
        self.assertGreaterEqual(
            min(audit["calibration_group_counts_by_label"].values()), 4
        )

    def test_group_label_purity_rejects_mixed_group(self) -> None:
        with self.assertRaises(selection.SelectionGuardError):
            selection.validate_group_label_purity(
                [0, 1], ["same-core", "same-core"], context="unit-test"
            )

    def test_realistic_imbalanced_group_support_satisfies_calibration_guards(
        self,
    ) -> None:
        labels: list[int] = []
        groups: list[str] = []
        for class_index, group_count in enumerate([28, 32, 32, 13]):
            for group_index in range(group_count):
                labels.extend([class_index, class_index])
                groups.extend(
                    [
                        f"class-{class_index}-group-{group_index}",
                        f"class-{class_index}-group-{group_index}",
                    ]
                )

        outer = selection.safe_stratified_group_splits(
            labels,
            groups,
            n_splits=5,
            seed=20260804,
            context="realistic-support",
        )
        for fold, (outer_train, _) in enumerate(outer):
            _, calibration_index, audit = selection.fit_calibration_split(
                outer_train,
                labels,
                groups,
                fraction=0.40,
                seed=20260804 + 1000 * (fold + 1),
                attempts=512,
                context=f"realistic-support-{fold}",
                min_fit_groups_per_class=5,
                min_calibration_groups_per_class=4,
            )
            self.assertGreaterEqual(
                min(audit["fit_group_counts_by_label"].values()), 5
            )
            self.assertGreaterEqual(
                min(audit["calibration_group_counts_by_label"].values()), 4
            )
            calibration_labels = np.asarray(labels)[calibration_index]
            calibration_groups = np.asarray(groups)[calibration_index]
            splits = selection.safe_stratified_group_splits(
                calibration_labels,
                calibration_groups,
                n_splits=2,
                seed=20260804 + 20000 + fold,
                context=f"realistic-calibration-{fold}",
                min_train_groups_per_class=2,
                min_test_groups_per_class=2,
            )
            self.assertEqual(len(splits), 2)

    def test_metadata_only_pair_representation_is_explicit_diagnostic(self) -> None:
        pair = {
            "unit_id": "P1",
            "current": {
                "location": "Sala 1",
                "category": "Elétrica",
                "requester": "a@example.org",
                "urgency": 2,
                "impact": 3,
            },
            "reference": {
                "location": "Sala 1",
                "category": "Elétrica",
                "requester": "b@example.org",
                "urgency": 1,
                "impact": 3,
            },
            "current_text": "lâmpada queimada",
            "reference_text": "sem iluminação",
            "label_name": "DUPLICADO",
        }
        builder = selection.PairFeatureBuilder(
            use_tfidf=False,
            use_embedding=False,
            use_metadata=True,
        )

        matrix = builder.fit_transform([pair])

        self.assertEqual(matrix.shape, (1, 7))
        self.assertEqual(
            builder.get_feature_names_out().tolist(),
            [
                f"metadata__{name}"
                for name in selection.STRUCTURED_PAIR_FEATURES
            ],
        )

    def test_deduplication_ablation_spaces_are_truly_isolated(self) -> None:
        samples = [
            {
                "unit_id": "P1",
                "current": {
                    "location": "Sala 1",
                    "category": "Elétrica",
                    "requester": "a@example.org",
                    "urgency": 2,
                    "impact": 3,
                },
                "reference": {
                    "location": "Sala 1",
                    "category": "Elétrica",
                    "requester": "b@example.org",
                    "urgency": 1,
                    "impact": 3,
                },
                "current_text": "lâmpada queimada na sala um",
                "reference_text": "sala um sem iluminação",
                "current_embedding": np.ones(384, dtype=np.float32) / np.sqrt(384),
                "reference_embedding": -np.ones(384, dtype=np.float32) / np.sqrt(384),
                "label_name": "DUPLICADO",
            },
            {
                "unit_id": "P2",
                "current": {
                    "location": "Bloco B",
                    "category": "Hidráulica",
                    "requester": "c@example.org",
                    "urgency": 3,
                    "impact": 2,
                },
                "reference": {
                    "location": "Bloco C",
                    "category": "Civil",
                    "requester": "d@example.org",
                    "urgency": 1,
                    "impact": 1,
                },
                "current_text": "torneira vazando no bloco b",
                "reference_text": "trinca na parede do bloco c",
                "current_embedding": -np.ones(384, dtype=np.float32) / np.sqrt(384),
                "reference_embedding": np.ones(384, dtype=np.float32) / np.sqrt(384),
                "label_name": "NAO_DUPLICADO",
            },
        ]
        builders = {
            "tfidf": selection.PairFeatureBuilder(
                use_tfidf=True, use_embedding=False, use_metadata=False
            ),
            "embedding": selection.PairFeatureBuilder(
                use_tfidf=False, use_embedding=True, use_metadata=False
            ),
            "hybrid": selection.PairFeatureBuilder(
                use_tfidf=True, use_embedding=True, use_metadata=False
            ),
            "metadata": selection.PairFeatureBuilder(
                use_tfidf=False, use_embedding=False, use_metadata=True
            ),
            "hybrid_metadata": selection.PairFeatureBuilder(
                use_tfidf=True, use_embedding=True, use_metadata=True
            ),
        }
        matrices = {
            name: builder.fit_transform(samples)
            for name, builder in builders.items()
        }
        self.assertEqual(matrices["embedding"].shape[1], 769)
        self.assertEqual(matrices["metadata"].shape[1], 7)
        self.assertEqual(
            matrices["hybrid"].shape[1],
            matrices["tfidf"].shape[1] + matrices["embedding"].shape[1],
        )
        self.assertEqual(
            matrices["hybrid_metadata"].shape[1],
            matrices["hybrid"].shape[1] + 7,
        )
        for name in ("tfidf", "embedding", "hybrid"):
            self.assertFalse(
                any(
                    feature.startswith("metadata__")
                    for feature in builders[name].get_feature_names_out()
                )
            )

    def test_classification_ranking_uses_protocol_metrics_not_interval_magnitude(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

        def result(combination_id: str, macro_f1: float, critical_upper: float) -> dict:
            return {
                "combination_id": combination_id,
                "task": "classification",
                "representation": "tfidf",
                "embedding": None,
                "classifier": "logistic_regression",
                "status": "COMPLETED_DEVELOPMENT_OOF",
                "elapsed_seconds": 1.0,
                "folds": [{"fit_seconds": 2.0}],
                "metrics": {
                    "automatic_non_obra_as_obra": 0,
                    "automatic_non_obra_as_obra_group_rate_upper": critical_upper,
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

        better_f1 = result("classification__tfidf__none__a", 0.91, 0.019)
        prettier_bound = result("classification__tfidf__none__b", 0.90, 0.001)
        ranking, winner, _ = selection.selection_rank(
            [prettier_bound, better_f1],
            task="classification",
            policy=config["operating_policy"],
        )
        self.assertEqual(ranking[0]["combination_id"], better_f1["combination_id"])
        self.assertIs(winner, better_f1)

    def test_ranking_uses_mean_fold_fit_and_deterministic_identifier(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

        def result(combination_id: str, elapsed: float, fit: float) -> dict:
            return {
                "combination_id": combination_id,
                "task": "classification",
                "representation": "tfidf",
                "embedding": None,
                "classifier": "logistic_regression",
                "status": "COMPLETED_DEVELOPMENT_OOF",
                "elapsed_seconds": elapsed,
                "folds": [{"fit_seconds": fit}],
                "metrics": {
                    "automatic_non_obra_as_obra": 0,
                    "automatic_non_obra_as_obra_group_rate_upper": 0.01,
                    "automatic_risk": 0.02,
                    "automatic_coverage": 0.70,
                    "macro_f1": 0.90,
                    "obra_recall": 0.90,
                    "log_loss": 0.30,
                    "confidence_intervals_group_bootstrap": {
                        "selective_risk": [0.0, 0.05],
                        "coverage": [0.60, 0.80],
                    },
                },
            }

        fast_fit = result("classification__tfidf__none__z", 100.0, 1.0)
        fast_elapsed = result("classification__tfidf__none__a", 1.0, 10.0)
        ranking, _, _ = selection.selection_rank(
            [fast_elapsed, fast_fit],
            task="classification",
            policy=config["operating_policy"],
        )
        self.assertEqual(ranking[0]["combination_id"], fast_fit["combination_id"])
        fast_elapsed["folds"] = [{"fit_seconds": 1.0}]
        ranking, _, _ = selection.selection_rank(
            [fast_fit, fast_elapsed],
            task="classification",
            policy=config["operating_policy"],
        )
        self.assertEqual(ranking[0]["combination_id"], fast_elapsed["combination_id"])

    def test_dedup_ranking_uses_cost_not_confidence_bound_magnitude(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

        def result(combination_id: str, cost: float, bound: float) -> dict:
            return {
                "combination_id": combination_id,
                "task": "deduplication",
                "representation": "tfidf",
                "embedding": None,
                "classifier": "logistic_regression",
                "status": "COMPLETED_DEVELOPMENT_OOF",
                "elapsed_seconds": 1.0,
                "folds": [{"fit_seconds": 1.0}],
                "metrics": {
                    "fn": 0,
                    "fp": int(cost),
                    "false_negative_group_rate_upper": bound,
                    "false_positive_group_rate_upper": min(bound, 0.049),
                    "automatic_false_negative_rate": 0.0,
                    "automatic_false_positive_rate": 0.01,
                    "negative_predictive_value": 1.0,
                    "precision": 0.99,
                    "decision_coverage": 0.80,
                    "full_automation_coverage": 0.60,
                    "weighted_error_fn5_fp1_total": cost,
                    "operating_confidence_intervals_group_bootstrap": {
                        "false_negative_rate": [0.0, bound],
                        "false_positive_rate": [0.0, min(bound, 0.049)],
                        "negative_predictive_value": [0.99, 1.0],
                        "precision": [0.95, 1.0],
                        "decision_coverage": [0.60, 0.90],
                    },
                },
            }

        lower_cost = result("deduplication__tfidf__none__a", 0.0, 0.019)
        prettier_bound = result("deduplication__tfidf__none__b", 1.0, 0.001)
        ranking, winner, _ = selection.selection_rank(
            [prettier_bound, lower_cost],
            task="deduplication",
            policy=config["operating_policy"],
        )
        self.assertEqual(ranking[0]["combination_id"], lower_cost["combination_id"])
        self.assertIs(winner, lower_cost)


if __name__ == "__main__":
    unittest.main()
