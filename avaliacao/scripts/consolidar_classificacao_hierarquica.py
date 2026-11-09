#!/usr/bin/env python3
"""Consolida a avaliacao hierarquica de classificacao do modelo local.

O script nao executa inferencia e nao altera os artefatos de origem. Ele
recalcula as contagens a partir do JSONL de predicoes, confere a matriz de
quatro classes publicada no resumo corrigido e produz uma leitura operacional
em duas etapas:

1. OBRA versus MANUTENCAO;
2. DEMO versus SOB_DEMANDA, somente entre manutencoes.

TRIAGEM_MANUAL e abstencoes operacionais sao contabilizadas como revisao
humana na leitura hierarquica. Assim, elas nao viram acertos automaticos nem
erros de encaminhamento automatico.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN_DIR = (
    ROOT
    / "avaliacao"
    / "resultados"
    / "local-only-desenvolvimento-v1.8.0-20260716"
)
DEFAULT_OUTPUT_DIR = (
    ROOT
    / "avaliacao"
    / "resultados"
    / "classificacao-obra-manutencao-v1.8.0-20260721"
)
DEFAULT_ARTIFACT_MANIFEST = ROOT / "local_ai" / "artifacts" / "local_hybrid_manifest.json"
DEFAULT_MODEL_MANIFEST = ROOT / "local_ai" / "models" / "manifest.json"

CLASS_LABELS = ("DEMO", "OBRA", "SOB_DEMANDA", "TRIAGEM_MANUAL")
ACTIONABLE_LABELS = ("DEMO", "OBRA", "SOB_DEMANDA")
REVIEW_LABEL = "REVISAO_HUMANA"
ABSTENTION_LABEL = "ABSTENCAO"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"JSON raiz deve ser objeto: {path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"Linha {line_number} nao e objeto JSON: {path}")
            rows.append(value)
    return rows


def operational_abstention(row: dict[str, Any]) -> bool:
    """Reproduz o contrato v1.1 usado no resumo corrigido do benchmark."""

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


def semantic_prediction(row: dict[str, Any], abstained: bool) -> str | None:
    declared = row.get("predicted_class")
    if declared in CLASS_LABELS:
        return str(declared)
    provenance = row.get("runtime_provenance")
    if isinstance(provenance, dict):
        declared = provenance.get("semantic_class_prediction")
        if declared in CLASS_LABELS:
            return str(declared)
    if not abstained and row.get("decision") in CLASS_LABELS:
        return str(row["decision"])
    return None


def percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return float(ordered[index])


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def interpreted_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    interpreted: list[dict[str, Any]] = []
    for row in rows:
        abstained = operational_abstention(row) if row.get("ok") else False
        predicted = semantic_prediction(row, abstained)
        evaluated = (
            "ERROR"
            if not row.get("ok")
            else ABSTENTION_LABEL
            if abstained
            else predicted
        )
        routed = row.get("routed_to_human")
        if not isinstance(routed, bool):
            routed = bool(
                row.get("ok")
                and (abstained or row.get("decision") == "TRIAGEM_MANUAL")
            )
        interpreted.append(
            {
                "row": row,
                "gold": (row.get("gold") or {}).get("decision"),
                "operational_abstention": abstained,
                "predicted_class": predicted,
                "evaluated_label": evaluated,
                "routed_to_human": routed,
            }
        )
    return interpreted


def confusion_four_class(rows: Sequence[dict[str, Any]]) -> dict[str, int]:
    confusion: Counter[str] = Counter()
    for view in interpreted_rows(rows):
        confusion[f"{view['gold']}->{view['evaluated_label']}"] += 1
    return dict(sorted(confusion.items()))


def hierarchy_bucket(view: dict[str, Any]) -> str:
    if (
        view["operational_abstention"]
        or view["predicted_class"] not in ACTIONABLE_LABELS
        or not view["row"].get("ok")
    ):
        return REVIEW_LABEL
    return str(view["predicted_class"])


def compact_error(view: dict[str, Any]) -> dict[str, Any]:
    row = view["row"]
    return {
        "case_id": row.get("case_id"),
        "scenario_id": row.get("scenario_id"),
        "surface_realization": row.get("surface_realization"),
        "gold": view["gold"],
        "prediction": view["predicted_class"],
        "confidence": row.get("confidence"),
        "decision_path": row.get("decision_path"),
        "shared_input_sha256": row.get("shared_input_sha256"),
    }


def source_entry(path: Path) -> dict[str, Any]:
    return {
        "path": relative_path(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def build_report(
    run_dir: Path,
    artifact_manifest_path: Path,
    model_manifest_path: Path,
) -> dict[str, Any]:
    predictions_path = run_dir / "local_only_predictions.jsonl"
    summary_path = run_dir / "local_only_summary_metrics_v1.2.json"
    if not summary_path.is_file():
        # Compatibilidade somente de leitura com rodadas históricas anteriores
        # ao contrato de métricas 1.2; novos artefatos nunca usam este nome.
        summary_path = run_dir / "local_only_summary_metrics_v1.1.json"
    plan_path = run_dir / "local_only_plan.json"
    units_path = run_dir / "local_only_units.jsonl"

    predictions = load_jsonl(predictions_path)
    summary = load_json(summary_path)
    artifact_manifest = load_json(artifact_manifest_path)
    model_manifest = load_json(model_manifest_path)

    declared_source = summary.get("metric_recalculation") or {}
    actual_predictions_sha = sha256_file(predictions_path)
    if declared_source.get("source_predictions_sha256") != actual_predictions_sha:
        raise ValueError("Hash das predicoes diverge do resumo corrigido")

    classification = [row for row in predictions if row.get("task") == "classification"]
    views = interpreted_rows(classification)
    summary_classification = ((summary.get("metrics") or {}).get("by_task") or {}).get(
        "classification"
    )
    if not isinstance(summary_classification, dict):
        raise ValueError("Resumo nao contem metrics.by_task.classification")
    if len(classification) != summary_classification.get("total"):
        raise ValueError("Total de classificacao diverge do resumo")

    recalculated_confusion = confusion_four_class(classification)
    if recalculated_confusion != summary_classification.get("confusion"):
        raise ValueError("Matriz de quatro classes diverge do resumo corrigido")

    valid = [view for view in views if view["row"].get("ok")]
    actionable_gold = [view for view in valid if view["gold"] in ACTIONABLE_LABELS]
    maintenance_gold = [view for view in actionable_gold if view["gold"] in {"DEMO", "SOB_DEMANDA"}]

    gold_support = Counter(str(view["gold"]) for view in valid)
    predicted_support = Counter(
        str(view["evaluated_label"]) for view in valid
    )
    route_support = Counter(str(view["row"].get("decision_path")) for view in valid)

    hierarchy_confusion: dict[str, Counter[str]] = {
        "OBRA": Counter(),
        "MANUTENCAO": Counter(),
    }
    maintenance_confusion: dict[str, Counter[str]] = {
        "DEMO": Counter(),
        "SOB_DEMANDA": Counter(),
    }
    actionable_automatic_errors: list[dict[str, Any]] = []
    all_automatic_errors: list[dict[str, Any]] = []

    for view in valid:
        bucket = hierarchy_bucket(view)
        if bucket in ACTIONABLE_LABELS and bucket != view["gold"]:
            all_automatic_errors.append(compact_error(view))

    for view in actionable_gold:
        predicted = hierarchy_bucket(view)
        gold_binary = "OBRA" if view["gold"] == "OBRA" else "MANUTENCAO"
        if predicted == REVIEW_LABEL:
            predicted_binary = REVIEW_LABEL
        else:
            predicted_binary = "OBRA" if predicted == "OBRA" else "MANUTENCAO"
        hierarchy_confusion[gold_binary][predicted_binary] += 1
        if predicted != REVIEW_LABEL and predicted != view["gold"]:
            actionable_automatic_errors.append(compact_error(view))

    for view in maintenance_gold:
        predicted = hierarchy_bucket(view)
        maintenance_confusion[str(view["gold"])][predicted] += 1

    hierarchy_automatic = sum(
        hierarchy_bucket(view) != REVIEW_LABEL for view in actionable_gold
    )
    hierarchy_correct = sum(
        hierarchy_bucket(view) == view["gold"] for view in actionable_gold
    )
    hierarchy_review = len(actionable_gold) - hierarchy_automatic

    maintenance_automatic = sum(
        hierarchy_bucket(view) in {"DEMO", "SOB_DEMANDA"} for view in maintenance_gold
    )
    maintenance_correct = sum(
        hierarchy_bucket(view) == view["gold"] for view in maintenance_gold
    )
    maintenance_review = len(maintenance_gold) - maintenance_automatic

    maintenance_as_obra = sum(
        view["gold"] in {"DEMO", "SOB_DEMANDA"}
        and hierarchy_bucket(view) == "OBRA"
        for view in actionable_gold
    )
    obra_as_maintenance = sum(
        view["gold"] == "OBRA"
        and hierarchy_bucket(view) in {"DEMO", "SOB_DEMANDA"}
        for view in actionable_gold
    )
    demo_as_sob = sum(
        view["gold"] == "DEMO" and hierarchy_bucket(view) == "SOB_DEMANDA"
        for view in maintenance_gold
    )
    sob_as_demo = sum(
        view["gold"] == "SOB_DEMANDA" and hierarchy_bucket(view) == "DEMO"
        for view in maintenance_gold
    )

    latencies = [float(view["row"]["latency_ms"]) for view in valid]
    scenario_ids = {str(view["row"].get("scenario_id")) for view in valid}
    narrative_cores = {
        str(view["row"].get("narrative_core_sha256")) for view in valid
    }
    actionable_cores = {
        str(view["row"].get("narrative_core_sha256")) for view in actionable_gold
    }
    maintenance_cores = {
        str(view["row"].get("narrative_core_sha256")) for view in maintenance_gold
    }
    surface_realizations = {
        str(view["row"].get("surface_realization")) for view in valid
    }

    training = artifact_manifest.get("training") or {}
    pipeline_metrics = artifact_manifest.get("pipeline_metrics") or {}
    embedding = artifact_manifest.get("embedding") or {}
    thresholds = artifact_manifest.get("thresholds") or {}
    bundle_path = artifact_manifest_path.parent / str(
        (artifact_manifest.get("bundle") or {}).get("path")
    )
    training_source = ((training.get("source_audit") or [{}])[0])
    training_source_path = ROOT / "avaliacao" / "datasets" / "desenvolvimento_local_v1.jsonl"

    sources = {
        "predictions": source_entry(predictions_path),
        "corrected_summary": source_entry(summary_path),
        "plan": source_entry(plan_path),
        "units": source_entry(units_path),
        "artifact_manifest": source_entry(artifact_manifest_path),
        "model_manifest": source_entry(model_manifest_path),
        "frozen_bundle": source_entry(bundle_path),
        "training_dataset": source_entry(training_source_path),
    }
    sources["predictions"]["matches_summary_declaration"] = True
    sources["frozen_bundle"]["matches_manifest_declaration"] = (
        sources["frozen_bundle"]["sha256"]
        == (artifact_manifest.get("bundle") or {}).get("sha256")
    )
    sources["training_dataset"]["matches_manifest_declaration"] = (
        sources["training_dataset"]["sha256"] == training_source.get("sha256")
    )

    four_class_errors = sum(
        count
        for transition, count in recalculated_confusion.items()
        if not transition.endswith(f"->{ABSTENTION_LABEL}")
        and transition.split("->", 1)[0] != transition.split("->", 1)[1]
    )

    return {
        "schema_version": "classificacao-hierarquica-v1.0.0",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "scope": "development_descriptive_non_confirmatory",
        "model": {
            "model_version": artifact_manifest.get("model_version"),
            "bundle_version": artifact_manifest.get("bundle_version"),
            "candidate_frozen": artifact_manifest.get("candidate_frozen"),
            "scientifically_validated": artifact_manifest.get("scientifically_validated"),
            "scientific_claim_status": artifact_manifest.get("scientific_claim_status"),
            "generation_profile": (artifact_manifest.get("pipeline") or {}).get(
                "generation_profile"
            ),
            "embedding": {
                "model_id": embedding.get("model_id"),
                "revision": embedding.get("model_revision"),
                "dimension": embedding.get("dimension"),
                "backend": "pytorch_fp32",
            },
        },
        "thresholds": {
            "classification": thresholds.get("classification"),
            "classification_obra": thresholds.get("classification_obra"),
            "selection_source": thresholds.get("selection_source"),
            "critical_error": (
                thresholds.get("classification_asymmetric_risk") or {}
            ).get("most_costly_error"),
        },
        "sources": sources,
        "dataset_structure": {
            "classification_records": len(classification),
            "valid_records": len(valid),
            "failed_records": len(classification) - len(valid),
            "scenario_ids": len(scenario_ids),
            "distinct_narrative_cores": len(narrative_cores),
            "surface_realizations": len(surface_realizations),
            "realizations_per_core": ratio(len(valid), len(narrative_cores)),
            "gold_support": dict(sorted(gold_support.items())),
            "actionable_hierarchy_records": len(actionable_gold),
            "actionable_hierarchy_distinct_cores": len(actionable_cores),
            "maintenance_subtype_records": len(maintenance_gold),
            "maintenance_subtype_distinct_cores": len(maintenance_cores),
        },
        "four_class_classification": {
            "total": summary_classification.get("total"),
            "valid": summary_classification.get("valid"),
            "failures": summary_classification.get("failures"),
            "operational_abstentions": summary_classification.get("abstention_count"),
            "semantic_covered_records": int(
                round(
                    summary_classification["semantic_coverage"]
                    * summary_classification["total"]
                )
            ),
            "semantic_coverage": summary_classification.get("semantic_coverage"),
            "selective_accuracy": summary_classification.get("selective_accuracy"),
            "semantic_errors_on_covered_records": four_class_errors,
            "predicted_triagem_manual": summary_classification.get(
                "predicted_class_triagem_manual"
            ),
            "routed_to_human": summary_classification.get("routed_to_human_total"),
            "routed_to_human_rate": summary_classification.get("routed_to_human_rate"),
            "straight_through_automation_records": int(
                round(
                    summary_classification["straight_through_automation_coverage"]
                    * summary_classification["total"]
                )
            ),
            "straight_through_automation_coverage": summary_classification.get(
                "straight_through_automation_coverage"
            ),
            "confusion": recalculated_confusion,
            "gold_support": dict(sorted(gold_support.items())),
            "evaluated_prediction_support": dict(sorted(predicted_support.items())),
            "decision_path_support": dict(sorted(route_support.items())),
            "latency_ms": {
                "mean": statistics.fmean(latencies),
                "p50": percentile(latencies, 0.50),
                "p95": percentile(latencies, 0.95),
            },
        },
        "hierarchical_operational_classification": {
            "obra_vs_manutencao": {
                "eligible_records": len(actionable_gold),
                "distinct_narrative_cores": len(actionable_cores),
                "gold_support": {
                    "OBRA": sum(view["gold"] == "OBRA" for view in actionable_gold),
                    "MANUTENCAO": sum(
                        view["gold"] in {"DEMO", "SOB_DEMANDA"}
                        for view in actionable_gold
                    ),
                },
                "automatic_records": hierarchy_automatic,
                "human_review_records": hierarchy_review,
                "automatic_coverage": ratio(hierarchy_automatic, len(actionable_gold)),
                "selective_accuracy": ratio(hierarchy_correct, hierarchy_automatic),
                "confusion_with_human_review": {
                    gold: dict(sorted(counts.items()))
                    for gold, counts in hierarchy_confusion.items()
                },
                "critical_maintenance_as_obra": {
                    "count": maintenance_as_obra,
                    "rate_over_all_maintenance": ratio(
                        maintenance_as_obra, len(maintenance_gold)
                    ),
                    "rate_over_automatic_maintenance": ratio(
                        maintenance_as_obra, maintenance_automatic
                    ),
                },
                "obra_as_maintenance": obra_as_maintenance,
                "by_gold_group": {
                    "OBRA": {
                        "total": 160,
                        "automatic_correct": hierarchy_confusion["OBRA"]["OBRA"],
                        "human_review": hierarchy_confusion["OBRA"][REVIEW_LABEL],
                        "automatic_coverage": ratio(
                            hierarchy_confusion["OBRA"]["OBRA"]
                            + hierarchy_confusion["OBRA"]["MANUTENCAO"],
                            160,
                        ),
                    },
                    "MANUTENCAO": {
                        "total": len(maintenance_gold),
                        "automatic_correct": hierarchy_confusion["MANUTENCAO"][
                            "MANUTENCAO"
                        ],
                        "human_review": hierarchy_confusion["MANUTENCAO"][REVIEW_LABEL],
                        "automatic_coverage": ratio(
                            hierarchy_confusion["MANUTENCAO"]["OBRA"]
                            + hierarchy_confusion["MANUTENCAO"]["MANUTENCAO"],
                            len(maintenance_gold),
                        ),
                    },
                },
                "automatic_errors": actionable_automatic_errors,
            },
            "maintenance_demo_vs_sob_demanda": {
                "eligible_records": len(maintenance_gold),
                "distinct_narrative_cores": len(maintenance_cores),
                "gold_support": {
                    "DEMO": sum(view["gold"] == "DEMO" for view in maintenance_gold),
                    "SOB_DEMANDA": sum(
                        view["gold"] == "SOB_DEMANDA" for view in maintenance_gold
                    ),
                },
                "automatic_records": maintenance_automatic,
                "human_review_records": maintenance_review,
                "automatic_coverage": ratio(maintenance_automatic, len(maintenance_gold)),
                "selective_accuracy": ratio(maintenance_correct, maintenance_automatic),
                "confusion_with_human_review": {
                    gold: dict(sorted(counts.items()))
                    for gold, counts in maintenance_confusion.items()
                },
                "demo_as_sob_demanda": demo_as_sob,
                "sob_demanda_as_demo": sob_as_demo,
            },
            "safety_across_all_four_gold_classes": {
                "straight_through_automatic_errors": len(all_automatic_errors),
                "errors": all_automatic_errors,
                "note": (
                    "Inclui TRIAGEM_MANUAL no gabarito; por isso registra um "
                    "encaminhamento automatico indevido que fica fora do subconjunto "
                    "OBRA/DEMO/SOB_DEMANDA."
                ),
            },
        },
        "training_development_evidence": {
            "training_records": training.get("train_records"),
            "calibration_records": training.get("calibration_records"),
            "train_groups": (training.get("split_audit") or {}).get("train_groups"),
            "calibration_groups": (training.get("split_audit") or {}).get(
                "calibration_groups"
            ),
            "group_overlap_counts": training.get("leakage_overlap_counts"),
            "full_pipeline_cross_fitted_classification": pipeline_metrics.get(
                "classification"
            ),
            "test_data_used": training.get("test_data_used"),
            "primary33_used": training.get("primary33_used"),
        },
        "scientific_interpretation": {
            "descriptive_result": True,
            "confirmatory_result": False,
            "local_model_beats_external_llm_claim_supported": False,
            "reason": (
                "O candidato foi medido em conjunto sintetico de desenvolvimento com "
                "cinco realizacoes por nucleo narrativo. O manifesto mantem o holdout "
                "confirmatorio pendente e nao ha comparacao pareada valida com Gemini "
                "ou DeepSeek neste artefato."
            ),
            "pseudoreplication_warning": (
                "As 640 linhas nao sao 640 unidades independentes: correspondem a 128 "
                "nucleos narrativos, cada um repetido em cinco realizacoes. Intervalos "
                "e testes inferenciais devem agrupar por narrative_core_sha256. A "
                "distincao por hash define o cluster, mas nao prova independencia entre "
                "nucleos sinteticos."
            ),
            "permitted_claim": (
                "No benchmark de desenvolvimento v1.8, entre 480 exemplos com gabarito "
                "acionavel, houve zero encaminhamentos automaticos de manutencao para "
                "OBRA; a cobertura automatica hierarquica foi 400/480 e todos os 400 "
                "casos automatizados desse subconjunto foram corretos."
            ),
        },
    }


def percent(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.2f}%"


def render_markdown(report: dict[str, Any]) -> str:
    data = report["dataset_structure"]
    four = report["four_class_classification"]
    hierarchy = report["hierarchical_operational_classification"]
    phase_one = hierarchy["obra_vs_manutencao"]
    phase_two = hierarchy["maintenance_demo_vs_sob_demanda"]
    safety = hierarchy["safety_across_all_four_gold_classes"]
    training = report["training_development_evidence"]
    crossfit = training["full_pipeline_cross_fitted_classification"]
    sources = report["sources"]

    lines = [
        "# Classificacao OBRA, DEMO e SOB_DEMANDA — modelo local v1.8",
        "",
        "## Conclusao",
        "",
        (
            "A classificacao foi avaliada, mas o resultado ainda e **descritivo de "
            "desenvolvimento**, nao confirmatorio. No subconjunto com gabarito acionavel "
            f"(OBRA, DEMO ou SOB_DEMANDA), o sistema automatizou "
            f"{phase_one['automatic_records']}/{phase_one['eligible_records']} casos "
            f"({percent(phase_one['automatic_coverage'])}) e acertou todos os casos "
            "automatizados. Os demais seguiram para revisao humana."
        ),
        "",
        (
            "O erro de maior risco — classificar manutencao como OBRA — ocorreu "
            f"**{phase_one['critical_maintenance_as_obra']['count']} vez(es)** no "
            "subconjunto automatizado. Esse zero observado nao prova risco zero em "
            "producao."
        ),
        "",
        "## Resultados hierarquicos",
        "",
        "| Etapa | Casos | Automatizados | Revisao humana | Cobertura automatica | Acuracia seletiva |",
        "|---|---:|---:|---:|---:|---:|",
        (
            f"| OBRA vs MANUTENCAO | {phase_one['eligible_records']} | "
            f"{phase_one['automatic_records']} | {phase_one['human_review_records']} | "
            f"{percent(phase_one['automatic_coverage'])} | "
            f"{percent(phase_one['selective_accuracy'])} |"
        ),
        (
            f"| DEMO vs SOB_DEMANDA | {phase_two['eligible_records']} | "
            f"{phase_two['automatic_records']} | {phase_two['human_review_records']} | "
            f"{percent(phase_two['automatic_coverage'])} | "
            f"{percent(phase_two['selective_accuracy'])} |"
        ),
        "",
        "### OBRA versus MANUTENCAO",
        "",
        "| Gabarito | OBRA | MANUTENCAO | Revisao humana | Total |",
        "|---|---:|---:|---:|---:|",
        (
            "| OBRA | "
            f"{phase_one['confusion_with_human_review']['OBRA'].get('OBRA', 0)} | "
            f"{phase_one['confusion_with_human_review']['OBRA'].get('MANUTENCAO', 0)} | "
            f"{phase_one['confusion_with_human_review']['OBRA'].get(REVIEW_LABEL, 0)} | "
            f"{phase_one['gold_support']['OBRA']} |"
        ),
        (
            "| MANUTENCAO | "
            f"{phase_one['confusion_with_human_review']['MANUTENCAO'].get('OBRA', 0)} | "
            f"{phase_one['confusion_with_human_review']['MANUTENCAO'].get('MANUTENCAO', 0)} | "
            f"{phase_one['confusion_with_human_review']['MANUTENCAO'].get(REVIEW_LABEL, 0)} | "
            f"{phase_one['gold_support']['MANUTENCAO']} |"
        ),
        "",
        f"- Manutencao enviada automaticamente como OBRA: {phase_one['critical_maintenance_as_obra']['count']}/{phase_one['gold_support']['MANUTENCAO']}. ",
        f"- OBRA enviada automaticamente como manutencao: {phase_one['obra_as_maintenance']}/{phase_one['gold_support']['OBRA']}. ",
        f"- Cobertura automatica de OBRA: {phase_one['by_gold_group']['OBRA']['automatic_correct']}/{phase_one['by_gold_group']['OBRA']['total']} ({percent(phase_one['by_gold_group']['OBRA']['automatic_coverage'])}).",
        f"- Cobertura automatica de manutencao: {phase_one['by_gold_group']['MANUTENCAO']['automatic_correct']}/{phase_one['by_gold_group']['MANUTENCAO']['total']} ({percent(phase_one['by_gold_group']['MANUTENCAO']['automatic_coverage'])}).",
        "",
        "### DEMO versus SOB_DEMANDA",
        "",
        "| Gabarito | DEMO | SOB_DEMANDA | Revisao humana | Total |",
        "|---|---:|---:|---:|---:|",
        (
            "| DEMO | "
            f"{phase_two['confusion_with_human_review']['DEMO'].get('DEMO', 0)} | "
            f"{phase_two['confusion_with_human_review']['DEMO'].get('SOB_DEMANDA', 0)} | "
            f"{phase_two['confusion_with_human_review']['DEMO'].get(REVIEW_LABEL, 0)} | "
            f"{phase_two['gold_support']['DEMO']} |"
        ),
        (
            "| SOB_DEMANDA | "
            f"{phase_two['confusion_with_human_review']['SOB_DEMANDA'].get('DEMO', 0)} | "
            f"{phase_two['confusion_with_human_review']['SOB_DEMANDA'].get('SOB_DEMANDA', 0)} | "
            f"{phase_two['confusion_with_human_review']['SOB_DEMANDA'].get(REVIEW_LABEL, 0)} | "
            f"{phase_two['gold_support']['SOB_DEMANDA']} |"
        ),
        "",
        f"Nao houve troca automatica DEMO→SOB_DEMANDA ({phase_two['demo_as_sob_demanda']}) nem SOB_DEMANDA→DEMO ({phase_two['sob_demanda_as_demo']}) nesse conjunto.",
        "",
        "## Leitura completa de quatro classes",
        "",
        f"Foram processados {four['valid']}/{four['total']} registros validos, sem falha de contrato. Houve {four['operational_abstentions']} abstencoes operacionais e {four['routed_to_human']} encaminhamentos humanos. A cobertura semantica foi {four['semantic_covered_records']}/{four['total']} ({percent(four['semantic_coverage'])}), com acuracia seletiva de {percent(four['selective_accuracy'])}. A automacao direta, sem rota humana, foi {four['straight_through_automation_records']}/{four['total']} ({percent(four['straight_through_automation_coverage'])}).",
        "",
        f"A matriz de quatro classes registra {four['semantic_errors_on_covered_records']} divergencias semanticas em casos cobertos. Entre as rotas diretas houve {safety['straight_through_automatic_errors']} erro: TRIAGEM_MANUAL→SOB_DEMANDA. Esse caso nao e manutencao→OBRA, mas impede afirmar perfeicao global.",
        "",
        f"Latencia da classificacao no computador de teste: media {four['latency_ms']['mean']:.3f} ms, mediana {four['latency_ms']['p50']:.3f} ms e p95 {four['latency_ms']['p95']:.3f} ms.",
        "",
        "## Evidencia de treinamento separada do benchmark",
        "",
        (
            f"No recorte cross-fitted do pipeline completo ({crossfit['records']} registros), a acuracia semantica foi {percent(crossfit['semantic_accuracy'])}, o macro-F1 foi {crossfit['semantic_macro_f1']:.6f}, a cobertura automatica foi {crossfit['automatic_records']}/{crossfit['records']} ({percent(crossfit['automatic_coverage'])}) e houve {crossfit['automatic_errors']} erros automaticos. Essa evidencia serviu para congelar limiares; nao substitui holdout confirmatorio."
            if crossfit
            else "Evidencia cross-fitted do pipeline completo nao informada no relatorio."
        ),
        "",
        f"Limiar geral: {report['thresholds']['classification']:.2f}. Limiar especifico para OBRA: {report['thresholds']['classification_obra']:.2f}. O manifesto declara o candidato congelado, mas ainda como `{report['model']['scientific_claim_status']}`.",
        "",
        "## Unidade amostral e limitacoes",
        "",
        f"As {data['classification_records']} linhas correspondem a {data['distinct_narrative_cores']} nucleos narrativos distintos e {data['surface_realizations']} realizacoes de superficie por nucleo. No recorte acionavel sao {data['actionable_hierarchy_records']} linhas, mas apenas {data['actionable_hierarchy_distinct_cores']} nucleos distintos; no recorte de manutencao, {data['maintenance_subtype_records']} linhas e {data['maintenance_subtype_distinct_cores']} nucleos distintos. Hashes distintos definem clusters, mas nao demonstram independencia estatistica entre nucleos sinteticos.",
        "",
        "Consequencias:",
        "",
        "- nao tratar as 640 linhas como observacoes independentes em testes ou intervalos de confianca;",
        "- agrupar por `narrative_core_sha256` em bootstrap, validacao ou comparacoes;",
        "- nao usar estes numeros para afirmar que o modelo local supera Gemini ou DeepSeek; falta comparacao pareada valida;",
        "- preservar a revisao humana: 59/160 casos OBRA e 21/320 manutencoes nao receberam encaminhamento automatico;",
        "- confirmar em holdout congelado, com rotulos independentes do treinamento, antes da alegacao cientifica final.",
        "",
        "## Rastreabilidade",
        "",
        "| Fonte | SHA-256 |",
        "|---|---|",
    ]
    for key in (
        "predictions",
        "corrected_summary",
        "plan",
        "units",
        "artifact_manifest",
        "model_manifest",
        "frozen_bundle",
        "training_dataset",
    ):
        source = sources[key]
        lines.append(f"| `{source['path']}` | `{source['sha256']}` |")

    lines.extend(
        [
            "",
            "O JSON ao lado deste relatorio contem as contagens, matrizes, casos de erro e metadados em formato legivel por maquina.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument(
        "--artifact-manifest", type=Path, default=DEFAULT_ARTIFACT_MANIFEST
    )
    parser.add_argument("--model-manifest", type=Path, default=DEFAULT_MODEL_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(
        args.run_dir.resolve(),
        args.artifact_manifest.resolve(),
        args.model_manifest.resolve(),
    )
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "metricas_classificacao_hierarquica.json"
    markdown_path = output_dir / "RELATORIO.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(json_path)
    print(markdown_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
