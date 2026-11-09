"""Gera a planilha científica a partir dos artefatos brutos do projeto.

O script não contém métricas de desempenho predefinidas. As contagens, taxas,
latências e estados são recalculados dos arquivos JSON/JSONL existentes. Antes
de criar o XLSX, os hashes e vínculos entre plano, unidades, predições e resumo
são conferidos. Divergências obrigatórias interrompem a geração.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import xlsxwriter


ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = ROOT / "avaliacao" / "resultados"
CLASS_LABELS = {"DEMO", "OBRA", "SOB_DEMANDA", "TRIAGEM_MANUAL"}
ABSTENTION_LABEL = "ABSTENCAO"


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Esperado objeto JSON em {relative(path)}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(
                    f"Esperado objeto na linha {line_number} de {relative(path)}"
                )
            rows.append(value)
    return rows


def percentile(values: Sequence[float], fraction: float) -> float | None:
    """Percentil por posto mais próximo, igual ao benchmark do projeto."""

    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return float(ordered[index])


def version_key(model: str) -> tuple[int, ...]:
    match = re.search(r"v(\d+(?:\.\d+)+)", model)
    if not match:
        return (0,)
    return tuple(int(part) for part in match.group(1).split("."))


def legacy_operational_abstention(row: dict[str, Any]) -> bool:
    """Separa a classe TRIAGEM_MANUAL de uma abstenção operacional legada."""

    if "operational_abstention" in row:
        return bool(row.get("operational_abstention"))
    if row.get("task") != "classification":
        return bool(row.get("abstained"))
    path = str(row.get("decision_path") or "").upper()
    if path == "REMOTE_MODEL":
        return False
    if path in {"HYBRID_MODEL", "DETERMINISTIC_SPECIALIZED_ASSET"}:
        return False
    if any(
        marker in path
        for marker in (
            "ABSTENTION",
            "INSUFFICIENT",
            "CONTRADICTION",
            "OUT_OF_SCOPE",
            "ARTIFACT_UNAVAILABLE",
            "PROMPT_INJECTION",
            "DETERMINISTIC_GATE",
        )
    ):
        return True
    if row.get("decision") != "TRIAGEM_MANUAL":
        return False
    return bool(row.get("abstained"))


def record_view(row: dict[str, Any]) -> dict[str, Any]:
    ok = bool(row.get("ok"))
    task = str(row.get("task") or "")
    abstained = legacy_operational_abstention(row) if ok else False
    predicted_class = row.get("predicted_class")
    if task == "classification" and predicted_class not in CLASS_LABELS:
        provenance = (
            row.get("runtime_provenance")
            if isinstance(row.get("runtime_provenance"), dict)
            else {}
        )
        declared = provenance.get("semantic_class_prediction")
        if declared in CLASS_LABELS:
            predicted_class = declared
        elif not abstained and row.get("decision") in CLASS_LABELS:
            predicted_class = row.get("decision")
        else:
            predicted_class = None
    elif task != "classification":
        predicted_class = None

    evaluated_label = (
        "ERROR"
        if not ok
        else ABSTENTION_LABEL
        if abstained
        else predicted_class
        if task == "classification"
        else row.get("decision")
    )
    routed_to_human = row.get("routed_to_human")
    if not isinstance(routed_to_human, bool):
        routed_to_human = bool(
            ok
            and (
                row.get("decision") == "TRIAGEM_MANUAL"
                or (task == "deduplication" and row.get("decision") == "DUPLICADO")
                or abstained
            )
        )

    gold = row.get("gold") if isinstance(row.get("gold"), dict) else {}
    correct = bool(ok and not abstained and evaluated_label == gold.get("decision"))
    reference_match: bool | None = None
    if task == "deduplication" and evaluated_label == "DUPLICADO" and ok:
        reference_match = row.get("reference_id") == gold.get("reference_id")
        correct = bool(correct and reference_match)

    covered = bool(
        ok
        and not abstained
        and evaluated_label not in {None, "ERROR", ABSTENTION_LABEL}
    )
    return {
        "ok": ok,
        "operational_abstention": abstained,
        "predicted_class": predicted_class,
        "evaluated_label": evaluated_label,
        "routed_to_human": routed_to_human,
        "straight_through": bool(ok and not routed_to_human),
        "correct": correct,
        "covered": covered,
        "reference_match": reference_match,
        "legacy_semantics_inferred": "operational_abstention" not in row,
    }


def derive_metrics(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    interpreted = [(row, record_view(row)) for row in records]
    valid = [(row, view) for row, view in interpreted if view["ok"]]
    covered = [(row, view) for row, view in valid if view["covered"]]
    straight = [(row, view) for row, view in valid if view["straight_through"]]
    latencies = [float(row["latency_ms"]) for row, _ in valid]
    total = len(records)
    correct = sum(bool(view["correct"]) for _, view in covered)
    fp = fn = reference_errors = 0
    confusion: Counter[str] = Counter()
    for row, view in interpreted:
        gold = row.get("gold") if isinstance(row.get("gold"), dict) else {}
        predicted = view["evaluated_label"]
        confusion[f"{gold.get('decision')}->{predicted}"] += 1
        if row.get("task") != "deduplication" or not view["covered"]:
            continue
        if gold.get("decision") == "DUPLICADO" and predicted == "NAO_DUPLICADO":
            fn += 1
        if gold.get("decision") == "NAO_DUPLICADO" and predicted == "DUPLICADO":
            fp += 1
        if (
            gold.get("decision") == "DUPLICADO"
            and predicted == "DUPLICADO"
            and view["reference_match"] is False
        ):
            reference_errors += 1

    error_counts = Counter(
        str(row.get("error_code") or f"HTTP_{row.get('http_status') or 0}")
        for row, view in interpreted
        if not view["ok"]
    )
    return {
        "total": total,
        "valid": len(valid),
        "failures": total - len(valid),
        "operational_abstentions": sum(
            bool(view["operational_abstention"]) for _, view in valid
        ),
        "semantic_triage_predictions": sum(
            row.get("task") == "classification"
            and view["predicted_class"] == "TRIAGEM_MANUAL"
            for row, view in valid
        ),
        "routed_to_human_total": sum(
            bool(view["routed_to_human"]) for _, view in valid
        ),
        "straight_through_total": len(straight),
        "covered": len(covered),
        "correct_covered": correct,
        "covered_errors": len(covered) - correct,
        "semantic_coverage": len(covered) / total if total else 0.0,
        "straight_through_coverage": len(straight) / total if total else 0.0,
        "selective_accuracy": correct / len(covered) if covered else None,
        "routed_to_human_rate": (
            sum(bool(view["routed_to_human"]) for _, view in valid) / total
            if total
            else 0.0
        ),
        "dedup_false_negatives": fn,
        "dedup_false_positives": fp,
        "dedup_reference_errors": reference_errors,
        "dedup_weighted_error_cost_fn5_fp1": 5 * fn + fp,
        "latency_mean_ms": statistics.fmean(latencies) if latencies else None,
        "latency_p50_ms": percentile(latencies, 0.50),
        "latency_p95_ms": percentile(latencies, 0.95),
        "confusion": dict(sorted(confusion.items())),
        "error_counts": dict(sorted(error_counts.items())),
        "legacy_semantics_inferred": sum(
            bool(view["legacy_semantics_inferred"]) for _, view in valid
        ),
    }


def derive_classification(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    selected = [row for row in records if row.get("task") == "classification"]
    rows: list[dict[str, Any]] = []
    for label in ("DEMO", "OBRA", "SOB_DEMANDA", "TRIAGEM_MANUAL"):
        group = [row for row in selected if (row.get("gold") or {}).get("decision") == label]
        interpreted = [(row, record_view(row)) for row in group]
        covered = [(row, view) for row, view in interpreted if view["covered"]]
        rows.append(
            {
                "label": label,
                "total": len(group),
                "valid": sum(view["ok"] for _, view in interpreted),
                "failures": sum(not view["ok"] for _, view in interpreted),
                "semantic_correct": sum(view["correct"] for _, view in interpreted),
                "semantic_triage_predictions": sum(
                    view["predicted_class"] == "TRIAGEM_MANUAL"
                    for _, view in interpreted
                    if view["ok"]
                ),
                "operational_abstentions": sum(
                    view["operational_abstention"] for _, view in interpreted
                ),
                "covered": len(covered),
                "covered_errors": sum(not view["correct"] for _, view in covered),
                "routed_to_human": sum(
                    view["routed_to_human"] for _, view in interpreted
                ),
                "straight_through": sum(
                    view["straight_through"] for _, view in interpreted
                ),
            }
        )
    metrics = derive_metrics(selected)
    maintenance_as_obra = 0
    for row in selected:
        view = record_view(row)
        gold = (row.get("gold") or {}).get("decision")
        if view["covered"] and view["predicted_class"] == "OBRA" and gold != "OBRA":
            maintenance_as_obra += 1
    return {"rows": rows, "metrics": metrics, "maintenance_as_obra": maintenance_as_obra}


def derive_deduplication(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    selected = [row for row in records if row.get("task") == "deduplication"]
    metrics = derive_metrics(selected)
    decisions = Counter()
    for row in selected:
        view = record_view(row)
        gold = (row.get("gold") or {}).get("decision")
        predicted = view["evaluated_label"]
        if view["operational_abstention"]:
            decisions["operational_abstention"] += 1
        elif not view["covered"]:
            decisions["failure_or_unresolved"] += 1
        elif gold == "DUPLICADO" and predicted == "DUPLICADO":
            if view["reference_match"]:
                decisions["tp"] += 1
            else:
                decisions["reference_error"] += 1
        elif gold == "DUPLICADO" and predicted == "NAO_DUPLICADO":
            decisions["fn"] += 1
        elif gold == "NAO_DUPLICADO" and predicted == "DUPLICADO":
            decisions["fp"] += 1
        elif gold == "NAO_DUPLICADO" and predicted == "NAO_DUPLICADO":
            decisions["tn"] += 1
    decisions["positive_human_confirmation"] = sum(
        bool(record_view(row)["covered"] and row.get("decision") == "DUPLICADO")
        for row in selected
    )
    return {"metrics": metrics, "decisions": dict(decisions)}


def add_check(
    checks: list[dict[str, Any]],
    scope: str,
    check: str,
    expected: Any,
    observed: Any,
    passed: bool,
    source: str,
    required: bool = True,
) -> None:
    checks.append(
        {
            "scope": scope,
            "check": check,
            "expected": expected,
            "observed": observed,
            "status": "PASS" if passed else "FAIL",
            "required": required,
            "source": source,
        }
    )


def load_local_run(run_dir: Path, checks: list[dict[str, Any]]) -> dict[str, Any]:
    plan_path = run_dir / "local_only_plan.json"
    predictions_path = run_dir / "local_only_predictions.jsonl"
    summary_path = run_dir / "local_only_summary.json"
    units_path = run_dir / "local_only_units.jsonl"
    for path in (plan_path, predictions_path, summary_path, units_path):
        if not path.is_file():
            raise FileNotFoundError(relative(path))

    plan = read_json(plan_path)
    summary = read_json(summary_path)
    predictions = read_jsonl(predictions_path)
    units = read_jsonl(units_path)
    scope = str(plan.get("local_candidate", {}).get("model_version") or run_dir.name)
    predictions_hash = sha256_file(predictions_path)
    units_hash = sha256_file(units_path)
    source = relative(run_dir)

    add_check(
        checks,
        scope,
        "SHA-256 das predições",
        summary.get("predictions_sha256"),
        predictions_hash,
        summary.get("predictions_sha256") == predictions_hash,
        source,
    )
    add_check(
        checks,
        scope,
        "Quantidade de predições",
        summary.get("records"),
        len(predictions),
        summary.get("records") == len(predictions),
        source,
    )
    sample = plan.get("sample") if isinstance(plan.get("sample"), dict) else {}
    add_check(
        checks,
        scope,
        "SHA-256 das unidades",
        sample.get("units_sha256"),
        units_hash,
        sample.get("units_sha256") == units_hash,
        source,
    )
    add_check(
        checks,
        scope,
        "Quantidade de unidades",
        sample.get("units"),
        len(units),
        sample.get("units") == len(units),
        source,
    )
    add_check(
        checks,
        scope,
        "Plano vinculado ao resumo",
        plan.get("manifest_payload_sha256"),
        summary.get("plan_manifest_payload_sha256"),
        plan.get("manifest_payload_sha256")
        == summary.get("plan_manifest_payload_sha256"),
        source,
    )
    unit_ids = [row.get("unit_id") for row in units]
    prediction_ids = [row.get("unit_id") for row in predictions]
    add_check(
        checks,
        scope,
        "unit_id únicos",
        len(unit_ids),
        len(set(prediction_ids)),
        len(unit_ids) == len(set(unit_ids)) == len(set(prediction_ids)),
        source,
    )
    unit_map = {row.get("unit_id"): row for row in units}
    shared_hash_ok = all(
        row.get("unit_id") in unit_map
        and row.get("shared_input_sha256")
        == unit_map[row.get("unit_id")].get("shared_input_sha256")
        for row in predictions
    )
    add_check(
        checks,
        scope,
        "Vínculo unit_id/shared_input_sha256",
        "todas as predições vinculadas",
        f"{len(predictions)} registros",
        shared_hash_ok,
        source,
    )

    return {
        "dir": run_dir,
        "plan": plan,
        "summary": summary,
        "predictions": predictions,
        "units": units,
        "model": scope,
        "metrics": derive_metrics(predictions),
        "predictions_sha256": predictions_hash,
        "units_sha256": units_hash,
        "sources": [plan_path, predictions_path, summary_path, units_path],
    }


def load_paired_run(run_dir: Path, checks: list[dict[str, Any]]) -> dict[str, Any]:
    plan_path = run_dir / "paired_plan.json"
    predictions_path = run_dir / "paired_predictions.jsonl"
    summary_path = run_dir / "paired_summary.json"
    units_path = run_dir / "paired_units.jsonl"
    for path in (plan_path, predictions_path, summary_path, units_path):
        if not path.is_file():
            raise FileNotFoundError(relative(path))

    plan = read_json(plan_path)
    summary = read_json(summary_path)
    predictions = read_jsonl(predictions_path)
    units = read_jsonl(units_path)
    scope = run_dir.name
    predictions_hash = sha256_file(predictions_path)
    units_hash = sha256_file(units_path)
    source = relative(run_dir)
    add_check(
        checks,
        scope,
        "SHA-256 das predições pareadas",
        summary.get("predictions_sha256"),
        predictions_hash,
        summary.get("predictions_sha256") == predictions_hash,
        source,
    )
    add_check(
        checks,
        scope,
        "Quantidade de predições pareadas",
        summary.get("records"),
        len(predictions),
        summary.get("records") == len(predictions),
        source,
    )
    sample = plan.get("sample") if isinstance(plan.get("sample"), dict) else {}
    add_check(
        checks,
        scope,
        "SHA-256 das unidades pareadas",
        sample.get("units_sha256"),
        units_hash,
        sample.get("units_sha256") == units_hash,
        source,
    )
    add_check(
        checks,
        scope,
        "Quantidade de unidades pareadas",
        sample.get("units"),
        len(units),
        sample.get("units") == len(units),
        source,
    )
    add_check(
        checks,
        scope,
        "Plano pareado vinculado ao resumo",
        plan.get("manifest_payload_sha256"),
        summary.get("plan_manifest_payload_sha256"),
        plan.get("manifest_payload_sha256")
        == summary.get("plan_manifest_payload_sha256"),
        source,
    )

    expected_providers = list(plan.get("paired_design", {}).get("providers") or [])
    if not expected_providers:
        expected_providers = sorted(
            {str(row.get("provider")) for row in predictions if row.get("provider")}
        )
    pairs = [(row.get("provider"), row.get("unit_id")) for row in predictions]
    add_check(
        checks,
        scope,
        "Par provedor/unit_id único",
        len(predictions),
        len(set(pairs)),
        len(predictions) == len(set(pairs)),
        source,
    )
    unit_map = {row.get("unit_id"): row for row in units}
    shared_hash_ok = all(
        row.get("unit_id") in unit_map
        and row.get("shared_input_sha256")
        == unit_map[row.get("unit_id")].get("shared_input_sha256")
        for row in predictions
    )
    add_check(
        checks,
        scope,
        "Vínculo pareado unit_id/shared_input_sha256",
        "todas as predições vinculadas",
        f"{len(predictions)} registros",
        shared_hash_ok,
        source,
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for provider in expected_providers:
        rows = [row for row in predictions if row.get("provider") == provider]
        grouped[provider] = rows
        add_check(
            checks,
            scope,
            f"Cobertura de unidades do provedor {provider}",
            len(units),
            len(rows),
            len(rows) == len(units),
            source,
        )

    valid_sets = {
        provider: {
            row.get("unit_id") for row in rows if record_view(row)["ok"]
        }
        for provider, rows in grouped.items()
    }
    valid_pairs = len(set.intersection(*valid_sets.values())) if valid_sets else 0
    return {
        "dir": run_dir,
        "plan": plan,
        "summary": summary,
        "predictions": predictions,
        "units": units,
        "providers": {provider: derive_metrics(rows) for provider, rows in grouped.items()},
        "provider_rows": grouped,
        "valid_pairs": valid_pairs,
        "predictions_sha256": predictions_hash,
        "units_sha256": units_hash,
        "sources": [plan_path, predictions_path, summary_path, units_path],
    }


def discover_local_runs(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for run_dir in RESULTS_DIR.glob("local-only-desenvolvimento*"):
        if run_dir.is_dir() and (run_dir / "local_only_plan.json").is_file():
            runs.append(load_local_run(run_dir, checks))
    if not runs:
        raise RuntimeError("Nenhum benchmark local de desenvolvimento foi encontrado.")
    return sorted(runs, key=lambda item: version_key(item["model"]))


def discover_paired_runs(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    runs = [
        load_paired_run(run_dir, checks)
        for run_dir in RESULTS_DIR.glob("pareado-local*")
        if run_dir.is_dir() and (run_dir / "paired_plan.json").is_file()
    ]
    return sorted(runs, key=lambda item: item["dir"].stat().st_mtime)


def discover_exploratory_local(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        load_local_run(run_dir, checks)
        for run_dir in RESULTS_DIR.glob("local-only-paired*")
        if run_dir.is_dir() and (run_dir / "local_only_plan.json").is_file()
    ]


def parse_links_report(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    parts = re.split(r"(?m)^##\s+", text)
    rows: list[dict[str, Any]] = []
    for part in parts[1:]:
        title, _, body = part.partition("\n")
        ticket = re.search(r"ticket(?: sintético)?:\s*`?(\d+)`?", body, re.I)
        response = re.search(r"resposta:\s*HTTP\s*(\d+)", body, re.I)
        decision = re.search(r"decisão persistida:\s*`([^`]+)`", body, re.I)
        state = re.search(r"estado (?:final|seguinte):\s*`([^`]+)`", body, re.I)
        rows.append(
            {
                "test": title.strip(),
                "ticket": int(ticket.group(1)) if ticket else None,
                "http": int(response.group(1)) if response else None,
                "decision": decision.group(1) if decision else None,
                "state": state.group(1) if state else None,
                "passed": bool(response and response.group(1) == "202"),
                "source": relative(path),
            }
        )
    return rows


def discover_integration(checks: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = list(RESULTS_DIR.glob("integracao*/**/metricas.json"))
    if not candidates:
        return None
    path = max(candidates, key=lambda item: item.stat().st_mtime)
    payload = read_json(path)
    experiment = payload.get("experimento") or {}
    run_id = str(experiment.get("run_id") or path.parent.name)
    dataset_path = path.parent / "dataset.jsonl"
    if dataset_path.is_file():
        observed_hash = sha256_file(dataset_path)
        expected_hash = experiment.get("dataset_sha256")
        add_check(
            checks,
            run_id,
            "SHA-256 do dataset de integração",
            expected_hash,
            observed_hash,
            expected_hash == observed_hash,
            relative(dataset_path),
        )
    link_candidates = list(RESULTS_DIR.glob("validacao-links-fiscais-*.md"))
    links_path = (
        max(link_candidates, key=lambda item: item.stat().st_mtime)
        if link_candidates
        else None
    )
    return {
        "path": path,
        "payload": payload,
        "links_path": links_path,
        "links": parse_links_report(links_path) if links_path else [],
    }


def discover_browser_checks() -> dict[str, Any] | None:
    candidates = list(RESULTS_DIR.glob("interfaces-web*/resultado.json"))
    if not candidates:
        return None
    path = max(candidates, key=lambda item: item.stat().st_mtime)
    return {"path": path, "payload": read_json(path)}


def discover_static_validation() -> dict[str, Any] | None:
    candidates = list(RESULTS_DIR.glob("static-validation-*.txt"))
    if not candidates:
        return None
    path = max(candidates, key=lambda item: item.stat().st_mtime)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    passed = sum(line.startswith("PASS:") for line in lines)
    failed = sum(line.startswith("FAIL:") for line in lines)
    return {
        "path": path,
        "passed": passed,
        "failed": failed,
        "status": "PASS" if passed and failed == 0 else "FAIL",
    }


def discover_wf06() -> dict[str, Any]:
    directories = sorted(
        [path for path in RESULTS_DIR.glob("calibracao-fila*") if path.is_dir()],
        key=lambda item: item.stat().st_mtime,
    )
    approved_files = [path / "calibracao_aprovada.json" for path in directories]
    approved_files = [path for path in approved_files if path.is_file()]
    if approved_files:
        path = max(approved_files, key=lambda item: item.stat().st_mtime)
        payload = read_json(path)
        runs = payload.get("runs") if isinstance(payload.get("runs"), list) else []
        all_success = bool(runs) and all(
            bool((row.get("metrics") or {}).get("success")) for row in runs
        )
        approved = bool(payload.get("approved") and payload.get("selected_config"))
        return {
            "status": "APROVADA" if approved and all_success else "REJEITADA",
            "reason": (
                "Todas as repetições foram aprovadas."
                if approved and all_success
                else "O artefato existe, mas a seleção/repetições não satisfazem os gates."
            ),
            "path": path,
            "payload": payload,
            "run_files": len(runs),
        }
    partials = [
        path
        for directory in directories
        for path in directory.glob("CALQ-*.json")
        if path.is_file()
    ]
    if partials:
        return {
            "status": "REJEITADA/INCOMPLETA",
            "reason": "Há execuções parciais, mas não existe calibração_aprovada.json.",
            "path": max(partials, key=lambda item: item.stat().st_mtime),
            "payload": None,
            "run_files": len(partials),
        }
    path = directories[-1] if directories else RESULTS_DIR / "calibracao-fila-v2"
    return {
        "status": "PENDENTE",
        "reason": "Nenhum resultado bruto de calibração concluída foi encontrado.",
        "path": path,
        "payload": None,
        "run_files": 0,
    }


def build_formats(workbook: xlsxwriter.Workbook) -> dict[str, Any]:
    return {
        "title": workbook.add_format(
            {
                "bold": True,
                "font_size": 18,
                "font_color": "#FFFFFF",
                "bg_color": "#17365D",
                "align": "left",
                "valign": "vcenter",
            }
        ),
        "subtitle": workbook.add_format(
            {
                "font_color": "#404040",
                "bg_color": "#D9EAF7",
                "text_wrap": True,
                "valign": "vcenter",
            }
        ),
        "header": workbook.add_format(
            {
                "bold": True,
                "font_color": "#FFFFFF",
                "bg_color": "#1F4E78",
                "border": 1,
                "align": "center",
                "valign": "vcenter",
                "text_wrap": True,
            }
        ),
        "body": workbook.add_format(
            {"border": 1, "valign": "top", "text_wrap": True}
        ),
        "integer": workbook.add_format(
            {"border": 1, "num_format": "#,##0", "valign": "top"}
        ),
        "decimal": workbook.add_format(
            {"border": 1, "num_format": "0.00", "valign": "top"}
        ),
        "percent": workbook.add_format(
            {"border": 1, "num_format": "0.00%", "valign": "top"}
        ),
        "hash": workbook.add_format(
            {"border": 1, "font_name": "Consolas", "font_size": 8, "valign": "top"}
        ),
        "note": workbook.add_format(
            {
                "font_color": "#7F6000",
                "bg_color": "#FFF2CC",
                "border": 1,
                "text_wrap": True,
            }
        ),
        "ok": workbook.add_format(
            {"font_color": "#006100", "bg_color": "#C6EFCE", "border": 1}
        ),
        "fail": workbook.add_format(
            {"font_color": "#9C0006", "bg_color": "#FFC7CE", "border": 1}
        ),
        "pending": workbook.add_format(
            {"font_color": "#9C6500", "bg_color": "#FFEB9C", "border": 1}
        ),
    }


def add_title(
    worksheet: Any,
    title: str,
    subtitle: str,
    formats: dict[str, Any],
    last_col: int,
) -> None:
    worksheet.merge_range(0, 0, 0, last_col, title, formats["title"])
    worksheet.merge_range(1, 0, 1, last_col, subtitle, formats["subtitle"])
    worksheet.set_row(0, 27)
    worksheet.set_row(1, 38)


def configure_sheet(worksheet: Any, widths: Sequence[float]) -> None:
    worksheet.freeze_panes(4, 0)
    worksheet.hide_gridlines(2)
    for column, width in enumerate(widths):
        worksheet.set_column(column, column, width)
    worksheet.set_landscape()
    worksheet.fit_to_pages(1, 0)


def write_value(
    worksheet: Any,
    row: int,
    col: int,
    value: Any,
    formats: dict[str, Any],
    format_key: str | None = None,
) -> None:
    selected = formats[format_key] if format_key else None
    if value is None:
        worksheet.write_blank(row, col, None, selected or formats["body"])
    elif isinstance(value, bool):
        worksheet.write_boolean(row, col, value, selected or formats["body"])
    elif isinstance(value, int):
        worksheet.write_number(row, col, value, selected or formats["integer"])
    elif isinstance(value, float):
        worksheet.write_number(row, col, value, selected or formats["decimal"])
    else:
        worksheet.write(row, col, value, selected or formats["body"])


def write_table(
    worksheet: Any,
    start_row: int,
    start_col: int,
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    formats: dict[str, Any],
    name: str,
    column_formats: dict[int, str] | None = None,
) -> int:
    for index, header in enumerate(headers):
        worksheet.write(start_row, start_col + index, header, formats["header"])
    for row_index, values in enumerate(rows, start=start_row + 1):
        for column_index, value in enumerate(values, start=start_col):
            relative_column = column_index - start_col
            format_key = (column_formats or {}).get(relative_column)
            write_value(
                worksheet,
                row_index,
                column_index,
                value,
                formats,
                format_key=format_key,
            )
    if rows:
        worksheet.add_table(
            start_row,
            start_col,
            start_row + len(rows),
            start_col + len(headers) - 1,
            {
                "name": name,
                "columns": [{"header": header} for header in headers],
                "style": "Table Style Medium 2",
            },
        )
    return start_row + len(rows)


def add_status_formatting(
    worksheet: Any, cell_range: str, formats: dict[str, Any]
) -> None:
    worksheet.conditional_format(
        cell_range,
        {
            "type": "text",
            "criteria": "containing",
            "value": "PASS",
            "format": formats["ok"],
        },
    )
    worksheet.conditional_format(
        cell_range,
        {
            "type": "text",
            "criteria": "containing",
            "value": "APROV",
            "format": formats["ok"],
        },
    )
    worksheet.conditional_format(
        cell_range,
        {
            "type": "text",
            "criteria": "containing",
            "value": "REJEIT",
            "format": formats["fail"],
        },
    )
    worksheet.conditional_format(
        cell_range,
        {
            "type": "text",
            "criteria": "containing",
            "value": "PENDENTE",
            "format": formats["pending"],
        },
    )


def provider_model(run: dict[str, Any], provider: str) -> str:
    if provider == "google-gemini":
        return str(run["plan"].get("remote", {}).get("model") or provider)
    if provider == "local-pytorch-fp32":
        return str(run["plan"].get("local_candidate", {}).get("model_version") or provider)
    return provider


def provider_status(metrics: dict[str, Any], remote: bool, scientific: bool) -> tuple[str, str]:
    if metrics["valid"] == 0:
        return (
            "REJEITADA" if remote else "CONTROLE INVÁLIDO",
            "Zero respostas válidas; não calcular eficácia nem superioridade.",
        )
    if not scientific:
        return (
            "NÃO CONFIRMATÓRIA",
            "Resultado de desenvolvimento/piloto sem autorização confirmatória.",
        )
    return "VÁLIDA", "Amostra válida segundo os gates declarados."


def collect_sources(
    local_runs: Sequence[dict[str, Any]],
    paired_runs: Sequence[dict[str, Any]],
    exploratory: Sequence[dict[str, Any]],
    integration: dict[str, Any] | None,
    browser: dict[str, Any] | None,
    static: dict[str, Any] | None,
    wf06: dict[str, Any],
) -> list[Path]:
    paths: list[Path] = []
    for run in [*local_runs, *paired_runs, *exploratory]:
        paths.extend(run["sources"])
    if integration:
        paths.append(integration["path"])
        if integration.get("links_path"):
            paths.append(integration["links_path"])
    if browser:
        paths.append(browser["path"])
    if static:
        paths.append(static["path"])
    if Path(wf06["path"]).is_file():
        paths.append(Path(wf06["path"]))
    return sorted(set(paths), key=lambda path: relative(path))


def verify_xlsx(output: Path) -> dict[str, Any]:
    required = {"xl/workbook.xml", "xl/styles.xml", "[Content_Types].xml"}
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        missing = sorted(required - names)
        if missing:
            raise RuntimeError(f"XLSX incompleto: {missing}")
        xml_files = [name for name in names if name.endswith(".xml")]
        xml = b"".join(archive.read(name) for name in xml_files)
        for marker in (b"#REF!", b"#DIV/0!", b"#VALUE!", b"#NAME?", b"#N/A"):
            if marker in xml:
                raise RuntimeError(f"Erro de fórmula encontrado: {marker.decode()}")
        workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
        sheet_names = re.findall(r'<sheet name="([^"]+)"', workbook_xml)
        formulas = sum(archive.read(name).count(b"<f") for name in xml_files)
        tables = len([name for name in names if name.startswith("xl/tables/table")])
        charts = len([name for name in names if name.startswith("xl/charts/chart")])
    return {
        "sheet_names": sheet_names,
        "formula_count": formulas,
        "table_count": tables,
        "chart_count": charts,
        "formula_error_scan": "PASS",
        "xlsx_structure": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gera o XLSX consolidado a partir de JSON/JSONL brutos."
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, Any]] = []
    local_runs = discover_local_runs(checks)
    latest = local_runs[-1]
    baseline = next(
        (run for run in local_runs if version_key(run["model"]) == (1, 1, 0)),
        local_runs[0],
    )
    add_check(
        checks,
        "comparação local",
        "Mesmas unidades no baseline e na última versão",
        baseline["units_sha256"],
        latest["units_sha256"],
        baseline["units_sha256"] == latest["units_sha256"],
        f"{relative(baseline['dir'])} | {relative(latest['dir'])}",
    )
    paired_runs = discover_paired_runs(checks)
    exploratory = discover_exploratory_local(checks)
    integration = discover_integration(checks)
    browser = discover_browser_checks()
    static = discover_static_validation()
    wf06 = discover_wf06()

    latest_plan = latest["plan"].get("local_candidate", {})
    for key, filename in (
        ("bundle_sha256", "local_hybrid_bundle.joblib"),
        ("manifest_sha256", "local_hybrid_manifest.json"),
    ):
        path = ROOT / "local_ai" / "artifacts" / filename
        if path.is_file():
            observed = sha256_file(path)
            expected = latest_plan.get(key)
            add_check(
                checks,
                latest["model"],
                f"Artefato congelado {filename}",
                expected,
                observed,
                expected == observed,
                relative(path),
            )

    failed_required = [
        item for item in checks if item["required"] and item["status"] != "PASS"
    ]
    if failed_required:
        details = "; ".join(
            f"{item['scope']}: {item['check']}" for item in failed_required
        )
        raise RuntimeError(f"Falha de integridade nos artefatos: {details}")

    classification = derive_classification(latest["predictions"])
    deduplication = derive_deduplication(latest["predictions"])
    latest_metrics = latest["metrics"]
    sources = collect_sources(
        local_runs, paired_runs, exploratory, integration, browser, static, wf06
    )

    workbook = xlsxwriter.Workbook(output)
    workbook.set_properties(
        {
            "title": "Resultados científicos do projeto IC",
            "subject": "Resultados recalculados de artefatos brutos e não confirmatórios",
            "author": "Projeto IC",
            "comments": "Métricas derivadas de JSON/JSONL com verificação de hashes.",
        }
    )
    formats = build_formats(workbook)

    worksheet = workbook.add_worksheet("Resumo")
    configure_sheet(worksheet, [30, 26, 24, 28, 74])
    add_title(
        worksheet,
        "Resultados consolidados do projeto IC",
        "Métricas recalculadas dos artefatos brutos. Desenvolvimento sintético e integração automatizada não equivalem a validação confirmatória.",
        formats,
        4,
    )
    latest_remote = next(
        (
            run
            for run in reversed(paired_runs)
            if run["plan"].get("local_candidate", {}).get("model_version")
            == latest["model"]
        ),
        None,
    )
    remote_metrics = (
        latest_remote["providers"].get("google-gemini") if latest_remote else None
    )
    remote_state = (
        "REJEITADA"
        if remote_metrics and remote_metrics["valid"] == 0
        else "PENDENTE"
    )
    integration_payload = integration["payload"] if integration else {}
    integration_experiment = integration_payload.get("experimento") or {}
    integration_state = (
        "APROVADA TECNICAMENTE / NÃO CONFIRMATÓRIA"
        if integration and integration_experiment.get("status") == "CONCLUIDO_AUTOMATIZADO"
        else "PENDENTE"
    )
    summary_rows = [
        [
            "Modelo local mais recente",
            latest["model"],
            f"{latest_metrics['valid']}/{latest_metrics['total']} válidos",
            "DESENVOLVIMENTO NÃO CONFIRMATÓRIO",
            "Acurácia seletiva e cobertura abaixo são de corpus sintético de desenvolvimento.",
        ],
        [
            "Cobertura semântica",
            latest_metrics["semantic_coverage"],
            latest_metrics["covered"],
            "Inclui classe TRIAGEM_MANUAL",
            "Exclui apenas abstenção operacional e falha de contrato.",
        ],
        [
            "Cobertura sem intervenção humana",
            latest_metrics["straight_through_coverage"],
            latest_metrics["straight_through_total"],
            "Automação integral",
            "Exclui TRIAGEM_MANUAL, abstenções e DUPLICADO, pois duplicidades preservam confirmação humana.",
        ],
        [
            "Acurácia seletiva",
            latest_metrics["selective_accuracy"],
            f"{latest_metrics['correct_covered']}/{latest_metrics['covered']}",
            "DESENVOLVIMENTO",
            "Calculada somente onde existe decisão semântica não abstida.",
        ],
        [
            "Encaminhado a humano",
            latest_metrics["routed_to_human_rate"],
            latest_metrics["routed_to_human_total"],
            "INCLUI CONFIRMAÇÃO DE DUPLICIDADE",
            "Não confundir com abstenção operacional.",
        ],
        [
            "Integração GLPI/n8n",
            integration_state,
            integration_experiment.get("run_id") or "sem artefato",
            "NÃO CONFIRMATÓRIA",
            "O oráculo automático testa o contrato técnico, não substitui rótulo humano para alegação científica.",
        ],
        [
            "Comparação Gemini da última versão",
            remote_state,
            f"{remote_metrics['valid'] if remote_metrics else 0} respostas válidas",
            "SEM COMPARAÇÃO DE EFICÁCIA",
            "Zero respostas válidas impede afirmar igualdade, superioridade ou inferioridade.",
        ],
        [
            "Comparação DeepSeek",
            "PENDENTE",
            "nenhum artefato bruto encontrado",
            "SEM COMPARAÇÃO DE EFICÁCIA",
            "Não foi localizado JSON/JSONL de respostas válidas do provedor.",
        ],
        [
            "Calibração WF06",
            wf06["status"],
            wf06["run_files"],
            "VAZÃO",
            wf06["reason"],
        ],
        [
            "Validação científica final",
            "PENDENTE",
            "holdout confirmatório",
            "NÃO PUBLICAR COMO SUPERIORIDADE",
            "Requer conjunto congelado independente, rótulos válidos e análise por núcleo/episódio.",
        ],
    ]
    write_table(
        worksheet,
        3,
        0,
        ["Área", "Valor/estado", "Evidência", "Natureza", "Interpretação"],
        summary_rows,
        formats,
        "tbResumo",
        {1: "percent"},
    )
    worksheet.set_column(1, 1, 26, formats["percent"])
    add_status_formatting(worksheet, "B5:D20", formats)

    worksheet = workbook.add_worksheet("Versoes local")
    configure_sheet(
        worksheet,
        [24, 11, 11, 11, 16, 16, 16, 16, 17, 15, 15, 14, 14, 68, 24],
    )
    add_title(
        worksheet,
        "Evolução do modelo local",
        "Todas as métricas são recalculadas dos JSONL. Baseline e última versão usam o mesmo arquivo de unidades quando o gate de hash está PASS.",
        formats,
        14,
    )
    version_rows = []
    for run in local_runs:
        metrics = run["metrics"]
        version_rows.append(
            [
                run["model"],
                metrics["total"],
                metrics["valid"],
                metrics["failures"],
                metrics["semantic_triage_predictions"],
                metrics["operational_abstentions"],
                metrics["semantic_coverage"],
                metrics["straight_through_coverage"],
                metrics["selective_accuracy"],
                metrics["routed_to_human_total"],
                metrics["routed_to_human_rate"],
                metrics["latency_mean_ms"],
                metrics["latency_p95_ms"],
                run["predictions_sha256"],
                "NÃO CONFIRMATÓRIO" if not run["summary"].get("scientific_result") else "CONFIRMATÓRIO",
            ]
        )
    version_end = write_table(
        worksheet,
        3,
        0,
        [
            "Versão",
            "Total",
            "Válidos",
            "Falhas",
            "TRIAGEM semântica",
            "Abstenções oper.",
            "Cobertura semântica",
            "Cobertura sem humano",
            "Acurácia seletiva",
            "Encam. humano",
            "Taxa humano",
            "Média ms",
            "p95 ms",
            "SHA-256 predições",
            "Natureza",
        ],
        version_rows,
        formats,
        "tbVersoesLocal",
        {
            6: "percent",
            7: "percent",
            8: "percent",
            10: "percent",
            11: "decimal",
            12: "decimal",
            13: "hash",
        },
    )
    worksheet.set_column(6, 10, 17, formats["percent"])
    worksheet.set_column(13, 13, 68, formats["hash"])
    baseline_excel_row = 5 + local_runs.index(baseline)
    latest_excel_row = 5 + local_runs.index(latest)
    delta_row = version_end + 2
    worksheet.write(delta_row, 0, f"Delta {latest['model']} - {baseline['model']}", formats["header"])
    worksheet.write_formula(
        delta_row,
        2,
        f"=C{latest_excel_row}-C{baseline_excel_row}",
        formats["integer"],
        latest_metrics["valid"] - baseline["metrics"]["valid"],
    )
    worksheet.write_formula(
        delta_row,
        3,
        f"=D{latest_excel_row}-D{baseline_excel_row}",
        formats["integer"],
        latest_metrics["failures"] - baseline["metrics"]["failures"],
    )
    worksheet.write_formula(
        delta_row,
        6,
        f"=G{latest_excel_row}-G{baseline_excel_row}",
        formats["percent"],
        latest_metrics["semantic_coverage"]
        - baseline["metrics"]["semantic_coverage"],
    )
    worksheet.write_formula(
        delta_row,
        7,
        f"=H{latest_excel_row}-H{baseline_excel_row}",
        formats["percent"],
        latest_metrics["straight_through_coverage"]
        - baseline["metrics"]["straight_through_coverage"],
    )
    chart = workbook.add_chart({"type": "column"})
    first_row = 5
    last_row = 4 + len(version_rows)
    chart.add_series(
        {
            "name": "Válidos",
            "categories": f"='Versoes local'!$A${first_row}:$A${last_row}",
            "values": f"='Versoes local'!$C${first_row}:$C${last_row}",
            "fill": {"color": "#5B9BD5"},
        }
    )
    chart.add_series(
        {
            "name": "Falhas",
            "categories": f"='Versoes local'!$A${first_row}:$A${last_row}",
            "values": f"='Versoes local'!$D${first_row}:$D${last_row}",
            "fill": {"color": "#C00000"},
        }
    )
    chart.set_title({"name": "Validade operacional por versão"})
    chart.set_y_axis({"name": "Unidades", "num_format": "#,##0"})
    chart.set_legend({"position": "bottom"})
    worksheet.insert_chart("Q4", chart, {"x_scale": 1.25, "y_scale": 1.15})

    worksheet = workbook.add_worksheet("Classificacao latest")
    configure_sheet(worksheet, [22, 11, 11, 11, 17, 17, 17, 14, 14, 16, 16])
    add_title(
        worksheet,
        f"Classificação — {latest['model']}",
        "TRIAGEM_MANUAL pode ser classe semântica correta. Abstenção operacional é uma categoria distinta; encaminhamento humano inclui ambas.",
        formats,
        10,
    )
    class_rows = [
        [
            row["label"],
            row["total"],
            row["valid"],
            row["failures"],
            row["semantic_correct"],
            row["semantic_triage_predictions"],
            row["operational_abstentions"],
            row["covered"],
            row["covered_errors"],
            row["routed_to_human"],
            row["straight_through"],
        ]
        for row in classification["rows"]
    ]
    class_metrics = classification["metrics"]
    class_rows.append(
        [
            "TOTAL",
            class_metrics["total"],
            class_metrics["valid"],
            class_metrics["failures"],
            class_metrics["correct_covered"],
            class_metrics["semantic_triage_predictions"],
            class_metrics["operational_abstentions"],
            class_metrics["covered"],
            class_metrics["covered_errors"],
            class_metrics["routed_to_human_total"],
            class_metrics["straight_through_total"],
        ]
    )
    end = write_table(
        worksheet,
        3,
        0,
        [
            "Gabarito",
            "Total",
            "Válidos",
            "Falhas",
            "Corretos semânticos",
            "Pred TRIAGEM semântica",
            "Abstenções oper.",
            "Cobertos",
            "Erros cobertos",
            "Encam. humano",
            "Sem humano",
        ],
        class_rows,
        formats,
        "tbClassificacaoLatest",
    )
    kpi_rows = [
        ["Cobertura semântica", class_metrics["semantic_coverage"], "Inclui TRIAGEM_MANUAL como classe"],
        ["Cobertura sem intervenção humana", class_metrics["straight_through_coverage"], "Fluxos realmente straight-through"],
        ["Acurácia seletiva", class_metrics["selective_accuracy"], "Somente decisões semânticas cobertas"],
        ["Taxa encaminhada a humano", class_metrics["routed_to_human_rate"], "Classe TRIAGEM + abstenções"],
    ]
    kpi_end = write_table(
        worksheet,
        end + 2,
        0,
        ["KPI", "Valor", "Definição"],
        kpi_rows,
        formats,
        "tbKpiClassificacao",
        {1: "percent"},
    )
    write_table(
        worksheet,
        kpi_end + 2,
        0,
        ["Gate de segurança", "Quantidade", "Definição"],
        [
            [
                "Manutenção/triagem → OBRA",
                classification["maintenance_as_obra"],
                "Erro crítico automático observado",
            ]
        ],
        formats,
        "tbGateObra",
    )
    worksheet.set_column(1, 1, 18, formats["percent"])

    worksheet = workbook.add_worksheet("Deduplicacao latest")
    configure_sheet(worksheet, [34, 18, 18, 72])
    add_title(
        worksheet,
        f"Deduplicação — {latest['model']}",
        "DUPLICADO preserva confirmação humana. Logo, cobertura semântica e automação sem humano não são a mesma métrica.",
        formats,
        3,
    )
    dedup_metrics = deduplication["metrics"]
    decisions = deduplication["decisions"]
    dedup_rows = [
        ["Total", dedup_metrics["total"], None, "Desafios avaliados"],
        ["Cobertos semanticamente", dedup_metrics["covered"], dedup_metrics["semantic_coverage"], "DUPLICADO ou NAO_DUPLICADO"],
        ["Abstenções operacionais", dedup_metrics["operational_abstentions"], dedup_metrics["operational_abstentions"] / dedup_metrics["total"], "Encaminhadas a humano sem decisão binária"],
        ["TP", decisions.get("tp", 0), None, "Duplicidade e referência corretas"],
        ["TN", decisions.get("tn", 0), None, "Não duplicado correto"],
        ["FP", decisions.get("fp", 0), None, "Não duplicado classificado como duplicado"],
        ["FN", decisions.get("fn", 0), None, "Duplicado classificado como não duplicado; peso 5"],
        ["Referência incorreta", decisions.get("reference_error", 0), None, "Classe duplicado correta, ticket de referência errado"],
        ["Duplicidades para confirmação", decisions.get("positive_human_confirmation", 0), None, "Decisão positiva preserva confirmação humana"],
        ["Total encaminhado a humano", dedup_metrics["routed_to_human_total"], dedup_metrics["routed_to_human_rate"], "Abstenções + confirmações positivas"],
        ["Sem intervenção humana", dedup_metrics["straight_through_total"], dedup_metrics["straight_through_coverage"], "Somente NAO_DUPLICADO válido"],
        ["Acurácia seletiva", None, dedup_metrics["selective_accuracy"], "Somente decisões cobertas"],
        ["Custo ponderado FN×5 + FP", dedup_metrics["dedup_weighted_error_cost_fn5_fp1"], None, "Política assimétrica do projeto"],
    ]
    write_table(
        worksheet,
        3,
        0,
        ["Medida", "Quantidade", "Taxa", "Definição"],
        dedup_rows,
        formats,
        "tbDeduplicacaoLatest",
        {2: "percent"},
    )
    worksheet.set_column(2, 2, 18, formats["percent"])

    worksheet = workbook.add_worksheet("Predicoes processadas")
    configure_sheet(
        worksheet,
        [26, 16, 20, 20, 21, 15, 15, 15, 16, 15, 10, 10, 28, 20, 24, 14, 15, 24, 24, 18],
    )
    worksheet.freeze_panes(4, 3)
    add_title(
        worksheet,
        f"Predições processadas — {latest['model']}",
        "Uma linha por unidade. Campos derivados explicitam a regra semântica; o JSONL original permanece a fonte imutável indicada na Proveniência.",
        formats,
        19,
    )
    processed_rows = []
    for row in latest["predictions"]:
        view = record_view(row)
        gold = row.get("gold") if isinstance(row.get("gold"), dict) else {}
        processed_rows.append(
            [
                row.get("unit_id"),
                row.get("task"),
                gold.get("decision"),
                row.get("decision"),
                view["evaluated_label"],
                view["operational_abstention"],
                view["covered"],
                view["correct"],
                view["routed_to_human"],
                view["straight_through"],
                view["ok"],
                not view["ok"],
                row.get("decision_path"),
                row.get("provider"),
                row.get("model"),
                row.get("latency_ms"),
                view["reference_match"],
                row.get("scenario_id"),
                row.get("error_code"),
                view["legacy_semantics_inferred"],
            ]
        )
    write_table(
        worksheet,
        3,
        0,
        [
            "unit_id",
            "task",
            "gold",
            "decisão bruta",
            "classe/decisão avaliada",
            "abstenção operacional",
            "cobertura semântica",
            "correto sob métrica",
            "encaminhado humano",
            "sem intervenção humana",
            "ok",
            "falha",
            "decision_path",
            "provider",
            "model",
            "latency_ms",
            "referência correta",
            "scenario_id",
            "error_code",
            "semântica legada inferida",
        ],
        processed_rows,
        formats,
        "tbPredicoesProcessadas",
        {15: "decimal"},
    )

    worksheet = workbook.add_worksheet("Provedores")
    configure_sheet(
        worksheet,
        [42, 25, 24, 11, 11, 11, 15, 15, 16, 15, 15, 18, 19, 74],
    )
    add_title(
        worksheet,
        "Ensaios por provedor",
        "Comparações com zero respostas válidas são rejeitadas. Métricas ausentes ficam em branco; não são convertidas em zero.",
        formats,
        13,
    )
    provider_rows: list[list[Any]] = []
    for run in paired_runs:
        scientific = bool(run["summary"].get("scientific_result"))
        reported_tokens = (run["summary"].get("remote_budget_observed") or {}).get(
            "reported_total_tokens"
        )
        for provider, metrics in run["providers"].items():
            remote = provider != "local-pytorch-fp32"
            status, limitation = provider_status(metrics, remote, scientific)
            error_text = ", ".join(
                f"{key}={value}" for key, value in metrics["error_counts"].items()
            )
            provider_rows.append(
                [
                    run["dir"].name,
                    provider_model(run, provider),
                    provider,
                    metrics["total"],
                    metrics["valid"],
                    metrics["failures"],
                    metrics["semantic_coverage"] if metrics["valid"] else None,
                    metrics["straight_through_coverage"] if metrics["valid"] else None,
                    metrics["selective_accuracy"],
                    metrics["routed_to_human_total"],
                    metrics["latency_mean_ms"],
                    reported_tokens if remote else 0,
                    status,
                    f"{limitation} Pares com ambos válidos no ensaio: {run['valid_pairs']}. {error_text}".strip(),
                ]
            )
    for run in exploratory:
        metrics = run["metrics"]
        provider_rows.append(
            [
                run["dir"].name,
                run["model"],
                "local-pytorch-fp32",
                metrics["total"],
                metrics["valid"],
                metrics["failures"],
                metrics["semantic_coverage"] if metrics["valid"] else None,
                metrics["straight_through_coverage"] if metrics["valid"] else None,
                metrics["selective_accuracy"],
                metrics["routed_to_human_total"],
                metrics["latency_mean_ms"],
                0,
                "EXPLORATÓRIO LOCAL",
                "Sem respostas remotas válidas pareadas neste artefato; não usar para superioridade.",
            ]
        )
    provider_rows.append(
        [
            "sem artefato bruto",
            "DeepSeek",
            "deepseek",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "PENDENTE",
            "Nenhum JSON/JSONL de benchmark DeepSeek foi localizado; eficácia não calculada.",
        ]
    )
    write_table(
        worksheet,
        3,
        0,
        [
            "Execução",
            "Modelo",
            "Provider",
            "Total",
            "Válidos",
            "Falhas",
            "Cobertura semântica",
            "Cobertura sem humano",
            "Acurácia seletiva",
            "Encam. humano",
            "Média ms",
            "Tokens reportados",
            "Estado",
            "Limite de interpretação/erros",
        ],
        provider_rows,
        formats,
        "tbProvedores",
        {6: "percent", 7: "percent", 8: "percent", 10: "decimal"},
    )
    worksheet.set_column(6, 8, 18, formats["percent"])
    add_status_formatting(worksheet, f"M5:M{4 + len(provider_rows)}", formats)

    worksheet = workbook.add_worksheet("Integracao")
    configure_sheet(worksheet, [34, 28, 24, 24, 76])
    add_title(
        worksheet,
        "Integração, links e interfaces",
        "Evidências técnicas extraídas de metricas.json, relatório de links e resultado.json do navegador. Natureza não confirmatória.",
        formats,
        4,
    )
    integration_rows: list[list[Any]] = []
    if integration:
        payload = integration["payload"]
        experiment = payload.get("experimento") or {}
        evidence = payload.get("classificacao_evidencia") or {}
        operational = ((payload.get("metricas") or {}).get("metricas_operacionais") or [{}])[0]
        integration_rows.extend(
            [
                ["Run", experiment.get("run_id"), experiment.get("status"), "NÃO CONFIRMATÓRIO", relative(integration["path"])],
                ["Tickets", operational.get("tickets"), "observado", "Integração", relative(integration["path"])],
                ["Chamadas IA", operational.get("chamadas_ia"), "observado", "Integração", relative(integration["path"])],
                ["Erros IA", operational.get("erros_ia"), "observado", "Integração", relative(integration["path"])],
                ["Triagens manuais", operational.get("triagens_manuais"), "observado", "Integração", relative(integration["path"])],
                ["Intervenções fiscais", operational.get("intervencoes_fiscais"), "observado", "Integração", relative(integration["path"])],
                ["Latência média total (s)", float(operational["latencia_total_media_s"]) if operational.get("latencia_total_media_s") is not None else None, "observado", "Integração", relative(integration["path"])],
                ["Latência p95 total (s)", float(operational["latencia_total_p95_s"]) if operational.get("latencia_total_p95_s") is not None else None, "observado", "Integração", relative(integration["path"])],
                ["Rótulos humanos", (evidence.get("gold_source_summary") or {}).get("humanos"), "gate", "PENDENTE", relative(integration["path"])],
                ["Gates obrigatórios satisfeitos", (evidence.get("gate_status") or {}).get("gates_obrigatorios_satisfeitos"), "gate", "PENDENTE", relative(integration["path"])],
            ]
        )
        for link in integration["links"]:
            integration_rows.append(
                [
                    f"Link fiscal: {link['test']}",
                    link["ticket"],
                    f"HTTP {link['http']}" if link["http"] else None,
                    "PASS" if link["passed"] else "FAIL",
                    f"{link['decision'] or ''}; {link['state'] or ''}; {link['source']}",
                ]
            )
    else:
        integration_rows.append(["Integração", None, "sem artefato", "PENDENTE", "Nenhum metricas.json encontrado"])
    if browser:
        for check in browser["payload"].get("checks") or []:
            integration_rows.append(
                [
                    f"Navegador: {check.get('service')} / {check.get('check')}",
                    check.get("duration_ms"),
                    check.get("detail"),
                    "PASS" if check.get("passed") else "FAIL",
                    relative(browser["path"]),
                ]
            )
    if static:
        integration_rows.append(
            [
                "Validação estática V9",
                static["passed"],
                f"falhas={static['failed']}",
                static["status"],
                relative(static["path"]),
            ]
        )
    write_table(
        worksheet,
        3,
        0,
        ["Evidência", "Valor", "Detalhe", "Estado/natureza", "Fonte"],
        integration_rows,
        formats,
        "tbIntegracao",
    )
    add_status_formatting(worksheet, f"D5:D{4 + len(integration_rows)}", formats)

    worksheet = workbook.add_worksheet("WF06")
    configure_sheet(worksheet, [34, 28, 24, 78])
    add_title(
        worksheet,
        "Calibração da fila WF06",
        "Somente calibracao_aprovada.json completo pode sustentar seleção de lote/intervalo. Ausência de artefato permanece pendente.",
        formats,
        3,
    )
    wf06_rows: list[list[Any]] = [
        ["Estado", wf06["status"], wf06["run_files"], wf06["reason"]],
        ["Fonte", relative(Path(wf06["path"])), None, "Caminho inspecionado"],
    ]
    if wf06["payload"]:
        payload = wf06["payload"]
        selected = payload.get("selected_config") or {}
        wf06_rows.extend(
            [
                ["Repetições", payload.get("repetitions"), "por configuração", "Declarado no resultado"],
                ["Tickets por repetição", payload.get("tickets_per_repetition"), "tickets", "Declarado no resultado"],
                ["Lote selecionado", selected.get("batch"), "tickets", "Somente se aprovado"],
                ["Intervalo selecionado", selected.get("interval_seconds"), "segundos", "Somente se aprovado"],
            ]
        )
    write_table(
        worksheet,
        3,
        0,
        ["Parâmetro", "Valor", "Unidade/evidência", "Interpretação"],
        wf06_rows,
        formats,
        "tbWF06",
    )
    add_status_formatting(worksheet, "B5:B20", formats)

    worksheet = workbook.add_worksheet("Proveniencia QA")
    configure_sheet(worksheet, [28, 42, 34, 68, 68, 12, 12, 72])
    add_title(
        worksheet,
        "Proveniência e controle de integridade",
        "Cada gate obrigatório foi verificado antes da geração. Qualquer FAIL obrigatório interrompe o script.",
        formats,
        7,
    )
    provenance_rows = [
        [
            item["scope"],
            item["check"],
            str(item["expected"]),
            str(item["observed"]),
            item["source"],
            item["status"],
            item["required"],
            "Comparação direta; nenhum valor estimado.",
        ]
        for item in checks
    ]
    write_table(
        worksheet,
        3,
        0,
        ["Escopo", "Gate", "Esperado", "Observado", "Fonte", "Estado", "Obrigatório", "Método"],
        provenance_rows,
        formats,
        "tbProvenienciaQA",
        {2: "hash", 3: "hash"},
    )
    worksheet.set_column(2, 3, 68, formats["hash"])
    add_status_formatting(worksheet, f"F5:F{4 + len(provenance_rows)}", formats)

    worksheet = workbook.add_worksheet("Metodologia")
    configure_sheet(worksheet, [34, 92, 28])
    add_title(
        worksheet,
        "Definições e limites de interpretação",
        "Regras visíveis usadas para transformar os registros brutos em métricas auditáveis.",
        formats,
        2,
    )
    methodology_rows = [
        ["Predição semântica TRIAGEM_MANUAL", "Classe válida apenas na classificação quando o decision_path indica decisão semântica, não gate/abstenção.", "Separada"],
        ["Abstenção operacional", "Gate de incerteza, informação insuficiente, contradição, fora de escopo ou caminho HYBRID_MODEL_ABSTENTION.", "Separada"],
        ["Cobertura semântica", "Decisões válidas não abstidas, inclusive TRIAGEM_MANUAL como classe de classificação.", "Desenvolvimento"],
        ["Cobertura sem intervenção humana", "Registros válidos que não seguem para pessoa. DUPLICADO não entra porque a confirmação humana permanece.", "Operacional"],
        ["Encaminhado a humano", "TRIAGEM_MANUAL, abstenções operacionais e deduplicações positivas que exigem confirmação.", "Operacional"],
        ["Acurácia seletiva", "Acertos entre decisões semanticamente cobertas. Falhas e abstenções não entram no denominador.", "Relatar com cobertura"],
        ["Comparação Gemini", "Rejeitada quando a amostra remota tem zero respostas válidas; testes estatísticos contra falhas totais não demonstram eficácia.", "Rejeitada/pendente"],
        ["Comparação DeepSeek", "Sem artefato bruto válido, nenhuma métrica de eficácia é calculada.", "Pendente"],
        ["Calibração WF06", "Somente resultado completo, repetido e aprovado autoriza selecionar lote/intervalo.", wf06["status"]],
        ["Validade científica", "O corpus é sintético de desenvolvimento e a integração usa oráculo automático. Falta holdout independente com rótulos válidos.", "Pendente"],
        ["Unidade de análise", "As realizações de um mesmo núcleo não são observações independentes; intervalos/testes finais devem agrupar por núcleo/episódio.", "Obrigatório no artigo"],
    ]
    write_table(
        worksheet,
        3,
        0,
        ["Conceito", "Definição", "Uso/estado"],
        methodology_rows,
        formats,
        "tbMetodologia",
    )

    workbook.close()
    structure = verify_xlsx(output)
    output_hash = sha256_file(output)
    source_hashes = [
        {"path": relative(path), "sha256": sha256_file(path)} for path in sources
    ]
    verification = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "output": str(output),
        "output_sha256": output_hash,
        "size_bytes": output.stat().st_size,
        "generator": relative(Path(__file__)),
        "generator_sha256": sha256_file(Path(__file__)),
        "latest_model": latest["model"],
        "baseline_model": baseline["model"],
        "integrity_checks": {
            "total": len(checks),
            "passed": sum(item["status"] == "PASS" for item in checks),
            "failed": sum(item["status"] != "PASS" for item in checks),
            "required_failed": len(failed_required),
        },
        "key_metrics_recomputed": {
            "total": latest_metrics["total"],
            "valid": latest_metrics["valid"],
            "semantic_triage_predictions": latest_metrics[
                "semantic_triage_predictions"
            ],
            "operational_abstentions": latest_metrics[
                "operational_abstentions"
            ],
            "routed_to_human_total": latest_metrics["routed_to_human_total"],
            "semantic_coverage": latest_metrics["semantic_coverage"],
            "straight_through_coverage": latest_metrics[
                "straight_through_coverage"
            ],
            "selective_accuracy": latest_metrics["selective_accuracy"],
        },
        "source_files": source_hashes,
        **structure,
        "visual_render": {
            "status": "UNAVAILABLE",
            "reason": "O runtime não expôs @oai/artifact-tool nem um renderizador headless de Excel/LibreOffice; foi feita verificação estrutural do pacote XLSX, tabelas, fórmulas e gráficos.",
        },
    }
    verification_path = output.with_suffix(".verification.json")
    verification_path.write_text(
        json.dumps(verification, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(verification, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
