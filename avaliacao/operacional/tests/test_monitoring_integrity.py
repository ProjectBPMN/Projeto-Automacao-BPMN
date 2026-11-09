from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from avaliacao.operacional import collector
from avaliacao.operacional.core import evaluate_drift, load_policy


START = datetime(2026, 9, 8, tzinfo=timezone.utc)


def test_mixed_timezone_offsets_deduplicate_same_instant():
    rows = [observation(0), observation(240)]
    duplicate = {**rows[1], "collected_at": "2026-09-08T01:00:00-03:00"}
    result = collector.summarize_windows([rows[0], duplicate, rows[1]], load_policy())
    assert result["observation_count"] == 2
    assert result["elapsed_seconds"] == 14400


def stamp(minutes: int) -> str:
    return (START + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def event(identifier: int, minute: int, *, latency: int = 100, error: bool = False) -> dict:
    return {
        "id": identifier,
        "criado_em": stamp(minute),
        "tempo_resposta_ms": latency,
        "erro_ia": error,
        "predicao": "INCIDENTE",
    }


def observation(minute: int, *, since: int | None = None, events: list | None = None) -> dict:
    row = {
        "collected_at": stamp(minute),
        "metrics": {
            "availability": {name: 1.0 for name in ("local_ai", "n8n", "glpi", "postgresql")},
            "open_dead_letters": 0,
            "backup_restore_age_hours": 2,
            # Valores legados não podem contaminar a janela nem produzir PASS.
            "local_ai_inference_p95_ms": 1,
            "technical_error_rate": 0,
            "queue_wait_p95_seconds": 0,
        },
        "drift": {"status": "STOP"},
    }
    if since is not None:
        row["database"] = {
            "interval": {"start": stamp(since), "end": stamp(minute), "complete": True, "decision_events": events or []}
        }
    return row


def test_window_ignores_legacy_metrics_and_repeated_drift() -> None:
    summary = collector.summarize_windows([observation(minute) for minute in range(726)], load_policy())
    assert summary["completed_technical_windows"] == 3
    assert summary["windows_with_complete_decision_coverage"] == 0
    assert summary["windows_passing_all_slo_checks"] == 0
    for window in summary["windows"]:
        assert window["decision_evidence"]["status"] == "INSUFFICIENT_TEMPORAL_COVERAGE"
        assert window["metrics"]["local_ai_inference_p95_ms"] is None
        assert window["metrics"]["technical_error_rate"] is None
        assert window["metrics"]["queue_wait_p95_seconds"] is None
        assert window["drift_evaluation"]["status"] == "INSUFFICIENT_DATA"
        assert window["drift_status_counts"] == {"STOP": 240}


def test_window_uses_closing_collection_and_unique_events_with_exact_bounds() -> None:
    rows = [observation(0)]
    for minute in range(1, 246):
        events = [event(1, 0, latency=2000, error=True)] if minute == 1 else []
        if minute == 240:
            events = [event(2, 239, latency=100)]
        if minute == 241:
            events = [event(3, 240, latency=90000)]
        rows.append(observation(minute, since=minute - 1, events=events))
    # Snapshot com sobreposição não pode dobrar denominador ou percentil.
    rows.append(observation(239, since=0, events=[event(1, 0, latency=2000, error=True)]))
    rows.append(
        observation(
            245,
            since=0,
            events=[
                event(1, 0, latency=2000, error=True),
                event(2, 239, latency=100),
                event(3, 240, latency=90000),
            ],
        )
    )
    summary = collector.summarize_windows(rows, load_policy())
    window = summary["windows"][0]
    assert window["decision_evidence"]["interval_coverage_complete"] is True
    assert window["decision_evidence"]["unique_decision_count"] == 2
    assert window["metrics"]["technical_error_rate"] == 0.5
    assert window["metrics"]["local_ai_inference_p95_ms"] == pytest.approx(1905)
    assert window["slo_evaluation"]["status"] == "FAIL"


def test_gap_in_database_intervals_keeps_window_metrics_insufficient() -> None:
    rows = [observation(0)] + [
        observation(minute, since=minute - 1, events=[event(minute, minute - 1)])
        for minute in range(1, 246)
    ]
    rows[120].pop("database")
    window = collector.summarize_windows(rows, load_policy())["windows"][0]
    assert window["decision_evidence"]["interval_coverage_complete"] is False
    assert window["metrics"]["technical_error_rate"] is None
    assert window["metrics"]["local_ai_inference_p95_ms"] is None


def test_empty_but_fully_covered_window_does_not_claim_zero_error() -> None:
    rows = [observation(0)] + [observation(minute, since=minute - 1) for minute in range(1, 246)]
    rows.append(observation(245, since=0))
    window = collector.summarize_windows(rows, load_policy())["windows"][0]
    assert window["decision_evidence"]["interval_coverage_complete"] is True
    assert window["decision_evidence"]["unique_decision_count"] == 0
    assert window["metrics"]["technical_error_rate"] is None
    assert window["drift_evaluation"]["status"] == "INSUFFICIENT_DATA"


def test_window_preserves_dlq_spike_and_missing_availability() -> None:
    rows = [observation(minute) for minute in range(246)]
    rows[2]["metrics"]["open_dead_letters"] = 4
    rows[3]["metrics"]["availability"]["n8n"] = None
    window = collector.summarize_windows(rows, load_policy())["windows"][0]
    assert window["metrics"]["open_dead_letters"] == 4
    assert window["metrics"]["availability"]["n8n"] is None
    assert window["slo_evaluation"]["status"] == "FAIL"


def test_duplicated_probes_cannot_supply_minimum_observations() -> None:
    rows = [observation(0)] * 300 + [observation(240)]
    summary = collector.summarize_windows(rows, load_policy())
    assert summary["observation_count"] == 2
    assert summary["completed_technical_windows"] == 0


def test_window_drift_is_evaluated_once_from_adjacent_new_decisions() -> None:
    rows = [observation(0)]
    for minute in range(1, 486):
        decision = event(minute, minute - 1)
        decision["predicao"] = "A" if minute <= 240 else "B"
        rows.append(observation(minute, since=minute - 1, events=[decision]))
    first_events = [event(minute, minute - 1) for minute in range(1, 241)]
    for decision in first_events:
        decision["predicao"] = "A"
    all_events = first_events + [event(minute, minute - 1) for minute in range(241, 481)]
    for decision in all_events[240:]:
        decision["predicao"] = "B"
    rows.append(observation(245, since=0, events=first_events))
    rows.append(observation(485, since=0, events=all_events))
    windows = collector.summarize_windows(rows, load_policy())["windows"]
    assert windows[0]["drift_evaluation"]["status"] == "INSUFFICIENT_DATA"
    drift = windows[1]["drift_evaluation"]
    assert drift["sample_size"] == {"reference": 240, "current": 240}
    assert drift["status"] == "STOP"
    assert drift["automatic_stop_enforced"] is False


def test_drift_stop_never_claims_runtime_enforcement() -> None:
    drift = evaluate_drift(
        {"sample_size": 200, "categorical": {"x": {"a": 200}}},
        {"sample_size": 200, "categorical": {"x": {"b": 200}}},
    )
    assert drift["status"] == "STOP"
    assert drift["stop_requested"] is True
    assert drift["automatic_stop_enforced"] is False
    assert drift["enforcement_scope"] == "READ_ONLY_DIAGNOSTIC_NO_RUNTIME_ACTUATION"
    assert "STOP aciona bloqueio automático" not in drift["interpretation_limit"]


def test_database_collection_is_readonly_and_uses_parameterized_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    class Cursor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query, params=None):
            self.calls.append((query, params))

        def fetchone(self):
            query = self.calls[-1][0]
            if "observation_end" in query:
                return {"observation_end": START + timedelta(minutes=1)}
            return {}

        def fetchall(self):
            if "tempo_resposta_ms" in self.calls[-1][0]:
                return [{**event(1, 0), "criado_em": START, "confianca": None}]
            return []

    class Connection:
        def __init__(self):
            self.session = {}
            self.cursor_instance = Cursor()
            self.closed = False

        def set_session(self, **kwargs):
            self.session = kwargs

        def cursor(self, **kwargs):
            return self.cursor_instance

        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(collector.psycopg2, "connect", lambda **kwargs: connection)
    result = collector._database_observation({}, interval_start=START)
    assert connection.session == {"readonly": True, "autocommit": False, "isolation_level": "REPEATABLE READ"}
    assert connection.closed is True
    interval_query, bounds = connection.cursor_instance.calls[1]
    assert "criado_em >= %s AND criado_em < %s" in interval_query
    assert bounds == (START, START + timedelta(minutes=1))
    assert all(query.strip().startswith("SELECT") for query, _ in connection.cursor_instance.calls)
    assert result["interval"]["decision_events"][0]["criado_em"] == stamp(0)
    assert result["interval"]["current_snapshot"]["sample_size"] == 1
    assert result["interval"]["reference_snapshot"]["sample_size"] == 0


def test_run_once_preserves_legacy_history_without_claiming_interval(tmp_path, monkeypatch) -> None:
    original = json_line = '{"collected_at":"2026-09-08T00:00:00Z","metrics":{}}\n'
    observations = tmp_path / "observations.jsonl"
    observations.write_text(json_line, encoding="utf-8")
    captured = {}

    def collect(**kwargs):
        captured.update(kwargs)
        return observation(1, since=0)

    monkeypatch.setattr(collector, "collect_observation", collect)
    collector.run_once(tmp_path, load_policy())
    assert captured["interval_start"] is None
    assert observations.read_text(encoding="utf-8").startswith(original)
    assert len(observations.read_text(encoding="utf-8").splitlines()) == 2


def test_run_once_requeries_from_earliest_interval_to_capture_late_commit(tmp_path, monkeypatch) -> None:
    observations = tmp_path / "observations.jsonl"
    observations.write_text(
        "\n".join(
            json.dumps(observation(minute, since=0))
            for minute in (1, 2)
        ) + "\n",
        encoding="utf-8",
    )
    captured = {}

    def collect(**kwargs):
        captured.update(kwargs)
        return observation(3, since=0, events=[event(99, 1)])

    monkeypatch.setattr(collector, "collect_observation", collect)
    collector.run_once(tmp_path, load_policy())
    assert captured["interval_start"] == START


def test_failed_database_probes_do_not_satisfy_decision_reconciliation() -> None:
    rows = [observation(0)] + [
        observation(minute, since=minute - 1)
        for minute in range(1, 241)
    ]
    rows.extend(observation(minute) for minute in range(241, 246))
    pending = collector.summarize_windows(rows, load_policy())["windows"][0]
    assert pending["decision_evidence"]["status"] == "PENDING_DECISION_RECONCILIATION"
    assert pending["decision_evidence"]["interval_coverage_complete"] is False

    rows.append(observation(246, since=0))
    reconciled = collector.summarize_windows(rows, load_policy())["windows"][0]
    assert reconciled["decision_evidence"]["status"] == "COMPLETE"
    assert reconciled["decision_evidence"]["interval_coverage_complete"] is True
