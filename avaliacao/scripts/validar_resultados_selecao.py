from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
from scipy.stats import beta, wilcoxon
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_recall_fscore_support,
    roc_auc_score,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = (
    ROOT / "avaliacao" / "config" / "selecao_modelos_supervisionados_v2.json"
)
CLASS_LABELS = ("OBRA", "DEMO", "SOB_DEMANDA", "TRIAGEM_MANUAL")
DEDUP_LABELS = ("NAO_DUPLICADO", "DUPLICADO")
ALL_TASKS = ("classification", "deduplication")
BOOL_TEXT = {"True": True, "False": False}
FLOAT_REL_TOL = 1e-9
FLOAT_ABS_TOL = 1e-10


class ResultValidationError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or len(set(reader.fieldnames)) != len(
            reader.fieldnames
        ):
            raise ResultValidationError(f"Cabeçalho CSV inválido: {path.name}")
        return list(reader)


def parse_bool(value: str, *, context: str) -> bool:
    try:
        return BOOL_TEXT[value]
    except KeyError as exc:
        raise ResultValidationError(
            f"Booleano não canônico em {context}: {value!r}"
        ) from exc


def parse_float(value: Any, *, context: str) -> float:
    if isinstance(value, bool) or value is None or value == "":
        raise ResultValidationError(f"Número ausente em {context}")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ResultValidationError(
            f"Número inválido em {context}: {value!r}"
        ) from exc
    if not math.isfinite(parsed):
        raise ResultValidationError(f"Número não finito em {context}")
    return parsed


def parse_optional_float(value: Any, *, context: str) -> float | None:
    if value is None or value == "":
        return None
    return parse_float(value, context=context)


def parse_json_cell(value: str, *, context: str) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ResultValidationError(f"JSON inválido em {context}") from exc


def assert_close(actual: Any, expected: Any, *, context: str) -> None:
    if expected is None:
        if actual is not None and actual != "":
            raise ResultValidationError(
                f"{context}: esperado nulo, observado {actual!r}"
            )
        return
    if isinstance(expected, bool):
        if isinstance(actual, str):
            actual_value = parse_bool(actual, context=context)
        else:
            actual_value = actual
        if actual_value is not expected:
            raise ResultValidationError(
                f"{context}: {actual_value!r} != {expected!r}"
            )
        return
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        actual_value = parse_float(actual, context=context)
        if not math.isclose(
            actual_value,
            float(expected),
            rel_tol=FLOAT_REL_TOL,
            abs_tol=FLOAT_ABS_TOL,
        ):
            raise ResultValidationError(
                f"{context}: {actual_value:.17g} != {float(expected):.17g}"
            )
        return
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            if isinstance(actual, str):
                actual = parse_json_cell(actual, context=context)
        if not isinstance(actual, dict):
            raise ResultValidationError(f"{context}: objeto esperado")
        for key, value in expected.items():
            if key not in actual:
                raise ResultValidationError(f"{context}.{key}: campo ausente")
            assert_close(actual[key], value, context=f"{context}.{key}")
        return
    if isinstance(expected, (list, tuple)):
        if not isinstance(actual, (list, tuple)):
            if isinstance(actual, str):
                actual = parse_json_cell(actual, context=context)
        if not isinstance(actual, (list, tuple)) or len(actual) != len(expected):
            raise ResultValidationError(f"{context}: lista divergente")
        for index, value in enumerate(expected):
            assert_close(actual[index], value, context=f"{context}[{index}]")
        return
    if actual != expected:
        raise ResultValidationError(f"{context}: {actual!r} != {expected!r}")


def unique_by(
    rows: Sequence[dict[str, Any]], key: str, *, context: str
) -> dict[str, dict[str, Any]]:
    values = [str(row.get(key, "")) for row in rows]
    empty = [index for index, value in enumerate(values) if not value]
    duplicates = [value for value, count in Counter(values).items() if count > 1]
    if empty or duplicates:
        raise ResultValidationError(
            f"{context}: chaves vazias={empty[:3]}, duplicadas={duplicates[:3]}"
        )
    return {value: row for value, row in zip(values, rows)}


def task_rows(
    payload: Any,
    tasks: Sequence[str],
    *,
    context: str,
) -> list[dict[str, Any]]:
    """Valida e recorta uma lista de artefatos para o escopo solicitado."""
    if not isinstance(payload, list) or any(
        not isinstance(row, dict) for row in payload
    ):
        raise ResultValidationError(f"{context}: lista de objetos ausente/inválida")
    selected = set(tasks)
    return [row for row in payload if row.get("task") in selected]


def expected_combinations(config: dict[str, Any]) -> set[str]:
    embedding_ids = [str(item["id"]) for item in config["embeddings"]]
    classifier_ids = [str(item["id"]) for item in config["classifiers"]]
    if len(set(embedding_ids)) != len(embedding_ids):
        raise ResultValidationError("IDs de embedding duplicados no protocolo")
    if len(set(classifier_ids)) != len(classifier_ids):
        raise ResultValidationError("IDs de classificador duplicados no protocolo")
    expected: set[str] = set()
    for representation, specification in config["representations"].items():
        flags = (
            specification.get("uses_tfidf"),
            specification.get("uses_embedding"),
            specification.get("uses_metadata"),
        )
        if any(type(flag) is not bool for flag in flags):
            raise ResultValidationError(
                f"Flags inválidas na representação {representation}"
            )
        embeddings: list[str | None] = (
            embedding_ids if specification["uses_embedding"] else [None]
        )
        for embedding in embeddings:
            for task in specification["tasks"]:
                if task not in {"classification", "deduplication"}:
                    raise ResultValidationError(f"Tarefa inválida: {task}")
                for classifier in classifier_ids:
                    combination_id = "__".join(
                        [task, representation, embedding or "none", classifier]
                    )
                    if combination_id in expected:
                        raise ResultValidationError(
                            f"Combinação repetida no protocolo: {combination_id}"
                        )
                    expected.add(combination_id)
    return expected


def expected_combination_metadata(combination_id: str) -> dict[str, str | None]:
    parts = combination_id.split("__")
    if len(parts) != 4:
        raise ResultValidationError(
            f"Identificador de combinação inválido: {combination_id}"
        )
    task, representation, embedding, classifier = parts
    return {
        "task": task,
        "representation": representation,
        "embedding": None if embedding == "none" else embedding,
        "classifier": classifier,
    }


def _f1_macro_from_confusions(confusions: np.ndarray) -> np.ndarray:
    # confusions: (..., gold, predicted). sklearn omite classes sem gold/pred.
    true_positive = np.diagonal(confusions, axis1=-2, axis2=-1)
    support = np.sum(confusions, axis=-1)
    predicted = np.sum(confusions, axis=-2)
    denominator = support + predicted
    per_class = np.divide(
        2.0 * true_positive,
        denominator,
        out=np.zeros_like(true_positive, dtype=np.float64),
        where=denominator > 0,
    )
    included = denominator > 0
    return np.divide(
        np.sum(per_class, axis=-1),
        np.sum(included, axis=-1),
        out=np.zeros(per_class.shape[:-1], dtype=np.float64),
        where=np.sum(included, axis=-1) > 0,
    )


def _group_draw_counts(
    groups: Sequence[str], *, resamples: int, seed: int
) -> tuple[list[str], np.ndarray]:
    unique_groups = sorted(set(groups))
    rng = np.random.default_rng(seed)
    draws = np.zeros((resamples, len(unique_groups)), dtype=np.int16)
    for row_index in range(resamples):
        chosen = rng.choice(
            np.asarray(unique_groups, dtype=object),
            size=len(unique_groups),
            replace=True,
        )
        counts = Counter(str(value) for value in chosen.tolist())
        draws[row_index] = [counts.get(group, 0) for group in unique_groups]
    return unique_groups, draws


def _group_aggregate(
    groups: Sequence[str], unique_groups: Sequence[str], values: np.ndarray
) -> np.ndarray:
    values_array = np.asarray(values)
    flattened = values_array.reshape(len(groups), -1)
    output = np.zeros(
        (len(unique_groups), flattened.shape[1]), dtype=np.float64
    )
    index = {group: position for position, group in enumerate(unique_groups)}
    for row, group in zip(flattened, groups):
        output[index[group]] += row
    return output.reshape((len(unique_groups),) + values_array.shape[1:])


def _percentile_interval(
    values: np.ndarray, confidence_level: float
) -> list[float] | None:
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        return None
    alpha = 1.0 - confidence_level
    return [
        float(np.percentile(finite, 100.0 * alpha / 2.0)),
        float(np.percentile(finite, 100.0 * (1.0 - alpha / 2.0))),
    ]


class BootstrapCache:
    def __init__(self) -> None:
        self._cache: dict[
            tuple[tuple[str, ...], int, int], tuple[list[str], np.ndarray]
        ] = {}

    def draws(
        self, groups: Sequence[str], *, resamples: int, seed: int
    ) -> tuple[list[str], np.ndarray]:
        key = (tuple(groups), resamples, seed)
        if key not in self._cache:
            self._cache[key] = _group_draw_counts(
                groups, resamples=resamples, seed=seed
            )
        return self._cache[key]


def _bootstrap_classification(
    labels: np.ndarray,
    predictions: np.ndarray,
    covered: np.ndarray,
    groups: Sequence[str],
    *,
    resamples: int,
    seed: int,
    confidence_level: float,
    cache: BootstrapCache,
) -> dict[str, list[float] | None]:
    class_count = len(CLASS_LABELS)
    output: dict[str, list[float] | None] = {}
    for offset, metric in enumerate(
        ("accuracy", "macro_f1", "coverage", "selective_risk")
    ):
        unique, draws = cache.draws(
            groups, resamples=resamples, seed=seed + offset
        )
        if metric in {"accuracy", "macro_f1"}:
            row_confusions = np.zeros(
                (len(labels), class_count, class_count), dtype=np.int8
            )
            row_confusions[
                np.arange(len(labels)), labels, predictions
            ] = 1
            grouped = _group_aggregate(groups, unique, row_confusions)
            sampled = np.tensordot(draws, grouped, axes=(1, 0))
            if metric == "accuracy":
                values = np.trace(sampled, axis1=1, axis2=2) / np.sum(
                    sampled, axis=(1, 2)
                )
            else:
                values = _f1_macro_from_confusions(sampled)
        else:
            numerator = (
                covered.astype(np.int8)
                if metric == "coverage"
                else (covered & (predictions != labels)).astype(np.int8)
            )
            denominator = (
                np.ones(len(labels), dtype=np.int8)
                if metric == "coverage"
                else covered.astype(np.int8)
            )
            grouped_num = _group_aggregate(groups, unique, numerator).reshape(-1)
            grouped_den = _group_aggregate(groups, unique, denominator).reshape(-1)
            num = draws @ grouped_num
            den = draws @ grouped_den
            values = np.divide(
                num,
                den,
                out=np.full(len(draws), np.nan),
                where=den > 0,
            )
        output[metric] = _percentile_interval(values, confidence_level)
    return output


def _bootstrap_dedup(
    labels: np.ndarray,
    semantic: np.ndarray,
    decisions: np.ndarray,
    groups: Sequence[str],
    *,
    false_negative_cost: float,
    false_positive_cost: float,
    resamples: int,
    seed: int,
    confidence_level: float,
    cache: BootstrapCache,
) -> tuple[dict[str, list[float] | None], dict[str, list[float] | None]]:
    semantic_output: dict[str, list[float] | None] = {}
    for offset, metric in enumerate(("accuracy", "macro_f1")):
        unique, draws = cache.draws(
            groups, resamples=resamples, seed=seed + offset
        )
        row_confusions = np.zeros((len(labels), 2, 2), dtype=np.int8)
        row_confusions[np.arange(len(labels)), labels, semantic] = 1
        grouped = _group_aggregate(groups, unique, row_confusions)
        sampled = np.tensordot(draws, grouped, axes=(1, 0))
        values = (
            np.trace(sampled, axis1=1, axis2=2)
            / np.sum(sampled, axis=(1, 2))
            if metric == "accuracy"
            else _f1_macro_from_confusions(sampled)
        )
        semantic_output[metric] = _percentile_interval(
            values, confidence_level
        )

    unique, draws = cache.draws(
        groups, resamples=resamples, seed=seed + 100
    )
    row_stats = np.column_stack(
        [
            (labels == 1) & (decisions == 1),  # tp
            (labels == 0) & (decisions == 1),  # fp
            (labels == 0) & (decisions == 0),  # tn
            (labels == 1) & (decisions == 0),  # fn
            labels == 1,
            labels == 0,
            decisions >= 0,
            decisions == 0,
            np.ones(len(labels), dtype=bool),
        ]
    ).astype(np.int8)
    sampled = draws @ _group_aggregate(groups, unique, row_stats)
    tp, fp, tn, fn, positives, negatives, covered, automatic_negative, total = (
        sampled[:, index] for index in range(sampled.shape[1])
    )

    def ratio(num: np.ndarray, den: np.ndarray) -> np.ndarray:
        return np.divide(
            num,
            den,
            out=np.full(len(num), np.nan),
            where=den > 0,
        )

    values = {
        "precision": ratio(tp, tp + fp),
        "negative_predictive_value": ratio(tn, tn + fn),
        "false_positive_rate": ratio(fp, negatives),
        "false_negative_rate": ratio(fn, positives),
        "weighted_error_per_record": ratio(
            false_negative_cost * fn + false_positive_cost * fp, total
        ),
        "decision_coverage": ratio(covered, total),
        "full_automation_coverage": ratio(automatic_negative, total),
    }
    operating = {
        metric: _percentile_interval(metric_values, confidence_level)
        for metric, metric_values in values.items()
    }
    return semantic_output, operating


def _ece(probabilities: np.ndarray, labels: np.ndarray, bins: int = 10) -> float:
    predictions = np.argmax(probabilities, axis=1)
    confidence = np.max(probabilities, axis=1)
    correct = predictions == labels
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
                float(np.mean(correct[mask]))
                - float(np.mean(confidence[mask]))
            )
    return float(error)


def _clopper_pearson_upper(
    events: int, trials: int, confidence_level: float
) -> float | None:
    if trials <= 0:
        return None
    if events >= trials:
        return 1.0
    return float(beta.ppf(confidence_level, events + 1, trials - events))


def _classification_metrics(
    rows: Sequence[dict[str, Any]],
    *,
    config: dict[str, Any],
    cache: BootstrapCache,
) -> dict[str, Any]:
    labels = np.asarray([row["gold_index"] for row in rows], dtype=int)
    predicted = np.asarray([row["semantic_index"] for row in rows], dtype=int)
    covered = np.asarray([row["covered_bool"] for row in rows], dtype=bool)
    probabilities = np.asarray([row["probabilities"] for row in rows])
    groups = [str(row["group"]) for row in rows]
    matrix = confusion_matrix(
        labels, predicted, labels=list(range(len(CLASS_LABELS)))
    )
    precision, recall, f1, support = precision_recall_fscore_support(
        labels,
        predicted,
        labels=list(range(len(CLASS_LABELS))),
        zero_division=0,
    )
    count = int(covered.sum())
    errors = int(np.sum(covered & (predicted != labels)))
    obra_index = CLASS_LABELS.index("OBRA")
    triage_index = CLASS_LABELS.index("TRIAGEM_MANUAL")
    maintenance = np.isin(
        labels,
        [CLASS_LABELS.index("DEMO"), CLASS_LABELS.index("SOB_DEMANDA")],
    )
    obra = predicted == obra_index
    non_obra = labels != obra_index
    critical = covered & non_obra & obra
    exposed_groups = {
        group
        for group in set(groups)
        if np.any(
            (np.asarray(groups, dtype=object) == group) & covered & non_obra
        )
    }
    critical_groups = {
        group
        for group in exposed_groups
        if np.any(
            (np.asarray(groups, dtype=object) == group) & critical
        )
    }
    covered_non_obra = int(np.sum(covered & non_obra))
    cv = config["cross_validation"]
    confidence = float(cv["confidence_level"])
    brier = np.zeros_like(probabilities)
    brier[np.arange(len(labels)), labels] = 1.0
    return {
        "records": len(labels),
        "accuracy": float(accuracy_score(labels, predicted)),
        "macro_f1": float(
            f1_score(labels, predicted, average="macro", zero_division=0)
        ),
        "log_loss": float(
            log_loss(
                labels,
                probabilities,
                labels=list(range(len(CLASS_LABELS))),
            )
        ),
        "brier_score": float(
            np.mean(np.sum((probabilities - brier) ** 2, axis=1))
        ),
        "expected_calibration_error_10_bins": _ece(
            probabilities, labels
        ),
        "confusion_matrix": {
            "labels": list(CLASS_LABELS),
            "values": matrix.astype(int).tolist(),
        },
        "per_class": {
            label: {
                "precision": float(precision[index]),
                "recall": float(recall[index]),
                "f1-score": float(f1[index]),
                "support": int(support[index]),
            }
            for index, label in enumerate(CLASS_LABELS)
        },
        "obra_recall": float(recall[obra_index]),
        "automatic_records": count,
        "automatic_coverage": count / len(labels),
        "human_review_required_records": len(labels) - count,
        "automatic_triage_records": int(
            np.sum(covered & (predicted == triage_index))
        ),
        "triagem_manual_is_automatic": False,
        "automatic_errors": errors,
        "automatic_risk": errors / count if count else None,
        "automatic_maintenance_as_obra": int(
            np.sum(covered & maintenance & obra)
        ),
        "automatic_non_obra_as_obra": int(critical.sum()),
        "automatic_non_obra_records": covered_non_obra,
        "automatic_non_obra_as_obra_rate": (
            int(critical.sum()) / covered_non_obra if covered_non_obra else None
        ),
        "automatic_non_obra_as_obra_group_events": len(critical_groups),
        "automatic_non_obra_exposed_groups": len(exposed_groups),
        "automatic_non_obra_as_obra_group_rate_upper": (
            _clopper_pearson_upper(
                len(critical_groups), len(exposed_groups), confidence
            )
        ),
        "semantic_maintenance_as_obra": int(np.sum(maintenance & obra)),
        "confidence_level": confidence,
        "confidence_intervals_group_bootstrap": _bootstrap_classification(
            labels,
            predicted,
            covered,
            groups,
            resamples=int(cv["bootstrap_group_resamples"]),
            seed=int(cv["outer_seed"]),
            confidence_level=confidence,
            cache=cache,
        ),
    }


def _dedup_metrics(
    rows: Sequence[dict[str, Any]],
    *,
    config: dict[str, Any],
    cache: BootstrapCache,
) -> dict[str, Any]:
    labels = np.asarray([row["gold_index"] for row in rows], dtype=int)
    semantic = np.asarray([row["semantic_index"] for row in rows], dtype=int)
    decisions = np.asarray([row["decision_index"] for row in rows], dtype=int)
    covered = np.asarray([row["covered_bool"] for row in rows], dtype=bool)
    probabilities = np.asarray([row["probabilities"] for row in rows])
    groups = [str(row["group"]) for row in rows]
    p_duplicate = probabilities[:, 1]
    tp = int(np.sum(covered & (labels == 1) & (decisions == 1)))
    fp = int(np.sum(covered & (labels == 0) & (decisions == 1)))
    tn = int(np.sum(covered & (labels == 0) & (decisions == 0)))
    fn = int(np.sum(covered & (labels == 1) & (decisions == 0)))
    positives = int(np.sum(labels == 1))
    negatives = int(np.sum(labels == 0))
    positive_groups = {
        group
        for group in set(groups)
        if np.any((np.asarray(groups, dtype=object) == group) & (labels == 1))
    }
    negative_groups = {
        group
        for group in set(groups)
        if np.any((np.asarray(groups, dtype=object) == group) & (labels == 0))
    }
    fn_groups = {
        group
        for group in positive_groups
        if np.any(
            (np.asarray(groups, dtype=object) == group)
            & (labels == 1)
            & (decisions == 0)
        )
    }
    fp_groups = {
        group
        for group in negative_groups
        if np.any(
            (np.asarray(groups, dtype=object) == group)
            & (labels == 0)
            & (decisions == 1)
        )
    }
    objectives = config["objectives"]
    fn_cost = float(objectives["deduplication_false_negative_cost"])
    fp_cost = float(objectives["deduplication_false_positive_cost"])
    weighted = fn_cost * fn + fp_cost * fp
    cv = config["cross_validation"]
    confidence = float(cv["confidence_level"])
    semantic_ci, operating_ci = _bootstrap_dedup(
        labels,
        semantic,
        decisions,
        groups,
        false_negative_cost=fn_cost,
        false_positive_cost=fp_cost,
        resamples=int(cv["bootstrap_group_resamples"]),
        seed=int(cv["outer_seed"]),
        confidence_level=confidence,
        cache=cache,
    )
    covered_count = int(covered.sum())
    automatic_positive = int(np.sum(decisions == 1))
    automatic_negative = int(np.sum(decisions == 0))
    return {
        "records": len(labels),
        "positive_records": positives,
        "negative_records": negatives,
        "semantic_accuracy": float(accuracy_score(labels, semantic)),
        "semantic_f1": float(f1_score(labels, semantic, zero_division=0)),
        "average_precision": float(average_precision_score(labels, p_duplicate)),
        "roc_auc": float(roc_auc_score(labels, p_duplicate)),
        "log_loss": float(log_loss(labels, probabilities, labels=[0, 1])),
        "brier_score": float(brier_score_loss(labels, p_duplicate)),
        "expected_calibration_error_10_bins": _ece(
            probabilities, labels
        ),
        "semantic_confusion_matrix": confusion_matrix(
            labels, semantic, labels=[0, 1]
        ).astype(int).tolist(),
        "decision_records": covered_count,
        "decision_coverage": covered_count / len(labels),
        "automatic_positive_records_requiring_human_confirmation": (
            automatic_positive
        ),
        "fully_automated_negative_records": automatic_negative,
        "full_automation_coverage": automatic_negative / len(labels),
        "human_review_required_records": len(labels) - automatic_negative,
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
        "false_negative_group_rate_upper": _clopper_pearson_upper(
            len(fn_groups), len(positive_groups), confidence
        ),
        "false_positive_group_events": len(fp_groups),
        "negative_groups": len(negative_groups),
        "false_positive_group_rate_upper": _clopper_pearson_upper(
            len(fp_groups), len(negative_groups), confidence
        ),
        "weighted_error_fn5_fp1_total": weighted,
        "weighted_error_fn5_fp1_per_record": weighted / len(labels),
        "weighted_error_fn5_fp1_per_automatic": (
            weighted / covered_count if covered_count else None
        ),
        "confidence_level": confidence,
        "semantic_confidence_intervals_group_bootstrap": semantic_ci,
        "operating_confidence_intervals_group_bootstrap": operating_ci,
    }


def _validate_probability_row(
    row: dict[str, str], *, combination_id: str, fold_policy: dict[str, Any]
) -> dict[str, Any]:
    metadata = expected_combination_metadata(combination_id)
    task = str(metadata["task"])
    for key in ("task", "representation", "classifier"):
        if row.get(key) != metadata[key]:
            raise ResultValidationError(
                f"{combination_id}/{row.get('unit_id')}: {key} divergente"
            )
    expected_embedding = metadata["embedding"] or ""
    if row.get("embedding", "") != expected_embedding:
        raise ResultValidationError(
            f"{combination_id}/{row.get('unit_id')}: embedding divergente"
        )
    if not row.get("unit_id") or not row.get("group"):
        raise ResultValidationError(f"{combination_id}: unidade/grupo vazio")
    labels = CLASS_LABELS if task == "classification" else DEDUP_LABELS
    probability_fields = tuple(f"p_{label.lower()}" for label in labels)
    # O CSV agrega as colunas das duas tarefas; as colunas da outra tarefa
    # devem existir vazias, nunca conter uma probabilidade silenciosa.
    observed_probability_fields = tuple(
        key for key, value in row.items() if key.startswith("p_") and value != ""
    )
    if set(observed_probability_fields) != set(probability_fields):
        raise ResultValidationError(
            f"{combination_id}/{row['unit_id']}: campos de probabilidade divergentes"
        )
    probabilities = np.asarray(
        [
            parse_float(
                row.get(field),
                context=f"{combination_id}/{row['unit_id']}/{field}",
            )
            for field in probability_fields
        ],
        dtype=np.float64,
    )
    if np.any(probabilities < 0.0) or np.any(probabilities > 1.0):
        raise ResultValidationError(
            f"{combination_id}/{row['unit_id']}: probabilidade fora de [0,1]"
        )
    if not math.isclose(
        float(np.sum(probabilities)), 1.0, rel_tol=0.0, abs_tol=1e-6
    ):
        raise ResultValidationError(
            f"{combination_id}/{row['unit_id']}: probabilidades não somam 1"
        )
    gold = row.get("gold")
    if gold not in labels:
        raise ResultValidationError(
            f"{combination_id}/{row['unit_id']}: gabarito inválido"
        )
    semantic_index = int(np.argmax(probabilities))
    semantic = labels[semantic_index]
    if row.get("semantic_prediction") != semantic:
        raise ResultValidationError(
            f"{combination_id}/{row['unit_id']}: argmax semântico divergente"
        )
    confidence = float(np.max(probabilities))
    assert_close(
        row.get("confidence"),
        confidence,
        context=f"{combination_id}/{row['unit_id']}/confidence",
    )
    covered = parse_bool(
        row.get("covered", ""),
        context=f"{combination_id}/{row['unit_id']}/covered",
    )
    if task == "classification":
        threshold = fold_policy.get("threshold")
        expected_covered = bool(
            threshold is not None
            and confidence >= float(threshold)
            and semantic != "TRIAGEM_MANUAL"
            and (
                semantic != "OBRA"
                or confidence >= float(fold_policy["obra_threshold"])
            )
        )
        expected_prediction = semantic if expected_covered else "TRIAGEM_MANUAL"
        if expected_covered:
            expected_reason = "AUTOMATIC_DECISION"
        elif threshold is None:
            expected_reason = "NO_ELIGIBLE_POLICY"
        elif semantic == "TRIAGEM_MANUAL":
            expected_reason = "SEMANTIC_TRIAGE"
        elif semantic == "OBRA" and confidence < float(
            fold_policy["obra_threshold"]
        ):
            expected_reason = "OBRA_BELOW_SAFETY_THRESHOLD"
        else:
            expected_reason = "LOW_CONFIDENCE"
        decision_index = semantic_index
    else:
        positive = fold_policy.get("positive_threshold")
        negative = fold_policy.get("negative_threshold")
        if positive is None or negative is None:
            decision_index = -1
        else:
            decision_index = -1
            if probabilities[1] >= float(positive):
                decision_index = 1
            # A implementação congelada aplica o limiar negativo por último.
            if probabilities[1] <= float(negative):
                decision_index = 0
        expected_covered = decision_index >= 0
        expected_prediction = (
            DEDUP_LABELS[decision_index] if expected_covered else "ABSTENCAO"
        )
        expected_reason = (
            "POSITIVE_REQUIRES_HUMAN_CONFIRMATION"
            if decision_index == 1
            else "AUTOMATIC_NEGATIVE"
            if decision_index == 0
            else "AMBIGUOUS_BAND"
        )
    if covered is not expected_covered:
        raise ResultValidationError(
            f"{combination_id}/{row['unit_id']}: cobertura divergente da política"
        )
    if row.get("prediction") != expected_prediction:
        raise ResultValidationError(
            f"{combination_id}/{row['unit_id']}: decisão divergente da política"
        )
    if row.get("review_reason") != expected_reason:
        raise ResultValidationError(
            f"{combination_id}/{row['unit_id']}: motivo de revisão divergente"
        )
    expected_correct = bool(covered and expected_prediction == gold)
    correct = parse_bool(
        row.get("correct", ""),
        context=f"{combination_id}/{row['unit_id']}/correct",
    )
    if correct is not expected_correct:
        raise ResultValidationError(
            f"{combination_id}/{row['unit_id']}: indicador correct divergente"
        )
    return {
        **row,
        "probabilities": probabilities,
        "gold_index": labels.index(str(gold)),
        "semantic_index": semantic_index,
        "decision_index": decision_index,
        "covered_bool": covered,
        "correct_bool": correct,
    }


def _mean_fold_fit_seconds(result: dict[str, Any]) -> float:
    folds = result.get("folds") or []
    if not folds:
        return math.inf
    return statistics.mean(float(row["fit_seconds"]) for row in folds)


def _independent_rank(
    results: Sequence[dict[str, Any]],
    recomputed: dict[str, dict[str, Any]],
    *,
    task: str,
    policy: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    ranked: list[tuple[tuple[Any, ...], str, bool, bool, list[str]]] = []
    for result in results:
        if result["task"] != task:
            continue
        combination_id = str(result["combination_id"])
        metrics = recomputed[combination_id]
        reasons: list[str] = []
        if task == "classification":
            intervals = metrics["confidence_intervals_group_bootstrap"]
            risk_interval = intervals["selective_risk"]
            coverage_interval = intervals["coverage"]
            risk_upper = risk_interval[1] if risk_interval else None
            coverage_lower = coverage_interval[0] if coverage_interval else None
            point = bool(
                metrics["automatic_non_obra_as_obra"]
                <= int(policy["classification_max_automatic_non_obra_as_obra"])
                and metrics["automatic_risk"] is not None
                and metrics["automatic_risk"]
                <= float(policy["classification_max_selective_risk"])
                and metrics["automatic_coverage"]
                >= float(policy["classification_min_coverage"])
            )
            qualified = bool(
                point
                and metrics["automatic_non_obra_as_obra_group_rate_upper"]
                is not None
                and metrics["automatic_non_obra_as_obra_group_rate_upper"]
                <= float(policy["classification_max_critical_group_rate_upper"])
                and risk_upper is not None
                and risk_upper
                <= float(policy["classification_max_selective_risk"])
                and coverage_lower is not None
                and coverage_lower
                >= float(policy["classification_min_coverage"])
            )
            if metrics["automatic_non_obra_as_obra"] > int(
                policy["classification_max_automatic_non_obra_as_obra"]
            ):
                reasons.append("automatic_non_obra_as_obra")
            if metrics["automatic_risk"] is None or metrics[
                "automatic_risk"
            ] > float(policy["classification_max_selective_risk"]):
                reasons.append("classification_selective_risk")
            if metrics["automatic_coverage"] < float(
                policy["classification_min_coverage"]
            ):
                reasons.append("classification_coverage")
            if not qualified:
                reasons.append("classification_critical_upper_confidence")
            if risk_upper is None or risk_upper > float(
                policy["classification_max_selective_risk"]
            ):
                reasons.append("classification_risk_upper_confidence")
            if coverage_lower is None or coverage_lower < float(
                policy["classification_min_coverage"]
            ):
                reasons.append("classification_coverage_lower_confidence")
            key = (
                0 if qualified else 1 if point else 2,
                -float(metrics["macro_f1"]),
                -float(metrics["obra_recall"]),
                -float(metrics["automatic_coverage"]),
                float(metrics["log_loss"]),
                _mean_fold_fit_seconds(result),
                combination_id,
            )
        else:
            intervals = metrics["operating_confidence_intervals_group_bootstrap"]
            fnr = intervals["false_negative_rate"]
            fpr = intervals["false_positive_rate"]
            npv = intervals["negative_predictive_value"]
            precision = intervals["precision"]
            coverage = intervals["decision_coverage"]
            point = bool(
                metrics["automatic_false_negative_rate"]
                <= float(policy["deduplication_max_false_negative_rate"])
                and metrics["negative_predictive_value"] is not None
                and metrics["negative_predictive_value"]
                >= float(policy["deduplication_min_negative_predictive_value"])
                and metrics["automatic_false_positive_rate"]
                <= float(policy["deduplication_max_false_positive_rate"])
                and metrics["precision"] is not None
                and metrics["precision"]
                >= float(policy["deduplication_min_precision"])
                and metrics["decision_coverage"]
                >= float(policy["deduplication_min_coverage"])
            )
            qualified = bool(
                point
                and metrics["false_negative_group_rate_upper"] is not None
                and metrics["false_negative_group_rate_upper"]
                <= float(policy["deduplication_max_false_negative_rate"])
                and metrics["false_positive_group_rate_upper"] is not None
                and metrics["false_positive_group_rate_upper"]
                <= float(policy["deduplication_max_false_positive_rate"])
                and fnr is not None
                and fnr[1] <= float(policy["deduplication_max_false_negative_rate"])
                and fpr is not None
                and fpr[1] <= float(policy["deduplication_max_false_positive_rate"])
                and npv is not None
                and npv[0]
                >= float(policy["deduplication_min_negative_predictive_value"])
                and precision is not None
                and precision[0] >= float(policy["deduplication_min_precision"])
                and coverage is not None
                and coverage[0] >= float(policy["deduplication_min_coverage"])
            )
            if not point:
                reasons.append("deduplication_operating_gate")
            if not qualified:
                reasons.append("deduplication_safety_upper_confidence")
            key = (
                0 if qualified else 1 if point else 2,
                int(metrics["fn"]),
                float(metrics["weighted_error_fn5_fp1_total"]),
                -float(metrics["negative_predictive_value"] or 0.0),
                -float(metrics["precision"] or 0.0),
                -float(metrics["full_automation_coverage"]),
                -float(metrics["decision_coverage"]),
                _mean_fold_fit_seconds(result),
                combination_id,
            )
        ranked.append((key, combination_id, qualified, point, reasons))
    ranked.sort(key=lambda item: item[0])
    rows = [
        {
            "rank": index,
            "task": task,
            "combination_id": combination_id,
            "eligible": qualified,
            "confidence_qualified": qualified,
            "provisional_point_eligible": point,
            "evidence_status": (
                "PASS" if qualified else "UNDERPOWERED" if point else "FAIL"
            ),
            "exclusion_reasons": reasons,
        }
        for index, (_, combination_id, qualified, point, reasons) in enumerate(
            ranked, start=1
        )
    ]
    winner = next((item[1] for item in ranked if item[2]), None)
    provisional = next((item[1] for item in ranked if item[3]), None)
    return rows, winner, provisional


def _flatten_metrics(
    result: dict[str, Any], metrics: dict[str, Any]
) -> dict[str, Any]:
    folds = result.get("folds") or []
    prediction_times = [
        float(row["downstream_predict_ms_per_record"])
        for row in folds
        if row.get("downstream_predict_ms_per_record") is not None
    ]
    output: dict[str, Any] = {
        "combination_id": result["combination_id"],
        "task": result["task"],
        "representation": result["representation"],
        "embedding": result.get("embedding") or "",
        "classifier": result["classifier"],
        "status": result["status"],
        "failure": result.get("failure") or "",
        "elapsed_seconds": result.get("elapsed_seconds"),
        "mean_fold_fit_seconds": (
            statistics.mean(float(row["fit_seconds"]) for row in folds)
            if folds
            else None
        ),
        "mean_downstream_predict_ms_per_record": (
            statistics.mean(prediction_times) if prediction_times else None
        ),
    }
    for key, value in metrics.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            output[key] = value
        elif key in {
            "confidence_intervals_group_bootstrap",
            "semantic_confidence_intervals_group_bootstrap",
            "operating_confidence_intervals_group_bootstrap",
        }:
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
                if interval is not None:
                    output[f"{prefix}_{metric}_ci_lower"] = interval[0]
                    output[f"{prefix}_{metric}_ci_upper"] = interval[1]
    return output


def _paired_operating_metrics(
    rows: Sequence[dict[str, Any]], task: str, config: dict[str, Any]
) -> dict[str, float | None]:
    labels = np.asarray([row["gold_index"] for row in rows], dtype=int)
    semantic = np.asarray([row["semantic_index"] for row in rows], dtype=int)
    covered = np.asarray([row["covered_bool"] for row in rows], dtype=bool)
    if task == "classification":
        errors = covered & (semantic != labels)
        non_obra = covered & (labels != CLASS_LABELS.index("OBRA"))
        critical = non_obra & (semantic == CLASS_LABELS.index("OBRA"))
        return {
            "semantic_accuracy": float(np.mean(semantic == labels)),
            "semantic_macro_f1": float(
                f1_score(
                    labels,
                    semantic,
                    labels=list(range(len(CLASS_LABELS))),
                    average="macro",
                    zero_division=0,
                )
            ),
            "automatic_coverage": float(np.mean(covered)),
            "selective_risk": (
                float(np.sum(errors) / np.sum(covered))
                if np.any(covered)
                else None
            ),
            "critical_non_obra_as_obra_rate": (
                float(np.sum(critical) / np.sum(non_obra))
                if np.any(non_obra)
                else None
            ),
        }
    decisions = np.asarray([row["decision_index"] for row in rows], dtype=int)
    false_negative = (labels == 1) & (decisions == 0)
    false_positive = (labels == 0) & (decisions == 1)
    positives = labels == 1
    negatives = labels == 0
    fn_cost = float(config["objectives"]["deduplication_false_negative_cost"])
    fp_cost = float(config["objectives"]["deduplication_false_positive_cost"])
    return {
        "semantic_accuracy": float(np.mean(semantic == labels)),
        "weighted_error_fn5_fp1_per_record": float(
            (fn_cost * np.sum(false_negative) + fp_cost * np.sum(false_positive))
            / len(labels)
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
        "decision_coverage": float(np.mean(decisions >= 0)),
        "full_automation_coverage": float(np.mean(decisions == 0)),
    }


def _holm_adjust(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    adjusted = [1.0] * len(values)
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, min(1.0, (len(values) - rank) * values[index]))
        adjusted[index] = running
    return adjusted


def _validate_paired_groups(
    observed: Sequence[dict[str, str]],
    predictions: dict[str, list[dict[str, Any]]],
    config: dict[str, Any],
    *,
    tasks: Sequence[str] = ALL_TASKS,
) -> int:
    observed_by_id = unique_by(observed, "contrast_id", context="pareado/grupos")
    expected_ids = {
        item["id"]
        for task in tasks
        for item in config["paired_comparisons"][task]
    }
    if set(observed_by_id) != expected_ids:
        raise ResultValidationError("IDs das comparações pareadas divergentes")
    for task in tasks:
        task_expected: list[dict[str, Any]] = []
        p_values: list[float] = []
        for comparison in config["paired_comparisons"][task]:
            baseline = {row["unit_id"]: row for row in predictions[comparison["baseline"]]}
            candidate = {row["unit_id"]: row for row in predictions[comparison["candidate"]]}
            if set(baseline) != set(candidate):
                raise ResultValidationError(
                    f"Unidades divergentes no contraste {comparison['id']}"
                )
            differences: dict[str, list[float]] = defaultdict(list)
            for unit_id in sorted(baseline):
                base = baseline[unit_id]
                cand = candidate[unit_id]
                for key in ("gold", "group", "fold"):
                    if base[key] != cand[key]:
                        raise ResultValidationError(
                            f"Pareamento divergente em {comparison['id']}/{unit_id}"
                        )
                differences[str(base["group"])].append(
                    float(cand["semantic_prediction"] == cand["gold"])
                    - float(base["semantic_prediction"] == base["gold"])
                )
            values = np.asarray(
                [np.mean(differences[group]) for group in sorted(differences)]
            )
            if np.allclose(values, 0.0):
                statistic, p_value = 0.0, 1.0
            else:
                test = wilcoxon(
                    values,
                    zero_method="pratt",
                    correction=False,
                    alternative="two-sided",
                    method="auto",
                )
                statistic, p_value = float(test.statistic), float(test.pvalue)
            task_expected.append(
                {
                    "contrast_id": comparison["id"],
                    "task": task,
                    "baseline": comparison["baseline"],
                    "candidate": comparison["candidate"],
                    "independent_groups": len(values),
                    "mean_group_accuracy_difference_candidate_minus_baseline": float(np.mean(values)),
                    "median_group_accuracy_difference_candidate_minus_baseline": float(np.median(values)),
                    "groups_candidate_better": int(np.sum(values > 0)),
                    "groups_baseline_better": int(np.sum(values < 0)),
                    "groups_tied": int(np.sum(values == 0)),
                    "wilcoxon_pratt_statistic": statistic,
                    "wilcoxon_pratt_p": p_value,
                    "scope": "semantic_accuracy_descriptive_only",
                }
            )
            p_values.append(p_value)
        for expected, adjusted in zip(task_expected, _holm_adjust(p_values)):
            expected["wilcoxon_pratt_holm_adjusted_p"] = adjusted
            actual = observed_by_id[expected["contrast_id"]]
            for key, value in expected.items():
                assert_close(actual.get(key), value, context=f"pareado/{expected['contrast_id']}/{key}")
    return len(observed)


def _validate_paired_objectives(
    observed: Sequence[dict[str, str]],
    predictions: dict[str, list[dict[str, Any]]],
    config: dict[str, Any],
    *,
    tasks: Sequence[str] = ALL_TASKS,
) -> int:
    expected_keys = {
        (item["id"], metric)
        for task, metrics in {
            "classification": (
                "semantic_accuracy",
                "semantic_macro_f1",
                "automatic_coverage",
                "selective_risk",
                "critical_non_obra_as_obra_rate",
            ),
            "deduplication": (
                "semantic_accuracy",
                "weighted_error_fn5_fp1_per_record",
                "automatic_false_negative_rate",
                "automatic_false_positive_rate",
                "decision_coverage",
                "full_automation_coverage",
            ),
        }.items()
        if task in tasks
        for item in config["paired_comparisons"][task]
        for metric in metrics
    }
    observed_keys = [(row.get("contrast_id"), row.get("metric")) for row in observed]
    if len(set(observed_keys)) != len(observed_keys) or set(observed_keys) != expected_keys:
        raise ResultValidationError("Matriz pareada por objetivos divergente")
    observed_by_key = {key: row for key, row in zip(observed_keys, observed)}
    cv = config["cross_validation"]
    resamples = int(cv["paired_group_bootstrap_resamples"])
    confidence = float(cv["confidence_level"])
    seed = int(cv["outer_seed"]) + 700000
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
    for task in tasks:
        task_offset = task_offsets[task]
        comparisons = config["paired_comparisons"][task]
        baseline_id = comparisons[0]["baseline"]
        baseline_by_unit = {row["unit_id"]: row for row in predictions[baseline_id]}
        units = sorted(baseline_by_unit)
        baseline = [baseline_by_unit[unit] for unit in units]
        groups = [str(row["group"]) for row in baseline]
        unique, draws = _group_draw_counts(
            groups, resamples=resamples, seed=seed + task_offset * 100000
        )
        indices_by_group = {
            group: np.flatnonzero(np.asarray(groups, dtype=object) == group)
            for group in unique
        }
        sampled_indices = [
            np.concatenate(
                [indices_by_group[group] for group, count in zip(unique, draw) for _ in range(int(count))]
            )
            for draw in draws
        ]
        baseline_point = _paired_operating_metrics(baseline, task, config)
        for comparison in comparisons:
            candidate_by_unit = {
                row["unit_id"]: row
                for row in predictions[comparison["candidate"]]
            }
            if set(candidate_by_unit) != set(units):
                raise ResultValidationError(
                    f"Unidades divergentes em {comparison['id']}"
                )
            candidate = [candidate_by_unit[unit] for unit in units]
            candidate_point = _paired_operating_metrics(candidate, task, config)
            differences = {metric: [] for metric in baseline_point}
            for indices in sampled_indices:
                sampled_baseline = [baseline[int(index)] for index in indices]
                sampled_candidate = [candidate[int(index)] for index in indices]
                base_metrics = _paired_operating_metrics(sampled_baseline, task, config)
                cand_metrics = _paired_operating_metrics(sampled_candidate, task, config)
                for metric in differences:
                    if base_metrics[metric] is not None and cand_metrics[metric] is not None:
                        differences[metric].append(
                            float(cand_metrics[metric]) - float(base_metrics[metric])
                        )
            for metric, values in differences.items():
                base_value = baseline_point[metric]
                candidate_value = candidate_point[metric]
                if base_value is None or candidate_value is None or not values:
                    difference = lower = upper = None
                else:
                    difference = float(candidate_value) - float(base_value)
                    interval = _percentile_interval(np.asarray(values), confidence)
                    assert interval is not None
                    lower, upper = interval
                expected = {
                    "contrast_id": comparison["id"],
                    "task": task,
                    "baseline": baseline_id,
                    "candidate": comparison["candidate"],
                    "metric": metric,
                    "better_direction": directions[metric],
                    "baseline_value": base_value,
                    "candidate_value": candidate_value,
                    "difference_candidate_minus_baseline": difference,
                    "difference_ci_lower": lower,
                    "difference_ci_upper": upper,
                    "confidence_level": confidence,
                    "bootstrap_resamples": resamples,
                    "independent_groups": len(unique),
                    "inference_scope": "paired_cluster_bootstrap_development",
                    "equivalence_test": False,
                }
                actual = observed_by_key[(comparison["id"], metric)]
                for key, value in expected.items():
                    assert_close(actual.get(key), value, context=f"pareado_obj/{comparison['id']}/{metric}/{key}")
    return len(observed)


def _assert_finite_tree(value: Any, *, context: str) -> None:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise ResultValidationError(f"Valor não finito em {context}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_finite_tree(item, context=f"{context}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_finite_tree(item, context=f"{context}.{key}")


def _validate_xai(
    xai: Any,
    *,
    config: dict[str, Any],
    selected: dict[str, str],
    evidence_status: dict[str, str],
    family_csv: Sequence[dict[str, str]],
    tasks: Sequence[str] = ALL_TASKS,
) -> int:
    if not isinstance(xai, list):
        raise ResultValidationError("xai.json não contém lista")
    expected_count = int(config["xai"]["finalists_per_task"])
    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in xai:
        by_task[str(item.get("task"))].append(item)
    if set(by_task) != set(tasks) or any(
        len(by_task[task]) != expected_count for task in by_task
    ):
        raise ResultValidationError("XAI não contém um finalista por tarefa")
    for task, items in by_task.items():
        item = items[0]
        if item.get("combination_id") != selected[task]:
            raise ResultValidationError(f"XAI explica candidato errado em {task}")
        if item.get("status") not in {"COMPLETED", "COMPLETED_FALLBACK"}:
            raise ResultValidationError(f"XAI incompleto em {task}")
        if item.get("selection_evidence_status") != evidence_status[task]:
            raise ResultValidationError(
                f"Status de evidência XAI divergente em {task}"
            )
        if item.get("causal_interpretation") is not False:
            raise ResultValidationError("XAI foi apresentado como causal")
        feature_count = item.get("feature_count")
        if isinstance(feature_count, bool) or not isinstance(feature_count, int) or feature_count <= 0:
            raise ResultValidationError(f"Número de atributos XAI inválido em {task}")
        expected_method = (
            "GroupedPermutationImportance"
            if item["status"] == "COMPLETED_FALLBACK"
            else item.get("method")
        )
        if item.get("method") != expected_method or (
            item["status"] == "COMPLETED"
            and item.get("method") not in {"LinearExplainer", "TreeExplainer"}
        ):
            raise ResultValidationError(f"Método XAI inválido em {task}")
        _assert_finite_tree(item, context=f"xai/{task}")
        units = item.get("explained_unit_ids")
        labels = item.get("explained_labels")
        groups = item.get("background_groups")
        if (
            not isinstance(units, list)
            or not isinstance(labels, list)
            or len(units) != len(labels)
            or len(units) != int(config["xai"]["explained_records_per_task"])
            or len(set(units)) != len(units)
        ):
            raise ResultValidationError(f"Amostra XAI inválida em {task}")
        expected_labels = set(range(4 if task == "classification" else 2))
        if set(labels) != expected_labels:
            raise ResultValidationError(f"XAI não amostrou todas as classes em {task}")
        if (
            not isinstance(groups, list)
            or not groups
            or len(groups) > int(config["xai"]["background_groups"])
            or len(set(groups)) != len(groups)
            or item.get("background_groups_sha256") != canonical_sha256(groups)
        ):
            raise ResultValidationError(f"Background XAI inválido em {task}")
        families = item.get("family_importance")
        if not isinstance(families, list) or not families:
            raise ResultValidationError(f"Famílias XAI ausentes em {task}")
        fractions = [
            parse_float(row.get("fraction"), context=f"xai/{task}/fraction")
            for row in families
        ]
        if any(value < 0 or value > 1 for value in fractions) or not (
            math.isclose(sum(fractions), 1.0, abs_tol=1e-8)
            or math.isclose(sum(fractions), 0.0, abs_tol=1e-8)
        ):
            raise ResultValidationError(f"Frações XAI inválidas em {task}")
        if item["status"] == "COMPLETED":
            residual = parse_float(
                item.get("max_absolute_additivity_residual"),
                context=f"xai/{task}/residual",
            )
            tolerance = float(config["xai"]["max_absolute_additivity_residual"])
            if residual > tolerance:
                raise ResultValidationError(f"Aditividade SHAP inválida em {task}")
            local = item.get("local_explanations")
            if not isinstance(local, list) or len(local) != len(units):
                raise ResultValidationError(f"Explicações locais incompletas em {task}")
            if any(abs(float(row["additivity_residual"])) > tolerance for row in local):
                raise ResultValidationError(f"Resíduo local SHAP inválido em {task}")
    expected_family_rows = [
        {"task": item["task"], "combination_id": item["combination_id"], **row}
        for item in xai
        for row in item.get("family_importance", [])
    ]
    if len(family_csv) != len(expected_family_rows):
        raise ResultValidationError("xai_familias.csv incompleto")
    for actual, expected in zip(family_csv, expected_family_rows):
        for key, value in expected.items():
            assert_close(actual.get(key), value, context=f"xai_familias/{key}")
    return len(xai)


def _validate_performance(
    payload: Any,
    csv_rows: Sequence[dict[str, str]],
    *,
    config: dict[str, Any],
    selected: dict[str, str],
    tasks: Sequence[str] = ALL_TASKS,
) -> int:
    if not isinstance(payload, list):
        raise ResultValidationError("Benchmark de latência não contém lista")
    expected_scenarios: dict[str, set[str]] = {}
    if "classification" in tasks:
        expected_scenarios["classification"] = {"classification_raw_text"}
    if "deduplication" in tasks:
        dedup_metadata = expected_combination_metadata(selected["deduplication"])
        dedup_uses_embedding = bool(
            config["representations"][str(dedup_metadata["representation"])][
                "uses_embedding"
            ]
        )
        expected_scenarios["deduplication"] = (
            {
                "deduplication_reference_embedding_cached",
                "deduplication_no_embedding_cache",
            }
            if dedup_uses_embedding
            else {"deduplication_raw_text_tfidf"}
        )
    expected_count = sum(len(values) for values in expected_scenarios.values())
    if len(payload) != expected_count or len(csv_rows) != len(payload):
        raise ResultValidationError(
            "JSON/CSV de latência têm número de cenários divergente do finalista"
        )
    frozen_scenarios = set(config["performance_benchmark"]["scenarios"])
    if not set().union(*expected_scenarios.values()).issubset(frozen_scenarios):
        raise ResultValidationError("Cenário exigido não foi congelado no protocolo")
    observed_scenarios: dict[str, set[str]] = defaultdict(set)
    representations = config["representations"]
    for index, row in enumerate(payload):
        task = str(row.get("task"))
        scenario = str(row.get("scenario"))
        observed_scenarios[task].add(scenario)
        if row.get("status") != "COMPLETED" or row.get("combination_id") != selected.get(task):
            raise ResultValidationError(f"Latência mede candidato inválido em {task}")
        metadata = expected_combination_metadata(str(row["combination_id"]))
        uses_embedding = bool(representations[str(metadata["representation"])]["uses_embedding"])
        expected_calls = 0 if not uses_embedding else 2 if scenario == "deduplication_no_embedding_cache" else 1
        expected = {
            "measurement_scope": "raw_text_to_base_classifier_prediction_before_calibration_and_threshold",
            "device": "cpu",
            "precision": "fp32",
            "seed": int(config["performance_benchmark"]["random_seed"]),
            "records": int(config["performance_benchmark"]["measured_records_per_task"]),
            "warmup_records": int(config["performance_benchmark"]["warmup_records"]),
            "encoder_calls_per_record": expected_calls,
        }
        for key, value in expected.items():
            assert_close(row.get(key), value, context=f"latencia/{task}/{key}")
        for key in (
            "reference_cache_precompute_seconds",
            "cold_encoder_load_seconds",
            "final_base_fit_seconds",
            "latency_ms_p50",
            "latency_ms_p95",
            "throughput_records_per_second",
            "peak_process_rss_mb",
        ):
            value = parse_float(row.get(key), context=f"latencia/{task}/{key}")
            if value < 0:
                raise ResultValidationError(f"Latência negativa em {task}/{key}")
        if float(row["latency_ms_p95"]) < float(row["latency_ms_p50"]):
            raise ResultValidationError(f"p95 menor que p50 em {task}")
        if float(row["throughput_records_per_second"]) <= 0 or float(row["peak_process_rss_mb"]) <= 0:
            raise ResultValidationError(f"Vazão/RAM inválida em {task}")
        optional_peak = row.get("cold_encoder_load_peak_rss_mb")
        if uses_embedding:
            if parse_float(optional_peak, context=f"latencia/{task}/encoder_peak") <= 0:
                raise ResultValidationError("Pico de RAM do encoder inválido")
        elif optional_peak is not None:
            raise ResultValidationError("Pico do encoder presente sem embedding")
        for key, value in row.items():
            assert_close(csv_rows[index].get(key), value, context=f"latencia_csv/{index}/{key}")
    if dict(observed_scenarios) != expected_scenarios:
        raise ResultValidationError("Cenários de latência divergentes")
    return len(payload)


def _validate_retrieval(
    output_dir: Path,
    *,
    result: dict[str, Any],
    config: dict[str, Any],
) -> int:
    summary_csv = read_csv(output_dir / "recuperacao_resumo.csv")
    detail_csv = read_csv(output_dir / "recuperacao_detalhes.csv")
    payload = json.loads((output_dir / "recuperacao.json").read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ResultValidationError("recuperacao.json inválido")
    summary_json = payload.get("summary")
    detail_json = payload.get("details")
    result_summary = result.get("retrieval")
    if not all(isinstance(item, list) for item in (summary_json, detail_json, result_summary)):
        raise ResultValidationError("Artefatos de recuperação incompletos")

    expected_representations = {"tfidf"} | {
        str(item["id"]) for item in config["embeddings"]
    }
    summary_by_representation = unique_by(
        summary_csv, "representation", context="recuperacao_resumo.csv"
    )
    summary_json_by_representation = unique_by(
        summary_json, "representation", context="recuperacao.json/summary"
    )
    result_by_representation = unique_by(
        result_summary, "representation", context="resultados.json/retrieval"
    )
    if not (
        set(summary_by_representation)
        == set(summary_json_by_representation)
        == set(result_by_representation)
        == expected_representations
    ):
        raise ResultValidationError("Recuperação não contém os quatro candidatos")

    detail_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in detail_csv:
        key = (str(row.get("representation")), str(row.get("query_case_id")))
        if not all(key) or key in detail_by_key:
            raise ResultValidationError(f"Detalhe de recuperação duplicado/inválido: {key}")
        if key[0] not in expected_representations:
            raise ResultValidationError(f"Representação de recuperação desconhecida: {key[0]}")
        rank = int(row["rank"])
        reciprocal_rank = parse_float(
            row.get("reciprocal_rank"), context=f"recuperacao/{key}/reciprocal_rank"
        )
        parsed = {
            **row,
            "rank": rank,
            "reciprocal_rank": reciprocal_rank,
            "hit_at_1": parse_bool(row["hit_at_1"], context=f"recuperacao/{key}/hit1"),
            "hit_at_5": parse_bool(row["hit_at_5"], context=f"recuperacao/{key}/hit5"),
            "hit_at_20": parse_bool(row["hit_at_20"], context=f"recuperacao/{key}/hit20"),
        }
        if rank < 1 or not math.isclose(reciprocal_rank, 1.0 / rank, abs_tol=FLOAT_ABS_TOL):
            raise ResultValidationError(f"Rank recíproco inválido: {key}")
        if (
            parsed["hit_at_1"] != (rank <= 1)
            or parsed["hit_at_5"] != (rank <= 5)
            or parsed["hit_at_20"] != (rank <= 20)
        ):
            raise ResultValidationError(f"Indicador de recuperação inválido: {key}")
        detail_by_key[key] = parsed

    detail_json_by_key = {
        (str(row.get("representation")), str(row.get("query_case_id"))): row
        for row in detail_json
    }
    if len(detail_json_by_key) != len(detail_json) or set(detail_json_by_key) != set(detail_by_key):
        raise ResultValidationError("Detalhes JSON/CSV de recuperação divergentes")
    for key, expected_row in detail_json_by_key.items():
        for field, value in expected_row.items():
            assert_close(detail_by_key[key].get(field), value, context=f"recuperacao_detalhe/{key}/{field}")

    queries_by_representation: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for (representation, query), row in detail_by_key.items():
        queries_by_representation[representation][query] = row
    reference_universe: dict[str, str] | None = None
    for representation in sorted(expected_representations):
        rows = list(queries_by_representation[representation].values())
        summary_row = summary_by_representation[representation]
        candidates = int(summary_row["candidates_per_query"])
        if candidates < 1 or any(int(row["rank"]) > candidates for row in rows):
            raise ResultValidationError(f"Pool de recuperação inválido: {representation}")
        universe = {
            str(row["query_case_id"]): str(row["expected_reference_case_id"])
            for row in rows
        }
        if reference_universe is None:
            reference_universe = universe
        elif universe != reference_universe:
            raise ResultValidationError("Universo de consultas diverge entre representações")
        ranks = np.asarray([int(row["rank"]) for row in rows], dtype=float)
        recomputed = {
            "representation": representation,
            "queries": len(rows),
            "candidates_per_query": candidates,
            "recall_at_1": float(np.mean(ranks <= 1)),
            "recall_at_5": float(np.mean(ranks <= 5)),
            "recall_at_20": float(np.mean(ranks <= 20)),
            "mrr": float(np.mean(1.0 / ranks)),
            "ndcg_at_20": float(
                np.mean(np.where(ranks <= 20, 1.0 / np.log2(ranks + 1.0), 0.0))
            ),
            "median_rank": float(np.median(ranks)),
        }
        for field, value in recomputed.items():
            assert_close(summary_row.get(field), value, context=f"recuperacao_resumo/{representation}/{field}")
            assert_close(summary_json_by_representation[representation].get(field), value, context=f"recuperacao_json/{representation}/{field}")
            assert_close(result_by_representation[representation].get(field), value, context=f"recuperacao_resultado/{representation}/{field}")
    return len(detail_by_key)


def _validate_implementation(
    protocol: dict[str, Any],
    environment: dict[str, Any],
    config_path: Path,
    output_dir: Path,
) -> str:
    implementation = protocol.get("implementation")
    if not isinstance(implementation, dict) or implementation != environment.get("implementation"):
        raise ResultValidationError("Manifesto de implementação inconsistente")
    expected_paths = {
        "selection_executor": ROOT / "avaliacao" / "scripts" / "selecionar_modelos_supervisionados.py",
        "training_helper": ROOT / "avaliacao" / "scripts" / "treinar_modelo_local.py",
        "benchmark_requirements": ROOT / "local_ai" / "requirements-benchmark.txt",
        "hybrid_requirements": ROOT / "local_ai" / "requirements-hybrid.txt",
        "granite_requirements": ROOT / "local_ai" / "requirements-granite.txt",
    }
    source_files = implementation.get("source_files")
    if not isinstance(source_files, dict) or set(source_files) != set(expected_paths):
        raise ResultValidationError("Arquivos-fonte congelados divergentes")
    source_hashes: dict[str, str] = {}
    snapshot_names = {
        "selection_executor": "selecionar_modelos_supervisionados.py",
        "training_helper": "treinar_modelo_local.py",
        "benchmark_requirements": "requirements-benchmark.txt",
        "hybrid_requirements": "requirements-hybrid.txt",
        "granite_requirements": "requirements-granite.txt",
    }
    snapshot_manifest_path = output_dir / "source_snapshot" / "manifest.json"
    snapshot_manifest = (
        json.loads(snapshot_manifest_path.read_text(encoding="utf-8"))
        if snapshot_manifest_path.is_file()
        else None
    )
    if isinstance(snapshot_manifest, dict) and (
        snapshot_manifest.get("protocol_sha256") != protocol.get("protocol_sha256")
        or snapshot_manifest.get("run_fingerprint")
        != implementation.get("run_fingerprint")
    ):
        raise ResultValidationError("Manifesto do snapshot de fontes divergente")
    for name, expected_path in expected_paths.items():
        item = source_files[name]
        resolved = expected_path.resolve()
        if Path(item.get("path", "")).resolve() != resolved:
            raise ResultValidationError(f"Caminho-fonte divergente: {name}")
        observed_sha = sha256_file(resolved)
        if item.get("sha256") != observed_sha:
            if not isinstance(snapshot_manifest, dict):
                raise ResultValidationError(
                    f"Fonte alterada após congelamento e snapshot ausente: {name}"
                )
            snapshot_item = snapshot_manifest.get("files", {}).get(name, {})
            snapshot_path = output_dir / "source_snapshot" / snapshot_names[name]
            if (
                snapshot_item.get("path") != snapshot_names[name]
                or snapshot_item.get("sha256") != item.get("sha256")
                or not snapshot_path.is_file()
                or sha256_file(snapshot_path) != item.get("sha256")
            ):
                raise ResultValidationError(
                    f"Snapshot da fonte congelada inválido: {name}"
                )
            observed_sha = str(item["sha256"])
        source_hashes[name] = observed_sha
    packages = environment.get("packages")
    if packages != implementation.get("packages"):
        raise ResultValidationError("Pacotes divergentes no manifesto")
    fingerprint_payload = {
        "protocol_sha256": protocol["protocol_sha256"],
        "config_path": str(config_path.resolve()),
        "source_hashes": source_hashes,
        "packages": packages,
    }
    expected_fingerprint = canonical_sha256(fingerprint_payload)
    if implementation.get("run_fingerprint") != expected_fingerprint:
        raise ResultValidationError("Fingerprint não é reproduzível")
    return expected_fingerprint


def validate(
    output_dir: Path,
    config_path: Path,
    *,
    tasks: Sequence[str] | None = None,
) -> dict[str, Any]:
    required = [
        "ambiente.json",
        "protocolo_congelado.json",
        "dataset_audit.json",
        "resultados.json",
        "resultados_resumo.csv",
        "ranking.csv",
        "dobras.csv",
        "predicoes_oof.csv",
        "comparacao_pareada_grupos.csv",
        "comparacao_pareada_objetivos.csv",
        "recuperacao_resumo.csv",
        "recuperacao_detalhes.csv",
        "recuperacao.json",
        "xai.json",
        "xai_familias.csv",
        "latencia_finalistas.json",
        "latencia_finalistas.csv",
        "RELATORIO.md",
    ]
    missing = [name for name in required if not (output_dir / name).is_file()]
    if missing:
        raise ResultValidationError(f"Arquivos ausentes: {missing}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    explicit_task_scope = tasks is not None
    requested_tasks = tuple(
        tasks or config.get("execution_tasks", list(ALL_TASKS))
    )
    selected_tasks = tuple(
        task for task in ALL_TASKS if task in set(requested_tasks)
    )
    if not selected_tasks or set(requested_tasks) - set(ALL_TASKS):
        raise ResultValidationError(
            f"Escopo de tarefas inválido: {list(requested_tasks)}"
        )
    protocol = json.loads((output_dir / "protocolo_congelado.json").read_text(encoding="utf-8"))
    environment = json.loads((output_dir / "ambiente.json").read_text(encoding="utf-8"))
    result = json.loads((output_dir / "resultados.json").read_text(encoding="utf-8"))
    dataset = json.loads((output_dir / "dataset_audit.json").read_text(encoding="utf-8"))
    protocol_sha = sha256_file(config_path)
    if protocol.get("protocol_sha256") != protocol_sha or protocol.get("config") != config:
        raise ResultValidationError("Protocolo congelado não é idêntico à configuração")
    if environment.get("protocol_path") != str(config_path.resolve()) or environment.get("protocol_sha256") != protocol_sha:
        raise ResultValidationError("Ambiente aponta para protocolo divergente")
    fingerprint = _validate_implementation(
        protocol, environment, config_path, output_dir
    )
    if {protocol.get("run_fingerprint"), result.get("run_fingerprint"), fingerprint} != {fingerprint}:
        raise ResultValidationError("Fingerprint de execução inconsistente")
    for context, payload in (("resultado", result), ("config", config)):
        if payload.get("scientific_result") is not False or payload.get("confirmatory_eligible") is not False or payload.get("development_only") is not True:
            raise ResultValidationError(f"{context} promoveu resultado de desenvolvimento")
    dataset_path = (ROOT / config["dataset"]["path"]).resolve()
    if Path(dataset.get("path", "")).resolve() != dataset_path or sha256_file(dataset_path) != config["dataset"]["sha256"]:
        raise ResultValidationError("Corpus congelado divergente")
    if result.get("dataset") != dataset:
        raise ResultValidationError("Auditoria do dataset divergente no resultado")

    all_expected = expected_combinations(config)
    expected = {
        combination_id
        for combination_id in all_expected
        if expected_combination_metadata(combination_id)["task"]
        in selected_tasks
    }
    results_list = result.get("results")
    if not isinstance(results_list, list):
        raise ResultValidationError("Lista de resultados ausente")
    all_observed_results = unique_by(
        results_list, "combination_id", context="resultados.json"
    )
    if set(all_observed_results) - all_expected:
        raise ResultValidationError(
            "Matriz contém combinações desconhecidas: "
            f"{sorted(set(all_observed_results)-all_expected)[:3]}"
        )
    observed_results = {
        combination_id: item
        for combination_id, item in all_observed_results.items()
        if combination_id in expected
    }
    if set(observed_results) != expected:
        raise ResultValidationError(
            f"Matriz incompleta no escopo: ausentes={sorted(expected-set(observed_results))[:3]}"
        )
    for combination_id, item in observed_results.items():
        metadata = expected_combination_metadata(combination_id)
        for key, value in metadata.items():
            if item.get(key) != value:
                raise ResultValidationError(f"Metadado divergente em {combination_id}/{key}")
        if item.get("status") != "COMPLETED_DEVELOPMENT_OOF" or item.get("outer_oof") is not True or item.get("failure") is not None:
            raise ResultValidationError(f"Configuração não concluída: {combination_id}")
        if item.get("protocol_sha256") != protocol_sha or item.get("run_fingerprint") != fingerprint:
            raise ResultValidationError(f"Hash divergente em {combination_id}")
        if item.get("scientific_result") is not False or item.get("confirmatory_eligible") is not False or item.get("development_only") is not True:
            raise ResultValidationError(f"Configuração promoveu desenvolvimento: {combination_id}")

    folds_csv = read_csv(output_dir / "dobras.csv")
    folds_by_combination: dict[str, list[dict[str, Any]]] = defaultdict(list)
    policies: dict[tuple[str, int], dict[str, Any]] = {}
    for row in folds_csv:
        combination_id = row.get("combination_id", "")
        if combination_id not in expected:
            if combination_id not in all_expected:
                raise ResultValidationError(
                    f"Dobra de combinação desconhecida: {combination_id}"
                )
            continue
        metadata = expected_combination_metadata(combination_id)
        for key in ("task", "representation", "classifier"):
            if row.get(key) != metadata[key]:
                raise ResultValidationError(f"Dobra divergente em {combination_id}/{key}")
        if row.get("embedding", "") != (metadata["embedding"] or ""):
            raise ResultValidationError(f"Embedding divergente em dobra {combination_id}")
        fold = int(row["fold"])
        if (combination_id, fold) in policies:
            raise ResultValidationError(f"Dobra duplicada: {combination_id}/{fold}")
        if int(row["group_overlap"]) != 0:
            raise ResultValidationError("Auditoria de dobra registrou vazamento")
        policy = parse_json_cell(row["calibration_policy"], context=f"{combination_id}/policy")
        split = parse_json_cell(row["calibration_split"], context=f"{combination_id}/split")
        calibration_folds = parse_json_cell(row["calibration_folds"], context=f"{combination_id}/calibration_folds")
        if split.get("group_overlap") != 0 or any(item.get("group_overlap") != 0 for item in calibration_folds):
            raise ResultValidationError(f"Vazamento de calibração em {combination_id}")
        if min(split.get("fit_group_counts_by_label", {}).values(), default=0) < int(config["cross_validation"]["fit_min_groups_per_class"]):
            raise ResultValidationError("Poucos grupos independentes no ajuste")
        if min(split.get("calibration_group_counts_by_label", {}).values(), default=0) < int(config["cross_validation"]["calibration_min_groups_per_class"]):
            raise ResultValidationError("Poucos grupos independentes na calibração")
        minimum = int(config["cross_validation"]["calibration_fold_min_groups_per_class"])
        for calibration_fold in calibration_folds:
            if min(calibration_fold.get("fit_group_counts_by_label", {}).values(), default=0) < minimum or min(calibration_fold.get("validation_group_counts_by_label", {}).values(), default=0) < minimum:
                raise ResultValidationError("Meia-dobra de calibração subdimensionada")
        for numeric in ("fit_seconds", "calibration_seconds", "downstream_predict_seconds", "downstream_predict_ms_per_record"):
            if parse_float(row.get(numeric), context=f"{combination_id}/{numeric}") < 0:
                raise ResultValidationError(f"Tempo negativo em {combination_id}")
        row_copy: dict[str, Any] = dict(row)
        row_copy["fit_seconds"] = float(row["fit_seconds"])
        row_copy["downstream_predict_ms_per_record"] = float(row["downstream_predict_ms_per_record"])
        folds_by_combination[combination_id].append(row_copy)
        policies[(combination_id, fold)] = policy
    outer_folds = int(config["cross_validation"]["outer_folds"])
    for combination_id in expected:
        rows = folds_by_combination[combination_id]
        if sorted(int(row["fold"]) for row in rows) != list(range(outer_folds)):
            raise ResultValidationError(f"Dobras incompletas em {combination_id}")
        json_folds = observed_results[combination_id].get("folds")
        if not isinstance(json_folds, list) or len(json_folds) != outer_folds:
            raise ResultValidationError(f"Dobras JSON incompletas em {combination_id}")
        for json_row, csv_row in zip(json_folds, rows):
            for key, value in json_row.items():
                assert_close(csv_row.get(key), value, context=f"dobras/{combination_id}/{key}")

    raw_predictions = read_csv(output_dir / "predicoes_oof.csv")
    prediction_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    units_seen: set[tuple[str, str]] = set()
    group_folds: dict[tuple[str, str], set[int]] = defaultdict(set)
    for row in raw_predictions:
        combination_id = row.get("combination_id", "")
        if combination_id not in expected:
            if combination_id not in all_expected:
                raise ResultValidationError(
                    f"Predição de combinação desconhecida: {combination_id}"
                )
            continue
        fold = int(row["fold"])
        key = (combination_id, row.get("unit_id", ""))
        if key in units_seen:
            raise ResultValidationError(f"Predição OOF duplicada: {key}")
        units_seen.add(key)
        parsed = _validate_probability_row(row, combination_id=combination_id, fold_policy=policies[(combination_id, fold)])
        prediction_rows[combination_id].append(parsed)
        group_folds[(combination_id, str(row["group"]))].add(fold)
    if any(len(values) != 1 for values in group_folds.values()):
        raise ResultValidationError("Grupo presente em múltiplas dobras")
    for combination_id, item in observed_results.items():
        expected_records = int(dataset["classification_model_records"] if item["task"] == "classification" else dataset["deduplication_pairs"])
        if len(prediction_rows[combination_id]) != expected_records:
            raise ResultValidationError(f"{combination_id}: número de predições divergente")
    for task in selected_tasks:
        task_ids = sorted(cid for cid in expected if cid.startswith(f"{task}__"))
        reference = {row["unit_id"]: (row["gold"], row["group"], row["fold"]) for row in prediction_rows[task_ids[0]]}
        for combination_id in task_ids[1:]:
            candidate = {row["unit_id"]: (row["gold"], row["group"], row["fold"]) for row in prediction_rows[combination_id]}
            if candidate != reference:
                raise ResultValidationError(f"Universo OOF divergente em {combination_id}")

    cache = BootstrapCache()
    recomputed: dict[str, dict[str, Any]] = {}
    for combination_id in sorted(expected):
        item = observed_results[combination_id]
        metrics = (
            _classification_metrics(prediction_rows[combination_id], config=config, cache=cache)
            if item["task"] == "classification"
            else _dedup_metrics(prediction_rows[combination_id], config=config, cache=cache)
        )
        recomputed[combination_id] = metrics
        assert_close(item.get("metrics"), metrics, context=f"metrics/{combination_id}")

    summary_rows = read_csv(output_dir / "resultados_resumo.csv")
    all_summary_by_id = unique_by(
        summary_rows, "combination_id", context="resultados_resumo.csv"
    )
    if set(all_summary_by_id) - all_expected:
        raise ResultValidationError("Resumo contém combinação desconhecida")
    summary_by_id = {
        combination_id: row
        for combination_id, row in all_summary_by_id.items()
        if combination_id in expected
    }
    if set(summary_by_id) != expected:
        raise ResultValidationError("Resumo de resultados incompleto")
    for combination_id in expected:
        flattened = _flatten_metrics(observed_results[combination_id], recomputed[combination_id])
        for key, value in flattened.items():
            assert_close(summary_by_id[combination_id].get(key), value, context=f"resumo/{combination_id}/{key}")

    independent_ranking: list[dict[str, Any]] = []
    winners: dict[str, str | None] = {}
    provisional: dict[str, str | None] = {}
    for task in selected_tasks:
        rows, winner, candidate = _independent_rank(results_list, recomputed, task=task, policy=config["operating_policy"])
        independent_ranking.extend(rows)
        winners[task] = winner
        provisional[task] = candidate
    ranking_csv = [
        row
        for row in read_csv(output_dir / "ranking.csv")
        if row.get("task") in selected_tasks
    ]
    ranking_by_id = unique_by(ranking_csv, "combination_id", context="ranking.csv")
    result_ranking = task_rows(
        result.get("ranking"),
        selected_tasks,
        context="resultados.json/ranking",
    )
    result_ranking_by_id = unique_by(
        result_ranking,
        "combination_id",
        context="resultados.json/ranking",
    )
    if set(ranking_by_id) != expected or set(result_ranking_by_id) != expected:
        raise ResultValidationError("Ranking incompleto")
    for expected_row in independent_ranking:
        combination_id = expected_row["combination_id"]
        for key, value in expected_row.items():
            assert_close(ranking_by_id[combination_id].get(key), value, context=f"ranking_csv/{combination_id}/{key}")
            assert_close(result_ranking_by_id[combination_id].get(key), value, context=f"ranking_json/{combination_id}/{key}")
    for task in selected_tasks:
        if (
            result.get("winners", {}).get(task) != winners[task]
            or result.get("provisional_point_candidates", {}).get(task)
            != provisional[task]
        ):
            raise ResultValidationError(
                "Vencedor/candidato provisório divergente do ranking recalculado"
            )
    selected = {
        task: winners[task] or provisional[task] or next(row["combination_id"] for row in independent_ranking if row["task"] == task)
        for task in selected_tasks
    }

    retrieval_detail_rows = _validate_retrieval(
        output_dir,
        result=result,
        config=config,
    )

    paired_rows = [
        row
        for row in read_csv(output_dir / "comparacao_pareada_grupos.csv")
        if row.get("task") in selected_tasks
    ]
    paired_count = _validate_paired_groups(
        paired_rows, prediction_rows, config, tasks=selected_tasks
    )
    paired_json = task_rows(
        result.get("paired_group_comparison"),
        selected_tasks,
        context="resultados.json/comparacao_pareada",
    )
    if len(paired_json) != len(paired_rows):
        raise ResultValidationError("Comparação pareada JSON/CSV divergente")
    paired_json_by_id = unique_by(
        paired_json, "contrast_id", context="resultados.json/pareado"
    )
    for row in paired_rows:
        for key, value in paired_json_by_id[row["contrast_id"]].items():
            assert_close(row.get(key), value, context=f"pareado_json/{row['contrast_id']}/{key}")

    paired_objective_rows = [
        row
        for row in read_csv(output_dir / "comparacao_pareada_objetivos.csv")
        if row.get("task") in selected_tasks
    ]
    paired_objective_count = _validate_paired_objectives(
        paired_objective_rows,
        prediction_rows,
        config,
        tasks=selected_tasks,
    )
    paired_objective_json = task_rows(
        result.get("paired_objective_comparison"),
        selected_tasks,
        context="resultados.json/objetivos_pareados",
    )
    if len(paired_objective_json) != len(paired_objective_rows):
        raise ResultValidationError("Objetivos pareados JSON/CSV divergentes")
    paired_objective_json_by_key = {
        (str(row.get("contrast_id")), str(row.get("metric"))): row
        for row in paired_objective_json
    }
    if len(paired_objective_json_by_key) != len(paired_objective_json):
        raise ResultValidationError("Objetivo pareado duplicado no JSON")
    for row in paired_objective_rows:
        key = (row["contrast_id"], row["metric"])
        if key not in paired_objective_json_by_key:
            raise ResultValidationError(f"Objetivo pareado ausente no JSON: {key}")
        for field, value in paired_objective_json_by_key[key].items():
            assert_close(row.get(field), value, context=f"pareado_obj_json/{key}/{field}")
    xai_payload = json.loads((output_dir / "xai.json").read_text(encoding="utf-8"))
    xai_payload = [
        row for row in xai_payload if row.get("task") in selected_tasks
    ]
    evidence_status = {
        task: (
            "CONFIDENCE_QUALIFIED_WINNER"
            if winners[task] is not None
            else "PROVISIONAL_POINT_CANDIDATE"
            if provisional[task] is not None
            else "EXPLORATORY_TOP_RANKED_NO_ELIGIBLE_POLICY"
        )
        for task in selected_tasks
    }
    xai_count = _validate_xai(
        xai_payload,
        config=config,
        selected=selected,
        evidence_status=evidence_status,
        family_csv=[
            row
            for row in read_csv(output_dir / "xai_familias.csv")
            if row.get("task") in selected_tasks
        ],
        tasks=selected_tasks,
    )
    result_xai = task_rows(
        result.get("xai"), selected_tasks, context="resultados.json/xai"
    )
    if result_xai != xai_payload:
        raise ResultValidationError("XAI divergente/incompleto no resultado")
    performance_payload = json.loads((output_dir / "latencia_finalistas.json").read_text(encoding="utf-8"))
    performance_payload = [
        row
        for row in performance_payload
        if row.get("task") in selected_tasks and row.get("status") == "COMPLETED"
    ]
    performance_csv = [
        row
        for row in read_csv(output_dir / "latencia_finalistas.csv")
        if row.get("task") in selected_tasks and row.get("status") == "COMPLETED"
    ]
    latency_count = _validate_performance(
        performance_payload,
        performance_csv,
        config=config,
        selected=selected,
        tasks=selected_tasks,
    )
    result_performance = [
        row
        for row in task_rows(
            result.get("performance_benchmark"),
            selected_tasks,
            context="resultados.json/performance_benchmark",
        )
        if row.get("task") in selected_tasks and row.get("status") == "COMPLETED"
    ]
    if result_performance != performance_payload:
        raise ResultValidationError("Benchmark de desempenho divergente/incompleto")

    expected_by_task = Counter(cid.split("__", 1)[0] for cid in expected)
    return {
        "schema": "projeto-ic-validacao-resultados-selecao-v2",
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "VALID_PARTIAL_TASK_SCOPE"
            if explicit_task_scope
            else "VALID"
            if set(selected_tasks) == set(ALL_TASKS)
            else "VALID_CONFIGURED_TASK_SCOPE"
        ),
        "validated_tasks": list(selected_tasks),
        "output_dir": str(output_dir),
        "protocol_sha256": protocol_sha,
        "run_fingerprint": fingerprint,
        "configurations": len(expected),
        "classification_configurations": expected_by_task["classification"],
        "deduplication_configurations": expected_by_task["deduplication"],
        "predictions": sum(len(rows) for rows in prediction_rows.values()),
        "fold_rows": sum(len(rows) for rows in folds_by_combination.values()),
        "paired_group_comparisons": paired_count,
        "paired_objective_comparisons": paired_objective_count,
        "xai_finalists": xai_count,
        "latency_scenarios": latency_count,
        "retrieval_detail_rows": retrieval_detail_rows,
        "retrieval_metrics_recomputed": True,
        "metrics_recomputed_from_oof": True,
        "ranking_recomputed": True,
        "development_only": True,
        "confirmatory_eligible": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Valida independentemente os artefatos da seleção interna."
    )
    parser.add_argument("--saida", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--task",
        choices=list(ALL_TASKS),
        help=(
            "Valida somente uma tarefa concluída de uma rodada parcial. "
            "O status será VALID_PARTIAL_TASK_SCOPE e não validará a rodada inteira."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.saida.resolve()
    tasks = (args.task,) if args.task else None
    audit = validate(output_dir, args.config.resolve(), tasks=tasks)
    audit_path = output_dir / (
        f"validacao_resultados_{args.task}.json"
        if args.task
        else "validacao_resultados.json"
    )
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
