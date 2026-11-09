from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

from project_env import load_project_env, postgres_connection_kwargs


ROOT = Path(__file__).resolve().parents[2]
load_project_env()


def connect_pg():
    return psycopg2.connect(
        **postgres_connection_kwargs(),
        connect_timeout=10,
        cursor_factory=RealDictCursor,
    )


def query(conn, sql: str, params: tuple = ()) -> list[dict]:
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Tipo não serializável: {type(value)!r}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def format_percent(numerator: int, denominator: int) -> str:
    return f"{100 * numerator / denominator:.2f}%" if denominator else "N/A"


def collect(since: datetime | None) -> dict:
    with connect_pg() as conn:
        collected_at = query(conn, "SELECT NOW() AS agora")[0]["agora"]
        historical = query(
            conn,
            """
            SELECT etapa,
                   COUNT(*)::int AS tentativas,
                   COUNT(*) FILTER (WHERE NOT erro_ia)::int AS respostas_validas,
                   COUNT(*) FILTER (WHERE erro_ia)::int AS erros,
                   COUNT(*) FILTER (
                     WHERE erro_ia AND (
                       mensagem_erro ILIKE '%%spacing%%'
                       OR mensagem_erro ILIKE '%%too many%%'
                       OR mensagem_erro ILIKE '%%high demand%%'
                       OR mensagem_erro ILIKE '%%503%%'
                     )
                   )::int AS erros_limite_ou_demanda,
                   MIN(criado_em) AS primeira_tentativa,
                   MAX(criado_em) AS ultima_tentativa
            FROM ia_decisoes
            GROUP BY etapa
            ORDER BY etapa
            """,
        )
        window = []
        if since is not None:
            window = query(
                conn,
                """
                SELECT etapa,
                       COUNT(*)::int AS tentativas,
                       COUNT(*) FILTER (WHERE NOT erro_ia)::int AS respostas_validas,
                       COUNT(*) FILTER (WHERE erro_ia)::int AS erros,
                       COUNT(*) FILTER (
                         WHERE erro_ia AND (
                           mensagem_erro ILIKE '%%spacing%%'
                           OR mensagem_erro ILIKE '%%too many%%'
                           OR mensagem_erro ILIKE '%%high demand%%'
                           OR mensagem_erro ILIKE '%%503%%'
                         )
                       )::int AS erros_limite_ou_demanda,
                       MIN(criado_em) AS primeira_tentativa,
                       MAX(criado_em) AS ultima_tentativa
                FROM ia_decisoes
                WHERE criado_em >= %s
                GROUP BY etapa
                ORDER BY etapa
                """,
                (since,),
            )
        queue = query(
            conn,
            """
            SELECT triagem_status,COALESCE(fila_etapa,'SEM_ETAPA') AS fila_etapa,
                   COUNT(*)::int AS quantidade
            FROM tickets_processados
            GROUP BY triagem_status,COALESCE(fila_etapa,'SEM_ETAPA')
            ORDER BY triagem_status,fila_etapa
            """,
        )
        dlq = query(
            conn,
            """
            SELECT COUNT(*)::int AS total,
                   COUNT(*) FILTER (WHERE resolvido_em IS NULL)::int AS abertas
            FROM fila_ia_dead_letter
            """,
        )[0]
        token_coverage = query(
            conn,
            """
            SELECT etapa,
                   COUNT(*) FILTER (
                     WHERE NOT erro_ia
                   )::int AS respostas_validas,
                   COUNT(*) FILTER (
                     WHERE api_response_raw#>>'{usageMetadata,totalTokenCount}'
                           ~ '^[0-9]+$'
                   )::int AS respostas_com_tokens,
                   SUM(CASE
                     WHEN api_response_raw#>>'{usageMetadata,promptTokenCount}'
                          ~ '^[0-9]+$'
                     THEN (api_response_raw#>>'{usageMetadata,promptTokenCount}')::bigint
                     ELSE 0 END)::bigint AS tokens_entrada,
                   SUM(CASE
                     WHEN api_response_raw#>>'{usageMetadata,candidatesTokenCount}'
                          ~ '^[0-9]+$'
                     THEN (api_response_raw#>>'{usageMetadata,candidatesTokenCount}')::bigint
                     ELSE 0 END)::bigint AS tokens_saida,
                   SUM(CASE
                     WHEN api_response_raw#>>'{usageMetadata,totalTokenCount}'
                          ~ '^[0-9]+$'
                     THEN (api_response_raw#>>'{usageMetadata,totalTokenCount}')::bigint
                     ELSE 0 END)::bigint AS tokens_total
            FROM ia_decisoes
            GROUP BY etapa
            ORDER BY etapa
            """,
        )
        research = query(
            conn,
            """
            SELECT
              (SELECT COUNT(*)::int FROM experimentos_avaliacao) AS experimentos,
              (SELECT COUNT(*)::int FROM experimentos_avaliacao
                WHERE status='CONCLUIDO') AS experimentos_concluidos,
              (SELECT COUNT(*)::int FROM avaliacoes_humanas
                WHERE run_id IS NOT NULL
                  AND COALESCE(NULLIF(classe_correta,''),NULLIF(decisao_humana,''))
                      IS NOT NULL) AS rotulos_humanos_com_run,
              (SELECT COUNT(*)::int FROM avaliacoes_humanas
                WHERE run_id IS NULL
                  AND COALESCE(NULLIF(classe_correta,''),NULLIF(decisao_humana,''))
                      IS NOT NULL) AS rotulos_historicos_sem_run
            """,
        )[0]
        queue_history = query(
            conn,
            """
            SELECT COUNT(*)::int AS amostras,
                   MIN(criado_em) AS inicio,
                   MAX(criado_em) AS fim,
                   SUM(liberados_ciclo)::int AS liberacoes_registradas,
                   MAX(pendentes)::int AS maximo_pendentes,
                   MAX(reservados)::int AS maximo_reservados
            FROM fila_ia_metricas
            """,
        )[0]

    workflow_dir = ROOT / "n8n" / "workflows" / "Versão9"
    hashes = {
        path.name: sha256(path)
        for path in sorted(workflow_dir.glob("V9-WF*.json"))
    }
    hashes["database/init_v9.sql"] = sha256(ROOT / "database" / "init_v9.sql")
    hashes["avaliacao/manifesto_modelo_prompts.json"] = sha256(
        ROOT / "avaliacao" / "manifesto_modelo_prompts.json"
    )

    return {
        "status_evidencia": "DIAGNOSTICO_OPERACIONAL_PRELIMINAR",
        "scientific_result": False,
        "collected_at": collected_at,
        "window_start": since,
        "attempts_historical": historical,
        "attempts_window": window,
        "queue_snapshot": queue,
        "dead_letter": dlq,
        "token_coverage": token_coverage,
        "research_gates": research,
        "queue_history": queue_history,
        "artifact_hashes": hashes,
        "interpretation_limits": [
            "Tentativas e retentativas não são unidades independentes nem medem acurácia.",
            "Erros históricos atravessam versões de workflow e incluem defeitos já corrigidos.",
            "Sem run_id experimental e gabarito adjudicado não há matriz de confusão do Gemini.",
            "Telemetria histórica de fila anterior às correções não estima a vazão aprovada.",
        ],
    }


def markdown(payload: dict) -> str:
    lines = [
        "# Diagnóstico operacional preliminar",
        "",
        f"Coleta: `{json_default(payload['collected_at'])}`.",
        "",
        "**Status:** diagnóstico de engenharia, não resultado científico de eficácia.",
        "",
        "## Tentativas instrumentadas no histórico",
        "",
        "| Etapa | Tentativas | Respostas válidas | Erros | Sucesso técnico | Erros de limite/demanda |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in payload["attempts_historical"]:
        lines.append(
            f"| {row['etapa']} | {row['tentativas']} | {row['respostas_validas']} | "
            f"{row['erros']} | {format_percent(row['respostas_validas'], row['tentativas'])} | "
            f"{row['erros_limite_ou_demanda']} |"
        )
    if payload["window_start"] is not None:
        lines.extend(
            [
                "",
                f"## Janela após a correção ({json_default(payload['window_start'])})",
                "",
                "| Etapa | Tentativas | Respostas válidas | Erros | Sucesso técnico | Erros de limite/demanda |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for row in payload["attempts_window"]:
            lines.append(
                f"| {row['etapa']} | {row['tentativas']} | {row['respostas_validas']} | "
                f"{row['erros']} | {format_percent(row['respostas_validas'], row['tentativas'])} | "
                f"{row['erros_limite_ou_demanda']} |"
            )
    lines.extend(
        [
            "",
            "`Sucesso técnico` significa que a resposta passou pelo normalizador; não significa acerto contra gabarito.",
            "",
            "## Cobertura histórica de tokens",
            "",
            "| Etapa | Respostas válidas | Com metadados de tokens | Entrada | Saída | Total do provedor |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in payload["token_coverage"]:
        lines.append(
            f"| {row['etapa']} | {row['respostas_validas']} | {row['respostas_com_tokens']} | "
            f"{row['tokens_entrada']} | {row['tokens_saida']} | {row['tokens_total']} |"
        )
    lines.extend(
        [
            "",
            "A cobertura parcial impede estimativa histórica confiável de custo por decisão.",
            "",
            "## Estado da fila na coleta",
            "",
            "| Estado | Etapa | Quantidade |",
            "|---|---|---:|",
        ]
    )
    for row in payload["queue_snapshot"]:
        lines.append(
            f"| {row['triagem_status']} | {row['fila_etapa']} | {row['quantidade']} |"
        )
    research = payload["research_gates"]
    dlq = payload["dead_letter"]
    lines.extend(
        [
            "",
            "## Gates científicos",
            "",
            f"- Execuções experimentais registradas: **{research['experimentos']}**.",
            f"- Execuções experimentais concluídas: **{research['experimentos_concluidos']}**.",
            f"- Rótulos humanos vinculados a `run_id`: **{research['rotulos_humanos_com_run']}**.",
            f"- Rótulos históricos sem `run_id` (não confirmatórios): **{research['rotulos_historicos_sem_run']}**.",
            f"- Dead letters: **{dlq['total']}**, das quais **{dlq['abertas']}** abertas.",
            "",
            "Logo, ainda não é válido publicar acurácia, F1 ou matriz de confusão do Gemini. O histórico prova apenas comportamento operacional e falhas de disponibilidade.",
            "",
            "## Limites de interpretação",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in payload["interpretation_limits"])
    lines.extend(
        [
            "",
            "## Reprodutibilidade",
            "",
            "Os hashes dos seis JSONs implantáveis, do schema SQL e do manifesto foram preservados no JSON desta coleta.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Gera um diagnóstico operacional sem confundi-lo com eficácia científica."
    )
    parser.add_argument("--saida-dir", type=Path, required=True)
    parser.add_argument(
        "--desde",
        type=datetime.fromisoformat,
        help="Início ISO da janela técnica, por exemplo 2026-07-10T16:07:00-03:00.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = collect(args.desde)
    args.saida_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.saida_dir / "diagnostico_operacional.json"
    md_path = args.saida_dir / "diagnostico_operacional.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=json_default) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(markdown(payload), encoding="utf-8")
    print(f"[OK] JSON: {json_path}")
    print(f"[OK] Markdown: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
