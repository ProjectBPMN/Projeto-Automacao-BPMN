from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "avaliacao" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import gerar_corpus_sintetico_v3 as corpus  # noqa: E402
import selecionar_modelos_supervisionados as selection  # noqa: E402
import treinar_modelo_local as training  # noqa: E402


DEV = ROOT / "avaliacao" / "datasets" / "desenvolvimento_sintetico_v3.jsonl"
DEV_MANIFEST = ROOT / "avaliacao" / "datasets" / "desenvolvimento_sintetico_v3_manifest.json"
LOCKED = ROOT / "avaliacao" / "datasets" / "desafio_sintetico_bloqueado_v3.jsonl"
LOCKED_MANIFEST = ROOT / "avaliacao" / "datasets" / "desafio_sintetico_bloqueado_v3_manifest.json"
CONFIG = ROOT / "avaliacao" / "config" / "selecao_modelos_supervisionados_v3.json"
SEMANTIC_DEV = ROOT / "avaliacao" / "datasets" / "semantico_v3" / "desenvolvimento_semantico_v3_1.jsonl"
SEMANTIC_DEV_MANIFEST = ROOT / "avaliacao" / "datasets" / "semantico_v3" / "desenvolvimento_semantico_v3_1_manifest.json"
SEMANTIC_LOCKED = ROOT / "avaliacao" / "datasets" / "semantico_v3" / "desafio_semantico_bloqueado_v3_1.jsonl"
SEMANTIC_LOCKED_MANIFEST = ROOT / "avaliacao" / "datasets" / "semantico_v3" / "desafio_semantico_bloqueado_v3_1_manifest.json"


def test_exact_independent_family_targets_and_model_eligible_balance() -> None:
    rows = training.load_jsonl(DEV)
    model_rows = training.classification_model_rows(rows)
    groups_by_class = {
        label: {
            row["source_dependency_group_sha256"]
            for row in model_rows
            if row["expected_classification"] == label
        }
        for label in corpus.CLASS_LABELS
    }
    assert {label: len(groups) for label, groups in groups_by_class.items()} == {
        label: 100 for label in corpus.CLASS_LABELS
    }
    pairs = training.dedup_pairs(rows)
    strata = Counter(
        {
            name: len(
                {
                    current["source_dependency_group_sha256"]
                    for current, _, _ in pairs
                    if current["dedup_stratum"] == name
                }
            )
            for name in corpus.DEDUP_TARGETS
        }
    )
    assert strata == Counter(corpus.DEDUP_TARGETS)


def test_locked_challenge_is_disjoint_and_forbidden_during_selection() -> None:
    dev_manifest = json.loads(SEMANTIC_DEV_MANIFEST.read_text(encoding="utf-8"))
    locked_manifest = json.loads(SEMANTIC_LOCKED_MANIFEST.read_text(encoding="utf-8"))
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert all(value == 0 for value in dev_manifest["cross_partition_overlap"].values())
    assert locked_manifest["selection_access"] == "FORBIDDEN_UNTIL_MODEL_SELECTION_FROZEN"
    assert "avaliacao/datasets/semantico_v3/desafio_semantico_bloqueado_v3_1.jsonl" in config["dataset"]["forbidden_paths"]
    locked_rows = training.load_jsonl(SEMANTIC_LOCKED)
    try:
        training.validate_source_role(SEMANTIC_LOCKED, locked_rows, role="TRAIN")
    except training.ScientificGuardError:
        pass
    else:
        raise AssertionError("Desafio bloqueado foi aceito como treino")


def test_generation_is_byte_reproducible() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        corpus.generate(
            root / DEV.name,
            root / DEV_MANIFEST.name,
            root / LOCKED.name,
            root / LOCKED_MANIFEST.name,
        )
        assert (root / DEV.name).read_bytes() == DEV.read_bytes()
        assert (root / LOCKED.name).read_bytes() == LOCKED.read_bytes()


def test_protocol_freezes_five_models_and_ten_combinations() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    selection.validate_protocol_config(config)
    assert len(config["execution_combination_ids"]) == 10
    assert {
        value.rsplit("__", 1)[-1] for value in config["execution_combination_ids"]
    } == {"logistic_regression", "decision_tree", "linear_svm", "mlp", "xgboost"}
    assert config["dataset"]["sha256"] == corpus.sha256_file(SEMANTIC_DEV)
    assert config["dataset"]["locked_challenge_sha256"] == corpus.sha256_file(SEMANTIC_LOCKED)
