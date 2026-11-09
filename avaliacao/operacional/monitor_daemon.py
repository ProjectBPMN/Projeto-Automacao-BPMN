#!/usr/bin/env python3
"""Executa o coletor local continuamente, sem console, com uma única instância."""

from __future__ import annotations

import argparse
import json
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

try:  # permite execução como módulo nos testes e como script no Windows
    from .collector import DEFAULT_RUNTIME_DIR, _atomic_json, _single_instance_lock, load_policy, run_once
except ImportError:  # pragma: no cover - caminho usado por python monitor_daemon.py
    from collector import DEFAULT_RUNTIME_DIR, _atomic_json, _single_instance_lock, load_policy, run_once


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--interval-seconds", type=int, default=60)
    return parser


def _status(path: Path, state: str, *, detail: str | None = None) -> None:
    payload = {
        "schema_version": "1.0.0",
        "state": state,
        "pid": os.getpid(),
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scientific_result": False,
        "semantic_correctness_confirmed": False,
    }
    if detail:
        payload["detail"] = detail
    _atomic_json(path, payload)


def main() -> int:
    args = build_parser().parse_args()
    if args.interval_seconds < 10:
        raise ValueError("interval-seconds deve ser pelo menos 10")

    runtime_dir = args.runtime_dir.resolve()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    status_path = runtime_dir / "daemon-status.json"
    stop_requested = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    policy = load_policy(args.policy) if args.policy else load_policy()

    with _single_instance_lock(runtime_dir / "daemon.lock") as acquired:
        if not acquired:
            _status(runtime_dir / "duplicate-start.json", "DUPLICATE_INSTANCE_REFUSED")
            return 2

        _status(status_path, "RUNNING")
        while not stop_requested:
            started = time.monotonic()
            try:
                result = run_once(runtime_dir, policy)
                _status(status_path, "RUNNING", detail=str(result.get("status", "COLLECTED")))
            except Exception as exc:  # o daemon continua; o estado registra apenas o tipo
                _status(status_path, "DEGRADED", detail=type(exc).__name__)

            remaining = max(0.0, args.interval_seconds - (time.monotonic() - started))
            deadline = time.monotonic() + remaining
            while not stop_requested and time.monotonic() < deadline:
                time.sleep(min(1.0, deadline - time.monotonic()))

        _status(status_path, "STOPPED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
