from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAN = ROOT / "avaliacao" / "config" / "plano_cientifico_preimplantacao_v5.json"
DEFAULT_DATASET = ROOT / "avaliacao" / "datasets" / "desenvolvimento_local_v2.jsonl"


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def audit(plan: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    corpus = plan["corpus"]
    class_groups: dict[str, set[str]] = defaultdict(set)
    dedup_positive: set[str] = set()
    dedup_negative_complete: set[str] = set()
    dedup_negative_critical: set[str] = set()
    missing_group = 0
    for row in rows:
        group = str(row.get("source_dependency_group_sha256") or "")
        if not group:
            missing_group += 1
            continue
        if row.get("dimension") == "CLASSIFICACAO":
            label = str(row.get("expected_classification") or "")
            if label:
                class_groups[label].add(group)
        elif row.get("dimension") == "DEDUPLICACAO" and row.get("pair_role") == "CHALLENGE":
            expected = row.get("expected_dedup")
            if expected is True:
                dedup_positive.add(group)
            elif expected is False:
                if row.get("information_completeness") == "COMPLETA":
                    dedup_negative_complete.add(group)
                else:
                    dedup_negative_critical.add(group)
    classification = {label: len(groups) for label, groups in sorted(class_groups.items())}
    class_target = int(corpus["classification_independent_families_per_class_min"])
    observed = {
        "classification_independent_groups_by_class": classification,
        "dedup_duplicate_independent_groups": len(dedup_positive),
        "dedup_hard_nonduplicate_complete_independent_groups": len(dedup_negative_complete),
        "dedup_hard_nonduplicate_critical_independent_groups": len(dedup_negative_critical),
        "records_missing_dependency_group": missing_group,
    }
    gates = {
        "classification_target_met": bool(classification) and all(
            count >= class_target for count in classification.values()
        ),
        "dedup_duplicate_target_met": len(dedup_positive)
        >= int(corpus["dedup_duplicate_independent_families_min"]),
        "dedup_complete_negative_target_met": len(dedup_negative_complete)
        >= int(corpus["dedup_hard_nonduplicate_complete_independent_families_min"]),
        "dedup_critical_negative_target_met": len(dedup_negative_critical)
        >= int(corpus["dedup_hard_nonduplicate_critical_independent_families_min"]),
        "all_records_grouped": missing_group == 0,
        "locked_challenge_exists_and_is_disjoint": False,
    }
    return {
        "status": "PASS" if all(gates.values()) else "GAPS_REMAIN",
        "observed": observed,
        "gates": gates,
        "scientific_result": False,
        "confirmatory_eligible": False,
        "interpretation_limit": "Conta grupos declarados no corpus sintético; não testa independência causal nem validade externa.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "plan": str(args.plan.resolve()),
        "dataset": str(args.dataset.resolve()),
        **audit(
            json.loads(args.plan.read_text(encoding="utf-8")),
            _rows(args.dataset),
        ),
    }
    if args.output:
        output = args.output.resolve()
        output.relative_to(ROOT.resolve())
        if output.exists():
            raise RuntimeError(f"Evidência já existe: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
