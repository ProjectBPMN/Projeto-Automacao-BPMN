from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from avaliacao.operacional.core import (  # noqa: E402
    DEFAULT_POLICY_PATH,
    ROOT,
    bounded_load_probe,
    collect_live_point_in_time,
    collect_static_audit,
    evaluate_drift,
    evaluate_slo,
    isolated_failure_simulation,
    load_json,
    load_policy,
    project_env,
    utc_now,
    write_json,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validação operacional segura. Por padrão executa apenas auditoria estática, "
            "simulação efêmera no loopback e avaliações sobre arquivos locais."
        )
    )
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--metrics", type=Path, help="JSON de métricas da janela observada")
    parser.add_argument("--drift-reference", type=Path, help="Snapshot de referência")
    parser.add_argument("--drift-current", type=Path, help="Snapshot corrente")
    parser.add_argument("--live-read-only", action="store_true", help="Coleta pontual explícita dos serviços locais")
    parser.add_argument("--load-url", help="Endpoint loopback permitido para cenário de carga limitado")
    parser.add_argument("--load-payload", type=Path, help="JSON opcional para POST ao serviço local")
    parser.add_argument("--load-requests", type=int, default=50)
    parser.add_argument("--load-concurrency", type=int, default=4)
    parser.add_argument("--load-timeout", type=float, default=3.0)
    parser.add_argument(
        "--token-env",
        default="IA_LOCAL_API_TOKEN",
        help="Nome da variável que contém o token; o valor nunca é aceito na CLI nem gravado no relatório",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Autoriza exclusivamente o cenário de carga solicitado; não altera configuração ou dados",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true", help="Retorna código não zero quando houver FAIL")
    return parser


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    policy = load_policy(args.policy)
    if bool(args.drift_reference) != bool(args.drift_current):
        raise ValueError("--drift-reference e --drift-current devem ser informados juntos")
    if args.load_payload and not args.load_url:
        raise ValueError("--load-payload exige --load-url")
    if args.load_url and not args.apply:
        load_result: dict[str, Any] = {
            "status": "NOT_RUN",
            "reason": "O cenário de carga exige --apply explícito.",
            "scientific_result": False,
        }
    elif args.load_url:
        token = os.environ.get(args.token_env, "") or project_env(ROOT).get(
            args.token_env, ""
        )
        payload = load_json(args.load_payload) if args.load_payload else None
        load_result = bounded_load_probe(
            url=args.load_url,
            requests_count=args.load_requests,
            concurrency=args.load_concurrency,
            timeout_seconds=args.load_timeout,
            token=token,
            payload=payload,
            policy=policy,
        )
    else:
        load_result = {"status": "NOT_REQUESTED", "scientific_result": False}

    metrics = load_json(args.metrics) if args.metrics else {}
    slo_result = evaluate_slo(metrics, policy)
    drift_result = (
        evaluate_drift(load_json(args.drift_reference), load_json(args.drift_current), policy=policy)
        if args.drift_reference and args.drift_current
        else {"status": "NOT_REQUESTED", "scientific_result": False}
    )
    live_result = (
        collect_live_point_in_time()
        if args.live_read_only
        else {
            "status": "NOT_REQUESTED",
            "reason": "Use --live-read-only para uma coleta pontual explícita.",
            "scientific_result": False,
        }
    )
    results_dir = ROOT / "avaliacao" / "resultados" / "operacional"
    least_path = results_dir / "postgres-menor-privilegio-20260902.json"
    restore_path = results_dir / "restore-volume-n8n-20260902.json"
    windows_path = ROOT / "avaliacao" / "runtime" / "monitoring" / "windows.json"
    accelerated_windows_path = results_dir / "janelas-aceleradas-proxy-20260902.json"
    homolog_path = results_dir / "homologacao-isolada-20260902.json"
    runtime_state_path = results_dir / "estado-runtime-final-20260902.json"
    e2e_path = ROOT / "avaliacao" / "resultados" / "e2e-pipeline-local-v1.8.0-20260902-1950.json"
    c1_path = results_dir / "carga-classificacao-c1-20260902.json"
    c4_path = results_dir / "carga-classificacao-c4-20260902.json"
    least_payload = load_json(least_path) if least_path.is_file() else {}
    restore_payload = load_json(restore_path) if restore_path.is_file() else {}
    windows_payload = load_json(windows_path) if windows_path.is_file() else {}
    accelerated_windows = load_json(accelerated_windows_path) if accelerated_windows_path.is_file() else {}
    homolog = load_json(homolog_path) if homolog_path.is_file() else {}
    runtime_state = load_json(runtime_state_path) if runtime_state_path.is_file() else {}
    e2e = load_json(e2e_path) if e2e_path.is_file() else {}
    historical_load = {
        "status": "OBSERVED" if c1_path.is_file() and c4_path.is_file() else "NOT_AVAILABLE",
        "evidence_status": "BOUNDED_TECHNICAL_LOAD_SCENARIOS",
        "scientific_result": False,
        "artifacts": [
            str(path.relative_to(ROOT))
            for path in (c1_path, c4_path)
            if path.is_file()
        ],
        "interpretation_limit": (
            "Comprova somente os cenários limitados executados; saturação e HTTP 429 "
            "são resultados válidos e não devem ser ocultados."
        ),
    }
    least_evidence = {
        "status": "PASS" if least_payload.get("status") == "PASS" else "NOT_AVAILABLE",
        "artifact": str(least_path.relative_to(ROOT)) if least_path.is_file() else None,
        "runtime_login": least_payload.get("remediation", {}).get("runtime_login"),
        "ddl_denial_sqlstate": least_payload.get("remediation", {}).get("ddl_denial_sqlstate"),
        "scientific_result": False,
    }
    restore_result = restore_payload.get("result", {})
    restore_evidence = {
        "status": (
            "PASS"
            if restore_payload.get("status") == "PASS" and restore_result.get("status") == "PASS"
            else "NOT_AVAILABLE"
        ),
        "artifact": str(restore_path.relative_to(ROOT)) if restore_path.is_file() else None,
        "rollback_recovery_minutes": restore_result.get("rollback_recovery_minutes"),
        "restored_workflow_count": restore_result.get("isolated_restore", {}).get("exported_workflow_count"),
        "scientific_result": False,
    }
    sections = {
        "static_audit": collect_static_audit(),
        "isolated_failure_simulation": isolated_failure_simulation(policy),
        "monitoring_plan": {
            "status": "PROPOSED_NOT_APPROVED",
            "collector_status": policy["monitoring"]["collector_status"],
            "required_signals": policy["monitoring"]["required_signals"],
            "automatic_retraining_allowed": policy["monitoring"]["automatic_retraining_allowed"],
            "scientific_result": False,
        },
        "slo_proposal_evaluation": slo_result,
        "drift": drift_result,
        "bounded_load": load_result,
        "historical_bounded_load_evidence": historical_load,
        "least_privilege_evidence": least_evidence,
        "n8n_volume_restore_evidence": restore_evidence,
        "monitoring_windows": windows_payload or {"status": "NOT_AVAILABLE", "scientific_result": False},
        "accelerated_proxy_windows": accelerated_windows or {"status": "NOT_AVAILABLE", "scientific_result": False},
        "isolated_homologation": homolog or {"status": "NOT_AVAILABLE", "scientific_result": False},
        "runtime_queue_state": runtime_state or {"status": "NOT_AVAILABLE", "scientific_result": False},
        "synthetic_e2e": e2e or {"status": "NOT_AVAILABLE", "scientific_result": False},
        "live_point_in_time": live_result,
    }
    failing = [name for name, value in sections.items() if value.get("status") == "FAIL"]
    insufficient = [
        name
        for name, value in sections.items()
        if value.get("status") in {"INSUFFICIENT_DATA", "INCOMPATIBLE_SNAPSHOTS"}
    ]
    readiness_blockers = ["POLICY_NOT_INSTITUTIONALLY_APPROVED"]
    if least_evidence["status"] != "PASS":
        readiness_blockers.append("LEAST_PRIVILEGE_REMEDIATION_NOT_VERIFIED")
    if restore_evidence["status"] != "PASS":
        readiness_blockers.append("ISOLATED_BACKUP_RESTORE_NOT_VERIFIED_IN_THIS_REPORT")
    accelerated_complete = (
        accelerated_windows.get("status") == "THREE_ACCELERATED_PROXY_WINDOWS_COMPLETE"
        and int(accelerated_windows.get("window_count") or 0)
        >= int(policy["slo"]["minimum_observation_windows"])
    )
    if not accelerated_complete:
        readiness_blockers.append("THREE_COMPLETE_TECHNICAL_SLO_WINDOWS_NOT_VERIFIED")
    if homolog.get("status") != "PASS":
        readiness_blockers.append("ISOLATED_HOMOLOGATION_NOT_VERIFIED")
    if runtime_state.get("status") != "PASS":
        readiness_blockers.append("RUNTIME_QUEUE_OR_DLQ_NOT_CLEAN")
    if e2e.get("passed") is not True:
        readiness_blockers.append("SYNTHETIC_E2E_NOT_VERIFIED")
    if failing:
        readiness_blockers.append("FAILING_OPERATIONAL_CHECKS")
    if insufficient:
        readiness_blockers.append("INSUFFICIENT_OPERATIONAL_EVIDENCE")
    if (
        load_result.get("status") in {"NOT_REQUESTED", "NOT_RUN"}
        and historical_load["status"] != "OBSERVED"
    ):
        readiness_blockers.append("BOUNDED_LOAD_NOT_VERIFIED")
    return {
        "schema_version": "1.0.0",
        "generated_at": utc_now(),
        "mode": "EXPLICIT_ACTIVE_PROBE" if args.apply or args.live_read_only else "SAFE_LOCAL_DEFAULT",
        "policy_status": policy["status"],
        "institutionally_approved": False,
        "production_ready": False,
        "readiness_blockers": readiness_blockers,
        "scientific_result": False,
        "failing_sections": failing,
        "insufficient_sections": insufficient,
        "sections": sections,
        "interpretation_limit": (
            "O relatório reúne evidência técnica de escopo limitado. Não substitui aceite institucional, "
            "evidência longitudinal de produção ou avaliação científica confirmatória. As janelas "
            "intradiárias locais, quando completas, validam apenas o mecanismo técnico."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = build_report(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    if args.output:
        write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if args.strict and report["failing_sections"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
