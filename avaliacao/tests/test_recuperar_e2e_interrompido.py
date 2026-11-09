from pathlib import Path
import json
import sys
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "avaliacao" / "scripts"))
import recuperar_e2e_interrompido as recovery


def test_saved_failed_evidence_is_verified():
    result = recovery.load_evidence(ROOT / "avaliacao/resultados/e2e-pipeline-local-v1.8.0-20260908-final.json")
    assert result["ticket_id"] == 325
    assert result["synthetic_only"] is True


def test_changed_evidence_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(recovery.e2e, "ROOT", tmp_path)
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps({"evidence_payload_sha256": "0" * 64}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="Hash"):
        recovery.load_evidence(path)


def test_source_outside_repository_is_refused(tmp_path):
    with pytest.raises(ValueError):
        recovery.load_evidence(tmp_path / "untrusted.json")
