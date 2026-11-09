import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from avaliacao.scripts import selecionar_modelos_supervisionados as selection


ROOT = Path(__file__).resolve().parents[2]


def test_source_groups_with_both_dedup_labels_stay_together():
    anchor = {"case_id": "anchor", "source_dependency_group_sha256": "asset-source"}
    positive = {"case_id": "positive", "source_dependency_group_sha256": "asset-source"}
    negative = {"case_id": "negative", "source_dependency_group_sha256": "asset-source"}
    pairs = [(positive, anchor, "DUPLICADO"), (negative, anchor, "NAO_DUPLICADO")]
    kwargs = dict(embedding_map=None, classification_group_field="source_dependency_group_sha256",
                  deduplication_group_field="source_dependency_group_sha256")
    with patch.object(selection.training, "classification_model_rows", return_value=[]), \
         patch.object(selection.training, "dedup_pairs", return_value=pairs), \
         patch.object(selection.training, "model_text", side_effect=lambda row: row["case_id"]):
        with pytest.raises(selection.SelectionGuardError, match="mais de um rótulo"):
            selection.build_samples([], **kwargs)
        data = selection.build_samples([], **kwargs, allow_mixed_label_source_groups=True)
    assert data[5] == ["asset-source", "asset-source"]
    assert set(data[4]) == {0, 1}


def test_nested_splits_keep_mixed_groups_disjoint_and_retain_classes():
    labels = [label for _ in range(40) for label in (0, 1)]
    groups = [str(group) for group in range(40) for _ in (0, 1)]
    config = json.loads((ROOT / "avaliacao/config/selecao_modelos_supervisionados_v2.json").read_text())
    audit = selection.validate_task_split_feasibility(
        task="deduplication", labels=labels, groups=groups, config=config,
    )
    assert len(audit) == 5
    for train, test in selection.safe_stratified_group_splits(labels, groups, n_splits=5, seed=1, context="test"):
        assert not set(np.array(groups)[train]) & set(np.array(groups)[test])
        assert set(np.array(labels)[train]) == set(np.array(labels)[test]) == {0, 1}
