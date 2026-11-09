from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "avaliacao" / "config" / "selecao_modelos_supervisionados_v2.json"
DATASET_DIR = ROOT / "avaliacao" / "datasets" / "semantico_v3"
DATASET = DATASET_DIR / "desenvolvimento_semantico_v3_1.jsonl"
DATASET_MANIFEST = DATASET_DIR / "desenvolvimento_semantico_v3_1_manifest.json"
LOCKED = DATASET_DIR / "desafio_semantico_bloqueado_v3_1.jsonl"
LOCKED_MANIFEST = DATASET_DIR / "desafio_semantico_bloqueado_v3_1_manifest.json"
OUTPUT = ROOT / "avaliacao" / "config" / "selecao_modelos_supervisionados_v3.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict:
    config = copy.deepcopy(json.loads(BASE.read_text(encoding="utf-8")))
    development_manifest = json.loads(DATASET_MANIFEST.read_text(encoding="utf-8"))
    locked_manifest = json.loads(LOCKED_MANIFEST.read_text(encoding="utf-8"))
    development_hash = str(development_manifest["files"]["jsonl"]["sha256"])
    locked_hash = str(locked_manifest["files"]["jsonl"]["sha256"])
    if sha256_file(DATASET) != development_hash:
        raise ValueError("Dataset DEV diverge do manifest v3.1")
    config["protocol_version"] = "3.1.0"
    config["created_at"] = "2026-09-14"
    config["development_only"] = True
    config["scientific_result"] = False
    config["confirmatory_eligible"] = False
    config["dataset"].update(
        {
            "path": str(DATASET.relative_to(ROOT)).replace("\\", "/"),
            "sha256": development_hash,
            "allowed_split": "DESENVOLVIMENTO",
            "allow_mixed_label_source_groups": True,
            "locked_challenge_path": str(LOCKED.relative_to(ROOT)).replace("\\", "/"),
            # O preparador le apenas o manifest: nao abre o conteudo bloqueado.
            "locked_challenge_sha256": locked_hash,
            "locked_challenge_access": "FORBIDDEN_DURING_SELECTION",
        }
    )
    locked_relative = str(LOCKED.relative_to(ROOT)).replace("\\", "/")
    config["dataset"]["forbidden_paths"] = sorted(
        set(config["dataset"]["forbidden_paths"] + [locked_relative])
    )
    classifiers = [
        "logistic_regression", "decision_tree", "linear_svm", "mlp", "xgboost"
    ]
    config["execution_combination_ids"] = [
        *[f"classification__hybrid__multilingual_e5_small__{item}" for item in classifiers],
        *[f"deduplication__hybrid_metadata__multilingual_e5_small__{item}" for item in classifiers],
    ]
    config["paired_comparisons"] = {
        "classification": [
            {
                "id": f"classification_{candidate}_vs_logreg",
                "baseline": "classification__hybrid__multilingual_e5_small__logistic_regression",
                "candidate": f"classification__hybrid__multilingual_e5_small__{candidate}",
            }
            for candidate in ("decision_tree", "linear_svm", "mlp", "xgboost")
        ],
        "deduplication": [
            {
                "id": f"deduplication_{candidate}_vs_logreg",
                "baseline": "deduplication__hybrid_metadata__multilingual_e5_small__logistic_regression",
                "candidate": f"deduplication__hybrid_metadata__multilingual_e5_small__{candidate}",
            }
            for candidate in ("decision_tree", "linear_svm", "mlp", "xgboost")
        ],
    }
    config["protocol_scope"] = {
        "classification_semantic_families_per_class_before_router": 100,
        "classification_post_router_semantic_families_by_class": {
            "DEMO": 100, "OBRA": 40, "SOB_DEMANDA": 60, "TRIAGEM_MANUAL": 24,
        },
        "classification_source_dependency_groups_per_class": 20,
        "classification_independent_groups_per_class": 20,
        "dedup_source_dependency_groups": 31,
        "dedup_positive_challenges": 186,
        "dedup_complete_negative_challenges": 97,
        "dedup_critical_negative_challenges": 75,
        "semantic_family_is_coverage_not_effective_sample_size": True,
        "inference_method": "known_grammar_conditional",
        "grammar_sensitivity_field": "grammar_family_sha256",
        "fixed_router_scope": "classification_model_rows conditional comparison",
        "fixed_embedding": "multilingual_e5_small",
        "classification_representation": "hybrid",
        "deduplication_representation": "hybrid_metadata",
        "locked_challenge_used_during_selection": False,
        "proxy_labels_only": True,
    }
    return config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    payload = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"output": str(args.output.resolve()), "sha256": sha256_file(args.output), "combinations": 10}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
