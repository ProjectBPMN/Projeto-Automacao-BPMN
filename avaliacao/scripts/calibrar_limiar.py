from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

import conferir_gabarito as checker


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "t", "yes", "sim"}


def classification_curve(run_id: str, thresholds: list[float]) -> list[dict]:
    rows = checker.query(
        """
        SELECT
          v.classe_correta,
          v.classe_predita,
          v.confianca,
          CASE
            WHEN LOWER(COALESCE(i.output_normalizado->>'abstained',''))
                 IN ('true','false')
              THEN (i.output_normalizado->>'abstained')::boolean
            ELSE FALSE
          END AS explicit_abstention
        FROM vw_decisoes_classificacao v
        LEFT JOIN LATERAL (
          SELECT d.output_normalizado
          FROM ia_decisoes d
          WHERE d.ticket_id=v.ticket_id
            AND d.etapa='CLASSIFICACAO'
          ORDER BY d.criado_em DESC,d.id DESC
          LIMIT 1
        ) i ON TRUE
        WHERE v.run_id=%s AND v.confianca IS NOT NULL
        """,
        (run_id,),
    )
    curve = []
    for threshold in thresholds:
        covered = []
        explicit_abstentions = 0
        threshold_abstentions = 0
        semantic_manual_predictions = 0
        for row in rows:
            explicit = _as_bool(row.get("explicit_abstention"))
            if explicit:
                explicit_abstentions += 1
                continue
            if float(row["confianca"]) < threshold:
                threshold_abstentions += 1
                continue
            covered.append(row)
            if row["classe_predita"] == "TRIAGEM_MANUAL":
                semantic_manual_predictions += 1
        correct = sum(
            row["classe_predita"] == row["classe_correta"] for row in covered
        )
        curve.append(
            {
                "threshold": threshold,
                "total": len(rows),
                "covered": len(covered),
                "coverage": len(covered) / len(rows) if rows else 0,
                "risk": 1 - correct / len(covered) if covered else None,
                "correct_covered": correct,
                "abstained": len(rows) - len(covered),
                "explicit_abstentions": explicit_abstentions,
                "threshold_abstentions": threshold_abstentions,
                "semantic_triagem_manual_predictions_covered": (
                    semantic_manual_predictions
                ),
            }
        )
    return curve


def dedup_curve(run_id: str, thresholds: list[float]) -> list[dict]:
    rows = checker.query(
        """
        SELECT
          classe_correta,
          classe_predita,
          confianca,
          CASE
            WHEN LOWER(COALESCE(output_normalizado->>'abstained',''))
                 IN ('true','false')
              THEN (output_normalizado->>'abstained')::boolean
            WHEN LOWER(COALESCE(output_normalizado->>'requer_revisao',''))
                 IN ('true','false')
              THEN (output_normalizado->>'requer_revisao')::boolean
            ELSE FALSE
          END AS explicit_abstention
        FROM vw_decisoes_deduplicacao
        WHERE run_id=%s AND confianca IS NOT NULL
        """,
        (run_id,),
    )
    curve = []
    for threshold in thresholds:
        covered = []
        explicit_abstentions = 0
        threshold_abstentions = 0
        for row in rows:
            explicit = _as_bool(row.get("explicit_abstention"))
            if explicit:
                explicit_abstentions += 1
                continue
            if float(row["confianca"]) < threshold:
                threshold_abstentions += 1
                continue
            covered.append(row)
        tp = sum(
            row["classe_correta"] == "DUPLICADO"
            and row["classe_predita"] == "DUPLICADO"
            for row in covered
        )
        fp = sum(
            row["classe_correta"] != "DUPLICADO"
            and row["classe_predita"] == "DUPLICADO"
            for row in covered
        )
        fn_covered = sum(
            row["classe_correta"] == "DUPLICADO"
            and row["classe_predita"] != "DUPLICADO"
            for row in covered
        )
        tn = sum(
            row["classe_correta"] != "DUPLICADO"
            and row["classe_predita"] != "DUPLICADO"
            for row in covered
        )
        all_positives = sum(row["classe_correta"] == "DUPLICADO" for row in rows)
        all_negatives = sum(row["classe_correta"] != "DUPLICADO" for row in rows)
        covered_negatives = sum(
            row["classe_correta"] != "DUPLICADO" for row in covered
        )
        precision = tp / (tp + fp) if tp + fp else None
        selective_recall = tp / (tp + fn_covered) if tp + fn_covered else None
        selective_f1 = (
            2 * precision * selective_recall / (precision + selective_recall)
            if precision is not None
            and selective_recall is not None
            and precision + selective_recall
            else None
        )
        curve.append(
            {
                "threshold": threshold,
                "total": len(rows),
                "covered": len(covered),
                "coverage": len(covered) / len(rows) if rows else 0,
                "abstained": len(rows) - len(covered),
                "explicit_abstentions": explicit_abstentions,
                "threshold_abstentions": threshold_abstentions,
                "tp": tp,
                "fp": fp,
                "fn_covered": fn_covered,
                "tn": tn,
                "precision": precision,
                "selective_recall": selective_recall,
                "selective_f1": selective_f1,
                "automation_recall": tp / all_positives if all_positives else None,
                "automated_false_positive_rate": (
                    fp / all_negatives if all_negatives else None
                ),
                "selective_false_positive_rate": (
                    fp / covered_negatives if covered_negatives else None
                ),
            }
        )
    return curve


def select_classification_threshold(
    curve: Sequence[dict[str, Any]],
    *,
    max_risk: float,
    min_coverage: float,
) -> float | None:
    for point in curve:
        if (
            point["risk"] is not None
            and point["risk"] <= max_risk
            and point["coverage"] >= min_coverage
        ):
            return float(point["threshold"])
    return None


def select_dedup_threshold(
    curve: Sequence[dict[str, Any]],
    *,
    max_false_positive_rate: float,
    min_precision: float,
    min_coverage: float,
) -> float | None:
    for point in curve:
        if (
            point["automated_false_positive_rate"] is not None
            and point["automated_false_positive_rate"] <= max_false_positive_rate
            and point["precision"] is not None
            and point["precision"] >= min_precision
            and point["coverage"] >= min_coverage
        ):
            return float(point["threshold"])
    return None


def build_payload(
    *,
    run_id: str,
    classification: list[dict[str, Any]],
    deduplication: list[dict[str, Any]],
    max_classification_risk: float,
    min_classification_coverage: float,
    max_dedup_false_positive_rate: float,
    min_dedup_precision: float,
    min_dedup_coverage: float,
) -> dict[str, Any]:
    classification_threshold = select_classification_threshold(
        classification,
        max_risk=max_classification_risk,
        min_coverage=min_classification_coverage,
    )
    dedup_threshold = select_dedup_threshold(
        deduplication,
        max_false_positive_rate=max_dedup_false_positive_rate,
        min_precision=min_dedup_precision,
        min_coverage=min_dedup_coverage,
    )
    approved = classification_threshold is not None and dedup_threshold is not None
    legacy_shared = (
        max(classification_threshold, dedup_threshold) if approved else None
    )
    return {
        "protocol_version": "calibracao-limiar-v2.0.0",
        "pilot_run_id": run_id,
        "criteria": {
            "classification": {
                "max_risk": max_classification_risk,
                "min_coverage": min_classification_coverage,
            },
            "deduplication": {
                "max_automated_false_positive_rate": (
                    max_dedup_false_positive_rate
                ),
                "min_precision": min_dedup_precision,
                "min_coverage": min_dedup_coverage,
            },
        },
        "classification_curve": classification,
        "deduplication_curve": deduplication,
        "selected_thresholds": {
            "classification": classification_threshold,
            "deduplication": dedup_threshold,
        },
        "selected_threshold": legacy_shared,
        "legacy_shared_threshold_policy": (
            "max(classification,deduplication); compatibilidade conservadora para "
            "runtimes antigos. Não substitui os dois limiares científicos."
        ),
        "approved": approved,
        "abstention_policy": {
            "explicit_output_field": "abstained",
            "dedup_review_field_accepted": "requer_revisao",
            "semantic_class": "TRIAGEM_MANUAL",
            "semantic_class_is_abstention": False,
            "below_threshold_action": "ABSTAIN_AND_ROUTE_TO_HUMAN_REVIEW",
            "below_threshold_is_not_nao_duplicado": True,
        },
        "warning": (
            "Limiar é calibrado somente no piloto. TRIAGEM_MANUAL permanece classe "
            "semântica; apenas abstained/requer_revisao ou confiança abaixo do limiar "
            "reduzem cobertura automática."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Calibra limiares independentes de classificação e deduplicação "
            "somente no piloto adjudicado."
        )
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--saida", type=Path, required=True)
    parser.add_argument("--min", dest="minimum", type=float, default=0.50)
    parser.add_argument("--max", dest="maximum", type=float, default=0.95)
    parser.add_argument("--passo", type=float, default=0.05)
    parser.add_argument("--risco-maximo", type=float, default=0.10)
    parser.add_argument("--cobertura-minima", type=float, default=0.60)
    parser.add_argument("--fp-dedup-maximo", type=float, default=0.05)
    parser.add_argument("--precisao-dedup-minima", type=float, default=0.90)
    parser.add_argument("--cobertura-dedup-minima", type=float, default=0.50)
    args = parser.parse_args()
    experiment = checker.experiment(args.run_id)
    if not experiment.get("rotulos_validados"):
        raise SystemExit("Calibração do limiar exige piloto adjudicado.")
    generation_config = experiment.get("generation_config") or {}
    pilot_threshold = float(generation_config.get("confidence_threshold", 0.65))
    if args.minimum < pilot_threshold:
        raise SystemExit(
            "A curva solicitada começa abaixo do limiar usado no piloto "
            f"({args.minimum:.2f} < {pilot_threshold:.2f}). Execute novo piloto "
            "com os limiares mínimos iguais ao início da curva; decisões já "
            "abstidas não podem ser reconstruídas sem nova inferência."
        )
    thresholds = []
    value = args.minimum
    while value <= args.maximum + 1e-9:
        thresholds.append(round(value, 6))
        value += args.passo
    classification = classification_curve(args.run_id, thresholds)
    deduplication = dedup_curve(args.run_id, thresholds)
    payload = build_payload(
        run_id=args.run_id,
        classification=classification,
        deduplication=deduplication,
        max_classification_risk=args.risco_maximo,
        min_classification_coverage=args.cobertura_minima,
        max_dedup_false_positive_rate=args.fp_dedup_maximo,
        min_dedup_precision=args.precisao_dedup_minima,
        min_dedup_coverage=args.cobertura_dedup_minima,
    )
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"[OK] Calibração de limiares: {args.saida}; "
        f"approved={payload['approved']}; selected={payload['selected_thresholds']}"
    )
    return 0 if payload["approved"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
