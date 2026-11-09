from datetime import datetime, timezone

from avaliacao.operacional import check_homologation as check


def test_exact_process_filter_rejects_other_venv_interval_or_runtime():
    valid = {"ProcessId": 10, "ExecutablePath": str(check.EXECUTABLE),
             "CommandLine": "monitor_daemon.py monitoring-homolog-20260910-v2 --interval-seconds 60"}
    assert check.matching_processes([
        valid, {**valid, "ExecutablePath": "C:\\other\\pythonw.exe"},
        {**valid, "CommandLine": "monitor_daemon.py monitoring-homolog-20260910 --interval-seconds 60"},
        {**valid, "CommandLine": "monitor_daemon.py monitoring-homolog-20260910-v2 --interval-seconds 10"},
    ]) == [valid]


def test_finalization_never_restarts_completed_collector():
    result = check.summary({"completed_technical_windows": 3, "status": "TECHNICAL_WINDOWS_COMPLETE"},
                           {"updated_at": "2026-09-11T03:33:00Z", "state": "RUNNING"}, [],
                           datetime(2026, 9, 14, tzinfo=timezone.utc))
    assert result["action"] == "FINALIZE"


def test_stale_single_instance_is_not_restarted_and_duplicates_alert():
    windows = {"completed_technical_windows": 1, "status": "IN_PROGRESS"}
    daemon = {"updated_at": "2026-09-11T03:33:00Z", "state": "RUNNING"}
    now = datetime(2026, 9, 11, 3, 40, tzinfo=timezone.utc)
    assert check.summary(windows, daemon, [{"ProcessId": 1}], now)["action"] == "ALERT_STALE_OR_FAILED"
    assert check.summary(windows, daemon, [{"ProcessId": 1}, {"ProcessId": 2}], now)["action"] == "ALERT_DUPLICATE_PROCESSES"
