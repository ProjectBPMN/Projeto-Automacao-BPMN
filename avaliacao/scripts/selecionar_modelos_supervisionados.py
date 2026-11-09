from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import json
import math
import os
import platform
import re
import statistics
import sys
import threading
import time
import warnings
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import joblib
import numpy as np
import psutil
import scipy
from scipy import sparse
from scipy.stats import beta, wilcoxon
from sklearn import __version__ as sklearn_version
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.calibration import CalibratedClassifierCV
from sklearn.exceptions import ConvergenceWarning
from sklearn.frozen import FrozenEstimator
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    classification_report,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_recall_fscore_support,
    roc_auc_score,
)
from sklearn.model_selection import (
    GridSearchCV,
    GroupShuffleSplit,
    StratifiedGroupKFold,
)
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC
from sklearn.tree import DecisionTreeClassifier
from sklearn.utils.class_weight import compute_sample_weight
from xgboost import XGBClassifier


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from avaliacao.scripts import treinar_modelo_local as training  # noqa: E402


SCHEMA = "projeto-ic-selecao-supervisionada-resultados-v1"
CLASS_LABELS = list(training.CLASS_LABELS)
DEDUP_LABELS = ["NAO_DUPLICADO", "DUPLICADO"]
ALL_TASKS = ("classification", "deduplication")
STRUCTURED_PAIR_FEATURES = [
    "location_equal",
    "category_equal",
    "requester_equal",
    "both_locations_present",
    "both_categories_present",
    "urgency_distance",
    "impact_distance",
]


class SelectionGuardError(ValueError):
    pass


EXPECTED_CLASSIFICATION_SELECTION = [
    "automatic_non_obra_as_obra_equals_zero",
    "selective_risk_at_most_configured_limit",
    "automatic_coverage_at_least_configured_limit",
    "critical_group_upper_at_most_configured_limit",
    "selective_risk_upper_at_most_configured_limit",
    "automatic_coverage_lower_at_least_configured_limit",
    "highest_macro_f1",
    "highest_obra_recall",
    "highest_automatic_coverage",
    "lowest_log_loss",
    "lowest_mean_fit_seconds",
]
EXPECTED_DEDUPLICATION_SELECTION = [
    "lowest_automatic_false_negatives",
    "false_negative_group_upper_at_most_configured_limit",
    "false_positive_group_upper_at_most_configured_limit",
    "false_negative_rate_upper_at_most_configured_limit",
    "false_positive_rate_upper_at_most_configured_limit",
    "negative_predictive_value_lower_at_least_configured_limit",
    "precision_lower_at_least_configured_limit",
    "decision_coverage_lower_at_least_configured_limit",
    "lowest_weighted_error_fn5_fp1",
    "highest_negative_predictive_value",
    "highest_precision",
    "highest_full_automation_coverage",
    "highest_decision_coverage",
    "lowest_mean_fit_seconds",
]


def classifier_spec(
    config: dict[str, Any],
    classifier_id: str,
) -> dict[str, Any]:
    matches = [
        item
        for item in config.get("classifiers", [])
        if item.get("id") == classifier_id
    ]
    if len(matches) != 1:
        raise SelectionGuardError(
            f"Configuração ausente ou duplicada para {classifier_id}"
        )
    return matches[0]


def validate_protocol_config(config: dict[str, Any]) -> None:
    if config.get("schema") != "projeto-ic-selecao-modelos-supervisionados-v1":
        raise SelectionGuardError("Schema do protocolo de seleção inválido")
    if not config.get("development_only"):
        raise SelectionGuardError("Seleção deve permanecer development_only")
    protocol_version = str(config.get("protocol_version", "") or "")
    try:
        protocol_major = int(protocol_version.split(".", 1)[0])
    except ValueError as exc:
        raise SelectionGuardError("protocol_version inválida") from exc
    dataset = config.get("dataset", {})
    if not isinstance(dataset.get("allow_mixed_label_source_groups", False), bool):
        raise SelectionGuardError("allow_mixed_label_source_groups deve ser booleano")
    if dataset.get("allow_mixed_label_source_groups", False) and protocol_major < 3:
        raise SelectionGuardError("Grupos-fonte multirrótulo exigem protocolo prospectivo V3")
    expected_group_field = (
        "source_dependency_group_sha256"
        if protocol_major >= 2
        else "narrative_core_sha256"
    )
    expected_dedup_group_field = (
        "source_dependency_group_sha256"
        if protocol_major >= 2
        else "episode_id"
    )
    if dataset.get("classification_group_field") != expected_group_field:
        raise SelectionGuardError(
            "Agrupamento de classificação incompatível com a versão do protocolo: "
            f"esperado {expected_group_field}"
        )
    if dataset.get("deduplication_group_field") != expected_dedup_group_field:
        raise SelectionGuardError(
            "Agrupamento de deduplicação incompatível com a versão do protocolo: "
            f"esperado {expected_dedup_group_field}"
        )
    representations = config.get("representations", {})
    expected_representations = {
        "tfidf": (True, False, False, {"classification", "deduplication"}),
        "embedding": (False, True, False, {"classification", "deduplication"}),
        "hybrid": (True, True, False, {"classification", "deduplication"}),
        "metadata": (False, False, True, {"deduplication"}),
        "hybrid_metadata": (True, True, True, {"deduplication"}),
    }
    if set(representations) != set(expected_representations):
        raise SelectionGuardError("Conjunto de representações divergente")
    for name, (tfidf, embedding, metadata, tasks) in expected_representations.items():
        observed = representations[name]
        if (
            bool(observed.get("uses_tfidf")) != tfidf
            or bool(observed.get("uses_embedding")) != embedding
            or bool(observed.get("uses_metadata")) != metadata
            or set(observed.get("tasks", [])) != tasks
        ):
            raise SelectionGuardError(f"Definição divergente para {name}")
    expected_classifiers = {
        "logistic_regression",
        "decision_tree",
        "linear_svm",
        "mlp",
        "xgboost",
    }
    if {item.get("id") for item in config.get("classifiers", [])} != expected_classifiers:
        raise SelectionGuardError("Conjunto de classificadores divergente")
    if classifier_spec(config, "mlp").get("early_stopping") is not False:
        raise SelectionGuardError(
            "MLP deve desativar early_stopping para preservar grupos"
        )
    execution_tasks = config.get("execution_tasks", list(ALL_TASKS))
    if (
        not isinstance(execution_tasks, list)
        or not execution_tasks
        or len(set(execution_tasks)) != len(execution_tasks)
        or set(execution_tasks) - set(ALL_TASKS)
    ):
        raise SelectionGuardError("Escopo execution_tasks inválido")
    cv = config.get("cross_validation", {})
    calibration_methods = {
        item.get("calibration") for item in config.get("classifiers", [])
    }
    if (
        cv.get("outer_strategy") != "StratifiedGroupKFold"
        or cv.get("inner_strategy") != "StratifiedGroupKFold"
        or not 0.0 < float(cv.get("confidence_level", 0.0)) < 1.0
        or not 0.0 < float(cv.get("calibration_fraction", 0.0)) < 1.0
        or int(cv.get("fit_min_groups_per_class", 0)) < 2
        or int(cv.get("calibration_min_groups_per_class", 0)) < 2
        or int(cv.get("calibration_fold_min_groups_per_class", 0)) < 1
        or cv.get("calibration_method") not in {"sigmoid", "isotonic"}
        or calibration_methods != {cv.get("calibration_method")}
    ):
        raise SelectionGuardError("Desenho de validação cruzada inválido")
    selection = config.get("selection_rule", {})
    if (
        selection.get("type") != "hierarchical_no_composite_score"
        or selection.get("evidence_policy")
        != "strict_confidence_qualified_else_provisional_point_selection"
        or selection.get("classification") != EXPECTED_CLASSIFICATION_SELECTION
        or selection.get("deduplication") != EXPECTED_DEDUPLICATION_SELECTION
        or selection.get("tie_policy") != "deterministic_lexicographic_only"
    ):
        raise SelectionGuardError("Regra hierárquica de seleção divergente")
    xai = config.get("xai", {})
    if (
        xai.get("enabled") is not True
        or int(xai.get("finalists_per_task", 0)) < 1
        or float(xai.get("max_absolute_additivity_residual", 0.0)) <= 0.0
        or xai.get("failure_policy") != "fail_full_run"
    ):
        raise SelectionGuardError("Política XAI inválida")
    performance = config.get("performance_benchmark", {})
    if (
        performance.get("enabled") is not True
        or int(performance.get("warmup_records", 0)) < 1
        or int(performance.get("measured_records_per_task", 0)) < 5
        or performance.get("failure_policy") != "fail_full_run"
        or set(performance.get("scenarios", []))
        != {
            "classification_raw_text",
            "deduplication_raw_text_tfidf",
            "deduplication_reference_embedding_cached",
            "deduplication_no_embedding_cache",
        }
    ):
        raise SelectionGuardError("Benchmark de desempenho inválido")
    embedding_ids = [item["id"] for item in config["embeddings"]]
    classifier_ids = [item["id"] for item in config["classifiers"]]
    expected_combinations: set[str] = set()
    for representation, specification in representations.items():
        candidate_embeddings: list[str | None] = (
            embedding_ids if specification["uses_embedding"] else [None]
        )
        for embedding_id in candidate_embeddings:
            for task in specification["tasks"]:
                for classifier_id in classifier_ids:
                    expected_combinations.add(
                        "__".join(
                            [
                                task,
                                representation,
                                embedding_id or "none",
                                classifier_id,
                            ]
                        )
                    )
    paired = config.get("paired_comparisons", {})
    if set(paired) != {"classification", "deduplication"}:
        raise SelectionGuardError("Contrastes pareados ausentes")
    for task, comparisons in paired.items():
        comparison_ids = [item.get("id") for item in comparisons]
        baselines = {item.get("baseline") for item in comparisons}
        expected_comparison_count = (
            4 if protocol_major >= 3 else (8 if task == "classification" else 10)
        )
        if (
            len(comparisons) != expected_comparison_count
            or len(set(comparison_ids)) != len(comparisons)
            or len(baselines) != 1
        ):
            raise SelectionGuardError(
                f"Contrastes pareados inválidos para {task}"
            )
        for comparison in comparisons:
            baseline = comparison.get("baseline")
            candidate = comparison.get("candidate")
            if (
                baseline not in expected_combinations
                or candidate not in expected_combinations
                or baseline == candidate
                or not str(baseline).startswith(f"{task}__")
                or not str(candidate).startswith(f"{task}__")
            ):
                raise SelectionGuardError(
                    f"Contraste pareado divergente: {comparison}"
                )
    if protocol_major >= 3:
        execution_ids = config.get("execution_combination_ids")
        if (
            not isinstance(execution_ids, list)
            or len(execution_ids) != 10
            or len(set(execution_ids)) != len(execution_ids)
            or set(execution_ids) - expected_combinations
        ):
            raise SelectionGuardError("Subconjunto V3 de dez combinações inválido")
        for task in ALL_TASKS:
            task_ids = [value for value in execution_ids if value.startswith(f"{task}__")]
            if len(task_ids) != 5 or {
                value.rsplit("__", 1)[-1] for value in task_ids
            } != expected_classifiers:
                raise SelectionGuardError(
                    f"V3 deve comparar os cinco classificadores em {task}"
                )


def implementation_manifest(
    *,
    config_path: Path,
    protocol_sha256: str,
    packages: dict[str, Any],
) -> dict[str, Any]:
    source_paths = {
        "selection_executor": Path(__file__).resolve(),
        "training_helper": Path(training.__file__).resolve(),
        "benchmark_requirements": (
            PROJECT_ROOT / "local_ai" / "requirements-benchmark.txt"
        ).resolve(),
        "hybrid_requirements": (
            PROJECT_ROOT / "local_ai" / "requirements-hybrid.txt"
        ).resolve(),
        "granite_requirements": (
            PROJECT_ROOT / "local_ai" / "requirements-granite.txt"
        ).resolve(),
    }
    hashes = {
        name: {
            "path": str(path),
            "sha256": sha256_file(path),
        }
        for name, path in source_paths.items()
    }
    fingerprint_payload = {
        "protocol_sha256": protocol_sha256,
        "config_path": str(config_path),
        "source_hashes": {
            name: item["sha256"] for name, item in hashes.items()
        },
        "packages": packages,
    }
    return {
        "source_files": hashes,
        "packages": packages,
        "run_fingerprint": canonical_sha256(fingerprint_payload),
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_sha256(path: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    files = sorted(
        item
        for item in path.rglob("*")
        if item.is_file() and ".cache" not in item.relative_to(path).parts
    )
    total_bytes = 0
    for item in files:
        relative = item.relative_to(path).as_posix().encode("utf-8")
        file_digest = bytes.fromhex(sha256_file(item))
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(file_digest)
        total_bytes += item.stat().st_size
    return digest.hexdigest(), len(files), total_bytes


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"Objeto não serializável: {type(value).__name__}")


def write_json(path: Path, value: Any) -> None:
    def stamp(item: Any) -> Any:
        if not isinstance(item, dict):
            return item
        stamped = dict(item)
        stamped.setdefault("scientific_result", False)
        stamped.setdefault("development_only", True)
        stamped.setdefault("confirmatory_eligible", False)
        stamped.setdefault("evidence_basis", "SYNTHETIC_PROXY_LABELS")
        return stamped

    rendered_value = [stamp(item) for item in value] if isinstance(value, list) else stamp(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(rendered_value, ensure_ascii=False, indent=2, default=_json_default)
        + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    rows = [
        {
            **row,
            "scientific_result": False,
            "development_only": True,
            "confirmatory_eligible": False,
            "evidence_basis": "SYNTHETIC_PROXY_LABELS",
        }
        for row in rows
    ]
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: canonical_json(value)
                    if isinstance(value, (dict, list, tuple))
                    else value
                    for key, value in row.items()
                }
            )


def percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def subset(values: Sequence[Any], indices: Sequence[int]) -> list[Any]:
    return [values[int(index)] for index in indices]


def label_counts(labels: Sequence[int]) -> dict[str, int]:
    return {str(key): int(value) for key, value in sorted(Counter(labels).items())}


def group_counts_by_label(
    labels: Sequence[int], groups: Sequence[str]
) -> dict[str, int]:
    labels_array = np.asarray(labels, dtype=int)
    groups_array = np.asarray(groups, dtype=object)
    return {
        str(label): len(set(groups_array[labels_array == label].tolist()))
        for label in sorted(set(labels_array.tolist()))
    }


def validate_group_label_purity(
    labels: Sequence[int], groups: Sequence[str], *, context: str
) -> None:
    labels_by_group: dict[str, set[int]] = defaultdict(set)
    for label, group in zip(labels, groups):
        labels_by_group[str(group)].add(int(label))
    mixed = {
        group: sorted(values)
        for group, values in labels_by_group.items()
        if len(values) != 1
    }
    if mixed:
        raise SelectionGuardError(
            f"{context}: grupos associados a mais de um rótulo: "
            f"{list(mixed.items())[:3]}"
        )


def validate_no_group_overlap(
    train_indices: Sequence[int],
    test_indices: Sequence[int],
    groups: Sequence[str],
    *,
    context: str,
) -> None:
    group_array = np.asarray(groups, dtype=object)
    overlap = set(group_array[list(train_indices)]) & set(
        group_array[list(test_indices)]
    )
    if overlap:
        raise SelectionGuardError(
            f"{context}: vazamento entre grupos: {sorted(overlap)[:3]}"
        )


def safe_stratified_group_splits(
    labels: Sequence[int],
    groups: Sequence[str],
    *,
    n_splits: int,
    seed: int,
    context: str,
    min_train_groups_per_class: int = 1,
    min_test_groups_per_class: int = 1,
) -> list[tuple[np.ndarray, np.ndarray]]:
    labels_array = np.asarray(labels, dtype=int)
    groups_array = np.asarray(groups, dtype=object)
    expected = set(labels_array.tolist())
    for offset in range(128):
        splitter = StratifiedGroupKFold(
            n_splits=n_splits,
            shuffle=True,
            random_state=seed + offset,
        )
        splits = list(
            splitter.split(
                np.zeros(len(labels_array), dtype=np.int8),
                labels_array,
                groups_array,
            )
        )
        valid = True
        for fold, (train_index, test_index) in enumerate(splits):
            validate_no_group_overlap(
                train_index,
                test_index,
                groups,
                context=f"{context}/fold-{fold}",
            )
            if (
                set(labels_array[train_index].tolist()) != expected
                or set(labels_array[test_index].tolist()) != expected
            ):
                valid = False
                break
            train_group_counts = group_counts_by_label(
                labels_array[train_index], groups_array[train_index]
            )
            test_group_counts = group_counts_by_label(
                labels_array[test_index], groups_array[test_index]
            )
            if (
                min(train_group_counts.values(), default=0)
                < min_train_groups_per_class
                or min(test_group_counts.values(), default=0)
                < min_test_groups_per_class
            ):
                valid = False
                break
        if valid:
            return splits
    raise SelectionGuardError(
        f"{context}: não foi possível produzir {n_splits} dobras com todas as classes"
    )


def fit_calibration_split(
    indices: Sequence[int],
    labels: Sequence[int],
    groups: Sequence[str],
    *,
    fraction: float,
    seed: int,
    attempts: int,
    context: str,
    min_fit_groups_per_class: int,
    min_calibration_groups_per_class: int,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    local_indices = np.asarray(indices, dtype=int)
    local_labels = np.asarray(labels, dtype=int)[local_indices]
    local_groups = np.asarray(groups, dtype=object)[local_indices]
    all_classes = set(local_labels.tolist())
    best: tuple[float, np.ndarray, np.ndarray] | None = None
    global_distribution = np.bincount(
        local_labels, minlength=max(all_classes) + 1
    ).astype(np.float64)
    global_distribution /= global_distribution.sum()
    for offset in range(attempts):
        splitter = GroupShuffleSplit(
            n_splits=1,
            test_size=fraction,
            random_state=seed + offset,
        )
        fit_local, calibration_local = next(
            splitter.split(local_indices, local_labels, local_groups)
        )
        fit_labels = local_labels[fit_local]
        calibration_labels = local_labels[calibration_local]
        if (
            set(fit_labels.tolist()) != all_classes
            or set(calibration_labels.tolist()) != all_classes
        ):
            continue
        if min(Counter(calibration_labels.tolist()).values(), default=0) < 4:
            continue
        fit_groups = set(local_groups[fit_local])
        calibration_groups = set(local_groups[calibration_local])
        if fit_groups & calibration_groups:
            continue
        fit_group_counts = group_counts_by_label(
            fit_labels, local_groups[fit_local]
        )
        calibration_group_counts = group_counts_by_label(
            calibration_labels, local_groups[calibration_local]
        )
        if (
            min(fit_group_counts.values(), default=0)
            < min_fit_groups_per_class
            or min(calibration_group_counts.values(), default=0)
            < min_calibration_groups_per_class
        ):
            continue
        distribution = np.bincount(
            calibration_labels, minlength=len(global_distribution)
        ).astype(np.float64)
        distribution /= distribution.sum()
        divergence = float(np.sum(np.abs(distribution - global_distribution)))
        size_error = abs(len(calibration_local) / len(local_indices) - fraction)
        score = divergence + size_error
        if best is None or score < best[0]:
            best = (score, fit_local, calibration_local)
    if best is None:
        raise SelectionGuardError(
            f"{context}: não foi possível separar ajuste e calibração por grupo"
        )
    fit_indices = local_indices[best[1]]
    calibration_indices = local_indices[best[2]]
    validate_no_group_overlap(
        fit_indices,
        calibration_indices,
        groups,
        context=f"{context}/fit-calibration",
    )
    return fit_indices, calibration_indices, {
        "fit_records": len(fit_indices),
        "calibration_records": len(calibration_indices),
        "fit_groups": len(set(np.asarray(groups, dtype=object)[fit_indices])),
        "calibration_groups": len(
            set(np.asarray(groups, dtype=object)[calibration_indices])
        ),
        "fit_label_counts": label_counts(np.asarray(labels)[fit_indices]),
        "calibration_label_counts": label_counts(
            np.asarray(labels)[calibration_indices]
        ),
        "fit_group_counts_by_label": group_counts_by_label(
            np.asarray(labels)[fit_indices],
            np.asarray(groups, dtype=object)[fit_indices],
        ),
        "calibration_group_counts_by_label": group_counts_by_label(
            np.asarray(labels)[calibration_indices],
            np.asarray(groups, dtype=object)[calibration_indices],
        ),
        "group_overlap": 0,
        "balance_score": best[0],
    }


def validate_task_split_feasibility(
    *,
    task: str,
    labels: Sequence[int],
    groups: Sequence[str],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Executa todas as divisões exigidas antes de qualquer ajuste caro."""
    cv = config["cross_validation"]
    outer_splits = safe_stratified_group_splits(
        labels,
        groups,
        n_splits=int(cv["outer_folds"]),
        seed=int(cv["outer_seed"]),
        context=f"preflight/{task}/outer",
    )
    audit: list[dict[str, Any]] = []
    for fold, (outer_train, outer_test) in enumerate(outer_splits):
        fit_index, calibration_index, split_audit = fit_calibration_split(
            outer_train,
            labels,
            groups,
            fraction=float(cv["calibration_fraction"]),
            seed=int(cv["outer_seed"]) + 1000 * (fold + 1),
            attempts=int(cv["calibration_search_attempts"]),
            context=f"preflight/{task}/outer-{fold}",
            min_fit_groups_per_class=int(cv["fit_min_groups_per_class"]),
            min_calibration_groups_per_class=int(
                cv["calibration_min_groups_per_class"]
            ),
        )
        safe_stratified_group_splits(
            np.asarray(labels)[fit_index],
            np.asarray(groups, dtype=object)[fit_index],
            n_splits=int(cv["inner_folds"]),
            seed=int(cv["outer_seed"]) + 10000 + fold,
            context=f"preflight/{task}/inner-{fold}",
        )
        safe_stratified_group_splits(
            np.asarray(labels)[calibration_index],
            np.asarray(groups, dtype=object)[calibration_index],
            n_splits=int(cv["calibration_oof_folds"]),
            seed=int(cv["outer_seed"]) + 20000 + fold,
            context=f"preflight/{task}/calibration-{fold}",
            min_train_groups_per_class=int(
                cv["calibration_fold_min_groups_per_class"]
            ),
            min_test_groups_per_class=int(
                cv["calibration_fold_min_groups_per_class"]
            ),
        )
        audit.append(
            {
                "fold": fold,
                "outer_train_groups": len(
                    set(np.asarray(groups, dtype=object)[outer_train])
                ),
                "outer_test_groups": len(
                    set(np.asarray(groups, dtype=object)[outer_test])
                ),
                **split_audit,
            }
        )
    return audit


def expected_calibration_error(
    probabilities: np.ndarray,
    labels: Sequence[int],
    *,
    bins: int = 10,
) -> float:
    label_array = np.asarray(labels, dtype=int)
    predictions = np.argmax(probabilities, axis=1)
    confidence = np.max(probabilities, axis=1)
    correct = predictions == label_array
    error = 0.0
    edges = np.linspace(0.0, 1.0, bins + 1)
    for index in range(bins):
        lower, upper = edges[index], edges[index + 1]
        mask = (confidence >= lower) & (
            confidence <= upper if index == bins - 1 else confidence < upper
        )
        count = int(mask.sum())
        if count:
            error += (count / len(labels)) * abs(
                float(np.mean(correct[mask])) - float(np.mean(confidence[mask]))
            )
    return float(error)


def multiclass_brier(
    probabilities: np.ndarray, labels: Sequence[int], class_count: int
) -> float:
    one_hot = np.zeros((len(labels), class_count), dtype=np.float64)
    one_hot[np.arange(len(labels)), np.asarray(labels, dtype=int)] = 1.0
    return float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1)))


@dataclass(frozen=True)
class EmbeddingSpec:
    id: str
    repository: str
    revision: str
    local_path: Path
    tree_sha256: str
    dimension: int
    symmetric_prefix: str
    retrieval_query_prefix: str
    retrieval_passage_prefix: str


class PeakRssSampler:
    def __init__(self, interval_seconds: float = 0.05) -> None:
        self.interval_seconds = interval_seconds
        self.process = psutil.Process(os.getpid())
        self.peak = self.process.memory_info().rss
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stopped.wait(self.interval_seconds):
            try:
                self.peak = max(self.peak, self.process.memory_info().rss)
            except psutil.Error:
                return

    def __enter__(self) -> PeakRssSampler:
        self._thread.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self._stopped.set()
        self._thread.join(timeout=1.0)
        try:
            self.peak = max(self.peak, self.process.memory_info().rss)
        except psutil.Error:
            pass


def load_npz_map(path: Path, expected_keys: Sequence[str], dimension: int) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as data:
        keys = data["keys"].astype(str).tolist()
        vectors = np.asarray(data["vectors"], dtype=np.float32)
    if keys != list(expected_keys):
        raise SelectionGuardError(f"Cache de embeddings não corresponde às entradas: {path}")
    if vectors.shape != (len(keys), dimension) or not np.isfinite(vectors).all():
        raise SelectionGuardError(f"Cache de embeddings inválido: {path}")
    norms = np.linalg.norm(vectors, axis=1)
    if keys and not np.allclose(norms, 1.0, atol=1e-4):
        raise SelectionGuardError(f"Embeddings não normalizados no cache: {path}")
    return {key: vectors[index] for index, key in enumerate(keys)}


def save_npz_map(path: Path, keys: Sequence[str], vectors: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        keys=np.asarray(list(keys), dtype=str),
        vectors=np.asarray(vectors, dtype=np.float32),
    )


def embedding_cache_valid(
    metadata_path: Path,
    *,
    spec: EmbeddingSpec,
    dataset_sha256: str,
    role_inputs: dict[str, tuple[Sequence[str], str]],
    packages: dict[str, str],
) -> bool:
    if not metadata_path.exists():
        return False
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if (
        metadata.get("repository") != spec.repository
        or metadata.get("revision") != spec.revision
        or metadata.get("tree_sha256") != spec.tree_sha256
        or metadata.get("dataset_sha256") != dataset_sha256
        or int(metadata.get("dimension", 0)) != spec.dimension
        or metadata.get("packages") != packages
    ):
        return False
    for role, (keys, prefix) in role_inputs.items():
        if metadata.get("roles", {}).get(role, {}).get("keys_sha256") != canonical_sha256(
            list(keys)
        ):
            return False
        if metadata.get("roles", {}).get(role, {}).get("prefix") != prefix:
            return False
        cache_path = metadata_path.parent / f"{role}.npz"
        if not cache_path.exists():
            return False
        expected_cache_sha256 = metadata.get("roles", {}).get(role, {}).get(
            "npz_sha256"
        )
        if (
            expected_cache_sha256
            and sha256_file(cache_path) != expected_cache_sha256
        ):
            return False
    return True


def encode_model_roles(
    spec: EmbeddingSpec,
    *,
    dataset_sha256: str,
    role_inputs: dict[str, tuple[list[str], str]],
    cache_root: Path,
    batch_size: int,
    cpu_threads: int,
    force: bool,
) -> tuple[dict[str, dict[str, np.ndarray]], dict[str, Any]]:
    cache_dir = cache_root / dataset_sha256[:16] / spec.id
    metadata_path = cache_dir / "metadata.json"
    role_keys = {role: values[0] for role, values in role_inputs.items()}

    try:
        import sentence_transformers
        import torch
        import transformers
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise SelectionGuardError(
            "Embeddings exigem torch, transformers e sentence-transformers"
        ) from exc

    packages = {
        "torch": torch.__version__,
        "sentence_transformers": sentence_transformers.__version__,
        "transformers": transformers.__version__,
    }
    model_path = spec.local_path.resolve()
    if not model_path.is_dir():
        raise SelectionGuardError(f"Modelo ausente: {model_path}")
    observed_tree, file_count, total_bytes = directory_sha256(model_path)
    if observed_tree != spec.tree_sha256:
        raise SelectionGuardError(
            f"Hash da árvore divergente para {spec.id}: {observed_tree}"
        )

    if not force and embedding_cache_valid(
        metadata_path,
        spec=spec,
        dataset_sha256=dataset_sha256,
        role_inputs=role_inputs,
        packages=packages,
    ):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        maps = {
            role: load_npz_map(cache_dir / f"{role}.npz", keys, spec.dimension)
            for role, keys in role_keys.items()
        }
        for role in role_keys:
            cache_path = cache_dir / f"{role}.npz"
            metadata["roles"][role]["npz_sha256"] = sha256_file(cache_path)
        metadata["cache_hit"] = True
        metadata["validated_at"] = utc_now()
        write_json(metadata_path, metadata)
        return maps, metadata

    torch.set_num_threads(max(1, min(4, int(cpu_threads))))
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass
    process = psutil.Process(os.getpid())
    rss_before = process.memory_info().rss
    load_started = time.perf_counter()
    with PeakRssSampler() as load_sampler:
        model = SentenceTransformer(
            str(model_path),
            device="cpu",
            local_files_only=True,
        )
    load_seconds = time.perf_counter() - load_started
    dimension = int(model.get_sentence_embedding_dimension() or 0)
    if dimension != spec.dimension:
        raise SelectionGuardError(
            f"{spec.id}: dimensão {dimension}, esperado {spec.dimension}"
        )

    first_role = next(iter(role_inputs.values()))
    warmup_text = (first_role[1] + first_role[0][0]) if first_role[0] else "teste"
    model.encode(
        [warmup_text],
        normalize_embeddings=True,
        convert_to_numpy=True,
        batch_size=1,
        show_progress_bar=False,
    )

    latency_inputs = first_role[0][:20]
    single_latencies: list[float] = []
    for text in latency_inputs:
        started = time.perf_counter()
        model.encode(
            [first_role[1] + text],
            normalize_embeddings=True,
            convert_to_numpy=True,
            batch_size=1,
            show_progress_bar=False,
        )
        single_latencies.append((time.perf_counter() - started) * 1000)

    batch_latencies: list[float] = []
    for start in range(0, min(len(first_role[0]), 80), 8):
        batch = first_role[0][start : start + 8]
        if not batch:
            continue
        started = time.perf_counter()
        model.encode(
            [first_role[1] + text for text in batch],
            normalize_embeddings=True,
            convert_to_numpy=True,
            batch_size=min(batch_size, len(batch)),
            show_progress_bar=False,
        )
        batch_latencies.append((time.perf_counter() - started) * 1000)

    role_maps: dict[str, dict[str, np.ndarray]] = {}
    role_metadata: dict[str, Any] = {}
    encode_peak = process.memory_info().rss
    for role, (keys, prefix) in role_inputs.items():
        started = time.perf_counter()
        with PeakRssSampler() as sampler:
            vectors = model.encode(
                [prefix + text for text in keys],
                normalize_embeddings=True,
                convert_to_numpy=True,
                batch_size=min(batch_size, max(1, len(keys))),
                show_progress_bar=True,
            )
        elapsed = time.perf_counter() - started
        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.shape != (len(keys), spec.dimension):
            raise SelectionGuardError(
                f"{spec.id}/{role}: shape {vectors.shape} inválido"
            )
        norms = np.linalg.norm(vectors, axis=1)
        if len(keys) and not np.allclose(norms, 1.0, atol=1e-4):
            raise SelectionGuardError(f"{spec.id}/{role}: vetores não normalizados")
        save_npz_map(cache_dir / f"{role}.npz", keys, vectors)
        cache_path = cache_dir / f"{role}.npz"
        role_maps[role] = {
            key: vectors[index] for index, key in enumerate(keys)
        }
        encode_peak = max(encode_peak, sampler.peak)
        role_metadata[role] = {
            "records": len(keys),
            "prefix": prefix,
            "keys_sha256": canonical_sha256(keys),
            "npz_sha256": sha256_file(cache_path),
            "seconds": elapsed,
            "texts_per_second": len(keys) / elapsed if elapsed else None,
            "peak_rss_mb": sampler.peak / 1024 / 1024,
        }

    metadata = {
        "schema": "projeto-ic-embedding-cache-v1",
        "created_at": utc_now(),
        "cache_hit": False,
        "model_id": spec.id,
        "repository": spec.repository,
        "revision": spec.revision,
        "local_path": str(model_path),
        "tree_sha256": observed_tree,
        "file_count": file_count,
        "total_bytes": total_bytes,
        "dataset_sha256": dataset_sha256,
        "dimension": dimension,
        "normalized": True,
        "backend": "pytorch_fp32",
        "measurement_scope": "encoder_only_sequential_process",
        "load_seconds": load_seconds,
        "rss_before_mb": rss_before / 1024 / 1024,
        "load_peak_rss_mb": load_sampler.peak / 1024 / 1024,
        "encode_peak_rss_mb": encode_peak / 1024 / 1024,
        "single_text_latency_ms": {
            "n": len(single_latencies),
            "p50": percentile(single_latencies, 50),
            "p95": percentile(single_latencies, 95),
        },
        "batch8_latency_ms": {
            "n": len(batch_latencies),
            "p50": percentile(batch_latencies, 50),
            "p95": percentile(batch_latencies, 95),
        },
        "roles": role_metadata,
        "packages": packages,
    }
    write_json(metadata_path, metadata)
    del model
    gc.collect()
    return role_maps, metadata


class TextFeatureBuilder(BaseEstimator, TransformerMixin):
    def __init__(
        self,
        *,
        use_tfidf: bool,
        use_embedding: bool,
        embedding_dimension: int = 384,
    ) -> None:
        self.use_tfidf = use_tfidf
        self.use_embedding = use_embedding
        self.embedding_dimension = embedding_dimension

    def fit(self, samples: Sequence[dict[str, Any]], y: Any = None) -> TextFeatureBuilder:
        del y
        if not self.use_tfidf and not self.use_embedding:
            raise SelectionGuardError("Representação vazia")
        self.vectorizer_ = None
        names: list[str] = []
        if self.use_tfidf:
            self.vectorizer_ = training.build_text_vectorizer()
            self.vectorizer_.fit([sample["text"] for sample in samples])
            names.extend(
                f"tfidf__{name}"
                for name in self.vectorizer_.get_feature_names_out().tolist()
            )
        if self.use_embedding:
            names.extend(
                f"embedding__{index:03d}"
                for index in range(self.embedding_dimension)
            )
        self.feature_names_ = np.asarray(names, dtype=object)
        return self

    def transform(self, samples: Sequence[dict[str, Any]]) -> sparse.csr_matrix:
        matrices: list[sparse.csr_matrix] = []
        if self.use_tfidf:
            matrices.append(
                self.vectorizer_.transform(
                    [sample["text"] for sample in samples]
                ).tocsr()
            )
        if self.use_embedding:
            embeddings = np.vstack(
                [np.asarray(sample["embedding"], dtype=np.float32) for sample in samples]
            )
            if embeddings.shape[1] != self.embedding_dimension:
                raise SelectionGuardError("Dimensão de embedding divergente")
            matrices.append(sparse.csr_matrix(embeddings))
        return matrices[0] if len(matrices) == 1 else sparse.hstack(matrices, format="csr")

    def get_feature_names_out(self, input_features: Any = None) -> np.ndarray:
        del input_features
        return self.feature_names_


class PairFeatureBuilder(BaseEstimator, TransformerMixin):
    def __init__(
        self,
        *,
        use_tfidf: bool,
        use_embedding: bool,
        use_metadata: bool,
        embedding_dimension: int = 384,
    ) -> None:
        self.use_tfidf = use_tfidf
        self.use_embedding = use_embedding
        self.use_metadata = use_metadata
        self.embedding_dimension = embedding_dimension

    @staticmethod
    def _pairs(
        samples: Sequence[dict[str, Any]],
    ) -> list[tuple[dict[str, Any], dict[str, Any], str]]:
        return [
            (sample["current"], sample["reference"], sample["label_name"])
            for sample in samples
        ]

    def fit(self, samples: Sequence[dict[str, Any]], y: Any = None) -> PairFeatureBuilder:
        del y
        if not self.use_tfidf and not self.use_embedding and not self.use_metadata:
            raise SelectionGuardError("Representação de pares vazia")
        self.vectorizer_ = None
        names: list[str] = []
        if self.use_tfidf:
            self.vectorizer_ = training.build_text_vectorizer()
            texts = [
                text
                for sample in samples
                for text in (sample["current_text"], sample["reference_text"])
            ]
            self.vectorizer_.fit(texts)
            base_names = self.vectorizer_.get_feature_names_out().tolist()
            names.extend(f"tfidf_abs__{name}" for name in base_names)
            names.extend(f"tfidf_overlap__{name}" for name in base_names)
            names.append("tfidf_cosine")
        if self.use_embedding:
            names.extend(
                f"embedding_abs__{index:03d}"
                for index in range(self.embedding_dimension)
            )
            names.extend(
                f"embedding_product__{index:03d}"
                for index in range(self.embedding_dimension)
            )
            names.append("embedding_cosine")
        if self.use_metadata:
            names.extend(f"metadata__{name}" for name in STRUCTURED_PAIR_FEATURES)
        self.feature_names_ = np.asarray(names, dtype=object)
        return self

    def transform(self, samples: Sequence[dict[str, Any]]) -> sparse.csr_matrix:
        matrices: list[sparse.csr_matrix] = []
        pairs = self._pairs(samples)
        if self.use_tfidf:
            current = self.vectorizer_.transform(
                [sample["current_text"] for sample in samples]
            ).tocsr()
            reference = self.vectorizer_.transform(
                [sample["reference_text"] for sample in samples]
            ).tocsr()
            difference = abs(current - reference)
            overlap = current.multiply(reference)
            dot = np.asarray(overlap.sum(axis=1), dtype=np.float64).reshape(-1)
            current_norm = np.sqrt(
                np.asarray(current.multiply(current).sum(axis=1)).reshape(-1)
            )
            reference_norm = np.sqrt(
                np.asarray(reference.multiply(reference).sum(axis=1)).reshape(-1)
            )
            denominator = current_norm * reference_norm
            cosine = np.divide(
                dot,
                denominator,
                out=np.zeros_like(dot),
                where=denominator > 0,
            ).reshape(-1, 1)
            matrices.extend(
                [
                    difference,
                    overlap,
                    sparse.csr_matrix(cosine),
                ]
            )
        if self.use_embedding:
            current_embedding = np.vstack(
                [
                    np.asarray(sample["current_embedding"], dtype=np.float32)
                    for sample in samples
                ]
            )
            reference_embedding = np.vstack(
                [
                    np.asarray(sample["reference_embedding"], dtype=np.float32)
                    for sample in samples
                ]
            )
            if (
                current_embedding.shape[1] != self.embedding_dimension
                or reference_embedding.shape[1] != self.embedding_dimension
            ):
                raise SelectionGuardError("Dimensão de embedding de par divergente")
            dense = np.hstack(
                [
                    np.abs(current_embedding - reference_embedding),
                    current_embedding * reference_embedding,
                    np.sum(
                        current_embedding * reference_embedding,
                        axis=1,
                        keepdims=True,
                    ),
                ]
            )
            matrices.append(sparse.csr_matrix(dense))
        if self.use_metadata:
            matrices.append(training.structured_pair_matrix(pairs))
        return matrices[0] if len(matrices) == 1 else sparse.hstack(matrices, format="csr")

    def get_feature_names_out(self, input_features: Any = None) -> np.ndarray:
        del input_features
        return self.feature_names_


def make_classifier(
    classifier_id: str,
    *,
    specification: dict[str, Any],
    seed: int,
    class_count: int,
) -> tuple[BaseEstimator, dict[str, list[Any]], bool]:
    if specification.get("id") != classifier_id:
        raise SelectionGuardError(
            f"Especificação divergente para {classifier_id}"
        )
    raw_grid = specification.get("grid")
    if not isinstance(raw_grid, dict) or not raw_grid:
        raise SelectionGuardError(f"Grade ausente para {classifier_id}")
    parameter_grid = {
        f"model__{name}": [
            tuple(value)
            if name == "hidden_layer_sizes" and isinstance(value, list)
            else value
            for value in values
        ]
        for name, values in raw_grid.items()
    }
    if classifier_id == "logistic_regression":
        estimator = LogisticRegression(
            max_iter=4000,
            random_state=seed,
            class_weight="balanced",
            solver="liblinear" if class_count == 2 else "lbfgs",
        )
        return estimator, parameter_grid, False
    if classifier_id == "decision_tree":
        estimator = DecisionTreeClassifier(
            random_state=seed,
            class_weight="balanced",
            criterion="gini",
        )
        return estimator, parameter_grid, False
    if classifier_id == "linear_svm":
        estimator = LinearSVC(
            random_state=seed,
            class_weight="balanced",
            dual="auto",
            max_iter=20000,
        )
        return estimator, parameter_grid, False
    if classifier_id == "mlp":
        estimator = MLPClassifier(
            random_state=seed,
            hidden_layer_sizes=(16,),
            alpha=0.001,
            max_iter=600,
            early_stopping=bool(specification.get("early_stopping", False)),
            batch_size=32,
            learning_rate_init=0.001,
            solver="adam",
        )
        return estimator, parameter_grid, True
    if classifier_id == "xgboost":
        objective = "binary:logistic" if class_count == 2 else "multi:softprob"
        estimator = XGBClassifier(
            objective=objective,
            eval_metric="logloss" if class_count == 2 else "mlogloss",
            random_state=seed,
            tree_method="hist",
            n_jobs=2,
            verbosity=0,
            subsample=0.9,
            colsample_bytree=0.9,
            reg_lambda=2.0,
            min_child_weight=2.0,
        )
        return estimator, parameter_grid, True
    raise SelectionGuardError(f"Classificador desconhecido: {classifier_id}")


def make_pipeline(
    *,
    task: str,
    use_tfidf: bool,
    use_embedding: bool,
    use_metadata: bool,
    classifier_id: str,
    classifier_specification: dict[str, Any],
    seed: int,
    class_count: int,
    embedding_dimension: int,
) -> tuple[Pipeline, dict[str, list[Any]], bool]:
    if task == "classification":
        if use_metadata:
            raise SelectionGuardError(
                "Metadados estruturados de pares não se aplicam à classificação"
            )
        features: BaseEstimator = TextFeatureBuilder(
            use_tfidf=use_tfidf,
            use_embedding=use_embedding,
            embedding_dimension=embedding_dimension,
        )
    elif task == "deduplication":
        features = PairFeatureBuilder(
            use_tfidf=use_tfidf,
            use_embedding=use_embedding,
            use_metadata=use_metadata,
            embedding_dimension=embedding_dimension,
        )
    else:
        raise SelectionGuardError(f"Tarefa desconhecida: {task}")
    model, grid, weighted = make_classifier(
        classifier_id,
        specification=classifier_specification,
        seed=seed,
        class_count=class_count,
    )
    return Pipeline([("features", features), ("model", model)]), grid, weighted


class DedupCostScorer:
    def __init__(self, false_negative_cost: float, false_positive_cost: float) -> None:
        self.false_negative_cost = false_negative_cost
        self.false_positive_cost = false_positive_cost

    def __call__(
        self, estimator: BaseEstimator, samples: Sequence[dict[str, Any]], labels: Sequence[int]
    ) -> float:
        predicted = np.asarray(estimator.predict(samples), dtype=int)
        gold = np.asarray(labels, dtype=int)
        false_negative = int(np.sum((gold == 1) & (predicted == 0)))
        false_positive = int(np.sum((gold == 0) & (predicted == 1)))
        cost = (
            self.false_negative_cost * false_negative
            + self.false_positive_cost * false_positive
        ) / len(gold)
        return -float(cost)


def reorder_probabilities(
    probabilities: np.ndarray,
    observed_classes: Sequence[int],
    class_count: int,
) -> np.ndarray:
    result = np.zeros((len(probabilities), class_count), dtype=np.float64)
    for source_index, label in enumerate(observed_classes):
        result[:, int(label)] = probabilities[:, source_index]
    return result


def fit_frozen_calibrator(
    estimator: BaseEstimator,
    samples: Sequence[dict[str, Any]],
    labels: Sequence[int],
    *,
    method: str,
) -> CalibratedClassifierCV:
    label_array = np.asarray(labels, dtype=int)
    if min(Counter(label_array.tolist()).values(), default=0) < 2:
        raise SelectionGuardError("Calibração exige ao menos duas observações por classe")
    calibrated = CalibratedClassifierCV(
        FrozenEstimator(estimator),
        method=method,
        cv=2,
        ensemble=False,
    )
    calibrated.fit(samples, label_array)
    return calibrated


def cross_fitted_calibration(
    estimator: BaseEstimator,
    samples: Sequence[dict[str, Any]],
    labels: Sequence[int],
    groups: Sequence[str],
    *,
    seed: int,
    folds: int,
    class_count: int,
    min_groups_per_class: int,
    method: str,
) -> tuple[CalibratedClassifierCV, np.ndarray, list[dict[str, Any]]]:
    splits = safe_stratified_group_splits(
        labels,
        groups,
        n_splits=folds,
        seed=seed,
        context="calibration",
        min_train_groups_per_class=min_groups_per_class,
        min_test_groups_per_class=min_groups_per_class,
    )
    probabilities = np.full(
        (len(labels), class_count),
        np.nan,
        dtype=np.float64,
    )
    audit: list[dict[str, Any]] = []
    for fold, (fit_index, validation_index) in enumerate(splits):
        calibrator = fit_frozen_calibrator(
            estimator,
            subset(samples, fit_index),
            np.asarray(labels)[fit_index],
            method=method,
        )
        fold_probabilities = calibrator.predict_proba(
            subset(samples, validation_index)
        )
        probabilities[validation_index] = reorder_probabilities(
            fold_probabilities,
            calibrator.classes_,
            class_count,
        )
        audit.append(
            {
                "fold": fold,
                "fit_records": len(fit_index),
                "validation_records": len(validation_index),
                "fit_groups": len(set(np.asarray(groups)[fit_index])),
                "validation_groups": len(set(np.asarray(groups)[validation_index])),
                "fit_group_counts_by_label": group_counts_by_label(
                    np.asarray(labels)[fit_index],
                    np.asarray(groups, dtype=object)[fit_index],
                ),
                "validation_group_counts_by_label": group_counts_by_label(
                    np.asarray(labels)[validation_index],
                    np.asarray(groups, dtype=object)[validation_index],
                ),
                "group_overlap": 0,
            }
        )
    if not np.isfinite(probabilities).all():
        raise SelectionGuardError("Calibração OOF deixou probabilidades ausentes")
    final = fit_frozen_calibrator(estimator, samples, labels, method=method)
    return final, probabilities, audit


def select_classification_policy(
    probabilities: np.ndarray,
    labels: Sequence[int],
    *,
    max_risk: float,
    min_coverage: float,
    obra_min_confidence: float,
) -> dict[str, Any]:
    labels_array = np.asarray(labels, dtype=int)
    predicted = np.argmax(probabilities, axis=1)
    confidence = np.max(probabilities, axis=1)
    obra_index = CLASS_LABELS.index("OBRA")
    triage_index = CLASS_LABELS.index("TRIAGEM_MANUAL")
    maintenance = np.isin(
        labels_array,
        [
            CLASS_LABELS.index("DEMO"),
            CLASS_LABELS.index("SOB_DEMANDA"),
        ],
    )
    non_obra = labels_array != obra_index
    candidates: list[dict[str, Any]] = []
    for threshold_int in range(50, 100):
        threshold = threshold_int / 100
        covered = confidence >= threshold
        covered &= predicted != triage_index
        covered &= (predicted != obra_index) | (
            confidence >= max(threshold, obra_min_confidence)
        )
        count = int(covered.sum())
        if not count:
            continue
        errors = int(np.sum(covered & (predicted != labels_array)))
        maintenance_as_obra = int(
            np.sum(covered & maintenance & (predicted == obra_index))
        )
        critical = int(
            np.sum(covered & non_obra & (predicted == obra_index))
        )
        risk = errors / count
        coverage = count / len(labels_array)
        candidates.append(
            {
                "threshold": threshold,
                "obra_threshold": max(threshold, obra_min_confidence),
                "covered": count,
                "coverage": coverage,
                "errors": errors,
                "risk": risk,
                "automatic_maintenance_as_obra": maintenance_as_obra,
                "automatic_non_obra_as_obra": critical,
                "eligible": bool(
                    critical == 0
                    and risk <= max_risk
                    and coverage >= min_coverage
                ),
            }
        )
    eligible = [candidate for candidate in candidates if candidate["eligible"]]
    if not eligible:
        return {
            "threshold": None,
            "obra_threshold": obra_min_confidence,
            "eligible": False,
            "curve": candidates,
        }
    selected = min(
        eligible,
        key=lambda item: (
            int(item["automatic_non_obra_as_obra"]),
            float(item["risk"]),
            -float(item["coverage"]),
            -float(item["threshold"]),
        ),
    )
    return {**selected, "curve": candidates}


def apply_classification_policy(
    probabilities: np.ndarray,
    policy: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray]:
    predicted = np.argmax(probabilities, axis=1)
    confidence = np.max(probabilities, axis=1)
    if policy.get("threshold") is None:
        return predicted, np.zeros(len(predicted), dtype=bool)
    covered = confidence >= float(policy["threshold"])
    obra_index = CLASS_LABELS.index("OBRA")
    triage_index = CLASS_LABELS.index("TRIAGEM_MANUAL")
    covered &= predicted != triage_index
    covered &= (predicted != obra_index) | (
        confidence >= float(policy["obra_threshold"])
    )
    return predicted, covered


def select_dedup_policy(
    probabilities: np.ndarray,
    labels: Sequence[int],
    policy: dict[str, Any],
    *,
    false_negative_cost: float,
    false_positive_cost: float,
) -> dict[str, Any]:
    string_labels = [DEDUP_LABELS[int(label)] for label in labels]
    positive, negative, curve = training._dedup_threshold(
        probabilities,
        string_labels,
        DEDUP_LABELS,
        max_false_positive_rate=float(policy["deduplication_max_false_positive_rate"]),
        min_precision=float(policy["deduplication_min_precision"]),
        min_coverage=float(policy["deduplication_min_coverage"]),
        max_false_negative_rate=float(policy["deduplication_max_false_negative_rate"]),
        min_negative_predictive_value=float(
            policy["deduplication_min_negative_predictive_value"]
        ),
        false_negative_cost=false_negative_cost,
        false_positive_cost=false_positive_cost,
    )
    selected = next(
        (
            item
            for item in curve
            if positive is not None
            and negative is not None
            and abs(float(item["positive_threshold"]) - positive) < 1e-12
            and abs(float(item["negative_threshold"]) - negative) < 1e-12
        ),
        None,
    )
    return {
        "positive_threshold": positive,
        "negative_threshold": negative,
        "eligible": selected is not None,
        "selected": selected,
        "curve_points": len(curve),
    }


def apply_dedup_policy(
    probabilities: np.ndarray,
    policy: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray]:
    p_duplicate = probabilities[:, 1]
    decisions = np.full(len(p_duplicate), -1, dtype=int)
    if (
        policy.get("positive_threshold") is None
        or policy.get("negative_threshold") is None
    ):
        return decisions, np.zeros(len(decisions), dtype=bool)
    decisions[p_duplicate >= float(policy["positive_threshold"])] = 1
    decisions[p_duplicate <= float(policy["negative_threshold"])] = 0
    return decisions, decisions >= 0


def clopper_pearson_upper(
    events: int,
    trials: int,
    *,
    confidence_level: float,
) -> float | None:
    if trials <= 0:
        return None
    if events >= trials:
        return 1.0
    return float(beta.ppf(confidence_level, events + 1, trials - events))


def bootstrap_group_interval(
    labels: Sequence[int],
    predictions: Sequence[int],
    groups: Sequence[str],
    covered: Sequence[bool],
    *,
    metric: str,
    resamples: int,
    seed: int,
    confidence_level: float,
) -> list[float] | None:
    labels_array = np.asarray(labels, dtype=int)
    predictions_array = np.asarray(predictions, dtype=int)
    groups_array = np.asarray(groups, dtype=object)
    covered_array = np.asarray(covered, dtype=bool)
    unique_groups = sorted(set(groups_array.tolist()))
    indices_by_group = {
        group: np.flatnonzero(groups_array == group) for group in unique_groups
    }
    rng = np.random.default_rng(seed)
    values: list[float] = []
    for _ in range(resamples):
        chosen = rng.choice(unique_groups, size=len(unique_groups), replace=True)
        sampled_indices = np.concatenate([indices_by_group[group] for group in chosen])
        gold = labels_array[sampled_indices]
        predicted = predictions_array[sampled_indices]
        sampled_covered = covered_array[sampled_indices]
        if metric == "accuracy":
            value = accuracy_score(gold, predicted)
        elif metric == "macro_f1":
            value = f1_score(gold, predicted, average="macro", zero_division=0)
        elif metric == "coverage":
            value = float(sampled_covered.mean())
        elif metric == "selective_risk":
            if not sampled_covered.any():
                continue
            value = float(
                np.mean(predicted[sampled_covered] != gold[sampled_covered])
            )
        else:
            raise SelectionGuardError(f"Métrica bootstrap desconhecida: {metric}")
        values.append(float(value))
    if not values:
        return None
    alpha = 1.0 - confidence_level
    return [
        float(np.percentile(values, 100.0 * alpha / 2.0)),
        float(np.percentile(values, 100.0 * (1.0 - alpha / 2.0))),
    ]


def classification_summary(
    labels: Sequence[int],
    probabilities: np.ndarray,
    predictions: Sequence[int],
    covered: Sequence[bool],
    groups: Sequence[str],
    *,
    bootstrap_resamples: int,
    seed: int,
    confidence_level: float,
) -> dict[str, Any]:
    labels_array = np.asarray(labels, dtype=int)
    predicted_array = np.asarray(predictions, dtype=int)
    covered_array = np.asarray(covered, dtype=bool)
    triage_index = CLASS_LABELS.index("TRIAGEM_MANUAL")
    automatic_triage_count = int(
        np.sum(covered_array & (predicted_array == triage_index))
    )
    if automatic_triage_count:
        raise SelectionGuardError(
            "TRIAGEM_MANUAL não pode ser contabilizada como automação"
        )
    report = classification_report(
        labels_array,
        predicted_array,
        labels=list(range(len(CLASS_LABELS))),
        target_names=CLASS_LABELS,
        output_dict=True,
        zero_division=0,
    )
    count = int(covered_array.sum())
    errors = int(np.sum(covered_array & (predicted_array != labels_array)))
    maintenance = np.isin(
        labels_array,
        [
            CLASS_LABELS.index("DEMO"),
            CLASS_LABELS.index("SOB_DEMANDA"),
        ],
    )
    obra = predicted_array == CLASS_LABELS.index("OBRA")
    non_obra = labels_array != CLASS_LABELS.index("OBRA")
    critical_mask = covered_array & non_obra & obra
    groups_array = np.asarray(groups, dtype=object)
    exposed_groups = {
        group
        for group in set(groups_array.tolist())
        if np.any(
            (groups_array == group)
            & covered_array
            & non_obra
        )
    }
    critical_groups = {
        group
        for group in exposed_groups
        if np.any((groups_array == group) & critical_mask)
    }
    covered_non_obra = int(np.sum(covered_array & non_obra))
    return {
        "records": len(labels_array),
        "accuracy": float(accuracy_score(labels_array, predicted_array)),
        "macro_f1": float(
            f1_score(labels_array, predicted_array, average="macro", zero_division=0)
        ),
        "log_loss": float(
            log_loss(labels_array, probabilities, labels=list(range(len(CLASS_LABELS))))
        ),
        "brier_score": multiclass_brier(
            probabilities, labels_array, len(CLASS_LABELS)
        ),
        "expected_calibration_error_10_bins": expected_calibration_error(
            probabilities, labels_array
        ),
        "confusion_matrix": {
            "labels": CLASS_LABELS,
            "values": confusion_matrix(
                labels_array,
                predicted_array,
                labels=list(range(len(CLASS_LABELS))),
            ).astype(int).tolist(),
        },
        "per_class": {
            label: {
                key: float(value) if key != "support" else int(value)
                for key, value in report[label].items()
            }
            for label in CLASS_LABELS
        },
        "obra_recall": float(report["OBRA"]["recall"]),
        "automatic_records": count,
        "automatic_coverage": count / len(labels_array),
        "human_review_required_records": len(labels_array) - count,
        "automatic_triage_records": automatic_triage_count,
        "triagem_manual_is_automatic": False,
        "automatic_errors": errors,
        "automatic_risk": errors / count if count else None,
        "automatic_maintenance_as_obra": int(
            np.sum(covered_array & maintenance & obra)
        ),
        "automatic_non_obra_as_obra": int(critical_mask.sum()),
        "automatic_non_obra_records": covered_non_obra,
        "automatic_non_obra_as_obra_rate": (
            int(critical_mask.sum()) / covered_non_obra
            if covered_non_obra
            else None
        ),
        "automatic_non_obra_as_obra_group_events": len(critical_groups),
        "automatic_non_obra_exposed_groups": len(exposed_groups),
        "automatic_non_obra_as_obra_group_rate_upper": clopper_pearson_upper(
            len(critical_groups),
            len(exposed_groups),
            confidence_level=confidence_level,
        ),
        "semantic_maintenance_as_obra": int(np.sum(maintenance & obra)),
        "confidence_level": confidence_level,
        "confidence_intervals_group_bootstrap": {
            metric: bootstrap_group_interval(
                labels_array,
                predicted_array,
                groups,
                covered_array,
                metric=metric,
                resamples=bootstrap_resamples,
                seed=seed + offset,
                confidence_level=confidence_level,
            )
            for offset, metric in enumerate(
                ["accuracy", "macro_f1", "coverage", "selective_risk"]
            )
        },
    }


def bootstrap_dedup_intervals(
    labels: Sequence[int],
    decisions: Sequence[int],
    groups: Sequence[str],
    *,
    false_negative_cost: float,
    false_positive_cost: float,
    resamples: int,
    seed: int,
    confidence_level: float,
) -> dict[str, list[float] | None]:
    labels_array = np.asarray(labels, dtype=int)
    decisions_array = np.asarray(decisions, dtype=int)
    groups_array = np.asarray(groups, dtype=object)
    unique_groups = sorted(set(groups_array.tolist()))
    indices_by_group = {
        group: np.flatnonzero(groups_array == group) for group in unique_groups
    }
    names = [
        "precision",
        "negative_predictive_value",
        "false_positive_rate",
        "false_negative_rate",
        "weighted_error_per_record",
        "decision_coverage",
        "full_automation_coverage",
    ]
    values: dict[str, list[float]] = {name: [] for name in names}
    rng = np.random.default_rng(seed)
    for _ in range(resamples):
        chosen = rng.choice(unique_groups, size=len(unique_groups), replace=True)
        sampled = np.concatenate([indices_by_group[group] for group in chosen])
        gold = labels_array[sampled]
        decision = decisions_array[sampled]
        positive = decision == 1
        negative = decision == 0
        covered = decision >= 0
        tp = int(np.sum((gold == 1) & positive))
        fp = int(np.sum((gold == 0) & positive))
        tn = int(np.sum((gold == 0) & negative))
        fn = int(np.sum((gold == 1) & negative))
        positives = int(np.sum(gold == 1))
        negatives = int(np.sum(gold == 0))
        candidates = {
            "precision": tp / (tp + fp) if tp + fp else None,
            "negative_predictive_value": tn / (tn + fn) if tn + fn else None,
            "false_positive_rate": fp / negatives if negatives else None,
            "false_negative_rate": fn / positives if positives else None,
            "weighted_error_per_record": (
                false_negative_cost * fn + false_positive_cost * fp
            )
            / len(gold),
            "decision_coverage": float(np.mean(covered)),
            "full_automation_coverage": float(np.mean(negative)),
        }
        for name, value in candidates.items():
            if value is not None:
                values[name].append(float(value))
    alpha = 1.0 - confidence_level
    return {
        name: (
            [
                float(np.percentile(metric_values, 100.0 * alpha / 2.0)),
                float(
                    np.percentile(
                        metric_values,
                        100.0 * (1.0 - alpha / 2.0),
                    )
                ),
            ]
            if metric_values
            else None
        )
        for name, metric_values in values.items()
    }


def dedup_summary(
    labels: Sequence[int],
    probabilities: np.ndarray,
    decisions: Sequence[int],
    covered: Sequence[bool],
    groups: Sequence[str],
    *,
    false_negative_cost: float,
    false_positive_cost: float,
    bootstrap_resamples: int,
    seed: int,
    confidence_level: float,
) -> dict[str, Any]:
    labels_array = np.asarray(labels, dtype=int)
    decisions_array = np.asarray(decisions, dtype=int)
    covered_array = np.asarray(covered, dtype=bool)
    semantic = np.argmax(probabilities, axis=1)
    p_duplicate = probabilities[:, 1]
    tp = int(np.sum(covered_array & (labels_array == 1) & (decisions_array == 1)))
    fp = int(np.sum(covered_array & (labels_array == 0) & (decisions_array == 1)))
    tn = int(np.sum(covered_array & (labels_array == 0) & (decisions_array == 0)))
    fn = int(np.sum(covered_array & (labels_array == 1) & (decisions_array == 0)))
    positives = int(np.sum(labels_array == 1))
    negatives = int(np.sum(labels_array == 0))
    covered_count = int(covered_array.sum())
    automatic_positive_count = int(np.sum(decisions_array == 1))
    automatic_negative_count = int(np.sum(decisions_array == 0))
    weighted_cost = false_negative_cost * fn + false_positive_cost * fp
    groups_array = np.asarray(groups, dtype=object)
    positive_groups = {
        group
        for group in set(groups_array.tolist())
        if np.any((groups_array == group) & (labels_array == 1))
    }
    negative_groups = {
        group
        for group in set(groups_array.tolist())
        if np.any((groups_array == group) & (labels_array == 0))
    }
    fn_groups = {
        group
        for group in positive_groups
        if np.any(
            (groups_array == group)
            & (labels_array == 1)
            & (decisions_array == 0)
        )
    }
    fp_groups = {
        group
        for group in negative_groups
        if np.any(
            (groups_array == group)
            & (labels_array == 0)
            & (decisions_array == 1)
        )
    }
    return {
        "records": len(labels_array),
        "positive_records": positives,
        "negative_records": negatives,
        "semantic_accuracy": float(accuracy_score(labels_array, semantic)),
        "semantic_f1": float(f1_score(labels_array, semantic, zero_division=0)),
        "average_precision": float(
            average_precision_score(labels_array, p_duplicate)
        ),
        "roc_auc": float(roc_auc_score(labels_array, p_duplicate)),
        "log_loss": float(
            log_loss(labels_array, probabilities, labels=[0, 1])
        ),
        "brier_score": float(brier_score_loss(labels_array, p_duplicate)),
        "expected_calibration_error_10_bins": expected_calibration_error(
            probabilities, labels_array
        ),
        "semantic_confusion_matrix": confusion_matrix(
            labels_array, semantic, labels=[0, 1]
        ).astype(int).tolist(),
        "decision_records": covered_count,
        "decision_coverage": covered_count / len(labels_array),
        "automatic_positive_records_requiring_human_confirmation": (
            automatic_positive_count
        ),
        "fully_automated_negative_records": automatic_negative_count,
        "full_automation_coverage": automatic_negative_count / len(labels_array),
        "human_review_required_records": (
            len(labels_array) - automatic_negative_count
        ),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "negative_predictive_value": tn / (tn + fn) if tn + fn else None,
        "automatic_false_positive_rate": fp / negatives if negatives else None,
        "automatic_false_negative_rate": fn / positives if positives else None,
        "false_negative_group_events": len(fn_groups),
        "positive_groups": len(positive_groups),
        "false_negative_group_rate_upper": clopper_pearson_upper(
            len(fn_groups),
            len(positive_groups),
            confidence_level=confidence_level,
        ),
        "false_positive_group_events": len(fp_groups),
        "negative_groups": len(negative_groups),
        "false_positive_group_rate_upper": clopper_pearson_upper(
            len(fp_groups),
            len(negative_groups),
            confidence_level=confidence_level,
        ),
        "weighted_error_fn5_fp1_total": weighted_cost,
        "weighted_error_fn5_fp1_per_record": weighted_cost / len(labels_array),
        "weighted_error_fn5_fp1_per_automatic": (
            weighted_cost / covered_count if covered_count else None
        ),
        "confidence_level": confidence_level,
        "semantic_confidence_intervals_group_bootstrap": {
            metric: bootstrap_group_interval(
                labels_array,
                semantic,
                groups,
                covered_array,
                metric=metric,
                resamples=bootstrap_resamples,
                seed=seed + offset,
                confidence_level=confidence_level,
            )
            for offset, metric in enumerate(["accuracy", "macro_f1"])
        },
        "operating_confidence_intervals_group_bootstrap": (
            bootstrap_dedup_intervals(
                labels_array,
                decisions_array,
                groups,
                false_negative_cost=false_negative_cost,
                false_positive_cost=false_positive_cost,
                resamples=bootstrap_resamples,
                seed=seed + 100,
                confidence_level=confidence_level,
            )
        ),
    }


def run_configuration(
    *,
    task: str,
    representation_id: str,
    embedding_id: str | None,
    classifier_id: str,
    samples: list[dict[str, Any]],
    labels: list[int],
    groups: list[str],
    config: dict[str, Any],
    output_dir: Path,
    protocol_sha256: str,
    run_fingerprint: str,
    resume: bool,
) -> dict[str, Any]:
    combination_id = "__".join(
        [
            task,
            representation_id,
            embedding_id or "none",
            classifier_id,
        ]
    )
    partial_path = output_dir / "partials" / f"{combination_id}.joblib"
    if resume and partial_path.exists():
        try:
            cached = joblib.load(partial_path)
        except Exception:
            cached = None
        if (
            isinstance(cached, dict)
            and cached.get("protocol_sha256") == protocol_sha256
            and cached.get("run_fingerprint") == run_fingerprint
            and cached.get("status") == "COMPLETED_DEVELOPMENT_OOF"
        ):
            print(f"[resume] {combination_id}", flush=True)
            return cached

    cv = config["cross_validation"]
    representation_spec = config["representations"].get(representation_id)
    if representation_spec is None:
        raise SelectionGuardError(
            f"Representação ausente no protocolo: {representation_id}"
        )
    if task not in representation_spec.get("tasks", []):
        raise SelectionGuardError(
            f"{representation_id} não é aplicável a {task}"
        )
    use_tfidf = bool(representation_spec["uses_tfidf"])
    use_embedding = bool(representation_spec["uses_embedding"])
    use_metadata = bool(representation_spec["uses_metadata"])
    class_count = len(CLASS_LABELS) if task == "classification" else 2
    outer_splits = safe_stratified_group_splits(
        labels,
        groups,
        n_splits=int(cv["outer_folds"]),
        seed=int(cv["outer_seed"]),
        context=f"{combination_id}/outer",
    )
    all_probabilities = np.full(
        (len(labels), class_count),
        np.nan,
        dtype=np.float64,
    )
    all_predictions = np.full(len(labels), -1, dtype=int)
    all_covered = np.zeros(len(labels), dtype=bool)
    fold_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    best_parameters: list[dict[str, Any]] = []
    failure: str | None = None
    started_total = time.perf_counter()

    try:
        for fold, (outer_train, outer_test) in enumerate(outer_splits):
            fit_index, calibration_index, split_audit = fit_calibration_split(
                outer_train,
                labels,
                groups,
                fraction=float(cv["calibration_fraction"]),
                seed=int(cv["outer_seed"]) + 1000 * (fold + 1),
                attempts=int(cv["calibration_search_attempts"]),
                context=f"{combination_id}/outer-{fold}",
                min_fit_groups_per_class=int(
                    cv["fit_min_groups_per_class"]
                ),
                min_calibration_groups_per_class=int(
                    cv["calibration_min_groups_per_class"]
                ),
            )
            inner_labels = np.asarray(labels)[fit_index]
            inner_groups = np.asarray(groups)[fit_index]
            inner_splits = safe_stratified_group_splits(
                inner_labels,
                inner_groups,
                n_splits=int(cv["inner_folds"]),
                seed=int(cv["outer_seed"]) + 10000 + fold,
                context=f"{combination_id}/inner-{fold}",
            )
            pipeline, parameter_grid, weighted = make_pipeline(
                task=task,
                use_tfidf=use_tfidf,
                use_embedding=use_embedding,
                use_metadata=use_metadata,
                classifier_id=classifier_id,
                classifier_specification=classifier_spec(
                    config, classifier_id
                ),
                seed=int(cv["outer_seed"]) + fold,
                class_count=class_count,
                embedding_dimension=384,
            )
            if task == "classification":
                scoring: Any = {
                    "macro_f1": "f1_macro",
                    "accuracy": "accuracy",
                }
                refit: Any = "macro_f1"
            else:
                scoring = {
                    "neg_weighted_cost": DedupCostScorer(
                        float(config["objectives"]["deduplication_false_negative_cost"]),
                        float(config["objectives"]["deduplication_false_positive_cost"]),
                    ),
                    "average_precision": "average_precision",
                }
                refit = "neg_weighted_cost"
            search = GridSearchCV(
                pipeline,
                parameter_grid,
                scoring=scoring,
                refit=refit,
                cv=inner_splits,
                n_jobs=int(config["hardware"]["parallel_model_fits"]),
                return_train_score=False,
                error_score="raise",
            )
            fit_samples = subset(samples, fit_index)
            fit_labels = np.asarray(labels)[fit_index]
            fit_kwargs: dict[str, Any] = {"groups": inner_groups}
            if weighted:
                fit_kwargs["model__sample_weight"] = compute_sample_weight(
                    class_weight="balanced",
                    y=fit_labels,
                )
            fit_started = time.perf_counter()
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", ConvergenceWarning)
                search.fit(fit_samples, fit_labels, **fit_kwargs)
            fit_seconds = time.perf_counter() - fit_started
            convergence_warnings = sum(
                issubclass(item.category, ConvergenceWarning) for item in caught
            )
            base = search.best_estimator_
            calibration_samples = subset(samples, calibration_index)
            calibration_labels = np.asarray(labels)[calibration_index]
            calibration_groups = np.asarray(groups)[calibration_index]
            calibration_started = time.perf_counter()
            calibrated, calibration_oof, calibration_audit = (
                cross_fitted_calibration(
                    base,
                    calibration_samples,
                    calibration_labels,
                    calibration_groups,
                    seed=int(cv["outer_seed"]) + 20000 + fold,
                    folds=int(cv["calibration_oof_folds"]),
                    class_count=class_count,
                    min_groups_per_class=int(
                        cv["calibration_fold_min_groups_per_class"]
                    ),
                    method=str(cv["calibration_method"]),
                )
            )
            calibration_seconds = time.perf_counter() - calibration_started
            if task == "classification":
                policy = select_classification_policy(
                    calibration_oof,
                    calibration_labels,
                    max_risk=float(
                        config["operating_policy"][
                            "classification_max_selective_risk"
                        ]
                    ),
                    min_coverage=float(
                        config["operating_policy"]["classification_min_coverage"]
                    ),
                    obra_min_confidence=float(
                        config["operating_policy"][
                            "classification_obra_min_confidence"
                        ]
                    ),
                )
            else:
                policy = select_dedup_policy(
                    calibration_oof,
                    calibration_labels,
                    config["operating_policy"],
                    false_negative_cost=float(
                        config["objectives"]["deduplication_false_negative_cost"]
                    ),
                    false_positive_cost=float(
                        config["objectives"]["deduplication_false_positive_cost"]
                    ),
                )
            test_samples = subset(samples, outer_test)
            predict_started = time.perf_counter()
            test_probabilities = reorder_probabilities(
                calibrated.predict_proba(test_samples),
                calibrated.classes_,
                class_count,
            )
            predict_seconds = time.perf_counter() - predict_started
            if task == "classification":
                test_predictions, test_covered = apply_classification_policy(
                    test_probabilities, policy
                )
            else:
                test_predictions, test_covered = apply_dedup_policy(
                    test_probabilities, policy
                )
            all_probabilities[outer_test] = test_probabilities
            all_predictions[outer_test] = test_predictions
            all_covered[outer_test] = test_covered
            best_parameters.append(search.best_params_)
            fold_rows.append(
                {
                    "combination_id": combination_id,
                    "task": task,
                    "representation": representation_id,
                    "embedding": embedding_id or "",
                    "classifier": classifier_id,
                    "fold": fold,
                    "outer_train_records": len(outer_train),
                    "outer_test_records": len(outer_test),
                    "outer_train_groups": len(set(np.asarray(groups)[outer_train])),
                    "outer_test_groups": len(set(np.asarray(groups)[outer_test])),
                    "group_overlap": 0,
                    "fit_seconds": fit_seconds,
                    "calibration_seconds": calibration_seconds,
                    "downstream_predict_seconds": predict_seconds,
                    "downstream_predict_ms_per_record": predict_seconds * 1000 / len(outer_test),
                    "prediction_measurement_scope": (
                        "classifier_pipeline_with_precomputed_embedding"
                        if use_embedding
                        else "classifier_pipeline_including_tfidf_transform"
                    ),
                    "best_params": search.best_params_,
                    "best_inner_score": float(search.best_score_),
                    "calibration_policy": {
                        key: value
                        for key, value in policy.items()
                        if key != "curve"
                    },
                    "calibration_split": split_audit,
                    "calibration_folds": calibration_audit,
                    "convergence_warnings": convergence_warnings,
                }
            )
            for local_position, global_index in enumerate(outer_test):
                sample = samples[int(global_index)]
                gold = int(labels[int(global_index)])
                predicted = int(test_predictions[local_position])
                probability = test_probabilities[local_position]
                row = {
                    "combination_id": combination_id,
                    "task": task,
                    "representation": representation_id,
                    "embedding": embedding_id or "",
                    "classifier": classifier_id,
                    "fold": fold,
                    "unit_id": sample["unit_id"],
                    "group": groups[int(global_index)],
                    "gold": (
                        CLASS_LABELS[gold]
                        if task == "classification"
                        else DEDUP_LABELS[gold]
                    ),
                    "prediction": (
                        CLASS_LABELS[predicted]
                        if task == "classification"
                        and bool(test_covered[local_position])
                        and predicted >= 0
                        else "TRIAGEM_MANUAL"
                        if task == "classification"
                        else DEDUP_LABELS[predicted]
                        if bool(test_covered[local_position]) and predicted >= 0
                        else "ABSTENCAO"
                    ),
                    "semantic_prediction": (
                        CLASS_LABELS[int(np.argmax(probability))]
                        if task == "classification"
                        else DEDUP_LABELS[int(np.argmax(probability))]
                    ),
                    "covered": bool(test_covered[local_position]),
                    "correct": bool(
                        test_covered[local_position] and predicted == gold
                    ),
                    "confidence": float(np.max(probability)),
                }
                if task == "classification":
                    semantic_index = int(np.argmax(probability))
                    obra_index = CLASS_LABELS.index("OBRA")
                    triage_index = CLASS_LABELS.index("TRIAGEM_MANUAL")
                    if bool(test_covered[local_position]):
                        review_reason = "AUTOMATIC_DECISION"
                    elif policy.get("threshold") is None:
                        review_reason = "NO_ELIGIBLE_POLICY"
                    elif semantic_index == triage_index:
                        review_reason = "SEMANTIC_TRIAGE"
                    elif (
                        semantic_index == obra_index
                        and float(np.max(probability))
                        < float(policy["obra_threshold"])
                    ):
                        review_reason = "OBRA_BELOW_SAFETY_THRESHOLD"
                    else:
                        review_reason = "LOW_CONFIDENCE"
                else:
                    review_reason = (
                        "POSITIVE_REQUIRES_HUMAN_CONFIRMATION"
                        if int(test_predictions[local_position]) == 1
                        else "AUTOMATIC_NEGATIVE"
                        if int(test_predictions[local_position]) == 0
                        else "AMBIGUOUS_BAND"
                    )
                row["review_reason"] = review_reason
                for class_index in range(class_count):
                    name = (
                        CLASS_LABELS[class_index]
                        if task == "classification"
                        else DEDUP_LABELS[class_index]
                    )
                    row[f"p_{name.lower()}"] = float(probability[class_index])
                prediction_rows.append(row)
            print(
                f"[{combination_id}] fold {fold + 1}/{len(outer_splits)} "
                f"fit={fit_seconds:.2f}s",
                flush=True,
            )
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"

    elapsed_total = time.perf_counter() - started_total
    if failure is None and not np.isfinite(all_probabilities).all():
        failure = "Probabilidades OOF ausentes"
    if failure is None:
        if task == "classification":
            metrics = classification_summary(
                labels,
                all_probabilities,
                all_predictions,
                all_covered,
                groups,
                bootstrap_resamples=int(cv["bootstrap_group_resamples"]),
                seed=int(cv["outer_seed"]),
                confidence_level=float(cv["confidence_level"]),
            )
        else:
            metrics = dedup_summary(
                labels,
                all_probabilities,
                all_predictions,
                all_covered,
                groups,
                false_negative_cost=float(
                    config["objectives"]["deduplication_false_negative_cost"]
                ),
                false_positive_cost=float(
                    config["objectives"]["deduplication_false_positive_cost"]
                ),
                bootstrap_resamples=int(cv["bootstrap_group_resamples"]),
                seed=int(cv["outer_seed"]),
                confidence_level=float(cv["confidence_level"]),
            )
        status = "COMPLETED_DEVELOPMENT_OOF"
    else:
        metrics = {}
        status = "FAILED"
        print(f"[falha] {combination_id}: {failure}", flush=True)
    result = {
        "schema": SCHEMA,
        "protocol_sha256": protocol_sha256,
        "run_fingerprint": run_fingerprint,
        "combination_id": combination_id,
        "task": task,
        "representation": representation_id,
        "embedding": embedding_id,
        "classifier": classifier_id,
        "status": status,
        "failure": failure,
        "scientific_result": False,
        "development_only": True,
        "confirmatory_eligible": False,
        "outer_oof": failure is None,
        "folds": fold_rows,
        "best_parameters": best_parameters,
        "metrics": metrics,
        "elapsed_seconds": elapsed_total,
        "predictions": prediction_rows,
    }
    partial_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_partial = partial_path.with_suffix(
        f".{os.getpid()}.tmp"
    )
    joblib.dump(result, temporary_partial, compress=3)
    os.replace(temporary_partial, partial_path)
    return result


def flatten_result(result: dict[str, Any]) -> dict[str, Any]:
    metrics = result.get("metrics") or {}
    row = {
        "combination_id": result["combination_id"],
        "task": result["task"],
        "representation": result["representation"],
        "embedding": result.get("embedding") or "",
        "classifier": result["classifier"],
        "status": result["status"],
        "failure": result.get("failure") or "",
        "elapsed_seconds": result.get("elapsed_seconds"),
        "mean_fold_fit_seconds": statistics.mean(
            [float(fold["fit_seconds"]) for fold in result.get("folds", [])]
        )
        if result.get("folds")
        else None,
        "mean_downstream_predict_ms_per_record": statistics.mean(
            [
                float(fold["downstream_predict_ms_per_record"])
                for fold in result.get("folds", [])
                if fold.get("downstream_predict_ms_per_record") is not None
            ]
        )
        if any(
            fold.get("downstream_predict_ms_per_record") is not None
            for fold in result.get("folds", [])
        )
        else None,
    }
    for key, value in metrics.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            row[key] = value
        elif key in {
            "confidence_intervals_group_bootstrap",
            "semantic_confidence_intervals_group_bootstrap",
            "operating_confidence_intervals_group_bootstrap",
        } and isinstance(value, dict):
            prefix = {
                "confidence_intervals_group_bootstrap": "group_bootstrap",
                "semantic_confidence_intervals_group_bootstrap": (
                    "semantic_group_bootstrap"
                ),
                "operating_confidence_intervals_group_bootstrap": (
                    "operating_group_bootstrap"
                ),
            }[key]
            for metric, interval in value.items():
                if interval is not None and len(interval) == 2:
                    row[f"{prefix}_{metric}_ci_lower"] = interval[0]
                    row[f"{prefix}_{metric}_ci_upper"] = interval[1]
    return row


def mean_fold_fit_seconds(result: dict[str, Any]) -> float:
    folds = result.get("folds", [])
    if not folds:
        return math.inf
    return statistics.mean(float(fold["fit_seconds"]) for fold in folds)


def selection_rank(
    results: Sequence[dict[str, Any]],
    *,
    task: str,
    policy: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any] | None,
    dict[str, Any] | None,
]:
    eligible_results = [
        result
        for result in results
        if result["task"] == task and result["status"] == "COMPLETED_DEVELOPMENT_OOF"
    ]
    ranked: list[
        tuple[tuple[Any, ...], dict[str, Any], bool, bool, list[str]]
    ] = []
    for result in eligible_results:
        metrics = result["metrics"]
        reasons: list[str] = []
        if task == "classification":
            classification_intervals = metrics.get(
                "confidence_intervals_group_bootstrap", {}
            )
            risk_interval = classification_intervals.get("selective_risk")
            coverage_interval = classification_intervals.get("coverage")
            risk_upper = (
                float(risk_interval[1]) if risk_interval is not None else None
            )
            coverage_lower = (
                float(coverage_interval[0])
                if coverage_interval is not None
                else None
            )
            point_eligible = (
                int(metrics["automatic_non_obra_as_obra"])
                <= int(policy["classification_max_automatic_non_obra_as_obra"])
                and metrics["automatic_risk"] is not None
                and float(metrics["automatic_risk"])
                <= float(policy["classification_max_selective_risk"])
                and float(metrics["automatic_coverage"])
                >= float(policy["classification_min_coverage"])
            )
            critical_upper = metrics.get(
                "automatic_non_obra_as_obra_group_rate_upper"
            )
            confidence_qualified = bool(
                point_eligible
                and critical_upper is not None
                and float(critical_upper)
                <= float(policy["classification_max_critical_group_rate_upper"])
                and risk_upper is not None
                and risk_upper
                <= float(policy["classification_max_selective_risk"])
                and coverage_lower is not None
                and coverage_lower
                >= float(policy["classification_min_coverage"])
            )
            if (
                int(metrics["automatic_non_obra_as_obra"])
                > int(policy["classification_max_automatic_non_obra_as_obra"])
            ):
                reasons.append("automatic_non_obra_as_obra")
            if (
                metrics["automatic_risk"] is None
                or float(metrics["automatic_risk"])
                > float(policy["classification_max_selective_risk"])
            ):
                reasons.append("classification_selective_risk")
            if float(metrics["automatic_coverage"]) < float(
                policy["classification_min_coverage"]
            ):
                reasons.append("classification_coverage")
            if not confidence_qualified:
                reasons.append("classification_critical_upper_confidence")
            if (
                risk_upper is None
                or risk_upper
                > float(policy["classification_max_selective_risk"])
            ):
                reasons.append("classification_risk_upper_confidence")
            if (
                coverage_lower is None
                or coverage_lower
                < float(policy["classification_min_coverage"])
            ):
                reasons.append("classification_coverage_lower_confidence")
            key = (
                0 if confidence_qualified else 1 if point_eligible else 2,
                -float(metrics["macro_f1"]),
                -float(metrics["obra_recall"]),
                -float(metrics["automatic_coverage"]),
                float(metrics["log_loss"]),
                mean_fold_fit_seconds(result),
                str(result["combination_id"]),
            )
        else:
            dedup_intervals = metrics.get(
                "operating_confidence_intervals_group_bootstrap", {}
            )
            fnr_interval = dedup_intervals.get("false_negative_rate")
            fpr_interval = dedup_intervals.get("false_positive_rate")
            npv_interval = dedup_intervals.get("negative_predictive_value")
            precision_interval = dedup_intervals.get("precision")
            decision_coverage_interval = dedup_intervals.get(
                "decision_coverage"
            )
            fnr_upper = float(fnr_interval[1]) if fnr_interval else None
            fpr_upper = float(fpr_interval[1]) if fpr_interval else None
            npv_lower = float(npv_interval[0]) if npv_interval else None
            precision_lower = (
                float(precision_interval[0]) if precision_interval else None
            )
            decision_coverage_lower = (
                float(decision_coverage_interval[0])
                if decision_coverage_interval
                else None
            )
            point_eligible = bool(
                metrics["automatic_false_negative_rate"]
                <= float(policy["deduplication_max_false_negative_rate"])
                and metrics["negative_predictive_value"] is not None
                and metrics["negative_predictive_value"]
                >= float(policy["deduplication_min_negative_predictive_value"])
                and metrics["automatic_false_positive_rate"]
                <= float(policy["deduplication_max_false_positive_rate"])
                and metrics["precision"] is not None
                and metrics["precision"] >= float(policy["deduplication_min_precision"])
                and metrics["decision_coverage"]
                >= float(policy["deduplication_min_coverage"])
            )
            fn_upper = metrics.get("false_negative_group_rate_upper")
            fp_upper = metrics.get("false_positive_group_rate_upper")
            confidence_qualified = bool(
                point_eligible
                and fn_upper is not None
                and float(fn_upper)
                <= float(policy["deduplication_max_false_negative_rate"])
                and fp_upper is not None
                and float(fp_upper)
                <= float(policy["deduplication_max_false_positive_rate"])
                and fnr_upper is not None
                and fnr_upper
                <= float(policy["deduplication_max_false_negative_rate"])
                and fpr_upper is not None
                and fpr_upper
                <= float(policy["deduplication_max_false_positive_rate"])
                and npv_lower is not None
                and npv_lower
                >= float(policy["deduplication_min_negative_predictive_value"])
                and precision_lower is not None
                and precision_lower
                >= float(policy["deduplication_min_precision"])
                and decision_coverage_lower is not None
                and decision_coverage_lower
                >= float(policy["deduplication_min_coverage"])
            )
            if not point_eligible:
                reasons.append("deduplication_operating_gate")
            if not confidence_qualified:
                reasons.append("deduplication_safety_upper_confidence")
            key = (
                0 if confidence_qualified else 1 if point_eligible else 2,
                int(metrics["fn"]),
                float(metrics["weighted_error_fn5_fp1_total"]),
                -float(metrics["negative_predictive_value"] or 0.0),
                -float(metrics["precision"] or 0.0),
                -float(metrics["full_automation_coverage"]),
                -float(metrics["decision_coverage"]),
                mean_fold_fit_seconds(result),
                str(result["combination_id"]),
            )
        ranked.append(
            (key, result, confidence_qualified, point_eligible, reasons)
        )
    ranked.sort(key=lambda item: item[0])
    rows: list[dict[str, Any]] = []
    for rank, (_, result, confidence_qualified, point_eligible, reasons) in enumerate(
        ranked, start=1
    ):
        rows.append(
            {
                "rank": rank,
                "task": task,
                "combination_id": result["combination_id"],
                "eligible": confidence_qualified,
                "confidence_qualified": confidence_qualified,
                "provisional_point_eligible": point_eligible,
                "evidence_status": (
                    "PASS"
                    if confidence_qualified
                    else "UNDERPOWERED"
                    if point_eligible
                    else "FAIL"
                ),
                "exclusion_reasons": reasons,
                **flatten_result(result),
            }
        )
    confidence_qualified_winner = next(
        (
            result
            for _, result, confidence_qualified, _, _ in ranked
            if confidence_qualified
        ),
        None,
    )
    provisional_point_candidate = next(
        (
            result
            for _, result, _, point_eligible, _ in ranked
            if point_eligible
        ),
        None,
    )
    return rows, confidence_qualified_winner, provisional_point_candidate


def holm_adjust(p_values: Sequence[float]) -> list[float]:
    count = len(p_values)
    order = sorted(range(count), key=lambda index: p_values[index])
    adjusted = [1.0] * count
    running = 0.0
    for rank, index in enumerate(order):
        value = min(1.0, (count - rank) * p_values[index])
        running = max(running, value)
        adjusted[index] = running
    return adjusted


def paired_group_rows(
    results: Sequence[dict[str, Any]],
    *,
    comparisons: dict[str, list[dict[str, str]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    by_id = {result["combination_id"]: result for result in results}
    for task, task_comparisons in comparisons.items():
        task_rows: list[dict[str, Any]] = []
        p_values: list[float] = []
        for comparison in task_comparisons:
            baseline = by_id.get(comparison["baseline"])
            result = by_id.get(comparison["candidate"])
            if (
                baseline is None
                or result is None
                or baseline["status"] != "COMPLETED_DEVELOPMENT_OOF"
                or result["status"] != "COMPLETED_DEVELOPMENT_OOF"
            ):
                continue
            baseline_units = [row["unit_id"] for row in baseline["predictions"]]
            candidate_units = [row["unit_id"] for row in result["predictions"]]
            if (
                len(set(baseline_units)) != len(baseline_units)
                or len(set(candidate_units)) != len(candidate_units)
            ):
                raise SelectionGuardError(
                    "Comparação pareada encontrou unit_id duplicado"
                )
            baseline_predictions = {
                row["unit_id"]: row for row in baseline["predictions"]
            }
            candidate = {row["unit_id"]: row for row in result["predictions"]}
            if set(candidate) != set(baseline_predictions):
                raise SelectionGuardError(
                    "Comparação pareada encontrou unidades divergentes"
                )
            differences_by_group: dict[str, list[float]] = defaultdict(list)
            for unit_id, baseline_row in baseline_predictions.items():
                candidate_row = candidate[unit_id]
                if any(
                    baseline_row[key] != candidate_row[key]
                    for key in ("gold", "group", "fold")
                ):
                    raise SelectionGuardError(
                        "Comparação pareada encontrou gold/grupo/dobra divergente"
                    )
                baseline_correct = (
                    baseline_row["semantic_prediction"] == baseline_row["gold"]
                )
                candidate_correct = (
                    candidate_row["semantic_prediction"] == candidate_row["gold"]
                )
                differences_by_group[str(baseline_row["group"])].append(
                    float(candidate_correct) - float(baseline_correct)
                )
            group_differences = np.asarray(
                [
                    float(np.mean(values))
                    for _, values in sorted(differences_by_group.items())
                ],
                dtype=np.float64,
            )
            if np.allclose(group_differences, 0.0):
                statistic = 0.0
                p_value = 1.0
            else:
                test = wilcoxon(
                    group_differences,
                    zero_method="pratt",
                    correction=False,
                    alternative="two-sided",
                    method="auto",
                )
                statistic = float(test.statistic)
                p_value = float(test.pvalue)
            task_rows.append(
                {
                    "contrast_id": comparison["id"],
                    "task": task,
                    "baseline": baseline["combination_id"],
                    "candidate": result["combination_id"],
                    "independent_groups": len(group_differences),
                    "mean_group_accuracy_difference_candidate_minus_baseline": (
                        float(np.mean(group_differences))
                    ),
                    "median_group_accuracy_difference_candidate_minus_baseline": (
                        float(np.median(group_differences))
                    ),
                    "groups_candidate_better": int(
                        np.sum(group_differences > 0)
                    ),
                    "groups_baseline_better": int(
                        np.sum(group_differences < 0)
                    ),
                    "groups_tied": int(np.sum(group_differences == 0)),
                    "wilcoxon_pratt_statistic": statistic,
                    "wilcoxon_pratt_p": p_value,
                    "scope": "semantic_accuracy_descriptive_only",
                }
            )
            p_values.append(p_value)
        adjusted = holm_adjust(p_values)
        for row, value in zip(task_rows, adjusted):
            row["wilcoxon_pratt_holm_adjusted_p"] = value
        rows.extend(task_rows)
    return rows


def _classification_operating_metrics(
    rows: Sequence[dict[str, Any]],
) -> dict[str, float | None]:
    gold = np.asarray(
        [CLASS_LABELS.index(str(row["gold"])) for row in rows], dtype=int
    )
    semantic = np.asarray(
        [
            CLASS_LABELS.index(str(row["semantic_prediction"]))
            for row in rows
        ],
        dtype=int,
    )
    covered = np.asarray([bool(row["covered"]) for row in rows], dtype=bool)
    errors = covered & (semantic != gold)
    obra_index = CLASS_LABELS.index("OBRA")
    non_obra_exposed = covered & (gold != obra_index)
    critical = non_obra_exposed & (semantic == obra_index)
    return {
        "semantic_accuracy": float(np.mean(semantic == gold)),
        "semantic_macro_f1": float(
            f1_score(
                gold,
                semantic,
                labels=list(range(len(CLASS_LABELS))),
                average="macro",
                zero_division=0,
            )
        ),
        "automatic_coverage": float(np.mean(covered)),
        "selective_risk": (
            float(np.sum(errors) / np.sum(covered)) if np.any(covered) else None
        ),
        "critical_non_obra_as_obra_rate": (
            float(np.sum(critical) / np.sum(non_obra_exposed))
            if np.any(non_obra_exposed)
            else None
        ),
    }


def _dedup_operating_metrics(
    rows: Sequence[dict[str, Any]],
    *,
    false_negative_cost: float,
    false_positive_cost: float,
) -> dict[str, float | None]:
    gold = np.asarray(
        [DEDUP_LABELS.index(str(row["gold"])) for row in rows], dtype=int
    )
    semantic = np.asarray(
        [
            DEDUP_LABELS.index(str(row["semantic_prediction"]))
            for row in rows
        ],
        dtype=int,
    )
    decision = np.asarray(
        [
            DEDUP_LABELS.index(str(row["prediction"]))
            if str(row["prediction"]) in DEDUP_LABELS
            else -1
            for row in rows
        ],
        dtype=int,
    )
    false_negative = (gold == 1) & (decision == 0)
    false_positive = (gold == 0) & (decision == 1)
    positives = gold == 1
    negatives = gold == 0
    return {
        "semantic_accuracy": float(np.mean(semantic == gold)),
        "weighted_error_fn5_fp1_per_record": float(
            (
                false_negative_cost * np.sum(false_negative)
                + false_positive_cost * np.sum(false_positive)
            )
            / len(gold)
        ),
        "automatic_false_negative_rate": (
            float(np.sum(false_negative) / np.sum(positives))
            if np.any(positives)
            else None
        ),
        "automatic_false_positive_rate": (
            float(np.sum(false_positive) / np.sum(negatives))
            if np.any(negatives)
            else None
        ),
        "decision_coverage": float(np.mean(decision >= 0)),
        "full_automation_coverage": float(np.mean(decision == 0)),
    }


def paired_objective_rows(
    results: Sequence[dict[str, Any]],
    *,
    baseline_ids: dict[str, str],
    comparison_candidates: dict[str, dict[str, str]],
    resamples: int,
    confidence_level: float,
    seed: int,
    false_negative_cost: float,
    false_positive_cost: float,
) -> list[dict[str, Any]]:
    by_id = {result["combination_id"]: result for result in results}
    output: list[dict[str, Any]] = []
    alpha = 1.0 - confidence_level
    directions = {
        "semantic_accuracy": "higher",
        "semantic_macro_f1": "higher",
        "automatic_coverage": "higher",
        "selective_risk": "lower",
        "critical_non_obra_as_obra_rate": "lower",
        "weighted_error_fn5_fp1_per_record": "lower",
        "automatic_false_negative_rate": "lower",
        "automatic_false_positive_rate": "lower",
        "decision_coverage": "higher",
        "full_automation_coverage": "higher",
    }
    task_offsets = {"classification": 0, "deduplication": 1}
    for task in baseline_ids:
        task_offset = task_offsets[task]
        baseline = by_id.get(baseline_ids[task])
        if baseline is None or baseline["status"] != "COMPLETED_DEVELOPMENT_OOF":
            continue
        baseline_units = [row["unit_id"] for row in baseline["predictions"]]
        if len(set(baseline_units)) != len(baseline_units):
            raise SelectionGuardError(
                "Bootstrap pareado encontrou unit_id duplicado no baseline"
            )
        baseline_by_unit = {
            row["unit_id"]: row for row in baseline["predictions"]
        }
        ordered_units = sorted(baseline_by_unit)
        baseline_rows = [baseline_by_unit[unit] for unit in ordered_units]
        groups = np.asarray(
            [str(row["group"]) for row in baseline_rows], dtype=object
        )
        unique_groups = sorted(set(groups.tolist()))
        indices_by_group = {
            group: np.flatnonzero(groups == group) for group in unique_groups
        }
        rng = np.random.default_rng(seed + task_offset * 100000)
        bootstrap_group_draws = [
            rng.choice(unique_groups, size=len(unique_groups), replace=True)
            for _ in range(resamples)
        ]
        metric_function: Callable[..., dict[str, float | None]]
        metric_kwargs: dict[str, Any]
        if task == "classification":
            metric_function = _classification_operating_metrics
            metric_kwargs = {}
        else:
            metric_function = _dedup_operating_metrics
            metric_kwargs = {
                "false_negative_cost": false_negative_cost,
                "false_positive_cost": false_positive_cost,
            }
        baseline_point = metric_function(baseline_rows, **metric_kwargs)
        for result in results:
            if (
                result["task"] != task
                or result["status"] != "COMPLETED_DEVELOPMENT_OOF"
                or result["combination_id"] == baseline["combination_id"]
                or result["combination_id"]
                not in comparison_candidates[task]
            ):
                continue
            candidate_by_unit = {
                row["unit_id"]: row for row in result["predictions"]
            }
            candidate_units = [row["unit_id"] for row in result["predictions"]]
            if len(set(candidate_units)) != len(candidate_units):
                raise SelectionGuardError(
                    "Bootstrap pareado encontrou unit_id duplicado no candidato"
                )
            if set(candidate_by_unit) != set(ordered_units):
                raise SelectionGuardError(
                    "Bootstrap pareado encontrou unidades divergentes"
                )
            candidate_rows = [candidate_by_unit[unit] for unit in ordered_units]
            if any(
                any(
                    candidate[key] != reference[key]
                    for key in ("gold", "group", "fold")
                )
                for candidate, reference in zip(candidate_rows, baseline_rows)
            ):
                raise SelectionGuardError(
                    "Bootstrap pareado encontrou gold/grupo/dobra divergente"
                )
            candidate_point = metric_function(candidate_rows, **metric_kwargs)
            differences: dict[str, list[float]] = {
                metric: [] for metric in baseline_point
            }
            for draw in bootstrap_group_draws:
                sampled = np.concatenate(
                    [indices_by_group[str(group)] for group in draw]
                )
                sampled_baseline = [baseline_rows[int(index)] for index in sampled]
                sampled_candidate = [candidate_rows[int(index)] for index in sampled]
                baseline_metrics = metric_function(
                    sampled_baseline, **metric_kwargs
                )
                candidate_metrics = metric_function(
                    sampled_candidate, **metric_kwargs
                )
                for metric in differences:
                    baseline_value = baseline_metrics[metric]
                    candidate_value = candidate_metrics[metric]
                    if baseline_value is not None and candidate_value is not None:
                        differences[metric].append(
                            float(candidate_value) - float(baseline_value)
                        )
            for metric, values in differences.items():
                baseline_value = baseline_point[metric]
                candidate_value = candidate_point[metric]
                if baseline_value is None or candidate_value is None or not values:
                    lower = upper = None
                    difference = None
                else:
                    difference = float(candidate_value) - float(baseline_value)
                    lower = float(np.percentile(values, 100.0 * alpha / 2.0))
                    upper = float(
                        np.percentile(values, 100.0 * (1.0 - alpha / 2.0))
                    )
                output.append(
                    {
                        "contrast_id": comparison_candidates[task][
                            result["combination_id"]
                        ],
                        "task": task,
                        "baseline": baseline["combination_id"],
                        "candidate": result["combination_id"],
                        "metric": metric,
                        "better_direction": directions[metric],
                        "baseline_value": baseline_value,
                        "candidate_value": candidate_value,
                        "difference_candidate_minus_baseline": difference,
                        "difference_ci_lower": lower,
                        "difference_ci_upper": upper,
                        "confidence_level": confidence_level,
                        "bootstrap_resamples": resamples,
                        "independent_groups": len(unique_groups),
                        "inference_scope": "paired_cluster_bootstrap_development",
                        "equivalence_test": False,
                    }
                )
    return output


def retrieval_rows(
    pairs: Sequence[tuple[dict[str, Any], dict[str, Any], str]],
    *,
    embedding_maps: dict[str, dict[str, dict[str, np.ndarray]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    positives = [pair for pair in pairs if pair[2] == "DUPLICADO"]
    anchors_by_id: dict[str, dict[str, Any]] = {}
    for _, reference, _ in pairs:
        anchors_by_id[str(reference["case_id"])] = reference
    candidate_ids = sorted(anchors_by_id)
    candidates = [anchors_by_id[case_id] for case_id in candidate_ids]
    candidate_texts = [training.model_text(case) for case in candidates]
    query_texts = [training.model_text(pair[0]) for pair in positives]
    expected_ids = [str(pair[1]["case_id"]) for pair in positives]
    detailed: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []

    vectorizer = training.build_text_vectorizer()
    passage_matrix = vectorizer.fit_transform(candidate_texts).tocsr()
    query_matrix = vectorizer.transform(query_texts).tocsr()
    tfidf_scores = (query_matrix @ passage_matrix.T).toarray()
    representations: list[tuple[str, np.ndarray]] = [("tfidf", tfidf_scores)]
    for model_id, maps in embedding_maps.items():
        query_vectors = np.vstack(
            [maps["retrieval_query"][text] for text in query_texts]
        )
        passage_vectors = np.vstack(
            [maps["retrieval_passage"][text] for text in candidate_texts]
        )
        representations.append((model_id, query_vectors @ passage_vectors.T))

    for representation, scores in representations:
        ranks: list[int] = []
        reciprocal: list[float] = []
        ndcg20: list[float] = []
        for index, expected_id in enumerate(expected_ids):
            order = sorted(
                range(len(candidate_ids)),
                key=lambda item: (-float(scores[index, item]), candidate_ids[item]),
            )
            expected_index = candidate_ids.index(expected_id)
            rank = order.index(expected_index) + 1
            ranks.append(rank)
            reciprocal.append(1.0 / rank)
            ndcg20.append(1.0 / math.log2(rank + 1) if rank <= 20 else 0.0)
            detailed.append(
                {
                    "representation": representation,
                    "query_case_id": positives[index][0]["case_id"],
                    "expected_reference_case_id": expected_id,
                    "rank": rank,
                    "reciprocal_rank": 1.0 / rank,
                    "hit_at_1": rank <= 1,
                    "hit_at_5": rank <= 5,
                    "hit_at_20": rank <= 20,
                }
            )
        summaries.append(
            {
                "representation": representation,
                "queries": len(ranks),
                "candidates_per_query": len(candidate_ids),
                "recall_at_1": float(np.mean(np.asarray(ranks) <= 1)),
                "recall_at_5": float(np.mean(np.asarray(ranks) <= 5)),
                "recall_at_20": float(np.mean(np.asarray(ranks) <= 20)),
                "mrr": float(np.mean(reciprocal)),
                "ndcg_at_20": float(np.mean(ndcg20)),
                "median_rank": float(np.median(ranks)),
            }
        )
    return summaries, detailed


def mode_parameters(results: dict[str, Any]) -> dict[str, Any]:
    values = [canonical_json(value) for value in results.get("best_parameters", [])]
    if not values:
        return {}
    selected = sorted(Counter(values).items(), key=lambda item: (-item[1], item[0]))[0][0]
    parameters = json.loads(selected)
    hidden = parameters.get("model__hidden_layer_sizes")
    if isinstance(hidden, list):
        parameters["model__hidden_layer_sizes"] = tuple(hidden)
    return parameters


def feature_family(name: str) -> str:
    if name.startswith("tfidf__word__") or name.startswith("tfidf_abs__word__") or name.startswith("tfidf_overlap__word__"):
        return "tfidf_word"
    if name.startswith("tfidf__char__") or name.startswith("tfidf_abs__char__") or name.startswith("tfidf_overlap__char__"):
        return "tfidf_character"
    if name.startswith("tfidf"):
        return "tfidf_other"
    if name.startswith("embedding"):
        return "embedding"
    if name.startswith("metadata"):
        return "metadata"
    return "other"


def fit_final_base(
    result: dict[str, Any],
    *,
    samples: list[dict[str, Any]],
    labels: list[int],
    config: dict[str, Any],
) -> Pipeline:
    representation_spec = config["representations"][result["representation"]]
    use_tfidf = bool(representation_spec["uses_tfidf"])
    use_embedding = bool(representation_spec["uses_embedding"])
    use_metadata = bool(representation_spec["uses_metadata"])
    class_count = len(CLASS_LABELS) if result["task"] == "classification" else 2
    pipeline, _, weighted = make_pipeline(
        task=result["task"],
        use_tfidf=use_tfidf,
        use_embedding=use_embedding,
        use_metadata=use_metadata,
        classifier_id=result["classifier"],
        classifier_specification=classifier_spec(
            config, result["classifier"]
        ),
        seed=int(config["xai"]["random_seed"]),
        class_count=class_count,
        embedding_dimension=384,
    )
    parameters = mode_parameters(result)
    if parameters:
        pipeline.set_params(**parameters)
    kwargs: dict[str, Any] = {}
    if weighted:
        kwargs["model__sample_weight"] = compute_sample_weight(
            class_weight="balanced",
            y=np.asarray(labels),
        )
    pipeline.fit(samples, labels, **kwargs)
    return pipeline


def normalize_shap_values(values: Any, class_count: int) -> np.ndarray:
    if isinstance(values, list):
        return np.stack([np.asarray(item) for item in values], axis=-1)
    array = np.asarray(getattr(values, "values", values))
    if array.ndim == 2:
        return array[:, :, np.newaxis]
    if array.ndim == 3:
        if array.shape[-1] == class_count:
            return array
        if array.shape[0] == class_count:
            return np.moveaxis(array, 0, -1)
    raise SelectionGuardError(f"Shape SHAP não reconhecido: {array.shape}")


def stratified_explain_indices(
    labels: Sequence[int],
    groups: Sequence[str],
    *,
    count: int,
    seed: int,
) -> np.ndarray:
    if count <= 0:
        raise SelectionGuardError("XAI exige ao menos um registro")
    label_array = np.asarray(labels, dtype=int)
    group_array = np.asarray(groups, dtype=object)
    rng = np.random.default_rng(seed)
    selected: list[int] = []
    used_groups: set[str] = set()
    for label in sorted(set(label_array.tolist())):
        candidates = np.flatnonzero(label_array == label)
        candidates = rng.permutation(candidates)
        chosen = next(
            (
                int(index)
                for index in candidates
                if str(group_array[int(index)]) not in used_groups
            ),
            int(candidates[0]),
        )
        selected.append(chosen)
        used_groups.add(str(group_array[chosen]))
    remaining = rng.permutation(len(labels))
    for index_value in remaining:
        index = int(index_value)
        if len(selected) >= min(count, len(labels)):
            break
        group = str(group_array[index])
        if index not in selected and group not in used_groups:
            selected.append(index)
            used_groups.add(group)
    if len(selected) < min(count, len(labels)):
        for index_value in remaining:
            index = int(index_value)
            if len(selected) >= min(count, len(labels)):
                break
            if index not in selected:
                selected.append(index)
    return np.asarray(selected[: min(count, len(labels))], dtype=int)


def grouped_permutation_xai(
    *,
    winner: dict[str, Any],
    model: BaseEstimator,
    features: sparse.csr_matrix,
    feature_names: Sequence[str],
    explain_index: np.ndarray,
    labels: Sequence[int],
    seed: int,
    repeats: int,
) -> dict[str, Any]:
    matrix = np.asarray(features[explain_index].toarray(), dtype=np.float32)
    gold = np.asarray(labels, dtype=int)[explain_index]
    baseline_prediction = np.asarray(model.predict(matrix), dtype=int)
    baseline_score = float(
        f1_score(gold, baseline_prediction, average="macro", zero_division=0)
    )
    columns_by_family: dict[str, list[int]] = defaultdict(list)
    for column, name in enumerate(feature_names):
        columns_by_family[feature_family(str(name))].append(column)
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    for family_name, columns in sorted(columns_by_family.items()):
        scores: list[float] = []
        for _ in range(repeats):
            permuted = matrix.copy()
            order = rng.permutation(len(permuted))
            permuted[:, columns] = permuted[order][:, columns]
            prediction = np.asarray(model.predict(permuted), dtype=int)
            scores.append(
                float(f1_score(gold, prediction, average="macro", zero_division=0))
            )
        mean_permuted = float(np.mean(scores))
        rows.append(
            {
                "family": family_name,
                "baseline_macro_f1": baseline_score,
                "mean_permuted_macro_f1": mean_permuted,
                "macro_f1_drop": baseline_score - mean_permuted,
                "repeats": repeats,
            }
        )
    positive_total = sum(max(0.0, row["macro_f1_drop"]) for row in rows)
    for row in rows:
        row["fraction"] = (
            max(0.0, row["macro_f1_drop"]) / positive_total
            if positive_total
            else 0.0
        )
    return {
        "status": "COMPLETED_FALLBACK",
        "task": winner["task"],
        "combination_id": winner["combination_id"],
        "method": "GroupedPermutationImportance",
        "explains": "base_model_macro_f1_association_before_calibration_and_threshold",
        "causal_interpretation": False,
        "feature_count": len(feature_names),
        "family_importance": rows,
        "global_top_features": [],
        "local_explanations": [],
    }


def generate_xai(
    winner: dict[str, Any],
    *,
    samples: list[dict[str, Any]],
    labels: list[int],
    groups: list[str],
    config: dict[str, Any],
) -> dict[str, Any]:
    import shap

    pipeline = fit_final_base(
        winner,
        samples=samples,
        labels=labels,
        config=config,
    )
    features = pipeline.named_steps["features"].transform(samples).tocsr()
    feature_names = pipeline.named_steps["features"].get_feature_names_out().tolist()
    model = pipeline.named_steps["model"]
    class_count = len(CLASS_LABELS) if winner["task"] == "classification" else 2
    rng = np.random.default_rng(int(config["xai"]["random_seed"]))
    unique_groups = sorted(set(groups))
    background_group_count = min(
        int(config["xai"]["background_groups"]), len(unique_groups)
    )
    chosen_groups = rng.choice(
        unique_groups, size=background_group_count, replace=False
    ).tolist()
    background_index = np.asarray(
        [
            next(index for index, group in enumerate(groups) if group == chosen)
            for chosen in chosen_groups
        ],
        dtype=int,
    )
    explain_count = min(
        int(config["xai"]["explained_records_per_task"]), len(samples)
    )
    explain_index = stratified_explain_indices(
        labels,
        groups,
        count=explain_count,
        seed=int(config["xai"]["random_seed"]) + 1,
    )
    family = winner["classifier"]
    if family in {"logistic_regression", "linear_svm"}:
        explainer = shap.LinearExplainer(
            model,
            features[background_index],
            feature_perturbation="interventional",
        )
        values = explainer(features[explain_index])
        method = "LinearExplainer"
    elif family in {"decision_tree", "xgboost"}:
        explainer = shap.TreeExplainer(model)
        explain_features = features[explain_index]
        if family == "decision_tree":
            explain_features = explain_features.toarray()
        values = explainer(explain_features)
        method = "TreeExplainer"
    else:
        fallback = grouped_permutation_xai(
            winner=winner,
            model=model,
            features=features,
            feature_names=feature_names,
            explain_index=explain_index,
            labels=labels,
            seed=int(config["xai"]["random_seed"]) + 2,
            repeats=5,
        )
        fallback["background_groups"] = chosen_groups
        fallback["background_groups_sha256"] = canonical_sha256(chosen_groups)
        fallback["explained_unit_ids"] = [
            samples[int(index)]["unit_id"] for index in explain_index
        ]
        fallback["explained_labels"] = [
            int(labels[int(index)]) for index in explain_index
        ]
        return fallback
    shap_array = normalize_shap_values(values, class_count)
    mean_abs_feature = np.mean(np.abs(shap_array), axis=(0, 2))
    family_totals: dict[str, float] = defaultdict(float)
    for index, name in enumerate(feature_names):
        family_totals[feature_family(name)] += float(mean_abs_feature[index])
    total = sum(family_totals.values())
    global_rows = [
        {
            "feature": feature_names[index],
            "family": feature_family(feature_names[index]),
            "mean_abs_shap": float(mean_abs_feature[index]),
        }
        for index in np.argsort(-mean_abs_feature)[:100]
    ]
    local_rows: list[dict[str, Any]] = []
    raw_base_values = np.asarray(
        getattr(values, "base_values", np.nan),
        dtype=np.float64,
    )
    if raw_base_values.ndim == 0:
        base_values = np.full(
            (len(explain_index), shap_array.shape[2]),
            float(raw_base_values),
        )
    elif raw_base_values.ndim == 1:
        if len(raw_base_values) == len(explain_index):
            base_values = raw_base_values[:, np.newaxis]
        else:
            base_values = np.tile(
                raw_base_values[np.newaxis, :],
                (len(explain_index), 1),
            )
    else:
        base_values = raw_base_values.reshape(len(explain_index), -1)
    if winner["task"] == "deduplication":
        target_classes = np.ones(len(explain_index), dtype=int)
    else:
        target_classes = np.asarray(
            model.predict(features[explain_index]),
            dtype=int,
        )
    explained_features = features[explain_index]
    if family in {"logistic_regression", "linear_svm"}:
        model_outputs = np.asarray(
            model.decision_function(explained_features),
            dtype=np.float64,
        )
    elif family == "decision_tree":
        model_outputs = np.asarray(
            model.predict_proba(explained_features.toarray()),
            dtype=np.float64,
        )
    else:
        model_outputs = np.asarray(
            model.predict(explained_features, output_margin=True),
            dtype=np.float64,
        )
    for row_position, sample_index in enumerate(explain_index):
        target_class = int(target_classes[row_position])
        if shap_array.shape[2] == 1 and class_count == 2:
            target_class = 1
        target_channel = (
            0 if shap_array.shape[2] == 1 else target_class
        )
        signed_values = shap_array[row_position, :, target_channel]
        positive = np.argsort(-signed_values)[:5]
        negative = np.argsort(signed_values)[:5]
        base_channel = (
            0 if base_values.shape[1] == 1 else target_channel
        )
        base_value = float(base_values[row_position, base_channel])
        reconstructed_score = base_value + float(np.sum(signed_values))
        if model_outputs.ndim == 1:
            model_output = float(model_outputs[row_position])
        else:
            model_output = float(model_outputs[row_position, target_class])
        local_rows.append(
            {
                "unit_id": samples[int(sample_index)]["unit_id"],
                "gold": int(labels[int(sample_index)]),
                "target_class": (
                    CLASS_LABELS[target_class]
                    if winner["task"] == "classification"
                    else "DUPLICADO"
                ),
                "base_value": base_value,
                "base_model_output": model_output,
                "reconstructed_base_model_output": reconstructed_score,
                "additivity_residual": reconstructed_score - model_output,
                "top_positive_features": [
                    {
                        "feature": feature_names[int(index)],
                        "family": feature_family(feature_names[int(index)]),
                        "signed_shap": float(signed_values[int(index)]),
                    }
                    for index in positive
                    if signed_values[int(index)] > 0
                ],
                "top_negative_features": [
                    {
                        "feature": feature_names[int(index)],
                        "family": feature_family(feature_names[int(index)]),
                        "signed_shap": float(signed_values[int(index)]),
                    }
                    for index in negative
                    if signed_values[int(index)] < 0
                ],
            }
        )
    maximum_residual = max(
        (abs(float(row["additivity_residual"])) for row in local_rows),
        default=0.0,
    )
    tolerance = float(config["xai"]["max_absolute_additivity_residual"])
    if not math.isfinite(maximum_residual) or maximum_residual > tolerance:
        raise SelectionGuardError(
            "SHAP violou aditividade: "
            f"resíduo={maximum_residual:.6g}, tolerância={tolerance:.6g}"
        )
    return {
        "status": "COMPLETED",
        "task": winner["task"],
        "combination_id": winner["combination_id"],
        "method": method,
        "explains": "base_model_score_before_sigmoid_calibration_and_threshold",
        "causal_interpretation": False,
        "background_groups": chosen_groups,
        "background_groups_sha256": canonical_sha256(chosen_groups),
        "explained_unit_ids": [
            samples[int(index)]["unit_id"] for index in explain_index
        ],
        "explained_labels": [
            int(labels[int(index)]) for index in explain_index
        ],
        "max_absolute_additivity_residual": maximum_residual,
        "feature_count": len(feature_names),
        "family_importance": [
            {
                "family": key,
                "mean_abs_shap_sum": value,
                "fraction": value / total if total else None,
            }
            for key, value in sorted(
                family_totals.items(), key=lambda item: -item[1]
            )
        ],
        "global_top_features": global_rows,
        "local_explanations": local_rows,
    }


def benchmark_finalist_performance(
    candidate: dict[str, Any],
    *,
    samples: list[dict[str, Any]],
    labels: list[int],
    groups: list[str],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    benchmark = config["performance_benchmark"]
    measured_count = min(
        int(benchmark["measured_records_per_task"]), len(samples)
    )
    indices = stratified_explain_indices(
        labels,
        groups,
        count=measured_count,
        seed=int(benchmark["random_seed"]),
    )
    fit_started = time.perf_counter()
    pipeline = fit_final_base(
        candidate,
        samples=samples,
        labels=labels,
        config=config,
    )
    final_fit_seconds = time.perf_counter() - fit_started
    representation = config["representations"][candidate["representation"]]
    use_embedding = bool(representation["uses_embedding"])
    encoder: Any = None
    prefix = ""
    load_seconds = 0.0
    load_peak_rss_mb: float | None = None
    if use_embedding:
        from sentence_transformers import SentenceTransformer

        embedding = next(
            item
            for item in config["embeddings"]
            if item["id"] == candidate["embedding"]
        )
        prefix = str(embedding["symmetric_prefix"])
        load_started = time.perf_counter()
        with PeakRssSampler() as sampler:
            encoder = SentenceTransformer(
                str((PROJECT_ROOT / embedding["local_path"]).resolve()),
                device="cpu",
                local_files_only=True,
            )
        load_seconds = time.perf_counter() - load_started
        load_peak_rss_mb = sampler.peak / 1024 / 1024

    def encode(texts: Sequence[str]) -> np.ndarray:
        if encoder is None:
            raise SelectionGuardError("Encoder ausente no cenário com embedding")
        return np.asarray(
            encoder.encode(
                [prefix + text for text in texts],
                normalize_embeddings=True,
                convert_to_numpy=True,
                batch_size=len(texts),
                show_progress_bar=False,
            ),
            dtype=np.float32,
        )

    scenarios = (
        ["classification_raw_text"]
        if candidate["task"] == "classification"
        else ["deduplication_raw_text_tfidf"]
        if not use_embedding
        else [
            "deduplication_reference_embedding_cached",
            "deduplication_no_embedding_cache",
        ]
    )
    rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        reference_cache: dict[int, np.ndarray] = {}
        reference_cache_seconds = 0.0
        if use_embedding and scenario == "deduplication_reference_embedding_cached":
            cache_started = time.perf_counter()
            for index_value in indices:
                index = int(index_value)
                reference_cache[index] = encode(
                    [str(samples[index]["reference_text"])]
                )[0]
            reference_cache_seconds = time.perf_counter() - cache_started

        def prepare(index: int) -> dict[str, Any]:
            sample = dict(samples[index])
            if not use_embedding:
                return sample
            if candidate["task"] == "classification":
                sample["embedding"] = encode([str(sample["text"])])[0]
            elif scenario == "deduplication_reference_embedding_cached":
                sample["current_embedding"] = encode(
                    [str(sample["current_text"])]
                )[0]
                sample["reference_embedding"] = reference_cache[index]
            else:
                vectors = encode(
                    [
                        str(sample["current_text"]),
                        str(sample["reference_text"]),
                    ]
                )
                sample["current_embedding"] = vectors[0]
                sample["reference_embedding"] = vectors[1]
            return sample

        warmup = indices[: min(int(benchmark["warmup_records"]), len(indices))]
        for index_value in warmup:
            pipeline.predict([prepare(int(index_value))])
        latencies: list[float] = []
        with PeakRssSampler() as sampler:
            total_started = time.perf_counter()
            for index_value in indices:
                started = time.perf_counter()
                pipeline.predict([prepare(int(index_value))])
                latencies.append((time.perf_counter() - started) * 1000.0)
            total_seconds = time.perf_counter() - total_started
        rows.append(
            {
                "status": "COMPLETED",
                "task": candidate["task"],
                "combination_id": candidate["combination_id"],
                "scenario": scenario,
                "measurement_scope": (
                    "raw_text_to_base_classifier_prediction_before_calibration_and_threshold"
                ),
                "device": "cpu",
                "precision": "fp32",
                "seed": int(benchmark["random_seed"]),
                "records": len(indices),
                "warmup_records": len(warmup),
                "encoder_calls_per_record": (
                    0
                    if not use_embedding
                    else 2
                    if scenario == "deduplication_no_embedding_cache"
                    else 1
                ),
                "reference_cache_precompute_seconds": reference_cache_seconds,
                "cold_encoder_load_seconds": load_seconds,
                "cold_encoder_load_peak_rss_mb": load_peak_rss_mb,
                "final_base_fit_seconds": final_fit_seconds,
                "latency_ms_p50": percentile(latencies, 50),
                "latency_ms_p95": percentile(latencies, 95),
                "throughput_records_per_second": (
                    len(indices) / total_seconds if total_seconds else None
                ),
                "peak_process_rss_mb": sampler.peak / 1024 / 1024,
            }
        )
    del pipeline, encoder
    gc.collect()
    return rows


def build_samples(
    cases: Sequence[dict[str, Any]],
    *,
    embedding_map: dict[str, np.ndarray] | None,
    classification_group_field: str,
    deduplication_group_field: str,
    allow_mixed_label_source_groups: bool = False,
) -> tuple[
    list[dict[str, Any]],
    list[int],
    list[str],
    list[dict[str, Any]],
    list[int],
    list[str],
]:
    class_cases = training.classification_model_rows(cases)
    class_samples: list[dict[str, Any]] = []
    for case in class_cases:
        text = training.model_text(case)
        sample = {
            "unit_id": str(case["case_id"]),
            "case": case,
            "text": text,
        }
        if embedding_map is not None:
            sample["embedding"] = embedding_map[text]
        class_samples.append(sample)
    class_labels = [
        CLASS_LABELS.index(str(case["expected_classification"]).upper())
        for case in class_cases
    ]
    class_groups = [
        str(case.get(classification_group_field) or "").strip()
        for case in class_cases
    ]
    if not all(class_groups):
        raise SelectionGuardError(
            f"{classification_group_field} ausente em classificação"
        )
    if not allow_mixed_label_source_groups:
        validate_group_label_purity(
            class_labels, class_groups, context="classification"
        )

    pairs = training.dedup_pairs(cases)
    pair_samples: list[dict[str, Any]] = []
    for current, reference, label_name in pairs:
        current_text = training.model_text(current)
        reference_text = training.model_text(reference)
        sample = {
            "unit_id": str(current["case_id"]),
            "current": current,
            "reference": reference,
            "current_text": current_text,
            "reference_text": reference_text,
            "label_name": label_name,
        }
        if embedding_map is not None:
            sample["current_embedding"] = embedding_map[current_text]
            sample["reference_embedding"] = embedding_map[reference_text]
        pair_samples.append(sample)
    pair_labels = [DEDUP_LABELS.index(pair[2]) for pair in pairs]
    pair_groups = [
        str(pair[0].get(deduplication_group_field) or "").strip()
        for pair in pairs
    ]
    if not all(pair_groups):
        raise SelectionGuardError(
            f"{deduplication_group_field} ausente em deduplicação"
        )
    if not allow_mixed_label_source_groups:
        validate_group_label_purity(
            pair_labels, pair_groups, context="deduplication"
        )
    return (
        class_samples,
        class_labels,
        class_groups,
        pair_samples,
        pair_labels,
        pair_groups,
    )


def environment_manifest(config_path: Path, protocol_sha256: str) -> dict[str, Any]:
    import pandas
    import sentence_transformers
    import shap
    import torch
    import transformers
    import xgboost

    process = psutil.Process(os.getpid())
    memory = psutil.virtual_memory()
    return {
        "created_at": utc_now(),
        "protocol_path": str(config_path.resolve()),
        "protocol_sha256": protocol_sha256,
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "logical_cpus": psutil.cpu_count(logical=True),
        "physical_cpus": psutil.cpu_count(logical=False),
        "total_ram_gib": memory.total / 1024**3,
        "available_ram_gib_at_start": memory.available / 1024**3,
        "process_rss_mb_at_start": process.memory_info().rss / 1024**2,
        "packages": {
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "scikit_learn": sklearn_version,
            "joblib": joblib.__version__,
            "psutil": psutil.__version__,
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "sentence_transformers": sentence_transformers.__version__,
            "xgboost": xgboost.__version__,
            "shap": shap.__version__,
            "pandas": pandas.__version__,
        },
        "thread_environment": {
            key: os.environ.get(key)
            for key in [
                "OMP_NUM_THREADS",
                "MKL_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
            ]
        },
    }


def make_report(
    *,
    output_dir: Path,
    dataset_info: dict[str, Any],
    retrieval: Sequence[dict[str, Any]],
    ranking_rows: Sequence[dict[str, Any]],
    winners: dict[str, dict[str, Any] | None],
    provisional_candidates: dict[str, dict[str, Any] | None],
    failed: Sequence[dict[str, Any]],
    xai: Sequence[dict[str, Any]],
    performance: Sequence[dict[str, Any]],
    selected_tasks: Sequence[str] = ALL_TASKS,
) -> None:
    def report_percent(value: Any) -> str:
        return "n/a" if value is None or value == "" else f"{float(value):.2%}"

    lines = [
        "# Seleção comparativa de embeddings e classificadores",
        "",
        "> Status: seleção interna no corpus sintético de desenvolvimento. Este "
        "relatório não é validação confirmatória nem evidência de eficácia em produção.",
        "",
        "## Integridade do protocolo",
        "",
        f"- dataset: `{dataset_info['path']}`;",
        f"- SHA-256: `{dataset_info['sha256']}`;",
        f"- registros: {dataset_info['records']};",
        "- classificação agrupada por "
        f"`{dataset_info['classification_group_field']}`;",
        "- deduplicação agrupada por "
        f"`{dataset_info['deduplication_group_field']}`;",
        "- dobras externas agrupadas; TF-IDF, modelo e calibração ajustados sem usar a dobra externa;",
        f"- tarefas executadas: {', '.join(selected_tasks)};",
        "- `corpus_v3_teste`, primary33 e datasets V2 não foram usados.",
        "",
        "## Recuperação semântica",
        "",
        "| Representação | Recall@1 | Recall@5 | Recall@20 | MRR | nDCG@20 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in sorted(retrieval, key=lambda item: -float(item["recall_at_20"])):
        lines.append(
            "| {representation} | {recall_at_1:.2%} | {recall_at_5:.2%} | "
            "{recall_at_20:.2%} | {mrr:.4f} | {ndcg_at_20:.4f} |".format(**row)
        )
    for task, title in (
        (
            "classification",
            "Classificação OBRA/DEMO/SOB_DEMANDA/TRIAGEM_MANUAL",
        ),
        ("deduplication", "Deduplicação"),
    ):
        if task not in selected_tasks:
            continue
        lines.extend(["", f"## {title}", ""])
        task_rows = [row for row in ranking_rows if row["task"] == task][:10]
        if task == "classification":
            lines.extend(
                [
                    "| Rank | Configuração | Evidência | Macro-F1 | Não-OBRA→OBRA | UCB95 por grupo | Cobertura | LCB95 cobertura |",
                    "|---:|---|---|---:|---:|---:|---:|---:|",
                ]
            )
            for row in task_rows:
                lines.append(
                    f"| {row['rank']} | `{row['combination_id']}` | "
                    f"{row['evidence_status']} | "
                    f"{float(row.get('macro_f1', 0)):.4f} | "
                    f"{int(row.get('automatic_non_obra_as_obra', 0))} | "
                    f"{report_percent(row.get('automatic_non_obra_as_obra_group_rate_upper'))} | "
                    f"{float(row.get('automatic_coverage', 0)):.2%} | "
                    f"{report_percent(row.get('group_bootstrap_coverage_ci_lower'))} |"
                )
        else:
            lines.extend(
                [
                    "| Rank | Configuração | Evidência | FN automáticos | UCB95 FN por grupo | Custo 5:1 | NPV | Automação integral | Cobertura de decisão |",
                    "|---:|---|---|---:|---:|---:|---:|---:|---:|",
                ]
            )
            for row in task_rows:
                lines.append(
                    f"| {row['rank']} | `{row['combination_id']}` | "
                    f"{row['evidence_status']} | "
                    f"{int(row.get('fn', 0))} | "
                    f"{report_percent(row.get('false_negative_group_rate_upper'))} | "
                    f"{float(row.get('weighted_error_fn5_fp1_total', 0)):.2f} | "
                    f"{float(row.get('negative_predictive_value') or 0):.4f} | "
                    f"{float(row.get('full_automation_coverage', 0)):.2%} | "
                    f"{float(row.get('decision_coverage', 0)):.2%} |"
                )
        winner = winners.get(task)
        provisional = provisional_candidates.get(task)
        lines.extend(
            [
                "",
                (
                    f"Vencedor interno qualificado pelos limites de confiança: "
                    f"`{winner['combination_id']}`."
                    if winner
                    else (
                        "Nenhum candidato foi qualificado pelos limites de "
                        "confiança. Candidato provisório pela estimativa pontual: "
                        f"`{provisional['combination_id']}`; não validado."
                        if provisional
                        else "Nenhum candidato satisfez sequer os gates pontuais."
                    )
                ),
            ]
        )
    lines.extend(
        [
            "",
            "## XAI",
            "",
            "SHAP explica o escore do classificador-base antes da calibração e dos "
            "limiares. Ele não prova causalidade e dimensões individuais do embedding "
            "não recebem interpretação linguística; por isso as contribuições são "
            "também agregadas por família.",
        ]
    )
    for item in xai:
        lines.append(
            f"- `{item.get('combination_id')}`: {item.get('status')} "
            f"({item.get('method') or item.get('reason', '')})."
        )
    lines.extend(
        [
            "",
            "## Desempenho dos finalistas",
            "",
            "A tabela mede texto bruto até a predição do classificador-base. O "
            "carregamento frio do encoder é separado e os tempos não incluem "
            "GLPI, n8n, rede, calibração nem efeitos externos.",
            "",
            "| Tarefa | Cenário | Configuração | p50 (ms) | p95 (ms) | itens/s | Pico RSS (MB) |",
            "|---|---|---|---:|---:|---:|---:|",
        ]
    )
    for row in performance:
        if row.get("status") != "COMPLETED":
            lines.append(
                f"| {row.get('task')} | falha | `{row.get('combination_id', '')}` | n/a | n/a | n/a | n/a |"
            )
            continue
        lines.append(
            f"| {row['task']} | {row['scenario']} | `{row['combination_id']}` | "
            f"{float(row['latency_ms_p50']):.2f} | "
            f"{float(row['latency_ms_p95']):.2f} | "
            f"{float(row['throughput_records_per_second']):.2f} | "
            f"{float(row['peak_process_rss_mb']):.1f} |"
        )
    classification_candidate = (
        winners.get("classification")
        or provisional_candidates.get("classification")
    )
    if classification_candidate:
        per_class = classification_candidate.get("metrics", {}).get(
            "per_class", {}
        )
        lines.extend(
            [
                "",
                "### Métricas por classe do candidato classificatório",
                "",
                "| Classe | Precisão | Recall | F1 | Suporte |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for label in CLASS_LABELS:
            metric = per_class.get(label, {})
            lines.append(
                f"| {label} | {float(metric.get('precision', 0)):.4f} | "
                f"{float(metric.get('recall', 0)):.4f} | "
                f"{float(metric.get('f1-score', 0)):.4f} | "
                f"{int(metric.get('support', 0))} |"
            )
        review_reasons = Counter(
            str(row.get("review_reason"))
            for row in classification_candidate.get("predictions", [])
            if not bool(row.get("covered"))
        )
        lines.extend(["", "Motivos de encaminhamento para revisão humana:"])
        for reason, count in sorted(review_reasons.items()):
            lines.append(f"- `{reason}`: {count} registros.")
    if failed:
        lines.extend(["", "## Falhas", ""])
        for result in failed:
            lines.append(
                f"- `{result['combination_id']}`: {result.get('failure')}."
            )
    lines.extend(
        [
            "",
            "## Limites da conclusão",
            "",
            "- os rótulos são sintéticos e não representam prevalência real;",
            "- os intervalos agrupam variações, mas não substituem holdout institucional;",
            "- a escolha é válida apenas como seleção de desenvolvimento;",
            "- nenhum vencedor ou candidato provisório deve substituir o bundle operacional antes do congelamento e do teste confirmatório;",
            "- ausência de diferença significativa não demonstra equivalência.",
            "",
        ]
    )
    (output_dir / "RELATORIO.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


DEFAULT_CONFIG = (
    PROJECT_ROOT
    / "avaliacao"
    / "config"
    / "selecao_modelos_supervisionados_v2.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Seleciona embeddings, representações e classificadores no corpus "
            "sintético de desenvolvimento com validação cruzada agrupada."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
    )
    parser.add_argument("--saida", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force-embeddings", action="store_true")
    parser.add_argument("--somente-embeddings", action="store_true")
    parser.add_argument("--skip-xai", action="store_true")
    parser.add_argument(
        "--classificadores",
        nargs="*",
        choices=[
            "logistic_regression",
            "decision_tree",
            "linear_svm",
            "mlp",
            "xgboost",
        ],
    )
    parser.add_argument(
        "--embeddings",
        nargs="*",
        choices=[
            "granite97m",
            "multilingual_e5_small",
            "multilingual_minilm_l12",
        ],
    )
    parser.add_argument(
        "--representacoes",
        nargs="*",
        choices=["tfidf", "embedding", "hybrid", "metadata", "hybrid_metadata"],
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    validate_protocol_config(config)
    selected_tasks = tuple(config.get("execution_tasks", list(ALL_TASKS)))
    protocol_sha256 = sha256_file(config_path)
    output_dir = args.saida.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    environment = environment_manifest(config_path, protocol_sha256)
    implementation = implementation_manifest(
        config_path=config_path,
        protocol_sha256=protocol_sha256,
        packages=environment["packages"],
    )
    run_fingerprint = implementation["run_fingerprint"]
    environment["implementation"] = implementation
    write_json(
        output_dir / "protocolo_congelado.json",
        {
            "protocol_sha256": protocol_sha256,
            "run_fingerprint": run_fingerprint,
            "implementation": implementation,
            "config": config,
        },
    )
    write_json(output_dir / "ambiente.json", environment)

    dataset_path = (PROJECT_ROOT / config["dataset"]["path"]).resolve()
    dataset_sha256 = sha256_file(dataset_path)
    if dataset_sha256 != config["dataset"]["sha256"]:
        raise SelectionGuardError(
            f"Dataset divergente: {dataset_sha256} != {config['dataset']['sha256']}"
        )
    forbidden_resolved = {
        str((PROJECT_ROOT / path).resolve()).casefold()
        for path in config["dataset"]["forbidden_paths"]
    }
    if str(dataset_path).casefold() in forbidden_resolved:
        raise SelectionGuardError("Dataset reservado foi configurado para seleção")
    cases = training.load_jsonl(dataset_path)
    source_audit = training.validate_source_role(
        dataset_path, cases, role="TRAIN"
    )
    training.validate_labels(cases, str(dataset_path))
    class_cases = training.classification_model_rows(cases)
    pairs = training.dedup_pairs(cases)
    classification_group_field = config["dataset"][
        "classification_group_field"
    ]
    deduplication_group_field = config["dataset"][
        "deduplication_group_field"
    ]
    dataset_info = {
        "path": str(dataset_path),
        "sha256": dataset_sha256,
        "records": len(cases),
        "classification_model_records": len(class_cases),
        "classification_group_field": classification_group_field,
        "classification_groups": len(
            {
                str(case[classification_group_field])
                for case in class_cases
            }
        ),
        "deduplication_pairs": len(pairs),
        "deduplication_group_field": deduplication_group_field,
        "deduplication_groups": len(
            {str(pair[0][deduplication_group_field]) for pair in pairs}
        ),
        "source_audit": source_audit,
        "synthetic": True,
        "development_only": True,
        "execution_tasks": list(selected_tasks),
    }
    write_json(output_dir / "dataset_audit.json", dataset_info)

    tfidf_samples = build_samples(
        cases,
        embedding_map=None,
        classification_group_field=classification_group_field,
        deduplication_group_field=deduplication_group_field,
        allow_mixed_label_source_groups=config["dataset"].get("allow_mixed_label_source_groups", False),
    )
    feasibility_inputs = {
        "classification": (tfidf_samples[1], tfidf_samples[2]),
        "deduplication": (tfidf_samples[4], tfidf_samples[5]),
    }
    feasibility: dict[str, Any] = {}
    try:
        for task in selected_tasks:
            feasibility[task] = validate_task_split_feasibility(
                task=task,
                labels=feasibility_inputs[task][0],
                groups=feasibility_inputs[task][1],
                config=config,
            )
    except Exception as exc:
        write_json(
            output_dir / "preflight_divisoes.json",
            {
                "status": "INFEASIBLE",
                "execution_tasks": list(selected_tasks),
                "tasks": feasibility,
                "failed_task": task,
                "failure": f"{type(exc).__name__}: {exc}",
            },
        )
        raise
    write_json(
        output_dir / "preflight_divisoes.json",
        {
            "status": "FEASIBLE",
            "execution_tasks": list(selected_tasks),
            "tasks": feasibility,
        },
    )

    unique_symmetric_texts = list(
        dict.fromkeys(
            [training.model_text(case) for case in class_cases]
            + [
                training.model_text(case)
                for pair in pairs
                for case in pair[:2]
            ]
        )
    )
    positive_pairs = [pair for pair in pairs if pair[2] == "DUPLICADO"]
    retrieval_queries = [training.model_text(pair[0]) for pair in positive_pairs]
    anchors_by_id = {
        str(pair[1]["case_id"]): pair[1] for pair in pairs
    }
    retrieval_passages = [
        training.model_text(anchors_by_id[key]) for key in sorted(anchors_by_id)
    ]
    frozen_execution_ids = set(config.get("execution_combination_ids", []))
    frozen_embeddings = {
        value.split("__")[2]
        for value in frozen_execution_ids
        if value.split("__")[2] != "none"
    }
    selected_embedding_ids = set(
        args.embeddings
        or frozen_embeddings
        or [item["id"] for item in config["embeddings"]]
    )
    specs = [
        EmbeddingSpec(
            id=item["id"],
            repository=item["repository"],
            revision=item["revision"],
            local_path=(PROJECT_ROOT / item["local_path"]).resolve(),
            tree_sha256=item["tree_sha256"],
            dimension=int(item["dimension"]),
            symmetric_prefix=item["symmetric_prefix"],
            retrieval_query_prefix=item["retrieval_query_prefix"],
            retrieval_passage_prefix=item["retrieval_passage_prefix"],
        )
        for item in config["embeddings"]
        if item["id"] in selected_embedding_ids
    ]
    embedding_maps: dict[str, dict[str, dict[str, np.ndarray]]] = {}
    embedding_metrics: list[dict[str, Any]] = []
    cache_root = PROJECT_ROOT / "local_ai" / "runtime" / "selection_cache"
    for spec in specs:
        print(f"[embedding] {spec.id}", flush=True)
        maps, metadata = encode_model_roles(
            spec,
            dataset_sha256=dataset_sha256,
            role_inputs={
                "symmetric": (
                    unique_symmetric_texts,
                    spec.symmetric_prefix,
                ),
                "retrieval_query": (
                    retrieval_queries,
                    spec.retrieval_query_prefix,
                ),
                "retrieval_passage": (
                    retrieval_passages,
                    spec.retrieval_passage_prefix,
                ),
            },
            cache_root=cache_root,
            batch_size=int(config["hardware"]["embedding_batch_size"]),
            cpu_threads=int(config["hardware"]["cpu_threads"]),
            force=args.force_embeddings,
        )
        embedding_maps[spec.id] = maps
        embedding_metrics.append(metadata)
        write_json(output_dir / "embedding_runtime.json", embedding_metrics)

    retrieval_summary, retrieval_detail = retrieval_rows(
        pairs,
        embedding_maps=embedding_maps,
    )
    write_csv(output_dir / "recuperacao_resumo.csv", retrieval_summary)
    write_csv(output_dir / "recuperacao_detalhes.csv", retrieval_detail)
    write_json(
        output_dir / "recuperacao.json",
        {"summary": retrieval_summary, "details": retrieval_detail},
    )
    if args.somente_embeddings:
        print(f"Artefatos de embedding em {output_dir}", flush=True)
        return 0

    frozen_classifiers = {
        value.rsplit("__", 1)[-1] for value in frozen_execution_ids
    }
    frozen_representations = {
        value.split("__")[1] for value in frozen_execution_ids
    }
    classifiers = args.classificadores or sorted(frozen_classifiers) or [
        item["id"] for item in config["classifiers"]
    ]
    representations = args.representacoes or sorted(frozen_representations) or list(config["representations"])
    results: list[dict[str, Any]] = []
    for representation in representations:
        representation_specification = config["representations"][representation]
        if not representation_specification["uses_embedding"]:
            embedding_options: list[str | None] = [None]
        else:
            embedding_options = [spec.id for spec in specs]
        for embedding_id in embedding_options:
            if embedding_id is None:
                sample_sets = tfidf_samples
            else:
                sample_sets = build_samples(
                    cases,
                    embedding_map=embedding_maps[embedding_id]["symmetric"],
                    classification_group_field=classification_group_field,
                    deduplication_group_field=deduplication_group_field,
                    allow_mixed_label_source_groups=config["dataset"].get("allow_mixed_label_source_groups", False),
                )
            (
                class_samples,
                class_labels,
                class_groups,
                pair_samples,
                pair_labels,
                pair_groups,
            ) = sample_sets
            for task, samples, labels, groups in (
                (
                    "classification",
                    class_samples,
                    class_labels,
                    class_groups,
                ),
                (
                    "deduplication",
                    pair_samples,
                    pair_labels,
                    pair_groups,
                ),
            ):
                if task not in selected_tasks:
                    continue
                if task not in representation_specification["tasks"]:
                    continue
                for classifier in classifiers:
                    combination_id = "__".join(
                        [task, representation, embedding_id or "none", classifier]
                    )
                    if frozen_execution_ids and combination_id not in frozen_execution_ids:
                        continue
                    result = run_configuration(
                        task=task,
                        representation_id=representation,
                        embedding_id=embedding_id,
                        classifier_id=classifier,
                        samples=samples,
                        labels=labels,
                        groups=groups,
                        config=config,
                        output_dir=output_dir,
                        protocol_sha256=protocol_sha256,
                        run_fingerprint=run_fingerprint,
                        resume=args.resume,
                    )
                    results.append(result)
                    write_csv(
                        output_dir / "resultados_parciais.csv",
                        [flatten_result(item) for item in results],
                    )

    ranking_rows: list[dict[str, Any]] = []
    winners: dict[str, dict[str, Any] | None] = {}
    provisional_candidates: dict[str, dict[str, Any] | None] = {}
    for task in selected_tasks:
        ranked, winner, provisional = selection_rank(
            results,
            task=task,
            policy=config["operating_policy"],
        )
        ranking_rows.extend(ranked)
        winners[task] = winner
        provisional_candidates[task] = provisional
    failed = [result for result in results if result["status"] == "FAILED"]
    predictions = [
        prediction
        for result in results
        for prediction in result.get("predictions", [])
    ]
    fold_rows = [
        fold
        for result in results
        for fold in result.get("folds", [])
    ]
    paired_comparisons = {
        task: config["paired_comparisons"][task]
        for task in selected_tasks
    }
    paired_baselines = {
        task: comparisons[0]["baseline"]
        for task, comparisons in paired_comparisons.items()
    }
    paired_candidates = {
        task: {
            comparison["candidate"]: comparison["id"]
            for comparison in comparisons
        }
        for task, comparisons in paired_comparisons.items()
    }
    paired_groups = paired_group_rows(
        results,
        comparisons=paired_comparisons,
    )
    paired_objectives = paired_objective_rows(
        results,
        baseline_ids=paired_baselines,
        comparison_candidates=paired_candidates,
        resamples=int(
            config["cross_validation"]["paired_group_bootstrap_resamples"]
        ),
        confidence_level=float(
            config["cross_validation"]["confidence_level"]
        ),
        seed=int(config["cross_validation"]["outer_seed"]) + 700000,
        false_negative_cost=float(
            config["objectives"]["deduplication_false_negative_cost"]
        ),
        false_positive_cost=float(
            config["objectives"]["deduplication_false_positive_cost"]
        ),
    )

    xai_results: list[dict[str, Any]] = []
    xai_expected: list[tuple[str, str]] = []
    if config["xai"]["enabled"] and not args.skip_xai:
        by_combination = {
            result["combination_id"]: result
            for result in results
            if result["status"] == "COMPLETED_DEVELOPMENT_OOF"
        }
        finalist_count = int(config["xai"]["finalists_per_task"])
        for task in selected_tasks:
            ordered_ids = [
                str(row["combination_id"])
                for row in ranking_rows
                if row["task"] == task
            ]
            preferred = winners.get(task) or provisional_candidates.get(task)
            if preferred is not None:
                ordered_ids = [preferred["combination_id"]] + [
                    combination_id
                    for combination_id in ordered_ids
                    if combination_id != preferred["combination_id"]
                ]
            finalists = [
                by_combination[combination_id]
                for combination_id in ordered_ids[:finalist_count]
            ]
            for xai_candidate in finalists:
                xai_expected.append((task, xai_candidate["combination_id"]))
                embedding_id = xai_candidate.get("embedding")
                sample_sets = (
                    tfidf_samples
                    if embedding_id is None
                    else build_samples(
                        cases,
                        embedding_map=embedding_maps[embedding_id]["symmetric"],
                        classification_group_field=classification_group_field,
                        deduplication_group_field=deduplication_group_field,
                        allow_mixed_label_source_groups=config["dataset"].get("allow_mixed_label_source_groups", False),
                    )
                )
                if task == "classification":
                    samples, labels, groups = sample_sets[:3]
                else:
                    samples, labels, groups = sample_sets[3:]
                try:
                    xai_result = generate_xai(
                        xai_candidate,
                        samples=samples,
                        labels=labels,
                        groups=groups,
                        config=config,
                    )
                    xai_result["selection_evidence_status"] = (
                        "CONFIDENCE_QUALIFIED_WINNER"
                        if winners.get(task) is xai_candidate
                        else "PROVISIONAL_POINT_CANDIDATE"
                        if provisional_candidates.get(task) is xai_candidate
                        else "EXPLORATORY_TOP_RANKED_NO_ELIGIBLE_POLICY"
                    )
                    xai_results.append(xai_result)
                except Exception as exc:
                    xai_results.append(
                        {
                            "status": "FAILED",
                            "task": task,
                            "combination_id": xai_candidate["combination_id"],
                            "failure": f"{type(exc).__name__}: {exc}",
                        }
                    )

    xai_failed = bool(
        config["xai"]["enabled"]
        and not args.skip_xai
        and (
            len(xai_results) != len(xai_expected)
            or any(
                item.get("status") not in {"COMPLETED", "COMPLETED_FALLBACK"}
                for item in xai_results
            )
        )
    )

    performance_results: list[dict[str, Any]] = []
    performance_failed = False
    if config["performance_benchmark"]["enabled"]:
        completed_by_id = {
            result["combination_id"]: result
            for result in results
            if result["status"] == "COMPLETED_DEVELOPMENT_OOF"
        }
        for task in selected_tasks:
            candidate = winners.get(task) or provisional_candidates.get(task)
            if candidate is None:
                top_row = next(
                    (row for row in ranking_rows if row["task"] == task),
                    None,
                )
                candidate = (
                    completed_by_id.get(str(top_row["combination_id"]))
                    if top_row is not None
                    else None
                )
            if candidate is None:
                performance_failed = True
                performance_results.append(
                    {
                        "status": "FAILED",
                        "task": task,
                        "failure": "Nenhum candidato concluído para medir",
                    }
                )
                continue
            embedding_id = candidate.get("embedding")
            candidate_samples = (
                tfidf_samples
                if embedding_id is None
                else build_samples(
                    cases,
                    embedding_map=embedding_maps[embedding_id]["symmetric"],
                    classification_group_field=classification_group_field,
                    deduplication_group_field=deduplication_group_field,
                    allow_mixed_label_source_groups=config["dataset"].get("allow_mixed_label_source_groups", False),
                )
            )
            if task == "classification":
                samples, labels, groups = candidate_samples[:3]
            else:
                samples, labels, groups = candidate_samples[3:]
            try:
                performance_results.extend(
                    benchmark_finalist_performance(
                        candidate,
                        samples=samples,
                        labels=labels,
                        groups=groups,
                        config=config,
                    )
                )
            except Exception as exc:
                performance_failed = True
                performance_results.append(
                    {
                        "status": "FAILED",
                        "task": task,
                        "combination_id": candidate["combination_id"],
                        "failure": f"{type(exc).__name__}: {exc}",
                    }
                )

    write_csv(
        output_dir / "resultados_resumo.csv",
        [flatten_result(result) for result in results],
    )
    write_csv(output_dir / "ranking.csv", ranking_rows)
    write_csv(output_dir / "dobras.csv", fold_rows)
    write_csv(output_dir / "predicoes_oof.csv", predictions)
    write_csv(
        output_dir / "comparacao_pareada_grupos.csv",
        paired_groups,
    )
    write_csv(
        output_dir / "comparacao_pareada_objetivos.csv",
        paired_objectives,
    )
    write_json(output_dir / "xai.json", xai_results)
    write_csv(
        output_dir / "xai_familias.csv",
        [
            {
                "task": item.get("task"),
                "combination_id": item.get("combination_id"),
                **row,
            }
            for item in xai_results
            for row in item.get("family_importance", [])
        ],
    )
    write_json(output_dir / "latencia_finalistas.json", performance_results)
    write_csv(output_dir / "latencia_finalistas.csv", performance_results)
    final_payload = {
        "schema": SCHEMA,
        "created_at": utc_now(),
        "protocol_sha256": protocol_sha256,
        "run_fingerprint": run_fingerprint,
        "scientific_result": False,
        "development_only": True,
        "confirmatory_eligible": False,
        "execution_tasks": list(selected_tasks),
        "dataset": dataset_info,
        "embedding_runtime": embedding_metrics,
        "retrieval": retrieval_summary,
        "results": [
            {key: value for key, value in result.items() if key != "predictions"}
            for result in results
        ],
        "ranking": ranking_rows,
        "winners": {
            task: winner["combination_id"] if winner else None
            for task, winner in winners.items()
        },
        "provisional_point_candidates": {
            task: candidate["combination_id"] if candidate else None
            for task, candidate in provisional_candidates.items()
        },
        "paired_group_comparison": paired_groups,
        "paired_objective_comparison": paired_objectives,
        "xai": xai_results,
        "xai_complete": not xai_failed and not args.skip_xai,
        "performance_benchmark": performance_results,
        "performance_benchmark_complete": not performance_failed,
        "limitations": [
            "Corpus sintético de desenvolvimento, sem prevalência real.",
            "Variações agrupadas por source_dependency_group_sha256; n efetivo menor que registros.",
            "Seleção não confirmatória; holdout permaneceu fechado.",
            "SHAP explica associação no score-base, não causalidade.",
        ],
    }
    write_json(output_dir / "resultados.json", final_payload)
    make_report(
        output_dir=output_dir,
        dataset_info=dataset_info,
        retrieval=retrieval_summary,
        ranking_rows=ranking_rows,
        winners=winners,
        provisional_candidates=provisional_candidates,
        failed=failed,
        xai=xai_results,
        performance=performance_results,
        selected_tasks=selected_tasks,
    )
    print(f"Seleção concluída em {output_dir}", flush=True)
    return 0 if not failed and not xai_failed and not performance_failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
