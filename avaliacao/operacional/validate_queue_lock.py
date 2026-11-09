"""Prova técnica do advisory lock do WF06, em transação sempre revertida."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "avaliacao/scripts"))
import validar_pipeline_fila_e2e as e2e


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = e2e.validate_output_path(args.output)
    workflow = ROOT / "n8n/workflows/Versão9/V9-WF06-Fila-IA.json"
    js = """const fs=require('fs');
const wf=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));
const expr=wf.nodes.find(n=>n.name==='PG: Reservar Fila IA').parameters.query;
process.env.FILA_IA_RUN_SCOPE='VALIDACAO-LOCK-SEM-TICKETS';
process.stdout.write(eval(expr.trim().slice(2,-2)));"""
    sql = subprocess.check_output(["node", "-e", js, str(workflow)], text=True,
        encoding="utf-8", timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    result = {"collected_at": datetime.now(timezone.utc).isoformat(),
        "scientific_result": False, "semantic_correctness_confirmed": False,
        "workflow_sha256": e2e.file_sha256(workflow), "transaction_committed": False}
    with e2e.queue_reservation_lock() as _owner:
        contender = e2e.database.connect_pg()
        try:
            with contender.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout='500ms'")
                cursor.execute("SET LOCAL statement_timeout='5s'")
                try:
                    cursor.execute(sql)
                except Exception as exc:
                    result["sqlstate"] = getattr(exc, "pgcode", None)
                    result["status"] = "PASS" if result["sqlstate"] == "55P03" else "FAIL"
                else:
                    result.update(status="FAIL", sqlstate=None)
        finally:
            contender.rollback()
            contender.close()
    e2e.write_report(output, result)
    print(json.dumps(result))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
