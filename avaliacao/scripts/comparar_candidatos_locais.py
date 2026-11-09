from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

import joblib
import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from avaliacao.scripts import treinar_modelo_local as training  # noqa: E402
from local_ai.artifacts import LoadedHybridBundle  # noqa: E402
from local_ai.backends import EmbeddingProvider  # noqa: E402
from local_ai.config import Settings  # noqa: E402
from local_ai.extraction import (  # noqa: E402
    classification_operational_information_sufficient,
    deterministic_extract,
)
from local_ai.hybrid import HybridBundleRuntime  # noqa: E402


SCHEMA = "projeto-ic-local-candidate-development-comparison-v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_runtime(manifest_path: Path) -> tuple[HybridBundleRuntime, dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bundle_entry = manifest.get("bundle") or {}
    relative = str(bundle_entry.get("path") or "local_hybrid_bundle.joblib")
    bundle_path = (manifest_path.parent / relative).resolve()
    expected = str(
        bundle_entry.get("sha256")
        or manifest.get("sha256")
        or manifest.get("bundle_sha256")
        or ""
    ).lower()
    actual = sha256(bundle_path)
    if not expected or expected != actual:
        raise ValueError(f"Checksum inválido para {bundle_path}: {actual} != {expected}")
    content = joblib.load(bundle_path)
    loaded = LoadedHybridBundle(
        version=str(content.get("bundle_version") or manifest.get("bundle_version") or ""),
        path=bundle_path,
        manifest_path=manifest_path,
        manifest=manifest,
        content=content,
    )
    return HybridBundleRuntime(loaded), {
        "manifest": str(manifest_path),
        "manifest_file_sha256": sha256(manifest_path),
        "bundle": str(bundle_path),
        "bundle_sha256": actual,
        "bundle_version": loaded.version,
    }


def classification_metrics(
    runtime: HybridBundleRuntime,
    cases: Sequence[dict[str, Any]],
    vectors: dict[str, list[float]],
) -> tuple[dict[str, Any], list[str], np.ndarray]:
    labels = list(training.CLASS_LABELS)
    gold: list[str] = []
    predicted: list[str] = []
    probabilities: list[list[float]] = []
    automatic: list[bool] = []
    for case in cases:
        text = training.model_text(case)
        result = runtime.classify(text, vectors[text], structured_values=[])
        decision = str(result["semantic_class"])
        operational = classification_operational_information_sufficient(
            deterministic_extract(case, 6000)
        )
        gold.append(str(case["expected_classification"]).upper())
        predicted.append(decision)
        probabilities.append([float(result["probabilities"][label]) for label in labels])
        automatic.append(
            bool(operational and not result["abstained"] and decision != "TRIAGEM_MANUAL")
        )
    probability_array = np.asarray(probabilities, dtype=np.float64)
    automatic_array = np.asarray(automatic, dtype=bool)
    correct = np.asarray(predicted) == np.asarray(gold)
    covered = int(automatic_array.sum())
    errors = int(np.sum((~correct) & automatic_array))
    return {
        "records": len(cases),
        "accuracy": float(accuracy_score(gold, predicted)),
        "macro_f1": float(f1_score(gold, predicted, average="macro", zero_division=0)),
        "confusion_matrix": {
            "labels": labels,
            "values": confusion_matrix(gold, predicted, labels=labels).astype(int).tolist(),
        },
        "classification_threshold": runtime.classification_threshold,
        "automatic_records": covered,
        "automatic_coverage": covered / len(cases) if cases else 0.0,
        "automatic_errors": errors,
        "automatic_risk": errors / covered if covered else None,
        "probability_metrics": training._classification_probability_metrics(
            probability_array, gold, labels
        ),
    }, predicted, probability_array


def classification_pipeline_metrics(
    runtime: HybridBundleRuntime,
    full_cases: Sequence[dict[str, Any]],
    model_cases: Sequence[dict[str, Any]],
    model_probabilities: np.ndarray,
    *,
    location_gate: str,
) -> dict[str, Any]:
    probability_by_case = {
        str(case["case_id"]): model_probabilities[index]
        for index, case in enumerate(model_cases)
    }
    gold: list[str] = []
    predicted: list[str] = []
    automatic: list[bool] = []
    paths: list[str] = []
    operational_flags: list[bool] = []
    for case in full_cases:
        extracted = deterministic_extract(case, 6000)
        route = training.classification_pre_model_path(extracted)
        if location_gate == "strict_exact_or_explicit_global":
            operational = bool(
                extracted.get("informacao_suficiente_classificacao")
                and extracted.get("localizacao_atendivel_politica_especializada")
                and not extracted.get("contradicoes")
            )
        elif location_gate == "exact_or_unique_named_or_explicit_global":
            operational = classification_operational_information_sufficient(extracted)
        else:
            raise ValueError(f"Gate de localização desconhecido: {location_gate}")
        if route == "deterministic_specialized_asset":
            decision = "SOB_DEMANDA"
            covered = operational
        elif route in {
            "deterministic_insufficient_information",
            "deterministic_contradiction",
            "deterministic_out_of_scope",
        }:
            decision = "TRIAGEM_MANUAL"
            covered = False
        else:
            row = probability_by_case[str(case["case_id"])]
            winner_index = int(np.argmax(row))
            decision = training.CLASS_LABELS[winner_index]
            confidence = float(row[winner_index])
            abstained = bool(
                decision != "TRIAGEM_MANUAL"
                and confidence < runtime.classification_threshold
            )
            covered = bool(
                operational and not abstained and decision != "TRIAGEM_MANUAL"
            )
            route = "hybrid_model_abstention" if abstained else "hybrid_model"
        gold.append(str(case["expected_classification"]).upper())
        predicted.append(decision)
        automatic.append(covered)
        operational_flags.append(operational)
        paths.append(str(route))
    automatic_array = np.asarray(automatic, dtype=bool)
    correct = np.asarray(predicted) == np.asarray(gold)
    path_metrics: dict[str, Any] = {}
    for path in sorted(set(paths)):
        mask = np.asarray([value == path for value in paths], dtype=bool)
        path_metrics[path] = {
            "records": int(mask.sum()),
            "semantic_errors": int(np.sum((~correct) & mask)),
            "automatic_records": int(np.sum(automatic_array & mask)),
            "automatic_errors": int(np.sum((~correct) & automatic_array & mask)),
        }
    covered = int(automatic_array.sum())
    errors = int(np.sum((~correct) & automatic_array))
    return {
        "location_gate": location_gate,
        "records": len(full_cases),
        "semantic_accuracy": float(accuracy_score(gold, predicted)),
        "semantic_macro_f1": float(
            f1_score(gold, predicted, average="macro", zero_division=0)
        ),
        "operational_information_sufficient_records": int(sum(operational_flags)),
        "operational_information_insufficient_records": int(
            len(operational_flags) - sum(operational_flags)
        ),
        "automatic_records": covered,
        "automatic_coverage": covered / len(full_cases) if full_cases else 0.0,
        "automatic_errors": errors,
        "automatic_risk": errors / covered if covered else None,
        "by_decision_path": path_metrics,
    }


def _sets_equivalent(left: set[str], right: set[str]) -> bool:
    if not left or not right:
        return False
    for a in left:
        a_tokens = set(a.split())
        for b in right:
            b_tokens = set(b.split())
            if a == b or (
                a_tokens
                and b_tokens
                and (a_tokens <= b_tokens or b_tokens <= a_tokens)
            ):
                return True
    return False


def dedup_metrics(
    runtime: HybridBundleRuntime,
    pairs: Sequence[tuple[dict[str, Any], dict[str, Any], str]],
    vectors: dict[str, list[float]],
) -> tuple[dict[str, Any], list[str], np.ndarray]:
    gold: list[str] = []
    decisions: list[str] = []
    probabilities: list[list[float]] = []
    for current, reference, label in pairs:
        current_text = training.model_text(current)
        reference_text = training.model_text(reference)
        result = runtime.deduplicate(
            current,
            reference,
            current_text,
            reference_text,
            vectors[current_text],
            vectors[reference_text],
        )
        probability = float(result["duplicate_probability"])
        gold.append(label)
        probabilities.append([1.0 - probability, probability])
        decisions.append(
            "DUPLICADO"
            if probability >= runtime.dedup_threshold
            else "NAO_DUPLICADO"
            if probability <= runtime.dedup_negative_threshold
            else "ABSTENCAO"
        )
    covered = np.asarray([value != "ABSTENCAO" for value in decisions], dtype=bool)
    correct = np.asarray(decisions) == np.asarray(gold)
    gold_positive = np.asarray([value == "DUPLICADO" for value in gold], dtype=bool)
    predicted_positive = np.asarray([value == "DUPLICADO" for value in decisions], dtype=bool)
    tp = int(np.sum(covered & gold_positive & predicted_positive))
    fp = int(np.sum(covered & ~gold_positive & predicted_positive))
    fn = int(np.sum(covered & gold_positive & ~predicted_positive))
    tn = int(np.sum(covered & ~gold_positive & ~predicted_positive))
    array = np.asarray(probabilities, dtype=np.float64)
    return {
        "records": len(pairs),
        "positive_records": int(gold_positive.sum()),
        "negative_records": int((~gold_positive).sum()),
        "positive_threshold": runtime.dedup_threshold,
        "negative_threshold": runtime.dedup_negative_threshold,
        "covered": int(covered.sum()),
        "coverage": float(covered.mean()) if len(covered) else 0.0,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall_covered": tp / (tp + fn) if tp + fn else None,
        "false_positive_rate": fp / (fp + tn) if fp + tn else None,
        "false_negative_rate": fn / (fn + tp) if fn + tp else None,
        "negative_predictive_value": tn / (tn + fn) if tn + fn else None,
        "weighted_covered_error_fn5_fp1": (5 * fn + fp) / int(covered.sum())
        if covered.any()
        else None,
        "probability_metrics": training._dedup_probability_metrics(
            array, gold, training.DEDUP_LABELS
        ),
    }, decisions, array


def dedup_pipeline_metrics(
    runtime: HybridBundleRuntime,
    pairs: Sequence[tuple[dict[str, Any], dict[str, Any], str]],
    model_probabilities: np.ndarray,
) -> tuple[dict[str, Any], list[str]]:
    gold: list[str] = []
    decisions: list[str] = []
    gates: dict[str, int] = {}
    for index, (current, reference, expected) in enumerate(pairs):
        probability = float(model_probabilities[index, 1])
        current_extraction = deterministic_extract(current, 6000)
        reference_extraction = deterministic_extract(reference, 6000)
        current_locations = set(current_extraction.get("localizacoes") or [])
        reference_locations = set(reference_extraction.get("localizacoes") or [])
        hard_blocks: list[str] = []
        if not current_locations or not reference_locations:
            probability = min(probability, 0.35)
            hard_blocks.append("localizacao_insuficiente")
        elif not _sets_equivalent(current_locations, reference_locations):
            probability = min(probability, 0.05)
            hard_blocks.append("localizacao_divergente")
        current_asset = current_extraction.get("ativo")
        reference_asset = reference_extraction.get("ativo")
        if current_asset and reference_asset and current_asset != reference_asset:
            probability = min(probability, 0.20)
            hard_blocks.append("elemento_divergente")
        if not current_asset or not reference_asset:
            probability = min(probability, 0.35)
            hard_blocks.append("problema_insuficiente")
        for gate in hard_blocks:
            gates[gate] = gates.get(gate, 0) + 1
        review_blocks = {
            "localizacao_insuficiente",
            "problema_insuficiente",
        }.intersection(hard_blocks)
        threshold_abstention = bool(
            runtime.dedup_negative_threshold
            < probability
            < runtime.dedup_threshold
        )
        if review_blocks or threshold_abstention:
            decision = "ABSTENCAO"
        else:
            duplicated = bool(
                probability >= runtime.dedup_threshold and not hard_blocks
            )
            decision = "DUPLICADO" if duplicated else "NAO_DUPLICADO"
        gold.append(expected)
        decisions.append(decision)
    covered = np.asarray([value != "ABSTENCAO" for value in decisions], dtype=bool)
    positive = np.asarray([value == "DUPLICADO" for value in gold], dtype=bool)
    predicted_positive = np.asarray(
        [value == "DUPLICADO" for value in decisions], dtype=bool
    )
    tp = int(np.sum(covered & positive & predicted_positive))
    fp = int(np.sum(covered & ~positive & predicted_positive))
    fn = int(np.sum(covered & positive & ~predicted_positive))
    tn = int(np.sum(covered & ~positive & ~predicted_positive))
    return {
        "records": len(pairs),
        "reference_identity_gate": "assumed_valid_from_synthetic_case_id",
        "covered": int(covered.sum()),
        "coverage": float(covered.mean()) if len(covered) else 0.0,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall_covered": tp / (tp + fn) if tp + fn else None,
        "false_positive_rate": fp / (fp + tn) if fp + tn else None,
        "false_negative_rate": fn / (fn + tp) if fn + tp else None,
        "negative_predictive_value": tn / (tn + fn) if tn + fn else None,
        "weighted_covered_error_fn5_fp1": (5 * fn + fp) / int(covered.sum())
        if covered.any()
        else None,
        "gate_counts": gates,
    }, decisions


def paired_counts(
    gold: Sequence[str], baseline: Sequence[str], candidate: Sequence[str]
) -> dict[str, int]:
    baseline_correct = np.asarray(baseline) == np.asarray(gold)
    candidate_correct = np.asarray(candidate) == np.asarray(gold)
    return {
        "both_correct": int(np.sum(baseline_correct & candidate_correct)),
        "both_wrong": int(np.sum(~baseline_correct & ~candidate_correct)),
        "baseline_only_correct": int(np.sum(baseline_correct & ~candidate_correct)),
        "candidate_only_correct": int(np.sum(~baseline_correct & candidate_correct)),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compara dois bundles locais no mesmo split de desenvolvimento."
    )
    parser.add_argument("--dados", type=Path, required=True)
    parser.add_argument("--baseline-manifest", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--saida", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260715)
    parser.add_argument("--validation-fraction", type=float, default=0.25)
    parser.add_argument("--group-field", default="auto")
    parser.add_argument("--embedding-model-path", type=Path, required=True)
    parser.add_argument(
        "--embedding-model-id",
        default="ibm-granite/granite-embedding-97m-multilingual-r2",
    )
    parser.add_argument(
        "--embedding-model-revision",
        default="835ad14087e140460703cf0fae09f97d469d65c2",
    )
    parser.add_argument("--cpu-threads", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    started = time.perf_counter()
    cases = load_jsonl(args.dados.resolve())
    _, calibration, split = training.grouped_development_split(
        cases,
        validation_fraction=args.validation_fraction,
        seed=args.seed,
        group_field=args.group_field,
    )
    classification_cases = training.classification_model_rows(calibration)
    pairs = training.dedup_pairs(calibration)
    baseline_runtime, baseline_info = load_runtime(args.baseline_manifest.resolve())
    candidate_runtime, candidate_info = load_runtime(args.candidate_manifest.resolve())
    if baseline_runtime.embedding_dimension != candidate_runtime.embedding_dimension:
        raise ValueError("Bundles usam dimensões de embedding diferentes")
    settings = replace(
        Settings.from_env(),
        mode="production",
        preferred_embedding_model=args.embedding_model_id,
        embedding_model_path=str(args.embedding_model_path.resolve()),
        embedding_model_revision=args.embedding_model_revision,
        embedding_backend="pytorch_fp32",
        allow_model_download=False,
        cpu_threads=args.cpu_threads,
        max_embed_batch=8,
    )
    texts = list(
        dict.fromkeys(
            [training.model_text(case) for case in classification_cases]
            + [
                training.model_text(case)
                for pair in pairs
                for case in pair[:2]
            ]
        )
    )
    provider = EmbeddingProvider(settings, {})
    encoded, backend = provider.encode(texts)
    vectors = dict(zip(texts, encoded))
    baseline_class, baseline_class_predictions, baseline_class_probabilities = classification_metrics(
        baseline_runtime, classification_cases, vectors
    )
    candidate_class, candidate_class_predictions, candidate_class_probabilities = classification_metrics(
        candidate_runtime, classification_cases, vectors
    )
    full_classification_cases = training.classification_rows(calibration)
    baseline_class["pipeline_before_location_gate"] = classification_pipeline_metrics(
        baseline_runtime,
        full_classification_cases,
        classification_cases,
        baseline_class_probabilities,
        location_gate="strict_exact_or_explicit_global",
    )
    baseline_class["pipeline_after_location_gate"] = classification_pipeline_metrics(
        baseline_runtime,
        full_classification_cases,
        classification_cases,
        baseline_class_probabilities,
        location_gate="exact_or_unique_named_or_explicit_global",
    )
    candidate_class["pipeline_before_location_gate"] = classification_pipeline_metrics(
        candidate_runtime,
        full_classification_cases,
        classification_cases,
        candidate_class_probabilities,
        location_gate="strict_exact_or_explicit_global",
    )
    candidate_class["pipeline_after_location_gate"] = classification_pipeline_metrics(
        candidate_runtime,
        full_classification_cases,
        classification_cases,
        candidate_class_probabilities,
        location_gate="exact_or_unique_named_or_explicit_global",
    )
    baseline_dedup, baseline_dedup_predictions, baseline_dedup_probabilities = dedup_metrics(
        baseline_runtime, pairs, vectors
    )
    candidate_dedup, candidate_dedup_predictions, candidate_dedup_probabilities = dedup_metrics(
        candidate_runtime, pairs, vectors
    )
    baseline_dedup_pipeline, baseline_dedup_pipeline_predictions = dedup_pipeline_metrics(
        baseline_runtime, pairs, baseline_dedup_probabilities
    )
    candidate_dedup_pipeline, candidate_dedup_pipeline_predictions = dedup_pipeline_metrics(
        candidate_runtime, pairs, candidate_dedup_probabilities
    )
    baseline_dedup["full_pipeline"] = baseline_dedup_pipeline
    candidate_dedup["full_pipeline"] = candidate_dedup_pipeline
    class_gold = [str(case["expected_classification"]).upper() for case in classification_cases]
    dedup_gold = [pair[2] for pair in pairs]
    report = {
        "schema": SCHEMA,
        "scientific_result": False,
        "confirmatory_eligible": False,
        "development_only": True,
        "calibration_resubstitution": True,
        "warning": (
            "O modelo final já foi calibrado neste pool; esta comparação é gate de "
            "não regressão e não uma estimativa confirmatória de generalização."
        ),
        "test_data_used": False,
        "primary33_used": False,
        "dataset": {
            "path": str(args.dados.resolve()),
            "sha256": sha256(args.dados.resolve()),
            "total_records": len(cases),
        },
        "split": split,
        "same_split_records": {
            "classification_model_only": len(classification_cases),
            "deduplication_pairs": len(pairs),
        },
        "embedding": backend.as_dict(),
        "baseline": {
            **baseline_info,
            "classification_model_only": baseline_class,
            "deduplication_model_only": baseline_dedup,
        },
        "candidate": {
            **candidate_info,
            "classification_model_only": candidate_class,
            "deduplication_model_only": candidate_dedup,
        },
        "paired_correctness": {
            "classification": paired_counts(
                class_gold, baseline_class_predictions, candidate_class_predictions
            ),
            "deduplication_thresholded": paired_counts(
                dedup_gold, baseline_dedup_predictions, candidate_dedup_predictions
            ),
            "deduplication_full_pipeline": paired_counts(
                dedup_gold,
                baseline_dedup_pipeline_predictions,
                candidate_dedup_pipeline_predictions,
            ),
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
