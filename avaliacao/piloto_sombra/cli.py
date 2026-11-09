"""CLI explícita do piloto em sombra; todas as saídas são JSON."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from .core import RELEASE_ACKNOWLEDGEMENT, ShadowPilot, ShadowPilotError


DEFAULT_DB = Path(__file__).resolve().parents[1] / "runtime" / "piloto_sombra.sqlite3"


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m avaliacao.piloto_sombra",
        description="Ledger local de piloto em sombra sem capacidade de mutar o GLPI.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(os.getenv("SHADOW_PILOT_DB", str(DEFAULT_DB))),
        help="Banco SQLite local (padrão: avaliacao/runtime/piloto_sombra.sqlite3).",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="Inicializa banco com kill switch ligado.")
    init.add_argument("--actor", required=True)
    init.add_argument("--reason", default="Inicialização segura: kill switch ligado")

    commands.add_parser("status", help="Exibe controles, estados e integridade.")
    commands.add_parser("verify-audit", help="Valida toda a cadeia de auditoria.")
    commands.add_parser("metrics", help="Calcula métricas do piloto e subgrupos.")
    commands.add_parser(
        "export-research-labels",
        help="Exporta somente rótulos humanos; nunca comandos de aplicação.",
    )
    queue = commands.add_parser("queue", help="Lista a fila obrigatória de revisão.")
    queue.add_argument("--limit", type=int, default=100)

    capture = commands.add_parser("capture", help="Registra uma predição apenas em sombra.")
    capture.add_argument("--ticket-ref", required=True)
    capture.add_argument("--task", required=True, choices=("classification", "deduplication"))
    capture.add_argument("--label", required=True)
    capture.add_argument("--confidence", required=True, type=float)
    capture.add_argument("--model-id", required=True)
    capture.add_argument("--model-version", required=True)
    capture.add_argument("--trace-id", required=True)
    capture.add_argument("--input-sha256", required=True)
    capture.add_argument("--prediction-sha256", required=True)
    capture.add_argument("--subgroup", required=True)
    capture.add_argument("--critical-risk", action="store_true")
    capture.add_argument("--actor", default="shadow-ingest")
    capture.add_argument("--idempotency-key", required=True)

    review = commands.add_parser("review", help="Registra revisão humana independente.")
    review.add_argument("--case-id", required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument(
        "--decision", required=True, choices=("LABEL", "REJECT", "ABSTAIN")
    )
    review.add_argument("--label")
    review.add_argument("--rationale", required=True)
    review.add_argument("--idempotency-key", required=True)

    adjudicate = commands.add_parser(
        "adjudicate", help="Resolve discordância com terceiro humano independente."
    )
    adjudicate.add_argument("--case-id", required=True)
    adjudicate.add_argument("--adjudicator", required=True)
    adjudicate.add_argument("--outcome", required=True, choices=("CONFIRM", "REJECT"))
    adjudicate.add_argument("--label")
    adjudicate.add_argument("--rationale", required=True)
    adjudicate.add_argument("--idempotency-key", required=True)

    engage = commands.add_parser("engage-kill-switch", help="Suspende imediatamente casos abertos.")
    engage.add_argument("--actor", required=True)
    engage.add_argument("--reason", required=True)
    engage.add_argument("--idempotency-key", required=True)

    release = commands.add_parser(
        "release-kill-switch", help="Libera somente o fluxo local de revisão humana."
    )
    release.add_argument("--actor", required=True)
    release.add_argument("--reason", required=True)
    release.add_argument(
        "--acknowledge",
        required=True,
        help=f"Valor obrigatório: {RELEASE_ACKNOWLEDGEMENT}",
    )
    release.add_argument("--idempotency-key", required=True)

    rollback = commands.add_parser("rollback", help="Invalida localmente um caso do piloto.")
    rollback.add_argument("--case-id", required=True)
    rollback.add_argument("--actor", required=True)
    rollback.add_argument("--reason", required=True)
    rollback.add_argument("--idempotency-key", required=True)
    return parser


def _execute(args: argparse.Namespace) -> Any:
    if args.command == "init":
        return ShadowPilot.initialize(args.db, actor_id=args.actor, reason=args.reason).status()
    pilot = ShadowPilot(args.db)
    if args.command == "status":
        return pilot.status()
    if args.command == "verify-audit":
        return pilot.verify_audit()
    if args.command == "metrics":
        return pilot.metrics()
    if args.command == "export-research-labels":
        return pilot.export_research_labels()
    if args.command == "queue":
        return pilot.queue(limit=args.limit)
    if args.command == "capture":
        return pilot.capture_prediction(
            source_ticket_ref=args.ticket_ref,
            task=args.task,
            prediction_label=args.label,
            prediction_confidence=args.confidence,
            model_id=args.model_id,
            model_version=args.model_version,
            inference_trace_id=args.trace_id,
            input_sha256=args.input_sha256,
            prediction_sha256=args.prediction_sha256,
            subgroup=args.subgroup,
            critical_risk=args.critical_risk,
            actor_id=args.actor,
            idempotency_key=args.idempotency_key,
        )
    if args.command == "review":
        return pilot.record_review(
            case_id=args.case_id,
            reviewer_id=args.reviewer,
            decision=args.decision,
            proposed_label=args.label,
            rationale=args.rationale,
            idempotency_key=args.idempotency_key,
        )
    if args.command == "adjudicate":
        return pilot.adjudicate(
            case_id=args.case_id,
            adjudicator_id=args.adjudicator,
            outcome=args.outcome,
            final_label=args.label,
            rationale=args.rationale,
            idempotency_key=args.idempotency_key,
        )
    if args.command == "engage-kill-switch":
        return pilot.engage_kill_switch(
            actor_id=args.actor,
            reason=args.reason,
            idempotency_key=args.idempotency_key,
        )
    if args.command == "release-kill-switch":
        return pilot.release_kill_switch(
            actor_id=args.actor,
            reason=args.reason,
            acknowledgement=args.acknowledge,
            idempotency_key=args.idempotency_key,
        )
    if args.command == "rollback":
        return pilot.rollback_case(
            case_id=args.case_id,
            actor_id=args.actor,
            reason=args.reason,
            idempotency_key=args.idempotency_key,
        )
    raise AssertionError(f"Comando não tratado: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _print(_execute(args))
        return 0
    except ShadowPilotError as exc:
        print(
            json.dumps(
                {"error": {"type": type(exc).__name__, "message": str(exc)}},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
