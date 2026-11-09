"""Recuperação restrita de E2E sintético interrompido; preserva o relatório original."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hmac
import json
from pathlib import Path

import requests
import validar_pipeline_fila_e2e as e2e
from isolamento_experimentos import EXPERIMENT_LOCK_KEY


def load_evidence(path: Path) -> dict:
    source = path.resolve()
    source.relative_to(e2e.ROOT)
    payload = json.loads(source.read_text(encoding="utf-8"))
    digest = payload.get("evidence_payload_sha256", "")
    unsigned = {**payload, "evidence_payload_sha256": None}
    if not hmac.compare_digest(digest, e2e.canonical_sha256(unsigned)):
        raise RuntimeError("Hash do relatório original inválido")
    e2e.validate_run_id(payload["run_id"])
    if payload.get("synthetic_only") is not True or payload.get("passed") is not False:
        raise RuntimeError("Recuperação exige evidência de E2E sintético falho")
    if set(payload.get("runtime_profile", {})) != set(e2e.PROFILE_KEYS):
        raise RuntimeError("Snapshot de perfil incompleto")
    return payload


def recover(source: Path, output: Path) -> dict:
    output = e2e.validate_output_path(output)
    original = load_evidence(source)
    run_id, ticket_id = original["run_id"], int(original["ticket_id"])
    profile = original["runtime_profile"]
    config = e2e.require_config()
    observed = e2e.snapshot_runtime_profile()
    if observed not in (profile, e2e.scoped_runtime_profile(profile, run_id)):
        raise RuntimeError("Perfil atual não pertence ao E2E; recusada sobrescrita")
    result = {
        "source_sha256": e2e.file_sha256(source), "run_id": run_id,
        "ticket_id": ticket_id, "scientific_result": False,
        "semantic_correctness_confirmed": False,
        "started_at": datetime.now(timezone.utc).isoformat(), "passed": False,
    }
    connection = e2e.database.connect_pg()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", (EXPERIMENT_LOCK_KEY,))
            if not e2e._first_value(cursor.fetchone()):
                raise RuntimeError("Outro experimento possui a trava")
            cursor.execute("SELECT run_id FROM experimentos_avaliacao WHERE status IN ('EXECUTANDO','CALIBRANDO') AND run_id <> %s", (run_id,))
            if cursor.fetchall():
                raise RuntimeError("Outro experimento ativo impede recuperação")
        connection.commit()
        e2e.wait_no_active_n8n_executions(config["n8n_url"], config["n8n_user"], config["n8n_password"], timeout=180, poll=2)
        with e2e.queue_reservation_lock() as locked:
            e2e.assert_no_eligible_foreign_queue()
            with e2e.GlpiSession(config["glpi_url"], config["glpi_app_token"], config["glpi_auth_basic"], 20) as glpi:
                try:
                    glpi.get_ticket(ticket_id)
                except requests.HTTPError as exc:
                    if exc.response is None or exc.response.status_code not in (404, 410):
                        raise
                else:
                    # Não remove um ticket ainda existente: esta recuperação é
                    # destinada ao caso com purge anterior comprovado.
                    raise RuntimeError("Ticket ainda existe no GLPI; recuperação recusada")
            result["glpi_absent"] = True
            e2e.restore_controller(locked, original["controller"])
            e2e.recreate_n8n(profile)
            e2e.assert_profile_exact(profile)
            result["runtime_profile_restored"] = True
            result["controller_restored"] = e2e.scalar(e2e.controller_snapshot(locked)) == original["controller"]
            if not result["controller_restored"]:
                raise RuntimeError("Controlador não foi restaurado")
            result["database_deleted"] = e2e.cleanup_database(locked, run_id, ticket_id)
            result["passed"] = result["controller_restored"]
    except Exception as exc:
        # Sem imprimir respostas, tokens ou DSNs.
        result["error_type"] = type(exc).__name__
        raise
    finally:
        connection.close()  # libera advisory lock também em falha
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        e2e.write_report(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--executar", action="store_true")
    parser.add_argument("--confirmacao", default="")
    args = parser.parse_args()
    if not args.executar:
        original = load_evidence(args.source)
        print(json.dumps({"status": "DRY_RUN", "run_id": original["run_id"]}))
        return 0
    if args.confirmacao != "RECUPERAR_E2E_SINTETICO_INTERROMPIDO":
        parser.error("Confirmação de recuperação ausente")
    result = recover(args.source, args.output)
    print(json.dumps({"passed": result["passed"], "output": str(args.output)}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
