from __future__ import annotations

"""Avalia uma escolha DEV congelada uma unica vez no desafio bloqueado.

O desenho deste modulo e deliberadamente sequencial: todos os guards, o ajuste
DEV e a persistencia verificavel dos modelos/politicas acontecem antes de o
arquivo do desafio ser sequer carregado. O desafio nunca participa de ajuste,
calibracao, escolha de limiar ou escolha de algoritmo.
"""

import argparse
import hashlib
import inspect
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import joblib
import numpy as np

from avaliacao.scripts import selecionar_modelos_supervisionados as selection
from avaliacao.scripts import treinar_modelo_local as training


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "projeto-ic-avaliacao-desafio-selado-v1"
EXPECTED_TASKS = ("classification", "deduplication")


class SealedChallengeError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def resolve_selection_results(path: Path) -> Path:
    candidate = path / "resultados.json" if path.is_dir() else path
    if not candidate.is_file():
        raise SealedChallengeError(f"Resultados de selecao ausentes: {candidate}")
    return candidate.resolve()


def expected_combination_ids(config: dict[str, Any]) -> set[str]:
    expected = {str(value) for value in config.get("execution_combination_ids", [])}
    if len(expected) != 10:
        raise SealedChallengeError(
            "O desafio exige a rodada DEV completa das 10 configuracoes congeladas"
        )
    classifiers = {value.rsplit("__", 1)[-1] for value in expected}
    required = {
        "logistic_regression", "decision_tree", "linear_svm", "mlp", "xgboost"
    }
    for task in EXPECTED_TASKS:
        task_ids = {value for value in expected if value.startswith(task + "__")}
        if len(task_ids) != 5 or {value.rsplit("__", 1)[-1] for value in task_ids} != required:
            raise SealedChallengeError(f"Grade incompleta para {task}")
    if classifiers != required:
        raise SealedChallengeError("Algoritmos da rodada DEV divergem do protocolo")
    return expected


def validate_completed_selection(
    config: dict[str, Any], results: dict[str, Any], *, config_sha256: str
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    expected = expected_combination_ids(config)
    if results.get("protocol_sha256") != config_sha256:
        raise SealedChallengeError("Hash do protocolo diverge dos resultados de selecao")
    if set(results.get("execution_tasks", [])) != set(EXPECTED_TASKS):
        raise SealedChallengeError("A selecao nao concluiu as duas tarefas")
    dataset = config.get("dataset", {})
    if results.get("dataset", {}).get("sha256") != dataset.get("sha256"):
        raise SealedChallengeError("Dataset DEV dos resultados diverge do protocolo")
    by_id = {str(row.get("combination_id")): row for row in results.get("results", [])}
    missing = sorted(expected - set(by_id))
    failed = sorted(
        value for value in expected
        if value in by_id and by_id[value].get("status") != "COMPLETED_DEVELOPMENT_OOF"
    )
    extra = sorted(set(by_id) - expected)
    if missing or failed or extra:
        raise SealedChallengeError(
            f"Rodada DEV incompleta ou divergente: missing={missing}, failed={failed}, extra={extra}"
        )
    selected: dict[str, dict[str, Any]] = {}
    evidence: dict[str, str] = {}
    for task in EXPECTED_TASKS:
        winner = results.get("winners", {}).get(task)
        status = "CONFIDENCE_QUALIFIED_WINNER"
        if not winner:
            winner = results.get("provisional_point_candidates", {}).get(task)
            status = "PROVISIONAL_POINT_CANDIDATE"
        if winner not in expected or not str(winner).startswith(task + "__"):
            raise SealedChallengeError(f"Escolha DEV ausente ou invalida para {task}")
        selected[task] = by_id[str(winner)]
        evidence[task] = status
    return selected, evidence


def challenge_location(config: dict[str, Any]) -> tuple[Path, str]:
    dataset = config.get("dataset", {})
    path_value = dataset.get("locked_challenge_path")
    expected_hash = (
        dataset.get("locked_challenge_sha256")
        or dataset.get("locked_challenge", {}).get("sha256")
        or dataset.get("locked_challenge_hash")
    )
    if not path_value or not expected_hash:
        raise SealedChallengeError("Path/hash do desafio bloqueado ausentes do protocolo")
    path = (PROJECT_ROOT / str(path_value)).resolve()
    try:
        path.relative_to(PROJECT_ROOT.resolve())
    except ValueError as exc:
        raise SealedChallengeError("Desafio deve permanecer dentro do repositorio") from exc
    return path, str(expected_hash)


def validate_sealed_challenge_role(path: Path, cases: Sequence[dict[str, Any]]) -> None:
    """Accept only the explicitly sealed TESTE_BLOQUEADO partition.

    ``validate_source_role`` deliberately accepts only train/calibration inputs,
    so it must not be reused when the frozen model finally reads the challenge.
    """
    observed_splits = {
        training.normalize_token(case.get("split")) for case in cases if case.get("split")
    }
    if observed_splits != {"TESTE_BLOQUEADO"}:
        raise SealedChallengeError(
            f"{path}: desafio selado exige somente split TESTE_BLOQUEADO; "
            f"observado={sorted(observed_splits)}"
        )


def embedding_spec(config: dict[str, Any], embedding_id: str) -> selection.EmbeddingSpec:
    matches = [item for item in config.get("embeddings", []) if item.get("id") == embedding_id]
    if len(matches) != 1:
        raise SealedChallengeError(f"Embedding congelado ausente: {embedding_id}")
    item = matches[0]
    return selection.EmbeddingSpec(
        id=item["id"], repository=item["repository"], revision=item["revision"],
        local_path=(PROJECT_ROOT / item["local_path"]).resolve(),
        tree_sha256=item["tree_sha256"], dimension=int(item["dimension"]),
        symmetric_prefix=item["symmetric_prefix"],
        retrieval_query_prefix=item["retrieval_query_prefix"],
        retrieval_passage_prefix=item["retrieval_passage_prefix"],
    )


def encode_cases(
    cases: Sequence[dict[str, Any]], *, dataset_sha256: str,
    spec: selection.EmbeddingSpec, config: dict[str, Any], cache_namespace: str,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    class_cases = training.classification_model_rows(cases)
    pairs = training.dedup_pairs(cases)
    texts = list(dict.fromkeys(
        [training.model_text(case) for case in class_cases]
        + [training.model_text(case) for pair in pairs for case in pair[:2]]
    ))
    maps, metadata = selection.encode_model_roles(
        spec, dataset_sha256=dataset_sha256,
        role_inputs={"symmetric": (texts, spec.symmetric_prefix)},
        cache_root=PROJECT_ROOT / "local_ai" / "runtime" / cache_namespace,
        batch_size=int(config["hardware"]["embedding_batch_size"]),
        cpu_threads=int(config["hardware"]["cpu_threads"]), force=False,
    )
    return maps["symmetric"], metadata


def build_samples(
    cases: Sequence[dict[str, Any]], embedding_map: dict[str, np.ndarray],
    config: dict[str, Any],
) -> tuple[Any, ...]:
    kwargs: dict[str, Any] = {
        "embedding_map": embedding_map,
        "classification_group_field": config["dataset"]["classification_group_field"],
        "deduplication_group_field": config["dataset"]["deduplication_group_field"],
    }
    parameters = inspect.signature(selection.build_samples).parameters
    if "allow_mixed_label_source_groups" in parameters:
        kwargs["allow_mixed_label_source_groups"] = bool(
            config["dataset"].get("allow_mixed_label_source_groups", False)
        )
    elif "allow_mixed_label_groups" in parameters:  # compatibilidade durante migracao v3
        kwargs["allow_mixed_label_groups"] = bool(
            config["dataset"].get("allow_mixed_label_source_groups", False)
        )
    return selection.build_samples(cases, **kwargs)


def _task_inputs(sample_sets: tuple[Any, ...], task: str) -> tuple[list[Any], list[int], list[str]]:
    values = sample_sets[:3] if task == "classification" else sample_sets[3:]
    return values[0], values[1], values[2]


def train_and_freeze(
    *, selected: dict[str, dict[str, Any]], evidence: dict[str, str],
    sample_sets: tuple[Any, ...], config: dict[str, Any], output_dir: Path,
    provenance: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    models_dir = output_dir / "modelos_congelados"
    models_dir.mkdir(parents=True, exist_ok=False)
    bundles: dict[str, dict[str, Any]] = {}
    frozen_tasks: dict[str, Any] = {}
    cv = config["cross_validation"]
    for offset, task in enumerate(EXPECTED_TASKS):
        samples, labels, groups = _task_inputs(sample_sets, task)
        indices = np.arange(len(labels), dtype=int)
        fit_index, calibration_index, split_audit = selection.fit_calibration_split(
            indices, labels, groups, fraction=float(cv["calibration_fraction"]),
            seed=int(cv["outer_seed"]) + 900000 + offset,
            attempts=int(cv["calibration_search_attempts"]),
            context=f"sealed-final/{task}",
            min_fit_groups_per_class=int(cv["fit_min_groups_per_class"]),
            min_calibration_groups_per_class=int(cv["calibration_min_groups_per_class"]),
        )
        fit_samples = selection.subset(samples, fit_index)
        fit_labels = np.asarray(labels)[fit_index].tolist()
        base = selection.fit_final_base(
            selected[task], samples=fit_samples, labels=fit_labels, config=config
        )
        calibration_samples = selection.subset(samples, calibration_index)
        calibration_labels = np.asarray(labels)[calibration_index]
        calibration_groups = np.asarray(groups, dtype=object)[calibration_index]
        calibrated, calibration_oof, calibration_folds = selection.cross_fitted_calibration(
            base, calibration_samples, calibration_labels, calibration_groups,
            folds=int(cv["calibration_oof_folds"]),
            class_count=(len(selection.CLASS_LABELS) if task == "classification" else 2),
            min_groups_per_class=int(cv["calibration_fold_min_groups_per_class"]),
            method=str(cv["calibration_method"]), seed=int(cv["outer_seed"]) + 910000 + offset,
        )
        if task == "classification":
            policy = selection.select_classification_policy(
                calibration_oof, calibration_labels,
                max_risk=float(config["operating_policy"]["classification_max_selective_risk"]),
                min_coverage=float(config["operating_policy"]["classification_min_coverage"]),
                obra_min_confidence=float(config["operating_policy"]["classification_obra_min_confidence"]),
            )
        else:
            policy = selection.select_dedup_policy(
                calibration_oof, calibration_labels, config["operating_policy"],
                false_negative_cost=float(config["objectives"]["deduplication_false_negative_cost"]),
                false_positive_cost=float(config["objectives"]["deduplication_false_positive_cost"]),
            )
        policy_frozen = {key: value for key, value in policy.items() if key != "curve"}
        bundle_path = models_dir / f"{task}.joblib"
        joblib.dump({"model": calibrated, "policy": policy_frozen}, bundle_path, compress=3)
        bundle_hash = sha256_file(bundle_path)
        bundles[task] = {"model": calibrated, "policy": policy_frozen}
        frozen_tasks[task] = {
            "combination_id": selected[task]["combination_id"],
            "selection_evidence": evidence[task],
            "best_parameters_mode": selection.mode_parameters(selected[task]),
            "policy": policy_frozen,
            "calibration_method": cv["calibration_method"],
            "fit_calibration_split": split_audit,
            "calibration_folds": calibration_folds,
            "fit_unit_ids_sha256": canonical_sha256([samples[int(i)]["unit_id"] for i in fit_index]),
            "calibration_unit_ids_sha256": canonical_sha256(
                [samples[int(i)]["unit_id"] for i in calibration_index]
            ),
            "artifact": str(bundle_path.relative_to(output_dir)),
            "artifact_sha256": bundle_hash,
        }
    freeze = {**provenance, "status": "FROZEN_BEFORE_CHALLENGE_ACCESS", "frozen_at": utc_now(),
              "tasks": frozen_tasks}
    freeze_path = output_dir / "freeze.json"
    write_json(freeze_path, freeze)
    observed = json.loads(freeze_path.read_text(encoding="utf-8"))
    for task, row in observed["tasks"].items():
        artifact = output_dir / row["artifact"]
        if sha256_file(artifact) != row["artifact_sha256"]:
            raise SealedChallengeError(f"Modelo congelado corrompido: {task}")
    return observed, bundles


def overlap_audit(dev: Sequence[dict[str, Any]], challenge: Sequence[dict[str, Any]]) -> dict[str, Any]:
    def values(rows: Sequence[dict[str, Any]], field: str) -> set[str]:
        return {str(row[field]) for row in rows if row.get(field) not in (None, "")}

    def semantic_id(row: dict[str, Any]) -> str | None:
        signature = row.get("semantic_signature")
        if not isinstance(signature, dict):
            return None
        normalized = {key: value for key, value in signature.items() if key != "challenge_partition"}
        return canonical_sha256(normalized)

    dimensions = {
        "source_dependency_group_sha256": (
            values(dev, "source_dependency_group_sha256"),
            values(challenge, "source_dependency_group_sha256"),
        ),
        "case_visible_text_sha256": (values(dev, "visible_text_sha256"), values(challenge, "visible_text_sha256")),
        "episode_narrative_core_sha256": (
            values(dev, "narrative_core_sha256"), values(challenge, "narrative_core_sha256")
        ),
        "normalized_semantic_signature_sha256": (
            {value for row in dev if (value := semantic_id(row))},
            {value for row in challenge if (value := semantic_id(row))},
        ),
    }
    result: dict[str, Any] = {}
    for name, (left, right) in dimensions.items():
        overlap = sorted(left & right)
        result[name] = {"development_unique": len(left), "challenge_unique": len(right),
                        "overlap_count": len(overlap), "overlap_ids": overlap}
    grammar_left = values(dev, "grammar_family_sha256")
    grammar_right = values(challenge, "grammar_family_sha256")
    grammar_overlap = sorted(grammar_left & grammar_right)
    result["grammar_family_sha256_sensitivity"] = {
        "development_unique": len(grammar_left), "challenge_unique": len(grammar_right),
        "overlap_count": len(grammar_overlap), "overlap_ids": grammar_overlap,
        "interpretation": "Dependencia residual de gramatica limita a generalizacao; ICs sao condicionais ao gerador.",
    }
    required = [key for key in dimensions]
    result["primary_disjoint"] = all(result[key]["overlap_count"] == 0 for key in required)
    return result


def evaluate_task(
    task: str, bundle: dict[str, Any], sample_sets: tuple[Any, ...], config: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    samples, labels, groups = _task_inputs(sample_sets, task)
    probabilities = bundle["model"].predict_proba(samples)
    class_count = len(selection.CLASS_LABELS) if task == "classification" else 2
    probabilities = selection.reorder_probabilities(
        probabilities, bundle["model"].classes_, class_count
    )
    if task == "classification":
        decisions, covered = selection.apply_classification_policy(probabilities, bundle["policy"])
        metrics = selection.classification_summary(
            labels, probabilities, decisions, covered, groups,
            bootstrap_resamples=2000, seed=int(config["cross_validation"]["outer_seed"]) + 920000,
            confidence_level=float(config["cross_validation"]["confidence_level"]),
        )
        label_names = selection.CLASS_LABELS
    else:
        decisions, covered = selection.apply_dedup_policy(probabilities, bundle["policy"])
        metrics = selection.dedup_summary(
            labels, probabilities, decisions, covered, groups,
            false_negative_cost=float(config["objectives"]["deduplication_false_negative_cost"]),
            false_positive_cost=float(config["objectives"]["deduplication_false_positive_cost"]),
            bootstrap_resamples=2000, seed=int(config["cross_validation"]["outer_seed"]) + 930000,
            confidence_level=float(config["cross_validation"]["confidence_level"]),
        )
        label_names = selection.DEDUP_LABELS
    rows = []
    for index, sample in enumerate(samples):
        decision = int(decisions[index])
        rows.append({
            "unit_id": sample["unit_id"], "group": groups[index],
            "gold": label_names[int(labels[index])],
            "semantic_prediction": label_names[int(np.argmax(probabilities[index]))],
            "policy_prediction": label_names[decision] if bool(covered[index]) and decision >= 0 else "ABSTENCAO",
            "covered": bool(covered[index]),
            "probabilities": {label.lower(): float(probabilities[index, pos]) for pos, label in enumerate(label_names)},
        })
    return metrics, rows


def run(config_path: Path, selection_path: Path, output_dir: Path) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SealedChallengeError("Output deve ser novo e vazio; evidencia selada e imutavel")
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_path.resolve()
    results_path = resolve_selection_results(selection_path.resolve())
    config = json.loads(config_path.read_text(encoding="utf-8"))
    selection.validate_protocol_config(config)
    config_hash = sha256_file(config_path)
    results_hash = sha256_file(results_path)
    results = json.loads(results_path.read_text(encoding="utf-8"))
    selected, evidence = validate_completed_selection(config, results, config_sha256=config_hash)
    challenge_path, expected_challenge_hash = challenge_location(config)
    dev_path = (PROJECT_ROOT / config["dataset"]["path"]).resolve()
    dev_hash = sha256_file(dev_path)
    if dev_hash != config["dataset"]["sha256"]:
        raise SealedChallengeError("Hash do dataset DEV diverge antes do ajuste final")
    dev_cases = training.load_jsonl(dev_path)
    training.validate_source_role(dev_path, dev_cases, role="TRAIN")
    training.validate_labels(dev_cases, str(dev_path))
    embedding_ids = {row.get("embedding") for row in selected.values()}
    if len(embedding_ids) != 1 or None in embedding_ids:
        raise SealedChallengeError("Finalistas devem compartilhar um embedding local congelado")
    spec = embedding_spec(config, str(next(iter(embedding_ids))))
    dev_embedding_map, dev_embedding_metadata = encode_cases(
        dev_cases, dataset_sha256=dev_hash, spec=spec, config=config,
        cache_namespace="selection_cache",
    )
    dev_sample_sets = build_samples(dev_cases, dev_embedding_map, config)
    implementation_files = [Path(__file__).resolve(), Path(selection.__file__).resolve(), Path(training.__file__).resolve()]
    provenance = {
        "schema": SCHEMA, "config_path": str(config_path), "config_sha256": config_hash,
        "selection_results_path": str(results_path), "selection_results_sha256": results_hash,
        "selection_run_fingerprint": results.get("run_fingerprint"),
        "development_dataset_path": str(dev_path), "development_dataset_sha256": dev_hash,
        "locked_challenge_path": str(challenge_path),
        "locked_challenge_expected_sha256": expected_challenge_hash,
        "embedding": {"id": spec.id, "revision": spec.revision, "tree_sha256": spec.tree_sha256,
                      "cache": dev_embedding_metadata},
        "implementation_sha256": {str(path.relative_to(PROJECT_ROOT)): sha256_file(path) for path in implementation_files},
        "bootstrap_group_resamples": 2000,
    }
    freeze, bundles = train_and_freeze(
        selected=selected, evidence=evidence, sample_sets=dev_sample_sets,
        config=config, output_dir=output_dir, provenance=provenance,
    )

    # Primeira leitura relacionada ao conteudo do desafio: somente apos freeze validado.
    observed_challenge_hash = sha256_file(challenge_path)
    if observed_challenge_hash != expected_challenge_hash:
        raise SealedChallengeError(
            f"Hash do desafio divergente: {observed_challenge_hash} != {expected_challenge_hash}"
        )
    challenge_cases = training.load_jsonl(challenge_path)
    validate_sealed_challenge_role(challenge_path, challenge_cases)
    training.validate_labels(challenge_cases, str(challenge_path))
    disjunction = overlap_audit(dev_cases, challenge_cases)
    if not disjunction["primary_disjoint"]:
        raise SealedChallengeError("Desafio nao e disjunto de DEV nas identidades pre-registradas")
    challenge_embedding_map, challenge_embedding_metadata = encode_cases(
        challenge_cases, dataset_sha256=observed_challenge_hash, spec=spec, config=config,
        cache_namespace="sealed_challenge_cache",
    )
    challenge_sample_sets = build_samples(challenge_cases, challenge_embedding_map, config)
    metrics: dict[str, Any] = {}
    predictions: dict[str, Any] = {}
    for task in EXPECTED_TASKS:
        metrics[task], predictions[task] = evaluate_task(task, bundles[task], challenge_sample_sets, config)
    payload = {
        "schema": SCHEMA, "created_at": utc_now(), "status": "COMPLETED_ONCE",
        "scientific_result": False, "synthetic_proxy_challenge": True,
        "confirmatory_eligible": False,
        "freeze_sha256": sha256_file(output_dir / "freeze.json"),
        "locked_challenge_sha256": observed_challenge_hash,
        "disjunction_audit": disjunction,
        "embedding_runtime": challenge_embedding_metadata,
        "metrics": metrics, "predictions": predictions,
        "gate_interpretation": {
            "status": "EVIDENCE_ONLY_NO_AUTOMATIC_PASS",
            "reason": "Gates requerem limites de confianca agrupados; amostra pequena ou IC indefinido nunca aprova automaticamente.",
        },
        "limitations": [
            "Rotulos sinteticos proxy nao medem eficacia institucional, justica ou prontidao de producao.",
            "Bootstrap usa source_dependency_group_sha256 e seus ICs sao condicionais ao gerador.",
            "O gold de deduplicacao representa a acao operacional de nao fusionar, nao certeza de eventos distintos.",
            "Familias gramaticais compartilhadas sao dependencia residual, nao unidades independentes.",
        ],
    }
    write_json(output_dir / "avaliacao_desafio.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--saida", required=True, type=Path, help="Diretorio/JSON dos resultados DEV")
    parser.add_argument("--output", required=True, type=Path, help="Diretorio novo de evidencia selada")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run(args.config, args.saida, args.output)
    print(f"Avaliacao selada concluida em {args.output.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
