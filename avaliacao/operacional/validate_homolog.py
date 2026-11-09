from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    "homolog-glpi",
    "homolog-glpi-db",
    "homolog-glpi-dedup-db",
    "homolog-n8n",
    "homolog-n8n-gateway",
    "homolog-n8n-task-runners",
    "homolog-glpi-credential-proxy",
    "homolog-local-ai-credential-proxy",
    "homolog-mailpit",
}


LOCAL_DOCKER_CONTEXT = os.getenv("DOCKER_CONTEXT", "desktop-linux")
os.environ["DOCKER_CONTEXT"] = LOCAL_DOCKER_CONTEXT


def _run(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    cmd = list(command)
    if cmd and cmd[0] == "docker" and (len(cmd) < 2 or cmd[1] != "--context"):
        cmd = ["docker", "--context", LOCAL_DOCKER_CONTEXT, *cmd[1:]]
    return subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def _http(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return {"status": int(response.status), "ok": 200 <= response.status < 300}
    except (OSError, urllib.error.URLError) as exc:
        return {"status": 0, "ok": False, "error_type": type(exc).__name__}


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida a homologação sintética isolada.")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "avaliacao" / "resultados" / "operacional" / "homologacao-isolada-20260902.json",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(ROOT.resolve())
    if output.exists():
        raise RuntimeError(f"Evidência já existe: {output}")

    inspect = _run(
        [
            "docker",
            "inspect",
            "--format",
            "{{.Name}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{index .Config.Labels \"com.docker.compose.project\"}}",
            *sorted(EXPECTED),
        ]
    )
    containers: list[dict[str, str]] = []
    for line in inspect.stdout.splitlines():
        name, state, health, project = line.lstrip("/").split("|", 3)
        containers.append({"name": name, "state": state, "health": health, "project": project})

    role_query = _run(
        [
            "docker",
            "exec",
            "homolog-glpi-dedup-db",
            "sh",
            "-lc",
            "PGPASSWORD=\"$POSTGRES_RUNTIME_PASSWORD\" psql -U \"$POSTGRES_RUNTIME_USER\" -d \"$POSTGRES_DB\" -At -F '|' -c \"SELECT current_user,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user; SELECT count(*) FROM information_schema.tables WHERE table_schema='public'; SELECT count(*) FROM tickets_processados;\"",
        ]
    )
    role_lines = role_query.stdout.splitlines()
    flags = role_lines[0].split("|") if role_lines else []
    postgres = {
        "runtime_role": flags[0] if flags else None,
        "superuser": flags[1] == "t" if len(flags) > 1 else None,
        "createdb": flags[2] == "t" if len(flags) > 2 else None,
        "createrole": flags[3] == "t" if len(flags) > 3 else None,
        "replication": flags[4] == "t" if len(flags) > 4 else None,
        "bypassrls": flags[5] == "t" if len(flags) > 5 else None,
        "public_table_count": int(role_lines[1]) if len(role_lines) > 1 else None,
        "ticket_count": int(role_lines[2]) if len(role_lines) > 2 else None,
        "query_ok": role_query.returncode == 0,
    }
    probes = {
        "n8n": _http("http://127.0.0.1:15678/healthz"),
        "glpi": _http("http://127.0.0.1:19080/"),
        "mailpit": _http("http://127.0.0.1:28025/"),
    }
    names = {row["name"] for row in containers}
    isolated = all(row["project"] == "projeto-ic-homolog" for row in containers)
    healthy = all(
        row["state"] == "running" and row["health"] in {"healthy", "none"}
        for row in containers
    )
    least_privilege = postgres["query_ok"] and not any(
        postgres[key] for key in ("superuser", "createdb", "createrole", "replication", "bypassrls")
    )
    passed = (
        names == EXPECTED
        and isolated
        and healthy
        and least_privilege
        and postgres["ticket_count"] == 0
        and all(value["ok"] for value in probes.values())
    )
    result = {
        "schema_version": "1.0.0",
        "status": "PASS" if passed else "FAIL",
        "scope": "ISOLATED_SYNTHETIC_INFRASTRUCTURE_HOMOLOGATION",
        "scientific_result": False,
        "semantic_correctness_confirmed": False,
        "production_data_copied": False,
        "secrets_printed": False,
        "containers": containers,
        "project_isolation": isolated,
        "postgres": postgres,
        "http_probes": probes,
        "application_seed_status": "NOT_SEEDED_WITH_PRODUCTION_DATA_BY_DESIGN",
        "interpretation_limit": (
            "Confirma infraestrutura isolada, saúde e menor privilégio. Não equivale a aceite de produção, "
            "não contém chamados reais e não confirma semântica do modelo."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(output)}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
