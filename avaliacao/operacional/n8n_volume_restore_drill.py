from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from avaliacao.operacional.core import sha256_file, utc_now, write_json


N8N_IMAGE = "n8nio/n8n:2.10.3@sha256:7d90cdb066ae31f08776b0f8287d33102c4b55d7d0173faf5edb5767c94d2b83"
SAFE_VOLUME_PREFIX = "projeto-ic-restore-n8n-"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backup consistente e restore isolado do volume n8n")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=PROJECT_ROOT / "avaliacao" / "runtime" / "backups",
    )
    parser.add_argument("--output", type=Path)
    return parser


LOCAL_DOCKER_CONTEXT = os.getenv("DOCKER_CONTEXT", "desktop-linux")
os.environ["DOCKER_CONTEXT"] = LOCAL_DOCKER_CONTEXT


def _run(command: Sequence[str], *, timeout: float = 300.0) -> dict[str, Any]:
    cmd = list(command)
    if cmd and cmd[0] == "docker" and (len(cmd) < 2 or cmd[1] != "--context"):
        cmd = ["docker", "--context", LOCAL_DOCKER_CONTEXT, *cmd[1:]]
    completed = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, check=False,
    )
    return {"returncode": completed.returncode, "stdout": completed.stdout.strip(), "stderr": completed.stderr.strip()}


def _ok(command: Sequence[str], step: str, *, timeout: float = 300.0) -> str:
    result = _run(command, timeout=timeout)
    if result["returncode"] != 0:
        detail = (result["stderr"] or result["stdout"] or "sem detalhe")[-2000:]
        raise RuntimeError(f"{step} falhou: {detail}")
    return str(result["stdout"])


def _live_volume_name() -> str:
    output = _ok(
        [
            "docker", "inspect", "n8n", "--format",
            '{{range .Mounts}}{{if eq .Destination "/home/node/.n8n"}}{{.Name}}{{end}}{{end}}',
        ],
        "inspeção do volume n8n",
    ).strip()
    if not output or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for character in output):
        raise RuntimeError("Nome do volume n8n ausente ou inválido")
    return output


def _wait_n8n_healthy(timeout_seconds: float = 120.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        state = _run(["docker", "inspect", "n8n", "--format", "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}"], timeout=5)
        if state["returncode"] == 0 and state["stdout"].strip() == "healthy":
            return
        time.sleep(2)
    raise RuntimeError("n8n vivo não recuperou healthcheck no prazo")


def execute(backup_dir: Path) -> dict[str, Any]:
    backup_dir = backup_dir.resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    live_volume = _live_volume_name()
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    artifact = backup_dir / f"n8n-volume-{stamp}.tar"
    temporary_volume = SAFE_VOLUME_PREFIX + uuid.uuid4().hex[:12]
    created = False
    stopped = False
    started = time.perf_counter()
    recovery_started: float | None = None
    try:
        _ok(["docker", "stop", "n8n"], "parada consistente do n8n", timeout=60)
        stopped = True
        recovery_started = time.perf_counter()
        _ok(
            [
                "docker", "run", "--rm", "--network", "none", "--user", "0:0",
                "--entrypoint", "sh", "-v", f"{live_volume}:/source:ro",
                "-v", f"{backup_dir}:/backup", N8N_IMAGE, "-c",
                # Cache de UI, traces e exports redundantes não são estado
                # restaurável. Banco, chave/configuração e dados binários são.
                f"cd /source && tar -cf /backup/{artifact.name} "
                "database.sqlite database.sqlite-wal database.sqlite-shm config "
                "binaryData storage nodes git ssh 2>/dev/null",
            ],
            "criação do arquivo do volume n8n",
        )
        _ok(["docker", "start", "n8n"], "reinício do n8n", timeout=60)
        stopped = False
        _wait_n8n_healthy()
        recovery_minutes = (time.perf_counter() - recovery_started) / 60.0
        if not artifact.is_file() or artifact.stat().st_size <= 0:
            raise RuntimeError("Artefato do volume n8n ausente ou vazio")
        artifact_hash = sha256_file(artifact)

        _ok(["docker", "volume", "create", temporary_volume], "criação do volume isolado")
        created = True
        _ok(
            [
                "docker", "run", "--rm", "--network", "none", "--user", "0:0",
                "--entrypoint", "sh", "-v", f"{temporary_volume}:/restore",
                "-v", f"{backup_dir}:/backup:ro", N8N_IMAGE, "-c",
                f"tar -C /restore -xf /backup/{artifact.name} && test -s /restore/database.sqlite",
            ],
            "restore isolado do volume n8n",
        )
        with tempfile.TemporaryDirectory(prefix="projeto_ic_n8n_verify_") as temp_name:
            verify_dir = Path(temp_name).resolve()
            _ok(
                [
                    # Executar como o usuário da imagem é essencial: sob root, o
                    # n8n usa /root/.n8n e validaria um banco vazio por engano.
                    "docker", "run", "--rm", "--network", "none",
                    "-v", f"{temporary_volume}:/home/node/.n8n",
                    "-v", f"{verify_dir}:/evidence", N8N_IMAGE,
                    "export:workflow", "--all", "--output=/evidence/workflows.json",
                ],
                "leitura dos workflows no volume restaurado",
            )
            exported = json.loads((verify_dir / "workflows.json").read_text(encoding="utf-8"))
            workflow_count = len(exported) if isinstance(exported, list) else 1
        return {
            "status": "PASS",
            "executed_at": utc_now(),
            "evidence_status": "ISOLATED_N8N_VOLUME_BACKUP_RESTORE_DRILL",
            "scientific_result": False,
            "semantic_correctness_confirmed": False,
            "live_volume": live_volume,
            "artifact": {"path": str(artifact), "sha256": artifact_hash, "bytes": artifact.stat().st_size},
            "isolated_restore": {
                "temporary_volume_prefix": SAFE_VOLUME_PREFIX,
                "network": "none",
                "published_ports": 0,
                "database_sqlite_nonempty": True,
                "exported_workflow_count": workflow_count,
                "included_runtime_state": [
                    "database.sqlite", "database.sqlite-wal", "database.sqlite-shm",
                    "config", "binaryData", "storage", "nodes", "git", "ssh",
                ],
                "excluded_transient_content": [".cache", "trace", "nested_legacy_exports"],
            },
            "rollback_recovery_minutes": recovery_minutes,
            "duration_seconds": time.perf_counter() - started,
            "interpretation_limit": "Comprova restauração técnica deste snapshot; não comprova RPO/RTO institucional nem correção semântica.",
        }
    finally:
        if stopped:
            _run(["docker", "start", "n8n"], timeout=60)
        if created:
            if not temporary_volume.startswith(SAFE_VOLUME_PREFIX):
                raise RuntimeError("Bloqueio de segurança: volume temporário fora do prefixo esperado")
            _run(["docker", "volume", "rm", temporary_volume], timeout=60)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "generated_at": utc_now(),
        "mode": "APPLY" if args.apply else "DRY_RUN",
        "status": "READY_TO_APPLY" if not args.apply else "RUNNING",
        "live_service_short_stop_required": True,
        "temporary_target": {"network": "none", "published_ports": 0, "volume_prefix": SAFE_VOLUME_PREFIX},
    }
    if args.apply:
        try:
            report["result"] = execute(args.backup_dir)
            report["status"] = report["result"]["status"]
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            report["status"] = "FAIL"
            report["error"] = str(exc)
    if args.output:
        write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"READY_TO_APPLY", "PASS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
