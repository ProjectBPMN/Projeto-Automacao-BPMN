from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from estatistica import bootstrap_binary, bootstrap_multiclass
from project_env import load_project_env, postgres_connection_kwargs

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Instale psycopg2-binary para executar este conferidor.") from exc


ROOT = Path(__file__).resolve().parents[2]
load_project_env()
FISCAL_WEBHOOK_URL = os.getenv(
    "FISCAL_WEBHOOK_URL",
    "http://localhost:5678/webhook/fiscal-decisao-fiscal-ic-2026",
)
WF04_WEBHOOK_PATH = "/webhook/fiscal-decisao-fiscal-ic-2026"
WF05_WEBHOOK_PATH = "/webhook/avaliacao-humana-v9"
CLASS_CLASSES = {
    "OBRA",
    "DEMO",
    "SOB_DEMANDA",
    "TRIAGEM_MANUAL",
}
DEDUP_CLASSES = {"DUPLICADO", "NAO_DUPLICADO"}
TERMINAL_TRIAGE = {
    "ERRO_IA",
    "TRIAGEM_MANUAL",
    "DUPLICADO_FECHADO",
    "ATRIBUIDO_DEMO",
    "PLANEJADO_DEMO_SEM_EQUIPE",
    "ENCAMINHADO_PLANEJADO",
    "FECHADO_OBRA",
}
LABEL_APPROVAL_KEYS = (
    "schema_version", "dataset_sha256", "planilha_sha256",
    "perfil_avaliadores_sha256", "versao_instrucoes",
    "total_decisoes_nucleo", "total_rotulos_propagados", "total_decisoes",
    "unidade_revisao", "confiabilidade", "rotulos_adjudicados",
    "human_label_gate", "rendered_text_audit_gate",
    "auditoria_humana_concluida", "approved_for_benchmark", "approved",
    "auditoria_textual",
)
HUMAN_REVIEW_WEBHOOK_URL = os.getenv(
    "AVALIACAO_HUMANA_WEBHOOK_URL",
    "http://localhost:5678/webhook/avaliacao-humana-v9",
)
ORACLE_RUN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
ORACLE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


def _validated_oracle_endpoint(value: str, expected_path: str) -> str:
    """Allow a configurable host, but never a different workflow endpoint."""
    parsed = urllib.parse.urlsplit(str(value or "").strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != expected_path
    ):
        raise RuntimeError(
            f"ORACULO_BLOQUEADO: endpoint deve terminar exatamente em {expected_path}"
        )
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, expected_path, "", "")
    )


def label_approval_hash(payload: dict) -> str:
    subset = {key: payload.get(key) for key in LABEL_APPROVAL_KEYS}
    canonical = json.dumps(
        subset, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def connect_pg():
    return psycopg2.connect(
        **postgres_connection_kwargs(),
        connect_timeout=10,
        cursor_factory=RealDictCursor,
    )


def query(sql: str, params: tuple = ()) -> list[dict]:
    with connect_pg() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


def execute(sql: str, params: tuple = ()) -> None:
    with connect_pg() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()


def experiment(run_id: str) -> dict:
    rows = query(
        "SELECT * FROM experimentos_avaliacao WHERE run_id=%s",
        (run_id,),
    )
    if not rows:
        raise RuntimeError(f"run_id não encontrado: {run_id}")
    return rows[0]


def completion_gates(exp: dict) -> dict[str, bool]:
    split = str(exp.get("split") or "").upper()
    is_benchmark = split in {"TEST", "TESTE", "BENCHMARK"}
    return {
        "rotulos_validados": bool(exp.get("rotulos_validados")),
        "protocolo_rotulagem_validado": bool(
            exp.get("protocolo_rotulagem_validado")
        ),
        "auditoria_humana_concluida": (
            bool(exp.get("auditoria_humana_concluida"))
            if is_benchmark
            else True
        ),
    }


def reported_gate_status(exp: dict) -> dict[str, bool]:
    """Mostra o estado real sem confundir gate dispensado com revisão feita."""
    split = str(exp.get("split") or "").upper()
    human_audit_required = split in {"TEST", "TESTE", "BENCHMARK"}
    required_gates = completion_gates(exp)
    return {
        "rotulos_validados": bool(exp.get("rotulos_validados")),
        "protocolo_rotulagem_validado": bool(
            exp.get("protocolo_rotulagem_validado")
        ),
        "auditoria_humana_concluida": bool(
            exp.get("auditoria_humana_concluida")
        ),
        "auditoria_humana_exigida_nesta_fase": human_audit_required,
        "gates_obrigatorios_satisfeitos": all(required_gates.values()),
    }


def result_nature(
    exp: dict,
    gates: dict[str, bool] | None = None,
    integrity_errors: list[str] | None = None,
) -> tuple[str, bool]:
    """Classifica a evidência sem promover validação sintética a benchmark."""
    split = str(exp.get("split") or "").upper()
    gates = gates if gates is not None else completion_gates(exp)
    integrity_errors = integrity_errors or []
    if split in {"TEST", "TESTE", "BENCHMARK"}:
        confirmatory = all(gates.values()) and not integrity_errors
        return (
            "BENCHMARK CONFIRMATORIO" if confirmatory else "BENCHMARK INCOMPLETO",
            confirmatory,
        )
    if split in {"VALIDACAO", "VALIDATION", "AUTOMATED_VALIDATION"}:
        return "VALIDACAO AUTOMATIZADA NAO CONFIRMATORIA", False
    if split in {"PILOTO", "PILOT"}:
        return "PILOTO EXPLORATORIO NAO CONFIRMATORIO", False
    return "EVIDENCIA TECNICA NAO CONFIRMATORIA", False


def require_completion_gates(exp: dict) -> None:
    gates = completion_gates(exp)
    missing = [name for name, passed in gates.items() if not passed]
    if missing:
        raise RuntimeError(
            "Experimento não pode ser concluído; gates ausentes: "
            + ", ".join(missing)
        )
    integrity_errors = confirmatory_model_integrity(exp)
    if integrity_errors:
        raise RuntimeError(
            "Experimento não pode ser concluído; integridade do modelo confirmatório: "
            + "; ".join(integrity_errors)
        )


def confirmatory_model_integrity(exp: dict) -> list[str]:
    split = str(exp.get("split") or "").upper()
    if split not in {"TEST", "TESTE", "BENCHMARK"}:
        return []
    run_id = str(exp.get("run_id") or "")
    expected_model = str(exp.get("modelo_ia") or "")
    generation = exp.get("generation_config") or {}
    if isinstance(generation, str):
        generation = json.loads(generation)
    expected_role = str(generation.get("ia_fixed_model_role") or "").upper()
    errors: list[str] = []
    if generation.get("ia_failover_enabled") is not False:
        errors.append("generation_config.ia_failover_enabled deve ser false")
    if str(generation.get("ia_execution_mode") or "").upper() != "BENCHMARK":
        errors.append("generation_config.ia_execution_mode deve ser BENCHMARK")
    if str(generation.get("ia_expected_model") or "") != expected_model:
        errors.append("ia_expected_model diverge de experimentos_avaliacao.modelo_ia")
    if expected_role not in {
        "PRIMARY",
        "SECONDARY",
        "LOCAL",
    }:
        errors.append("ia_fixed_model_role inválido ou ausente")

    rows = query(
        """
        WITH esperadas AS (
          SELECT run_id,ticket_id,'DEDUPLICACAO'::text AS etapa
          FROM dataset_controle WHERE run_id=%s AND duplicado_esperado IS NOT NULL
          UNION ALL
          SELECT run_id,ticket_id,'CLASSIFICACAO'::text
          FROM dataset_controle
          WHERE run_id=%s AND NULLIF(classificacao_esperada,'') IS NOT NULL
        ), finais AS (
          SELECT DISTINCT ON (i.ticket_id,i.etapa)
            i.ticket_id,i.etapa,i.versao_modelo,i.papel_modelo,
            i.fallback_utilizado,i.total_modelos_tentados,i.modo_execucao,
            i.elegivel_eficacia_confirmatoria
          FROM ia_decisoes i
          WHERE i.run_id=%s
          ORDER BY i.ticket_id,i.etapa,i.criado_em DESC,i.id DESC
        )
        SELECT
          COUNT(*)::int AS esperadas,
          COUNT(f.ticket_id)::int AS observadas,
          COUNT(*) FILTER (WHERE f.versao_modelo IS DISTINCT FROM %s)::int AS modelo_incorreto,
          COUNT(*) FILTER (WHERE f.papel_modelo IS DISTINCT FROM %s)::int AS papel_incorreto,
          COUNT(*) FILTER (WHERE COALESCE(f.fallback_utilizado,FALSE))::int AS fallback,
          COUNT(*) FILTER (WHERE f.total_modelos_tentados IS DISTINCT FROM 1)::int AS cadeia_invalida,
          COUNT(*) FILTER (WHERE f.modo_execucao IS DISTINCT FROM 'BENCHMARK')::int AS modo_incorreto,
          COUNT(*) FILTER (WHERE COALESCE(f.elegivel_eficacia_confirmatoria,FALSE)=FALSE)::int AS inelegiveis,
          COUNT(g.ticket_id)::int AS gabaritos_observados,
          COUNT(*) FILTER (WHERE COALESCE(g.gabarito_humano,FALSE))::int AS gabaritos_humanos,
          COUNT(*) FILTER (WHERE COALESCE(g.gabarito_sintetico,FALSE))::int AS gabaritos_sinteticos,
          COUNT(*) FILTER (WHERE g.fonte_gabarito='ORACULO_GABARITO')::int AS gabaritos_oraculo
        FROM esperadas e
        LEFT JOIN finais f ON f.ticket_id=e.ticket_id AND f.etapa=e.etapa
        LEFT JOIN vw_gabarito_final g
          ON g.run_id=e.run_id AND g.ticket_id=e.ticket_id AND g.etapa=e.etapa
        """,
        (run_id, run_id, run_id, expected_model, expected_role),
    )[0]
    if rows["esperadas"] != rows["observadas"]:
        errors.append(
            f"decisões finais incompletas: esperadas={rows['esperadas']}, observadas={rows['observadas']}"
        )
    if rows["esperadas"] != rows["gabaritos_observados"]:
        errors.append(
            "gabaritos finais incompletos: "
            f"esperados={rows['esperadas']}, observados={rows['gabaritos_observados']}"
        )
    if rows["esperadas"] != rows["gabaritos_humanos"]:
        errors.append(
            "gabarito confirmatório exige apenas fontes humanas normativas "
            "(ADJUDICADO ou REVISAO_HUMANA): "
            f"humanos={rows['gabaritos_humanos']}, esperados={rows['esperadas']}, "
            f"sintéticos={rows['gabaritos_sinteticos']}, oráculo={rows['gabaritos_oraculo']}"
        )
    for key in (
        "modelo_incorreto",
        "papel_incorreto",
        "fallback",
        "cadeia_invalida",
        "modo_incorreto",
        "inelegiveis",
    ):
        if int(rows[key] or 0) > 0:
            errors.append(f"{key}={rows[key]}")

    attempts = query(
        """
        SELECT
          COUNT(*)::int AS total,
          COUNT(*) FILTER (WHERE versao_modelo IS DISTINCT FROM %s)::int AS modelo_incorreto,
          COUNT(*) FILTER (WHERE papel_modelo IS DISTINCT FROM %s)::int AS papel_incorreto,
          COUNT(*) FILTER (WHERE fallback_utilizado)::int AS fallback,
          COUNT(DISTINCT versao_modelo)::int AS modelos_distintos,
          COUNT(*) FILTER (WHERE status_tentativa='POLICY_ERROR')::int AS erros_politica
        FROM ia_tentativas_modelo
        WHERE run_id=%s
        """,
        (expected_model, expected_role, run_id),
    )[0]
    if int(attempts["total"] or 0) == 0:
        errors.append("nenhuma tentativa de provedor registrada")
    if int(attempts["modelo_incorreto"] or 0) > 0 or int(attempts["modelos_distintos"] or 0) > 1:
        errors.append("tentativas misturaram modelos no mesmo run_id")
    if int(attempts["papel_incorreto"] or 0) > 0:
        errors.append("tentativas usaram papel diferente do congelado")
    if int(attempts["fallback"] or 0) > 0:
        errors.append("tentativas confirmatórias contêm fallback")
    if int(attempts["erros_politica"] or 0) > 0:
        errors.append("gateway registrou violação de política experimental")
    return errors


def gold_source_summary(run_id: str) -> dict:
    """Resume a proveniência real dos rótulos finais de um run."""
    return query(
        """
        SELECT
          COUNT(*)::int AS total,
          COUNT(*) FILTER (WHERE gabarito_humano)::int AS humanos,
          COUNT(*) FILTER (WHERE gabarito_sintetico)::int AS sinteticos,
          COUNT(*) FILTER (WHERE fonte_gabarito='ORACULO_GABARITO')::int AS oraculo,
          COUNT(*) FILTER (WHERE NOT gabarito_humano)::int AS nao_humanos
        FROM vw_gabarito_final
        WHERE run_id=%s
        """,
        (run_id,),
    )[0]


def set_experiment_status(run_id: str, status: str) -> None:
    allowed = {"PREPARANDO", "CALIBRANDO", "EXECUTANDO", "CONCLUIDO", "FALHOU"}
    if status not in allowed:
        raise ValueError(f"Status experimental inválido: {status}")
    execute(
        """
        UPDATE experimentos_avaliacao
        SET status=%s,
            iniciado_em=CASE WHEN %s IN ('CALIBRANDO','EXECUTANDO')
                              THEN COALESCE(iniciado_em,NOW()) ELSE iniciado_em END,
            concluido_em=CASE WHEN %s IN ('CONCLUIDO','FALHOU')
                              THEN NOW() ELSE concluido_em END
        WHERE run_id=%s
          AND status NOT LIKE 'INVALIDADO%%'
          AND status NOT LIKE 'EXECUTION_ABORTED%%'
        """,
        (status, status, status, run_id),
    )


def pending_summary(run_id: str) -> dict:
    rows = query(
        """
        SELECT
          COUNT(*)::int AS total,
          COUNT(*) FILTER (WHERE tp.em_aprovacao_fiscal=TRUE)::int AS fiscal,
          COUNT(*) FILTER (
            WHERE COALESCE(tp.triagem_status,'') NOT IN (
              'ERRO_IA','TRIAGEM_MANUAL','DUPLICADO_FECHADO','ATRIBUIDO_DEMO',
              'PLANEJADO_DEMO_SEM_EQUIPE','ENCAMINHADO_PLANEJADO','FECHADO_OBRA'
            )
          )::int AS pendentes,
          COUNT(*) FILTER (WHERE tp.triagem_status='ERRO_IA')::int AS erros
        FROM dataset_controle dc
        LEFT JOIN tickets_processados tp ON tp.id=dc.ticket_id
        WHERE dc.run_id=%s
        """,
        (run_id,),
    )
    return rows[0]


def _project_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for path in (ROOT / "n8n" / ".env", ROOT / "n8n" / ".env.local"):
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    values.update({key: value for key, value in os.environ.items() if value is not None})
    return values


def _oracle_guard(run_id: str) -> dict[str, str]:
    """Falha fechada antes de ler qualquer rótulo ou token de confirmação."""
    env = _project_env()
    if not ORACLE_RUN_RE.fullmatch(str(run_id or "")):
        raise RuntimeError("ORACULO_BLOQUEADO: run_id inválido")
    if env.get("TEST_MODE", "").strip().lower() != "true":
        raise RuntimeError("ORACULO_BLOQUEADO: TEST_MODE não está ativo")
    if env.get("TEST_AUTO_HUMAN_CONFIRMATION", "").strip().lower() != "true":
        raise RuntimeError("ORACULO_BLOQUEADO: confirmação automática não está ativa")
    secret = env.get("TEST_AUTO_REVIEW_TOKEN", "").strip()
    if not ORACLE_TOKEN_RE.fullmatch(secret):
        raise RuntimeError("ORACULO_BLOQUEADO: token do assessor ausente ou inválido")
    env["FISCAL_WEBHOOK_URL"] = _validated_oracle_endpoint(
        env.get("FISCAL_WEBHOOK_URL", FISCAL_WEBHOOK_URL), WF04_WEBHOOK_PATH
    )
    env["AVALIACAO_HUMANA_WEBHOOK_URL"] = _validated_oracle_endpoint(
        env.get("AVALIACAO_HUMANA_WEBHOOK_URL", HUMAN_REVIEW_WEBHOOK_URL),
        WF05_WEBHOOK_PATH,
    )
    rows = query(
        """
        SELECT
          e.status,
          LOWER(COALESCE(e.generation_config->>'test_mode','false'))='true' AS test_mode,
          LOWER(COALESCE(e.generation_config->>'auto_human_confirmation','false'))='true'
            AS auto_human_confirmation,
          COUNT(dc.id)::int AS total_realizacoes,
          COUNT(dc.id) FILTER (WHERE
            dc.run_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$'
            OR COALESCE(dc.scenario_id,'') !~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'
            OR COALESCE(dc.case_id,'') !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$'
            OR COALESCE(dc.episode_id,'') !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$'
            OR UPPER(COALESCE(dc.split,'')) NOT IN (
              'PILOTO','VALIDACAO','TESTE','TEST','BENCHMARK','CALIBRACAO'
            )
            OR COALESCE(dc.origem,'') !~ '^(AVALIACAO_|VALIDACAO_|DATASET_|CALIBRACAO_FILA_)'
            OR COALESCE(dc.label_source,'') !~ '^(REGRA_SINTETICA|SYNTHETIC_|ADJUDICADO_|GABARITO_)'
          )::int AS realizacoes_invalidas
        FROM experimentos_avaliacao e
        LEFT JOIN dataset_controle dc ON dc.run_id=e.run_id
        WHERE e.run_id=%s
        GROUP BY e.run_id,e.status,e.generation_config
        """,
        (run_id,),
    )
    if len(rows) != 1:
        raise RuntimeError("ORACULO_BLOQUEADO: experimento não encontrado ou ambíguo")
    row = rows[0]
    if str(row["status"]) not in {"CALIBRANDO", "EXECUTANDO"}:
        raise RuntimeError(f"ORACULO_BLOQUEADO: status experimental {row['status']}")
    if row["test_mode"] is not True or row["auto_human_confirmation"] is not True:
        raise RuntimeError("ORACULO_BLOQUEADO: experimento não autorizou o assessor")
    if int(row["total_realizacoes"] or 0) <= 0 or int(row["realizacoes_invalidas"] or 0) > 0:
        raise RuntimeError("ORACULO_BLOQUEADO: origem ou identificadores do dataset inválidos")
    return env


def _reconcile_oracle_actions(cursor, run_id: str) -> None:
    cursor.execute(
        """
        UPDATE avaliacao_auto_confirmacoes ac
        SET status='CONFIRMADA',confirmada_em=COALESCE(ac.confirmada_em,NOW()),
            atualizado_em=NOW(),mensagem_erro=NULL,proxima_tentativa_em=NULL
        FROM tickets_processados tp
        WHERE ac.ticket_id=tp.id AND ac.run_id=%s
          AND ac.tipo_confirmacao='FISCAL_DUPLICIDADE'
          AND ac.status IN ('RESERVADA','ENVIADA','FALHA')
          AND (
            (ac.decisao_webhook='confirmar'
              AND tp.decisao_fiscal IN ('PROCESSANDO_CONFIRMAR_DUP','CONFIRMOU_DUP'))
            OR
            (ac.decisao_webhook='nao_duplicado'
              AND tp.decisao_fiscal IN ('PROCESSANDO_REJEITAR_DUP','REJEITOU_DUP'))
          )
        """,
        (run_id,),
    )
    cursor.execute(
        """
        UPDATE avaliacao_auto_confirmacoes ac
        SET status='CONFIRMADA',confirmada_em=COALESCE(ac.confirmada_em,NOW()),
            atualizado_em=NOW(),mensagem_erro=NULL,proxima_tentativa_em=NULL
        FROM avaliacoes_humanas ah
        WHERE ac.avaliacao_id=ah.id AND ac.run_id=%s
          AND ac.tipo_confirmacao='AVALIACAO_METRICA'
          AND ac.status IN ('RESERVADA','ENVIADA','FALHA')
          AND ah.status_avaliacao='CONCLUIDA'
          AND ah.fonte_gabarito='ORACULO_GABARITO'
        """,
        (run_id,),
    )
    cursor.execute(
        """
        UPDATE avaliacao_auto_confirmacoes
        SET status='FALHA',mensagem_erro='Webhook não confirmou dentro da janela',
            proxima_tentativa_em=CASE WHEN tentativas<3
              THEN NOW()+INTERVAL '30 seconds' ELSE NULL END,
            atualizado_em=NOW()
        WHERE run_id=%s AND status='ENVIADA'
          AND enviada_em<NOW()-INTERVAL '2 minutes'
        """,
        (run_id,),
    )


def _reserve_oracle_actions(run_id: str, batch_size: int) -> list[dict]:
    """Reserva ações por compare-and-set; só então o gabarito sai do banco."""
    conn = connect_pg()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (9062027,))
            _reconcile_oracle_actions(cursor, run_id)
            cursor.execute(
                """
                WITH contexto AS MATERIALIZED (
                  SELECT dc.*,tp.em_aprovacao_fiscal,tp.decisao_fiscal,
                         tp.fiscal_decision_token,tp.fiscal_token_expira_em,
                         tp.aprovacao_iniciada_em
                  FROM dataset_controle dc
                  JOIN tickets_processados tp ON tp.id=dc.ticket_id
                  WHERE dc.run_id=%s
                ),
                acoes_fiscais AS (
                  SELECT
                    c.ticket_id,c.run_id,c.scenario_id,c.case_id AS realization_id,
                    c.episode_id,'DEDUPLICACAO'::text AS etapa,
                    'FISCAL_DUPLICIDADE'::text AS tipo_confirmacao,
                    i.id AS ia_decisao_id,NULL::bigint AS avaliacao_id,
                    i.predicao AS predicao_ia,
                    CASE WHEN c.duplicado_esperado THEN 'DUPLICADO' ELSE 'NAO_DUPLICADO' END
                      AS classe_gabarito,
                    CASE WHEN c.duplicado_esperado THEN 'confirmar' ELSE 'nao_duplicado' END
                      AS decisao_webhook,
                    c.label_source,c.fiscal_decision_token AS token_endpoint,
                    NULL::text AS classe_correta_webhook
                  FROM contexto c
                  JOIN LATERAL (
                    SELECT d.id,d.predicao,d.criado_em
                    FROM ia_decisoes d
                    WHERE d.ticket_id=c.ticket_id AND d.run_id=c.run_id
                      AND d.case_id=c.case_id AND d.etapa='DEDUPLICACAO'
                    ORDER BY d.criado_em DESC,d.id DESC LIMIT 1
                  ) i ON TRUE
                  WHERE c.dimension='DEDUPLICACAO'
                    AND c.duplicado_esperado IS NOT NULL
                    AND c.em_aprovacao_fiscal=TRUE AND COALESCE(c.decisao_fiscal,'')=''
                    AND c.fiscal_decision_token ~ '^[a-f0-9]{32,128}$'
                    AND (c.fiscal_token_expira_em IS NULL OR c.fiscal_token_expira_em>NOW())
                    AND i.predicao='DUPLICADO'
                    AND i.criado_em<=COALESCE(c.aprovacao_iniciada_em,NOW())
                ),
                acoes_metricas AS (
                  SELECT
                    c.ticket_id,c.run_id,c.scenario_id,c.case_id AS realization_id,
                    c.episode_id,ah.etapa,'AVALIACAO_METRICA'::text AS tipo_confirmacao,
                    i.id AS ia_decisao_id,ah.id AS avaliacao_id,i.predicao AS predicao_ia,
                    CASE WHEN ah.etapa='DEDUPLICACAO'
                      THEN CASE WHEN c.duplicado_esperado THEN 'DUPLICADO' ELSE 'NAO_DUPLICADO' END
                      ELSE c.classificacao_esperada END AS classe_gabarito,
                    CASE WHEN i.predicao=(CASE WHEN ah.etapa='DEDUPLICACAO'
                      THEN CASE WHEN c.duplicado_esperado THEN 'DUPLICADO' ELSE 'NAO_DUPLICADO' END
                      ELSE c.classificacao_esperada END) THEN 'correta' ELSE 'incorreta' END
                      AS decisao_webhook,
                    c.label_source,ah.avaliacao_token AS token_endpoint,
                    CASE WHEN i.predicao=(CASE WHEN ah.etapa='DEDUPLICACAO'
                      THEN CASE WHEN c.duplicado_esperado THEN 'DUPLICADO' ELSE 'NAO_DUPLICADO' END
                      ELSE c.classificacao_esperada END) THEN NULL
                      ELSE (CASE WHEN ah.etapa='DEDUPLICACAO'
                        THEN CASE WHEN c.duplicado_esperado THEN 'DUPLICADO' ELSE 'NAO_DUPLICADO' END
                        ELSE c.classificacao_esperada END) END AS classe_correta_webhook
                  FROM contexto c
                  JOIN avaliacoes_humanas ah ON ah.ticket_id=c.ticket_id
                    AND ah.status_avaliacao='PENDENTE'
                    AND ah.origem_amostra LIKE 'WF05_AMOSTRA_%%'
                    AND ah.avaliacao_token ~ '^[a-f0-9]{32,128}$'
                    AND (ah.avaliacao_token_expira_em IS NULL OR ah.avaliacao_token_expira_em>NOW())
                  JOIN LATERAL (
                    SELECT d.id,d.predicao,d.criado_em
                    FROM ia_decisoes d
                    WHERE d.ticket_id=c.ticket_id AND d.run_id=c.run_id
                      AND d.case_id=c.case_id AND d.etapa=ah.etapa
                      AND d.criado_em<=COALESCE(ah.solicitado_em,NOW())
                    ORDER BY d.criado_em DESC,d.id DESC LIMIT 1
                  ) i ON TRUE
                  WHERE ah.etapa IN ('DEDUPLICACAO','CLASSIFICACAO')
                    AND ah.decisao_ia=i.predicao
                    AND (CASE WHEN ah.etapa='DEDUPLICACAO'
                      THEN CASE WHEN c.duplicado_esperado IS NULL THEN NULL
                        WHEN c.duplicado_esperado THEN 'DUPLICADO' ELSE 'NAO_DUPLICADO' END
                      ELSE NULLIF(c.classificacao_esperada,'') END) IS NOT NULL
                ),
                acoes AS MATERIALIZED (
                  SELECT * FROM acoes_fiscais
                  UNION ALL
                  SELECT * FROM acoes_metricas
                ),
                novas AS MATERIALIZED (
                  SELECT a.*,
                    md5(random()::text||clock_timestamp()::text||a.ticket_id::text||a.tipo_confirmacao)
                      AS nonce
                  FROM acoes a
                  LEFT JOIN avaliacao_auto_confirmacoes ac
                    ON ac.run_id=a.run_id AND ac.realization_id=a.realization_id
                   AND ac.tipo_confirmacao=a.tipo_confirmacao AND ac.etapa=a.etapa
                  WHERE ac.id IS NULL OR (
                    ac.status='FALHA' AND ac.tentativas<3
                    AND COALESCE(ac.proxima_tentativa_em,NOW())<=NOW()
                  )
                  ORDER BY a.episode_id,a.ticket_id,a.tipo_confirmacao,a.etapa
                  LIMIT %s
                ),
                reservadas AS (
                  INSERT INTO avaliacao_auto_confirmacoes(
                    ticket_id,run_id,scenario_id,realization_id,episode_id,etapa,
                    tipo_confirmacao,ia_decisao_id,avaliacao_id,predicao_ia,
                    classe_gabarito,decisao_webhook,label_source,token_hash,
                    assessor_nonce_hash,status,tentativas,reservada_em,atualizado_em
                  )
                  SELECT ticket_id,run_id,scenario_id,realization_id,episode_id,etapa,
                    tipo_confirmacao,ia_decisao_id,avaliacao_id,predicao_ia,
                    classe_gabarito,decisao_webhook,label_source,
                    encode(sha256(convert_to(token_endpoint,'UTF8')),'hex'),
                    encode(sha256(convert_to(nonce,'UTF8')),'hex'),'RESERVADA',1,NOW(),NOW()
                  FROM novas
                  ON CONFLICT(run_id,realization_id,tipo_confirmacao,etapa) DO UPDATE SET
                    ia_decisao_id=EXCLUDED.ia_decisao_id,
                    avaliacao_id=EXCLUDED.avaliacao_id,
                    predicao_ia=EXCLUDED.predicao_ia,
                    classe_gabarito=EXCLUDED.classe_gabarito,
                    decisao_webhook=EXCLUDED.decisao_webhook,
                    label_source=EXCLUDED.label_source,
                    token_hash=EXCLUDED.token_hash,
                    assessor_nonce_hash=EXCLUDED.assessor_nonce_hash,
                    status='RESERVADA',
                    tentativas=avaliacao_auto_confirmacoes.tentativas+1,
                    resposta_resumo=NULL,mensagem_erro=NULL,proxima_tentativa_em=NULL,
                    reservada_em=NOW(),atualizado_em=NOW()
                  WHERE avaliacao_auto_confirmacoes.status='FALHA'
                    AND avaliacao_auto_confirmacoes.tentativas<3
                    AND COALESCE(avaliacao_auto_confirmacoes.proxima_tentativa_em,NOW())<=NOW()
                  RETURNING *
                )
                SELECT r.id AS auto_confirmacao_id,r.ticket_id,r.run_id,r.scenario_id,
                       r.realization_id,r.episode_id,r.etapa,r.tipo_confirmacao,
                       r.predicao_ia,r.classe_gabarito,r.decisao_webhook,
                       n.token_endpoint,n.classe_correta_webhook,n.nonce AS assessor_nonce,
                       r.tentativas
                FROM reservadas r
                JOIN novas n ON n.run_id=r.run_id AND n.realization_id=r.realization_id
                  AND n.tipo_confirmacao=r.tipo_confirmacao AND n.etapa=r.etapa
                ORDER BY r.id
                """,
                (run_id, max(1, min(100, int(batch_size)))),
            )
            rows = [dict(row) for row in cursor.fetchall()]
        conn.commit()
        return rows
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _finish_oracle_action(
    action: dict, success: bool, status_code: int | None, error_message: str | None
) -> None:
    execute(
        """
        UPDATE avaliacao_auto_confirmacoes
        SET status=%s,
            enviada_em=CASE WHEN %s THEN NOW() ELSE enviada_em END,
            resposta_resumo=%s,
            mensagem_erro=%s,
            proxima_tentativa_em=CASE WHEN %s THEN NULL ELSE NOW()+INTERVAL '30 seconds' END,
            atualizado_em=NOW()
        WHERE id=%s
          AND assessor_nonce_hash=encode(sha256(convert_to(%s,'UTF8')),'hex')
          AND status='RESERVADA'
        """,
        (
            "ENVIADA" if success else "FALHA",
            success,
            f"HTTP {status_code}" if status_code is not None else None,
            None if success else str(error_message or "Falha no webhook")[:1000],
            success,
            action["auto_confirmacao_id"],
            action["assessor_nonce"],
        ),
    )


def _call_oracle_action(action: dict, env: dict[str, str]) -> bool:
    common = {
        "fonte": "ORACULO_GABARITO",
        "run_id": action["run_id"],
        "scenario_id": action["scenario_id"],
        "realization_id": action["realization_id"],
    }
    if action["tipo_confirmacao"] == "FISCAL_DUPLICIDADE":
        url = env.get("FISCAL_WEBHOOK_URL", FISCAL_WEBHOOK_URL)
        params = {
            **common,
            "decisao": action["decisao_webhook"],
            "chamado_id": action["ticket_id"],
            "token": action["token_endpoint"],
        }
    else:
        url = env.get("AVALIACAO_HUMANA_WEBHOOK_URL", HUMAN_REVIEW_WEBHOOK_URL)
        params = {
            **common,
            "token": action["token_endpoint"],
            "resultado": action["decisao_webhook"],
            "avaliador": "oraculo_gabarito",
        }
        if action.get("classe_correta_webhook"):
            params["classe_correta"] = action["classe_correta_webhook"]
    request = urllib.request.Request(
        url + "?" + urllib.parse.urlencode(params),
        data=b"",
        headers={
            "X-Test-Mode": "true",
            "X-Test-Auto-Review-Token": env["TEST_AUTO_REVIEW_TOKEN"],
            "X-Test-Auto-Review-Nonce": action["assessor_nonce"],
            "X-Test-Run-Id": action["run_id"],
            "X-Test-Scenario-Id": action["scenario_id"],
            "X-Test-Realization-Id": action["realization_id"],
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            success = 200 <= int(response.status) < 400
            _finish_oracle_action(action, success, int(response.status), None)
            return success
    except urllib.error.HTTPError as exc:
        _finish_oracle_action(action, False, int(exc.code), f"HTTP {exc.code}")
    except (urllib.error.URLError, TimeoutError) as exc:
        _finish_oracle_action(action, False, None, type(exc).__name__)
    return False


def resolve_fiscal(run_id: str) -> int:
    """Compatibilidade CLI: resolve WF04 e WF05 sem fingir revisão humana."""
    env = _oracle_guard(run_id)
    batch = int(env.get("TEST_AUTO_REVIEW_BATCH_SIZE", "25") or 25)
    actions = _reserve_oracle_actions(run_id, batch)
    resolved = sum(_call_oracle_action(action, env) for action in actions)
    conn = connect_pg()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (9062027,))
            _reconcile_oracle_actions(cursor, run_id)
        conn.commit()
    finally:
        conn.close()
    if actions:
        print(
            f"[OK] Assessor ORACULO_GABARITO: {resolved}/{len(actions)} "
            "webhooks WF04/WF05 acionados."
        )
    return resolved


def import_validated_labels(run_id: str, validation_path: Path) -> None:
    payload = json.loads(validation_path.read_text(encoding="utf-8"))
    if payload.get("human_label_gate") != "CONCLUIDO_DUPLA_REVISAO_E_ADJUDICACAO":
        raise ValueError("Dupla revisão e adjudicação humana não estão concluídas.")
    if payload.get("rendered_text_audit_gate") != "APROVADO":
        raise ValueError("A auditoria textual cega não foi aprovada.")
    if payload.get("auditoria_humana_concluida") is not True:
        raise ValueError("auditoria_humana_concluida deve ser true.")
    if payload.get("approved_for_benchmark") is not True or payload.get("approved") is not True:
        raise ValueError("O artefato não está aprovado para benchmark.")
    if str(payload.get("approval_integrity_sha256") or "").lower() != label_approval_hash(payload):
        raise ValueError("approval_integrity_sha256 inválido.")
    exp = experiment(run_id)
    if str(payload.get("dataset_sha256") or "").lower() != str(
        exp.get("dataset_sha256") or ""
    ).lower():
        raise ValueError("O hash dos rótulos não coincide com o dataset do run.")
    reviewed = payload.get("rotulos_adjudicados")
    if not isinstance(reviewed, list) or not reviewed:
        raise ValueError("Arquivo não contém rotulos_adjudicados.")

    expected_rows = query(
        """
        SELECT case_id,ticket_id,episode_id,'DEDUPLICACAO'::text AS etapa
        FROM dataset_controle
        WHERE run_id=%s AND duplicado_esperado IS NOT NULL
        UNION ALL
        SELECT case_id,ticket_id,episode_id,'CLASSIFICACAO'::text
        FROM dataset_controle
        WHERE run_id=%s AND NULLIF(classificacao_esperada,'') IS NOT NULL
        """,
        (run_id, run_id),
    )
    expected = {(row["case_id"], row["etapa"]): row for row in expected_rows}
    actual: dict[tuple[str, str], dict] = {}
    for row in reviewed:
        key = (str(row.get("case_id") or ""), str(row.get("etapa") or ""))
        if key in actual:
            raise ValueError(f"Rótulo duplicado: {key}")
        allowed = DEDUP_CLASSES if key[1] == "DEDUPLICACAO" else CLASS_CLASSES
        label = str(row.get("rotulo_final") or "").upper()
        if label not in allowed:
            raise ValueError(f"Rótulo final inválido em {key}: {label}")
        row = {**row, "rotulo_final": label}
        actual[key] = row
    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise ValueError(f"Rótulos incompletos; ausentes={missing}, extras={extra}")

    validation_hash = hashlib.sha256(validation_path.read_bytes()).hexdigest()
    with connect_pg() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM avaliacoes_humanas WHERE run_id=%s AND fonte_gabarito='ADJUDICADO'",
                (run_id,),
            )
            for key, row in actual.items():
                meta = expected[key]
                cur.execute(
                    """
                    INSERT INTO avaliacoes_humanas(
                      ticket_id,etapa,avaliador,decisao_ia,decisao_humana,
                      classe_correta,ia_estava_correta,status_avaliacao,
                      origem_amostra,run_id,case_id,episode_id,fonte_gabarito,
                      revisao_id,adjudicada,concluido_em,avaliado_em,observacao
                    )
                    SELECT
                      %s,%s,%s,
                      COALESCE((SELECT predicao FROM ia_decisoes
                        WHERE ticket_id=%s AND etapa=%s
                        ORDER BY criado_em DESC,id DESC LIMIT 1),'SEM_DECISAO'),
                      %s,%s,
                      COALESCE((SELECT predicao FROM ia_decisoes
                        WHERE ticket_id=%s AND etapa=%s
                        ORDER BY criado_em DESC,id DESC LIMIT 1),'SEM_DECISAO')=%s,
                      'CONCLUIDA','ROTULAGEM_CEGA_DUPLA',%s,%s,%s,
                      'ADJUDICADO',%s,TRUE,NOW(),NOW(),%s
                    """,
                    (
                        meta["ticket_id"],
                        key[1],
                        "+".join(
                            filter(
                                None,
                                [
                                    str(row.get("revisor_1") or ""),
                                    str(row.get("revisor_2") or ""),
                                    str(row.get("adjudicador") or ""),
                                ],
                            )
                        ),
                        meta["ticket_id"],
                        key[1],
                        row["rotulo_final"],
                        row["rotulo_final"],
                        meta["ticket_id"],
                        key[1],
                        row["rotulo_final"],
                        run_id,
                        key[0],
                        meta["episode_id"],
                        row.get("review_id"),
                        json.dumps(
                            {
                                "rotulo_revisor_1": row.get("rotulo_revisor_1"),
                                "rotulo_revisor_2": row.get("rotulo_revisor_2"),
                                "adjudicador": row.get("adjudicador"),
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
            cur.execute(
                """
                UPDATE experimentos_avaliacao
                SET rotulos_validados=TRUE,
                    protocolo_rotulagem_validado=TRUE,
                    congelado_em=COALESCE(congelado_em,NOW()),
                    generation_config=COALESCE(generation_config,'{}'::jsonb)
                      || jsonb_build_object(
                        'rotulagem_validacao_sha256',%s,
                        'confiabilidade_interavaliadores',%s::jsonb
                      )
                WHERE run_id=%s
                """,
                (
                    validation_hash,
                    json.dumps(payload.get("confiabilidade") or {}, ensure_ascii=False),
                    run_id,
                ),
            )
        conn.commit()
    print(f"[OK] Rótulos adjudicados importados: {len(actual)} decisões")


def wait_processing(
    run_id: str,
    timeout: int,
    poll: int,
    use_oracle: bool,
) -> dict:
    started = time.monotonic()
    while True:
        if use_oracle:
            resolve_fiscal(run_id)
        summary = pending_summary(run_id)
        elapsed = time.monotonic() - started
        print(
            f"[MONITOR] run={run_id} pendentes={summary['pendentes']} "
            f"fiscal={summary['fiscal']} erros={summary['erros']} "
            f"tempo={elapsed:.0f}s"
        )
        if summary["total"] > 0 and summary["pendentes"] == 0:
            return summary
        if elapsed >= timeout:
            raise TimeoutError(
                f"Processamento excedeu {timeout}s com "
                f"{summary['pendentes']} pendentes."
            )
        time.sleep(max(1, poll))


def materialize_synthetic_gold(run_id: str) -> None:
    exp = experiment(run_id)
    split = str(exp.get("split") or "").upper()
    if split in {"TEST", "TESTE", "BENCHMARK"}:
        raise RuntimeError(
            "Gabarito sintético não pode ser materializado em benchmark confirmatório; "
            "use rótulos humanos importados pelo executor V3."
        )
    source = "SINTETICO_GERADOR"
    execute(
        """
        UPDATE experimentos_avaliacao
        SET generation_config=COALESCE(generation_config,'{}'::jsonb) ||
              '{"label_source":"SYNTHETIC_GENERATOR",'
              '"scientific_result":false,'
              '"confirmatory_eligible":false}'::jsonb
        WHERE run_id=%s
        """,
        (run_id,),
    )
    execute(
        """
        WITH gold AS (
          SELECT
            dc.run_id,dc.case_id,dc.episode_id,dc.ticket_id,
            'DEDUPLICACAO'::text AS etapa,
            CASE WHEN dc.duplicado_esperado THEN 'DUPLICADO'
                 ELSE 'NAO_DUPLICADO' END AS classe_correta
          FROM dataset_controle dc
          WHERE dc.run_id=%s AND dc.duplicado_esperado IS NOT NULL
          UNION ALL
          SELECT
            dc.run_id,dc.case_id,dc.episode_id,dc.ticket_id,
            'CLASSIFICACAO'::text,
            dc.classificacao_esperada
          FROM dataset_controle dc
          WHERE dc.run_id=%s
            AND NULLIF(dc.classificacao_esperada,'') IS NOT NULL
        ),
        predicted AS (
          SELECT
            g.*,
            COALESCE((
              SELECT i.predicao
              FROM ia_decisoes i
              WHERE i.ticket_id=g.ticket_id AND i.etapa=g.etapa
                AND i.run_id=g.run_id AND i.case_id=g.case_id
              ORDER BY i.criado_em DESC,i.id DESC
              LIMIT 1
            ),'SEM_DECISAO') AS decisao_ia
          FROM gold g
        )
        INSERT INTO avaliacoes_humanas(
          ticket_id,etapa,decisao_ia,decisao_humana,classe_correta,
          ia_estava_correta,avaliador,status_avaliacao,origem_amostra,
          avaliado_em,concluido_em,run_id,case_id,episode_id,
          fonte_gabarito,adjudicada
        )
        SELECT
          ticket_id,etapa,decisao_ia,classe_correta,classe_correta,
          decisao_ia=classe_correta,'ORACULO_DATASET','CONCLUIDA',
          'DATASET_EPISODICO',NOW(),NOW(),run_id,case_id,episode_id,%s,FALSE
        FROM predicted
        WHERE NOT EXISTS (
          SELECT 1 FROM avaliacoes_humanas a
          WHERE a.run_id=predicted.run_id
            AND a.case_id=predicted.case_id
            AND a.etapa=predicted.etapa
            AND a.fonte_gabarito IN (
              'SINTETICO_GERADOR','SINTETICO_VALIDADO','SINTETICO_NAO_VALIDADO'
            )
        )
        """,
        (run_id, run_id, source),
    )
    print(f"[OK] Gabarito materializado com fonte={source}")


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def metric_tables(run_id: str) -> dict[str, list[dict]]:
    tables = {
        "matriz_confusao_classificacao": query(
            "SELECT * FROM vw_matriz_confusao_classificacao "
            "WHERE run_id=%s ORDER BY classe_correta,classe_predita_pela_ia",
            (run_id,),
        ),
        "metricas_classificacao": query(
            "SELECT * FROM vw_metricas_assertividade_classificacao "
            "WHERE run_id=%s ORDER BY classe",
            (run_id,),
        ),
        "kpi_classificacao": query(
            "SELECT * FROM vw_kpi_classificacao WHERE run_id=%s",
            (run_id,),
        ),
        "auc_classificacao": query(
            "SELECT * FROM vw_auc_classificacao WHERE run_id=%s ORDER BY classe",
            (run_id,),
        ),
        "average_precision_classificacao": query(
            "SELECT * FROM vw_average_precision_classificacao "
            "WHERE run_id=%s ORDER BY classe",
            (run_id,),
        ),
        "log_loss_classificacao": query(
            "SELECT * FROM vw_log_loss_classificacao WHERE run_id=%s",
            (run_id,),
        ),
        "brier_classificacao": query(
            "SELECT * FROM vw_brier_classificacao WHERE run_id=%s",
            (run_id,),
        ),
        "metricas_deduplicacao": query(
            "SELECT * FROM vw_metricas_deduplicacao WHERE run_id=%s",
            (run_id,),
        ),
        "metricas_deduplicacao_desafio_primaria": query(
            "SELECT * FROM vw_metricas_deduplicacao_desafio WHERE run_id=%s",
            (run_id,),
        ),
        "recall_candidatos_deduplicacao": query(
            "SELECT * FROM vw_recall_candidatos_deduplicacao WHERE run_id=%s",
            (run_id,),
        ),
        "auc_deduplicacao": query(
            "SELECT * FROM vw_auc_deduplicacao WHERE run_id=%s",
            (run_id,),
        ),
        "average_precision_deduplicacao": query(
            "SELECT * FROM vw_average_precision_deduplicacao WHERE run_id=%s",
            (run_id,),
        ),
        "log_loss_deduplicacao": query(
            "SELECT * FROM vw_log_loss_deduplicacao WHERE run_id=%s",
            (run_id,),
        ),
        "risco_cobertura": query(
            "SELECT * FROM vw_risco_cobertura_classificacao "
            "WHERE run_id=%s ORDER BY threshold",
            (run_id,),
        ),
        "metricas_operacionais": query(
            """
            WITH tickets AS (
              SELECT
                tp.*,
                EXTRACT(EPOCH FROM (
                  tp.atualizado_em-COALESCE(tp.fila_enfileirada_em,tp.criado_em)
                )) AS latencia_s
              FROM dataset_controle dc
              JOIN tickets_processados tp ON tp.id=dc.ticket_id
              WHERE dc.run_id=%s
            ),
            chamadas AS (
              SELECT
                COUNT(*)::int AS chamadas_ia,
                COUNT(*) FILTER (WHERE erro_ia)::int AS erros_ia,
                COUNT(*) FILTER (
                  WHERE erro_ia=FALSE AND probabilidades_validas=FALSE
                )::int AS probabilidades_invalidas,
                SUM(CASE
                  WHEN api_response_raw#>>'{usageMetadata,promptTokenCount}' ~ '^[0-9]+$'
                  THEN (api_response_raw#>>'{usageMetadata,promptTokenCount}')::bigint ELSE 0
                END)::bigint AS tokens_entrada,
                SUM(CASE
                  WHEN api_response_raw#>>'{usageMetadata,candidatesTokenCount}' ~ '^[0-9]+$'
                  THEN (api_response_raw#>>'{usageMetadata,candidatesTokenCount}')::bigint ELSE 0
                END)::bigint AS tokens_saida,
                SUM(CASE
                  WHEN api_response_raw#>>'{usageMetadata,totalTokenCount}' ~ '^[0-9]+$'
                  THEN (api_response_raw#>>'{usageMetadata,totalTokenCount}')::bigint ELSE 0
                END)::bigint AS tokens_total
              FROM ia_decisoes
              WHERE run_id=%s
            )
            SELECT
              COUNT(*)::int AS tickets,
              c.chamadas_ia,
              c.erros_ia,
              c.probabilidades_invalidas,
              c.tokens_entrada,
              c.tokens_saida,
              c.tokens_total,
              COUNT(*) FILTER (
                WHERE t.triagem_status='TRIAGEM_MANUAL'
              )::int AS triagens_manuais,
              COUNT(*) FILTER (
                WHERE NULLIF(t.decisao_fiscal,'') IS NOT NULL
              )::int AS intervencoes_fiscais,
              ROUND(AVG(t.latencia_s)::numeric,3) AS latencia_total_media_s,
              ROUND(percentile_cont(0.95) WITHIN GROUP (
                ORDER BY t.latencia_s
              )::numeric,3) AS latencia_total_p95_s
            FROM tickets t CROSS JOIN chamadas c
            GROUP BY c.chamadas_ia,c.erros_ia,c.probabilidades_invalidas,
                     c.tokens_entrada,c.tokens_saida,c.tokens_total
            """,
            (run_id, run_id),
        ),
    }
    return tables


def wilson_95(successes: int, total: int) -> dict | None:
    if total <= 0:
        return None
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + (z * z / total)
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / total
            + z * z / (4 * total * total)
        )
        / denominator
    )
    return {
        "estimate": proportion,
        "lower": max(0.0, center - margin),
        "upper": min(1.0, center + margin),
        "method": "Wilson 95%",
    }


def confidence_intervals(tables: dict[str, list[dict]]) -> dict:
    intervals: dict[str, dict] = {}
    kpi = tables.get("kpi_classificacao", [])
    matrix = tables.get("matriz_confusao_classificacao", [])
    if kpi and matrix:
        total = int(kpi[0]["total"])
        covered = int(kpi[0].get("cobertos", total))
        correct = sum(
            int(row["quantidade"])
            for row in matrix
            if row["classe_correta"] == row["classe_predita_pela_ia"]
            and row["classe_predita_pela_ia"] != "ABSTENCAO"
        )
        intervals["cobertura_automatica_classificacao"] = wilson_95(
            covered, total
        )
        intervals["acuracia_classificacao_sob_cobertura"] = wilson_95(
            correct, covered
        )
    for metric_name, output_prefix in (
        ("metricas_deduplicacao_desafio_primaria", "deduplicacao_desafio_primaria"),
        ("metricas_deduplicacao", "deduplicacao_global_secundaria"),
    ):
        dedup = tables.get(metric_name, [])
        if not dedup:
            continue
        row = dedup[0]
        total = int(row["total"])
        covered = int(row.get("cobertos", total))
        intervals[f"{output_prefix}_cobertura_automatica"] = wilson_95(
            covered, total
        )
        intervals[f"{output_prefix}_acuracia"] = wilson_95(
            int(row["tp"]) + int(row["tn"]), covered
        )
        intervals[f"{output_prefix}_recall_duplicado"] = wilson_95(
            int(row["tp"]), int(row["tp"]) + int(row["fn"])
        )
        intervals[f"{output_prefix}_precisao_duplicado"] = wilson_95(
            int(row["tp"]), int(row["tp"]) + int(row["fp"])
        )
    return intervals


def bootstrap_confidence_intervals(
    run_id: str, replications: int, seed: int
) -> dict:
    classification = query(
        """
        SELECT classe_correta,classe_predita,episode_id
        FROM vw_decisoes_classificacao
        WHERE run_id=%s AND NOT abstencao
        ORDER BY episode_id,case_id,ticket_id
        """,
        (run_id,),
    )
    deduplication = query(
        """
        SELECT classe_correta,classe_predita,episode_id
        FROM vw_decisoes_deduplicacao
        WHERE run_id=%s AND NOT abstencao
        ORDER BY episode_id,case_id,ticket_id
        """,
        (run_id,),
    )
    deduplication_challenge = query(
        """
        SELECT classe_correta,classe_predita,episode_id
        FROM vw_decisoes_deduplicacao_desafio
        WHERE run_id=%s AND NOT abstencao
        ORDER BY episode_id,case_id,ticket_id
        """,
        (run_id,),
    )
    output: dict[str, dict] = {}
    if classification:
        output["classificacao"] = bootstrap_multiclass(
            [row["classe_correta"] for row in classification],
            [row["classe_predita"] for row in classification],
            [row["episode_id"] for row in classification],
            sorted(CLASS_CLASSES),
            replications=replications,
            seed=seed,
        )
    if deduplication:
        output["deduplicacao_global_secundaria"] = bootstrap_binary(
            [row["classe_correta"] for row in deduplication],
            [row["classe_predita"] for row in deduplication],
            [row["episode_id"] for row in deduplication],
            replications=replications,
            seed=seed + 1,
        )
    if deduplication_challenge:
        output["deduplicacao_desafio_primaria"] = bootstrap_binary(
            [row["classe_correta"] for row in deduplication_challenge],
            [row["classe_predita"] for row in deduplication_challenge],
            [row["episode_id"] for row in deduplication_challenge],
            replications=replications,
            seed=seed + 2,
        )
    return output


def generate_report(
    run_id: str,
    out_dir: Path,
    bootstrap_replications: int = 2000,
    seed: int = 20260702,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    exp = experiment(run_id)
    tables = metric_tables(run_id)
    for name, rows in tables.items():
        write_csv(out_dir / f"{name}.csv", rows)
    gates = completion_gates(exp)
    gate_status = reported_gate_status(exp)
    integrity_errors = confirmatory_model_integrity(exp)
    nature, scientific_confirmatory = result_nature(exp, gates, integrity_errors)
    generation_config = exp.get("generation_config") or {}
    if isinstance(generation_config, str):
        try:
            generation_config = json.loads(generation_config)
        except json.JSONDecodeError:
            generation_config = {}
    label_source = str(generation_config.get("label_source") or "NAO_DECLARADA")
    gold_sources = gold_source_summary(run_id)
    synthetic_gold = (
        label_source == "SYNTHETIC_GENERATOR"
        or int(gold_sources.get("sinteticos") or 0) > 0
        or int(gold_sources.get("oraculo") or 0) > 0
    )
    all_gold_human = (
        int(gold_sources.get("total") or 0) > 0
        and int(gold_sources.get("humanos") or 0)
        == int(gold_sources.get("total") or 0)
        and int(gold_sources.get("nao_humanos") or 0) == 0
    )
    payload = {
        "experimento": exp,
        "classificacao_evidencia": {
            "natureza": nature,
            "scientific_result": scientific_confirmatory,
            "confirmatory_eligible": scientific_confirmatory,
            "label_source": label_source,
            "synthetic_gold": synthetic_gold,
            "gold_source_summary": gold_sources,
            "integrity_errors": integrity_errors,
            "gate_status": gate_status,
        },
        "metricas": tables,
        "intervalos_confianca_wilson": confidence_intervals(tables),
        "intervalos_confianca_bootstrap": bootstrap_confidence_intervals(
            run_id, bootstrap_replications, seed
        ),
    }
    (out_dir / "metricas.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    human_review = bool(exp.get("auditoria_humana_concluida")) and all_gold_human
    lines = [
        "# Relatório experimental",
        "",
        f"- Run: `{run_id}`",
        f"- Dataset: `{exp.get('dataset_version')}`",
        f"- SHA-256: `{exp.get('dataset_sha256')}`",
        f"- Modelo: `{exp.get('modelo_ia')}`",
        f"- Perfil: `{exp.get('generation_profile')}`",
        f"- Fonte do gabarito: `{label_source}`",
        f"- Rótulos humanos importados: `{'SIM' if all_gold_human and exp.get('rotulos_validados') else 'NÃO'}`",
        f"- Protocolo de rotulagem validado: `{'SIM' if exp.get('protocolo_rotulagem_validado') else 'NÃO'}`",
        f"- Auditoria humana do teste: `{'SIM' if human_review else 'NÃO'}`",
        f"- Natureza do resultado: `{nature}`",
        f"- Resultado científico confirmatório: `{'SIM' if scientific_confirmatory else 'NÃO'}`",
        f"- Estado dos gates: `{json.dumps(gate_status, ensure_ascii=False, sort_keys=True)}`",
        "",
        "Os CSVs deste diretório são filtrados exclusivamente por este run_id.",
        "Scores ausentes ou inválidos não são imputados e não entram em AUC, Log Loss ou Brier.",
    ]
    if synthetic_gold:
        lines.extend(
            [
                "",
                "As métricas medem concordância com o gabarito sintético determinístico.",
                "Elas validam software e comportamento nos cenários codificados, mas não estimam validade externa no GLPI real.",
            ]
        )
    (out_dir / "relatorio.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[OK] Relatório: {out_dir / 'relatorio.md'}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Confere um run experimental isolado e calcula métricas sem vazamento."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--liberar-fila", action="store_true")
    parser.add_argument("--aguardar-processamento", action="store_true")
    parser.add_argument(
        "--resolver-confirmacoes-automaticas",
        "--resolver-fiscal",
        dest="resolver_confirmacoes_automaticas",
        action="store_true",
        help=(
            "Em modo de teste autorizado, confirma deterministicamente WF04/WF05 "
            "pelo gabarito. --resolver-fiscal é um alias legado/deprecado."
        ),
    )
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--poll", type=int, default=10)
    parser.add_argument("--registrar-gabarito", action="store_true")
    parser.add_argument("--importar-rotulos", type=Path)
    parser.add_argument("--gerar-relatorio", action="store_true")
    parser.add_argument("--saida", default="avaliacao/resultados/EVAL-atual")
    parser.add_argument("--concluir", action="store_true")
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20260702)
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    if "--resolver-fiscal" in sys.argv[1:]:
        print(
            "[AVISO] --resolver-fiscal está deprecado; "
            "use --resolver-confirmacoes-automaticas."
        )
    resolver_confirmacoes = args.resolver_confirmacoes_automaticas
    experiment(args.run_id)
    if args.liberar_fila:
        set_experiment_status(args.run_id, "EXECUTANDO")
        print(f"[OK] Fila liberada para {args.run_id}")
    if args.aguardar_processamento:
        wait_processing(
            args.run_id,
            args.timeout,
            args.poll,
            use_oracle=resolver_confirmacoes,
        )
    elif resolver_confirmacoes:
        resolve_fiscal(args.run_id)
    if args.registrar_gabarito:
        materialize_synthetic_gold(args.run_id)
    if args.importar_rotulos:
        import_validated_labels(args.run_id, args.importar_rotulos)
    if args.gerar_relatorio:
        materialize_synthetic_gold(args.run_id)
        generate_report(
            args.run_id,
            ROOT / args.saida,
            bootstrap_replications=args.bootstrap,
            seed=args.seed,
        )
    if args.concluir:
        summary = pending_summary(args.run_id)
        if summary["pendentes"]:
            raise RuntimeError("Benchmark ainda possui chamados pendentes.")
        require_completion_gates(experiment(args.run_id))
        set_experiment_status(args.run_id, "CONCLUIDO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
