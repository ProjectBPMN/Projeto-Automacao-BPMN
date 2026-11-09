from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from avaliacao.operacional import (
    backup_restore_drill,
    capture_live_backups,
    capture_runtime_state,
    core,
    least_privilege,
    monitor_daemon,
    scan_secrets,
    validar_operacao,
)
from avaliacao.operacional.collector import _backup_restore_age_hours, _single_instance_lock, summarize_windows
from avaliacao.operacional.core import (
    bounded_load_probe,
    evaluate_drift,
    evaluate_slo,
    isolated_failure_simulation,
    load_policy,
    validate_loopback_url,
)


ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = ROOT / "avaliacao" / "operacional" / "politica_operacional_v1.json"


def test_policy_is_explicitly_proposed_and_safe() -> None:
    policy = load_policy(POLICY_PATH)
    assert policy["status"] == "PROPOSTA_NAO_APROVADA"
    assert policy["safe_defaults"]["loopback_only"] is True
    assert policy["slo"]["approval_status"] == "PROPOSTO_NAO_APROVADO"
    assert policy["monitoring"]["collector_status"] == "INSTALADO_LOCALMENTE_2026-09-02"
    assert policy["monitoring"]["automatic_retraining_allowed"] is False
    assert all(
        row["automatic_decision_allowed"] is False
        for row in policy["failure_policy"].values()
    )


def test_policy_rejects_unsafe_failure_rule(tmp_path: Path) -> None:
    policy = load_policy(POLICY_PATH)
    policy["failure_policy"]["local_ai_unavailable"]["automatic_decision_allowed"] = True
    path = tmp_path / "unsafe.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(ValueError, match="insegura"):
        load_policy(path)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org/health",
        "file:///etc/passwd",
        "http://user:password@127.0.0.1/health",
        "http://127.0.0.1/health?mutate=true",
        "http://127.0.0.1/admin",
    ],
)
def test_load_target_restrictions(url: str) -> None:
    with pytest.raises(ValueError):
        validate_loopback_url(url, allowed_paths={"/health"})


def test_bounded_load_and_concurrency_on_ephemeral_loopback() -> None:
    from avaliacao.operacional.core import _isolated_http_server

    with _isolated_http_server(status=200) as url:
        result = bounded_load_probe(
            url=url,
            requests_count=12,
            concurrency=4,
            timeout_seconds=0.5,
            policy=load_policy(POLICY_PATH),
        )
    assert result["requests"] == 12
    assert result["concurrency"] == 4
    assert result["success_rate"] == 1.0
    assert result["latency_ms"]["p95"] is not None
    assert result["scientific_result"] is False


def test_isolated_failure_simulation_does_not_touch_live_services() -> None:
    result = isolated_failure_simulation(load_policy(POLICY_PATH))
    assert result["status"] == "PASS"
    assert result["live_services_touched"] is False
    assert {row["detected_failure"] for row in result["scenarios"]} == {
        "HTTP_503",
        "TIMEOUT",
        "CONNECTION_REFUSED",
    }
    assert all(row["automatic_decision_allowed"] is False for row in result["scenarios"])


def test_read_only_commands_suppress_windows_console(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> object:
        captured.update(kwargs)
        return core.subprocess.CompletedProcess(command, 0, "ok\n", "")

    monkeypatch.setattr(core.subprocess, "run", fake_run)
    result = core.run_command_read_only(["docker", "version"])

    expected = core.subprocess.CREATE_NO_WINDOW if core.os.name == "nt" else 0
    assert captured["creationflags"] == expected
    assert result == {"returncode": 0, "stdout": "ok", "stderr": ""}


def test_live_probe_is_pinned_to_local_docker_desktop(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(core, "project_env", lambda _root: {})
    monkeypatch.setattr(
        core,
        "_http_request",
        lambda *_args, **_kwargs: {"status": 200, "latency_ms": 1.0, "body": "ok"},
    )

    def fake_run(command: list[str], timeout_seconds: float = 15.0) -> dict[str, object]:
        captured["command"] = command
        captured["timeout_seconds"] = timeout_seconds
        return {
            "returncode": 0,
            "stdout": "\n".join(
                f"/{name}|running|healthy"
                for name in ("glpi", "glpi-db", "glpi-dedup-db", "n8n")
            ),
            "stderr": "",
        }

    monkeypatch.setattr(core, "run_command_read_only", fake_run)
    result = core.collect_live_point_in_time(ROOT)

    assert captured["command"][:3] == ["docker", "--context", "desktop-linux"]
    assert result["status"] == "PASS"
    assert result["docker_healthy"] is True


def test_live_probe_fails_when_docker_is_unhealthy_despite_http_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core, "project_env", lambda _root: {})
    monkeypatch.setattr(
        core,
        "_http_request",
        lambda *_args, **_kwargs: {"status": 200, "latency_ms": 1.0, "body": "ok"},
    )
    monkeypatch.setattr(
        core,
        "run_command_read_only",
        lambda *_args, **_kwargs: {
            "returncode": 1,
            "stdout": "/n8n|running|healthy",
            "stderr": "missing containers",
        },
    )

    result = core.collect_live_point_in_time(ROOT)

    assert result["status"] == "FAIL"
    assert result["docker_healthy"] is False


def test_runtime_state_query_is_pinned_local_and_uses_one_statement_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> object:
        captured["command"] = command
        captured.update(kwargs)
        return core.subprocess.CompletedProcess(command, 0, "0|0|0\n", "")

    monkeypatch.setattr(capture_runtime_state.subprocess, "run", fake_run)
    sql = (
        "SELECT count(*) FILTER (WHERE triagem_status='ERRO_IA'), "
        "count(*) FILTER (WHERE triagem_status='PENDENTE_FILA_IA'), "
        "(SELECT count(*) FROM fila_ia_dead_letter WHERE NOT resolvido) "
        "FROM tickets_processados"
    )
    assert capture_runtime_state._query(sql) == ["0|0|0"]
    command = captured["command"]
    assert isinstance(command, list)
    assert command[:3] == ["docker", "--context", "desktop-linux"]
    assert sql in command[-1]


def test_runtime_state_passes_when_all_three_atomic_counts_are_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "runtime.json"
    monkeypatch.setattr(capture_runtime_state, "ROOT", tmp_path)
    monkeypatch.setattr(capture_runtime_state, "_query", lambda _sql: ["0|0|0"])
    monkeypatch.setattr(
        sys,
        "argv",
        ["capture_runtime_state.py", "--output", str(output)],
    )

    assert capture_runtime_state.main() == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert (payload["erro_ia"], payload["active_queue"], payload["open_dlq"]) == (0, 0, 0)


def test_drift_without_shared_features_cannot_pass() -> None:
    reference = {"sample_size": 200, "categorical": {"a": {"x": 200}}}
    current = {"sample_size": 200, "categorical": {"b": {"x": 200}}}
    result = evaluate_drift(reference, current, policy=load_policy(POLICY_PATH))
    assert result["status"] == "INCOMPATIBLE_SNAPSHOTS"


def test_drift_stop_and_slo_remains_unapproved() -> None:
    reference = {"sample_size": 200, "categorical": {"classe": {"a": 199, "b": 1}}}
    current = {"sample_size": 200, "categorical": {"classe": {"a": 1, "b": 199}}}
    drift = evaluate_drift(reference, current, policy=load_policy(POLICY_PATH))
    assert drift["status"] == "STOP"
    slo = evaluate_slo({}, load_policy(POLICY_PATH))
    assert slo["status"] == "INSUFFICIENT_DATA"
    assert slo["institutionally_approved"] is False


def test_monitoring_windows_require_elapsed_time_and_minimum_observations() -> None:
    policy = load_policy(POLICY_PATH)
    observations = [
        {
            "collected_at": "2026-09-02T00:00:00Z",
            "metrics": {"availability": {name: 1.0 for name in ("local_ai", "n8n", "glpi", "postgresql")}},
        },
        {
            "collected_at": "2026-09-02T00:01:00Z",
            "metrics": {"availability": {name: 1.0 for name in ("local_ai", "n8n", "glpi", "postgresql")}},
        },
    ]
    summary = summarize_windows(observations, policy)
    assert summary["status"] == "IN_PROGRESS"
    assert summary["completed_technical_windows"] == 0
    assert summary["required_technical_windows"] == 3
    assert summary["scientific_result"] is False


def test_three_intraday_windows_are_technical_not_longitudinal() -> None:
    policy = load_policy(POLICY_PATH)
    observations = []
    # Três janelas de quatro horas só fecham depois da defasagem obrigatória
    # de reconciliação de decisões da terceira janela.
    reconciliation_minutes = int(policy["monitoring"]["decision_reconciliation_lag_seconds"] / 60)
    for minute in range(12 * 60 + reconciliation_minutes + 1):
        observations.append(
            {
                "collected_at": f"2026-09-02T{minute // 60:02d}:{minute % 60:02d}:00Z",
                "metrics": {"availability": {name: 1.0 for name in ("local_ai", "n8n", "glpi", "postgresql")}},
                "drift": {"status": "PASS"},
            }
        )
    summary = summarize_windows(observations, policy)
    assert summary["status"] == "TECHNICAL_WINDOWS_COMPLETE"
    assert summary["completed_technical_windows"] == 3
    assert summary["longitudinal_production_evaluation"] == "OUT_OF_SCOPE_BY_USER_DECISION"
    assert summary["scientific_result"] is False


def test_collector_recovers_reusable_descriptor_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / "collector.lock"
    lock_path.write_text("0", encoding="ascii")
    with _single_instance_lock(lock_path) as acquired:
        assert acquired is True
    with _single_instance_lock(lock_path) as acquired_again:
        assert acquired_again is True


def test_monitor_daemon_status_is_sanitized(tmp_path: Path) -> None:
    status_path = tmp_path / "daemon-status.json"
    monitor_daemon._status(status_path, "DEGRADED", detail="TimeoutError")
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["state"] == "DEGRADED"
    assert status["detail"] == "TimeoutError"
    assert status["scientific_result"] is False
    assert status["semantic_correctness_confirmed"] is False


def test_monitor_installer_uses_hidden_user_startup_and_removes_old_task() -> None:
    installer = (ROOT / "avaliacao" / "operacional" / "install_monitoring.ps1").read_text(
        encoding="utf-8"
    )
    assert "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" in installer
    assert "ProjetoICMonitoramento" in installer
    assert ".venv\\Scripts\\pythonw.exe" in installer
    assert "Unregister-ScheduledTask" in installer
    assert "-WindowStyle Hidden" in installer
    assert "Register-ScheduledTask" not in installer


def test_collector_reads_nested_n8n_restore_timestamp(tmp_path: Path) -> None:
    results = tmp_path / "avaliacao" / "resultados" / "operacional"
    results.mkdir(parents=True)
    (results / "restore-volume-n8n-test.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "result": {"status": "PASS", "executed_at": "2026-09-02T04:52:46Z"},
            }
        ),
        encoding="utf-8",
    )
    age = _backup_restore_age_hours(tmp_path)
    assert age is not None
    assert age >= 0


def test_validator_dry_run_does_not_execute_requested_load(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(**_: object) -> dict[str, object]:
        raise AssertionError("carga não deveria executar sem --apply")

    monkeypatch.setattr(validar_operacao, "bounded_load_probe", forbidden)
    args = validar_operacao.build_parser().parse_args(["--load-url", "http://127.0.0.1:8090/health"])
    report = validar_operacao.build_report(args)
    assert report["sections"]["bounded_load"]["status"] == "NOT_RUN"
    assert report["mode"] == "SAFE_LOCAL_DEFAULT"
    assert report["sections"]["monitoring_plan"]["status"] == "PROPOSED_NOT_APPROVED"
    assert report["production_ready"] is False
    assert "POLICY_NOT_INSTITUTIONALLY_APPROVED" in report["readiness_blockers"]
    assert "LEAST_PRIVILEGE_REMEDIATION_NOT_VERIFIED" not in report["readiness_blockers"]
    assert report["sections"]["least_privilege_evidence"]["status"] == "PASS"
    assert report["sections"]["n8n_volume_restore_evidence"]["status"] == "PASS"


def test_backup_restore_default_is_plan_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_: object, **__: object) -> dict[str, object]:
        raise AssertionError("Docker não deve executar no dry-run")

    monkeypatch.setattr(backup_restore_drill, "_run", forbidden)
    args = backup_restore_drill.build_parser().parse_args([])
    plan = backup_restore_drill.build_plan(args)
    assert plan["mode"] == "DRY_RUN"
    assert plan["live_services_touched"] is False
    assert plan["temporary_target_controls"]["network"] == "none"
    assert (
        plan["temporary_target_controls"]["resource_strategy"]
        == "SEQUENTIAL_EPHEMERAL_DATABASES"
    )


def test_backup_restore_is_pinned_to_local_docker_desktop() -> None:
    assert backup_restore_drill.docker_command("ps")[:3] == [
        "docker",
        "--context",
        "desktop-linux",
    ]
    source = Path(backup_restore_drill.__file__).read_text(encoding="utf-8")
    assert '"pg_restore", "--no-owner", "--no-privileges"' in source


def test_live_backup_capture_is_dry_run_and_pinned(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output_dir = tmp_path / "backup"
    manifest = tmp_path / "manifest.json"
    assert capture_live_backups.main(
        ["--output-dir", str(output_dir), "--manifest", str(manifest)]
    ) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["mode"] == "DRY_RUN"
    assert plan["daemon_touched"] is False
    assert plan["live_databases_mutated"] is False
    assert capture_live_backups.docker_command("ps")[:3] == [
        "docker",
        "--context",
        "desktop-linux",
    ]


@pytest.mark.parametrize(
    "payload",
    [
        "headers: {'App-Token': 'literal-token-value-123456'}",
        '{"name":"App-Token","value":"literal-token-value-123456"}',
    ],
)
def test_secret_scan_detects_structured_glpi_token_without_echoing(payload: str) -> None:
    findings = scan_secrets._scan_text(payload, "legacy.json", "candidate_tree")
    assert any(row["rule"] == "structured_credential_literal" for row in findings)
    assert "literal-token-value-123456" not in json.dumps(findings)


def test_superuser_live_row_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        least_privilege,
        "_run",
        lambda _: {
            "returncode": 0,
            "stdout": "triagem_user|t|t|t|f|f|t",
            "stderr": "",
        },
    )
    result = least_privilege.live_audit("glpi-dedup-db", "triagem", "triagem_user")
    assert result["status"] == "FAIL"
    assert result["dangerous_attributes"] == ["rolsuper", "rolcreaterole", "rolcreatedb"]


def test_least_privilege_sql_and_static_blocker_are_explicit() -> None:
    sql = least_privilege.SQL_PATH.read_text(encoding="utf-8")
    static = least_privilege.static_audit(ROOT)
    assert "triagem_migration_owner" in sql
    assert "triagem_runtime" in sql
    assert "GRANT SELECT, INSERT, UPDATE, DELETE" in sql
    assert "REVOKE CREATE ON SCHEMA public" in sql
    assert static["apply_blocked"] is False
    assert static["runtime_workflow_ddl_tokens"] == []


def test_apply_requires_persisted_rollback_output() -> None:
    with pytest.raises(SystemExit):
        least_privilege.main(["--apply"])


def test_readme_has_nist_matrix_and_no_certification_claim() -> None:
    readme = (ROOT / "avaliacao" / "operacional" / "README.md").read_text(encoding="utf-8")
    for function in ("GOVERN", "MAP", "MEASURE", "MANAGE"):
        assert function in readme
    assert "declaração de conformidade" in readme
    assert "não aprovados" in readme
