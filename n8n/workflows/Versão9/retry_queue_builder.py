"""Gera a consulta n8n de retry/cooldown compartilhada pelos workers de IA.

A consulta usa o mesmo advisory lock do WF06 e bloqueia a linha de controle
antes de atualizar o chamado. Assim, retries e novas reservas não invertem a
ordem dos locks nem produzem uma tempestade concorrente contra os provedores.
"""

from __future__ import annotations


def build_retry_queue_query(
    *,
    workflow: str,
    stage: str,
    attempts_column: str,
    requeue_action: str,
    terminal_action: str,
) -> str:
    if workflow not in {"WF02", "WF03"}:
        raise ValueError(f"Workflow de retry inválido: {workflow}")
    if stage not in {"DEDUPLICACAO", "CLASSIFICACAO"}:
        raise ValueError(f"Etapa de retry inválida: {stage}")
    if attempts_column not in {
        "tentativas_ia_dedup",
        "tentativas_ia_classificacao",
    }:
        raise ValueError(f"Coluna de tentativas inválida: {attempts_column}")

    template = r"""{{ (() => {
const d=$json || {};
const chamado=d.chamado || {};
const id=Number(chamado.id || d.id || 0);
if (!Number.isInteger(id) || id <= 0) {
  throw new Error('__WF__: ticket ausente no tratamento de erro IA');
}
const envNumber=(name,fallback) => {
  let raw=fallback;
  try {
    if (typeof $env !== 'undefined' && $env && $env[name] !== undefined) raw=$env[name];
    else if (typeof process !== 'undefined' && process.env && process.env[name] !== undefined) raw=process.env[name];
  } catch(e) {}
  const value=Number(raw);
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : fallback;
};
const esc=value=>"'"+String(value??'').replace(/'/g,"''")+"'";
const base=Math.max(1,envNumber('IA_RETRY_BASE_SEGUNDOS',30));
const max=Math.max(base,envNumber('IA_RETRY_MAX_SEGUNDOS',900));
const hardMax=Math.max(max,envNumber('IA_RETRY_HARD_MAX_SEGUNDOS',3600));
const httpRaw=Number(d.ia_http_status);
const httpStatus=Number.isInteger(httpRaw) && httpRaw >= 100 && httpRaw <= 599 ? httpRaw : null;
const retryAfterRaw=Number(d.ia_retry_after_seconds);
const retryAfter=Number.isFinite(retryAfterRaw) && retryAfterRaw > 0
  ? Math.min(hardMax,Math.ceil(retryAfterRaw)) : 0;
let errorType=String(d.ia_error_type || '').toUpperCase().trim();
if (!errorType && httpStatus === 429) errorType='RATE_LIMIT';
if (!errorType && [500,502,503,504].includes(httpStatus)) errorType='SERVICE_UNAVAILABLE';
const retryableValue=d.ia_retryable;
const explicitRetryable=typeof retryableValue === 'boolean'
  ? retryableValue
  : (String(retryableValue).toLowerCase() === 'true'
    ? true
    : (String(retryableValue).toLowerCase() === 'false' ? false : null));
const permanentHttp=httpStatus !== null && httpStatus >= 400 && httpStatus < 500
  && ![408,425,429].includes(httpStatus);
const permanentType=['PERMANENT_HTTP','CONFIGURATION','POLICY','NON_RETRYABLE'].includes(errorType);
const rateLimited=httpStatus === 429 || errorType === 'RATE_LIMIT';
const serviceUnavailable=[500,502,503,504].includes(httpStatus)
  || errorType === 'SERVICE_UNAVAILABLE';
const timeout=errorType === 'TIMEOUT';
const retryable=explicitRetryable === true
  || (explicitRetryable === null && !permanentHttp && !permanentType);
const applyCooldown=retryable && (rateLimited || serviceUnavailable || timeout);
const erro=String(d.mensagem_erro || 'Erro IA').slice(0,2000);
const httpSql=httpStatus === null ? 'NULL' : String(httpStatus);
const errorTypeSql=esc(errorType || (permanentHttp ? 'PERMANENT_HTTP' : 'TRANSPORT'));
const retryableSql=retryable ? 'TRUE' : 'FALSE';
const rateLimitSql=rateLimited ? 'TRUE' : 'FALSE';
const unavailableSql=serviceUnavailable ? 'TRUE' : 'FALSE';
const timeoutSql=timeout ? 'TRUE' : 'FALSE';
const cooldownSql=applyCooldown ? 'TRUE' : 'FALSE';
return `
WITH
bloqueio AS MATERIALIZED (
  SELECT pg_advisory_xact_lock(9062026) AS adquirido
),
controle AS MATERIALIZED (
  SELECT f.id
  FROM fila_ia_controle f
  CROSS JOIN bloqueio
  WHERE f.id=1
  FOR UPDATE
),
parametros_base AS MATERIALIZED (
  SELECT
    t.id,
    COALESCE(t.__ATTEMPTS_COLUMN__,0) AS tentativas_anteriores,
    COALESCE(t.__ATTEMPTS_COLUMN__,0)+1 AS tentativa_numero,
    ${httpSql}::integer AS ia_http_status,
    ${retryAfter}::integer AS ia_retry_after_seconds,
    ${retryableSql}::boolean AS ia_retryable,
    ${errorTypeSql}::text AS ia_error_type,
    ${rateLimitSql}::boolean AS rate_limited,
    ${unavailableSql}::boolean AS service_unavailable,
    ${timeoutSql}::boolean AS timeout,
    ${cooldownSql}::boolean AS aplicar_cooldown
  FROM tickets_processados t
  CROSS JOIN controle
  WHERE t.id=${id}
),
parametros AS MATERIALIZED (
  SELECT
    p.*,
    (p.ia_retryable AND p.tentativa_numero < 3) AS reenfileirar,
    CASE
      WHEN NOT p.ia_retryable OR p.tentativa_numero >= 3 THEN 0
      WHEN p.rate_limited THEN LEAST(
        ${hardMax},
        GREATEST(${retryAfter},${max})
          + floor(random() * (GREATEST(1,${base}) + 1))::integer
      )
      WHEN p.service_unavailable OR p.timeout THEN LEAST(
        ${hardMax},
        GREATEST(
          ${retryAfter},
          60,
          (${base} * power(2,p.tentativas_anteriores))::integer
        ) + floor(
          random() * (
            GREATEST(60,(${base} * power(2,p.tentativas_anteriores))::integer) + 1
          )
        )::integer
      )
      ELSE LEAST(
        ${max},
        GREATEST(${retryAfter},(${base} * power(2,p.tentativas_anteriores))::integer)
          + floor(
            random() * (
              GREATEST(1,(${base} * power(2,p.tentativas_anteriores))::integer) + 1
            )
          )::integer
      )
    END::integer AS delay_seconds
  FROM parametros_base p
),
atualizada AS (
  UPDATE tickets_processados t
  SET triagem_status=CASE WHEN p.reenfileirar THEN 'PENDENTE_FILA_IA' ELSE 'ERRO_IA' END,
      fila_etapa='__STAGE__',
      fila_enfileirada_em=CASE WHEN p.reenfileirar THEN NOW() ELSE t.fila_enfileirada_em END,
      fila_disponivel_em=CASE
        WHEN p.reenfileirar THEN NOW() + (p.delay_seconds || ' seconds')::interval
        ELSE t.fila_disponivel_em
      END,
      fila_liberar_em=NULL,
      fila_reservada_em=NULL,
      ultima_acao_workflow=CASE
        WHEN p.reenfileirar THEN '__REQUEUE_ACTION__'
        WHEN NOT p.ia_retryable THEN '__TERMINAL_ACTION___PERMANENTE'
        ELSE '__TERMINAL_ACTION__'
      END,
      ultimo_erro_ia=${esc(erro)},
      __ATTEMPTS_COLUMN__=p.tentativa_numero,
      tentativas_ia=COALESCE(t.tentativas_ia,0)+1,
      log_workflow=COALESCE(t.log_workflow,'[]'::jsonb) || jsonb_build_object(
        'wf','__WF__','acao','ERRO_IA___STAGE__','ts',NOW(),
        'erro',${esc(erro)},'http_status',p.ia_http_status,
        'retry_after_seconds',p.ia_retry_after_seconds,
        'retryable',p.ia_retryable,'error_type',p.ia_error_type,
        'delay_seconds',p.delay_seconds,'cooldown_global',p.aplicar_cooldown
      ),
      atualizado_em=NOW()
  FROM parametros p
  WHERE t.id=p.id
  RETURNING
    t.id,t.triagem_status,t.ultima_acao_workflow,t.__ATTEMPTS_COLUMN__,t.ultimo_erro_ia,
    p.ia_http_status,p.ia_retry_after_seconds,p.ia_retryable,p.ia_error_type,
    p.delay_seconds,p.aplicar_cooldown
),
cooldown AS (
  UPDATE fila_ia_controle f
  SET proxima_liberacao_em=GREATEST(
        COALESCE(f.proxima_liberacao_em,NOW()),
        NOW() + (a.delay_seconds || ' seconds')::interval
      ),
      atualizado_em=NOW()
  FROM atualizada a
  WHERE f.id=1
    AND a.triagem_status='PENDENTE_FILA_IA'
    AND a.aplicar_cooldown
  RETURNING f.id,f.proxima_liberacao_em
),
contexto AS (
  SELECT dc.run_id,dc.case_id,dc.episode_id
  FROM dataset_controle dc
  WHERE dc.ticket_id=${id}
  ORDER BY dc.id DESC
  LIMIT 1
),
dlq AS (
  INSERT INTO fila_ia_dead_letter(
    ticket_id,etapa,tentativa_numero,erro,run_id,case_id,episode_id,payload_contexto
  )
  SELECT
    a.id,'__STAGE__',a.__ATTEMPTS_COLUMN__,a.ultimo_erro_ia,
    c.run_id,c.case_id,c.episode_id,
    jsonb_build_object(
      'workflow','__WF__','ultima_acao',a.ultima_acao_workflow,
      'http_status',a.ia_http_status,'retry_after_seconds',a.ia_retry_after_seconds,
      'retryable',a.ia_retryable,'error_type',a.ia_error_type
    )
  FROM atualizada a
  LEFT JOIN contexto c ON TRUE
  WHERE a.triagem_status='ERRO_IA'
  ON CONFLICT(ticket_id,etapa,tentativa_numero) DO UPDATE
  SET erro=EXCLUDED.erro,payload_contexto=EXCLUDED.payload_contexto
  RETURNING id
)
SELECT
  a.*,
  EXISTS(SELECT 1 FROM cooldown) AS cooldown_global_aplicado
FROM atualizada a;
`;
})() }}"""

    return (
        template.replace("__WF__", workflow)
        .replace("__STAGE__", stage)
        .replace("__ATTEMPTS_COLUMN__", attempts_column)
        .replace("__REQUEUE_ACTION__", requeue_action)
        .replace("__TERMINAL_ACTION__", terminal_action)
    )
