#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from avaliacao.confirmatorio.amostra import planejar_zero_eventos  # noqa: E402
from avaliacao.confirmatorio.avaliar import (  # noqa: E402
    executar_avaliacao_confirmatoria,
    reservar_abertura_confirmatoria,
    status_execucao,
)
from avaliacao.confirmatorio.familias import import_registry  # noqa: E402
from avaliacao.confirmatorio.preregistro import (  # noqa: E402
    congelar_preregistro,
    criar_rascunho,
    verificar_preregistro_congelado,
)


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Administra o holdout confirmatório one-shot sem criar dados artificiais."
    )
    commands = root.add_subparsers(dest="command", required=True)

    sample = commands.add_parser("planejar-amostra")
    sample.add_argument("--limite-superior", type=float, default=0.02)
    sample.add_argument("--confianca", type=float, default=0.95)
    sample.add_argument("--fracao-exposta", type=float, required=True)
    sample.add_argument("--perdas", type=float, default=0.0)
    sample.add_argument("--efeito-desenho", type=float, default=1.0)

    families = commands.add_parser("importar-familias")
    families.add_argument("--origem", type=Path, required=True)
    families.add_argument("--dataset", type=Path, required=True)
    families.add_argument("--manifesto", type=Path, required=True)
    families.add_argument("--exclusoes", type=Path)

    draft = commands.add_parser("criar-rascunho")
    draft.add_argument("--config", type=Path, required=True)
    draft.add_argument("--dataset", type=Path, required=True)
    draft.add_argument("--manifesto", type=Path, required=True)
    draft.add_argument("--candidato", type=Path, required=True)
    draft.add_argument("--saida", type=Path, required=True)
    draft.add_argument("--exclusoes", type=Path)

    freeze = commands.add_parser("congelar")
    freeze.add_argument("--rascunho", type=Path, required=True)
    freeze.add_argument("--saida", type=Path, required=True)

    verify = commands.add_parser("verificar")
    verify.add_argument("--preregistro", type=Path, required=True)

    status = commands.add_parser("status")
    status.add_argument("--preregistro", type=Path, required=True)

    reserve = commands.add_parser("reservar-abertura")
    reserve.add_argument("--preregistro", type=Path, required=True)
    reserve.add_argument("--confirmar-abertura-irreversivel", action="store_true")

    execute = commands.add_parser(
        "registrar-predicoes",
        aliases=["executar-uma-vez"],
    )
    execute.add_argument("--preregistro", type=Path, required=True)
    execute.add_argument("--predicoes", type=Path, required=True)
    execute.add_argument(
        "--confirmar-registro-irreversivel",
        action="store_true",
        help="Confirma que erro ou interrupção consome o único registro de predições.",
    )
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "planejar-amostra":
        _print(
            planejar_zero_eventos(
                maximum_upper=args.limite_superior,
                confidence=args.confianca,
                expected_exposure_fraction=args.fracao_exposta,
                attrition_fraction=args.perdas,
                design_effect=args.efeito_desenho,
            )
        )
    elif args.command == "importar-familias":
        _print(
            import_registry(
                args.origem,
                args.dataset,
                args.manifesto,
                exclusions_path=args.exclusoes,
            )
        )
    elif args.command == "criar-rascunho":
        _print(
            criar_rascunho(
                evaluation_config_path=args.config,
                dataset_path=args.dataset,
                dataset_manifest_path=args.manifesto,
                candidate_artifact_path=args.candidato,
                output_path=args.saida,
                exclusions_path=args.exclusoes,
            )
        )
    elif args.command == "congelar":
        _print(congelar_preregistro(draft_path=args.rascunho, output_path=args.saida))
    elif args.command == "verificar":
        document = verificar_preregistro_congelado(args.preregistro)
        _print(
            {
                "status": "PASS",
                "protocol_id": document["protocol_id"],
                "contract_sha256": document["contract_sha256"],
                "scientific_result": False,
            }
        )
    elif args.command == "status":
        _print(status_execucao(args.preregistro))
    elif args.command == "reservar-abertura":
        _print(
            reservar_abertura_confirmatoria(
                preregistration_path=args.preregistro,
                confirm_irreversible_open=args.confirmar_abertura_irreversivel,
            )
        )
    elif args.command in {"registrar-predicoes", "executar-uma-vez"}:
        _print(
            executar_avaliacao_confirmatoria(
                preregistration_path=args.preregistro,
                predictions_path=args.predicoes,
                confirm_predictions_registration_once=args.confirmar_registro_irreversivel,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
