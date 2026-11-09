from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from avaliacao.scripts import benchmark_pareado_local_gemini as benchmark  # noqa: E402


SCHEMA_VERSION = "projeto-ic-local-version-engineering-comparison-v1.0.0"
SUMMARY_FILENAME = "local_only_summary_metrics_v1.2.json"
PLAN_FILENAME = "local_only_plan.json"
UNITS_FILENAME = "local_only_units.jsonl"
PREDICTIONS_FILENAME = "local_only_predictions.jsonl"
DEFAULT_BASELINE_DIR = (
    PROJECT_ROOT / "avaliacao" / "resultados" / "local-only-desenvolvimento-v1"
)
DEFAULT_CANDIDATE_DIR = (
    PROJECT_ROOT
    / "avaliacao"
    / "resultados"
    / "local-only-desenvolvimento-v1.8.0-20260716"
)
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT
    / "avaliacao"
    / "resultados"
    / "comparacao-local-v1.1-v1.8-20260722"
)


class RecommendationPolicy:
    """Critérios explícitos para uma recomendação apenas de engenharia."""

    def __init__(
        self,
        *,
        min_availability_delta: float = 0.0,
        min_semantic_coverage_delta: float = 0.0,
        min_straight_through_automation_delta: float = 0.0,
        max_common_covered_accuracy_regression: float = 0.0,
        max_mean_paired_latency_regression_ms: float = 0.0,
        min_common_covered_units: int = 30,
    ) -> None:
        self.min_availability_delta = min_availability_delta
        self.min_semantic_coverage_delta = min_semantic_coverage_delta
        self.min_straight_through_automation_delta = (
            min_straight_through_automation_delta
        )
        self.max_common_covered_accuracy_regression = (
            max_common_covered_accuracy_regression
        )
        self.max_mean_paired_latency_regression_ms = (
            max_mean_paired_latency_regression_ms
        )
        self.min_common_covered_units = min_common_covered_units

    def as_dict(self) -> dict[str, float | int]:
        return {
            "min_availability_delta": self.min_availability_delta,
            "min_semantic_coverage_delta": self.min_semantic_coverage_delta,
            "min_straight_through_automation_delta": (
                self.min_straight_through_automation_delta
            ),
            "max_common_covered_accuracy_regression": (
                self.max_common_covered_accuracy_regression
            ),
            "max_mean_paired_latency_regression_ms": (
                self.max_mean_paired_latency_regression_ms
            ),
            "min_common_covered_units": self.min_common_covered_units,
        }

    def validate(self) -> None:
        for name in (
            "min_availability_delta",
            "min_semantic_coverage_delta",
            "min_straight_through_automation_delta",
            "max_common_covered_accuracy_regression",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} deve estar entre 0 e 1")
        if self.max_mean_paired_latency_regression_ms < 0:
            raise ValueError(
                "max_mean_paired_latency_regression_ms não pode ser negativo"
            )
        if self.min_common_covered_units < 1:
            raise ValueError("min_common_covered_units deve ser ao menos 1")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Objeto JSON esperado em {path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"Objeto JSON esperado em {path}:{line_number}")
        rows.append(value)
    return rows


def unique_by_unit_id(
    rows: Sequence[dict[str, Any]], source_name: str
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for row in rows:
        unit_id = str(row.get("unit_id") or "")
        if not unit_id:
            raise ValueError(f"unit_id ausente em {source_name}")
        if unit_id in indexed:
            duplicates.append(unit_id)
        indexed[unit_id] = row
    if duplicates:
        sample = ", ".join(sorted(set(duplicates))[:5])
        raise ValueError(f"unit_id duplicado em {source_name}: {sample}")
    return indexed


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compare_identity_fields(
    left: dict[str, dict[str, Any]],
    right: dict[str, dict[str, Any]],
    fields: Sequence[str],
) -> list[dict[str, str]]:
    mismatches: list[dict[str, str]] = []
    for unit_id in sorted(set(left) & set(right)):
        for field in fields:
            if canonical(left[unit_id].get(field)) != canonical(right[unit_id].get(field)):
                mismatches.append({"unit_id": unit_id, "field": field})
    return mismatches


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def resolve_recorded_path(value: Any, source_dir: Path) -> Path:
    recorded = Path(str(value or ""))
    if recorded.is_absolute():
        return recorded
    candidates = [PROJECT_ROOT / recorded, source_dir / recorded]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def _close(left: Any, right: Any, tolerance: float = 1e-12) -> bool:
    if left is None or right is None:
        return left is right
    return math.isclose(float(left), float(right), rel_tol=tolerance, abs_tol=tolerance)


def validate_source(
    source_dir: Path,
    *,
    expected_units: int,
) -> dict[str, Any]:
    source_dir = source_dir.resolve()
    paths = {
        "plan": source_dir / PLAN_FILENAME,
        "summary": source_dir / SUMMARY_FILENAME,
        "units": source_dir / UNITS_FILENAME,
        "predictions": source_dir / PREDICTIONS_FILENAME,
    }
    for name, path in paths.items():
        require(path.is_file(), f"Artefato {name} ausente: {path}")

    plan = load_json(paths["plan"])
    summary = load_json(paths["summary"])
    units = load_jsonl(paths["units"])
    predictions = load_jsonl(paths["predictions"])
    unit_map = unique_by_unit_id(units, str(paths["units"]))
    prediction_map = unique_by_unit_id(predictions, str(paths["predictions"]))

    require(summary.get("schema_version") == "1.2.0", "Resumo fora do contrato 1.2.0")
    require(summary.get("scientific_result") is False, "Resumo local não pode ser confirmatório")
    require(
        summary.get("confirmatory_claim_allowed") is False,
        "Resumo local permitiu alegação confirmatória",
    )
    require(len(units) == expected_units, f"Esperadas {expected_units} unidades; obtidas {len(units)}")
    require(len(predictions) == expected_units, "Quantidade de predições difere das unidades")
    require(set(unit_map) == set(prediction_map), "Predições não correspondem exatamente às unidades")
    require(summary.get("records") == expected_units, "Resumo não declara o total esperado")
    require(
        summary.get("plan_manifest_payload_sha256") == plan.get("manifest_payload_sha256"),
        "Hash lógico do plano diverge do resumo",
    )

    source_hashes = summary.get("metric_recalculation") or {}
    actual_hashes = {name: file_sha256(path) for name, path in paths.items()}
    require(
        source_hashes.get("contract_version") == "1.2.0",
        "Recalculo não declara contrato 1.2.0",
    )
    require(
        source_hashes.get("source_predictions_sha256") == actual_hashes["predictions"],
        "Predições mudaram após o resumo padronizado",
    )
    require(
        source_hashes.get("source_plan_sha256") == actual_hashes["plan"],
        "Plano mudou após o resumo padronizado",
    )

    prediction_identity_mismatches = compare_identity_fields(
        unit_map,
        prediction_map,
        ("shared_input_sha256", "task", "gold", "narrative_core_sha256", "scenario_id"),
    )
    require(
        not prediction_identity_mismatches,
        "Identidade das predições diverge das unidades",
    )

    recalculated = benchmark._provider_metrics(predictions)
    reported = summary["metrics"]["all_contract_valid"]
    for field in (
        "total",
        "valid",
        "failures",
        "abstention_count",
        "routed_to_human_total",
        "semantic_coverage",
        "straight_through_automation_coverage",
        "selective_accuracy",
    ):
        require(
            _close(recalculated.get(field), reported.get(field)),
            f"Métrica padronizada não reproduzida: {field}",
        )
    for field in ("mean", "p50", "p95"):
        require(
            _close(recalculated["latency_ms"].get(field), reported["latency_ms"].get(field)),
            f"Latência padronizada não reproduzida: {field}",
        )

    dataset = plan.get("dataset") or {}
    dataset_path = resolve_recorded_path(dataset.get("path"), source_dir)
    manifest_path = resolve_recorded_path(dataset.get("manifest_path"), source_dir)
    require(dataset_path.is_file(), f"Dataset registrado não encontrado: {dataset_path}")
    require(manifest_path.is_file(), f"Manifesto registrado não encontrado: {manifest_path}")
    actual_dataset_sha256 = file_sha256(dataset_path)
    actual_manifest_sha256 = file_sha256(manifest_path)
    require(
        actual_dataset_sha256 == dataset.get("dataset_sha256"),
        "SHA-256 atual do dataset diverge do plano",
    )
    recorded_manifest_sha256 = dataset.get("manifest_sha256")
    if actual_manifest_sha256 != recorded_manifest_sha256:
        current_manifest = load_json(manifest_path)
        matching_revisions = [
            revision
            for revision in current_manifest.get("manifest_revision_history", [])
            if revision.get("previous_manifest_sha256")
            == recorded_manifest_sha256
        ]
        require(
            len(matching_revisions) == 1,
            "SHA-256 atual do manifesto diverge do plano sem linhagem única",
        )
        revision = matching_revisions[0]
        require(
            revision.get("scope") == "PROVENANCE_ONLY"
            and revision.get("content_data_unchanged") is True
            and revision.get("dataset_sha256") == actual_dataset_sha256,
            "Linhagem do manifesto não comprova alteração apenas de proveniência",
        )

    return {
        "source_dir": source_dir,
        "paths": paths,
        "plan": plan,
        "summary": summary,
        "units": units,
        "unit_map": unit_map,
        "predictions": predictions,
        "prediction_map": prediction_map,
        "artifact_sha256": actual_hashes,
        "dataset_sha256": actual_dataset_sha256,
        "dataset_manifest_sha256": actual_manifest_sha256,
        "recorded_dataset_manifest_sha256": recorded_manifest_sha256,
        "dataset_manifest_lineage_accepted": (
            actual_manifest_sha256 != recorded_manifest_sha256
        ),
    }


def record_flags(row: dict[str, Any]) -> dict[str, bool]:
    semantics = benchmark._record_semantics(row)
    covered = bool(
        semantics["ok"]
        and not semantics["operational_abstention"]
        and semantics["evaluated_label"] not in {None, "ERROR", benchmark.ABSTENTION_LABEL}
    )
    return {
        "availability": bool(semantics["ok"]),
        "semantic_coverage": covered,
        "straight_through_automation": bool(
            semantics["ok"] and not semantics["routed_to_human"]
        ),
        "strict_correctness": bool(semantics["correct"]),
    }


def transition_counts(
    baseline: dict[str, bool], candidate: dict[str, bool]
) -> dict[str, int]:
    both_positive = baseline["value"] and candidate["value"]
    baseline_only = baseline["value"] and not candidate["value"]
    candidate_only = not baseline["value"] and candidate["value"]
    both_negative = not baseline["value"] and not candidate["value"]
    return {
        "both_positive": int(both_positive),
        "baseline_only": int(baseline_only),
        "candidate_only": int(candidate_only),
        "both_negative": int(both_negative),
    }


def aggregate_transitions(
    unit_ids: Iterable[str],
    baseline_map: dict[str, dict[str, Any]],
    candidate_map: dict[str, dict[str, Any]],
) -> dict[str, dict[str, int]]:
    names = (
        "availability",
        "semantic_coverage",
        "straight_through_automation",
        "strict_correctness",
    )
    totals = {
        name: {
            "both_positive": 0,
            "baseline_only": 0,
            "candidate_only": 0,
            "both_negative": 0,
        }
        for name in names
    }
    for unit_id in unit_ids:
        left = record_flags(baseline_map[unit_id])
        right = record_flags(candidate_map[unit_id])
        for name in names:
            counts = transition_counts(
                {"value": left[name]}, {"value": right[name]}
            )
            for cell, value in counts.items():
                totals[name][cell] += value
    return totals


def metric_value(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def marginal_metrics(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    metrics = benchmark._provider_metrics(records)
    total = int(metrics["total"])
    covered = round(float(metrics["semantic_coverage"]) * total)
    straight = round(float(metrics["straight_through_automation_coverage"]) * total)
    correct = sum(record_flags(row)["strict_correctness"] for row in records)
    return {
        "records": total,
        "availability": {
            "numerator": int(metrics["valid"]),
            "denominator": total,
            "value": metric_value(int(metrics["valid"]), total),
        },
        "semantic_coverage": {
            "numerator": covered,
            "denominator": total,
            "value": metrics["semantic_coverage"],
        },
        "straight_through_automation": {
            "numerator": straight,
            "denominator": total,
            "value": metrics["straight_through_automation_coverage"],
        },
        "selective_accuracy": {
            "numerator": correct,
            "denominator": covered,
            "value": metrics["selective_accuracy"],
        },
        "latency_ms_available_only": metrics["latency_ms"],
    }


def metric_delta(left: Any, right: Any) -> float | None:
    if left is None or right is None:
        return None
    return float(right) - float(left)


def compare_marginals(
    baseline_records: Sequence[dict[str, Any]],
    candidate_records: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    baseline = marginal_metrics(baseline_records)
    candidate = marginal_metrics(candidate_records)
    comparison: dict[str, Any] = {
        "records": baseline["records"],
        "baseline": baseline,
        "candidate": candidate,
        "delta_candidate_minus_baseline": {},
    }
    for name in (
        "availability",
        "semantic_coverage",
        "straight_through_automation",
        "selective_accuracy",
    ):
        comparison["delta_candidate_minus_baseline"][name] = metric_delta(
            baseline[name]["value"], candidate[name]["value"]
        )
    comparison["delta_candidate_minus_baseline"]["latency_ms_available_only"] = {
        name: metric_delta(
            baseline["latency_ms_available_only"].get(name),
            candidate["latency_ms_available_only"].get(name),
        )
        for name in ("mean", "p50", "p95")
    }
    return comparison


def percentile(values: Sequence[float], quantile: float) -> float | None:
    return benchmark._percentile(list(values), quantile) if values else None


def paired_latency(
    unit_ids: Iterable[str],
    baseline_map: dict[str, dict[str, Any]],
    candidate_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rows: list[tuple[float, float]] = []
    for unit_id in unit_ids:
        left = baseline_map[unit_id]
        right = candidate_map[unit_id]
        if bool(left.get("ok")) and bool(right.get("ok")):
            rows.append((float(left["latency_ms"]), float(right["latency_ms"])))
    differences = [right - left for left, right in rows]
    return {
        "common_available_records": len(rows),
        "baseline_ms": {
            "mean": statistics.fmean(left for left, _ in rows) if rows else None,
            "p50": percentile([left for left, _ in rows], 0.50),
            "p95": percentile([left for left, _ in rows], 0.95),
        },
        "candidate_ms": {
            "mean": statistics.fmean(right for _, right in rows) if rows else None,
            "p50": percentile([right for _, right in rows], 0.50),
            "p95": percentile([right for _, right in rows], 0.95),
        },
        "paired_difference_candidate_minus_baseline_ms": {
            "mean": statistics.fmean(differences) if differences else None,
            "p50": percentile(differences, 0.50),
            "p95": percentile(differences, 0.95),
            "candidate_faster": sum(value < 0 for value in differences),
            "equal": sum(value == 0 for value in differences),
            "candidate_slower": sum(value > 0 for value in differences),
        },
    }


def common_covered_accuracy(
    unit_ids: Iterable[str],
    baseline_map: dict[str, dict[str, Any]],
    candidate_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    selected: list[str] = []
    for unit_id in unit_ids:
        if (
            record_flags(baseline_map[unit_id])["semantic_coverage"]
            and record_flags(candidate_map[unit_id])["semantic_coverage"]
        ):
            selected.append(unit_id)
    transitions = aggregate_transitions(selected, baseline_map, candidate_map)[
        "strict_correctness"
    ]
    denominator = len(selected)
    baseline_correct = transitions["both_positive"] + transitions["baseline_only"]
    candidate_correct = transitions["both_positive"] + transitions["candidate_only"]
    return {
        "common_covered_records": denominator,
        "baseline_accuracy": metric_value(baseline_correct, denominator),
        "candidate_accuracy": metric_value(candidate_correct, denominator),
        "delta_candidate_minus_baseline": metric_delta(
            metric_value(baseline_correct, denominator),
            metric_value(candidate_correct, denominator),
        ),
        "correctness_transitions": transitions,
    }


def source_public_view(source: dict[str, Any]) -> dict[str, Any]:
    plan = source["plan"]
    return {
        "directory": str(source["source_dir"]),
        "model_version": (plan.get("local_candidate") or {}).get("model_version"),
        "bundle_sha256": (plan.get("local_candidate") or {}).get("bundle_sha256"),
        "summary_contract": source["summary"].get("schema_version"),
        "summary_status": source["summary"].get("status"),
        "dataset_version": (plan.get("dataset") or {}).get("dataset_version"),
        "dataset_sha256": source["dataset_sha256"],
        "dataset_manifest_sha256": source["dataset_manifest_sha256"],
        "artifact_sha256": source["artifact_sha256"],
    }


def _criterion(
    *,
    name: str,
    observed: float | int | None,
    operator: str,
    threshold: float | int,
) -> dict[str, Any]:
    if observed is None:
        passed: bool | None = None
    elif operator == ">=":
        passed = float(observed) >= float(threshold)
    elif operator == "<=":
        passed = float(observed) <= float(threshold)
    else:  # pragma: no cover - contrato interno
        raise ValueError(f"Operador de critério desconhecido: {operator}")
    return {
        "name": name,
        "observed": observed,
        "operator": operator,
        "threshold": threshold,
        "passed": passed,
    }


def evaluate_engineering_recommendation(
    comparisons: dict[str, Any],
    *,
    candidate_version: str | None,
    policy: RecommendationPolicy,
) -> dict[str, Any]:
    """Avalia critérios auditáveis; nunca infere superioridade científica."""
    policy.validate()
    overall = comparisons["overall"]
    marginal = overall["marginal_descriptive_metrics"]
    deltas = marginal["delta_candidate_minus_baseline"]
    common = overall["selective_accuracy_on_common_covered_units"]
    paired_latency_data = overall["latency_on_common_available_units"]
    strict = overall["exact_paired_transition_counts"]["strict_correctness"]
    records = int(marginal["records"])
    strict_delta = (
        (int(strict["candidate_only"]) - int(strict["baseline_only"])) / records
        if records
        else None
    )
    latency_delta = paired_latency_data[
        "paired_difference_candidate_minus_baseline_ms"
    ].get("mean")

    criteria = [
        _criterion(
            name="availability_delta",
            observed=deltas.get("availability"),
            operator=">=",
            threshold=policy.min_availability_delta,
        ),
        _criterion(
            name="semantic_coverage_delta",
            observed=deltas.get("semantic_coverage"),
            operator=">=",
            threshold=policy.min_semantic_coverage_delta,
        ),
        _criterion(
            name="straight_through_automation_delta",
            observed=deltas.get("straight_through_automation"),
            operator=">=",
            threshold=policy.min_straight_through_automation_delta,
        ),
        _criterion(
            name="common_covered_accuracy_delta",
            observed=common.get("delta_candidate_minus_baseline"),
            operator=">=",
            threshold=-policy.max_common_covered_accuracy_regression,
        ),
        _criterion(
            name="strict_correctness_delta_all_units",
            observed=strict_delta,
            operator=">=",
            threshold=0.0,
        ),
        _criterion(
            name="mean_paired_latency_delta_ms",
            observed=latency_delta,
            operator="<=",
            threshold=policy.max_mean_paired_latency_regression_ms,
        ),
        _criterion(
            name="common_covered_units",
            observed=common.get("common_covered_records"),
            operator=">=",
            threshold=policy.min_common_covered_units,
        ),
    ]
    missing = [item["name"] for item in criteria if item["passed"] is None]
    failed = [item["name"] for item in criteria if item["passed"] is False]
    insufficient_support = "common_covered_units" in failed
    if missing:
        status = "INCONCLUSIVE_MISSING_METRICS"
        recommended = False
    elif insufficient_support:
        status = "INCONCLUSIVE_INSUFFICIENT_SUPPORT"
        recommended = False
    elif failed:
        status = "CANDIDATE_NOT_RECOMMENDED"
        recommended = False
    else:
        status = "CANDIDATE_RECOMMENDED_FOR_NEXT_ENGINEERING_STAGE"
        recommended = True
    return {
        "status": status,
        "candidate_version": candidate_version,
        "recommended_for_next_engineering_stage": recommended,
        "policy": policy.as_dict(),
        "criteria": criteria,
        "failed_criteria": failed,
        "missing_criteria": missing,
        "scope": "DESCRIPTIVE_ENGINEERING_ONLY",
        "scientific_superiority_claim_allowed": False,
    }


def build_comparison(
    baseline_dir: Path = DEFAULT_BASELINE_DIR,
    candidate_dir: Path = DEFAULT_CANDIDATE_DIR,
    *,
    expected_units: int = 1240,
    recommendation_policy: RecommendationPolicy | None = None,
) -> dict[str, Any]:
    recommendation_policy = recommendation_policy or RecommendationPolicy()
    recommendation_policy.validate()
    baseline = validate_source(baseline_dir, expected_units=expected_units)
    candidate = validate_source(candidate_dir, expected_units=expected_units)

    baseline_units = baseline["unit_map"]
    candidate_units = candidate["unit_map"]
    require(set(baseline_units) == set(candidate_units), "Conjuntos de unit_id diferem")
    unit_mismatches = compare_identity_fields(
        baseline_units,
        candidate_units,
        ("shared_input_sha256", "task", "gold", "narrative_core_sha256", "scenario_id"),
    )
    require(not unit_mismatches, "Entradas, tarefas ou gabaritos diferem entre versões")
    require(
        baseline["dataset_sha256"] == candidate["dataset_sha256"],
        "Versões usam datasets diferentes",
    )
    require(
        baseline["dataset_manifest_sha256"] == candidate["dataset_manifest_sha256"],
        "Versões usam manifestos de dataset diferentes",
    )
    require(
        baseline["artifact_sha256"]["units"] == candidate["artifact_sha256"]["units"],
        "Arquivos de unidades não são idênticos byte a byte",
    )

    unit_ids = sorted(baseline_units)
    scopes: dict[str, list[str]] = {"overall": unit_ids}
    tasks = sorted({str(baseline_units[unit_id]["task"]) for unit_id in unit_ids})
    for task in tasks:
        scopes[task] = [
            unit_id
            for unit_id in unit_ids
            if str(baseline_units[unit_id]["task"]) == task
        ]

    comparisons: dict[str, Any] = {}
    for scope, scope_ids in scopes.items():
        baseline_records = [baseline["prediction_map"][unit_id] for unit_id in scope_ids]
        candidate_records = [candidate["prediction_map"][unit_id] for unit_id in scope_ids]
        comparisons[scope] = {
            "marginal_descriptive_metrics": compare_marginals(
                baseline_records, candidate_records
            ),
            "exact_paired_transition_counts": aggregate_transitions(
                scope_ids, baseline["prediction_map"], candidate["prediction_map"]
            ),
            "selective_accuracy_on_common_covered_units": common_covered_accuracy(
                scope_ids, baseline["prediction_map"], candidate["prediction_map"]
            ),
            "latency_on_common_available_units": paired_latency(
                scope_ids, baseline["prediction_map"], candidate["prediction_map"]
            ),
        }

    overall = comparisons["overall"]["marginal_descriptive_metrics"]
    baseline_metrics = overall["baseline"]
    candidate_metrics = overall["candidate"]
    candidate_version = (candidate["plan"].get("local_candidate") or {}).get(
        "model_version"
    )
    recommendation = evaluate_engineering_recommendation(
        comparisons,
        candidate_version=candidate_version,
        policy=recommendation_policy,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "DESCRIPTIVE_ENGINEERING_COMPARISON_NON_CONFIRMATORY",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scientific_scope": {
            "confirmatory_result": False,
            "generalization_claim_allowed": False,
            "significance_test_performed": False,
            "noninferiority_test_performed": False,
            "reason": (
                "As duas versões foram reexecutadas no mesmo corpus sintético de "
                "desenvolvimento; as realizações do mesmo núcleo semântico não são "
                "uma amostra externa independente."
            ),
        },
        "sources": {
            "baseline": source_public_view(baseline),
            "candidate": source_public_view(candidate),
            "metric_contract_implementation": {
                "path": str(Path(benchmark.__file__).resolve()),
                "sha256": file_sha256(Path(benchmark.__file__).resolve()),
                "contract": "1.2.0",
            },
        },
        "pairing_validation": {
            "passed": True,
            "expected_units": expected_units,
            "baseline_unique_unit_ids": len(baseline_units),
            "candidate_unique_unit_ids": len(candidate_units),
            "unit_id_sets_identical": True,
            "unit_files_byte_identical": True,
            "unit_file_sha256": baseline["artifact_sha256"]["units"],
            "shared_input_sha256_identical_for_all_units": True,
            "gold_identical_for_all_units": True,
            "task_identical_for_all_units": True,
            "dataset_sha256_identical": True,
            "dataset_manifest_sha256_identical": True,
            "prediction_identity_matches_units": True,
            "standardized_summary_metrics_reproduced": True,
        },
        "comparisons": comparisons,
        "engineering_interpretation": {
            "candidate_improves_availability": (
                candidate_metrics["availability"]["value"]
                > baseline_metrics["availability"]["value"]
            ),
            "candidate_improves_semantic_coverage": (
                candidate_metrics["semantic_coverage"]["value"]
                > baseline_metrics["semantic_coverage"]["value"]
            ),
            "candidate_improves_straight_through_automation": (
                candidate_metrics["straight_through_automation"]["value"]
                > baseline_metrics["straight_through_automation"]["value"]
            ),
            "candidate_improves_mean_available_latency": (
                candidate_metrics["latency_ms_available_only"]["mean"]
                < baseline_metrics["latency_ms_available_only"]["mean"]
            ),
            "candidate_equal_or_higher_selective_accuracy": (
                candidate_metrics["selective_accuracy"]["value"]
                >= baseline_metrics["selective_accuracy"]["value"]
            ),
            "recommended_for_next_engineering_stage": recommendation[
                "recommended_for_next_engineering_stage"
            ],
            "not_proven_superior_in_generalization": True,
            "recommendation": recommendation,
        },
    }


def format_percent(value: Any) -> str:
    return "n/a" if value is None else f"{100 * float(value):.2f}%"


def format_percentage_points(value: Any) -> str:
    return "n/a" if value is None else f"{100 * float(value):.2f} p.p."


def format_number(value: Any, digits: int = 3) -> str:
    return "n/a" if value is None else f"{float(value):.{digits}f}"


def render_markdown(report: dict[str, Any]) -> str:
    overall = report["comparisons"]["overall"]
    marginal = overall["marginal_descriptive_metrics"]
    left = marginal["baseline"]
    right = marginal["candidate"]
    delta = marginal["delta_candidate_minus_baseline"]
    transitions = overall["exact_paired_transition_counts"]
    common_accuracy = overall["selective_accuracy_on_common_covered_units"]
    paired_latency_data = overall["latency_on_common_available_units"]
    baseline_version = report["sources"]["baseline"]["model_version"]
    candidate_version = report["sources"]["candidate"]["model_version"]
    recommendation = report["engineering_interpretation"]["recommendation"]

    rows = []
    for name, label in (
        ("availability", "Disponibilidade"),
        ("semantic_coverage", "Cobertura semântica"),
        ("straight_through_automation", "Automação sem revisão humana"),
        ("selective_accuracy", "Acurácia seletiva"),
    ):
        rows.append(
            f"| {label} | {left[name]['numerator']}/{left[name]['denominator']} "
            f"({format_percent(left[name]['value'])}) | "
            f"{right[name]['numerator']}/{right[name]['denominator']} "
            f"({format_percent(right[name]['value'])}) | "
            f"{format_percentage_points(delta[name])} |"
        )

    transition_rows = []
    for name, label in (
        ("availability", "Disponível"),
        ("semantic_coverage", "Decisão semântica coberta"),
        ("straight_through_automation", "Automação direta"),
        ("strict_correctness", "Correto, tratando falha/abstenção como erro"),
    ):
        value = transitions[name]
        transition_rows.append(
            f"| {label} | {value['both_positive']} | {value['baseline_only']} | "
            f"{value['candidate_only']} | {value['both_negative']} |"
        )

    criteria_rows = [
        "| Critério | Observado | Regra | Limite | Resultado |",
        "|---|---:|:---:|---:|:---:|",
    ]
    for criterion in recommendation["criteria"]:
        passed = criterion["passed"]
        result = "PASS" if passed is True else "FAIL" if passed is False else "INDEFINIDO"
        criteria_rows.append(
            f"| `{criterion['name']}` | {format_number(criterion['observed'], 6)} | "
            f"{criterion['operator']} | {format_number(criterion['threshold'], 6)} | "
            f"{result} |"
        )

    baseline_failures = int(left["records"]) - int(left["availability"]["numerator"])
    candidate_failures = int(right["records"]) - int(
        right["availability"]["numerator"]
    )
    recommendation_status = recommendation["status"]
    if recommendation["recommended_for_next_engineering_stage"]:
        recommendation_text = (
            f"{candidate_version} atende todos os critérios explícitos desta "
            "execução e, por isso, é recomendado somente para a próxima etapa "
            "de engenharia."
        )
    elif recommendation_status.startswith("INCONCLUSIVE_"):
        recommendation_text = (
            "A comparação é inconclusiva para recomendação de engenharia, "
            "pois faltam métricas ou suporte exigidos pela política."
        )
    else:
        failed = ", ".join(recommendation["failed_criteria"])
        recommendation_text = (
            f"{candidate_version} não é recomendado pela política desta "
            f"execução; critérios não atendidos: {failed}."
        )

    return "\n".join(
        [
            f"# Comparação local {baseline_version} versus {candidate_version}",
            "",
            f"**Status:** comparação descritiva de engenharia, não confirmatória.  "
            f"**Unidades pareadas:** {report['pairing_validation']['expected_units']}.  "
            "**Contrato das métricas:** 1.2.0.",
            "",
            "## Validação do pareamento",
            "",
            "Os dois testes usam exatamente os mesmos `unit_id`, entradas "
            "(`shared_input_sha256`), tarefas, gabaritos, dataset e manifesto. "
            f"O arquivo de unidades é idêntico byte a byte (SHA-256 "
            f"`{report['pairing_validation']['unit_file_sha256']}`). Os hashes das "
            "predições também correspondem aos registrados nos resumos padronizados.",
            "",
            "## Resultados gerais",
            "",
            f"| Métrica | {baseline_version} | {candidate_version} | "
            f"Delta {candidate_version} - {baseline_version} |",
            "|---|---:|---:|---:|",
            *rows,
            "| Latência média entre respostas disponíveis | "
            f"{format_number(left['latency_ms_available_only']['mean'])} ms | "
            f"{format_number(right['latency_ms_available_only']['mean'])} ms | "
            f"{format_number(delta['latency_ms_available_only']['mean'])} ms |",
            "| Latência p50 entre respostas disponíveis | "
            f"{format_number(left['latency_ms_available_only']['p50'])} ms | "
            f"{format_number(right['latency_ms_available_only']['p50'])} ms | "
            f"{format_number(delta['latency_ms_available_only']['p50'])} ms |",
            "| Latência p95 entre respostas disponíveis | "
            f"{format_number(left['latency_ms_available_only']['p95'])} ms | "
            f"{format_number(right['latency_ms_available_only']['p95'])} ms | "
            f"{format_number(delta['latency_ms_available_only']['p95'])} ms |",
            "",
            f"As falhas operacionais passaram de {baseline_failures} em "
            f"{baseline_version} para {candidate_failures} em {candidate_version}. "
            "A acurácia seletiva marginal passou de "
            f"{format_percent(left['selective_accuracy']['value'])} "
            f"({left['selective_accuracy']['numerator']} acertos em "
            f"{left['selective_accuracy']['denominator']} decisões cobertas) para "
            f"{format_percent(right['selective_accuracy']['value'])} "
            f"({right['selective_accuracy']['numerator']} acertos em "
            f"{right['selective_accuracy']['denominator']} decisões cobertas): "
            "são denominadores diferentes, "
            "portanto esse contraste não deve ser interpretado isoladamente.",
            "",
            "## Contagens pareadas exatas",
            "",
            f"| Evento | Ambas | Somente {baseline_version} | Somente {candidate_version} | Nenhuma |",
            "|---|---:|---:|---:|---:|",
            *transition_rows,
            "",
            "Nas unidades cobertas pelas duas versões, a acurácia foi "
            f"{format_percent(common_accuracy['baseline_accuracy'])} em "
            f"{baseline_version} e "
            f"{format_percent(common_accuracy['candidate_accuracy'])} em "
            f"{candidate_version} "
            f"(n={common_accuracy['common_covered_records']}). Para latência, existem "
            f"{paired_latency_data['common_available_records']} unidades com resposta "
            "disponível nas duas versões; a diferença média pareada "
            f"({candidate_version} - {baseline_version}) foi "
            f"{format_number(paired_latency_data['paired_difference_candidate_minus_baseline_ms']['mean'])} ms.",
            "",
            "## Critérios da recomendação de engenharia",
            "",
            *criteria_rows,
            "",
            f"**Decisão derivada:** `{recommendation_status}`. "
            f"{recommendation_text}",
            "",
            "## Limite da interpretação",
            "",
            "A recomendação acima não escolhe automaticamente uma versão por "
            "nome e não equivale a superioridade científica. Não foi demonstrada "
            "superioridade em "
            "generalização: o corpus é sintético, pertence ao desenvolvimento e possui "
            "variações do mesmo núcleo semântico. Por isso não foram executados testes "
            "de significância ou não inferioridade e este relatório não valida o modelo "
            "cientificamente em dados externos.",
            "",
            "## Reprodução",
            "",
            "```powershell",
            "python avaliacao\\scripts\\comparar_versoes_locais.py",
            "```",
            "",
        ]
    )


def csv_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scope, comparison in report["comparisons"].items():
        marginal = comparison["marginal_descriptive_metrics"]
        for metric in (
            "availability",
            "semantic_coverage",
            "straight_through_automation",
            "selective_accuracy",
        ):
            left = marginal["baseline"][metric]
            right = marginal["candidate"][metric]
            transitions = comparison["exact_paired_transition_counts"].get(metric)
            if metric == "selective_accuracy":
                transitions = None
            rows.append(
                {
                    "section": "marginal_metric",
                    "scope": scope,
                    "metric": metric,
                    "baseline_numerator": left["numerator"],
                    "baseline_denominator": left["denominator"],
                    "baseline_value": left["value"],
                    "candidate_numerator": right["numerator"],
                    "candidate_denominator": right["denominator"],
                    "candidate_value": right["value"],
                    "delta_candidate_minus_baseline": marginal[
                        "delta_candidate_minus_baseline"
                    ][metric],
                    "paired_n": marginal["records"],
                    "both_positive": (transitions or {}).get("both_positive"),
                    "baseline_only": (transitions or {}).get("baseline_only"),
                    "candidate_only": (transitions or {}).get("candidate_only"),
                    "both_negative": (transitions or {}).get("both_negative"),
                    "note": "descritivo; corpus de desenvolvimento",
                }
            )
        latency = comparison["latency_on_common_available_units"]
        for metric in ("mean", "p50", "p95"):
            rows.append(
                {
                    "section": "paired_latency",
                    "scope": scope,
                    "metric": f"latency_ms_{metric}",
                    "baseline_numerator": "",
                    "baseline_denominator": "",
                    "baseline_value": latency["baseline_ms"][metric],
                    "candidate_numerator": "",
                    "candidate_denominator": "",
                    "candidate_value": latency["candidate_ms"][metric],
                    "delta_candidate_minus_baseline": (
                        latency["paired_difference_candidate_minus_baseline_ms"][metric]
                        if metric in {"mean", "p50", "p95"}
                        else None
                    ),
                    "paired_n": latency["common_available_records"],
                    "both_positive": "",
                    "baseline_only": "",
                    "candidate_only": "",
                    "both_negative": "",
                    "note": "somente unidades disponíveis nas duas versões",
                }
            )
        strict = comparison["exact_paired_transition_counts"]["strict_correctness"]
        rows.append(
            {
                "section": "paired_transition",
                "scope": scope,
                "metric": "strict_correctness",
                "baseline_numerator": strict["both_positive"] + strict["baseline_only"],
                "baseline_denominator": marginal["records"],
                "baseline_value": metric_value(
                    strict["both_positive"] + strict["baseline_only"], marginal["records"]
                ),
                "candidate_numerator": strict["both_positive"] + strict["candidate_only"],
                "candidate_denominator": marginal["records"],
                "candidate_value": metric_value(
                    strict["both_positive"] + strict["candidate_only"], marginal["records"]
                ),
                "delta_candidate_minus_baseline": (
                    strict["candidate_only"] - strict["baseline_only"]
                )
                / marginal["records"],
                "paired_n": marginal["records"],
                "both_positive": strict["both_positive"],
                "baseline_only": strict["baseline_only"],
                "candidate_only": strict["candidate_only"],
                "both_negative": strict["both_negative"],
                "note": "falha e abstencao contam como incorretas",
            }
        )
    return rows


def write_outputs(report: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": output_dir / "comparacao_versoes_locais.json",
        "csv": output_dir / "comparacao_versoes_locais.csv",
        "markdown": output_dir / "RELATORIO.md",
    }
    paths["json"].write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    rows = csv_rows(report)
    fieldnames = list(rows[0])
    with paths["csv"].open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    paths["markdown"].write_text(render_markdown(report), encoding="utf-8")
    return paths


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compara, de forma pareada e descritiva, duas versões locais."
    )
    parser.add_argument("--baseline-dir", type=Path, default=DEFAULT_BASELINE_DIR)
    parser.add_argument("--candidate-dir", type=Path, default=DEFAULT_CANDIDATE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--expected-units", type=int, default=1240)
    parser.add_argument(
        "--min-availability-improvement-pp",
        type=float,
        default=0.0,
        help="Melhoria mínima de disponibilidade, em pontos percentuais.",
    )
    parser.add_argument(
        "--min-semantic-coverage-improvement-pp",
        type=float,
        default=0.0,
        help="Melhoria mínima de cobertura semântica, em pontos percentuais.",
    )
    parser.add_argument(
        "--min-straight-through-improvement-pp",
        type=float,
        default=0.0,
        help="Melhoria mínima de automação direta, em pontos percentuais.",
    )
    parser.add_argument(
        "--max-common-accuracy-regression-pp",
        type=float,
        default=0.0,
        help=(
            "Regressão máxima aceita na acurácia das unidades cobertas por "
            "ambas as versões, em pontos percentuais."
        ),
    )
    parser.add_argument(
        "--max-mean-paired-latency-regression-ms",
        type=float,
        default=0.0,
        help="Aumento médio pareado de latência aceito, em milissegundos.",
    )
    parser.add_argument(
        "--min-common-covered-units",
        type=int,
        default=30,
        help="Suporte mínimo para comparar acurácia nas unidades cobertas por ambas.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    policy = RecommendationPolicy(
        min_availability_delta=args.min_availability_improvement_pp / 100.0,
        min_semantic_coverage_delta=(
            args.min_semantic_coverage_improvement_pp / 100.0
        ),
        min_straight_through_automation_delta=(
            args.min_straight_through_improvement_pp / 100.0
        ),
        max_common_covered_accuracy_regression=(
            args.max_common_accuracy_regression_pp / 100.0
        ),
        max_mean_paired_latency_regression_ms=(
            args.max_mean_paired_latency_regression_ms
        ),
        min_common_covered_units=args.min_common_covered_units,
    )
    policy.validate()
    report = build_comparison(
        args.baseline_dir,
        args.candidate_dir,
        expected_units=args.expected_units,
        recommendation_policy=policy,
    )
    paths = write_outputs(report, args.output_dir.resolve())
    print(json.dumps({name: str(path) for name, path in paths.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
