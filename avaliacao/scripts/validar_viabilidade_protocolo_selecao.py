"""Falha cedo quando o desenho agrupado não cabe nos grupos disponíveis.

Este preflight não treina modelos nem calcula embeddings. Ele executa as mesmas
divisões externas, de ajuste/calibração, internas e de calibração OOF exigidas
pelo seletor, usando somente rótulos e grupos do corpus congelado.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np

import selecionar_modelos_supervisionados as selection
import treinar_modelo_local as training


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = (
    ROOT / "avaliacao" / "config" / "selecao_modelos_supervisionados_v2.json"
)
TASKS = ("classification", "deduplication")


def effective_cv(config: dict[str, Any], task: str) -> dict[str, Any]:
    base = {
        key: value
        for key, value in config["cross_validation"].items()
        if key != "task_overrides"
    }
    override = config["cross_validation"].get("task_overrides", {}).get(task, {})
    return {**base, **override}


def group_counts(labels: Sequence[int], groups: Sequence[str]) -> dict[str, int]:
    by_label: dict[int, set[str]] = {}
    for label, group in zip(labels, groups):
        by_label.setdefault(int(label), set()).add(str(group))
    return {str(label): len(values) for label, values in sorted(by_label.items())}


def zero_event_upper_95(groups: int) -> float | None:
    return 1.0 - 0.05 ** (1.0 / groups) if groups > 0 else None


def groups_needed_for_zero_event_bound(target: float) -> int:
    return math.ceil(math.log(0.05) / math.log(1.0 - target))


def audit_task(
    task: str,
    labels: Sequence[int],
    groups: Sequence[str],
    config: dict[str, Any],
) -> dict[str, Any]:
    cv = effective_cv(config, task)
    errors: list[str] = []
    fold_audit: list[dict[str, Any]] = []
    counts = group_counts(labels, groups)
    try:
        outer = selection.safe_stratified_group_splits(
            labels,
            groups,
            n_splits=int(cv["outer_folds"]),
            seed=int(cv["outer_seed"]),
            context=f"preflight/{task}/outer",
        )
        for fold, (outer_train, outer_test) in enumerate(outer):
            fit_index, calibration_index, split = selection.fit_calibration_split(
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
            fit_labels = np.asarray(labels)[fit_index]
            fit_groups = np.asarray(groups, dtype=object)[fit_index]
            selection.safe_stratified_group_splits(
                fit_labels,
                fit_groups,
                n_splits=int(cv["inner_folds"]),
                seed=int(cv["outer_seed"]) + 10000 + fold,
                context=f"preflight/{task}/inner-{fold}",
            )
            calibration_labels = np.asarray(labels)[calibration_index]
            calibration_groups = np.asarray(groups, dtype=object)[calibration_index]
            selection.safe_stratified_group_splits(
                calibration_labels,
                calibration_groups,
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
            fold_audit.append(
                {
                    "fold": fold,
                    "outer_train_groups": len(
                        set(np.asarray(groups, dtype=object)[outer_train])
                    ),
                    "outer_test_groups": len(
                        set(np.asarray(groups, dtype=object)[outer_test])
                    ),
                    **split,
                }
            )
    except Exception as exc:  # a mensagem faz parte da evidência de inviabilidade
        errors.append(f"{type(exc).__name__}: {exc}")

    return {
        "task": task,
        "feasible": not errors,
        "records": len(labels),
        "groups": len(set(groups)),
        "groups_by_label": counts,
        "effective_cross_validation": cv,
        "folds_checked": len(fold_audit),
        "fold_audit": fold_audit,
        "errors": errors,
        "zero_event_group_upper_95_by_label": {
            label: zero_event_upper_95(count) for label, count in counts.items()
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--task", action="append", choices=list(TASKS))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    selection.validate_protocol_config(config)
    dataset_path = (ROOT / config["dataset"]["path"]).resolve()
    if selection.sha256_file(dataset_path) != config["dataset"]["sha256"]:
        raise selection.SelectionGuardError("SHA-256 do dataset diverge do protocolo")
    cases = training.load_jsonl(dataset_path)
    sample_sets = selection.build_samples(
        cases,
        embedding_map=None,
        classification_group_field=config["dataset"]["classification_group_field"],
        deduplication_group_field=config["dataset"]["deduplication_group_field"],
    )
    task_data = {
        "classification": (sample_sets[1], sample_sets[2]),
        "deduplication": (sample_sets[4], sample_sets[5]),
    }
    requested = tuple(
        args.task or config.get("execution_tasks", list(TASKS))
    )
    audits = [
        audit_task(task, *task_data[task], config)
        for task in requested
    ]
    payload = {
        "schema": "projeto-ic-preflight-viabilidade-selecao-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "config_path": str(config_path),
        "config_sha256": selection.sha256_file(config_path),
        "dataset_path": str(dataset_path),
        "dataset_sha256": selection.sha256_file(dataset_path),
        "status": "FEASIBLE" if all(item["feasible"] for item in audits) else "INFEASIBLE",
        "tasks": audits,
        "power_context": {
            "groups_needed_for_zero_events_upper_95_at_2_percent": (
                groups_needed_for_zero_event_bound(0.02)
            ),
            "groups_needed_for_zero_events_upper_95_at_5_percent": (
                groups_needed_for_zero_event_bound(0.05)
            ),
            "interpretation": (
                "Viabilidade computacional não implica potência; os limites usam "
                "grupos independentes e zero eventos observados."
            ),
        },
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if payload["status"] == "FEASIBLE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
