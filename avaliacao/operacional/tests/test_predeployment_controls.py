from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _load_verify_module():
    path = ROOT / "avaliacao" / "operacional" / "verify_backup_restore_evidence.py"
    spec = importlib.util.spec_from_file_location("verify_backup_restore_evidence", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tls_profile_static_validation_passes() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_tls_profile.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_stop_contract_is_fail_closed_and_not_overclaimed() -> None:
    payload = json.loads(
        (ROOT / "avaliacao" / "config" / "stop_operacional_v1.json").read_text(encoding="utf-8")
    )
    assert payload["fail_closed_on_missing_or_malformed_evidence"] is True
    assert payload["runtime_effect"]["block_new_automatic_decisions"] is True
    assert payload["runtime_effect"]["route_to_manual_triage"] is True
    assert payload["current_enforcement"] == "READ_ONLY_DIAGNOSTIC_UNTIL_POST_WINDOW_WIRING"
    assert payload["production_ready"] is False


def test_scientific_plan_separates_proxy_from_institutional_labels() -> None:
    payload = json.loads(
        (ROOT / "avaliacao" / "config" / "plano_cientifico_preimplantacao_v5.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["labels"]["development"] == "SYNTHETIC_PROXY"
    assert payload["labels"]["institutional"] == "UNAVAILABLE"
    assert payload["corpus"]["zero_group_overlap_between_development_and_locked_challenge"] is True
    assert {"decision_tree", "linear_svm", "mlp", "xgboost"}.issubset(
        payload["comparison"]["required_models"]
    )
    assert payload["scientific_result"] is False
    assert payload["production_ready"] is False


def test_backup_restore_verifier_accepts_native_and_legacy_count_maps() -> None:
    module = _load_verify_module()
    expected = {"tickets_processados": 230, "fila_ia_dead_letter": 110}
    assert module._counts(expected) == expected
    assert module._counts("@{tickets_processados=230; fila_ia_dead_letter=110}") == expected


def test_current_scientific_corpus_audit_reports_gaps_without_overclaiming() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "avaliacao" / "scripts" / "auditar_prontidao_cientifica_preimplantacao.py"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert payload["status"] == "GAPS_REMAIN"
    assert payload["scientific_result"] is False
    assert payload["confirmatory_eligible"] is False
