from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from avaliacao.operacional.core import (  # noqa: E402
    DEFAULT_POLICY_PATH,
    ROOT,
    load_policy,
    sha256_file,
    utc_now,
    write_json,
)


POSTGRES_IMAGE = "postgres:16.13@sha256:71e27bf60b70bded003791b5573f8b808365613f341df20ffcf0c1ed7bc13ddf"
MARIADB_IMAGE = "mariadb:10.11.16@sha256:8d9046cdb0b0961b3d2119bcb4bea62a185f11944be5968bc42b81d47801902e"
DOCKER_PREFIX = ["docker", "--context", "desktop-linux"]


def docker_command(*args: str) -> list[str]:
    return [*DOCKER_PREFIX, *args]


def latest_mariadb_backup(root: Path = ROOT) -> Path:
    backups = sorted((root / "glpi" / "backups").glob("glpi_backup_*.sql"), key=lambda path: path.stat().st_mtime)
    return backups[-1] if backups else root / "glpi" / "backups" / "BACKUP_AUSENTE.sql"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Drill de restauração em containers temporários, sem portas e sem redes. "
            "O padrão é somente planejar; --apply cria e remove apenas alvos efêmeros."
        )
    )
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--postgres-artifact", type=Path, default=ROOT / "database" / "init_v9.sql")
    parser.add_argument("--mariadb-artifact", type=Path, default=latest_mariadb_backup())
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser


def _run(command: Sequence[str], *, stdin_path: Path | None = None, timeout: float = 300.0) -> dict[str, Any]:
    source = stdin_path.open("rb") if stdin_path else None
    try:
        completed = subprocess.run(
            list(command),
            stdin=source,
            capture_output=True,
            text=False,
            timeout=timeout,
            check=False,
        )
    finally:
        if source:
            source.close()
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout.decode("utf-8", errors="replace").strip(),
        "stderr": completed.stderr.decode("utf-8", errors="replace").strip(),
    }


def _require_ok(result: dict[str, Any], step: str) -> str:
    if result["returncode"] != 0:
        message = (result["stderr"] or result["stdout"] or "sem detalhe")[-2000:]
        raise RuntimeError(f"{step} falhou: {message}")
    return str(result["stdout"])


def _wait(command: Sequence[str], *, attempts: int = 40) -> None:
    for _ in range(attempts):
        if _run(command, timeout=5.0)["returncode"] == 0:
            return
        time.sleep(0.5)
    raise RuntimeError("Alvo temporário não ficou pronto no limite previsto")


def _wait_mariadb_final(container: str, *, attempts: int = 80) -> None:
    """Espera o servidor final, não o servidor temporário do entrypoint.

    Durante a inicialização de um datadir vazio, a imagem oficial sobe um
    MariaDB temporário que já responde a ping e depois o encerra. O processo 1
    só passa a ser ``mariadbd`` quando a inicialização terminou.
    """

    for _ in range(attempts):
        process_one = _run(docker_command("exec", container, "cat", "/proc/1/comm"), timeout=5.0)
        ping = _run(
            docker_command("exec", container, "mariadb-admin", "ping", "-uroot", "--silent"),
            timeout=5.0,
        )
        if process_one["returncode"] == 0 and process_one["stdout"].strip() in {
            "mariadbd",
            "mysqld",
        } and ping["returncode"] == 0:
            return
        time.sleep(0.5)
    raise RuntimeError("MariaDB temporário não chegou ao processo final no limite previsto")


def _copy_verified(source: Path, target_dir: Path) -> tuple[Path, str]:
    if not source.is_file():
        raise FileNotFoundError(source)
    target = target_dir / source.name
    shutil.copy2(source, target)
    source_hash = sha256_file(source)
    if sha256_file(target) != source_hash:
        raise RuntimeError(f"Cópia de staging divergiu de {source}")
    return target, source_hash


def _query_counts_postgres(container: str, tables: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in tables:
        command = [
            *DOCKER_PREFIX, "exec", container, "psql", "-U", "postgres", "-d", "restore_target", "-At",
            "-c", f'SELECT count(*) FROM public."{table}";',
        ]
        counts[table] = int(_require_ok(_run(command), f"contagem PostgreSQL {table}"))
    return counts


def _query_counts_mariadb(container: str, tables: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in tables:
        command = [
            *DOCKER_PREFIX, "exec", container, "mariadb", "-uroot", "-N", "-B", "glpi_restore",
            "-e", f"SELECT COUNT(*) FROM `{table}`;",
        ]
        counts[table] = int(_require_ok(_run(command), f"contagem MariaDB {table}"))
    return counts


def execute_drill(postgres_artifact: Path, mariadb_artifact: Path, policy: dict[str, Any]) -> dict[str, Any]:
    pg_name = f"projeto-ic-restore-pg-{uuid.uuid4().hex[:10]}"
    maria_name = f"projeto-ic-restore-maria-{uuid.uuid4().hex[:10]}"
    created: list[str] = []
    resource_strategy = "SEQUENTIAL_EPHEMERAL_DATABASES"
    started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="projeto_ic_restore_") as temp_name:
            temp_dir = Path(temp_name)
            pg_staged, pg_hash = _copy_verified(postgres_artifact.resolve(), temp_dir)
            maria_staged, maria_hash = _copy_verified(mariadb_artifact.resolve(), temp_dir)

            _require_ok(
                _run([
                    *DOCKER_PREFIX, "run", "--rm", "-d", "--name", pg_name, "--network", "none",
                    "-e", "POSTGRES_HOST_AUTH_METHOD=trust", POSTGRES_IMAGE,
                ]),
                "criação do PostgreSQL temporário",
            )
            created.append(pg_name)
            _wait(docker_command("exec", pg_name, "pg_isready", "-U", "postgres", "-d", "postgres"))
            _require_ok(_run(docker_command("exec", pg_name, "createdb", "-U", "postgres", "restore_target")), "createdb")
            if pg_staged.suffix.lower() == ".dump":
                restore_pg = _run(
                    docker_command(
                        "exec", "-i", pg_name, "pg_restore", "--no-owner", "--no-privileges",
                        "-U", "postgres", "-d", "restore_target",
                    ),
                    stdin_path=pg_staged,
                )
            else:
                restore_pg = _run(
                    docker_command("exec", "-i", pg_name, "psql", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "restore_target"),
                    stdin_path=pg_staged,
                )
            _require_ok(restore_pg, "restauração PostgreSQL")
            pg_counts = _query_counts_postgres(pg_name, list(policy["required_backup_tables"]["postgresql"]))

            # Não mantenha dois SGBDs efêmeros simultâneos em estações com pouca
            # memória. O alvo PostgreSQL já foi verificado e pode ser removido
            # antes de iniciar o MariaDB, sem tocar os containers vivos.
            _require_ok(_run(docker_command("rm", "-f", pg_name), timeout=20.0), "remoção do PostgreSQL temporário")
            created.remove(pg_name)

            _require_ok(
                _run([
                    *DOCKER_PREFIX, "run", "--rm", "-d", "--name", maria_name, "--network", "none",
                    "-e", "MARIADB_ALLOW_EMPTY_ROOT_PASSWORD=1", MARIADB_IMAGE,
                ]),
                "criação do MariaDB temporário",
            )
            created.append(maria_name)
            _wait_mariadb_final(maria_name)
            _require_ok(
                _run(docker_command("exec", maria_name, "mariadb", "-uroot", "-e", "CREATE DATABASE glpi_restore;")),
                "criação do banco MariaDB temporário",
            )
            _require_ok(
                _run(docker_command("cp", str(maria_staged), f"{maria_name}:/tmp/restore.sql")),
                "staging do dump no MariaDB temporário",
            )
            staged_hash_output = _require_ok(
                _run(docker_command("exec", maria_name, "sha256sum", "/tmp/restore.sql")),
                "hash do dump dentro do MariaDB temporário",
            )
            staged_hash = staged_hash_output.split()[0].lower()
            if staged_hash != maria_hash:
                raise RuntimeError("hash do dump divergiu após a cópia para o container")
            restore_maria = _run(
                [
                    *DOCKER_PREFIX,
                    "exec",
                    maria_name,
                    "mariadb",
                    "-uroot",
                    "glpi_restore",
                    "-e",
                    "source /tmp/restore.sql",
                ],
            )
            if restore_maria["returncode"] != 0:
                logs = _run(docker_command("logs", "--tail", "200", maria_name), timeout=20.0)
                detail = (logs["stderr"] or logs["stdout"] or "logs indisponíveis")[-4000:]
                message = (restore_maria["stderr"] or restore_maria["stdout"] or "sem detalhe")[-2000:]
                raise RuntimeError(f"restauração MariaDB falhou: {message}; logs do alvo: {detail}")
            maria_counts = _query_counts_mariadb(maria_name, list(policy["required_backup_tables"]["mariadb"]))
            return {
                "status": "PASS",
                "evidence_status": policy["evidence_labels"]["restore_drill"],
                "scientific_result": False,
                "live_services_touched": False,
                "isolated_targets": {"network": "none", "published_ports": 0},
                "resource_strategy": resource_strategy,
                "artifacts": {
                    "postgresql": {"path": str(postgres_artifact.resolve()), "sha256": pg_hash, "row_counts": pg_counts},
                    "mariadb": {
                        "path": str(mariadb_artifact.resolve()),
                        "sha256": maria_hash,
                        "container_staging_sha256": staged_hash,
                        "row_counts": maria_counts,
                    },
                },
                "duration_seconds": time.perf_counter() - started,
                "interpretation_limit": (
                    "Prova somente que estes artefatos restauraram nos alvos efêmeros e que as tabelas exigidas "
                    "foram consultáveis. init_v9.sql restaura esquema, não dados vivos nem o volume n8n."
                ),
            }
    finally:
        for name in reversed(created):
            _run(docker_command("rm", "-f", name), timeout=20.0)


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    policy = load_policy(args.policy)
    present = {
        "postgresql": args.postgres_artifact.is_file(),
        "mariadb": args.mariadb_artifact.is_file(),
    }
    return {
        "schema_version": "1.0.0",
        "generated_at": utc_now(),
        "mode": "APPLY_ISOLATED" if args.apply else "DRY_RUN",
        "status": "READY_TO_APPLY" if all(present.values()) else "BLOCKED_MISSING_ARTIFACT",
        "live_services_touched": False,
        "artifacts": {
            "postgresql": {"path": str(args.postgres_artifact.resolve()), "exists": present["postgresql"]},
            "mariadb": {"path": str(args.mariadb_artifact.resolve()), "exists": present["mariadb"]},
        },
        "temporary_target_controls": {
            "random_container_names": True,
            "network": "none",
            "published_ports": 0,
            "cleanup_in_finally": True,
            "resource_strategy": "SEQUENTIAL_EPHEMERAL_DATABASES",
            "pinned_images": [POSTGRES_IMAGE, MARIADB_IMAGE],
        },
        "required_tables": policy["required_backup_tables"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    plan = build_plan(args)
    if args.apply:
        if plan["status"] != "READY_TO_APPLY":
            parser.error("os dois artefatos devem existir antes de --apply")
        try:
            plan["result"] = execute_drill(args.postgres_artifact, args.mariadb_artifact, load_policy(args.policy))
            plan["status"] = plan["result"]["status"]
        except (OSError, RuntimeError, ValueError) as exc:
            plan["status"] = "FAIL"
            plan["error"] = str(exc)
    if args.output:
        write_json(args.output, plan)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0 if plan["status"] in {"READY_TO_APPLY", "PASS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
