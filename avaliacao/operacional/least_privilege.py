from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from avaliacao.operacional.core import ROOT, sha256_file, utc_now, write_json  # noqa: E402


SQL_PATH = Path(__file__).with_name("sql") / "postgres_menor_privilegio.sql"
ROLE_FIELDS = ("rolsuper", "rolcreaterole", "rolcreatedb", "rolreplication", "rolbypassrls", "rolcanlogin")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audita menor privilégio; a remediação transacional só ocorre com --apply."
    )
    parser.add_argument("--live-read-only", action="store_true")
    parser.add_argument("--container", default="glpi-dedup-db")
    parser.add_argument("--database", default="triagem")
    parser.add_argument("--audit-login", default="triagem_app")
    parser.add_argument("--runtime-login", default=os.environ.get("OPERACIONAL_PG_RUNTIME_LOGIN", "triagem_app"))
    parser.add_argument("--admin-dsn-env", default="OPERACIONAL_PG_ADMIN_DSN")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser


LOCAL_DOCKER_CONTEXT = os.getenv("DOCKER_CONTEXT", "desktop-linux")
os.environ["DOCKER_CONTEXT"] = LOCAL_DOCKER_CONTEXT


def _run(command: Sequence[str]) -> dict[str, Any]:
    cmd = list(command)
    if cmd and cmd[0] == "docker" and (len(cmd) < 2 or cmd[1] != "--context"):
        cmd = ["docker", "--context", LOCAL_DOCKER_CONTEXT, *cmd[1:]]
    completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    return {"returncode": completed.returncode, "stdout": completed.stdout.strip(), "stderr": completed.stderr.strip()}


def role_assessment(role: dict[str, Any]) -> dict[str, Any]:
    dangerous = [field for field in ROLE_FIELDS[:-1] if bool(role.get(field))]
    status = "FAIL" if dangerous else "PASS"
    return {
        "status": status,
        "role": role.get("rolname"),
        "dangerous_attributes": dangerous,
        "attributes": {field: bool(role.get(field)) for field in ROLE_FIELDS},
        "required": "runtime LOGIN sem SUPERUSER/CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS e sem propriedade do esquema",
    }


def static_audit(root: Path = ROOT) -> dict[str, Any]:
    compose = (root / "n8n" / "docker-compose.yml").read_text(encoding="utf-8")
    wf05 = (root / "n8n" / "workflows" / "Versão9" / "V9-WF05-Metricas.json").read_text(encoding="utf-8")
    bootstrap_runtime_same = "POSTGRES_USER=${POSTGRES_USER:-triagem_user}" in compose
    runtime_ddl = sorted({token for token in ("CREATE TABLE", "ALTER TABLE", "CREATE OR REPLACE VIEW") if token in wf05})
    return {
        "status": "FAIL" if bootstrap_runtime_same or runtime_ddl else "PASS",
        "bootstrap_and_runtime_same_role": bootstrap_runtime_same,
        "runtime_workflow_ddl_tokens": runtime_ddl,
        "apply_blocked": bool(runtime_ddl),
        "required_remediation_order": [
            "mover DDL do WF05 para migração administrada",
            "provisionar credencial admin fora da CLI",
            "aplicar roles migration_owner/runtime em transação",
            "comprovar negação de CREATE TABLE sob o login runtime",
            "reiniciar somente em janela aprovada e validar rollback",
        ],
    }


def live_audit(container: str, database: str, login: str) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", container) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", login):
        raise ValueError("container/login inválido")
    query = (
        "SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls, rolcanlogin "
        "FROM pg_roles WHERE rolname = current_user;"
    )
    result = _run(["docker", "exec", container, "psql", "-U", login, "-d", database, "-At", "-F", "|", "-c", query])
    if result["returncode"] != 0:
        return {"status": "INDETERMINATE", "error": result["stderr"][-1000:] or "consulta falhou"}
    fields = result["stdout"].split("|")
    if len(fields) != 7:
        return {"status": "INDETERMINATE", "error": "resposta inesperada do catálogo PostgreSQL"}
    role = {"rolname": fields[0]}
    role.update({name: value == "t" for name, value in zip(ROLE_FIELDS, fields[1:], strict=True)})
    return role_assessment(role)


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _rollback_text(
    runtime_login: str,
    role_before: dict[str, Any],
    owners: list[tuple[str, str, str, str]],
) -> str:
    enabled = [
        keyword
        for field, keyword in (
            ("rolsuper", "SUPERUSER"), ("rolcreaterole", "CREATEROLE"), ("rolcreatedb", "CREATEDB"),
            ("rolreplication", "REPLICATION"), ("rolbypassrls", "BYPASSRLS"),
        )
        if role_before.get(field)
    ]
    disabled = [
        keyword
        for field, keyword in (
            ("rolsuper", "NOSUPERUSER"), ("rolcreaterole", "NOCREATEROLE"), ("rolcreatedb", "NOCREATEDB"),
            ("rolreplication", "NOREPLICATION"), ("rolbypassrls", "NOBYPASSRLS"),
        )
        if not role_before.get(field)
    ]
    lines = [
        "-- PLANO DE ROLLBACK GERADO ANTES DA MUDANÇA. NÃO EXECUTAR SEM APROVAÇÃO.",
        "BEGIN;",
        f"REVOKE triagem_runtime FROM {_quote_ident(runtime_login)};",
        f"ALTER ROLE {_quote_ident(runtime_login)} {' '.join(enabled + disabled)};",
    ]
    commands = {"r": "ALTER TABLE", "p": "ALTER TABLE", "v": "ALTER VIEW", "m": "ALTER MATERIALIZED VIEW", "S": "ALTER SEQUENCE", "f": "ALTER FOREIGN TABLE"}
    for schema, name, owner, kind in owners:
        lines.append(f"{commands[kind]} {_quote_ident(schema)}.{_quote_ident(name)} OWNER TO {_quote_ident(owner)};")
    lines.extend(["COMMIT;", "-- Após rollback: revalidar saúde, permissões, fila, DLQ e um cenário sombra."])
    return "\n".join(lines) + "\n"


def apply_remediation(admin_dsn: str, runtime_login: str, output: Path) -> dict[str, Any]:
    import psycopg2
    from psycopg2 import sql

    connection = psycopg2.connect(admin_dsn)
    connection.autocommit = False
    rollback_path = output.with_suffix(".rollback.sql")
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user")
            admin_login = cursor.fetchone()[0]
            if admin_login == runtime_login:
                raise RuntimeError("o administrador deve ser uma credencial distinta do login runtime")
            cursor.execute(
                "SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls, rolcanlogin "
                "FROM pg_roles WHERE rolname = %s",
                (runtime_login,),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("o login runtime deve ser provisionado antes da migração")
            role_before = {"rolname": row[0], **dict(zip(ROLE_FIELDS, row[1:], strict=True))}
            cursor.execute(
                "SELECT n.nspname, c.relname, r.rolname, c.relkind FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_roles r ON r.oid=c.relowner "
                "WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','S','f') "
                "AND (c.relkind <> 'S' OR NOT EXISTS (SELECT 1 FROM pg_depend d "
                "WHERE d.classid='pg_class'::regclass AND d.objid=c.oid AND d.deptype IN ('a','i'))) "
                "ORDER BY 1,2"
            )
            owners = cursor.fetchall()
            rollback_path.parent.mkdir(parents=True, exist_ok=True)
            rollback_path.write_text(_rollback_text(runtime_login, role_before, owners), encoding="utf-8")
            cursor.execute(SQL_PATH.read_text(encoding="utf-8"))
            cursor.execute(sql.SQL("GRANT triagem_runtime TO {}").format(sql.Identifier(runtime_login)))
            cursor.execute(
                sql.SQL("ALTER ROLE {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS").format(
                    sql.Identifier(runtime_login)
                )
            )
            cursor.execute("SAVEPOINT ddl_denial")
            cursor.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(runtime_login)))
            denied = False
            try:
                cursor.execute("CREATE TABLE public.__operacional_ddl_deve_falhar(id integer)")
            except psycopg2.Error as exc:
                denied = exc.pgcode == "42501"
            cursor.execute("ROLLBACK TO SAVEPOINT ddl_denial")
            if not denied:
                raise RuntimeError("o teste de negação DDL não produziu insufficient_privilege; transação revertida")
        connection.commit()
        return {
            "status": "PASS",
            "runtime_login": runtime_login,
            "ddl_denial_sqlstate": "42501",
            "rollback_plan": str(rollback_path.resolve()),
            "rollback_plan_sha256": sha256_file(rollback_path),
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    static = static_audit()
    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "generated_at": utc_now(),
        "mode": "APPLY" if args.apply else "DRY_RUN",
        "scientific_result": False,
        "static_audit": static,
        "live_audit": live_audit(args.container, args.database, args.audit_login) if args.live_read_only else {"status": "NOT_REQUESTED"},
        "migration": {"path": str(SQL_PATH.resolve()), "sha256": sha256_file(SQL_PATH)},
        "remediation": {"status": "NOT_RUN", "reason": "Requer --apply e pré-condições satisfeitas."},
    }
    if args.apply:
        if args.output is None:
            parser.error("--apply exige --output para preservar relatório e plano de rollback")
        if static["apply_blocked"]:
            parser.error("DDL ainda está no WF05; separe migração antes de aplicar menor privilégio")
        admin_dsn = os.environ.get(args.admin_dsn_env, "")
        if not admin_dsn:
            parser.error(f"defina a credencial administrativa fora da CLI em {args.admin_dsn_env}")
        report["remediation"] = apply_remediation(admin_dsn, args.runtime_login, args.output)
    statuses = [static["status"], report["live_audit"].get("status"), report["remediation"].get("status")]
    report["status"] = "FAIL" if "FAIL" in statuses else "PASS" if report["remediation"].get("status") == "PASS" else "NOT_READY"
    if args.output:
        write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not args.apply or report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
