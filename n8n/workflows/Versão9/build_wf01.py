"""Gera V9-WF01-Sincronizador.json a partir do snapshot Python do JSON final V9.

Este arquivo foi regenerado a partir de V9-WF01-Sincronizador.json. A estrutura WORKFLOW abaixo
mantem a logica, posicoes, parametros e conexoes do workflow exportado pelo n8n.
Edite este builder nas proximas alteracoes e execute-o para recriar os JSONs.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from helpers import sanitize_workflow_secrets

DIR = Path(__file__).resolve().parent
EXPECTED_NAME = 'V9 - WF01 Sincronizador'
SNAPSHOT_SHA256 = "844732c63e2c0083ab9ffa7e227957785c99449fb238f181bbc246216a09b9b2"
OUTPUT_FILES = ['V9-WF01-Sincronizador.json']

WORKFLOW = {'name': 'V9 - WF01 Sincronizador',
 'nodes': [{'parameters': {},
            'type': 'n8n-nodes-base.manualTrigger',
            'typeVersion': 1,
            'position': [-1200, 0],
            'id': 'v9-wf01-t1',
            'name': 'T1. Manual'},
           {'parameters': {'rule': {'interval': [{'field': 'cronExpression', 'expression': '0 6,12 * * *'}]}},
            'type': 'n8n-nodes-base.scheduleTrigger',
            'typeVersion': 1.2,
            'position': [-1200, 280],
            'id': 'v9-wf01-t2',
            'name': 'T2. Schedule 06h/12h'},
           {'parameters': {'jsCode': "console.log('[WF01][LOG] Início sincronizador V9'); return [{json:{ts:new "
                                     'Date().toISOString()}}];'},
            'type': 'n8n-nodes-base.code',
            'typeVersion': 2,
            'position': [-930, 140],
            'id': 'v9-wf01-log1',
            'name': 'LOG: Início',
            'alwaysOutputData': True},
           {'parameters': {'operation': 'executeQuery',
                           'query': '\n'
                                    'CREATE TABLE IF NOT EXISTS tickets_processados (\n'
                                    '  id                    BIGINT PRIMARY KEY,\n'
                                    "  titulo                TEXT NOT NULL DEFAULT '',\n"
                                    '  descricao             TEXT,\n'
                                    '  tipo_servico          TEXT,\n'
                                    '  tipo_servico_id       BIGINT,\n'
                                    '  localizacao           TEXT,\n'
                                    '  solicitante           TEXT,\n'
                                    '  solicitante_id        BIGINT,\n'
                                    '  email_solicitante     TEXT,\n'
                                    '  status_num            INTEGER NOT NULL DEFAULT 0,\n'
                                    "  status_nome           TEXT NOT NULL DEFAULT '',\n"
                                    '  data_abertura         TIMESTAMPTZ,\n'
                                    '  data_ultima_mudanca   TIMESTAMPTZ,\n'
                                    "  origem_ingestao       TEXT NOT NULL DEFAULT 'SYNC',\n"
                                    '  triagem_status        TEXT,\n'
                                    '  classificacao         TEXT,\n'
                                    '  classificacao_final   TEXT,\n'
                                    '  executor              TEXT,\n'
                                    '  duplicado_de_id       BIGINT,\n'
                                    '  decisao_fiscal        TEXT,\n'
                                    '  fiscal_decision_token TEXT,\n'
                                    '  fiscal_token_expira_em TIMESTAMPTZ,\n'
                                    '  motivo_classificacao  TEXT,\n'
                                    '  confianca_ia          NUMERIC(5,4),\n'
                                    '  triagem_manual        BOOLEAN DEFAULT FALSE,\n'
                                    '  em_aprovacao_fiscal   BOOLEAN DEFAULT FALSE,\n'
                                    '  aprovacao_iniciada_em TIMESTAMPTZ,\n'
                                    '  aprovacao_decidida_em TIMESTAMPTZ,\n'
                                    '  triado_em             TIMESTAMPTZ,\n'
                                    '  ultima_acao_workflow  TEXT,\n'
                                    '  tentativas_ia_dedup   INTEGER DEFAULT 0,\n'
                                    '  tentativas_ia_classificacao INTEGER DEFAULT 0,\n'
                                    '  tentativas_ia         INTEGER DEFAULT 0,\n'
                                    '  ultimo_erro_ia        TEXT,\n'
                                    "  log_workflow          JSONB DEFAULT '[]'::jsonb,\n"
                                    "  wf_version            TEXT DEFAULT 'v9',\n"
                                    '  criado_em             TIMESTAMPTZ DEFAULT NOW(),\n'
                                    '  atualizado_em         TIMESTAMPTZ DEFAULT NOW()\n'
                                    ');\n'
                                    '\n'
                                    'ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS classificacao_final '
                                    'TEXT;\n'
                                    'ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS tentativas_ia_dedup '
                                    'INTEGER DEFAULT 0;\n'
                                    'ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS '
                                    'tentativas_ia_classificacao INTEGER DEFAULT 0;\n'
                                    'ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS tentativas_ia INTEGER '
                                    'DEFAULT 0;\n'
                                    'ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS ultimo_erro_ia TEXT;\n'
                                    'ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS log_workflow JSONB '
                                    "DEFAULT '[]'::jsonb;\n"
                                    'ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS wf_version TEXT DEFAULT '
                                    "'v9';\n"
                                    'ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS tipo_servico_id BIGINT;\n'
                                    'ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS solicitante_id BIGINT;\n'
                                    'ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS confianca_ia '
                                    'NUMERIC(5,4);\n'
                                    'ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS triagem_manual BOOLEAN '
                                    'DEFAULT FALSE;\n'
                                    'ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS fiscal_decision_token '
                                    'TEXT;\n'
                                    'ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS fiscal_token_expira_em '
                                    'TIMESTAMPTZ;\n'
                                    '\n'
                                    'CREATE INDEX IF NOT EXISTS idx_tp_status ON tickets_processados(status_num);\n'
                                    'CREATE INDEX IF NOT EXISTS idx_tp_data_abertura ON '
                                    'tickets_processados(data_abertura);\n'
                                    'CREATE INDEX IF NOT EXISTS idx_tp_mudanca ON '
                                    'tickets_processados(data_ultima_mudanca);\n'
                                    'CREATE INDEX IF NOT EXISTS idx_tp_localizacao ON '
                                    'tickets_processados(localizacao);\n'
                                    'CREATE INDEX IF NOT EXISTS idx_tp_triagem ON '
                                    'tickets_processados(triagem_status);\n'
                                    'CREATE INDEX IF NOT EXISTS idx_tp_aprovacao ON '
                                    'tickets_processados(em_aprovacao_fiscal);\n'
                                    'CREATE INDEX IF NOT EXISTS idx_tp_classificacao_final ON '
                                    'tickets_processados(classificacao_final);\n'
                                    'CREATE INDEX IF NOT EXISTS idx_tp_tipo_servico_id ON '
                                    'tickets_processados(tipo_servico_id);\n'
                                    'CREATE INDEX IF NOT EXISTS idx_tp_solicitante_id ON '
                                    'tickets_processados(solicitante_id);\n'
                                    'CREATE INDEX IF NOT EXISTS idx_tp_triagem_manual ON '
                                    'tickets_processados(triagem_manual);\n'
                                    'CREATE INDEX IF NOT EXISTS idx_tp_fiscal_decision_token ON '
                                    'tickets_processados(fiscal_decision_token);\n'
                                    'CREATE INDEX IF NOT EXISTS idx_tp_fiscal_token_expira ON '
                                    'tickets_processados(fiscal_token_expira_em);\n'
                                    '\n'
                                    'CREATE OR REPLACE FUNCTION trg_atualizado_em() RETURNS trigger AS $$\n'
                                    'BEGIN NEW.atualizado_em = NOW(); RETURN NEW; END;\n'
                                    '$$ LANGUAGE plpgsql;\n'
                                    '\n'
                                    'DROP TRIGGER IF EXISTS trg_tickets_atualizado ON tickets_processados;\n'
                                    'CREATE TRIGGER trg_tickets_atualizado\n'
                                    '  BEFORE UPDATE ON tickets_processados\n'
                                    '  FOR EACH ROW EXECUTE FUNCTION trg_atualizado_em();\n'
                                    '\n'
                                    'CREATE OR REPLACE VIEW metricas_ia_duplicidade_v9 AS\n'
                                    'WITH base AS (\n'
                                    '  SELECT\n'
                                    '    COUNT(*) FILTER (\n'
                                    "      WHERE classificacao = 'POSSIVEL_DUPLICADO'\n"
                                    "         OR classificacao_final IN ('POSSIVEL_DUPLICADO','DUPLICADO')\n"
                                    "         OR decisao_fiscal IN ('CONFIRMOU_DUP','REJEITOU_DUP')\n"
                                    '    ) AS suspeitas_ia,\n'
                                    "    COUNT(*) FILTER (WHERE decisao_fiscal = 'CONFIRMOU_DUP') AS "
                                    'confirmadas_fiscal,\n'
                                    "    COUNT(*) FILTER (WHERE decisao_fiscal = 'REJEITOU_DUP') AS "
                                    'rejeitadas_fiscal,\n'
                                    '    COUNT(*) FILTER (WHERE em_aprovacao_fiscal = TRUE) AS pendentes_fiscal\n'
                                    '  FROM tickets_processados\n'
                                    ')\n'
                                    'SELECT\n'
                                    '  suspeitas_ia,\n'
                                    '  confirmadas_fiscal,\n'
                                    '  rejeitadas_fiscal,\n'
                                    '  pendentes_fiscal,\n'
                                    '  CASE\n'
                                    '    WHEN confirmadas_fiscal + rejeitadas_fiscal = 0 THEN NULL\n'
                                    '    ELSE ROUND((confirmadas_fiscal::numeric * 100.0) / (confirmadas_fiscal + '
                                    'rejeitadas_fiscal), 2)\n'
                                    '  END AS assertividade_percentual\n'
                                    'FROM base;\n'
                                    '\n'
                                    "SELECT 'schema_ok' AS result;\n",
                           'options': {}},
            'type': 'n8n-nodes-base.postgres',
            'typeVersion': 2.5,
            'position': [-680, 140],
            'id': 'v9-wf01-schema',
            'name': 'PG: Garantir Schema',
            'credentials': {'postgres': {'id': 'PG_TRIAGEM', 'name': 'Postgres Triagem'}},
            'alwaysOutputData': True},
           {'parameters': {'operation': 'executeQuery',
                           'query': '\n'
                                    'WITH removidos AS (\n'
                                    '  DELETE FROM tickets_processados\n'
                                    '  WHERE status_num IN (5,6)\n'
                                    '    AND GREATEST(\n'
                                    "      COALESCE(data_abertura, 'epoch'::timestamptz),\n"
                                    "      COALESCE(data_ultima_mudanca, 'epoch'::timestamptz)\n"
                                    "    ) < NOW() - INTERVAL '90 days'\n"
                                    '    AND COALESCE(em_aprovacao_fiscal, FALSE) = FALSE\n'
                                    '  RETURNING id\n'
                                    ')\n'
                                    'SELECT COUNT(*)::int AS removidos FROM removidos;\n',
                           'options': {}},
            'type': 'n8n-nodes-base.postgres',
            'typeVersion': 2.5,
            'position': [-430, 140],
            'id': 'v9-wf01-retencao',
            'name': 'PG: Retenção 90 dias',
            'credentials': {'postgres': {'id': 'PG_TRIAGEM', 'name': 'Postgres Triagem'}},
            'alwaysOutputData': True},
           {'parameters': {'jsCode': "const r=$json||{}; console.log('[WF01][LOG] Retencao 90 dias removeu "
                                     "'+Number(r.removidos||0)+' registros'); return [{json:r}];"},
            'type': 'n8n-nodes-base.code',
            'typeVersion': 2,
            'position': [-180, 140],
            'id': 'v9-wf01-ret-log',
            'name': 'LOG: Retenção 90 dias',
            'alwaysOutputData': True},
           {'parameters': {'url': "={{ ($env.GLPI_API_URL || 'http://host.docker.internal:9080/apirest.php') + "
                                  "'/initSession' }}",
                           'options': {},
                           'sendHeaders': True,
                           'headerParameters': {'parameters': [{'name': 'App-Token',
                                                                'value': '={{ $env.GLPI_APP_TOKEN || '
                                                                         "'' }}"},
                                                               {'name': 'Authorization',
                                                                'value': "={{ $env.GLPI_AUTH_BASIC || 'Basic "
                                                                         "' }}"}]}},
            'type': 'n8n-nodes-base.httpRequest',
            'typeVersion': 4.2,
            'position': [70, 140],
            'id': 'v9-wf01-gs',
            'name': 'GLPI: Iniciar Sessão',
            'typeOptions': {'timeoutMilliseconds': 15000},
            'alwaysOutputData': True},
           {'parameters': {'url': "={{ ($env.GLPI_API_URL || 'http://host.docker.internal:9080/apirest.php') + "
                                  "'/search/Ticket' }}",
                           'options': {},
                           'sendHeaders': True,
                           'headerParameters': {'parameters': [{'name': 'App-Token',
                                                                'value': '={{ $env.GLPI_APP_TOKEN || '
                                                                         "'' }}"},
                                                               {'name': 'Session-Token',
                                                                'value': "={{ $('GLPI: Iniciar "
                                                                         "Sessão').first().json.session_token }}"}]},
                           'sendQuery': True,
                           'queryParameters': {'parameters': [{'name': 'criteria[0][field]', 'value': '12'},
                                                              {'name': 'criteria[0][searchtype]', 'value': 'equals'},
                                                              {'name': 'criteria[0][value]', 'value': '1'},
                                                              {'name': 'criteria[1][link]', 'value': 'OR'},
                                                              {'name': 'criteria[1][field]', 'value': '12'},
                                                              {'name': 'criteria[1][searchtype]', 'value': 'equals'},
                                                              {'name': 'criteria[1][value]', 'value': '2'},
                                                              {'name': 'criteria[2][link]', 'value': 'OR'},
                                                              {'name': 'criteria[2][field]', 'value': '12'},
                                                              {'name': 'criteria[2][searchtype]', 'value': 'equals'},
                                                              {'name': 'criteria[2][value]', 'value': '3'},
                                                              {'name': 'criteria[3][link]', 'value': 'OR'},
                                                              {'name': 'criteria[3][field]', 'value': '12'},
                                                              {'name': 'criteria[3][searchtype]', 'value': 'equals'},
                                                              {'name': 'criteria[3][value]', 'value': '4'},
                                                              {'name': 'criteria[4][link]', 'value': 'OR'},
                                                              {'name': 'criteria[4][field]', 'value': '12'},
                                                              {'name': 'criteria[4][searchtype]', 'value': 'equals'},
                                                              {'name': 'criteria[4][value]', 'value': '5'},
                                                              {'name': 'criteria[5][link]', 'value': 'OR'},
                                                              {'name': 'criteria[5][field]', 'value': '12'},
                                                              {'name': 'criteria[5][searchtype]', 'value': 'equals'},
                                                              {'name': 'criteria[5][value]', 'value': '6'},
                                                              {'name': 'forcedisplay[0]', 'value': '1'},
                                                              {'name': 'forcedisplay[1]', 'value': '2'},
                                                              {'name': 'forcedisplay[2]', 'value': '12'},
                                                              {'name': 'forcedisplay[3]', 'value': '21'},
                                                              {'name': 'forcedisplay[4]', 'value': '83'},
                                                              {'name': 'forcedisplay[5]', 'value': '15'},
                                                              {'name': 'forcedisplay[6]', 'value': '4'},
                                                              {'name': 'forcedisplay[7]', 'value': '22'},
                                                              {'name': 'forcedisplay[8]', 'value': '7'},
                                                              {'name': 'forcedisplay[9]', 'value': '19'},
                                                              {'name': 'range', 'value': '0-9999'}]}},
            'type': 'n8n-nodes-base.httpRequest',
            'typeVersion': 4.2,
            'position': [350, 140],
            'id': 'v9-wf01-search',
            'name': 'GLPI: Buscar Chamados',
            'typeOptions': {'timeoutMilliseconds': 15000},
            'alwaysOutputData': True},
           {'parameters': {'jsCode': '\n'
                                     "const STATUS_MAP = {1:'Novo',2:'Em atendimento (atribuído)',3:'Em atendimento "
                                     "(planejado)',4:'Pendente',5:'Solucionado',6:'Fechado'};\n"
                                     'const corte = new Date(Date.now() - 90 * 86400000);\n'
                                     "let trigger = 'SCHEDULE';\n"
                                     'try {\n'
                                     "  const manual = $('T1. Manual').first();\n"
                                     "  if (manual) trigger = 'MANUAL';\n"
                                     '} catch(e) {}\n'
                                     '\n'
                                     'function stripHtml(s) {\n'
                                     "  return String(s || '').replace(/<[^>]*>/g, '').replace(/\\s+/g, ' ').trim();\n"
                                     '}\n'
                                     'function parseId(v) {\n'
                                     '  const n = Number(v);\n'
                                     '  return Number.isFinite(n) && n > 0 ? n : null;\n'
                                     '}\n'
                                     'function parseStatus(s) {\n'
                                     "  if (typeof s === 'number') return s;\n"
                                     "  const t = String(s || '').toLowerCase();\n"
                                     "  if (t.includes('novo')) return 1;\n"
                                     "  if (t.includes('atribu')) return 2;\n"
                                     "  if (t.includes('planejad')) return 3;\n"
                                     "  if (t.includes('pendent')) return 4;\n"
                                     "  if (t.includes('soluc')) return 5;\n"
                                     "  if (t.includes('fechado') || t.includes('close')) return 6;\n"
                                     '  return Number(s) || 0;\n'
                                     '}\n'
                                     'function keepByTrigger(c) {\n'
                                     '  if ([1,4].includes(c.status_num)) return true;\n'
                                     '  if (![2,3,5,6].includes(c.status_num)) return false;\n'
                                     '  const abertura = new Date(c.data_abertura);\n'
                                     '  const mudanca = new Date(c.data_ultima_mudanca);\n'
                                     '  const aberturaDentro = !isNaN(abertura) && abertura >= corte;\n'
                                     '  const mudancaDentro = !isNaN(mudanca) && mudanca >= corte;\n'
                                     '  return aberturaDentro || mudancaDentro;\n'
                                     '}\n'
                                     'function readableDropdown(detailValue, fallback) {\n'
                                     "  const raw = detailValue ?? fallback ?? '';\n"
                                     "  const text = String(raw || '').trim();\n"
                                     '  return text;\n'
                                     '}\n'
                                     'function userDisplayName(user, fallback) {\n'
                                     "  if (!user || typeof user !== 'object') return String(fallback || '');\n"
                                     "  const full = [user.firstname, user.realname].filter(Boolean).join(' "
                                     "').trim();\n"
                                     "  return full || String(user.name || fallback || '');\n"
                                     '}\n'
                                     'function firstEmail(items) {\n'
                                     "  if (!Array.isArray(items)) return '';\n"
                                     "  const def = items.find(e => e?.is_default === 1 || e?.is_default === '1') || "
                                     'items[0];\n'
                                     "  return String(def?.email || '').trim();\n"
                                     '}\n'
                                     'function linkId(detail, rel) {\n'
                                     '  const link = Array.isArray(detail?.links) ? detail.links.find(l => l.rel === '
                                     'rel) : null;\n'
                                     "  const m = String(link?.href || '').match(/\\/(\\d+)\\/?$/);\n"
                                     '  return m ? Number(m[1]) : null;\n'
                                     '}\n'
                                     '\n'
                                     "const baseUrl = String((typeof process !== 'undefined' && "
                                     'process.env.GLPI_API_URL) || '
                                     "'http://host.docker.internal:9080/apirest.php').replace(/\\/$/, '');\n"
                                     "const appToken = String((typeof process !== 'undefined' && "
                                     "process.env.GLPI_APP_TOKEN) || '');\n"
                                     "const sessionToken = String($('GLPI: Iniciar Sessão').first().json.session_token "
                                     "|| '');\n"
                                     'async function glpi(path) {\n'
                                     '  try {\n'
                                     '    return await helpers.httpRequest({\n'
                                     "      method: 'GET',\n"
                                     '      url: baseUrl + path,\n'
                                     "      headers: {'App-Token': appToken, 'Session-Token': sessionToken, "
                                     "'Content-Type': 'application/json'},\n"
                                     '      json: true\n'
                                     '    });\n'
                                     '  } catch (e) {\n'
                                     '    console.log(`[WF01][LOG] Falha GLPI ${path}: ${e.message}`);\n'
                                     '    return null;\n'
                                     '  }\n'
                                     '}\n'
                                     '\n'
                                     'function configuredChunkSize() {\n'
                                     "  const rawSize = String((typeof process !== 'undefined' && "
                                     "process.env.WF01_GLPI_CHUNK_SIZE) || '10').trim();\n"
                                     '  const parsed = Number(rawSize);\n'
                                     '  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 25) return 10;\n'
                                     '  return parsed;\n'
                                     '}\n'
                                     'function chunked(items, size) {\n'
                                     '  const chunks = [];\n'
                                     '  for (let i = 0; i < items.length; i += size) chunks.push(items.slice(i, i + '
                                     'size));\n'
                                     '  return chunks;\n'
                                     '}\n'
                                     'async function fetchAllSearchTickets() {\n'
                                     '  let offset = 0;\n'
                                     '  const limit = 150;\n'
                                     '  const rawList = [];\n'
                                     '  let hasMore = true;\n'
                                     '  while (hasMore) {\n'
                                     "    const queryStr = '/search/Ticket?range=' + offset + '-' + (offset + limit - 1) +\n"
                                     "      '&criteria[0][field]=12&criteria[0][searchtype]=equals&criteria[0][value]=1' +\n"
                                     "      '&criteria[1][link]=OR&criteria[1][field]=12&criteria[1][searchtype]=equals&criteria[1][value]=2' +\n"
                                     "      '&criteria[2][link]=OR&criteria[2][field]=12&criteria[2][searchtype]=equals&criteria[2][value]=3' +\n"
                                     "      '&criteria[3][link]=OR&criteria[3][field]=12&criteria[3][searchtype]=equals&criteria[3][value]=4' +\n"
                                     "      '&criteria[4][link]=OR&criteria[4][field]=12&criteria[4][searchtype]=equals&criteria[4][value]=5' +\n"
                                     "      '&criteria[5][link]=OR&criteria[5][field]=12&criteria[5][searchtype]=equals&criteria[5][value]=6' +\n"
                                     "      '&forcedisplay[0]=1&forcedisplay[1]=2&forcedisplay[2]=12&forcedisplay[3]=21&forcedisplay[4]=83&forcedisplay[5]=15&forcedisplay[6]=4&forcedisplay[7]=22&forcedisplay[8]=7&forcedisplay[9]=19';\n"
                                     '    const page = await glpi(queryStr);\n'
                                     '    if (!page) {\n'
                                     '      hasMore = false;\n'
                                     '      break;\n'
                                     '    }\n'
                                     '    let pageItems = [];\n'
                                     '    if (Array.isArray(page)) {\n'
                                     '      pageItems = page;\n'
                                     '    } else if (Array.isArray(page.data)) {\n'
                                     '      pageItems = page.data;\n'
                                     "    } else if (page && typeof page === 'object') {\n"
                                     '      const keys = Object.keys(page).filter(k => !isNaN(Number(k)));\n'
                                     '      if (keys.length > 0) {\n'
                                     '        pageItems = keys.map(k => page[k]);\n'
                                     '      }\n'
                                     '    }\n'
                                     '    if (pageItems.length > 0) {\n'
                                     '      rawList.push(...pageItems);\n'
                                     '      offset += limit;\n'
                                     '      if (pageItems.length < limit) {\n'
                                     '        hasMore = false;\n'
                                     '      }\n'
                                     '    } else {\n'
                                     '      hasMore = false;\n'
                                     '    }\n'
                                     '  }\n'
                                     '  return rawList;\n'
                                     '}\n'
                                     '\n'
                                     'let raw = [];\n'
                                     'try {\n'
                                     '  raw = await fetchAllSearchTickets();\n'
                                     '} catch (e) {\n'
                                     "  console.log('[WF01][LOG] Falha ao paginar busca de chamados: ' + e.message);\n"
                                     '  for (const it of $input.all()) {\n'
                                     '    const d = it.json;\n'
                                     '    if (Array.isArray(d?.data)) raw.push(...d.data);\n'
                                     "    else if (d && typeof d === 'object' && (d['2'] || d.id)) raw.push(d);\n"
                                     '  }\n'
                                     '}\n'
                                     '\n'
                                     'async function processTicket(c) {\n'
                                     '  try {\n'
                                     "    const id = Number(c['2'] ?? c.id);\n"
                                     '    if (!Number.isFinite(id) || id <= 0) return null;\n'
                                     '    const [detailRaw, actorsRaw] = await Promise.all([\n'
                                     '      glpi(`/Ticket/${id}?expand_dropdowns=true`),\n'
                                     '      glpi(`/Ticket/${id}/Ticket_User`)\n'
                                     '    ]);\n'
                                     '    const detail = detailRaw || {};\n'
                                     '    const actors = Array.isArray(actorsRaw) ? actorsRaw : [];\n'
                                     '    const requester = actors.find(a => Number(a.type) === 1 && '
                                     'Number(a.users_id) > 0)\n'
                                     '      || actors.find(a => Number(a.users_id) > 0)\n'
                                     '      || null;\n'
                                     "    const solicitanteId = parseId(requester?.users_id) || parseId(c['4']);\n"
                                     '    const [userRaw, emailsRaw] = solicitanteId\n'
                                     '      ? await Promise.all([\n'
                                     '        glpi(`/User/${solicitanteId}`),\n'
                                     '        glpi(`/User/${solicitanteId}/UserEmail`)\n'
                                     '      ])\n'
                                     '      : [null, []];\n'
                                     '    const user = userRaw || null;\n'
                                     '    const emails = Array.isArray(emailsRaw) ? emailsRaw : [];\n'
                                     "    const st = parseStatus(c['12'] ?? detail.status ?? c.status);\n"
                                     "    const tipoServicoId = linkId(detail, 'ITILCategory') || parseId(c['7']);\n"
                                     '    const chamado = {\n'
                                     '      id,\n'
                                     "      titulo: String(detail.name || c['1'] || c.name || ''),\n"
                                     "      descricao: stripHtml(detail.content || c['21'] || c.content || ''),\n"
                                     "      tipo_servico: readableDropdown(detail.itilcategories_id, c['7']),\n"
                                     '      tipo_servico_id: tipoServicoId,\n'
                                     "      localizacao: readableDropdown(detail.locations_id, c['83'] ?? "
                                     'c.locations_id),\n'
                                     "      solicitante: userDisplayName(user, c['4'] ?? detail.users_id_recipient),\n"
                                     '      solicitante_id: solicitanteId,\n'
                                     '      email_solicitante: String(requester?.alternative_email || '
                                     "firstEmail(emails) || '').trim(),\n"
                                     '      status_num: st,\n'
                                     "      status_nome: STATUS_MAP[st] || String(st || ''),\n"
                                     "      data_abertura: detail.date || c['15'] || c.date || null,\n"
                                     "      data_ultima_mudanca: detail.date_mod || c['19'] || c.date_mod || c['15'] "
                                     '|| null\n'
                                     '    };\n'
                                     '    return keepByTrigger(chamado) ? chamado : null;\n'
                                     '  } catch (e) {\n'
                                     '    console.log(`[WF01][LOG] Falha ao estruturar chamado: ${e.message}`);\n'
                                     '    return null;\n'
                                     '  }\n'
                                     '}\n'
                                     '\n'
                                     'const chunkSize = configuredChunkSize();\n'
                                     'const out = [];\n'
                                     'const batches = chunked(raw, chunkSize);\n'
                                     'for (let i = 0; i < batches.length; i++) {\n'
                                     '  const results = await Promise.all(batches[i].map(processTicket));\n'
                                     '  out.push(...results.filter(Boolean));\n'
                                     '}\n'
                                     '\n'
                                     'console.log(`[WF01][LOG] Estruturados ${out.length} chamados | '
                                     'trigger=${trigger} | raw=${raw.length} | chunkSize=${chunkSize} | '
                                     'lotes=${batches.length}`);\n'
                                     'if (out.length === 0) return [{json:{sem_chamados:true, trigger, total:0, '
                                     'chamados:[], raw:raw.length, chunkSize, lotes:batches.length}}];\n'
                                     'return [{json:{chamados:out, trigger, total:out.length, raw:raw.length, '
                                     'chunkSize, lotes:batches.length}}];\n'},
            'type': 'n8n-nodes-base.code',
            'typeVersion': 2,
            'position': [630, 140],
            'id': 'v9-wf01-struct',
            'name': 'Estruturar e Filtrar',
            'alwaysOutputData': True},
           {'parameters': {'conditions': {'options': {'caseSensitive': True,
                                                      'leftValue': '',
                                                      'typeValidation': 'strict',
                                                      'version': 2},
                                          'conditions': [{'leftValue': '={{ Array.isArray($json.chamados) && '
                                                                       '$json.chamados.length > 0 }}',
                                                          'operator': {'type': 'boolean', 'operation': 'true'},
                                                          'id': 'if1'}],
                                          'combinator': 'and'},
                           'options': {}},
            'type': 'n8n-nodes-base.if',
            'typeVersion': 2.2,
            'position': [880, 140],
            'id': 'v9-wf01-has',
            'name': 'Tem Chamados?'},
           {'parameters': {'operation': 'executeQuery',
                           'query': '={{ (() => {\n'
                                    '  const chamados = Array.isArray($json.chamados) ? $json.chamados : [];\n'
                                    '  const esc = s => "\'" + String(s ?? \'\').replace(/\'/g, "\'\'") + "\'";\n'
                                    "  const origem = esc($json.trigger === 'MANUAL' ? 'MANUAL_BOOTSTRAP' : "
                                    "'SCHEDULE_SYNC');\n"
                                    "  const trigger = esc($json.trigger || 'SCHEDULE');\n"
                                    '  const ts = esc(new Date().toISOString());\n'
                                    '  const payload = esc(JSON.stringify(chamados));\n'
                                    '  if (chamados.length === 0) {\n'
                                    '    return `SELECT 0::int AS total, 0::int AS inseridos, 0::int AS '
                                    'atualizados;`;\n'
                                    '  }\n'
                                    '  return `\n'
                                    '  WITH payload_raw AS (\n'
                                    '    SELECT *\n'
                                    '    FROM jsonb_to_recordset(${payload}::jsonb) AS c(\n'
                                    '      id BIGINT,\n'
                                    '      titulo TEXT,\n'
                                    '      descricao TEXT,\n'
                                    '      tipo_servico TEXT,\n'
                                    '      tipo_servico_id BIGINT,\n'
                                    '      localizacao TEXT,\n'
                                    '      solicitante TEXT,\n'
                                    '      solicitante_id BIGINT,\n'
                                    '      email_solicitante TEXT,\n'
                                    '      status_num INTEGER,\n'
                                    '      status_nome TEXT,\n'
                                    '      data_abertura TIMESTAMPTZ,\n'
                                    '      data_ultima_mudanca TIMESTAMPTZ\n'
                                    '    )\n'
                                    '    WHERE id IS NOT NULL\n'
                                    '  ),\n'
                                    '  payload AS (\n'
                                    '    SELECT DISTINCT ON (id) *\n'
                                    '    FROM payload_raw\n'
                                    '    ORDER BY id\n'
                                    '  ),\n'
                                    '  upserted AS (\n'
                                    '    INSERT INTO tickets_processados(\n'
                                    '      '
                                    'id,titulo,descricao,tipo_servico,tipo_servico_id,localizacao,solicitante,solicitante_id,email_solicitante,\n'
                                    '      status_num,status_nome,data_abertura,data_ultima_mudanca,origem_ingestao,\n'
                                    '      triagem_status,ultima_acao_workflow,log_workflow,wf_version\n'
                                    '    )\n'
                                    '    SELECT\n'
                                    '      id,\n'
                                    "      COALESCE(titulo,''),\n"
                                    '      descricao,\n'
                                    '      tipo_servico,\n'
                                    '      tipo_servico_id,\n'
                                    '      localizacao,\n'
                                    '      solicitante,\n'
                                    '      solicitante_id,\n'
                                    '      email_solicitante,\n'
                                    '      COALESCE(status_num,0),\n'
                                    "      COALESCE(status_nome,''),\n"
                                    '      data_abertura,\n'
                                    '      data_ultima_mudanca,\n'
                                    '      ${origem},\n'
                                    "      'PENDENTE_SYNC',\n"
                                    "      'WF01_SYNC',\n"
                                    '      '
                                    "jsonb_build_array(jsonb_build_object('wf','WF01','acao','SYNC','trigger',${trigger},'ts',${ts},'status',COALESCE(status_nome,''))),\n"
                                    "      'v9'\n"
                                    '    FROM payload\n'
                                    '    ON CONFLICT(id) DO UPDATE SET\n'
                                    '      titulo=EXCLUDED.titulo,\n'
                                    '      descricao=EXCLUDED.descricao,\n'
                                    '      tipo_servico=EXCLUDED.tipo_servico,\n'
                                    '      tipo_servico_id=EXCLUDED.tipo_servico_id,\n'
                                    '      localizacao=EXCLUDED.localizacao,\n'
                                    '      solicitante=EXCLUDED.solicitante,\n'
                                    '      solicitante_id=EXCLUDED.solicitante_id,\n'
                                    '      email_solicitante=EXCLUDED.email_solicitante,\n'
                                    '      status_num=EXCLUDED.status_num,\n'
                                    '      status_nome=EXCLUDED.status_nome,\n'
                                    '      '
                                    'data_abertura=COALESCE(EXCLUDED.data_abertura,tickets_processados.data_abertura),\n'
                                    '      data_ultima_mudanca=CASE\n'
                                    '        WHEN EXCLUDED.data_ultima_mudanca IS NULL THEN '
                                    'tickets_processados.data_ultima_mudanca\n'
                                    '        WHEN tickets_processados.data_ultima_mudanca IS NULL THEN '
                                    'EXCLUDED.data_ultima_mudanca\n'
                                    '        ELSE GREATEST(tickets_processados.data_ultima_mudanca, '
                                    'EXCLUDED.data_ultima_mudanca)\n'
                                    '      END,\n'
                                    '      origem_ingestao=EXCLUDED.origem_ingestao,\n'
                                    "      ultima_acao_workflow='WF01_SYNC',\n"
                                    "      log_workflow=COALESCE(tickets_processados.log_workflow,'[]'::jsonb)\n"
                                    '        || '
                                    "jsonb_build_object('wf','WF01','acao','SYNC','trigger',${trigger},'ts',${ts},'status',EXCLUDED.status_nome)\n"
                                    '    RETURNING id,status_num,status_nome,triagem_status,em_aprovacao_fiscal,(xmax '
                                    '= 0) AS inserido\n'
                                    '  )\n'
                                    '  SELECT\n'
                                    '    COUNT(*)::int AS total,\n'
                                    '    COUNT(*) FILTER (WHERE inserido)::int AS inseridos,\n'
                                    '    COUNT(*) FILTER (WHERE NOT inserido)::int AS atualizados\n'
                                    '  FROM upserted;`;\n'
                                    '})() }}',
                           'options': {}},
            'type': 'n8n-nodes-base.postgres',
            'typeVersion': 2.5,
            'position': [1140, 20],
            'id': 'v9-wf01-upsert',
            'name': 'PG: UPSERT Chamado',
            'credentials': {'postgres': {'id': 'PG_TRIAGEM', 'name': 'Postgres Triagem'}},
            'alwaysOutputData': True},
           {'parameters': {'jsCode': 'const r=$input.first().json||{}; const total=Number(r.total||0); const '
                                     'inseridos=Number(r.inseridos||0); const atualizados=Number(r.atualizados||0); '
                                     "console.log('[WF01][LOG] UPSERT em lote concluido: '+total+' chamados | "
                                     "inseridos='+inseridos+' atualizados='+atualizados); return "
                                     '[{json:{ok:true,total,inseridos,atualizados}}];'},
            'type': 'n8n-nodes-base.code',
            'typeVersion': 2,
            'position': [1400, 20],
            'id': 'v9-wf01-resumo',
            'name': 'LOG: Resumo Sync',
            'alwaysOutputData': True},
           {'parameters': {'url': "={{ ($env.GLPI_API_URL || 'http://host.docker.internal:9080/apirest.php') + "
                                  "'/killSession' }}",
                           'options': {},
                           'sendHeaders': True,
                           'headerParameters': {'parameters': [{'name': 'App-Token',
                                                                'value': '={{ $env.GLPI_APP_TOKEN || '
                                                                         "'' }}"},
                                                               {'name': 'Session-Token',
                                                                'value': "={{ $('GLPI: Iniciar "
                                                                         "Sessão').first().json.session_token }}"}]}},
            'type': 'n8n-nodes-base.httpRequest',
            'typeVersion': 4.2,
            'position': [1660, 140],
            'id': 'v9-wf01-gk',
            'name': 'GLPI: Encerrar Sessão',
            'typeOptions': {'timeoutMilliseconds': 15000},
            'alwaysOutputData': True,
            'onError': 'continueRegularOutput'},
           {'parameters': {'jsCode': "console.log('[WF01][LOG] Fim sincronizador V9'); return [{json:{ok:true,ts:new "
                                     'Date().toISOString()}}];'},
            'type': 'n8n-nodes-base.code',
            'typeVersion': 2,
            'position': [1920, 140],
            'id': 'v9-wf01-fim',
            'name': 'LOG: Fim',
            'alwaysOutputData': True}],
 'pinData': {},
 'connections': {'T1. Manual': {'main': [[{'node': 'LOG: Início', 'type': 'main', 'index': 0}]]},
                 'T2. Schedule 06h/12h': {'main': [[{'node': 'LOG: Início', 'type': 'main', 'index': 0}]]},
                 'LOG: Início': {'main': [[{'node': 'PG: Garantir Schema', 'type': 'main', 'index': 0}]]},
                 'PG: Garantir Schema': {'main': [[{'node': 'PG: Retenção 90 dias', 'type': 'main', 'index': 0}]]},
                 'PG: Retenção 90 dias': {'main': [[{'node': 'LOG: Retenção 90 dias', 'type': 'main', 'index': 0}]]},
                 'LOG: Retenção 90 dias': {'main': [[{'node': 'GLPI: Iniciar Sessão', 'type': 'main', 'index': 0}]]},
                 'GLPI: Iniciar Sessão': {'main': [[{'node': 'GLPI: Buscar Chamados', 'type': 'main', 'index': 0}]]},
                 'GLPI: Buscar Chamados': {'main': [[{'node': 'Estruturar e Filtrar', 'type': 'main', 'index': 0}]]},
                 'Estruturar e Filtrar': {'main': [[{'node': 'Tem Chamados?', 'type': 'main', 'index': 0}]]},
                 'Tem Chamados?': {'main': [[{'node': 'PG: UPSERT Chamado', 'type': 'main', 'index': 0}],
                                            [{'node': 'GLPI: Encerrar Sessão', 'type': 'main', 'index': 0}]]},
                 'PG: UPSERT Chamado': {'main': [[{'node': 'LOG: Resumo Sync', 'type': 'main', 'index': 0}]]},
                 'LOG: Resumo Sync': {'main': [[{'node': 'GLPI: Encerrar Sessão', 'type': 'main', 'index': 0}]]},
                 'GLPI: Encerrar Sessão': {'main': [[{'node': 'LOG: Fim', 'type': 'main', 'index': 0}]]}},
 'active': True,
 'settings': {'executionOrder': 'v1',
              'timezone': 'America/Sao_Paulo',
              'saveExecutionProgress': True,
              'saveManualExecutions': True},
 'versionId': 'v9-V9 - WF01 ',
 'meta': {},
 'tags': [],
 'id': 'BCrENoTzdW20owz4'}


WF01_STRUCTURAR_JS = r"""
const STATUS_MAP = {1:'Novo',2:'Em atendimento',3:'Planejado',4:'Pendente',5:'Solucionado',6:'Fechado'};
const corte = new Date(Date.now() - 90 * 24 * 60 * 60 * 1000);
let trigger = 'SCHEDULE';
try {
  if ($('T1. Manual').first().json) trigger = 'MANUAL';
} catch(e) {}
function stripHtml(value) {
  return String(value || '')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')
    .trim();
}
function parseId(value) {
  if (value === null || value === undefined) return null;
  if (typeof value === 'number') return Number.isFinite(value) && value > 0 ? value : null;
  const match = String(value).match(/\d+/);
  return match ? Number(match[0]) : null;
}
function parseStatus(value) {
  if (typeof value === 'number') return value;
  const text = String(value || '').trim();
  if (/^\d+$/.test(text)) return Number(text);
  const n = text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  if (n.includes('novo')) return 1;
  if (n.includes('atendimento')) return 2;
  if (n.includes('planejado')) return 3;
  if (n.includes('pendente')) return 4;
  if (n.includes('solucionado')) return 5;
  if (n.includes('fechado')) return 6;
  return 0;
}
function keepByTrigger(c) {
  if ([1,4].includes(c.status_num)) return true;
  if (![2,3,5,6].includes(c.status_num)) return false;
  const abertura = new Date(c.data_abertura);
  const mudanca = new Date(c.data_ultima_mudanca);
  const aberturaDentro = !isNaN(abertura) && abertura >= corte;
  const mudancaDentro = !isNaN(mudanca) && mudanca >= corte;
  return aberturaDentro || mudancaDentro;
}
function readableDropdown(detailValue, fallback) {
  return String(detailValue ?? fallback ?? '').trim();
}
function userDisplayName(user, fallback) {
  if (!user || typeof user !== 'object') return String(fallback || '');
  const full = [user.firstname, user.realname].filter(Boolean).join(' ').trim();
  return full || String(user.name || fallback || '');
}
function firstEmail(items) {
  if (!Array.isArray(items)) return '';
  const def = items.find(e => e?.is_default === 1 || e?.is_default === '1') || items[0];
  return String(def?.email || '').trim();
}
function linkId(detail, rel) {
  const link = Array.isArray(detail?.links) ? detail.links.find(l => l.rel === rel) : null;
  const m = String(link?.href || '').match(/\/(\d+)\/?$/);
  return m ? Number(m[1]) : null;
}
function collectSearchRows() {
  const rows = [];
  for (const it of $input.all()) {
    const d = it.json;
    if (Array.isArray(d)) {
      rows.push(...d);
    } else if (Array.isArray(d?.data)) {
      rows.push(...d.data);
    } else if (d && typeof d === 'object') {
      const numericKeys = Object.keys(d).filter(k => /^\d+$/.test(k) && d[k] && typeof d[k] === 'object');
      if (numericKeys.length > 0) rows.push(...numericKeys.map(k => d[k]));
      else if (d['2'] || d.id) rows.push(d);
    }
  }
  return rows;
}
const baseUrl = String((typeof process !== 'undefined' && process.env.GLPI_API_URL) || 'http://host.docker.internal:9080/apirest.php').replace(/\/$/, '');
const appToken = String((typeof process !== 'undefined' && process.env.GLPI_APP_TOKEN) || '');
const sessionToken = String($('GLPI: Iniciar Sessão').first().json.session_token || '');
async function glpi(path) {
  try {
    return await helpers.httpRequest({
      method: 'GET',
      url: baseUrl + path,
      headers: {'App-Token': appToken, 'Session-Token': sessionToken, 'Content-Type': 'application/json'},
      json: true
    });
  } catch (e) {
    console.log(`[WF01][LOG] Falha GLPI ${path}: ${e.message}`);
    return null;
  }
}
function configuredChunkSize() {
  const rawSize = String((typeof process !== 'undefined' && process.env.WF01_GLPI_CHUNK_SIZE) || '10').trim();
  const parsed = Number(rawSize);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 25) return 10;
  return parsed;
}
function chunked(items, size) {
  const chunks = [];
  for (let i = 0; i < items.length; i += size) chunks.push(items.slice(i, i + size));
  return chunks;
}
async function processTicket(c) {
  try {
    const id = Number(c['2'] ?? c.id);
    if (!Number.isFinite(id) || id <= 0) return null;
    const [detailRaw, actorsRaw] = await Promise.all([
      glpi(`/Ticket/${id}?expand_dropdowns=true`),
      glpi(`/Ticket/${id}/Ticket_User`)
    ]);
    const detail = detailRaw || {};
    const actors = Array.isArray(actorsRaw) ? actorsRaw : [];
    const requester = actors.find(a => Number(a.type) === 1 && Number(a.users_id) > 0)
      || actors.find(a => Number(a.users_id) > 0)
      || null;
    const solicitanteId = parseId(requester?.users_id) || parseId(c['4']);
    const [userRaw, emailsRaw] = solicitanteId
      ? await Promise.all([
        glpi(`/User/${solicitanteId}`),
        glpi(`/User/${solicitanteId}/UserEmail`)
      ])
      : [null, []];
    const st = parseStatus(detail.status ?? c['12'] ?? c.status);
    const tipoServicoId = linkId(detail, 'ITILCategory') || parseId(c['7']);
    const chamado = {
      id,
      titulo: String(detail.name || c['1'] || c.name || ''),
      descricao: stripHtml(detail.content || c['21'] || c.content || ''),
      tipo_servico: readableDropdown(detail.itilcategories_id, c['7']),
      tipo_servico_id: tipoServicoId,
      localizacao: readableDropdown(detail.locations_id, c['83'] ?? c.locations_id),
      solicitante: userDisplayName(userRaw || null, c['4'] ?? detail.users_id_recipient),
      solicitante_id: solicitanteId,
      email_solicitante: String(requester?.alternative_email || firstEmail(Array.isArray(emailsRaw) ? emailsRaw : []) || '').trim(),
      status_num: st,
      status_nome: STATUS_MAP[st] || String(st || ''),
      data_abertura: detail.date || c['15'] || c.date || null,
      data_ultima_mudanca: detail.date_mod || c['19'] || c.date_mod || c['15'] || null
    };
    return keepByTrigger(chamado) ? chamado : null;
  } catch (e) {
    console.log(`[WF01][LOG] Falha ao estruturar chamado: ${e.message}`);
    return null;
  }
}
const raw = collectSearchRows();
const chunkSize = configuredChunkSize();
const out = [];
const batches = chunked(raw, chunkSize);
for (let i = 0; i < batches.length; i++) {
  const results = await Promise.all(batches[i].map(processTicket));
  out.push(...results.filter(Boolean));
}
console.log(`[WF01][LOG] Estruturados ${out.length} chamados usando saida do GLPI: Buscar Chamados | trigger=${trigger} | raw=${raw.length} | chunkSize=${chunkSize} | lotes=${batches.length}`);
if (out.length === 0) return [{json:{sem_chamados:true, trigger, total:0, chamados:[], raw:raw.length, chunkSize, lotes:batches.length}}];
return [{json:{chamados:out, trigger, total:out.length, raw:raw.length, chunkSize, lotes:batches.length}}];
"""


WF01_OBSERVABILITY_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS ia_decisoes (
  id BIGSERIAL PRIMARY KEY,
  ticket_id BIGINT,
  workflow_origem TEXT NOT NULL,
  etapa TEXT NOT NULL,
  modelo_ia TEXT DEFAULT 'Gemini',
  versao_modelo TEXT,
  prompt_version TEXT,
  input_hash TEXT,
  input_resumo JSONB,
  output_raw JSONB,
  output_normalizado JSONB,
  predicao TEXT,
  classe_referencia_id BIGINT,
  confianca NUMERIC(5,4),
  justificativa TEXT,
  tempo_resposta_ms INTEGER,
  tentativa_numero INTEGER,
  erro_ia BOOLEAN DEFAULT FALSE,
  mensagem_erro TEXT,
  criado_em TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ia_decisoes_ticket ON ia_decisoes(ticket_id);
CREATE INDEX IF NOT EXISTS idx_ia_decisoes_etapa ON ia_decisoes(etapa);
CREATE INDEX IF NOT EXISTS idx_ia_decisoes_prompt ON ia_decisoes(prompt_version);
CREATE INDEX IF NOT EXISTS idx_ia_decisoes_criado ON ia_decisoes(criado_em);

CREATE TABLE IF NOT EXISTS workflow_eventos (
  id BIGSERIAL PRIMARY KEY,
  ticket_id BIGINT,
  workflow TEXT NOT NULL,
  node_name TEXT,
  fase TEXT,
  acao TEXT,
  status_evento TEXT,
  status_anterior TEXT,
  status_novo TEXT,
  erro BOOLEAN DEFAULT FALSE,
  mensagem_erro TEXT,
  execution_id TEXT,
  inicio_em TIMESTAMPTZ,
  fim_em TIMESTAMPTZ,
  duracao_ms INTEGER,
  criado_em TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_workflow_eventos_ticket ON workflow_eventos(ticket_id);
CREATE INDEX IF NOT EXISTS idx_workflow_eventos_workflow ON workflow_eventos(workflow);
CREATE INDEX IF NOT EXISTS idx_workflow_eventos_criado ON workflow_eventos(criado_em);
"""


def _node(name: str) -> dict:
    for node in WORKFLOW["nodes"]:
        if node.get("name") == name:
            return node
    raise KeyError(f"Nó não encontrado: {name}")


def _ensure_node(node: dict) -> None:
    if not any(existing.get("name") == node.get("name") for existing in WORKFLOW["nodes"]):
        WORKFLOW["nodes"].append(node)


def _connect_parallel(source: str, target: str) -> None:
    outputs = WORKFLOW["connections"].setdefault(source, {"main": [[]]})["main"]
    if not outputs:
        outputs.append([])
    first_output = outputs[0]
    if not any(conn.get("node") == target for conn in first_output):
        first_output.append({"node": target, "type": "main", "index": 0})


def _apply_section7_updates() -> None:
    schema_node = _node("PG: Garantir Schema")
    query = schema_node["parameters"]["query"]
    marker = "SELECT 'schema_ok' AS result;"
    if "CREATE TABLE IF NOT EXISTS ia_decisoes" not in query:
        schema_node["parameters"]["query"] = query.replace(marker, WF01_OBSERVABILITY_SCHEMA_SQL + "\n" + marker)

    _node("Estruturar e Filtrar")["parameters"]["jsCode"] = WF01_STRUCTURAR_JS
    _ensure_node(
        {
            "parameters": {
                "jsCode": "const token = String($json.session_token || '').trim(); if (!token) { throw new Error('GLPI initSession nao retornou session_token no WF01'); } return [{json:{...$json,session_token:token}}];"
            },
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [320, 140],
            "id": "v9-wf01-validar-sessao",
            "name": "Validar Sessão GLPI",
            "alwaysOutputData": True,
        }
    )
    WORKFLOW["connections"]["GLPI: Iniciar Sessão"] = {
        "main": [[{"node": "Validar Sessão GLPI", "type": "main", "index": 0}]]
    }
    WORKFLOW["connections"]["Validar Sessão GLPI"] = {
        "main": [[{"node": "GLPI: Buscar Chamados", "type": "main", "index": 0}]]
    }
    _ensure_node(
        {
            "parameters": {
                "operation": "executeQuery",
                "query": """
SELECT
  COALESCE(jsonb_agg(jsonb_build_object('id', id, 'ticket_id', id, 'event', 'ticket.add', 'source', 'wf01-sync') ORDER BY id), '[]'::jsonb) AS tickets,
  COUNT(*)::int AS total_pendentes
FROM tickets_processados
WHERE status_num = 1
  AND triagem_status = 'PENDENTE_SYNC'
  AND COALESCE(em_aprovacao_fiscal, FALSE) = FALSE;
""",
                "options": {},
            },
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.5,
            "position": [1400, 260],
            "id": "v9-wf01-pendentes-wf02",
            "name": "PG: Pendentes WF02",
            "credentials": {"postgres": {"id": "PG_TRIAGEM", "name": "Postgres Triagem"}},
            "alwaysOutputData": True,
        }
    )
    _ensure_node(
        {
            "parameters": {
                "jsCode": "const r=$input.first().json||{}; const tickets=Array.isArray(r.tickets)?r.tickets:[]; const total=Number(r.total_pendentes||tickets.length||0); console.log('[WF01][LOG] Pendentes para WF02: '+total); return [{json:{tickets,total_pendentes:total}}];"
            },
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1660, 260],
            "id": "v9-wf01-preparar-wf02",
            "name": "Preparar WF02 Sync",
            "alwaysOutputData": True,
        }
    )
    _ensure_node(
        {
            "parameters": {
                "conditions": {
                    "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                    "conditions": [
                        {
                            "leftValue": "={{ Number($json.total_pendentes || 0) > 0 }}",
                            "operator": {"type": "boolean", "operation": "true"},
                            "id": "if1",
                        }
                    ],
                    "combinator": "and",
                },
                "options": {},
            },
            "type": "n8n-nodes-base.if",
            "typeVersion": 2.2,
            "position": [1920, 260],
            "id": "v9-wf01-tem-pendentes-wf02",
            "name": "Tem Pendentes WF02?",
        }
    )
    _ensure_node(
        {
            "parameters": {
                "jsCode": "const tickets = Array.isArray($json.tickets) ? $json.tickets : []; return tickets.map(t => ({json:{...t, chamado:{id:Number(t.id || t.ticket_id), status_num:1, status_nome:'Novo', source:'wf01-sync-test', evento:'ticket.add', evento_criacao:true}}}));"
            },
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [2180, 180],
            "id": "v9-wf01-expandir-wf02",
            "name": "Expandir WF02 Sync",
            "alwaysOutputData": True,
        }
    )
    _ensure_node(
        {
            "parameters": {
                "workflowId": {"__rl": True, "mode": "id", "value": "nmNEsgC8kXmCVOsX"},
                "workflowInputs": {
                    "mappingMode": "defineBelow",
                    "value": {
                        "id": "={{ $json.id }}",
                        "ticket_id": "={{ $json.ticket_id }}",
                        "event": "={{ $json.event }}",
                        "source": "={{ $json.source }}",
                        "chamado": "={{ $json.chamado }}",
                    },
                    "matchingColumns": [],
                    "schema": [],
                    "attemptToConvertTypes": False,
                    "convertFieldsToString": True,
                },
                "mode": "each",
                "options": {"waitForSubWorkflow": False},
            },
            "type": "n8n-nodes-base.executeWorkflow",
            "typeVersion": 1.2,
            "position": [2440, 180],
            "id": "v9-wf01-chamar-wf02-sync",
            "name": "Chamar WF02 Sync",
        }
    )
    # _connect_parallel("PG: UPSERT Chamado", "PG: Pendentes WF02")
    WORKFLOW["connections"]["PG: Pendentes WF02"] = {
        "main": [[{"node": "Preparar WF02 Sync", "type": "main", "index": 0}]]
    }
    WORKFLOW["connections"]["Preparar WF02 Sync"] = {
        "main": [[{"node": "Tem Pendentes WF02?", "type": "main", "index": 0}]]
    }
    WORKFLOW["connections"]["Tem Pendentes WF02?"] = {
        "main": [[{"node": "Expandir WF02 Sync", "type": "main", "index": 0}], []]
    }
    WORKFLOW["connections"]["Expandir WF02 Sync"] = {
        "main": [[{"node": "Chamar WF02 Sync", "type": "main", "index": 0}]]
    }


_apply_section7_updates()


def _apply_queue_ingress_updates() -> None:
    """Mantém o WF01 como recuperação de ingestão e envia todo caso novo à fila."""
    schema_path = DIR.parents[2] / "database" / "init_v9.sql"
    _node("PG: Garantir Schema")["parameters"]["query"] = (
        schema_path.read_text(encoding="utf-8") + "\nSELECT 'schema_ok' AS result;"
    )

    obsolete = {
        "PG: Pendentes WF02",
        "Preparar WF02 Sync",
        "Tem Pendentes WF02?",
        "Expandir WF02 Sync",
        "Chamar WF02 Sync",
    }
    WORKFLOW["nodes"] = [
        node for node in WORKFLOW["nodes"] if node.get("name") not in obsolete
    ]
    for source in obsolete:
        WORKFLOW["connections"].pop(source, None)
    for source, outputs in list(WORKFLOW["connections"].items()):
        for branch in outputs.get("main", []):
            branch[:] = [edge for edge in branch if edge.get("node") not in obsolete]

    _ensure_node(
        {
            "parameters": {
                "operation": "executeQuery",
                "query": """
UPDATE tickets_processados
SET triagem_status='PENDENTE_FILA_IA',
    fila_etapa='DEDUPLICACAO',
    fila_enfileirada_em=COALESCE(fila_enfileirada_em,NOW()),
    fila_liberar_em=NULL,
    fila_reservada_em=NULL,
    fila_ultimo_erro=NULL,
    ultima_acao_workflow='WF01_RECUPEROU_PARA_FILA',
    log_workflow=COALESCE(log_workflow,'[]'::jsonb)
      || jsonb_build_object(
           'wf','WF01','acao','RECUPERAR_PARA_FILA','ts',NOW()
         ),
    atualizado_em=NOW()
WHERE status_num=1
  AND triagem_status='PENDENTE_SYNC'
  AND COALESCE(em_aprovacao_fiscal,FALSE)=FALSE
RETURNING id,triagem_status,fila_enfileirada_em;
""",
                "options": {},
            },
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.5,
            "position": [1640, 20],
            "id": "v9-wf01-enfileirar-wf06",
            "name": "PG: Enfileirar Pendentes WF06",
            "credentials": {
                "postgres": {"id": "PG_TRIAGEM", "name": "Postgres Triagem"}
            },
            "alwaysOutputData": True,
        }
    )
    WORKFLOW["connections"]["LOG: Resumo Sync"] = {
        "main": [
            [
                {
                    "node": "PG: Enfileirar Pendentes WF06",
                    "type": "main",
                    "index": 0,
                }
            ]
        ]
    }
    WORKFLOW["connections"]["PG: Enfileirar Pendentes WF06"] = {
        "main": [[{"node": "GLPI: Encerrar Sessão", "type": "main", "index": 0}]]
    }


_apply_queue_ingress_updates()


def main() -> None:
    sanitize_workflow_secrets(WORKFLOW)
    if WORKFLOW.get("name") != EXPECTED_NAME:
        raise ValueError(f"Workflow inesperado: {WORKFLOW.get('name')!r}; esperado {EXPECTED_NAME!r}")
    rendered = json.dumps(WORKFLOW, ensure_ascii=False, indent=2) + "\n"
    rendered_sha = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    if rendered_sha != SNAPSHOT_SHA256:
        raise ValueError(
            "Snapshot Python divergiu do hash registrado. "
            f"Atualize SNAPSHOT_SHA256 apos uma alteracao intencional: {rendered_sha}"
        )
    for output in OUTPUT_FILES:
        path = DIR / output
        path.write_text(rendered, encoding="utf-8", newline="\n")
        print(f"Salvo: {path}")


if __name__ == "__main__":
    main()
