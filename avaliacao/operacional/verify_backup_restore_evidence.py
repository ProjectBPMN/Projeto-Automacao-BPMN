from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def _counts(value: Any) -> dict[str, int]:
    if isinstance(value, dict):
        return {str(key): int(count) for key, count in value.items()}
    if isinstance(value, str) and value.startswith("@{") and value.endswith("}"):
        pairs = re.findall(r"([A-Za-z0-9_]+)=([0-9]+)", value)
        return {key: int(count) for key, count in pairs}
    raise ValueError("Formato de contagens restauradas não reconhecido")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--restore", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(ROOT.resolve())
    if output.exists():
        raise RuntimeError(f"Evidência já existe: {output}")
    backup = json.loads(args.backup.read_text(encoding="utf-8"))
    restore = json.loads(args.restore.read_text(encoding="utf-8"))
    checks: dict[str, bool] = {
        "backup_captured": backup.get("status") == "CAPTURED",
        "restore_passed": restore.get("status") == "PASS",
        "live_services_not_touched": restore.get("live_services_touched") is False,
        "isolated_network_none": restore["result"]["isolated_targets"]["network"] == "none",
        "zero_published_ports": restore["result"]["isolated_targets"]["published_ports"] == 0,
    }
    details: dict[str, Any] = {}
    for engine in ("postgresql", "mariadb"):
        source = backup["artifacts"][engine]
        recovered = restore["result"]["artifacts"][engine]
        path = Path(source["path"])
        current_hash = _sha256(path)
        source_counts = {str(key): int(value) for key, value in source["source_row_counts"].items()}
        restored_counts = _counts(recovered["row_counts"])
        checks[f"{engine}_artifact_exists"] = path.is_file()
        checks[f"{engine}_hash_matches_backup_manifest"] = current_hash == source["sha256"]
        checks[f"{engine}_hash_matches_restore_evidence"] = current_hash == recovered["sha256"]
        checks[f"{engine}_row_counts_match"] = source_counts == restored_counts
        details[engine] = {
            "sha256": current_hash,
            "source_row_counts": source_counts,
            "restored_row_counts": restored_counts,
        }
    status = "PASS" if all(checks.values()) else "FAIL"
    payload = {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status,
        "backup_evidence": str(args.backup.resolve()),
        "restore_evidence": str(args.restore.resolve()),
        "checks": checks,
        "details": details,
        "scientific_result": False,
        "interpretation_limit": "Verifica hashes e igualdade das contagens registradas; não amplia o escopo do drill isolado.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "output": str(output)}, ensure_ascii=False))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
