from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from avaliacao.operacional.core import project_env, utc_now


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reconcilia DLQs e ERRO_IA históricos sem apagar a trilha de auditoria"
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser


LOCAL_DOCKER_CONTEXT = os.getenv("DOCKER_CONTEXT", "desktop-linux")
os.environ["DOCKER_CONTEXT"] = LOCAL_DOCKER_CONTEXT


def _glpi_statuses(ticket_ids: list[int]) -> dict[int, int]:
    if not ticket_ids:
        return {}
    joined = ",".join(str(value) for value in sorted(set(ticket_ids)))
    sql = f"SELECT id,status FROM glpi_tickets WHERE id IN ({joined}) ORDER BY id;\n"
    command = [
        "docker",
        "--context",
        LOCAL_DOCKER_CONTEXT,
        "exec",
        "-i",
        "glpi-db",
        "sh",
        "-c",
        'MYSQL_PWD="$MYSQL_PASSWORD" mariadb -u "$MYSQL_USER" "$MYSQL_DATABASE" -N',
    ]
    completed = subprocess.run(
        command,
        input=sql,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("Não foi possível consultar o estado dos tickets no GLPI")
    result: dict[int, int] = {}
    for raw in completed.stdout.splitlines():
        parts = raw.split("\t")
        if len(parts) == 2:
            result[int(parts[0])] = int(parts[1])
    return result


def _id_digest(values: list[int]) -> str:
    canonical = ",".join(str(value) for value in sorted(values)).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def reconcile(*, apply: bool) -> dict[str, Any]:
    env = project_env(PROJECT_ROOT)
    connection = psycopg2.connect(
        host=env.get("POSTGRES_HOST", "127.0.0.1"),
        port=int(env.get("POSTGRES_PORT", "5432")),
        dbname=env.get("POSTGRES_DB", "triagem"),
        user=env.get("POSTGRES_RUNTIME_USER", "triagem_app"),
        password=env.get("POSTGRES_RUNTIME_PASSWORD", ""),
        connect_timeout=5,
        application_name="projeto_ic_historical_reconciliation",
    )
    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT t.id, t.triagem_status,
                       EXISTS (
                           SELECT 1
                           FROM dataset_controle dc
                           WHERE dc.ticket_id = t.id
                             AND UPPER(COALESCE(dc.split, '')) IN (
                                 'TEST', 'TESTE', 'BENCHMARK', 'CALIBRATION', 'CALIBRACAO'
                             )
                       ) AS synthetic_test
                FROM tickets_processados t
                WHERE triagem_status IN ('ERRO_IA', 'PENDENTE_IA')
                ORDER BY t.id
                FOR UPDATE
                """
            )
            error_rows = [dict(row) for row in cursor.fetchall()]
            ticket_ids = [int(row["id"]) for row in error_rows]
            erro_ia_ids = [
                int(row["id"]) for row in error_rows if row["triagem_status"] == "ERRO_IA"
            ]
            legacy_pending_ids = [
                int(row["id"]) for row in error_rows if row["triagem_status"] == "PENDENTE_IA"
            ]
            synthetic_test_ids = [
                int(row["id"]) for row in error_rows if bool(row.get("synthetic_test"))
            ]
            operational_ids = [ticket_id for ticket_id in ticket_ids if ticket_id not in synthetic_test_ids]
            statuses = _glpi_statuses(operational_ids)
            active_ids = [ticket_id for ticket_id in operational_ids if statuses.get(ticket_id) in {1, 4}]
            closed_ids = [ticket_id for ticket_id in operational_ids if statuses.get(ticket_id) == 6]
            other_ids = [
                ticket_id
                for ticket_id in operational_ids
                if ticket_id in statuses and statuses[ticket_id] not in {1, 4, 6}
            ]
            missing_ids = [ticket_id for ticket_id in operational_ids if ticket_id not in statuses]
            cursor.execute("SELECT COUNT(*) AS total, COUNT(DISTINCT ticket_id) AS tickets FROM fila_ia_dead_letter WHERE NOT resolvido")
            dlq_before = dict(cursor.fetchone() or {})

            report = {
                "schema_version": "1.0.0",
                "executed_at": utc_now(),
                "mode": "APPLY" if apply else "DRY_RUN",
                "evidence_status": "OPERATIONAL_RECONCILIATION_NOT_SEMANTIC_VALIDATION",
                "scientific_result": False,
                "semantic_correctness_confirmed": False,
                "before": {
                    "erro_ia_tickets": len(erro_ia_ids),
                    "legacy_pending_alias_tickets": len(legacy_pending_ids),
                    "open_dlq_rows": int(dlq_before.get("total") or 0),
                    "open_dlq_tickets": int(dlq_before.get("tickets") or 0),
                },
                "plan": {
                    "requeue_active_glpi": len(active_ids),
                    "archive_synthetic_test_without_glpi_mutation": len(synthetic_test_ids),
                    "archive_closed_glpi": len(closed_ids),
                    "archive_missing_glpi": len(missing_ids),
                    "leave_other_glpi_status_unchanged": len(other_ids),
                    "active_ticket_set_sha256": _id_digest(active_ids),
                },
                "interpretation_limit": (
                    "A reconciliação remove pendência operacional preservando DLQ e eventos. "
                    "Ela não transforma falhas em acertos e não confirma a classe semântica dos tickets."
                ),
            }
            if not apply:
                connection.rollback()
                report["status"] = "PLAN_READY"
                return report

            if active_ids:
                cursor.execute(
                    """
                    WITH latest_stage AS (
                        SELECT DISTINCT ON (ticket_id)
                            ticket_id,
                            CASE
                                WHEN etapa ILIKE 'CLASSIF%%' THEN 'CLASSIFICACAO'
                                ELSE 'DEDUPLICACAO'
                            END AS etapa
                        FROM (
                            SELECT ticket_id, etapa, criado_em
                            FROM fila_ia_dead_letter
                            WHERE ticket_id = ANY(%s)
                            UNION ALL
                            SELECT ticket_id, etapa, criado_em
                            FROM ia_decisoes
                            WHERE ticket_id = ANY(%s) AND erro_ia
                        ) source
                        ORDER BY ticket_id, criado_em DESC
                    )
                    UPDATE tickets_processados target
                    SET triagem_status = 'PENDENTE_FILA_IA',
                        fila_etapa = COALESCE(latest_stage.etapa, 'DEDUPLICACAO'),
                        fila_enfileirada_em = COALESCE(target.fila_enfileirada_em, NOW()),
                        fila_liberar_em = NOW(),
                        fila_disponivel_em = NOW(),
                        fila_reservada_em = NULL,
                        fila_tentativas = 0,
                        tentativas_ia_dedup = 0,
                        tentativas_ia_classificacao = 0,
                        fila_ultimo_erro = NULL,
                        ultimo_erro_ia = NULL,
                        atualizado_em = NOW()
                    FROM latest_stage
                    WHERE target.id = latest_stage.ticket_id
                      AND target.id = ANY(%s)
                    """,
                    (active_ids, active_ids, active_ids),
                )
                # Tickets ativos sem qualquer decisão/DLQ anterior também recebem etapa segura inicial.
                cursor.execute(
                    """
                    UPDATE tickets_processados
                    SET triagem_status = 'PENDENTE_FILA_IA',
                        fila_etapa = COALESCE(fila_etapa, 'DEDUPLICACAO'),
                        fila_enfileirada_em = COALESCE(fila_enfileirada_em, NOW()),
                        fila_liberar_em = NOW(),
                        fila_disponivel_em = NOW(),
                        fila_reservada_em = NULL,
                        fila_tentativas = 0,
                        tentativas_ia_dedup = 0,
                        tentativas_ia_classificacao = 0,
                        fila_ultimo_erro = NULL,
                        ultimo_erro_ia = NULL,
                        atualizado_em = NOW()
                    WHERE id = ANY(%s)
                      AND triagem_status IN ('ERRO_IA', 'PENDENTE_IA')
                    """,
                    (active_ids,),
                )
            if synthetic_test_ids:
                cursor.execute(
                    """
                    UPDATE tickets_processados
                    SET triagem_status = 'EXPERIMENTO_ENCERRADO',
                        fila_reservada_em = NULL,
                        fila_liberar_em = NULL,
                        fila_disponivel_em = NULL,
                        fila_ultimo_erro = NULL,
                        ultimo_erro_ia = NULL,
                        atualizado_em = NOW()
                    WHERE id = ANY(%s)
                    """,
                    (synthetic_test_ids,),
                )
            if closed_ids:
                cursor.execute(
                    """
                    UPDATE tickets_processados
                    SET triagem_status = 'ARQUIVADO_ERRO_IA_GLPI_FECHADO',
                        fila_reservada_em = NULL,
                        fila_disponivel_em = NULL,
                        atualizado_em = NOW()
                    WHERE id = ANY(%s)
                    """,
                    (closed_ids,),
                )
            if missing_ids:
                cursor.execute(
                    """
                    UPDATE tickets_processados
                    SET triagem_status = 'ARQUIVADO_ERRO_IA_SEM_GLPI',
                        fila_reservada_em = NULL,
                        fila_disponivel_em = NULL,
                        atualizado_em = NOW()
                    WHERE id = ANY(%s)
                    """,
                    (missing_ids,),
                )

            cursor.execute(
                """
                UPDATE fila_ia_dead_letter
                SET resolvido = TRUE,
                    resolvido_em = NOW(),
                    payload_contexto = jsonb_set(
                        COALESCE(payload_contexto, '{}'::jsonb),
                        '{formal_resolution}',
                        jsonb_build_object(
                            'code', 'HISTORICAL_RECONCILIATION_20260902',
                            'resolved_at', NOW(),
                            'semantic_validation', FALSE,
                            'action', CASE
                                WHEN ticket_id = ANY(%s) THEN 'ARCHIVED_SYNTHETIC_TEST_NO_GLPI_MUTATION'
                                WHEN ticket_id = ANY(%s) THEN 'REQUEUED'
                                WHEN ticket_id = ANY(%s) THEN 'ARCHIVED_GLPI_CLOSED'
                                WHEN ticket_id = ANY(%s) THEN 'ARCHIVED_GLPI_MISSING'
                                ELSE 'NO_AUTOMATIC_ACTION_OTHER_GLPI_STATUS'
                            END
                        ),
                        TRUE
                    )
                WHERE NOT resolvido
                """,
                (synthetic_test_ids, active_ids, closed_ids, missing_ids),
            )
            affected_ids = synthetic_test_ids + active_ids + closed_ids + missing_ids
            if affected_ids:
                cursor.execute(
                    """
                    INSERT INTO workflow_eventos (
                        ticket_id, workflow, node_name, fase, acao, status_evento,
                        status_anterior, status_novo, mensagem_erro, criado_em
                    )
                    SELECT id, 'RECONCILIACAO_HISTORICA', 'script_controlado',
                           'OPERACIONAL', 'RECONCILIAR_ERRO_IA', 'CONCLUIDO',
                           'ERRO_IA_OU_PENDENTE_IA_LEGADO', triagem_status,
                           'Sem validação semântica; trilha histórica preservada.', NOW()
                    FROM tickets_processados
                    WHERE id = ANY(%s)
                    """,
                    (affected_ids,),
                )
            connection.commit()

            cursor.execute("SELECT COUNT(*) AS total FROM fila_ia_dead_letter WHERE NOT resolvido")
            open_after = int((cursor.fetchone() or {}).get("total") or 0)
            cursor.execute("SELECT COUNT(*) AS total FROM tickets_processados WHERE triagem_status = 'ERRO_IA'")
            errors_after = int((cursor.fetchone() or {}).get("total") or 0)
            cursor.execute("SELECT COUNT(*) AS total FROM tickets_processados WHERE triagem_status = 'PENDENTE_IA'")
            legacy_pending_after = int((cursor.fetchone() or {}).get("total") or 0)
            cursor.execute("SELECT COUNT(*) AS total FROM tickets_processados WHERE triagem_status = 'PENDENTE_FILA_IA'")
            pending_after = int((cursor.fetchone() or {}).get("total") or 0)
            report["after"] = {
                "open_dlq_rows": open_after,
                "erro_ia_tickets": errors_after,
                "legacy_pending_alias_tickets": legacy_pending_after,
                "pending_ai_tickets": pending_after,
            }
            report["status"] = (
                "PASS"
                if open_after == 0
                and errors_after == len(other_ids)
                and legacy_pending_after == 0
                else "FAIL"
            )
            return report
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.apply and args.output is None:
        raise SystemExit("--apply exige --output para persistir a trilha da reconciliação")
    report = reconcile(apply=args.apply)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report.get("status") in {"PASS", "PLAN_READY"} else 1


if __name__ == "__main__":
    sys.exit(main())
