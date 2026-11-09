"""One compact, read-only-by-default observation for the hourly task."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "avaliacao/runtime/monitoring-homolog-20260910-v2"
EXECUTABLE = ROOT / ".venv/Scripts/pythonw.exe"
SCRIPT = ROOT / "avaliacao/operacional/monitor_daemon.py"


def instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp without timezone")
    return parsed.astimezone(timezone.utc)


def matching_processes(processes: list[dict]) -> list[dict]:
    return [p for p in processes if p.get("ExecutablePath") == str(EXECUTABLE)
            and all(token in (p.get("CommandLine") or "") for token in (
                "monitor_daemon.py", "monitoring-homolog-20260910-v2", "--interval-seconds 60"))]


def processes() -> list[dict]:
    query = "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
    proc = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", query],
                          capture_output=True, text=True, timeout=30, check=True,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    data = json.loads(proc.stdout) if proc.stdout.strip() else []
    return data if isinstance(data, list) else [data]


def summary(windows: dict, daemon: dict, matches: list[dict], now: datetime) -> dict:
    completed = int(windows["completed_technical_windows"])
    age = (now - instant(daemon["updated_at"])).total_seconds()
    if len(matches) > 1:
        action = "ALERT_DUPLICATE_PROCESSES"
    elif completed >= 3:
        action = "FINALIZE"
    elif not matches:
        action = "RESTART_REQUIRED"
    elif daemon.get("state") != "RUNNING" or age > 180 or age < -60:
        action = "ALERT_STALE_OR_FAILED"
    elif windows.get("status") == "IN_PROGRESS":
        action = "QUIET"
    else:
        action = "ALERT_UNEXPECTED_STATE"
    return {
        "action": action, "exact_process_count": len(matches),
        "pids": [p["ProcessId"] for p in matches], "daemon_age_seconds": round(age, 1),
        "status": windows["status"], "completed_technical_windows": completed,
        "windows_with_complete_decision_coverage": windows.get("windows_with_complete_decision_coverage"),
        "windows_passing_all_slo_checks": windows.get("windows_passing_all_slo_checks"),
        "first_three": [{"index": w["index"], "end": w["end"],
                         "observations": w["observation_count"],
                         "coverage": w["decision_evidence"]["status"],
                         "decisions": w["decision_evidence"]["unique_decision_count"],
                         "slo": w["slo_evaluation"]["status"],
                         "drift": w["drift_evaluation"]["status"]}
                        for w in windows.get("windows", [])[:3]],
        "scientific_ready": False, "production_ready": False,
    }


def temporal_gaps(path: Path) -> dict:
    # Stream without exposing observations or consuming model context.
    previous = None
    gaps = []
    for line in path.open(encoding="utf-8"):
        row = json.loads(line)
        current = instant(row["collected_at"])
        if previous is not None and (current - previous).total_seconds() > 120:
            gaps.append({"from": previous.isoformat(), "to": current.isoformat(),
                         "seconds": round((current - previous).total_seconds(), 2)})
        previous = current
    return {"count_over_120_seconds": len(gaps),
            "largest": max(gaps, key=lambda g: g["seconds"]) if gaps else None}


@contextmanager
def repair_lock():
    import msvcrt
    lock_path = RUNTIME / "hourly-watcher.lock"
    with lock_path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def restart_if_absent() -> list[dict]:
    with repair_lock():
        matches = matching_processes(processes())
        if matches:
            return matches
        # Paths are fixed workspace constants, not external command inputs.
        command = (f"Start-Process -FilePath '{EXECUTABLE}' -WindowStyle Hidden "
                   f"-ArgumentList '\"{SCRIPT}\" --runtime-dir \"{RUNTIME}\" --interval-seconds 60'")
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                       capture_output=True, check=True, timeout=20,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        time.sleep(1)
        return matching_processes(processes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        windows = json.loads((RUNTIME / "windows.json").read_text(encoding="utf-8"))
        daemon = json.loads((RUNTIME / "daemon-status.json").read_text(encoding="utf-8"))
        matches = matching_processes(processes())
        result = summary(windows, daemon, matches, datetime.now(timezone.utc))
        result["gaps"] = temporal_gaps(RUNTIME / "observations.jsonl")
        if args.repair and result["action"] == "RESTART_REQUIRED":
            matches = restart_if_absent()
            result.update(exact_process_count=len(matches), pids=[p["ProcessId"] for p in matches],
                          action="RESTARTED_VERIFY_CONTINUITY" if len(matches) == 1 else "ALERT_RESTART_FAILED")
        elif result["action"] == "QUIET" and result["gaps"]["count_over_120_seconds"]:
            result["action"] = "ALERT_TEMPORAL_GAP"
        result["checked_at"] = datetime.now(timezone.utc).isoformat()
        if args.output:
            output = args.output.resolve()
            output.relative_to(ROOT)
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as target:
                json.dump(result, target, ensure_ascii=False, indent=2)
                target.write("\n")
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"action": "ALERT_CHECK_FAILED", "error_type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
