from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = ROOT / "avaliacao" / "datasets" / "corpus_v3_teste.jsonl"
DEFAULT_MANIFEST = ROOT / "avaliacao" / "datasets" / "corpus_v3_teste_manifest.json"
DEFAULT_PLAN = ROOT / "avaliacao" / "config" / "plano_amostral_automatizado_v4.json"
DEFAULT_OUTPUT = ROOT / "avaliacao" / "resultados" / "auditoria_suficiencia_amostral_2026-07-15"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Objeto JSON esperado: {path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows:
        raise ValueError(f"Dataset vazio: {path}")
    return rows


def z_value(confidence: float) -> float:
    if not 0 < confidence < 1:
        raise ValueError("confidence deve estar entre zero e um")
    return NormalDist().inv_cdf(0.5 + confidence / 2)


def required_worst_case(margin: float, confidence: float = 0.95) -> int:
    if not 0 < margin < 1:
        raise ValueError("margin deve estar entre zero e um")
    z = z_value(confidence)
    return math.ceil((z * z * 0.25) / (margin * margin))


def wilson_interval(successes: int, total: int, confidence: float = 0.95) -> dict[str, float]:
    if total <= 0 or not 0 <= successes <= total:
        raise ValueError("contagem binomial inválida")
    z = z_value(confidence)
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return {
        "estimate": p,
        "lower": max(0.0, center - margin),
        "upper": min(1.0, center + margin),
        "half_width": margin,
    }


def required_zero_event_upper(maximum_upper: float, confidence: float = 0.95) -> int:
    for total in range(1, 1_000_000):
        if wilson_interval(0, total, confidence)["upper"] <= maximum_upper:
            return total
    raise RuntimeError("limite de busca excedido")


def unique_cores(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        core = str(row.get("narrative_core") or row.get("case_id") or "")
        if not core:
            raise ValueError("registro sem narrative_core/case_id")
        output.setdefault(core, row)
    return output


def audit(
    cases: list[dict[str, Any]],
    manifest: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    challenges = [row for row in cases if row.get("pair_role") == "CHALLENGE"]
    classification = [row for row in cases if row.get("dimension") == "CLASSIFICACAO"]
    challenge_cores = unique_cores(challenges)
    class_cores = unique_cores(classification)
    duplicate_cores = {
        core: row for core, row in challenge_cores.items() if bool(row.get("expected_dedup"))
    }
    nonduplicate_cores = {
        core: row for core, row in challenge_cores.items() if not bool(row.get("expected_dedup"))
    }
    critical_nonduplicate_cores = {
        core: row
        for core, row in nonduplicate_cores.items()
        if str(row.get("risk") or "").upper() == "CRITICO"
        or str(row.get("completeness") or "").upper() == "INSUFICIENTE"
    }
    complete_nonduplicate_cores = {
        core: row
        for core, row in nonduplicate_cores.items()
        if core not in critical_nonduplicate_cores
    }
    class_core_counts = Counter(
        str(row.get("expected_classification") or "") for row in class_cores.values()
    )
    target = plan["targets"]
    class_target = int(target["classification_independent_cores_per_class"])
    duplicate_target = int(target["dedup_duplicate_independent_cores"])
    complete_target = int(target["dedup_hard_nonduplicate_complete_independent_cores"])
    critical_target = int(target["dedup_hard_nonduplicate_critical_independent_cores"])
    class_gaps = {
        label: max(0, class_target - class_core_counts.get(label, 0))
        for label in ("OBRA", "DEMO", "SOB_DEMANDA", "TRIAGEM_MANUAL")
    }
    gaps = {
        "classification_new_tickets": sum(class_gaps.values()),
        "dedup_duplicate_new_episodes": max(0, duplicate_target - len(duplicate_cores)),
        "dedup_nonduplicate_complete_new_episodes": max(
            0, complete_target - len(complete_nonduplicate_cores)
        ),
        "dedup_nonduplicate_critical_new_episodes": max(
            0, critical_target - len(critical_nonduplicate_cores)
        ),
    }
    additional_tickets = gaps["classification_new_tickets"] + 2 * (
        gaps["dedup_duplicate_new_episodes"]
        + gaps["dedup_nonduplicate_complete_new_episodes"]
        + gaps["dedup_nonduplicate_critical_new_episodes"]
    )
    confidence = float(plan.get("confidence", 0.95))
    per_class_intervals = {
        label: wilson_interval(max(0, count // 2), count, confidence)
        for label, count in class_core_counts.items()
        if count
    }
    family_counts = Counter(str(row.get("contrast_family") or "") for row in challenge_cores.values())
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(DEFAULT_DATASET.relative_to(ROOT)),
        "manifest_status": manifest.get("status"),
        "scientific_result": False,
        "confirmatory_eligible": False,
        "nominal": {
            "tickets": len(cases),
            "dedup_challenges": len(challenges),
            "classification_cases": len(classification),
        },
        "independent_units": {
            "dedup_challenge_cores": len(challenge_cores),
            "dedup_duplicate_cores": len(duplicate_cores),
            "dedup_nonduplicate_complete_cores": len(complete_nonduplicate_cores),
            "dedup_nonduplicate_critical_cores": len(critical_nonduplicate_cores),
            "classification_cores": len(class_cores),
            "classification_cores_by_class": dict(sorted(class_core_counts.items())),
            "dedup_cores_by_family_min": min(family_counts.values()) if family_counts else 0,
            "dedup_cores_by_family_max": max(family_counts.values()) if family_counts else 0,
        },
        "precision_reference": {
            "required_independent_n_margin_10pp_worst_case": required_worst_case(0.10, confidence),
            "required_independent_n_margin_5pp_worst_case": required_worst_case(0.05, confidence),
            "required_zero_false_positive_n_for_wilson_upper_5pct": required_zero_event_upper(0.05, confidence),
            "required_zero_false_negative_n_for_wilson_upper_2pct": required_zero_event_upper(0.02, confidence),
            "current_classification_per_class_wilson_half_width_at_50pct": {
                label: interval["half_width"] for label, interval in sorted(per_class_intervals.items())
            },
            "current_dedup_challenge_wilson_half_width_at_50pct": wilson_interval(
                len(challenge_cores) // 2, len(challenge_cores), confidence
            )["half_width"],
            "current_critical_nonduplicate_zero_fp_upper": wilson_interval(
                0, len(critical_nonduplicate_cores), confidence
            )["upper"],
        },
        "recommended_v4": {
            "targets": target,
            "classification_gap_by_class": class_gaps,
            "gaps": gaps,
            "additional_tickets": additional_tickets,
            "recommended_total_tickets": len(cases) + additional_tickets,
            "increase_raw_tickets_only": False,
            "instruction": (
                "Acrescentar núcleos semânticos realmente novos com uma realização primária; "
                "não contar outra seed ou paráfrases como novas unidades independentes."
            ),
        },
        "decision": {
            "sufficient_for_automated_functional_regression": True,
            "sufficient_for_precise_per_class_scientific_estimates": all(
                count >= class_target for count in class_core_counts.values()
            ),
            "human_review_required_in_this_automated_phase": False,
            "human_workflow_confirmations_must_remain": True,
            "real_world_external_validity_established": False,
        },
    }


def write_report(result: dict[str, Any], output_prefix: Path) -> None:
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    output_prefix.with_suffix(".json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    units = result["independent_units"]
    precision = result["precision_reference"]
    recommendation = result["recommended_v4"]
    lines = [
        "# Auditoria de suficiência amostral — fase automatizada",
        "",
        "## Conclusão",
        "",
        "O corpus V3 é suficiente para regressão funcional automatizada, mas não para estimativas precisas por classe/estrato.",
        "Aumentar somente o número bruto ou trocar a seed não corrige a dependência entre paráfrases.",
        "Esta fase dispensa dupla revisão humana, preserva as confirmações dos workflows e permanece não confirmatória.",
        "",
        "## Unidade independente observada",
        "",
        f"- Tickets nominais: `{result['nominal']['tickets']}`.",
        f"- Núcleos de desafio dedup: `{units['dedup_challenge_cores']}`.",
        f"- Núcleos dedup positivos: `{units['dedup_duplicate_cores']}`.",
        f"- Núcleos negativos completos: `{units['dedup_nonduplicate_complete_cores']}`.",
        f"- Núcleos negativos críticos/insuficientes: `{units['dedup_nonduplicate_critical_cores']}`.",
        f"- Núcleos classificatórios: `{units['classification_cores']}`, `{units['classification_cores_by_class']}`.",
        "",
        "## Precisão e decisão de ampliação",
        "",
        f"- Para margem conservadora de ±10 pp são necessárias `{precision['required_independent_n_margin_10pp_worst_case']}` unidades independentes.",
        f"- Para ±5 pp são necessárias `{precision['required_independent_n_margin_5pp_worst_case']}`.",
        f"- Com zero falsos positivos, são necessários `{precision['required_zero_false_positive_n_for_wilson_upper_5pct']}` negativos independentes para limite superior Wilson ≤ 5%.",
        f"- Com zero falsos negativos, são necessários `{precision['required_zero_false_negative_n_for_wilson_upper_2pct']}` episódios positivos independentes para limite superior Wilson ≤ 2%.",
        f"- Recomendação V4.1: acrescentar `{recommendation['additional_tickets']}` tickets baseados em núcleos novos, totalizando `{recommendation['recommended_total_tickets']}`.",
        "",
        "As repetições superficiais existentes continuam úteis para estabilidade linguística, mas ficam fora do n independente primário.",
    ]
    output_prefix.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audita suficiência amostral por núcleo independente.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--manifesto", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--plano", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--saida", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = audit(
        load_jsonl(args.dataset.resolve()),
        load_json(args.manifesto.resolve()),
        load_json(args.plano.resolve()),
    )
    write_report(result, args.saida.resolve())
    print(json.dumps(result["decision"], ensure_ascii=False, sort_keys=True))
    print(f"[OK] Relatórios: {args.saida.with_suffix('.json')} e {args.saida.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
