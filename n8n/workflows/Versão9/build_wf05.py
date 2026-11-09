"""Gera V9-WF05-Metricas.json.

WF05 e um workflow independente de avaliacao. Ele nao participa da triagem
operacional; verifica o schema provisionado pela migracao administrada e
consolida metricas para BI. O login runtime nao executa DDL.
"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

from helpers import sanitize_workflow_secrets


DIR = Path(__file__).resolve().parent
OUTPUT_FILES = ["V9-WF05-Metricas.json"]
SNAPSHOT_SHA256 = "7ba4d7f8cabf7ae05d8b3e3bb06de2f19eda504c6ce6b852cf05fd3a852841ae"

PG_CRED = {"postgres": {"id": "PG_TRIAGEM", "name": "Postgres Triagem"}}
SMTP_CRED = {"smtp": {"id": "SMTP_MAILPIT_LOCAL", "name": "SMTP Mailpit Local"}}

SCHEMA_READINESS_SQL = r"""
SELECT
  'schema_observabilidade_ok' AS result,
  CASE WHEN
    to_regclass('public.ia_decisoes') IS NOT NULL AND
    to_regclass('public.ia_tentativas_modelo') IS NOT NULL AND
    to_regclass('public.workflow_eventos') IS NOT NULL AND
    to_regclass('public.metricas_diarias_automacao') IS NOT NULL AND
    to_regclass('public.metricas_prompt_version') IS NOT NULL AND
    to_regclass('public.metricas_workflow_performance') IS NOT NULL AND
    to_regclass('public.vw_kpi_geral_automacao') IS NOT NULL AND
    to_regclass('public.vw_kpi_duplicidade') IS NOT NULL AND
    to_regclass('public.vw_kpi_classificacao') IS NOT NULL
  THEN 1 ELSE 1 / 0 END AS readiness_gate;
"""




CONSOLIDATE_SQL_EXPR = r"""={{ (() => {
const erroLimite = Number($env.METRICAS_ALERTA_ERRO_IA_PERCENT || 5);
const manualLimite = Number($env.METRICAS_ALERTA_TRIAGEM_MANUAL_PERCENT || 25);
const travadosLimite = Number($env.METRICAS_ALERTA_CHAMADOS_TRAVADOS || 10);
return `
WITH base AS (
  SELECT
    CURRENT_DATE AS data_ref,
    COUNT(*)::int AS total_chamados_processados,
    COUNT(*) FILTER (WHERE classificacao_final IN ('OBRA','DEMO','SOB_DEMANDA','DUPLICADO'))::int AS total_classificados_automaticamente,
    COUNT(*) FILTER (WHERE classificacao_final='TRIAGEM_MANUAL' OR triagem_manual=TRUE)::int AS total_enviados_triagem_manual,
    COUNT(*) FILTER (WHERE triagem_status='ERRO_IA' OR ultimo_erro_ia IS NOT NULL)::int AS total_com_erro_ia,
    COUNT(*) FILTER (WHERE em_aprovacao_fiscal=TRUE)::int AS total_aguardando_fiscal,
    ROUND(AVG(EXTRACT(EPOCH FROM (triado_em - data_abertura)) / 60.0) FILTER (WHERE triado_em IS NOT NULL AND data_abertura IS NOT NULL AND triado_em >= data_abertura), 2) AS tempo_medio_triagem_min,
    COUNT(*) FILTER (
      WHERE (
        em_aprovacao_fiscal = TRUE
        OR triagem_status IN ('TRIAGEM_MANUAL','ERRO_IA','REPROCESSAR_IA')
        OR ultima_acao_workflow IN ('AGUARDANDO_FISCAL','ERRO_IA_DEDUP','ERRO_IA_CLASSIF')
      )
      AND COALESCE(aprovacao_iniciada_em, triado_em, atualizado_em, criado_em) < NOW() - INTERVAL '24 hours'
    )::int AS chamados_travados_24h
  FROM tickets_processados
),
kpi AS (
  SELECT
    *,
    ROUND(100.0 * (total_enviados_triagem_manual + total_aguardando_fiscal) / NULLIF(total_chamados_processados,0), 4) AS taxa_intervencao_humana,
    ROUND(100.0 * total_classificados_automaticamente / NULLIF(total_chamados_processados,0), 4) AS taxa_automacao_efetiva,
    ROUND(100.0 * total_com_erro_ia / NULLIF(total_chamados_processados,0), 4) AS taxa_erro_ia,
    ROUND(100.0 * total_enviados_triagem_manual / NULLIF(total_chamados_processados,0), 4) AS taxa_triagem_manual
  FROM base
),
upsert_diario AS (
  INSERT INTO metricas_diarias_automacao(
    data_ref,total_chamados_processados,total_classificados_automaticamente,total_enviados_triagem_manual,
    total_com_erro_ia,total_aguardando_fiscal,tempo_medio_triagem_min,taxa_intervencao_humana,
    taxa_automacao_efetiva,taxa_erro_ia,taxa_triagem_manual,chamados_travados_24h,atualizado_em
  )
  SELECT
    data_ref,total_chamados_processados,total_classificados_automaticamente,total_enviados_triagem_manual,
    total_com_erro_ia,total_aguardando_fiscal,tempo_medio_triagem_min,taxa_intervencao_humana,
    taxa_automacao_efetiva,taxa_erro_ia,taxa_triagem_manual,chamados_travados_24h,NOW()
  FROM kpi
  ON CONFLICT(data_ref) DO UPDATE SET
    total_chamados_processados=EXCLUDED.total_chamados_processados,
    total_classificados_automaticamente=EXCLUDED.total_classificados_automaticamente,
    total_enviados_triagem_manual=EXCLUDED.total_enviados_triagem_manual,
    total_com_erro_ia=EXCLUDED.total_com_erro_ia,
    total_aguardando_fiscal=EXCLUDED.total_aguardando_fiscal,
    tempo_medio_triagem_min=EXCLUDED.tempo_medio_triagem_min,
    taxa_intervencao_humana=EXCLUDED.taxa_intervencao_humana,
    taxa_automacao_efetiva=EXCLUDED.taxa_automacao_efetiva,
    taxa_erro_ia=EXCLUDED.taxa_erro_ia,
    taxa_triagem_manual=EXCLUDED.taxa_triagem_manual,
    chamados_travados_24h=EXCLUDED.chamados_travados_24h,
    atualizado_em=NOW()
  RETURNING *
),
prompt_metrics AS (
  INSERT INTO metricas_prompt_version(
    data_ref, etapa, prompt_version, modelo_ia, versao_modelo, total_decisoes,
    total_erros_ia, confianca_media, tempo_medio_ia_ms, acuracia_avaliada, atualizado_em
  )
  SELECT
    CURRENT_DATE,
    d.etapa,
    COALESCE(prompt_version, 'nao_informado'),
    COALESCE(modelo_ia, 'nao_informado'),
    COALESCE(versao_modelo, 'nao_informado'),
    COUNT(*)::int,
    COUNT(*) FILTER (WHERE erro_ia=TRUE)::int,
    ROUND(AVG(confianca), 4),
    ROUND(AVG(tempo_resposta_ms), 2),
    ROUND(AVG((a.ia_estava_correta::int)::numeric) FILTER (WHERE a.ia_estava_correta IS NOT NULL), 4),
    NOW()
  FROM ia_decisoes d
  LEFT JOIN avaliacoes_humanas a ON a.ticket_id=d.ticket_id AND a.etapa=d.etapa
  WHERE d.criado_em >= CURRENT_DATE
  GROUP BY d.etapa, COALESCE(prompt_version, 'nao_informado'), COALESCE(modelo_ia, 'nao_informado'), COALESCE(versao_modelo, 'nao_informado')
  ON CONFLICT(data_ref, etapa, prompt_version, modelo_ia, versao_modelo) DO UPDATE SET
    total_decisoes=EXCLUDED.total_decisoes,
    total_erros_ia=EXCLUDED.total_erros_ia,
    confianca_media=EXCLUDED.confianca_media,
    tempo_medio_ia_ms=EXCLUDED.tempo_medio_ia_ms,
    acuracia_avaliada=EXCLUDED.acuracia_avaliada,
    atualizado_em=NOW()
  RETURNING 1
),
workflow_perf AS (
  INSERT INTO metricas_workflow_performance(data_ref, workflow, fase, total_eventos, total_erros, duracao_media_ms, duracao_p95_ms, atualizado_em)
  SELECT
    CURRENT_DATE,
    workflow,
    COALESCE(fase, ''),
    COUNT(*)::int,
    COUNT(*) FILTER (WHERE erro=TRUE)::int,
    ROUND(AVG(duracao_ms), 2),
    percentile_cont(0.95) WITHIN GROUP (ORDER BY duracao_ms),
    NOW()
  FROM workflow_eventos
  WHERE criado_em >= CURRENT_DATE
  GROUP BY workflow, COALESCE(fase, '')
  ON CONFLICT(data_ref, workflow, fase) DO UPDATE SET
    total_eventos=EXCLUDED.total_eventos,
    total_erros=EXCLUDED.total_erros,
    duracao_media_ms=EXCLUDED.duracao_media_ms,
    duracao_p95_ms=EXCLUDED.duracao_p95_ms,
    atualizado_em=NOW()
  RETURNING 1
),
evento AS (
  INSERT INTO workflow_eventos(workflow,node_name,fase,acao,status_evento,inicio_em,fim_em,duracao_ms)
  VALUES('WF05','PG: Consolidar Metricas','CONSOLIDACAO','CONSOLIDAR_METRICAS','OK',NOW(),NOW(),0)
  RETURNING 1
)
SELECT
  *,
  (COALESCE(taxa_erro_ia,0) > ${erroLimite}
   OR COALESCE(taxa_triagem_manual,0) > ${manualLimite}
   OR COALESCE(chamados_travados_24h,0) > ${travadosLimite}) AS gerar_alerta,
  ${erroLimite}::numeric AS limite_erro_ia_percent,
  ${manualLimite}::numeric AS limite_triagem_manual_percent,
  ${travadosLimite}::int AS limite_chamados_travados
FROM upsert_diario;`;
})() }}"""


HUMAN_REVIEW_SAMPLE_SQL_EXPR = r"""={{ (() => {
const pctRaw = Number($env.AVALIACAO_HUMANA_AMOSTRA_PERCENT || 20);
const minRaw = Number($env.AVALIACAO_HUMANA_AMOSTRA_MIN || 30);
const limitRaw = Number($env.AVALIACAO_HUMANA_AMOSTRA_LIMIT || 30);
const ttlRaw = Number($env.AVALIACAO_HUMANA_TOKEN_TTL_DIAS || 30);
const pct = Number.isFinite(pctRaw) && pctRaw > 0 && pctRaw <= 100 ? pctRaw : 20;
const min = Number.isFinite(minRaw) && minRaw >= 0 ? Math.floor(minRaw) : 30;
const limit = Number.isFinite(limitRaw) && limitRaw > 0 ? Math.floor(limitRaw) : 30;
const ttl = Number.isFinite(ttlRaw) && ttlRaw > 0 ? Math.floor(ttlRaw) : 30;
return `
WITH ultimas_decisoes AS (
  SELECT DISTINCT ON (ticket_id, etapa)
    id AS ia_decisao_id,
    ticket_id,
    etapa,
    predicao,
    confianca,
    prompt_version,
    run_id,
    case_id,
    episode_id,
    criado_em
  FROM ia_decisoes
  WHERE erro_ia = FALSE
    AND ticket_id IS NOT NULL
    AND etapa IN ('CLASSIFICACAO','DEDUPLICACAO')
  ORDER BY ticket_id, etapa, criado_em DESC, id DESC
),
candidatos_classificacao AS (
  SELECT d.*
  FROM ultimas_decisoes d
  JOIN tickets_processados t ON t.id = d.ticket_id
  WHERE d.etapa = 'CLASSIFICACAO'
    AND d.predicao IS NOT NULL
    AND NOT EXISTS (
      SELECT 1 FROM avaliacoes_humanas a
      WHERE a.ticket_id = d.ticket_id
        AND a.etapa = d.etapa
        AND COALESCE(a.status_avaliacao,'CONCLUIDA') IN ('PENDENTE','CONCLUIDA')
    )
),
candidatos_dedup AS (
  SELECT d.*
  FROM ultimas_decisoes d
  JOIN tickets_processados t ON t.id = d.ticket_id
  WHERE d.etapa = 'DEDUPLICACAO'
    AND d.predicao = 'NAO_DUPLICADO'
    AND NOT EXISTS (
      SELECT 1 FROM avaliacoes_humanas a
      WHERE a.ticket_id = d.ticket_id
        AND a.etapa = d.etapa
        AND COALESCE(a.status_avaliacao,'CONCLUIDA') IN ('PENDENTE','CONCLUIDA')
    )
),
limites AS (
  SELECT
    LEAST(${limit}, GREATEST(${min}, CEIL((SELECT COUNT(*) FROM candidatos_classificacao) * ${pct} / 100.0)::int))::int AS limite_classificacao,
    LEAST(${limit}, GREATEST(${min}, CEIL((SELECT COUNT(*) FROM candidatos_dedup) * ${pct} / 100.0)::int))::int AS limite_dedup
),
amostra_classificacao AS (
  SELECT *
  FROM candidatos_classificacao
  ORDER BY random()
  LIMIT (SELECT limite_classificacao FROM limites)
),
amostra_dedup AS (
  SELECT *
  FROM candidatos_dedup
  ORDER BY random()
  LIMIT (SELECT limite_dedup FROM limites)
),
inseridos AS (
  INSERT INTO avaliacoes_humanas(
    ticket_id, etapa, decisao_ia, avaliacao_token, avaliacao_token_expira_em,
    status_avaliacao, origem_amostra, solicitado_em, observacao,
    run_id,case_id,episode_id
  )
  SELECT
    ticket_id,
    etapa,
    predicao,
    replace(gen_random_uuid()::text,'-',''),
    NOW() + (${ttl} || ' days')::interval,
    'PENDENTE',
    CASE WHEN etapa='CLASSIFICACAO' THEN 'WF05_AMOSTRA_CLASSIFICACAO' ELSE 'WF05_AMOSTRA_DEDUP_RECALL' END,
    NOW(),
    jsonb_build_object('ia_decisao_id',ia_decisao_id,'confianca',confianca,'prompt_version',prompt_version)::text,
    run_id,case_id,episode_id
  FROM (
    SELECT * FROM amostra_classificacao
    UNION ALL
    SELECT * FROM amostra_dedup
  ) s
  ON CONFLICT DO NOTHING
  RETURNING id, ticket_id, etapa, decisao_ia, avaliacao_token, avaliacao_token_expira_em, origem_amostra
),
evento AS (
  INSERT INTO workflow_eventos(workflow,node_name,fase,acao,status_evento,inicio_em,fim_em,duracao_ms)
  VALUES('WF05','PG: Selecionar Avaliações Humanas','AVALIACAO_HUMANA','AMOSTRA_AVALIACAO','OK',NOW(),NOW(),0)
  RETURNING 1
)
SELECT
  i.id AS avaliacao_id,
  i.ticket_id,
  i.etapa,
  i.decisao_ia,
  i.avaliacao_token,
  i.avaliacao_token_expira_em,
  i.origem_amostra,
  t.titulo,
  t.status_nome,
  t.classificacao_final,
  t.duplicado_de_id
FROM inseridos i
JOIN tickets_processados t ON t.id = i.ticket_id
ORDER BY i.id;`;
})() }}"""


REQUEST_HUMAN_REVIEW_JS = r"""
const rows = $input.all().map(i => i.json || {}).filter(r => r.ticket_id && r.avaliacao_token);
if (rows.length === 0) {
  console.log('[WF05][LOG] Nenhuma avaliacao humana nova para solicitar.');
  return [{json:{ok:true,total_solicitado:0}}];
}
const apiBase = String((typeof process !== 'undefined' && process.env.GLPI_API_URL) || 'http://host.docker.internal:9080/apirest.php').replace(/\/$/, '');
const appToken = String((typeof process !== 'undefined' && process.env.GLPI_APP_TOKEN) || '');
const auth = String((typeof process !== 'undefined' && process.env.GLPI_AUTH_BASIC) || 'Basic ');
const publicBase = String((typeof process !== 'undefined' && process.env.AVALIACAO_HUMANA_CONFIRMATION_BASE_URL) || ((typeof process !== 'undefined' && process.env.N8N_PUBLIC_BASE_URL) || 'http://localhost:5678') + '/webhook/avaliacao-humana-confirmacao-v9').replace(/\/$/, '');
function enc(v){ return encodeURIComponent(String(v ?? '')); }
function link(token, resultado, classe) {
  let url = publicBase + '?token=' + enc(token) + '&resultado=' + enc(resultado);
  if (classe) url += '&classe_correta=' + enc(classe);
  return url;
}
function correctionLinks(row) {
  if (row.etapa === 'DEDUPLICACAO') {
    return [
      'Confirmar que NAO era duplicado: ' + link(row.avaliacao_token, 'correta', ''),
      'Marcar como duplicado nao detectado: ' + link(row.avaliacao_token, 'incorreta', 'DUPLICADO')
    ].join('\n');
  }
  const classes = ['OBRA','DEMO','SOB_DEMANDA','DEMO_SEM_EQUIPE','TRIAGEM_MANUAL'];
  const out = ['Confirmar classificacao da IA: ' + link(row.avaliacao_token, 'correta', '')];
  for (const c of classes) out.push('Corrigir para ' + c + ': ' + link(row.avaliacao_token, 'incorreta', c));
  return out.join('\n');
}
const init = await helpers.httpRequest({
  method: 'GET',
  url: apiBase + '/initSession',
  headers: {'App-Token': appToken, 'Authorization': auth, 'Content-Type': 'application/json'},
  json: true
});
const sessionToken = String(init.session_token || '');
if (!sessionToken) throw new Error('GLPI initSession sem session_token no WF05 avaliacao humana');
const headers = {'App-Token': appToken, 'Session-Token': sessionToken, 'Content-Type': 'application/json'};
let enviados = 0;
let falhas = 0;
for (const row of rows) {
  const titulo = String(row.titulo || '').slice(0, 180);
  const validade = row.avaliacao_token_expira_em ? String(row.avaliacao_token_expira_em) : 'nao informada';
  const content = [
    '[AVALIACAO_HUMANA]',
    'Solicitacao de validacao para pesquisa/metricas da automacao.',
    'Etapa: ' + row.etapa,
    'Decisao da IA: ' + (row.decisao_ia || 'N/A'),
    'Chamado: #' + row.ticket_id + ' - ' + titulo,
    'Validade do link: ' + validade,
    '',
    correctionLinks(row)
  ].join('\n');
  try {
    await helpers.httpRequest({
      method: 'POST',
      url: apiBase + '/Ticket/' + Number(row.ticket_id) + '/ITILFollowup',
      headers,
      body: {input:{items_id:Number(row.ticket_id), content}},
      json: true
    });
    enviados++;
  } catch (e) {
    falhas++;
    console.log('[WF05][LOG] Falha ao solicitar avaliacao humana #' + row.ticket_id + ': ' + e.message);
  }
}
try {
  await helpers.httpRequest({method:'GET', url: apiBase + '/killSession', headers, json:true});
} catch (e) {}
console.log('[WF05][LOG] Avaliacoes humanas solicitadas=' + enviados + ' falhas=' + falhas);
return [{json:{ok:falhas===0,total_solicitado:enviados,total_falhas:falhas,total_candidatos:rows.length}}];
"""


EXTRACT_HUMAN_REVIEW_JS = r"""
const q = {...($json.query || {}),...($json.body || {})};
const headers = $json.headers || {};
const token = String(q.token || '').trim();
const resultado = String(q.resultado || '').toLowerCase().trim();
const classe = String(q.classe_correta || '').toUpperCase().trim();
const fonteSolicitada = String(q.fonte || '').toUpperCase().trim();
const oraculo = fonteSolicitada === 'ORACULO_GABARITO';
const runId = String(q.run_id || headers['x-test-run-id'] || '').trim();
const scenarioId = String(q.scenario_id || headers['x-test-scenario-id'] || '').trim();
const realizationId = String(q.realization_id || headers['x-test-realization-id'] || '').trim();
const nonce = String(headers['x-test-auto-review-nonce'] || '').trim();
const receivedSecret = String(headers['x-test-auto-review-token'] || '').trim();
const expectedSecret = String(
  (typeof $env!=='undefined' && $env.TEST_AUTO_REVIEW_TOKEN) ||
  (typeof process!=='undefined' && process.env.TEST_AUTO_REVIEW_TOKEN) || ''
);
const flag = name => {
  let value='';
  try { value=String((typeof $env!=='undefined' && $env[name]) || (typeof process!=='undefined' && process.env[name]) || ''); } catch(e) {}
  return value.trim().toLowerCase()==='true';
};
function sameSecret(a,b) {
  if (a.length!==b.length || a.length<32) return false;
  let diff=0; for (let i=0;i<a.length;i++) diff|=a.charCodeAt(i)^b.charCodeAt(i);
  return diff===0;
}
const idsOk = /^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$/.test(runId)
  && /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(scenarioId)
  && /^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$/.test(realizationId);
const oracleAuthOk = !oraculo || (
  flag('TEST_MODE') && flag('TEST_AUTO_HUMAN_CONFIRMATION') &&
  sameSecret(expectedSecret,receivedSecret) && /^[a-f0-9]{32}$/i.test(nonce) && idsOk
);
let avaliador = oraculo ? 'oraculo_gabarito' : String(q.avaliador || 'fiscal_glpi').trim();
if (!oraculo && avaliador.toLowerCase().includes('oraculo')) avaliador='fiscal_glpi';
const motivo = String(q.motivo || '').trim();
const tokenOk = /^[a-f0-9]{32,128}$/i.test(token);
const resultadoOk = ['correta','incorreta'].includes(resultado);
const ok = tokenOk && resultadoOk && oracleAuthOk;
let msg = '';
if (!tokenOk) msg = 'Token de avaliacao ausente ou invalido.';
else if (!resultadoOk) msg = 'Resultado de avaliacao invalido.';
else if (!oracleAuthOk) msg = 'Origem ORACULO_GABARITO nao autorizada.';
return [{json:{
  ok,token:tokenOk?token:null,resultado,classe_correta:classe,avaliador,motivo,msg,
  fonte_gabarito:oraculo?'ORACULO_GABARITO':'REVISAO_HUMANA',oraculo,
  run_id:oraculo?runId:null,scenario_id:oraculo?scenarioId:null,
  realization_id:oraculo?realizationId:null,assessor_nonce:oraculo?nonce:null
}}];
"""


REGISTER_HUMAN_REVIEW_SQL_EXPR = r"""={{ (() => {
const d = $('Extrair Avaliação Humana').first().json || {};
const esc = s => "'" + String(s ?? '').replace(/'/g,"''") + "'";
if (d.ok !== true) {
  return `SELECT 400::int AS http_status, ${esc(d.msg || 'Avaliacao invalida.')} AS mensagem;`;
}
const token = esc(d.token);
const resultado = String(d.resultado || '').toLowerCase();
const correta = resultado === 'correta';
const classe = d.classe_correta ? esc(d.classe_correta) : 'NULL';
const avaliador = esc(d.avaliador || 'fiscal_glpi');
const motivo = d.motivo ? esc(d.motivo) : 'NULL';
const oraculo = d.oraculo === true;
const runId = d.run_id ? esc(d.run_id) : 'NULL';
const scenarioId = d.scenario_id ? esc(d.scenario_id) : 'NULL';
const realizationId = d.realization_id ? esc(d.realization_id) : 'NULL';
const nonce = d.assessor_nonce ? esc(d.assessor_nonce) : 'NULL';
const fonte = esc(oraculo ? 'ORACULO_GABARITO' : 'REVISAO_HUMANA');
return `
WITH alvo AS (
  SELECT *
  FROM avaliacoes_humanas
  WHERE avaliacao_token = ${token}
  LIMIT 1
),
contexto_oraculo AS (
  SELECT
    dc.run_id,dc.scenario_id,dc.case_id AS realization_id,
    i.id AS ia_decisao_id,i.predicao,
    CASE WHEN a.etapa='DEDUPLICACAO'
      THEN CASE WHEN dc.duplicado_esperado THEN 'DUPLICADO' ELSE 'NAO_DUPLICADO' END
      ELSE dc.classificacao_esperada END AS classe_gabarito,
    (i.predicao=(CASE WHEN a.etapa='DEDUPLICACAO'
      THEN CASE WHEN dc.duplicado_esperado THEN 'DUPLICADO' ELSE 'NAO_DUPLICADO' END
      ELSE dc.classificacao_esperada END)) AS ia_correta
  FROM alvo a
  JOIN dataset_controle dc ON dc.ticket_id=a.ticket_id
  JOIN experimentos_avaliacao e ON e.run_id=dc.run_id
  JOIN LATERAL (
    SELECT id,predicao,criado_em
    FROM ia_decisoes i
    WHERE i.ticket_id=a.ticket_id AND i.run_id=dc.run_id
      AND i.case_id=dc.case_id AND i.etapa=a.etapa
      AND i.criado_em<=COALESCE(a.solicitado_em,NOW())
    ORDER BY i.criado_em DESC,i.id DESC LIMIT 1
  ) i ON TRUE
  WHERE ${oraculo ? 'TRUE' : 'FALSE'}
    AND dc.run_id=${runId} AND dc.scenario_id=${scenarioId} AND dc.case_id=${realizationId}
    AND length(dc.run_id) BETWEEN 3 AND 128
    AND left(dc.run_id,1) ~ '[A-Za-z0-9]'
    AND dc.run_id !~ '[^A-Za-z0-9._:-]'
    AND length(dc.scenario_id) BETWEEN 1 AND 64
    AND left(dc.scenario_id,1) ~ '[A-Za-z0-9]'
    AND dc.scenario_id !~ '[^A-Za-z0-9_-]'
    AND length(dc.case_id) BETWEEN 3 AND 128
    AND left(dc.case_id,1) ~ '[A-Za-z0-9]'
    AND dc.case_id !~ '[^A-Za-z0-9._:-]'
    AND UPPER(COALESCE(dc.split,'')) IN ('PILOTO','VALIDACAO','TESTE','TEST','BENCHMARK')
    AND COALESCE(dc.origem,'') ~ '^(AVALIACAO_|VALIDACAO_|DATASET_)'
    AND COALESCE(dc.label_source,'') ~ '^(REGRA_SINTETICA|SYNTHETIC_|ADJUDICADO_|GABARITO_)'
    AND LOWER(COALESCE(e.generation_config->>'test_mode','false'))='true'
    AND LOWER(COALESCE(e.generation_config->>'auto_human_confirmation','false'))='true'
    AND a.decisao_ia=i.predicao
    AND (CASE WHEN a.etapa='DEDUPLICACAO'
      THEN CASE WHEN dc.duplicado_esperado IS NULL THEN NULL
        WHEN dc.duplicado_esperado THEN 'DUPLICADO' ELSE 'NAO_DUPLICADO' END
      ELSE NULLIF(dc.classificacao_esperada,'') END) IS NOT NULL
    AND ${esc(resultado)}=(CASE WHEN i.predicao=(CASE WHEN a.etapa='DEDUPLICACAO'
      THEN CASE WHEN dc.duplicado_esperado THEN 'DUPLICADO' ELSE 'NAO_DUPLICADO' END
      ELSE dc.classificacao_esperada END) THEN 'correta' ELSE 'incorreta' END)
    AND (
      ${esc(resultado)}='correta'
      OR ${classe}=(CASE WHEN a.etapa='DEDUPLICACAO'
        THEN CASE WHEN dc.duplicado_esperado THEN 'DUPLICADO' ELSE 'NAO_DUPLICADO' END
        ELSE dc.classificacao_esperada END)
    )
    AND EXISTS (
      SELECT 1 FROM avaliacao_auto_confirmacoes ac
      WHERE ac.avaliacao_id=a.id AND ac.run_id=dc.run_id
        AND ac.scenario_id=dc.scenario_id AND ac.realization_id=dc.case_id
        AND ac.tipo_confirmacao='AVALIACAO_METRICA' AND ac.etapa=a.etapa
        AND ac.ia_decisao_id=i.id AND ac.status='RESERVADA'
        AND ac.predicao_ia=i.predicao
        AND ac.classe_gabarito=(CASE WHEN a.etapa='DEDUPLICACAO'
          THEN CASE WHEN dc.duplicado_esperado THEN 'DUPLICADO' ELSE 'NAO_DUPLICADO' END
          ELSE dc.classificacao_esperada END)
        AND ac.decisao_webhook=${esc(resultado)}
        AND ac.token_hash=encode(sha256(convert_to(a.avaliacao_token,'UTF8')),'hex')
        AND ac.assessor_nonce_hash=encode(sha256(convert_to(${nonce},'UTF8')),'hex')
    )
),
atualizado AS (
  UPDATE avaliacoes_humanas a
  SET
    status_avaliacao = 'CONCLUIDA',
    ia_estava_correta = CASE WHEN ${oraculo ? 'TRUE' : 'FALSE'}
      THEN (SELECT ia_correta FROM contexto_oraculo)
      ELSE ${correta ? 'TRUE' : 'FALSE'} END,
    decisao_humana = CASE
      WHEN ${oraculo ? 'TRUE' : 'FALSE'} THEN (SELECT classe_gabarito FROM contexto_oraculo)
      WHEN ${correta ? 'TRUE' : 'FALSE'} THEN a.decisao_ia
      ELSE COALESCE(${classe}, a.decisao_humana, 'CORRIGIR_MANUAL')
    END,
    classe_correta = CASE
      WHEN ${oraculo ? 'TRUE' : 'FALSE'} THEN (SELECT classe_gabarito FROM contexto_oraculo)
      WHEN ${correta ? 'TRUE' : 'FALSE'} THEN COALESCE(a.classe_correta, a.decisao_ia)
      ELSE COALESCE(${classe}, a.classe_correta)
    END,
    avaliador = ${avaliador},
    fonte_gabarito = ${fonte},
    motivo_divergencia = ${motivo},
    concluido_em = NOW(),
    avaliado_em = NOW(),
    observacao = COALESCE(a.observacao,'')
      || CASE WHEN ${oraculo ? 'TRUE' : 'FALSE'} THEN E'\n[ORACULO_GABARITO] Confirmacao automatica test-only autenticada.' ELSE '' END
      || CASE WHEN ${motivo} IS NULL THEN '' ELSE E'\n' || ${motivo} END
  WHERE a.id = (SELECT id FROM alvo)
    AND COALESCE(a.status_avaliacao,'PENDENTE') = 'PENDENTE'
    AND (a.avaliacao_token_expira_em IS NULL OR a.avaliacao_token_expira_em > NOW())
    AND (NOT ${oraculo ? 'TRUE' : 'FALSE'} OR EXISTS (SELECT 1 FROM contexto_oraculo))
  RETURNING a.id, a.ticket_id, a.etapa, a.decisao_ia, a.decisao_humana, a.classe_correta
),
evento_ok AS (
  INSERT INTO workflow_eventos(ticket_id,workflow,node_name,fase,acao,status_evento,erro,mensagem_erro,inicio_em,fim_em)
  SELECT ticket_id,'WF05','PG: Registrar Avaliação Humana','AVALIACAO_HUMANA',
         CASE WHEN ${oraculo ? 'TRUE' : 'FALSE'} THEN 'ORACULO_GABARITO'
              WHEN ${correta ? 'TRUE' : 'FALSE'} THEN 'IA_CORRETA' ELSE 'IA_CORRIGIDA' END,
         'OK',FALSE,NULL,NOW(),NOW()
  FROM atualizado
  RETURNING 1
)
SELECT
  200::int AS http_status,
  ('Avaliacao registrada para o chamado #' || ticket_id || '.')::text AS mensagem,
  ticket_id,
  etapa,
  decisao_ia,
  decisao_humana,
  classe_correta
FROM atualizado
UNION ALL
SELECT
  CASE
    WHEN NOT EXISTS (SELECT 1 FROM alvo) THEN 404
    WHEN ${oraculo ? 'TRUE' : 'FALSE'} AND NOT EXISTS (SELECT 1 FROM contexto_oraculo) THEN 403
    WHEN EXISTS (SELECT 1 FROM alvo WHERE COALESCE(status_avaliacao,'PENDENTE') <> 'PENDENTE') THEN 200
    WHEN EXISTS (SELECT 1 FROM alvo WHERE avaliacao_token_expira_em IS NOT NULL AND avaliacao_token_expira_em <= NOW()) THEN 410
    ELSE 409
  END::int AS http_status,
  CASE
    WHEN NOT EXISTS (SELECT 1 FROM alvo) THEN 'Token de avaliacao nao encontrado.'
    WHEN ${oraculo ? 'TRUE' : 'FALSE'} AND NOT EXISTS (SELECT 1 FROM contexto_oraculo) THEN 'Confirmacao automatica sem reserva ou contexto experimental valido.'
    WHEN EXISTS (SELECT 1 FROM alvo WHERE COALESCE(status_avaliacao,'PENDENTE') <> 'PENDENTE') THEN 'Avaliacao ja registrada anteriormente.'
    WHEN EXISTS (SELECT 1 FROM alvo WHERE avaliacao_token_expira_em IS NOT NULL AND avaliacao_token_expira_em <= NOW()) THEN 'Token de avaliacao expirado.'
    ELSE 'Avaliacao nao pode ser registrada.'
  END::text AS mensagem,
  (SELECT ticket_id FROM alvo),
  (SELECT etapa FROM alvo),
  (SELECT decisao_ia FROM alvo),
  NULL::text,
  NULL::text
WHERE NOT EXISTS (SELECT 1 FROM atualizado);`;
})() }}"""


WORKFLOW = {
    "name": "V9 - WF05 Métricas",
    "nodes": [
        {
            "parameters": {},
            "type": "n8n-nodes-base.manualTrigger",
            "typeVersion": 1,
            "position": [-800, 0],
            "id": "v9-wf05-manual",
            "name": "T1. Manual",
        },
        {
            "parameters": {"rule": {"interval": [{"field": "cronExpression", "expression": "0 23 * * *"}]}},
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.2,
            "position": [-800, 220],
            "id": "v9-wf05-schedule",
            "name": "T2. Schedule 23h",
        },
        {
            "parameters": {
                "jsCode": "const inicio=new Date(); console.log('[WF05][LOG] Inicio metricas V9'); return [{json:{inicio:inicio.toISOString(),fase:'WF05_INICIO'}}];"
            },
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [-560, 110],
            "id": "v9-wf05-log-inicio",
            "name": "LOG: Início",
            "alwaysOutputData": True,
        },
        {
            "parameters": {"operation": "executeQuery", "query": SCHEMA_READINESS_SQL, "options": {}},
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.5,
            "position": [-320, 110],
            "id": "v9-wf05-schema",
            "name": "PG: Verificar Schema Observabilidade",
            "credentials": PG_CRED,
            "alwaysOutputData": True,
        },
        {
            "parameters": {"operation": "executeQuery", "query": CONSOLIDATE_SQL_EXPR, "options": {}},
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.5,
            "position": [-60, 110],
            "id": "v9-wf05-consolidar",
            "name": "PG: Consolidar Métricas",
            "credentials": PG_CRED,
            "alwaysOutputData": True,
        },
        {
            "parameters": {
                "conditions": {
                    "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                    "conditions": [{"leftValue": "={{ $json.gerar_alerta === true }}", "operator": {"type": "boolean", "operation": "true"}, "id": "if1"}],
                    "combinator": "and",
                },
                "options": {},
            },
            "type": "n8n-nodes-base.if",
            "typeVersion": 2.2,
            "position": [200, 110],
            "id": "v9-wf05-alerta-if",
            "name": "Alerta necessário?",
        },
        {
            "parameters": {
                "fromEmail": "n8n@campus.local",
                "toEmail": "={{ $env.METRICAS_ALERTA_EMAIL || $env.INFRA_EMAIL || 'infraestrutura@campus.local' }}",
                "subject": "={{ (()=>{ const d=new Date($json.data_ref); const dia=Number.isNaN(d.getTime())?String($json.data_ref).slice(0,10):d.toISOString().slice(0,10); return '[V9][Métricas] Alerta de indicadores - '+dia; })() }}",
                "emailFormat": "text",
                "text": "={{ (()=>{ const d=new Date($json.data_ref); const dia=Number.isNaN(d.getTime())?String($json.data_ref).slice(0,10):d.toISOString().slice(0,10); return 'Resumo WF05 '+dia+'\\n\\nErro IA: '+String($json.taxa_erro_ia)+'% (limite '+String($json.limite_erro_ia_percent)+'%)\\nTriagem manual: '+String($json.taxa_triagem_manual)+'% (limite '+String($json.limite_triagem_manual_percent)+'%)\\nChamados travados 24h: '+String($json.chamados_travados_24h)+' (limite '+String($json.limite_chamados_travados)+')\\n\\nTotal processado: '+String($json.total_chamados_processados)+'\\nAutomação efetiva: '+String($json.taxa_automacao_efetiva)+'%'; })() }}",
                "options": {"appendAttribution": False},
            },
            "type": "n8n-nodes-base.emailSend",
            "typeVersion": 2.1,
            "position": [460, 0],
            "id": "v9-wf05-email-alerta",
            "name": "Email: Alerta Métricas",
            "credentials": SMTP_CRED,
            "onError": "continueRegularOutput",
        },
        {
            "parameters": {
                "jsCode": "console.log('[WF05][LOG] Fim metricas alerta=' + String($json.gerar_alerta)); return [{json:{ok:true,resumo_visual:'WF05 consolidou metricas da V9.', data_ref:$json.data_ref, gerar_alerta:$json.gerar_alerta}}];"
            },
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [720, 110],
            "id": "v9-wf05-fim",
            "name": "LOG: Fim",
            "alwaysOutputData": True,
        },
    ],
    "pinData": {},
    "connections": {
        "T1. Manual": {"main": [[{"node": "LOG: Início", "type": "main", "index": 0}]]},
        "T2. Schedule 23h": {"main": [[{"node": "LOG: Início", "type": "main", "index": 0}]]},
        "LOG: Início": {"main": [[{"node": "PG: Verificar Schema Observabilidade", "type": "main", "index": 0}]]},
        "PG: Verificar Schema Observabilidade": {"main": [[{"node": "PG: Consolidar Métricas", "type": "main", "index": 0}]]},
        "PG: Consolidar Métricas": {"main": [[{"node": "Alerta necessário?", "type": "main", "index": 0}]]},
        "Alerta necessário?": {"main": [[{"node": "Email: Alerta Métricas", "type": "main", "index": 0}], [{"node": "LOG: Fim", "type": "main", "index": 0}]]},
        "Email: Alerta Métricas": {"main": [[{"node": "LOG: Fim", "type": "main", "index": 0}]]},
    },
    "active": True,
    "settings": {"executionOrder": "v1", "timezone": "America/Sao_Paulo", "saveExecutionProgress": True, "saveManualExecutions": True},
    "versionId": "v9-wf05-metricas",
    "meta": {},
    "id": "ZpQ0H9uV9Metric05",
    "tags": [],
}


def _ensure_node(node: dict) -> None:
    if not any(existing.get("name") == node.get("name") for existing in WORKFLOW["nodes"]):
        WORKFLOW["nodes"].append(node)


def _connect(source: str, target: str, output_index: int = 0) -> None:
    outputs = WORKFLOW["connections"].setdefault(source, {"main": [[]]})["main"]
    while len(outputs) <= output_index:
        outputs.append([])
    if not any(conn.get("node") == target for conn in outputs[output_index]):
        outputs[output_index].append({"node": target, "type": "main", "index": 0})


def _apply_section7_updates() -> None:
    _ensure_node(
        {
            "parameters": {"path": "avaliacao-humana-v9", "httpMethod": "POST", "responseMode": "responseNode", "options": {}},
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [-800, 440],
            "id": "v9-wf05-webhook-avaliacao",
            "name": "Webhook Avaliação Humana",
            "webhookId": "v9-wf05-avaliacao-humana",
        }
    )
    _ensure_node(
        {
            "parameters": {"jsCode": EXTRACT_HUMAN_REVIEW_JS},
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [-560, 440],
            "id": "v9-wf05-extrair-avaliacao",
            "name": "Extrair Avaliação Humana",
            "alwaysOutputData": True,
        }
    )
    _ensure_node(
        {
            "parameters": {"operation": "executeQuery", "query": REGISTER_HUMAN_REVIEW_SQL_EXPR, "options": {}},
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.5,
            "position": [-320, 440],
            "id": "v9-wf05-registrar-avaliacao",
            "name": "PG: Registrar Avaliação Humana",
            "credentials": PG_CRED,
            "alwaysOutputData": True,
        }
    )
    _ensure_node(
        {
            "parameters": {
                "respondWith": "text",
                "responseBody": "={{ $json.mensagem || 'Avaliacao registrada.' }}",
                "options": {
                    "responseCode": "={{ Number($json.http_status || 200) }}",
                    "responseHeaders": {"entries": [{"name": "Content-Type", "value": "text/plain; charset=utf-8"}]},
                },
            },
            "type": "n8n-nodes-base.respondToWebhook",
            "typeVersion": 1.5,
            "position": [-60, 440],
            "id": "v9-wf05-resp-avaliacao",
            "name": "Resp: Avaliação Humana",
        }
    )
    _ensure_node(
        {
            "parameters": {"operation": "executeQuery", "query": HUMAN_REVIEW_SAMPLE_SQL_EXPR, "options": {}},
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.5,
            "position": [200, 320],
            "id": "v9-wf05-selecionar-avaliacoes",
            "name": "PG: Selecionar Avaliações Humanas",
            "credentials": PG_CRED,
            "alwaysOutputData": True,
        }
    )
    _ensure_node(
        {
            "parameters": {"jsCode": REQUEST_HUMAN_REVIEW_JS},
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [460, 320],
            "id": "v9-wf05-solicitar-avaliacoes",
            "name": "GLPI: Solicitar Avaliações Humanas",
            "alwaysOutputData": True,
            "onError": "continueRegularOutput",
        }
    )
    _connect("PG: Consolidar Métricas", "PG: Selecionar Avaliações Humanas")
    _connect("PG: Selecionar Avaliações Humanas", "GLPI: Solicitar Avaliações Humanas")
    _connect("Webhook Avaliação Humana", "Extrair Avaliação Humana")
    _connect("Extrair Avaliação Humana", "PG: Registrar Avaliação Humana")
    _connect("PG: Registrar Avaliação Humana", "Resp: Avaliação Humana")


_apply_section7_updates()


def _apply_post_confirmation_updates() -> None:
    preview_js = r"""
const q=$json.query || {};
const esc=value=>String(value ?? '').replace(/[&<>\"']/g,ch=>({
  '&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'
}[ch]));
const token=String(q.token || '').trim();
const resultado=String(q.resultado || '').toLowerCase().trim();
const classe=String(q.classe_correta || '').toUpperCase().trim();
const valido=/^[a-f0-9]{32,128}$/i.test(token) && ['correta','incorreta'].includes(resultado);
const campos={token,resultado};
if (classe) campos.classe_correta=classe;
const hidden=Object.entries(campos).map(([key,value])=>
  '<input type="hidden" name="'+esc(key)+'" value="'+esc(value)+'">'
).join('');
const resumo=resultado==='correta' ? 'Confirmar a decisão da automação' : 'Registrar correção da decisão';
const html=valido
  ? '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Confirmar avaliação</title></head><body><main><h1>Confirmar avaliação humana</h1><p>'+esc(resumo)+(classe ? ': '+esc(classe) : '')+'.</p><p>Esta página não registra a avaliação até você pressionar o botão.</p><form method="post" action="/webhook/avaliacao-humana-v9">'+hidden+'<button type="submit">Confirmar avaliação</button></form></main></body></html>'
  : '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Link inválido</title></head><body><h1>Link inválido ou incompleto</h1><p>Revise o chamado diretamente no GLPI.</p></body></html>';
return [{json:{http_status:valido?200:400,response_html:html}}];
"""
    _ensure_node(
        {
            "parameters": {
                "path": "avaliacao-humana-confirmacao-v9",
                "httpMethod": "GET",
                "responseMode": "responseNode",
                "options": {},
            },
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [-800, 620],
            "id": "v9-wf05-webhook-confirmacao",
            "name": "Webhook Confirmação Avaliação",
            "webhookId": "v9-wf05-confirmacao-avaliacao",
        }
    )
    _ensure_node(
        {
            "parameters": {"jsCode": preview_js},
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [-560, 620],
            "id": "v9-wf05-render-confirmacao",
            "name": "Renderizar Confirmação Avaliação",
            "alwaysOutputData": True,
        }
    )
    _ensure_node(
        {
            "parameters": {
                "respondWith": "text",
                "responseBody": "={{ $json.response_html }}",
                "options": {
                    "responseCode": "={{ Number($json.http_status || 200) }}",
                    "responseHeaders": {
                        "entries": [
                            {"name": "Content-Type", "value": "text/html; charset=utf-8"},
                            {"name": "Cache-Control", "value": "no-store"},
                            {"name": "X-Content-Type-Options", "value": "nosniff"},
                        ]
                    },
                },
            },
            "type": "n8n-nodes-base.respondToWebhook",
            "typeVersion": 1.5,
            "position": [-320, 620],
            "id": "v9-wf05-resp-confirmacao",
            "name": "Resp: Confirmação Avaliação",
        }
    )
    _connect("Webhook Confirmação Avaliação", "Renderizar Confirmação Avaliação")
    _connect("Renderizar Confirmação Avaliação", "Resp: Confirmação Avaliação")


_apply_post_confirmation_updates()


def _apply_experiment_updates() -> None:
    # A amostragem científica é estratificada pelo conferir_gabarito.py.
    # O WF05 não deve criar uma amostra aleatória concorrente durante o benchmark.
    obsolete = {
        "PG: Selecionar Avaliações Humanas",
        "GLPI: Solicitar Avaliações Humanas",
    }
    WORKFLOW["nodes"] = [
        node for node in WORKFLOW["nodes"] if node.get("name") not in obsolete
    ]
    for source in obsolete:
        WORKFLOW["connections"].pop(source, None)
    outputs = WORKFLOW["connections"].get("PG: Consolidar Métricas", {}).get("main", [])
    for branch in outputs:
        branch[:] = [
            edge
            for edge in branch
            if edge.get("node") not in obsolete
        ]


_apply_experiment_updates()


def main() -> None:
    sanitize_workflow_secrets(WORKFLOW)
    rendered = json.dumps(WORKFLOW, ensure_ascii=False, indent=2) + "\n"
    rendered_sha = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    if rendered_sha != SNAPSHOT_SHA256:
        raise RuntimeError(
            "WF05 gerado diverge do snapshot aprovado. "
            f"Atualize SNAPSHOT_SHA256 apos uma alteracao intencional: {rendered_sha}"
        )
    for output in OUTPUT_FILES:
        path = DIR / output
        path.write_text(rendered, encoding="utf-8", newline="\n")
        print(f"Salvo: {path}")


if __name__ == "__main__":
    main()
