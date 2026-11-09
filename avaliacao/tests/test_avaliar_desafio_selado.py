from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from avaliacao.scripts import avaliar_desafio_selado as sealed


ALGORITHMS = (
    "logistic_regression", "decision_tree", "linear_svm", "mlp", "xgboost"
)


def combination_ids() -> list[str]:
    return [
        *(f"classification__hybrid__multilingual_e5_small__{name}" for name in ALGORITHMS),
        *(f"deduplication__hybrid_metadata__multilingual_e5_small__{name}" for name in ALGORITHMS),
    ]


def minimal_config() -> dict:
    return {
        "dataset": {
            "path": "dev.jsonl", "sha256": "dev-hash",
            "classification_group_field": "source_dependency_group_sha256",
            "deduplication_group_field": "source_dependency_group_sha256",
            "allow_mixed_label_source_groups": True,
            "locked_challenge_path": "challenge.jsonl",
            "locked_challenge_sha256": "challenge-hash",
        },
        "execution_combination_ids": combination_ids(),
        "cross_validation": {
            "calibration_fraction": .4, "outer_seed": 7,
            "calibration_search_attempts": 8, "fit_min_groups_per_class": 1,
            "calibration_min_groups_per_class": 1, "calibration_oof_folds": 2,
            "calibration_fold_min_groups_per_class": 1,
            "calibration_method": "sigmoid", "confidence_level": .95,
        },
        "operating_policy": {
            "classification_max_selective_risk": .1,
            "classification_min_coverage": .5,
            "classification_obra_min_confidence": .9,
            "deduplication_max_false_positive_rate": .05,
            "deduplication_min_precision": .9,
            "deduplication_min_coverage": .5,
            "deduplication_max_false_negative_rate": .02,
            "deduplication_min_negative_predictive_value": .98,
        },
        "objectives": {
            "deduplication_false_negative_cost": 5.,
            "deduplication_false_positive_cost": 1.,
        },
    }


def complete_results(config_hash: str = "config-hash") -> dict:
    rows = []
    for value in combination_ids():
        task, representation, embedding, classifier = value.split("__")
        rows.append({
            "combination_id": value, "task": task, "representation": representation,
            "embedding": embedding, "classifier": classifier,
            "status": "COMPLETED_DEVELOPMENT_OOF", "best_parameters": [{}],
        })
    return {
        "protocol_sha256": config_hash, "execution_tasks": list(sealed.EXPECTED_TASKS),
        "dataset": {"sha256": "dev-hash"}, "results": rows,
        "winners": {
            "classification": combination_ids()[0],
            "deduplication": combination_ids()[5],
        },
        "provisional_point_candidates": {},
    }


def test_incomplete_selection_fails_before_any_dataset_read(tmp_path, monkeypatch):
    config = minimal_config()
    results = complete_results()
    results["results"].pop()
    config_path = tmp_path / "config.json"
    results_path = tmp_path / "results.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    results_path.write_text(json.dumps(results), encoding="utf-8")
    monkeypatch.setattr(sealed.selection, "validate_protocol_config", lambda value: None)
    monkeypatch.setattr(
        sealed, "sha256_file",
        lambda path: "config-hash" if Path(path) == config_path else "unused",
    )
    reads: list[Path] = []
    monkeypatch.setattr(sealed.training, "load_jsonl", lambda path: reads.append(path))

    with pytest.raises(sealed.SealedChallengeError, match="Rodada DEV incompleta"):
        sealed.run(config_path, results_path, tmp_path / "evidence")
    assert reads == []


def test_challenge_hash_mismatch_fails_before_challenge_jsonl_is_loaded(
    tmp_path, monkeypatch
):
    config = minimal_config()
    config_path = tmp_path / "config.json"
    results_path = tmp_path / "results.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    results_path.write_text(json.dumps(complete_results()), encoding="utf-8")
    dev_path = (sealed.PROJECT_ROOT / "dev.jsonl").resolve()
    challenge_path = (sealed.PROJECT_ROOT / "challenge.jsonl").resolve()
    events: list[str] = []

    monkeypatch.setattr(sealed.selection, "validate_protocol_config", lambda value: None)
    def fake_hash(path: Path) -> str:
        path = Path(path).resolve()
        if path == config_path.resolve():
            return "config-hash"
        if path == results_path.resolve():
            return "results-hash"
        if path == dev_path:
            return "dev-hash"
        if path == challenge_path:
            events.append("hash-challenge")
            return "wrong-challenge-hash"
        return "artifact-hash"
    monkeypatch.setattr(sealed, "sha256_file", fake_hash)
    def fake_load(path: Path):
        events.append("load-challenge" if Path(path).resolve() == challenge_path else "load-dev")
        return [{"case_id": "DEV-ONLY"}]
    monkeypatch.setattr(sealed.training, "load_jsonl", fake_load)
    monkeypatch.setattr(sealed.training, "validate_source_role", lambda *args, **kwargs: {})
    monkeypatch.setattr(sealed.training, "validate_labels", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        sealed, "embedding_spec",
        lambda *args: SimpleNamespace(
            id="multilingual_e5_small", revision="rev", tree_sha256="tree"
        ),
    )
    monkeypatch.setattr(sealed, "encode_cases", lambda *args, **kwargs: ({}, {}))
    monkeypatch.setattr(sealed, "build_samples", lambda *args: ([], [], [], [], [], []))
    def fake_freeze(**kwargs):
        events.append("freeze")
        return {}, {}
    monkeypatch.setattr(sealed, "train_and_freeze", fake_freeze)

    with pytest.raises(sealed.SealedChallengeError, match="Hash do desafio divergente"):
        sealed.run(config_path, results_path, tmp_path / "evidence")
    assert events == ["load-dev", "freeze", "hash-challenge"]


def test_final_fit_receives_only_development_units_and_freezes_before_return(
    tmp_path, monkeypatch
):
    config = minimal_config()
    selected_rows = complete_results()["results"]
    selected = {
        "classification": selected_rows[0], "deduplication": selected_rows[5]
    }
    class_samples = [{"unit_id": f"DEV-C-{i}"} for i in range(4)]
    dedup_samples = [{"unit_id": f"DEV-D-{i}"} for i in range(4)]
    sample_sets = (
        class_samples, [0, 1, 2, 3], [f"cg{i}" for i in range(4)],
        dedup_samples, [0, 1, 0, 1], [f"dg{i}" for i in range(4)],
    )
    fitted_ids: list[list[str]] = []

    monkeypatch.setattr(
        sealed.selection, "fit_calibration_split",
        lambda indices, *args, **kwargs: (
            np.asarray([0, 1]), np.asarray([2, 3]), {"group_overlap": 0}
        ),
    )
    def fake_fit(row, *, samples, labels, config):
        fitted_ids.append([sample["unit_id"] for sample in samples])
        assert all(value.startswith("DEV-") for value in fitted_ids[-1])
        return object()
    monkeypatch.setattr(sealed.selection, "fit_final_base", fake_fit)
    class FakeCalibrated:
        classes_ = np.asarray([0, 1])
    monkeypatch.setattr(
        sealed.selection, "cross_fitted_calibration",
        lambda estimator, samples, labels, groups, **kwargs: (
            FakeCalibrated(),
            np.full((2, kwargs["class_count"]), 1 / kwargs["class_count"]),
            [{"group_overlap": 0}],
        ),
    )
    monkeypatch.setattr(
        sealed.selection, "select_classification_policy",
        lambda *args, **kwargs: {"threshold": .8, "curve": ["not-frozen"]},
    )
    monkeypatch.setattr(
        sealed.selection, "select_dedup_policy",
        lambda *args, **kwargs: {"positive_threshold": .9, "negative_threshold": .1},
    )
    monkeypatch.setattr(sealed.selection, "mode_parameters", lambda row: {})
    def fake_dump(value, path, compress):
        Path(path).write_bytes(b"frozen-model")
    monkeypatch.setattr(sealed.joblib, "dump", fake_dump)

    freeze, _ = sealed.train_and_freeze(
        selected=selected,
        evidence={task: "DEV_ONLY" for task in sealed.EXPECTED_TASKS},
        sample_sets=sample_sets, config=config, output_dir=tmp_path,
        provenance={"config_sha256": "config-hash"},
    )
    assert fitted_ids == [["DEV-C-0", "DEV-C-1"], ["DEV-D-0", "DEV-D-1"]]
    assert freeze["status"] == "FROZEN_BEFORE_CHALLENGE_ACCESS"
    assert "curve" not in freeze["tasks"]["classification"]["policy"]
    assert (tmp_path / "freeze.json").is_file()


def test_overlap_audit_uses_split_neutral_hashes_and_reports_grammar_dependency():
    dev = [{
        "source_dependency_group_sha256": "source-dev", "visible_text_sha256": "case-dev",
        "narrative_core_sha256": "episode-dev",
        "semantic_signature": {"task": "classification", "label": "OBRA", "challenge_partition": "development"},
        "grammar_family_sha256": "shared-grammar",
    }]
    challenge = [{
        "source_dependency_group_sha256": "source-challenge", "visible_text_sha256": "case-challenge",
        "narrative_core_sha256": "episode-challenge",
        "semantic_signature": {"task": "classification", "label": "DEMO", "challenge_partition": "locked"},
        "grammar_family_sha256": "shared-grammar",
    }]
    audit = sealed.overlap_audit(dev, challenge)
    assert audit["primary_disjoint"] is True
    assert audit["grammar_family_sha256_sensitivity"]["overlap_count"] == 1
    assert "condicionais" in audit["grammar_family_sha256_sensitivity"]["interpretation"]


def test_sealed_challenge_requires_explicitly_locked_split(tmp_path):
    locked = [{"split": "TESTE_BLOQUEADO"}]
    sealed.validate_sealed_challenge_role(tmp_path / "locked.jsonl", locked)
    with pytest.raises(sealed.SealedChallengeError, match="TESTE_BLOQUEADO"):
        sealed.validate_sealed_challenge_role(tmp_path / "wrong.jsonl", [{"split": "DESENVOLVIMENTO"}])
