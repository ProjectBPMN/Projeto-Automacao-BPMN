from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from avaliacao.operacional.core import ROOT, load_policy, sha256_file, utc_now, write_json  # noqa: E402


DOCKER_PREFIX = ["docker", "--context", "desktop-linux"]
PG_CONTAINER = "glpi-dedup-db"
MARIA_CONTAINER = "glpi-db"
ALLOWED_BACKUP_ROOT = ROOT / "avaliacao" / "runtime" / "backups"


def docker_command(*args: str) -> list[str]:
    return [*DOCKER_PREFIX, *args]


def _run(command: Sequence[str], *, timeout: float = 300.0) -> dict[str, Any]:
    completed = subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _require_ok(result: dict[str, Any], step: str) -> str:
    if result["returncode"] != 0:
        detail = (result["stderr"] or result["stdout"] or "sem detalhe")[-1200:]
        raise RuntimeError(f"{step} falhou sem expor credenciais: {detail}")
    return str(result["stdout"])


def _inside(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    resolved.relative_to(root.resolve())
    return resolved


def _postgres_counts(tables: list[str]) -> dict[str, int]:
    unions = " UNION ALL ".join(
        f"SELECT '{table}', count(*)::bigint FROM public.\"{table}\"" for table in tables
    )
    output = _require_ok(
        _run(
            docker_command(
                "exec",
                PG_CONTAINER,
                "sh",
                "-lc",
                f'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F "|" -c "{unions};"',
            )
        ),
        "contagem PostgreSQL",
    )
    return {name: int(count) for name, count in (line.split("|", 1) for line in output.splitlines())}


def _mariadb_counts(tables: list[str]) -> dict[str, int]:
    statements = " ".join(
        f"SELECT '{table}', COUNT(*) FROM {table};" for table in tables
    )
    output = _require_ok(
        _run(
            docker_command(
                "exec",
                MARIA_CONTAINER,
                "sh",
                "-lc",
                f'mariadb -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" -N -B "$MYSQL_DATABASE" -e "{statements}"',
            )
        ),
        "contagem MariaDB",
    )
    return {name: int(count) for name, count in (line.split("\t", 1) for line in output.splitlines())}


def capture(output_dir: Path, manifest_path: Path) -> dict[str, Any]:
    output_dir = _inside(output_dir, ALLOWED_BACKUP_ROOT)
    manifest_path = _inside(manifest_path, ROOT)
    if output_dir.exists() or manifest_path.exists():
        raise FileExistsError("destino de backup ou manifesto já existe")
    output_dir.mkdir(parents=True)

    pg_name = "triagem-live.dump"
    maria_name = "glpi-live.sql"
    pg_container_path = f"/tmp/projeto-ic-{pg_name}"
    maria_container_path = f"/tmp/projeto-ic-{maria_name}"
    pg_target = output_dir / pg_name
    maria_target = output_dir / maria_name
    policy = load_policy()
    try:
        _require_ok(
            _run(
                docker_command(
                    "exec",
                    PG_CONTAINER,
                    "sh",
                    "-lc",
                    f'umask 077; pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" '
                    f'--format=custom --no-owner --no-privileges --file="{pg_container_path}"',
                )
            ),
            "dump PostgreSQL",
        )
        _require_ok(
            _run(docker_command("cp", f"{PG_CONTAINER}:{pg_container_path}", str(pg_target))),
            "cópia PostgreSQL",
        )

        _require_ok(
            _run(
                docker_command(
                    "exec",
                    MARIA_CONTAINER,
                    "sh",
                    "-lc",
                    f'umask 077; mariadb-dump -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" '
                    f'--single-transaction --quick --routines --triggers --events --hex-blob '
                    f'--default-character-set=utf8mb4 "$MYSQL_DATABASE" > "{maria_container_path}"',
                )
            ),
            "dump MariaDB",
        )
        _require_ok(
            _run(docker_command("cp", f"{MARIA_CONTAINER}:{maria_container_path}", str(maria_target))),
            "cópia MariaDB",
        )

        payload = {
            "schema_version": "1.0.0",
            "created_at": utc_now(),
            "status": "CAPTURED",
            "evidence_status": "LIVE_CONSISTENT_DATABASE_BACKUP_CAPTURE",
            "scientific_result": False,
            "daemon_touched": False,
            "live_databases_mutated": False,
            "docker_context": "desktop-linux",
            "consistency": {
                "postgresql": "pg_dump custom format consistent snapshot",
                "mariadb": "mariadb-dump --single-transaction",
            },
            "artifacts": {
                "postgresql": {
                    "path": str(pg_target),
                    "bytes": pg_target.stat().st_size,
                    "sha256": sha256_file(pg_target),
                    "source_row_counts": _postgres_counts(list(policy["required_backup_tables"]["postgresql"])),
                },
                "mariadb": {
                    "path": str(maria_target),
                    "bytes": maria_target.stat().st_size,
                    "sha256": sha256_file(maria_target),
                    "source_row_counts": _mariadb_counts(list(policy["required_backup_tables"]["mariadb"])),
                },
            },
            "interpretation_limit": (
                "A captura prova a criação de snapshots consistentes dos bancos locais. "
                "A recuperabilidade só é estabelecida pelo drill isolado de restauração."
            ),
        }
        write_json(manifest_path, payload)
        return payload
    finally:
        _run(docker_command("exec", PG_CONTAINER, "rm", "-f", pg_container_path), timeout=20.0)
        _run(docker_command("exec", MARIA_CONTAINER, "rm", "-f", maria_container_path), timeout=20.0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Captura snapshots consistentes dos bancos vivos; padrão dry-run.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    plan = {
        "mode": "APPLY_READ_ONLY_CAPTURE" if args.apply else "DRY_RUN",
        "output_dir": str(args.output_dir.resolve()),
        "manifest": str(args.manifest.resolve()),
        "daemon_touched": False,
        "live_databases_mutated": False,
        "docker_context": "desktop-linux",
    }
    if not args.apply:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    payload = capture(args.output_dir, args.manifest)
    print(json.dumps({"status": payload["status"], "manifest": str(args.manifest.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
