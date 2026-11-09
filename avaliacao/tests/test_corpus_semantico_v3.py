from __future__ import annotations

import json
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "avaliacao" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import gerar_corpus_semantico_v3 as corpus  # noqa: E402


REQUIRED_FIELDS = {
    "case_id", "scenario_id", "group_id", "episode_id", "dimension",
    "order_in_episode", "title", "content", "category", "location", "requester",
    "expected_classification", "expected_dedup", "pair_role", "reference_case_id",
    "contrast_anchor_case_id", "source_dependency_group_sha256", "split", "rationale",
    "label_source", "semantic_family_sha256", "grammar_family_sha256",
}


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_exact_semantic_coverage_and_dependency_counts() -> None:
    rows = load_jsonl(corpus.DEV_OUTPUT)
    class_rows = [row for row in rows if row["pair_role"] == "CLASSIFICATION"]
    semantic = {
        label: {row["semantic_family_sha256"] for row in class_rows if row["expected_classification"] == label}
        for label in corpus.CLASSES
    }
    sources = {
        label: {row["source_dependency_group_sha256"] for row in class_rows if row["expected_classification"] == label}
        for label in corpus.CLASSES
    }
    assert {label: len(values) for label, values in semantic.items()} == {label: 100 for label in corpus.CLASSES}
    # Cinco mecanismos do mesmo ativo não são fingidos como fontes independentes.
    assert {label: len(values) for label, values in sources.items()} == {label: 20 for label in corpus.CLASSES}
    challenges = [row for row in rows if row["pair_role"] == "CHALLENGE"]
    assert Counter(row["dedup_stratum"] for row in challenges) == Counter(corpus.DEV_DEDUP_TARGETS)
    assert len({row["visible_text_sha256"] for row in rows}) == len(rows)
    assert all(REQUIRED_FIELDS <= row.keys() and row["label_source"] == "synthetic_proxy" for row in rows)


def test_locked_manifest_proves_disjoint_provenance_without_opening_payload() -> None:
    dev = json.loads(corpus.DEV_MANIFEST.read_text(encoding="utf-8"))
    locked = json.loads(corpus.LOCKED_MANIFEST.read_text(encoding="utf-8"))
    assert dev["cross_partition_overlap"] == {
        "grammar_family_sha256": 0,
        "semantic_family_sha256": 0,
        "source_dependency_group_sha256": 0,
        "visible_text_sha256": 0,
    }
    assert locked["selection_access"] == "FORBIDDEN_UNTIL_MODEL_SELECTION_FROZEN"
    assert locked["split"] == "TESTE_BLOQUEADO"
    assert locked["files"]["jsonl"]["sha256"] == corpus.sha256_file(corpus.LOCKED_OUTPUT)
    assert locked["inference_method"] == "known_grammar_conditional"
    assert locked["grouping"]["effective_sample_size"] == "UNKNOWN"
    assert locked["validation"]["semantic_classification_families_by_class"] == {
        label: 25 for label in corpus.CLASSES
    }
    assert locked["validation"]["dedup_challenges_by_stratum"] == corpus.LOCKED_DEDUP_TARGETS
    assert dev["validation"]["post_fixed_router_semantic_families_by_class"] == {
        "OBRA": 40,
        "DEMO": 100,
        "SOB_DEMANDA": 60,
        "TRIAGEM_MANUAL": 24,
    }
    assert dev["validation"]["post_fixed_router_records_by_class"] == {
        "OBRA": 80,
        "DEMO": 200,
        "SOB_DEMANDA": 120,
        "TRIAGEM_MANUAL": 48,
    }


def test_relations_and_critical_negative_semantics() -> None:
    rows = load_jsonl(corpus.DEV_OUTPUT)
    by_id = {row["case_id"]: row for row in rows}
    for row in rows:
        if row["pair_role"] != "CHALLENGE":
            continue
        anchor = by_id[row["reference_case_id"]]
        assert row["reference_case_id"] == row["contrast_anchor_case_id"]
        assert anchor["pair_role"] == "ANCHOR"
        assert anchor["episode_id"] == row["episode_id"]
        assert anchor["order_in_episode"] < row["order_in_episode"]
        assert anchor["source_dependency_group_sha256"] == row["source_dependency_group_sha256"]
        if row["dedup_stratum"] == "critical_negative":
            assert row["expected_dedup"] is False
            assert row["requires_human_review"] is True
            assert "não afirma" in row["rationale"]


def test_generation_is_reproducible_and_locked_overwrite_is_guarded() -> None:
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory)
        dev = target / corpus.DEV_OUTPUT.name
        dev_manifest = target / corpus.DEV_MANIFEST.name
        locked = target / corpus.LOCKED_OUTPUT.name
        locked_manifest = target / corpus.LOCKED_MANIFEST.name
        corpus.generate(dev, dev_manifest, locked, locked_manifest)
        assert dev.read_bytes() == corpus.DEV_OUTPUT.read_bytes()
        assert locked.read_bytes() == corpus.LOCKED_OUTPUT.read_bytes()
        # Idempotência byte a byte é permitida.
        corpus.generate(dev, dev_manifest, locked, locked_manifest)
        locked.write_bytes(locked.read_bytes() + b"\n")
        with pytest.raises(FileExistsError, match="não será sobrescrito"):
            corpus.generate(dev, dev_manifest, locked, locked_manifest)


def test_source_and_grammar_hashes_do_not_depend_on_partition_fields() -> None:
    class_catalog = corpus.load_json(corpus.CLASS_CATALOG)
    groups = corpus.classification_groups(class_catalog, locked=False)
    by_source: dict[str, set[str]] = defaultdict(set)
    for group in groups:
        row = group[0]
        by_source[row["source_dependency_group_sha256"]].add(row["semantic_family_sha256"])
    assert len(by_source) == 80
    assert {len(families) for families in by_source.values()} == {5}
    semantic = {"task": "classification", "class": "DEMO", "asset": "x", "mechanism": "y"}
    source = {"task": "classification", "class": "DEMO", "authored_asset_source": "x"}
    grammar = {"task": "classification", "class": "DEMO", "authored_grammar": "y"}
    kwargs = dict(case_id="x", scenario_id="x", episode_id="x", dimension="CLASSIFICACAO",
                  order=1, title="x", content="y", category="z", location="l",
                  semantic_key=semantic, source_key=source, grammar_key=grammar,
                  occurrence=corpus.datetime(2025, 1, 1, tzinfo=corpus.timezone.utc))
    dev = corpus.base_record(split="DESENVOLVIMENTO", **kwargs)
    locked = corpus.base_record(split="TESTE_BLOQUEADO", **kwargs)
    assert dev["semantic_family_sha256"] == locked["semantic_family_sha256"]
    assert dev["source_dependency_group_sha256"] == locked["source_dependency_group_sha256"]
    assert dev["grammar_family_sha256"] == locked["grammar_family_sha256"]
