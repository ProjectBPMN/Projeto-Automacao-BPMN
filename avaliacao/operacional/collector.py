from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import psycopg2
from psycopg2.extras import RealDictCursor

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from avaliacao.operacional.core import (
    ROOT,
    collect_live_point_in_time,
    evaluate_drift,
    evaluate_slo,
    load_policy,
    percentile,
    project_env,
    sha256_file,
    snapshot_from_rows,
    utc_now,
)


DEFAULT_RUNTIME_DIR = ROOT / "avaliacao" / "runtime" / "monitoring"
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Coleta pontual e cumulativa de SLO/drift do projeto IC")
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR)
    parser.add_argument("--policy", type=Path, default=None)
    return parser


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _database_observation(
    env: Mapping[str, str], *, interval_start: datetime | None = None
) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    connection = psycopg2.connect(
        host=env.get("POSTGRES_HOST", "127.0.0.1"),
        port=int(env.get("POSTGRES_PORT", "5432")),
        dbname=env.get("POSTGRES_DB", "triagem"),
        user=env.get("POSTGRES_RUNTIME_USER", "triagem_app"),
        password=env.get("POSTGRES_RUNTIME_PASSWORD", ""),
        connect_timeout=3,
        application_name="projeto_ic_monitoring_collector",
    )
    try:
        connection.set_session(readonly=True, autocommit=False, isolation_level="REPEATABLE READ")
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT NOW() AS observation_end")
            interval_end = (cursor.fetchone() or {})["observation_end"].astimezone(timezone.utc)
            interval_start = interval_start or interval_end
            cursor.execute(
                """
                SELECT id, criado_em, predicao, etapa, confianca, erro_ia, tempo_resposta_ms
                FROM ia_decisoes
                WHERE criado_em >= %s AND criado_em < %s
                ORDER BY criado_em, id
                """,
                (interval_start, interval_end),
            )
            interval_rows = [dict(row) for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE criado_em >= NOW() - INTERVAL '30 days') AS decisoes_30d,
                    COUNT(*) FILTER (WHERE criado_em >= NOW() - INTERVAL '30 days' AND erro_ia) AS erros_30d,
                    percentile_cont(0.95) WITHIN GROUP (ORDER BY tempo_resposta_ms)
                        FILTER (WHERE criado_em >= NOW() - INTERVAL '30 days' AND tempo_resposta_ms IS NOT NULL)
                        AS inferencia_p95_ms
                FROM ia_decisoes
                """
            )
            decision_metrics = dict(cursor.fetchone() or {})
            cursor.execute("SELECT COUNT(*) AS total FROM fila_ia_dead_letter WHERE NOT resolvido")
            open_dlq = int((cursor.fetchone() or {}).get("total") or 0)
            cursor.execute(
                """
                SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY espera_p95_segundos) AS espera_p95
                FROM fila_ia_metricas
                WHERE criado_em >= NOW() - INTERVAL '30 days'
                """
            )
            queue_wait = (cursor.fetchone() or {}).get("espera_p95")
            cursor.execute(
                """
                SELECT predicao, etapa, confianca, erro_ia
                FROM ia_decisoes
                WHERE criado_em < %s
                ORDER BY criado_em DESC, id DESC
                LIMIT 400
                """,
                (interval_start,),
            )
            decision_rows = [dict(row) for row in cursor.fetchall()]
    finally:
        connection.close()

    elapsed_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000.0
    total = int(decision_metrics.get("decisoes_30d") or 0)
    errors = int(decision_metrics.get("erros_30d") or 0)
    current_rows = decision_rows[:200]
    reference_rows = decision_rows[200:400]
    return {
        "available": True,
        "latency_ms": elapsed_ms,
        "decisions_30d": total,
        "technical_errors_30d": errors,
        "technical_error_rate_30d": errors / total if total else None,
        "local_ai_inference_p95_ms_30d": (
            float(decision_metrics["inferencia_p95_ms"])
            if decision_metrics.get("inferencia_p95_ms") is not None
            else None
        ),
        "queue_wait_p95_seconds_30d": float(queue_wait) if queue_wait is not None else None,
        "open_dead_letters": open_dlq,
        "reference_snapshot": snapshot_from_rows(reference_rows),
        "current_snapshot": snapshot_from_rows(current_rows),
        "snapshot_partition": "NON_OVERLAPPING_NEWEST_200_VS_PREVIOUS_200",
        "historical_metrics_scope": "ROLLING_30_DAYS_CONTEXT_NOT_WINDOW_EVIDENCE",
        "historical_snapshots_scope": "MOST_RECENT_400_BEFORE_INTERVAL_NOT_NEW_OBSERVATIONS",
        "interval": {
            "start": interval_start.isoformat().replace("+00:00", "Z"),
            "end": interval_end.isoformat().replace("+00:00", "Z"),
            "bounds": "START_INCLUSIVE_END_EXCLUSIVE",
            "complete": True,
            "decision_events": [
                {
                    **row,
                    "criado_em": row["criado_em"].astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "confianca": float(row["confianca"]) if row.get("confianca") is not None else None,
                }
                for row in interval_rows
            ],
            "reference_snapshot": snapshot_from_rows(current_rows),
            "current_snapshot": snapshot_from_rows(interval_rows),
            "interpretation_limit": (
                "Registros são reconciliados novamente desde o início da série por criado_em; "
                "a janela só fecha após a defasagem configurada para capturar commits tardios."
            ),
        },
    }


def _backup_restore_age_hours(root: Path) -> float | None:
    latest: datetime | None = None
    for path in (root / "avaliacao" / "resultados" / "operacional").glob("*restore*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("status") != "PASS":
                continue
            result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            stamp = (
                payload.get("collected_at")
                or payload.get("executed_at")
                or result.get("executed_at")
                or payload.get("generated_at")
            )
            if not stamp:
                continue
            parsed = _parse_timestamp(str(stamp))
            latest = parsed if latest is None or parsed > latest else latest
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    if latest is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - latest).total_seconds() / 3600.0)


def collect_observation(
    root: Path = ROOT,
    policy: Mapping[str, Any] | None = None,
    *,
    interval_start: datetime | None = None,
) -> dict[str, Any]:
    policy = dict(policy or load_policy())
    live = collect_live_point_in_time(root)
    env = project_env(root)
    try:
        database = _database_observation(env, interval_start=interval_start)
    except Exception as exc:  # falha fechada; mensagem não inclui DSN nem segredo
        database = {
            "available": False,
            "error_type": type(exc).__name__,
            "reference_snapshot": {"sample_size": 0},
            "current_snapshot": {"sample_size": 0},
        }

    http = live.get("http_probes", {})
    availability = {
        name: 1.0 if 200 <= int(http.get(name, {}).get("status") or 0) < 300 else 0.0
        for name in ("local_ai", "n8n", "glpi")
    }
    availability["postgresql"] = 1.0 if database.get("available") else 0.0
    interval = database.get("interval", {})
    events = interval.get("decision_events", [])
    latencies = [float(row["tempo_resposta_ms"]) for row in events if row.get("tempo_resposta_ms") is not None]
    metrics = {
        "availability": availability,
        "local_ai_inference_p95_ms": percentile(latencies, 0.95) if latencies else None,
        # Percentis por ciclo não permitem reconstruir o percentil das esperas individuais.
        "queue_wait_p95_seconds": None,
        "open_dead_letters": database.get("open_dead_letters"),
        "technical_error_rate": sum(bool(row.get("erro_ia")) for row in events) / len(events) if events else None,
        # Rótulos-proxy não permitem verificar erro semântico crítico.
        "critical_automatic_error_count": None,
        "rollback_recovery_minutes": None,
        "backup_restore_age_hours": _backup_restore_age_hours(root),
    }
    drift = evaluate_drift(
        interval.get("reference_snapshot", {"sample_size": 0}),
        interval.get("current_snapshot", {"sample_size": 0}),
        policy=policy,
    )
    workflow_paths = sorted((root / "n8n" / "workflows" / "Versão9").glob("V9-WF*.json"))
    return {
        "schema_version": "1.1.0",
        "collected_at": interval.get("end") or utc_now(),
        "evidence_status": "POINT_IN_TIME_PROXY_TECHNICAL_EVIDENCE",
        "scientific_result": False,
        "semantic_correctness_confirmed": False,
        "live": live,
        "database": database,
        "metrics": metrics,
        "metrics_scope": "COLLECTION_INTERVAL_AND_SAMPLED_GAUGES",
        "slo_point_in_time": evaluate_slo(metrics, policy),
        "drift": drift,
        "integrity": {
            "n8n_compose_sha256": sha256_file(root / "n8n" / "docker-compose.yml"),
            "policy_sha256": sha256_file(Path(__file__).with_name("politica_operacional_v1.json")),
            "workflow_sha256": {path.name: sha256_file(path) for path in workflow_paths},
        },
        "interpretation_limit": (
            "Coleta automática baseada em disponibilidade e rótulos-proxy. Não confirma correção semântica, "
            "não substitui rótulos normativos e não constitui uma janela de SLO até decorrer o período completo."
        ),
    }


def _window_decision_evidence(
    observations: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    *,
    reconciliation_lag_seconds: int = 300,
) -> dict[str, Any]:
    intervals: list[tuple[datetime, datetime]] = []
    events: dict[str, dict[str, Any]] = {}
    for observation in observations:
        interval = observation.get("database", {}).get("interval", {})
        if not interval.get("complete") or not interval.get("start") or not interval.get("end"):
            continue
        left = _parse_timestamp(str(interval["start"]))
        right = _parse_timestamp(str(interval["end"]))
        if left >= end or right <= start:
            continue
        intervals.append((max(start, left), min(end, right)))
        for event in interval.get("decision_events", []):
            if event.get("id") is None or not event.get("criado_em"):
                continue
            stamp = _parse_timestamp(str(event["criado_em"]))
            if start <= stamp < end and left <= stamp < right:
                events[str(event["id"])] = event
    covered_until = start
    for left, right in sorted(intervals):
        if left > covered_until:
            break
        covered_until = max(covered_until, right)
    coverage_complete = covered_until >= end
    reconciliation_target = datetime.fromtimestamp(
        end.timestamp() + reconciliation_lag_seconds, timezone.utc
    )
    reconciled_ends = [
        _parse_timestamp(str(interval["end"]))
        for observation in observations
        if isinstance((interval := observation.get("database", {}).get("interval", {})), dict)
        and interval.get("complete")
        and interval.get("start")
        and interval.get("end")
        and _parse_timestamp(str(interval["start"])) <= start
        and _parse_timestamp(str(interval["end"])) >= reconciliation_target
    ]
    reconciliation_complete = bool(reconciled_ends)
    complete = coverage_complete and reconciliation_complete
    status = "COMPLETE"
    if not coverage_complete:
        status = "INSUFFICIENT_TEMPORAL_COVERAGE"
    elif not reconciliation_complete:
        status = "PENDING_DECISION_RECONCILIATION"
    return {
        "status": status,
        "interval_coverage_complete": complete,
        "raw_interval_coverage_complete": coverage_complete,
        "decision_reconciliation_complete": reconciliation_complete,
        "decision_reconciliation_target": reconciliation_target.isoformat().replace("+00:00", "Z"),
        "decision_reconciled_through": (
            max(reconciled_ends).isoformat().replace("+00:00", "Z")
            if reconciled_ends
            else None
        ),
        "unique_decision_count": len(events),
        "events": list(events.values()),
        "bounds": "START_INCLUSIVE_END_EXCLUSIVE",
        "scope": "UNIQUE_DECISIONS_CREATED_WITHIN_WINDOW",
        "interpretation_limit": (
            "Telemetria legada sem intervalos explícitos não comprova métricas desta janela. "
            "Ausência de decisões não demonstra ausência de erro."
        ),
    }


def _window_metrics(
    rows: list[dict[str, Any]], decision_evidence: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    availability: dict[str, float | None] = {}
    for name in ("local_ai", "n8n", "glpi", "postgresql"):
        values = [row.get("metrics", {}).get("availability", {}).get(name) for row in rows]
        numeric = [float(value) for value in values if value is not None]
        availability[name] = sum(numeric) / len(numeric) if numeric and len(numeric) == len(rows) else None
    evidence = decision_evidence or {}
    events = evidence.get("events", []) if evidence.get("interval_coverage_complete") else []
    latencies = [float(event["tempo_resposta_ms"]) for event in events if event.get("tempo_resposta_ms") is not None]

    def observed_max(name: str) -> float | None:
        values = [row.get("metrics", {}).get(name) for row in rows]
        return max(float(value) for value in values) if values and all(value is not None for value in values) else None

    return {
        "availability": availability,
        "local_ai_inference_p95_ms": percentile(latencies, 0.95) if latencies else None,
        "technical_error_rate": sum(bool(event.get("erro_ia")) for event in events) / len(events) if events else None,
        "queue_wait_p95_seconds": None,
        "open_dead_letters": observed_max("open_dead_letters"),
        "backup_restore_age_hours": observed_max("backup_restore_age_hours"),
        "critical_automatic_error_count": None,
        "rollback_recovery_minutes": None,
    }


def summarize_windows(observations: list[dict[str, Any]], policy: Mapping[str, Any]) -> dict[str, Any]:
    # A mesma coleta serializada novamente não é uma observação independente.
    valid = list({_parse_timestamp(str(row["collected_at"])): row for row in observations if row.get("collected_at")}.values())
    valid.sort(key=lambda row: _parse_timestamp(str(row["collected_at"])))
    if not valid:
        return {"status": "NO_DATA", "observation_count": 0, "scientific_result": False}
    first = _parse_timestamp(str(valid[0]["collected_at"]))
    last = _parse_timestamp(str(valid[-1]["collected_at"]))
    elapsed = max(0.0, (last - first).total_seconds())
    window_seconds = int(policy["slo"]["window_seconds"])
    reconciliation_lag_seconds = int(
        policy.get("monitoring", {}).get("decision_reconciliation_lag_seconds", 300)
    )
    minimum_rows = int(policy["slo"]["minimum_observations_per_window"])
    windows: list[dict[str, Any]] = []
    previous_evidence: dict[str, Any] = {}
    cursor = first
    while (last - cursor).total_seconds() >= window_seconds + reconciliation_lag_seconds:
        window_end = cursor.timestamp() + window_seconds
        rows = [
            row for row in valid
            if cursor.timestamp() <= _parse_timestamp(str(row["collected_at"])).timestamp() < window_end
        ]
        end = datetime.fromtimestamp(window_end, timezone.utc)
        decision_evidence = _window_decision_evidence(
            valid,
            cursor,
            end,
            reconciliation_lag_seconds=reconciliation_lag_seconds,
        )
        if len(rows) >= minimum_rows:
            drift_counts: dict[str, int] = {}
            for row in rows:
                status = str(row.get("drift", {}).get("status") or "NOT_AVAILABLE")
                drift_counts[status] = drift_counts.get(status, 0) + 1
            metrics = _window_metrics(rows, decision_evidence)
            reference_events = previous_evidence.get("events", []) if previous_evidence.get("interval_coverage_complete") else []
            current_events = decision_evidence["events"] if decision_evidence["interval_coverage_complete"] else []
            window_drift = evaluate_drift(
                snapshot_from_rows(reference_events), snapshot_from_rows(current_events), policy=policy
            )
            windows.append(
                {
                    "index": len(windows) + 1,
                    "start": cursor.isoformat().replace("+00:00", "Z"),
                    "end": datetime.fromtimestamp(window_end, timezone.utc).isoformat().replace("+00:00", "Z"),
                    "observation_count": len(rows),
                    "minimum_observations": minimum_rows,
                    "metrics": metrics,
                    "metrics_scope": "WINDOW_DECISIONS_AND_SAMPLED_GAUGES",
                    "decision_evidence": {key: value for key, value in decision_evidence.items() if key != "events"},
                    "availability_measurement": "FRACTION_OF_HTTP_AND_DATABASE_PROBES_NOT_CONTINUOUS_UPTIME",
                    "queue_wait_measurement": "INSUFFICIENT_DATA_INDIVIDUAL_WAIT_TIMES_NOT_RECORDED",
                    "slo_evaluation": evaluate_slo(metrics, policy),
                    "drift_status_counts": drift_counts,
                    "drift_status_counts_scope": "COLLECTOR_DIAGNOSTICS_MAY_REPEAT_HISTORICAL_SNAPSHOTS",
                    "drift_evaluation": window_drift,
                    "drift_evaluation_scope": "CURRENT_WINDOW_VS_IMMEDIATELY_PREVIOUS_WINDOW_UNIQUE_DECISIONS",
                    "semantic_correctness_confirmed": False,
                }
            )
        previous_evidence = decision_evidence
        cursor = datetime.fromtimestamp(window_end, timezone.utc)
    completed = len(windows)
    required = int(policy["slo"]["minimum_observation_windows"])
    return {
        "status": "TECHNICAL_WINDOWS_COMPLETE" if completed >= required else "IN_PROGRESS",
        "window_mode": policy["slo"]["window_mode"],
        "window_seconds": window_seconds,
        "decision_reconciliation_lag_seconds": reconciliation_lag_seconds,
        "observation_count": len(valid),
        "first_collected_at": valid[0]["collected_at"],
        "last_collected_at": valid[-1]["collected_at"],
        "elapsed_seconds": elapsed,
        "completed_technical_windows": completed,
        "required_technical_windows": required,
        "windows_with_complete_decision_coverage": sum(
            bool(window["decision_evidence"]["interval_coverage_complete"]) for window in windows
        ),
        "windows_passing_all_slo_checks": sum(window["slo_evaluation"]["status"] == "PASS" for window in windows),
        "technical_windows_complete_means": "ELAPSED_DURATION_AND_MINIMUM_PROBE_COUNT_ONLY",
        "windows": windows,
        "longitudinal_production_evaluation": "OUT_OF_SCOPE_BY_USER_DECISION",
        "longitudinal_production_window_days": policy["slo"]["longitudinal_production_window_days"],
        "scientific_result": False,
        "semantic_correctness_confirmed": False,
        "interpretation_limit": (
            "Janelas intradiárias de telemetria local/sintética verificam o mecanismo técnico, não "
            "estimam disponibilidade longitudinal de produção nem confirmam correção semântica. "
            "TECHNICAL_WINDOWS_COMPLETE não implica PASS no SLO; métricas sem cobertura temporal "
            "ou sem novas decisões permanecem insuficientes."
        ),
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
        except json.JSONDecodeError:
            continue
    return rows


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


@contextmanager
def _single_instance_lock(path: Path):
    """Trava pelo descritor; uma queda do processo não deixa bloqueio órfão."""
    handle = path.open("a+b")
    if path.stat().st_size == 0:
        handle.write(b"0")
        handle.flush()
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        yield False
        handle.close()
        return
    try:
        yield True
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


def run_once(runtime_dir: Path, policy: Mapping[str, Any]) -> dict[str, Any]:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    lock_path = runtime_dir / "collector.lock"
    with _single_instance_lock(lock_path) as acquired:
        if not acquired:
            return {"status": "SKIPPED_OVERLAP", "scientific_result": False}
        observations_path = runtime_dir / "observations.jsonl"
        rows = _read_jsonl(observations_path)
        interval_starts = [
            _parse_timestamp(str(interval["start"]))
            for row in rows
            if isinstance((interval := row.get("database", {}).get("interval", {})), dict)
            and interval.get("complete")
            and interval.get("start")
        ]
        # Reconsulta cumulativamente desde o primeiro intervalo válido. Isso
        # recupera decisões cujo criado_em pertence à janela, mas cuja transação
        # só ficou visível após um snapshot anterior.
        reconciliation_start = min(interval_starts, default=None)
        observation = collect_observation(
            policy=policy, interval_start=reconciliation_start
        )
        with observations_path.open("a", encoding="utf-8") as target:
            target.write(json.dumps(observation, ensure_ascii=False, separators=(",", ":")) + "\n")
        rows.append(observation)
        summary = summarize_windows(rows, policy)
        _atomic_json(runtime_dir / "latest.json", observation)
        _atomic_json(runtime_dir / "windows.json", summary)
        return summary


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    policy = load_policy(args.policy) if args.policy else load_policy()
    result = run_once(args.runtime_dir.resolve(), policy)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") != "SKIPPED_OVERLAP" else 2


if __name__ == "__main__":
    sys.exit(main())
