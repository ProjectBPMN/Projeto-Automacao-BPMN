from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
COMPOSE = ROOT / "n8n" / "docker-compose.yml"
GENERATOR = SCRIPT_DIR / "gerar_dataset_avaliacao.py"
CHECKER = SCRIPT_DIR / "conferir_gabarito.py"
VALIDATOR = ROOT / "n8n" / "workflows" / "Versão9" / "validate_v9_static.py"
LOCAL_DOCKER_CONTEXT = os.getenv("DOCKER_CONTEXT", "desktop-linux")
os.environ["DOCKER_CONTEXT"] = LOCAL_DOCKER_CONTEXT


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    cmd = list(command)
    if cmd and cmd[0] == "docker" and (len(cmd) < 2 or cmd[1] != "--context"):
        cmd = ["docker", "--context", LOCAL_DOCKER_CONTEXT, *cmd[1:]]
    result = subprocess.run(cmd, cwd=ROOT, env=env, check=False)
    if result.returncode:
        raise RuntimeError(
            f"Comando falhou ({result.returncode}): {' '.join(cmd)}"
        )


def queue_count() -> int:
    result = subprocess.run(
        [
            "docker",
            "--context",
            LOCAL_DOCKER_CONTEXT,
            "exec",
            "glpi-dedup-db",
            "psql",
            "-U",
            "triagem_user",
            "-d",
            "triagem",
            "-Atc",
            (
                "SELECT count(*) FROM tickets_processados "
                "WHERE triagem_status IN ("
                "'PENDENTE_FILA_IA','FILA_IA_LIBERADA','CLASSIFICANDO_DUP',"
                "'CLASSIFICANDO','AGUARDANDO_FILA_CLASSIFICACAO');"
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Falha ao consultar a fila.")
    return int(result.stdout.strip())


def recreate_n8n(demo_available: bool) -> None:
    env = os.environ.copy()
    env["DEMO_EQUIPE_DISPONIVEL"] = "true" if demo_available else "false"
    run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE),
            "up",
            "-d",
            "--force-recreate",
            "n8n",
        ],
        env=env,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Executa três cenários controlados com DEMO_EQUIPE_DISPONIVEL=false "
            "e restaura a configuração padrão ao terminar."
        )
    )
    parser.add_argument("--run-id", default="")
    parser.add_argument("--seed", type=int, default=20260702)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--saida-dir", default="avaliacao/resultados")
    args = parser.parse_args()

    run([sys.executable, str(VALIDATOR)])
    pending = queue_count()
    if pending:
        raise SystemExit(
            f"Execução recusada: há {pending} item(ns) operacionais na fila. "
            "Esvazie ou isole a fila antes do perfil DEMO_OFF."
        )

    run_id = args.run_id or "DEMO-OFF-" + dt.datetime.now().strftime(
        "%Y%m%dT%H%M%S"
    )
    out_dir = ROOT / args.saida_dir / run_id
    out_dir.mkdir(parents=True, exist_ok=False)
    dataset_prefix = out_dir / "dataset"

    recreate_n8n(False)
    try:
        run(
            [
                sys.executable,
                str(GENERATOR),
                "--por-cenario",
                "1",
                "--seed",
                str(args.seed),
                "--split",
                "VALIDACAO",
                "--perfil-operacional",
                "DEMO_OFF",
                "--run-id",
                run_id,
                "--saida",
                str(dataset_prefix),
                "--criar-glpi",
                "--registrar-dataset-controle",
            ]
        )
        run(
            [
                sys.executable,
                str(CHECKER),
                "--run-id",
                run_id,
                "--liberar-fila",
                "--aguardar-processamento",
                "--resolver-confirmacoes-automaticas",
                "--timeout",
                str(args.timeout),
                "--registrar-gabarito",
                "--gerar-relatorio",
                "--saida",
                str(out_dir.relative_to(ROOT)),
                "--seed",
                str(args.seed),
            ]
        )
    finally:
        recreate_n8n(True)

    print(f"[OK] Perfil DEMO_OFF concluído: {run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
