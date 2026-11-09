from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from avaliacao.operacional.core import (
    ROOT,
    collect_live_point_in_time,
    evaluate_drift,
    load_policy,
    sha256_file,
    snapshot_from_rows,
    utc_now,
)


DEFAULT_SOURCE = (
    ROOT
    / "avaliacao"
    / "resultados"
    / "selecao-supervisionada-v2.1-20260826"
    / "predicoes_oof.csv"
)
DEFAULT_OUTPUT = (
    ROOT
    / "avaliacao"
    / "resultados"
    / "operacional"
    / "janelas-aceleradas-proxy-20260902.json"
)
CANDIDATE = "classification__hybrid__multilingual_e5_small__linear_svm"
CLASSES = ("DEMO", "OBRA", "SOB_DEMANDA", "TRIAGEM_MANUAL")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Valida três janelas técnicas aceleradas, disjuntas por grupo e somente com rótulos-proxy."
    )
    result.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    result.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return result


def _boolean(value: str) -> bool:
    return value.strip().lower() == "true"


def _read_candidate(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        rows = [row for row in csv.DictReader(source) if row.get("combination_id") == CANDIDATE]
    if not rows:
        raise RuntimeError(f"Candidato congelado ausente em {path}")
    if len({row["unit_id"] for row in rows}) != len(rows):
        raise RuntimeError("unit_id duplicado no candidato congelado")
    return rows


def _partition_by_group(rows: list[dict[str, str]]) -> list[list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["group"], []).append(row)
    buckets: list[list[dict[str, str]]] = [[], [], []]
    assigned: list[set[str]] = [set(), set(), set()]
    groups = sorted(
        grouped.items(),
        key=lambda item: (-len(item[1]), hashlib.sha256(item[0].encode("utf-8")).hexdigest()),
    )
    for group, group_rows in groups:
        index = min(range(3), key=lambda candidate: (len(buckets[candidate]), candidate))
        buckets[index].extend(group_rows)
        assigned[index].add(group)
    if (assigned[0] & assigned[1]) or (assigned[0] & assigned[2]) or (assigned[1] & assigned[2]):
        raise RuntimeError("Particionamento permitiu vazamento de grupo")
    return buckets


def _macro_f1(rows: list[dict[str, str]]) -> float:
    values: list[float] = []
    for label in CLASSES:
        tp = sum(row["gold"] == label and row["semantic_prediction"] == label for row in rows)
        fp = sum(row["gold"] != label and row["semantic_prediction"] == label for row in rows)
        fn = sum(row["gold"] == label and row["semantic_prediction"] != label for row in rows)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        values.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return sum(values) / len(values)


def _ece(rows: list[dict[str, str]]) -> float:
    bins: list[list[tuple[float, bool]]] = [[] for _ in range(10)]
    for row in rows:
        confidence = min(1.0, max(0.0, float(row["confidence"])))
        bins[min(9, int(confidence * 10))].append(
            (confidence, row["gold"] == row["semantic_prediction"])
        )
    total = len(rows)
    return sum(
        (len(values) / total)
        * abs(
            sum(confidence for confidence, _ in values) / len(values)
            - sum(1.0 for _, correct in values if correct) / len(values)
        )
        for values in bins
        if values
    )


def _window(rows: list[dict[str, str]], index: int, probe: dict[str, Any]) -> dict[str, Any]:
    covered = [row for row in rows if _boolean(row["covered"])]
    errors = [row for row in covered if row["gold"] != row["semantic_prediction"]]
    critical = [
        row
        for row in covered
        if row["gold"] != "OBRA" and row["semantic_prediction"] == "OBRA"
    ]
    snapshot_rows = [
        {
            "predicao": row["semantic_prediction"],
            "etapa": "CLASSIFICACAO_PROXY",
            "confianca": float(row["confidence"]),
            "erro_ia": False,
        }
        for row in rows
    ]
    return {
        "index": index,
        "mode": "ACCELERATED_COUNT_BASED_DISJOINT_PROXY_GROUPS",
        "record_count": len(rows),
        "independent_proxy_group_count": len({row["group"] for row in rows}),
        "proxy_class_distribution": dict(sorted(Counter(row["gold"] for row in rows).items())),
        "proxy_prediction_distribution": dict(
            sorted(Counter(row["semantic_prediction"] for row in rows).items())
        ),
        "metrics": {
            "proxy_accuracy": sum(
                row["gold"] == row["semantic_prediction"] for row in rows
            )
            / len(rows),
            "proxy_macro_f1": _macro_f1(rows),
            "proxy_ece_10_bins": _ece(rows),
            "automatic_coverage": len(covered) / len(rows),
            "proxy_selective_risk": len(errors) / len(covered) if covered else None,
            "proxy_non_obra_as_obra": len(critical),
        },
        "component_probe": probe,
        "snapshot": snapshot_from_rows(snapshot_rows),
        "semantic_correctness_confirmed": False,
    }


def main() -> int:
    args = parser().parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    output.relative_to(ROOT.resolve())
    if output.exists():
        raise RuntimeError(f"Evidência já existe: {output}")
    policy = load_policy()
    rows = _read_candidate(source)
    buckets = _partition_by_group(rows)
    if any(len(bucket) < int(policy["drift"]["minimum_current_sample_size"]) for bucket in buckets):
        raise RuntimeError("Uma janela ficou abaixo do mínimo pré-registrado para drift")
    windows = [
        _window(bucket, index + 1, collect_live_point_in_time())
        for index, bucket in enumerate(buckets)
    ]
    reference = windows[0]["snapshot"]
    for window in windows:
        window["drift_vs_window_1"] = evaluate_drift(
            reference, window["snapshot"], policy=policy
        )
        del window["snapshot"]
    all_components_available = all(
        window["component_probe"]["status"] == "PASS" for window in windows
    )
    result = {
        "schema_version": "1.0.0",
        "generated_at": utc_now(),
        "status": "THREE_ACCELERATED_PROXY_WINDOWS_COMPLETE",
        "technical_mechanism_passed": all_components_available,
        "candidate": CANDIDATE,
        "source": source.relative_to(ROOT).as_posix(),
        "source_sha256": sha256_file(source),
        "window_count": len(windows),
        "group_leakage_between_windows": False,
        "windows": windows,
        "labels": {
            "proxy_labels_only": True,
            "scientific_result": False,
            "semantic_correctness_confirmed": False,
            "production_slo_estimated": False,
            "longitudinal_window": False,
        },
        "conclusion": (
            "As três janelas aceleradas validam cálculo, particionamento por grupo, sondagem "
            "e detecção de drift. Elas não medem SLO longitudinal, não usam chamados reais e "
            "não tornam o candidato cientificamente confirmado."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
