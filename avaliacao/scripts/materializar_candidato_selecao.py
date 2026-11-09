from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
for entry in (PROJECT_ROOT, SCRIPT_DIR):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import selecionar_modelos_supervisionados as selection  # noqa: E402
import treinar_modelo_local as training  # noqa: E402
from local_ai.inference import SERVICE_VERSION  # noqa: E402


MODEL_VERSION = "local-hybrid-v1.9.1"
BUNDLE_VERSION = "local-hybrid-bundle-v1.9.1"
PIPELINE_VERSION = "local-ai-hybrid-pipeline-v1.9.1"
GENERATION_PROFILE = (
    "selection-v1.3-granite97m-hybrid-svm-logreg-single-refit-v1.9.1"
)
REQUIRED_MATRIX = {"classification": 35, "deduplication": 55}


class MaterializationGuardError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MaterializationGuardError(f"JSON inválido ou ausente: {path}") from exc
    if not isinstance(value, dict):
        raise MaterializationGuardError(f"Objeto JSON esperado: {path}")
    return value


def prepare_output_dir(path: Path) -> None:
    if path.exists():
        if not path.is_dir() or any(path.iterdir()):
            raise MaterializationGuardError(
                f"Saída deve ser um diretório novo e vazio: {path}"
            )
        return
    path.mkdir(parents=True, exist_ok=False)


def validated_candidates(
    selection_dir: Path,
    *,
    allow_underpowered: bool,
    override_dedup_candidate_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    validation = load_json(selection_dir / "validacao_resultados.json")
    if validation.get("status") != "VALID":
        raise MaterializationGuardError("A seleção não possui validação independente VALID")
    if validation.get("development_only") is not True:
        raise MaterializationGuardError("A materialização exige seleção de desenvolvimento")
    if validation.get("confirmatory_eligible") is not False:
        raise MaterializationGuardError("Seleção foi marcada incorretamente como confirmatória")
    if int(validation.get("configurations", 0)) != sum(REQUIRED_MATRIX.values()):
        raise MaterializationGuardError("Matriz validada não contém 90 configurações")
    for task, expected in REQUIRED_MATRIX.items():
        if int(validation.get(f"{task}_configurations", 0)) != expected:
            raise MaterializationGuardError(
                f"Contagem validada divergente para {task}: esperado {expected}"
            )

    results = load_json(selection_dir / "resultados.json")
    if results.get("run_fingerprint") != validation.get("run_fingerprint"):
        raise MaterializationGuardError("Fingerprint diverge entre resultado e validação")
    if results.get("protocol_sha256") != validation.get("protocol_sha256"):
        raise MaterializationGuardError("Hash do protocolo diverge entre artefatos")
    if results.get("development_only") is not True:
        raise MaterializationGuardError("Resultado não está marcado como desenvolvimento")
    if results.get("confirmatory_eligible") is not False:
        raise MaterializationGuardError("Resultado não confirmatório foi promovido indevidamente")

    winners = results.get("winners") or {}
    provisional = results.get("provisional_point_candidates") or {}
    candidates: dict[str, dict[str, Any]] = {}
    ranking = {
        str(row.get("combination_id")): row
        for row in results.get("ranking", [])
        if isinstance(row, dict)
    }
    result_rows = {
        str(row.get("combination_id")): row
        for row in results.get("results", [])
        if isinstance(row, dict)
    }
    for task in REQUIRED_MATRIX:
        candidate_id = winners.get(task)
        source = "CONFIDENCE_QUALIFIED_WINNER"
        if task == "deduplication" and override_dedup_candidate_id:
            candidate_id = override_dedup_candidate_id
            source = "OVERRIDE_DEVELOPMENT_CANDIDATE"
        elif not candidate_id:
            candidate_id = provisional.get(task)
            source = "PROVISIONAL_POINT_CANDIDATE"
            if candidate_id and not allow_underpowered:
                raise MaterializationGuardError(
                    "A seleção produziu somente candidato UNDERPOWERED; repita com "
                    "--allow-underpowered-development-candidate para materializá-lo "
                    "sem promovê-lo a vencedor científico"
                )
        if not candidate_id:
            raise MaterializationGuardError(f"Nenhum candidato disponível para {task}")
        rank = ranking.get(str(candidate_id))
        result = result_rows.get(str(candidate_id))
        if not rank or not result:
            raise MaterializationGuardError(f"Candidato ausente no ranking/resultados: {candidate_id}")
        if result.get("status") != "COMPLETED_DEVELOPMENT_OOF":
            raise MaterializationGuardError(f"Candidato incompleto: {candidate_id}")
        if source == "CONFIDENCE_QUALIFIED_WINNER":
            if rank.get("confidence_qualified") is not True:
                raise MaterializationGuardError("Vencedor não está qualificado por confiança")
        else:
            if (
                rank.get("evidence_status") != "UNDERPOWERED"
                or rank.get("provisional_point_eligible") is not True
            ):
                raise MaterializationGuardError("Candidato provisório não é UNDERPOWERED elegível")
        candidates[task] = {"rank": rank, "result": result, "source": source}

    protocol = load_json(selection_dir / "protocolo_congelado.json")
    if protocol.get("protocol_sha256") != validation.get("protocol_sha256"):
        raise MaterializationGuardError("Protocolo congelado diverge da validação")
    config = protocol.get("config")
    if not isinstance(config, dict):
        raise MaterializationGuardError("Configuração ausente no protocolo congelado")
    return validation, results, config, candidates


def validate_runtime_compatibility(candidates: dict[str, dict[str, Any]]) -> str:
    classification = candidates["classification"]["rank"]
    deduplication = candidates["deduplication"]["rank"]
    if classification.get("representation") != "hybrid":
        raise MaterializationGuardError("Runtime v1.9 suporta classificação final hybrid")
    if deduplication.get("representation") != "hybrid":
        raise MaterializationGuardError("Runtime v1.9 suporta deduplicação final hybrid")
    if classification.get("classifier") != "linear_svm":
        raise MaterializationGuardError("Classificador final esperado é linear_svm")
    if deduplication.get("classifier") != "logistic_regression":
        raise MaterializationGuardError("Classificador final de deduplicação esperado é logreg")
    embedding_ids = {
        str(classification.get("embedding") or ""),
        str(deduplication.get("embedding") or ""),
    }
    if len(embedding_ids) != 1 or "" in embedding_ids:
        raise MaterializationGuardError(
            "O runtime atual exige o mesmo embedding nas duas tarefas"
        )
    return next(iter(embedding_ids))


def oof_rows(selection_dir: Path, combination_id: str) -> list[dict[str, str]]:
    path = selection_dir / "predicoes_oof.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row.get("combination_id") == combination_id
        ]
    if not rows:
        raise MaterializationGuardError(f"Predições OOF ausentes: {combination_id}")
    unit_ids = [str(row.get("unit_id") or "") for row in rows]
    if not all(unit_ids) or len(unit_ids) != len(set(unit_ids)):
        raise MaterializationGuardError("Predições OOF possuem unit_id ausente/duplicado")
    return rows


def derive_operating_points(
    selection_dir: Path,
    candidates: dict[str, dict[str, Any]],
    config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    class_id = candidates["classification"]["rank"]["combination_id"]
    class_rows = oof_rows(selection_dir, class_id)
    class_probabilities = np.asarray(
        [
            [
                float(row["p_obra"]),
                float(row["p_demo"]),
                float(row["p_sob_demanda"]),
                float(row["p_triagem_manual"]),
            ]
            for row in class_rows
        ],
        dtype=np.float64,
    )
    class_labels = [selection.CLASS_LABELS.index(row["gold"]) for row in class_rows]
    class_policy = selection.select_classification_policy(
        class_probabilities,
        class_labels,
        max_risk=float(
            config["operating_policy"]["classification_max_selective_risk"]
        ),
        min_coverage=float(config["operating_policy"]["classification_min_coverage"]),
        obra_min_confidence=float(
            config["operating_policy"]["classification_obra_min_confidence"]
        ),
    )
    if class_policy.get("eligible") is not True or class_policy.get("threshold") is None:
        raise MaterializationGuardError("Nenhum limiar classificatório global OOF elegível")

    dedup_id = candidates["deduplication"]["rank"]["combination_id"]
    dedup_rows = oof_rows(selection_dir, dedup_id)
    dedup_probabilities = np.asarray(
        [
            [float(row["p_nao_duplicado"]), float(row["p_duplicado"])]
            for row in dedup_rows
        ],
        dtype=np.float64,
    )
    dedup_labels = [selection.DEDUP_LABELS.index(row["gold"]) for row in dedup_rows]
    dedup_policy = selection.select_dedup_policy(
        dedup_probabilities,
        dedup_labels,
        config["operating_policy"],
        false_negative_cost=float(
            config["objectives"]["deduplication_false_negative_cost"]
        ),
        false_positive_cost=float(
            config["objectives"]["deduplication_false_positive_cost"]
        ),
    )
    if dedup_policy.get("eligible") is not True:
        raise MaterializationGuardError("Nenhum limiar de deduplicação global OOF elegível")
    return (
        {key: value for key, value in class_policy.items() if key != "curve"},
        {key: value for key, value in dedup_policy.items() if key != "curve"},
    )


def mode_model_parameters(result: dict[str, Any]) -> dict[str, Any]:
    parameters = selection.mode_parameters(result)
    return {
        key.removeprefix("model__"): value
        for key, value in parameters.items()
    }


def grouped_calibrated_model(
    *,
    matrix: Any,
    labels: Sequence[str],
    numeric_labels: Sequence[int],
    groups: Sequence[str],
    candidate: dict[str, Any],
    config: dict[str, Any],
    task: str,
) -> tuple[CalibratedClassifierCV, dict[str, Any]]:
    classifier_id = str(candidate["rank"]["classifier"])
    class_count = len(selection.CLASS_LABELS) if task == "classification" else 2
    model, _, weighted = selection.make_classifier(
        classifier_id,
        specification=selection.classifier_spec(config, classifier_id),
        seed=int(config["cross_validation"]["outer_seed"]),
        class_count=class_count,
    )
    if weighted:
        raise MaterializationGuardError(
            "Materializador v1.9 não permite finalista que exija sample_weight"
        )
    parameters = mode_model_parameters(candidate["result"])
    if parameters:
        model.set_params(**parameters)
    splits = selection.safe_stratified_group_splits(
        numeric_labels,
        groups,
        n_splits=int(config["cross_validation"]["outer_folds"]),
        seed=int(config["cross_validation"]["outer_seed"]),
        context=f"materialization/{task}",
    )
    calibrated = CalibratedClassifierCV(
        model,
        method=str(config["cross_validation"]["calibration_method"]),
        cv=splits,
        # As probabilidades de calibração continuam sendo obtidas fora da
        # amostra por CV agrupada. Na inferência, um único estimador refitado em
        # todo o treino substitui a média de cinco cópias, reduzindo latência e
        # RAM sem usar holdout ou alterar os candidatos selecionados.
        ensemble=False,
        n_jobs=1,
    )
    calibrated.fit(matrix, np.asarray(labels, dtype=object))
    operational_estimators = len(
        getattr(calibrated, "calibrated_classifiers_", [])
    )
    if operational_estimators != 1:
        raise MaterializationGuardError(
            "Calibração final deve materializar exatamente um estimador operacional"
        )
    audit = []
    group_array = np.asarray(groups, dtype=object)
    for fold, (fit_index, calibration_index) in enumerate(splits):
        fit_groups = sorted(set(group_array[fit_index].tolist()))
        calibration_groups = sorted(set(group_array[calibration_index].tolist()))
        overlap = sorted(set(fit_groups) & set(calibration_groups))
        if overlap:
            raise MaterializationGuardError("Sobreposição de grupos na calibração final")
        audit.append(
            {
                "fold": fold,
                "fit_records": len(fit_index),
                "calibration_records": len(calibration_index),
                "fit_groups": len(fit_groups),
                "calibration_groups": len(calibration_groups),
                "group_overlap": 0,
                "fit_groups_sha256": canonical_sha256(fit_groups),
                "calibration_groups_sha256": canonical_sha256(calibration_groups),
            }
        )
    return calibrated, {
        "classifier": classifier_id,
        "parameters": parameters,
        "calibration_method": str(config["cross_validation"]["calibration_method"]),
        "calibration_strategy": "five_fold_group_oof_single_full_refit",
        "operational_inference_estimators": operational_estimators,
        "folds": audit,
    }


def materialize(
    selection_dir: Path,
    output_dir: Path,
    *,
    allow_underpowered: bool,
    dedup_candidate_id: str | None = None,
) -> tuple[Path, Path]:
    selection_dir = selection_dir.resolve()
    validation, results, config, candidates = validated_candidates(
        selection_dir,
        allow_underpowered=allow_underpowered,
        override_dedup_candidate_id=dedup_candidate_id,
    )
    embedding_id = validate_runtime_compatibility(candidates)
    class_policy, dedup_policy = derive_operating_points(
        selection_dir, candidates, config
    )
    dataset_path = (PROJECT_ROOT / config["dataset"]["path"]).resolve()
    if sha256_file(dataset_path) != config["dataset"]["sha256"]:
        raise MaterializationGuardError("Corpus de desenvolvimento diverge do protocolo")
    cases = training.load_jsonl(dataset_path)
    training.validate_source_role(dataset_path, cases, role="TRAIN")
    training.validate_labels(cases, str(dataset_path))

    embedding_config = next(
        item for item in config["embeddings"] if item["id"] == embedding_id
    )
    spec = selection.EmbeddingSpec(
        id=embedding_config["id"],
        repository=embedding_config["repository"],
        revision=embedding_config["revision"],
        local_path=(PROJECT_ROOT / embedding_config["local_path"]).resolve(),
        tree_sha256=embedding_config["tree_sha256"],
        dimension=int(embedding_config["dimension"]),
        symmetric_prefix=embedding_config["symmetric_prefix"],
        retrieval_query_prefix=embedding_config["retrieval_query_prefix"],
        retrieval_passage_prefix=embedding_config["retrieval_passage_prefix"],
    )
    class_cases = training.classification_model_rows(cases)
    pairs = training.dedup_pairs(cases)
    symmetric_texts = list(
        dict.fromkeys(
            [training.model_text(case) for case in class_cases]
            + [training.model_text(case) for pair in pairs for case in pair[:2]]
        )
    )
    embedding_maps, embedding_runtime = selection.encode_model_roles(
        spec,
        dataset_sha256=config["dataset"]["sha256"],
        role_inputs={"symmetric": (symmetric_texts, spec.symmetric_prefix)},
        cache_root=PROJECT_ROOT / "local_ai" / "runtime" / "selection_cache",
        batch_size=int(config["hardware"]["embedding_batch_size"]),
        cpu_threads=int(config["hardware"]["cpu_threads"]),
        force=False,
    )
    (
        class_samples,
        class_numeric_labels,
        class_groups,
        pair_samples,
        pair_numeric_labels,
        pair_groups,
    ) = selection.build_samples(
        cases,
        embedding_map=embedding_maps["symmetric"],
        classification_group_field=config["dataset"]["classification_group_field"],
        deduplication_group_field=config["dataset"]["deduplication_group_field"],
    )

    class_features = selection.TextFeatureBuilder(
        use_tfidf=True, use_embedding=True, embedding_dimension=spec.dimension
    )
    class_matrix = class_features.fit_transform(class_samples).tocsr()
    pair_features = selection.PairFeatureBuilder(
        use_tfidf=True,
        use_embedding=True,
        use_metadata=False,
        embedding_dimension=spec.dimension,
    )
    pair_matrix = pair_features.fit_transform(pair_samples).tocsr()
    class_labels = [selection.CLASS_LABELS[index] for index in class_numeric_labels]
    pair_labels = [selection.DEDUP_LABELS[index] for index in pair_numeric_labels]
    classification_model, classification_training = grouped_calibrated_model(
        matrix=class_matrix,
        labels=class_labels,
        numeric_labels=class_numeric_labels,
        groups=class_groups,
        candidate=candidates["classification"],
        config=config,
        task="classification",
    )
    dedup_model, dedup_training = grouped_calibrated_model(
        matrix=pair_matrix,
        labels=pair_labels,
        numeric_labels=pair_numeric_labels,
        groups=pair_groups,
        candidate=candidates["deduplication"],
        config=config,
        task="deduplication",
    )

    output_dir = output_dir.resolve()
    prepare_output_dir(output_dir)
    bundle_path = output_dir / "local_hybrid_bundle.joblib"
    manifest_path = output_dir / "local_hybrid_manifest.json"
    source_paths = {
        "materializer": Path(__file__).resolve(),
        "selection_executor": SCRIPT_DIR / "selecionar_modelos_supervisionados.py",
        "training_helpers": SCRIPT_DIR / "treinar_modelo_local.py",
        "runtime": PROJECT_ROOT / "local_ai" / "hybrid.py",
        "inference": PROJECT_ROOT / "local_ai" / "inference.py",
        "text": PROJECT_ROOT / "local_ai" / "text.py",
    }
    source_hashes = {name: sha256_file(path) for name, path in source_paths.items()}
    thresholds = {
        "classification": float(class_policy["threshold"]),
        "classification_obra": float(class_policy["obra_threshold"]),
        "deduplication": float(dedup_policy["positive_threshold"]),
        "deduplication_negative": float(dedup_policy["negative_threshold"]),
        "deduplication_reference_margin": 0.035,
        "approved": True,
        "selection_source": "validated_outer_oof_global_policy",
        "approval_scope": "underpowered_development_candidate_for_engineering_comparison",
        "approval_uses_point_estimates": True,
        "confidence_qualified": False,
        "abstention_is_not_triagem_manual": True,
        "error_costs": {
            "false_negative": float(
                config["objectives"]["deduplication_false_negative_cost"]
            ),
            "false_positive": float(
                config["objectives"]["deduplication_false_positive_cost"]
            ),
        },
    }
    feature_schema = {
        "classification": {
            "text_fields": list(training.TEXT_FIELDS),
            "layout": ["tfidf_word_char", "embedding"],
            "structured_features": [],
            "block_order": ["tfidf", "embedding"],
        },
        "deduplication": {
            "pair_order": ["current", "reference"],
            "text_fields": list(training.TEXT_FIELDS),
            "representation": "hybrid",
            "uses_metadata": False,
            "block_order": ["tfidf", "embedding"],
            "layout": [
                "tfidf_abs_difference",
                "tfidf_elementwise_product",
                "tfidf_cosine",
                "embedding_abs_difference",
                "embedding_elementwise_product",
                "embedding_cosine",
            ],
        },
    }
    candidate_summary = {
        task: {
            "combination_id": value["rank"]["combination_id"],
            "selection_rank": value["rank"]["rank"],
            "selection_source": value["source"],
            "evidence_status": value["rank"]["evidence_status"],
            "exclusion_reasons": value["rank"].get("exclusion_reasons", []),
            "representation": value["rank"]["representation"],
            "embedding": value["rank"]["embedding"],
            "classifier": value["rank"]["classifier"],
            "development_metrics": value["result"]["metrics"],
        }
        for task, value in candidates.items()
    }
    embedding = {
        "backend": "granite",
        "id": spec.id,
        "dimension": spec.dimension,
        "model_id": spec.repository,
        "model_revision": spec.revision,
        "model_tree_sha256": spec.tree_sha256,
        "symmetric_prefix": spec.symmetric_prefix,
        "normalized": True,
        "external_download_performed": False,
    }
    training_metadata = {
        "model_version": MODEL_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "service_version": SERVICE_VERSION,
        "generation_profile": GENERATION_PROFILE,
        "created_at": utc_now(),
        "candidate_frozen": True,
        "evaluation_eligible": True,
        "scientifically_validated": False,
        "scientific_result": False,
        "confirmatory_eligible": False,
        "test_data_used": False,
        "primary33_used": False,
        "dataset": {
            "path": str(dataset_path.relative_to(PROJECT_ROOT)),
            "sha256": config["dataset"]["sha256"],
            "records": len(cases),
            "classification_records": len(class_samples),
            "classification_groups": len(set(class_groups)),
            "deduplication_records": len(pair_samples),
            "deduplication_groups": len(set(pair_groups)),
            "development_only": True,
        },
        "selection": {
            "directory": str(selection_dir.relative_to(PROJECT_ROOT)),
            "protocol_sha256": validation["protocol_sha256"],
            "run_fingerprint": validation["run_fingerprint"],
            "validation_sha256": sha256_file(selection_dir / "validacao_resultados.json"),
            "results_sha256": sha256_file(selection_dir / "resultados.json"),
            "oof_sha256": sha256_file(selection_dir / "predicoes_oof.csv"),
            "validation_status": "VALID",
            "development_only": True,
            "confirmatory_eligible": False,
        },
        "candidates": candidate_summary,
        "classification_fit": classification_training,
        "deduplication_fit": dedup_training,
        "pipeline_source_sha256": source_hashes,
        "embedding_runtime": embedding_runtime,
    }
    bundle = {
        "bundle_version": BUNDLE_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "service_version": SERVICE_VERSION,
        "generation_profile": GENERATION_PROFILE,
        "pipeline_source_sha256": source_hashes,
        "classification_model": classification_model,
        "dedup_model": dedup_model,
        "vectorizers": {
            "classification": class_features.vectorizer_,
            "dedup": pair_features.vectorizer_,
        },
        "feature_schema": feature_schema,
        "classes": {
            "classification": [str(value) for value in classification_model.classes_],
            "deduplication": [str(value) for value in dedup_model.classes_],
        },
        "thresholds": thresholds,
        "embedding": embedding,
        "training_metadata": training_metadata,
        "selected_operating_points": {
            "classification": class_policy,
            "deduplication": dedup_policy,
        },
        "calibration_metrics": {},
        "pipeline_metrics": {},
    }
    joblib.dump(bundle, bundle_path, compress=3)
    bundle_sha256 = sha256_file(bundle_path)
    manifest: dict[str, Any] = {
        "schema_version": "local-hybrid-manifest-v1.9",
        "model_version": MODEL_VERSION,
        "bundle_version": BUNDLE_VERSION,
        "status": "CALIBRATED_DEVELOPMENT_CANDIDATE_UNDERPOWERED",
        "candidate_frozen": True,
        "evaluation_eligible": True,
        "scientifically_validated": False,
        "scientific_result": False,
        "confirmatory_eligible": False,
        "confirmatory_evaluation_completed": False,
        "test_data_used": False,
        "primary33_used": False,
        "scientific_claim_status": (
            "validated_development_selection_underpowered_not_confirmatory"
        ),
        "pipeline": {
            "version": PIPELINE_VERSION,
            "service_version": SERVICE_VERSION,
            "generation_profile": GENERATION_PROFILE,
            "source_sha256": source_hashes,
        },
        "bundle": {
            "path": bundle_path.name,
            "sha256": bundle_sha256,
            "load_contract": "joblib.load(path)",
            "required_keys": [
                "classification_model",
                "dedup_model",
                "vectorizers",
                "feature_schema",
                "classes",
                "thresholds",
                "embedding",
                "training_metadata",
                "pipeline_version",
                "service_version",
                "generation_profile",
                "pipeline_source_sha256",
            ],
        },
        "embedding": embedding,
        "feature_schema": feature_schema,
        "classes": bundle["classes"],
        "thresholds": thresholds,
        "selected_operating_points": bundle["selected_operating_points"],
        "training": training_metadata,
        "selection_candidates": candidate_summary,
        "reproducibility": {
            "protocol_sha256": validation["protocol_sha256"],
            "run_fingerprint": validation["run_fingerprint"],
            "bundle_sha256": bundle_sha256,
            "materializer_sha256": source_hashes["materializer"],
        },
        "manifest_payload_sha256": None,
    }
    manifest["manifest_payload_sha256"] = canonical_sha256(manifest)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return bundle_path, manifest_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Materializa, sem holdout, o candidato validado da seleção v1.3/v2.0."
    )
    parser.add_argument("--selection-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--allow-underpowered-development-candidate",
        action="store_true",
        help="Permite empacotar candidato provisório sem promovê-lo a validado.",
    )
    parser.add_argument(
        "--dedup-candidate-id",
        type=str,
        default=None,
        help="Especifica explicitamente o ID do candidato de deduplicação a materializar.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bundle, manifest = materialize(
        args.selection_dir,
        args.output_dir,
        allow_underpowered=args.allow_underpowered_development_candidate,
        dedup_candidate_id=args.dedup_candidate_id,
    )
    print(f"Bundle: {bundle}")
    print(f"Manifesto: {manifest}")
    print("Status: candidato de desenvolvimento UNDERPOWERED; não confirmatório")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
