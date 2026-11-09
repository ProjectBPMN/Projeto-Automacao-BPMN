from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _query(sql: str) -> list[str]:
    completed = subprocess.run(
        [
            "docker",
            "--context",
            "desktop-linux",
            "exec",
            "glpi-dedup-db",
            "sh",
            "-lc",
            f'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F "|" -c "{sql}"',
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if completed.returncode != 0:
        raise RuntimeError("Consulta operacional falhou sem expor credenciais")
    return completed.stdout.splitlines()


def main() -> int:
    parser = argparse.ArgumentParser(description="Captura somente contagens operacionais não sensíveis.")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "avaliacao" / "resultados" / "operacional" / "estado-runtime-final-20260902.json",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(ROOT.resolve())
    if output.exists():
        raise RuntimeError(f"Evidência já existe: {output}")
    queue = _query(
        "SELECT count(*) FILTER (WHERE triagem_status='ERRO_IA'), "
        "count(*) FILTER (WHERE triagem_status IN ('PENDENTE_FILA_IA','FILA_IA_LIBERADA','PROCESSANDO_IA',"
        "'CLASSIFICANDO_DUP','CLASSIFICANDO','AGUARDANDO_FILA_CLASSIFICACAO')), "
        "(SELECT count(*) FROM fila_ia_dead_letter WHERE NOT resolvido) "
        "FROM tickets_processados"
    )[0].split("|")
    dlq = int(queue[2])
    payload = {
        "schema_version": "1.1.0",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if queue[:2] == ["0", "0"] and dlq == 0 else "FAIL",
        "erro_ia": int(queue[0]),
        "active_queue": int(queue[1]),
        "open_dlq": dlq,
        "historical_records_deleted": False,
        "scientific_result": False,
        "semantic_correctness_confirmed": False,
        "interpretation_limit": "Contagens operacionais; não validam a correção semântica das decisões.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "output": str(output)}, ensure_ascii=False))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
