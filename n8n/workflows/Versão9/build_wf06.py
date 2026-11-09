"""Builder do WF06 V9: ingresso GLPI e fila persistente para chamadas de IA."""
import hashlib
import json
from pathlib import Path

from helpers import (
    WORKFLOW_IDS,
    code_node,
    conn,
    exec_wf,
    if_node,
    pg_query,
    respond_node,
    sanitize_workflow_secrets,
    save,
    webhook_node,
    workflow,
)


DIR = Path(__file__).resolve().parent
OUTPUT = DIR / "V9-WF06-Fila-IA.json"
SNAPSHOT_SHA256 = "73a3b919c50c3975c7b9d8ff4e75cda38ed46715878e72a1bd3dfc6a6e0b6332"


def schedule_trigger():
    return {
        "parameters": {
            "rule": {
                "interval": [
                    {"field": "cronExpression", "expression": "*/1 * * * *"}
                ]
            }
        },
        "type": "n8n-nodes-base.scheduleTrigger",
        "typeVersion": 1.2,
        "position": [-1120, 400],
        "id": "v9-wf06-schedule",
        "name": "Agendador Fila IA",
    }


def manual_trigger():
    return {
        "parameters": {},
        "type": "n8n-nodes-base.manualTrigger",
        "typeVersion": 1,
        "position": [-1120, 560],
        "id": "v9-wf06-manual",
        "name": "Manual",
    }


def wait_node():
    return {
        "parameters": {
            "amount": "={{ Number($json.delay_seconds || 0) }}",
            "unit": "seconds",
        },
        "type": "n8n-nodes-base.wait",
        "typeVersion": 1.1,
        "position": [96, 400],
        "id": "v9-wf06-aguardar",
        "name": "Aguardar Janela",
        "webhookId": "v9-wf06-aguardar",
    }


def execute_wf02_node():
    node = exec_wf(
        "v9-wf06-chamar-wf02",
        "Chamar WF02 da Fila",
        [608, 496],
        WORKFLOW_IDS["V9 - WF02 Triagem"],
        wait=True,
    )
    node["parameters"]["workflowInputs"]["value"] = {
        "source": "wf06-fila-ia",
        "event": "ticket_queued_release",
        "ticket_id": "={{ $json.chamado.id }}",
        "id": "={{ $json.chamado.id }}",
        "chamado": "={{ $json.chamado }}",
    }
    return node


def execute_wf03_node():
    node = exec_wf(
        "v9-wf06-chamar-wf03",
        "Chamar WF03 da Fila",
        [608, 304],
        WORKFLOW_IDS["V9 - WF03 Classificação"],
        wait=True,
    )
    node["parameters"]["workflowInputs"]["value"] = {
        "source": "wf06-fila-ia",
        "event": "classification_queued_release",
        "ticket_id": "={{ $json.chamado.id }}",
        "id": "={{ $json.chamado.id }}",
        "chamado": "={{ $json.chamado }}",
    }
    return node


PREPARAR_ENTRADA_JS = r"""
const raw = $input.first().json || {};
const body = raw.body || raw;
const id = Number(body.ticket_id ?? body.items_id ?? body.id);
// O gateway n8n-gateway valida X-Webhook-Key antes de encaminhar este path.
// O processo n8n não publica porta própria, portanto não existe rota de bypass.
if (!Number.isInteger(id) || id <= 0) {
  console.log('[WF06][LOG] Ingresso GLPI sem ticket_id válido');
  return [{json:{authorized:false, erro:true, codigo_http:422, mensagem:'ticket_id inválido'}}];
}
const chamado = {
  id,
  titulo: String(body.name || body.titulo || ''),
  descricao: String(body.descricao || ''),
  tipo_servico: String(body.itilcategories_id || body.tipo_servico || ''),
  localizacao: String(body.localizacao || ''),
  solicitante: String(body.solicitante || ''),
  email_solicitante: String(body.email_solicitante || ''),
  status_num: Number(body.status || body.status_num || 1),
  status_nome: String(body.status_nome || 'Novo'),
  data_abertura: body.date || body.data_abertura || new Date().toISOString(),
  data_ultima_mudanca: body.date_mod || body.data_ultima_mudanca || new Date().toISOString(),
  source: String(body.source || 'glpi-plugin-n8nwebhook'),
  evento: String(body.event || 'ticket.add')
};
console.log('[WF06][LOG] Ingresso GLPI autenticado ticket=#' + id);
return [{json:{authorized:true, erro:false, codigo_http:202, chamado}}];
"""


ENFILEIRAR_QUERY = r"""{{ (() => {
const c = $json.chamado || {};
const esc = value => "'" + String(value ?? '').replace(/'/g, "''") + "'";
const id = Number(c.id || 0);
const status = Number(c.status_num || 1);
const log = esc(JSON.stringify({wf:'WF06',acao:'ENFILEIRAR',origem:c.source||'GLPI',ts:new Date().toISOString()}));
return `
INSERT INTO tickets_processados(
  id,titulo,descricao,tipo_servico,localizacao,solicitante,email_solicitante,
  status_num,status_nome,data_abertura,data_ultima_mudanca,origem_ingestao,
  triagem_status,ultima_acao_workflow,log_workflow,wf_version,
  fila_enfileirada_em,fila_disponivel_em,fila_liberar_em,fila_reservada_em,fila_ultimo_erro,fila_etapa
)
VALUES(
  ${id},${esc(c.titulo)},${esc(c.descricao)},${esc(c.tipo_servico)},${esc(c.localizacao)},
  ${esc(c.solicitante)},${esc(c.email_solicitante)},${status},${esc(c.status_nome || 'Novo')},
  ${esc(c.data_abertura)},${esc(c.data_ultima_mudanca)},${esc(c.source || 'GLPI_WEBHOOK')},
  'PENDENTE_FILA_IA','WF06_ENFILEIRADO','[${log.substring(1,log.length-1)}]'::jsonb,'v9',
  NOW(),NOW(),NULL,NULL,NULL,'DEDUPLICACAO'
)
ON CONFLICT(id) DO UPDATE SET
  titulo=COALESCE(NULLIF(EXCLUDED.titulo,''),tickets_processados.titulo),
  descricao=COALESCE(NULLIF(EXCLUDED.descricao,''),tickets_processados.descricao),
  tipo_servico=COALESCE(NULLIF(EXCLUDED.tipo_servico,''),tickets_processados.tipo_servico),
  localizacao=COALESCE(NULLIF(EXCLUDED.localizacao,''),tickets_processados.localizacao),
  solicitante=COALESCE(NULLIF(EXCLUDED.solicitante,''),tickets_processados.solicitante),
  email_solicitante=COALESCE(NULLIF(EXCLUDED.email_solicitante,''),tickets_processados.email_solicitante),
  status_num=EXCLUDED.status_num,
  status_nome=EXCLUDED.status_nome,
  data_abertura=COALESCE(EXCLUDED.data_abertura,tickets_processados.data_abertura),
  data_ultima_mudanca=CASE
    WHEN EXCLUDED.data_ultima_mudanca IS NULL THEN tickets_processados.data_ultima_mudanca
    WHEN tickets_processados.data_ultima_mudanca IS NULL THEN EXCLUDED.data_ultima_mudanca
    ELSE GREATEST(tickets_processados.data_ultima_mudanca,EXCLUDED.data_ultima_mudanca)
  END,
  origem_ingestao=COALESCE(NULLIF(EXCLUDED.origem_ingestao,''),tickets_processados.origem_ingestao),
  triagem_status=CASE
    WHEN EXCLUDED.status_num <> 1 THEN tickets_processados.triagem_status
    WHEN COALESCE(tickets_processados.em_aprovacao_fiscal,FALSE)
      OR tickets_processados.triagem_status IN (
        'FILA_IA_LIBERADA','CLASSIFICANDO_DUP','PENDENTE','CLASSIFICANDO',
        'TRIAGEM_MANUAL','ERRO_IA','DUPLICADO_FECHADO','ATRIBUIDO_DEMO',
        'PLANEJADO_DEMO_SEM_EQUIPE','ENCAMINHADO_PLANEJADO','FECHADO_OBRA'
      )
      OR tickets_processados.classificacao_final IN (
        'OBRA','DEMO','SOB_DEMANDA','TRIAGEM_MANUAL','DUPLICADO','POSSIVEL_DUPLICADO'
      )
    THEN tickets_processados.triagem_status
    ELSE 'PENDENTE_FILA_IA'
  END,
  fila_enfileirada_em=CASE
    WHEN EXCLUDED.status_num=1
      AND NOT COALESCE(tickets_processados.em_aprovacao_fiscal,FALSE)
      AND COALESCE(tickets_processados.triagem_status,'') NOT IN (
        'FILA_IA_LIBERADA','CLASSIFICANDO_DUP','PENDENTE','CLASSIFICANDO',
        'TRIAGEM_MANUAL','ERRO_IA','DUPLICADO_FECHADO','ATRIBUIDO_DEMO',
        'PLANEJADO_DEMO_SEM_EQUIPE','ENCAMINHADO_PLANEJADO','FECHADO_OBRA'
      )
    THEN COALESCE(tickets_processados.fila_enfileirada_em,NOW())
    ELSE tickets_processados.fila_enfileirada_em
  END,
  fila_disponivel_em=CASE
    WHEN EXCLUDED.status_num=1
      AND NOT COALESCE(tickets_processados.em_aprovacao_fiscal,FALSE)
      AND COALESCE(tickets_processados.triagem_status,'') NOT IN (
        'FILA_IA_LIBERADA','CLASSIFICANDO_DUP','PENDENTE','CLASSIFICANDO',
        'TRIAGEM_MANUAL','ERRO_IA','DUPLICADO_FECHADO','ATRIBUIDO_DEMO',
        'PLANEJADO_DEMO_SEM_EQUIPE','ENCAMINHADO_PLANEJADO','FECHADO_OBRA'
      )
    THEN COALESCE(tickets_processados.fila_disponivel_em,NOW())
    ELSE tickets_processados.fila_disponivel_em
  END,
  fila_liberar_em=CASE
    WHEN tickets_processados.triagem_status IN ('PENDENTE_FILA_IA','FILA_IA_LIBERADA')
    THEN tickets_processados.fila_liberar_em ELSE NULL END,
  fila_reservada_em=CASE
    WHEN tickets_processados.triagem_status='FILA_IA_LIBERADA'
    THEN tickets_processados.fila_reservada_em ELSE NULL END,
  fila_etapa=CASE
    WHEN tickets_processados.triagem_status IN ('PENDENTE_FILA_IA','FILA_IA_LIBERADA')
    THEN tickets_processados.fila_etapa
    ELSE 'DEDUPLICACAO'
  END,
  ultima_acao_workflow=CASE
    WHEN tickets_processados.triagem_status IN ('PENDENTE_FILA_IA','FILA_IA_LIBERADA')
    THEN tickets_processados.ultima_acao_workflow
    ELSE 'WF06_ENFILEIRADO'
  END,
  log_workflow=COALESCE(tickets_processados.log_workflow,'[]'::jsonb) || ${log}::jsonb,
  atualizado_em=NOW()
RETURNING id,triagem_status,(triagem_status='PENDENTE_FILA_IA') AS enfileirado;
`;
})() }}"""


SELECIONAR_QUERY = r"""{{ (() => {
const envValue=name=>{
  let value='';
  try { value=String((typeof $env!=='undefined' && $env[name]) || ''); } catch(e) {}
  if (!value) {
    try { value=String((typeof process!=='undefined' && process.env[name]) || ''); } catch(e) {}
  }
  return value.trim();
};
const loteRaw = Number(envValue('FILA_IA_LOTE_TAMANHO') || 3);
const loteMinRaw = Number(envValue('FILA_IA_LOTE_MIN') || 1);
const loteMaxRaw = Number(envValue('FILA_IA_LOTE_MAX') || 5);
const adaptive = ['1','true','yes','on','sim'].includes(envValue('FILA_IA_RATE_LIMIT_ADAPTATIVO').toLowerCase());
const intervaloRaw = Number(envValue('FILA_IA_INTERVALO_SEGUNDOS') || 45);
const leaseRaw = Number(envValue('FILA_IA_LEASE_SEGUNDOS') || 900);
const graceRaw = Number(envValue('FILA_IA_INGRESS_GRACE_SEGUNDOS') || 10);
const runScope = envValue('FILA_IA_RUN_SCOPE');
if (runScope && !/^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$/.test(runScope)) {
  throw new Error('FILA_IA_RUN_SCOPE inválido');
}
const runScopeSql = runScope ? "'" + runScope.replace(/'/g,"''") + "'" : 'NULL';
const lote = Number.isFinite(loteRaw) && loteRaw > 0 ? Math.min(50,Math.floor(loteRaw)) : 3;
const loteMin = Number.isFinite(loteMinRaw) && loteMinRaw > 0 ? Math.min(10,Math.floor(loteMinRaw)) : 1;
const loteMax = Number.isFinite(loteMaxRaw) && loteMaxRaw >= loteMin ? Math.min(50,Math.floor(loteMaxRaw)) : 5;
const intervalo = Number.isFinite(intervaloRaw) && intervaloRaw >= 0 ? Math.min(600,Math.floor(intervaloRaw)) : 45;
const lease = Number.isFinite(leaseRaw) && leaseRaw >= 60 ? Math.min(86400,Math.floor(leaseRaw)) : 900;
const grace = Number.isFinite(graceRaw) && graceRaw >= 0 ? Math.min(300,Math.floor(graceRaw)) : 10;
const log = JSON.stringify({wf:'WF06',acao:'RESERVAR_FILA',lote,lote_min:loteMin,lote_max:loteMax,adaptativo:adaptive,intervalo,lease,run_scope:runScope||null,ts:new Date().toISOString()}).replace(/'/g,"''");
return `
WITH
parametros AS MATERIALIZED (
  SELECT ${runScopeSql}::text AS run_scope
),
escopo_ids AS MATERIALIZED (
  SELECT DISTINCT dc.ticket_id
  FROM dataset_controle dc
  CROSS JOIN parametros p
  WHERE p.run_scope IS NOT NULL
    AND dc.run_id=p.run_scope
    AND dc.ticket_id IS NOT NULL
),
bloqueio AS MATERIALIZED (
  SELECT pg_advisory_xact_lock(9062026) AS adquirido
),
reservas_expiradas AS (
  UPDATE tickets_processados t
  SET triagem_status='PENDENTE_FILA_IA',
      fila_liberar_em=NULL,
      fila_reservada_em=NULL,
      fila_ultimo_erro='Reserva expirada; reenfileirado pelo WF06',
      ultima_acao_workflow='WF06_REENFILEIROU_RESERVA_EXPIRADA',
      atualizado_em=NOW()
  FROM bloqueio
  WHERE t.triagem_status='FILA_IA_LIBERADA'
    AND COALESCE(t.fila_liberar_em,t.fila_reservada_em,t.atualizado_em)
        + (${lease} || ' seconds')::interval < NOW()
    AND (
      (SELECT run_scope FROM parametros) IS NULL
      OR EXISTS (SELECT 1 FROM escopo_ids s WHERE s.ticket_id=t.id)
    )
  RETURNING t.id
),
experimentos_encerrados AS (
  UPDATE tickets_processados t
  SET triagem_status='EXPERIMENTO_ENCERRADO',
      fila_liberar_em=NULL,
      fila_reservada_em=NULL,
      fila_ultimo_erro='Experimento encerrado; removido da fila operacional pelo WF06',
      ultima_acao_workflow='WF06_QUARENTENA_EXPERIMENTO_ENCERRADO',
      log_workflow=COALESCE(t.log_workflow,'[]'::jsonb) || jsonb_build_array(
        jsonb_build_object(
          'wf','WF06',
          'acao','QUARENTENA_EXPERIMENTO_ENCERRADO',
          'ts',NOW()
        )
      ),
      atualizado_em=NOW()
  FROM bloqueio
  WHERE t.triagem_status IN ('PENDENTE_FILA_IA','FILA_IA_LIBERADA')
    AND EXISTS (
      SELECT 1
      FROM dataset_controle dc
      WHERE dc.ticket_id=t.id AND dc.run_id IS NOT NULL
    )
    AND NOT EXISTS (
      SELECT 1
      FROM dataset_controle dc
      JOIN experimentos_avaliacao e ON e.run_id=dc.run_id
      WHERE dc.ticket_id=t.id
        AND e.status IN ('EXECUTANDO','CALIBRANDO')
    )
  RETURNING t.id
),
controle AS (
  SELECT id,GREATEST(COALESCE(proxima_liberacao_em,NOW()),NOW()) AS base
  FROM fila_ia_controle
  CROSS JOIN bloqueio
  WHERE id=1
  FOR UPDATE
),
lote_efetivo AS (
  SELECT CASE
    WHEN ${adaptive ? 'TRUE' : 'FALSE'} THEN
      CASE
        WHEN (SELECT AVG(COALESCE((output_normalizado->>'elapsed_ms')::numeric, 150)) FROM ia_decisoes WHERE criado_em >= NOW() - INTERVAL '5 minutes') > 600
             OR (SELECT COUNT(*) FROM fila_ia_dead_letter WHERE criado_em >= NOW() - INTERVAL '5 minutes') > 0
          THEN ${loteMin}
        WHEN (SELECT AVG(COALESCE((output_normalizado->>'elapsed_ms')::numeric, 150)) FROM ia_decisoes WHERE criado_em >= NOW() - INTERVAL '5 minutes') < 250
          THEN ${loteMax}
        ELSE ${lote}
      END
    ELSE ${lote}
  END AS tamanho
),
fila_elegivel AS MATERIALIZED (
  SELECT t.id
  FROM tickets_processados t
  WHERE t.triagem_status IN ('PENDENTE_FILA_IA','FILA_IA_LIBERADA')
    AND COALESCE(t.em_aprovacao_fiscal,FALSE)=FALSE
    AND (
      (
        COALESCE(t.fila_etapa,'DEDUPLICACAO')='DEDUPLICACAO'
        AND COALESCE(t.status_num,1)=1
      )
      OR (
        t.fila_etapa='CLASSIFICACAO'
        AND COALESCE(t.status_num,4)=4
      )
    )
    AND (
      (
        (SELECT run_scope FROM parametros) IS NOT NULL
        AND EXISTS (
          SELECT 1
          FROM dataset_controle dc
          JOIN experimentos_avaliacao e ON e.run_id=dc.run_id
          WHERE dc.ticket_id=t.id
            AND dc.run_id=(SELECT run_scope FROM parametros)
            AND e.status IN ('EXECUTANDO','CALIBRANDO')
        )
      )
      OR (
        (SELECT run_scope FROM parametros) IS NULL
        AND (
          NOT EXISTS (
            SELECT 1 FROM dataset_controle dc
            WHERE dc.ticket_id=t.id AND dc.run_id IS NOT NULL
          )
          OR EXISTS (
            SELECT 1
            FROM dataset_controle dc
            JOIN experimentos_avaliacao e ON e.run_id=dc.run_id
            WHERE dc.ticket_id=t.id
              AND e.status IN ('EXECUTANDO','CALIBRANDO')
          )
        )
      )
    )
),
capacidade AS (
  SELECT GREATEST((SELECT tamanho FROM lote_efetivo) - COUNT(*)::int,0)::int AS slots
  FROM tickets_processados t
  JOIN fila_elegivel e ON e.id=t.id
  WHERE t.triagem_status='FILA_IA_LIBERADA'
),
travados AS (
  SELECT t.id,COALESCE(t.data_abertura,t.criado_em) AS ordem_data
  FROM tickets_processados t
  JOIN fila_elegivel e ON e.id=t.id
  WHERE t.triagem_status='PENDENTE_FILA_IA'
    AND COALESCE(t.fila_enfileirada_em,t.criado_em)
        <= NOW() - (${grace} || ' seconds')::interval
    AND COALESCE(t.fila_disponivel_em,t.fila_enfileirada_em,t.criado_em) <= NOW()
  ORDER BY COALESCE(t.data_abertura,t.criado_em),t.id
  LIMIT (SELECT slots FROM capacidade)
  FOR UPDATE SKIP LOCKED
),
candidatos AS (
  SELECT
    id,
    ROW_NUMBER() OVER (ORDER BY ordem_data,id)-1 AS pos
  FROM travados
),
marcados AS (
  UPDATE tickets_processados t
  SET triagem_status='FILA_IA_LIBERADA',
      fila_liberar_em=c.base + (candidatos.pos * ${intervalo} || ' seconds')::interval,
      fila_reservada_em=NOW(),
      fila_tentativas=COALESCE(t.fila_tentativas,0)+1,
      fila_ultimo_erro=NULL,
      ultima_acao_workflow='WF06_RESERVOU_FILA',
      log_workflow=COALESCE(t.log_workflow,'[]'::jsonb) || '${log}'::jsonb,
      atualizado_em=NOW()
  FROM candidatos CROSS JOIN controle c
  WHERE t.id=candidatos.id
  RETURNING t.*,GREATEST(
    0,EXTRACT(EPOCH FROM (
      c.base + (candidatos.pos * ${intervalo} || ' seconds')::interval - NOW()
    ))
  )::int AS delay_seconds
),
avanco AS (
  UPDATE fila_ia_controle f
  SET proxima_liberacao_em=CASE
        WHEN (SELECT COUNT(*) FROM marcados)>0
        THEN (SELECT base FROM controle)
          + ((SELECT COUNT(*) FROM marcados) * ${intervalo} || ' seconds')::interval
        ELSE GREATEST(COALESCE(f.proxima_liberacao_em,NOW()),NOW())
      END,
      intervalo_segundos=${intervalo},
      lote_tamanho=${lote},
      atualizado_em=NOW()
  FROM bloqueio
  WHERE f.id=1
  RETURNING f.id
),
metricas AS (
  INSERT INTO fila_ia_metricas(
    run_id,pendentes,reservados,liberados_ciclo,espera_media_segundos,
    espera_p95_segundos,intervalo_segundos,lote_tamanho
  )
  SELECT
    COALESCE(
      (SELECT run_scope FROM parametros),
      CASE
        WHEN COUNT(DISTINCT COALESCE(dc.run_id,'__OPERACIONAL__'))=1
        THEN MAX(dc.run_id)
        ELSE NULL
      END
    ),
    (
      SELECT COUNT(*)::int
      FROM tickets_processados t
      JOIN fila_elegivel e ON e.id=t.id
      WHERE t.triagem_status='PENDENTE_FILA_IA'
    ),
    (
      SELECT COUNT(*)::int
      FROM tickets_processados t
      JOIN fila_elegivel e ON e.id=t.id
      WHERE t.triagem_status='FILA_IA_LIBERADA'
    ),
    (SELECT COUNT(*)::int FROM marcados),
    (
      SELECT AVG(EXTRACT(EPOCH FROM (NOW()-COALESCE(t.fila_enfileirada_em,t.criado_em))))
      FROM tickets_processados t
      JOIN fila_elegivel e ON e.id=t.id
      WHERE t.triagem_status IN ('PENDENTE_FILA_IA','FILA_IA_LIBERADA')
    ),
    (
      SELECT percentile_cont(0.95) WITHIN GROUP (
        ORDER BY EXTRACT(EPOCH FROM (NOW()-COALESCE(t.fila_enfileirada_em,t.criado_em)))
      )
      FROM tickets_processados t
      JOIN fila_elegivel e ON e.id=t.id
      WHERE t.triagem_status IN ('PENDENTE_FILA_IA','FILA_IA_LIBERADA')
    ),
    ${intervalo},${lote}
  FROM bloqueio base
  LEFT JOIN marcados m ON TRUE
  LEFT JOIN dataset_controle dc ON dc.ticket_id=m.id
    AND (
      (SELECT run_scope FROM parametros) IS NULL
      OR dc.run_id=(SELECT run_scope FROM parametros)
    )
  RETURNING id
),
contextualizados AS (
  SELECT
    m.*,
    dc.run_id AS experiment_run_id,
    COALESCE(dc.split,e.split) AS experiment_split,
    COALESCE(e.generation_config,'{}'::jsonb) AS experiment_generation_config,
    CASE
      WHEN dc.run_id IS NULL THEN 'LOCAL'
      ELSE e.generation_config->>'ia_fixed_model_role'
    END AS ia_fixed_model_role,
    COALESCE(e.generation_config->>'ia_expected_model',e.modelo_ia) AS ia_expected_model,
    COALESCE(
      e.generation_config->>'ia_execution_mode',
      CASE
        WHEN UPPER(COALESCE(dc.split,e.split,'')) IN ('TEST','TESTE','BENCHMARK') THEN 'BENCHMARK'
        WHEN dc.run_id IS NOT NULL THEN 'EXPERIMENTAL'
        ELSE 'OPERATIONAL'
      END
    ) AS ia_execution_mode
  FROM marcados m
  LEFT JOIN LATERAL (
    SELECT d.run_id,d.split
    FROM dataset_controle d
    WHERE d.ticket_id=m.id
      AND (
        (SELECT run_scope FROM parametros) IS NULL
        OR d.run_id=(SELECT run_scope FROM parametros)
      )
    ORDER BY d.id DESC
    LIMIT 1
  ) dc ON TRUE
  LEFT JOIN experimentos_avaliacao e ON e.run_id=dc.run_id
)
SELECT COALESCE(
         jsonb_agg(to_jsonb(contextualizados) ORDER BY contextualizados.fila_liberar_em,contextualizados.id),
         '[]'::jsonb
       ) AS tickets,
       COUNT(*)::int AS total
FROM contextualizados
WHERE EXISTS (SELECT 1 FROM avanco)
  AND EXISTS (SELECT 1 FROM metricas);
`;
})() }}"""


PREPARAR_LOTE_JS = r"""
const inputRows = $input.all().map(item => item.json || {});
const row = inputRows.find(candidate =>
  Object.prototype.hasOwnProperty.call(candidate, 'tickets')
) || {};
let tickets = row.tickets || [];
if (typeof tickets === 'string') {
  try { tickets = JSON.parse(tickets); } catch { tickets = []; }
}
if (!Array.isArray(tickets)) tickets = [];
console.log('[WF06][LOG] Reservas liberadas no ciclo=' + tickets.length);
if (tickets.length === 0) return [{json:{total_lote:0}}];
return tickets.map((chamado,index) => ({
  json:{
    total_lote:tickets.length,
    lote_posicao:index+1,
    delay_seconds:Number(chamado.delay_seconds || 0),
    source:'wf06-fila-ia',
    event:'ticket_queued_release',
    chamado:{...chamado,source:'wf06-fila-ia'}
  }
}));
"""


LOG_INGRESSO_JS = (
    "console.log('[WF06][LOG] Ticket #' + ($json.id || 'N/A') + "
    "' enfileirado=' + String($json.enfileirado)); "
    "return [{json:{ok:true,ticket_id:$json.id,enfileirado:$json.enfileirado,"
    "triagem_status:$json.triagem_status}}];"
)
LOG_INICIO_JS = (
    "console.log('[WF06][LOG] Início do ciclo da fila IA'); "
    "return [{json:{ok:true,fase:'WF06_INICIO'}}];"
)
LOG_FIM_JS = (
    "console.log('[WF06][LOG] Ticket liberado ao WF02: #' + "
    "($json.chamado?.id || $json.ticket_id || 'N/A')); "
    "return [{json:{ok:true,fase:'WF06_LIBERADO'}}];"
)


WF = workflow(
    "V9 - WF06 Fila IA",
    [
        webhook_node(
            "v9-wf06-webhook",
            "Webhook GLPI Fila",
            [-1120, 0],
            "glpi-ticket-fila-ia-v9",
            response_mode="responseNode",
        ),
        code_node(
            "v9-wf06-preparar-entrada",
            "Preparar Entrada GLPI",
            [-880, 0],
            PREPARAR_ENTRADA_JS,
        ),
        if_node(
            "v9-wf06-autorizado",
            "Entrada Autorizada?",
            [-640, 0],
            "={{ $json.authorized === true }}",
            "boolean",
            "true",
        ),
        respond_node(
            "v9-wf06-resp-202",
            "Resp: Enfileirado 202",
            [-144, -80],
            "Recebido pelo WF06 para processamento em fila",
            202,
        ),
        respond_node(
            "v9-wf06-resp-401",
            "Resp: Rejeitado",
            [-400, 96],
            "={{ $json.mensagem || 'Não autorizado' }}",
            "={{ Number($json.codigo_http || 401) }}",
        ),
        pg_query(
            "v9-wf06-enfileirar",
            "PG: Enfileirar Ticket",
            [-400, -80],
            ENFILEIRAR_QUERY,
        ),
        code_node(
            "v9-wf06-log-ingresso",
            "LOG: Ingresso Enfileirado",
            [112, -80],
            LOG_INGRESSO_JS,
        ),
        schedule_trigger(),
        manual_trigger(),
        code_node(
            "v9-wf06-log-inicio",
            "LOG: Início Fila",
            [-880, 480],
            LOG_INICIO_JS,
        ),
        pg_query(
            "v9-wf06-selecionar",
            "PG: Reservar Fila IA",
            [-624, 480],
            SELECIONAR_QUERY,
        ),
        code_node(
            "v9-wf06-preparar-lote",
            "Preparar Lote",
            [-368, 480],
            PREPARAR_LOTE_JS,
        ),
        if_node(
            "v9-wf06-tem-chamados",
            "Tem Chamados?",
            [-144, 480],
            "={{ Number($json.total_lote || 0) > 0 }}",
            "boolean",
            "true",
        ),
        wait_node(),
        execute_wf02_node(),
        if_node(
            "v9-wf06-etapa-classificacao",
            "É Classificação?",
            [352, 400],
            "={{ String($json.chamado.fila_etapa || 'DEDUPLICACAO') === 'CLASSIFICACAO' }}",
            "boolean",
            "true",
        ),
        execute_wf03_node(),
        code_node(
            "v9-wf06-log-fim",
            "LOG: Fim Fila",
            [864, 400],
            LOG_FIM_JS,
        ),
    ],
    [
        conn("Webhook GLPI Fila", "Preparar Entrada GLPI"),
        conn("Preparar Entrada GLPI", "Entrada Autorizada?"),
        conn("Entrada Autorizada?", "PG: Enfileirar Ticket", "Resp: Rejeitado"),
        conn("PG: Enfileirar Ticket", "Resp: Enfileirado 202"),
        conn("Resp: Enfileirado 202", "LOG: Ingresso Enfileirado"),
        conn("Agendador Fila IA", "LOG: Início Fila"),
        conn("Manual", "LOG: Início Fila"),
        conn("LOG: Início Fila", "PG: Reservar Fila IA"),
        conn("PG: Reservar Fila IA", "Preparar Lote"),
        conn("Preparar Lote", "Tem Chamados?"),
        conn("Tem Chamados?", "Aguardar Janela", []),
        conn("Aguardar Janela", "É Classificação?"),
        conn("É Classificação?", "Chamar WF03 da Fila", "Chamar WF02 da Fila"),
        conn("Chamar WF02 da Fila", "LOG: Fim Fila"),
        conn("Chamar WF03 da Fila", "LOG: Fim Fila"),
    ],
    active=True,
)


if __name__ == "__main__":
    sanitize_workflow_secrets(WF)
    rendered = json.dumps(WF, indent=2, ensure_ascii=False)
    rendered_sha = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    if rendered_sha != SNAPSHOT_SHA256:
        raise RuntimeError(
            "WF06 gerado diverge do snapshot aprovado. "
            f"Atualize SNAPSHOT_SHA256 apos uma alteracao intencional: {rendered_sha}"
        )
    save(WF, OUTPUT)
