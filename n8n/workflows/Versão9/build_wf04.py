"""Gera V9-WF04-Decisao-Fiscal.json a partir do snapshot Python do JSON final V9.

Este arquivo foi regenerado a partir de V9-WF04-Decisao-Fiscal.json. A estrutura WORKFLOW abaixo
mantem a logica, posicoes, parametros e conexoes do workflow exportado pelo n8n.
Edite este builder nas proximas alteracoes e execute-o para recriar os JSONs.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from helpers import sanitize_workflow_secrets


DIR = Path(__file__).resolve().parent
EXPECTED_NAME = 'V9 - WF04 Decisão Fiscal'
SNAPSHOT_SHA256 = 'c2a69976913cd11f3ab0d33c91aed7a29b28335ca49a6de42c60b89c766993a3'
OUTPUT_FILES = ['V9-WF04-Decisao-Fiscal.json']

WORKFLOW = {'name': 'V9 - WF04 Decisão Fiscal',
 'nodes': [{'parameters': {'path': 'fiscal-decisao-fiscal-ic-2026', 'responseMode': 'responseNode', 'options': {}},
            'type': 'n8n-nodes-base.webhook',
            'typeVersion': 2,
            'position': [-1168, 0],
            'id': 'v9-wf04-wh',
            'name': 'Webhook Fiscal',
            'webhookId': 'v9-wf04-wh'},
           {'parameters': {'jsCode': '\n'
                                     'const q = $json.query || {};\n'
                                     "const dec = String(q.decisao ?? '').toLowerCase().trim();\n"
                                     'const cid = Number(q.chamado_id);\n'
                                     'const rid = Number(q.ref_id || 0);\n'
                                     "const token = String(q.token || '').trim();\n"
                                     'const temChamado = Number.isFinite(cid) && cid > 0;\n'
                                     "const decisaoValida = ['confirmar','nao_duplicado'].includes(dec);\n"
                                     'const tokenValidoFormato = /^[a-f0-9]{32,128}$/i.test(token);\n'
                                     'const ok = temChamado && decisaoValida && tokenValidoFormato;\n'
                                     "let motivo_invalidade = '';\n"
                                     "if (!temChamado) motivo_invalidade = 'chamado_id ausente ou invalido';\n"
                                     "else if (!decisaoValida) motivo_invalidade = 'decisao ausente ou invalida: ' + "
                                     "(dec || 'vazia');\n"
                                     "else if (!tokenValidoFormato) motivo_invalidade = 'token fiscal ausente ou "
                                     "invalido';\n"
                                     "console.log('[WF04][LOG] Webhook fiscal decisao=' + dec + ' chamado=' + cid + ' "
                                     "ok=' + ok + ' motivo=' + motivo_invalidade);\n"
                                     'return '
                                     '[{json:{ok,decisao:dec,chamado_id:temChamado?cid:null,ref_id:rid>0?rid:null,token:tokenValidoFormato?token:null,motivo_invalidade}}];\n'},
            'type': 'n8n-nodes-base.code',
            'typeVersion': 2,
            'position': [-912, 0],
            'id': 'v9-wf04-fext',
            'name': 'Extrair Decisão',
            'alwaysOutputData': True},
           {'parameters': {'conditions': {'options': {'caseSensitive': True,
                                                      'leftValue': '',
                                                      'typeValidation': 'strict',
                                                      'version': 2},
                                          'conditions': [{'leftValue': '={{ $json.ok }}',
                                                          'operator': {'type': 'boolean', 'operation': 'true'},
                                                          'id': 'if1'}],
                                          'combinator': 'and'},
                           'options': {}},
            'type': 'n8n-nodes-base.if',
            'typeVersion': 2.2,
            'position': [-656, 0],
            'id': 'v9-wf04-fchk',
            'name': 'Link Válido?'},
           {'parameters': {'conditions': {'options': {'caseSensitive': True,
                                                      'leftValue': '',
                                                      'typeValidation': 'strict',
                                                      'version': 2},
                                          'conditions': [{'leftValue': '={{ $json.chamado_id !== null }}',
                                                          'operator': {'type': 'boolean', 'operation': 'true'},
                                                          'id': 'if1'}],
                                          'combinator': 'and'},
                           'options': {}},
            'type': 'n8n-nodes-base.if',
            'typeVersion': 2.2,
            'position': [-512, 208],
            'id': 'v9-wf04-has-id',
            'name': 'Tem Chamado no Link?'},
           {'parameters': {'url': "={{ ($env.GLPI_API_URL || 'http://host.docker.internal:9080/apirest.php') + "
                                  "'/initSession' }}",
                           'sendHeaders': True,
                           'headerParameters': {'parameters': [{'name': 'App-Token',
                                                                'value': '={{ $env.GLPI_APP_TOKEN || '
                                                                         "'' }}"},
                                                               {'name': 'Authorization',
                                                                'value': "={{ $env.GLPI_AUTH_BASIC || 'Basic "
                                                                         "' }}"}]},
                           'options': {}},
            'type': 'n8n-nodes-base.httpRequest',
            'typeVersion': 4.2,
            'position': [-320, 96],
            'id': 'v9-wf04-bad-gs',
            'name': 'GLPI: Sessão Link Inválido',
            'typeOptions': {'timeoutMilliseconds': 15000},
            'alwaysOutputData': True},
           {'parameters': {'method': 'POST',
                           'url': "={{ ($env.GLPI_API_URL || 'http://host.docker.internal:9080/apirest.php') + "
                                  "'/ITILFollowup' }}",
                           'sendHeaders': True,
                           'headerParameters': {'parameters': [{'name': 'App-Token',
                                                                'value': '={{ $env.GLPI_APP_TOKEN || '
                                                                         "'' }}"},
                                                               {'name': 'Session-Token',
                                                                'value': "={{ $('GLPI: Sessão Link "
                                                                         "Inválido').first().json.session_token }}"}]},
                           'sendBody': True,
                           'specifyBody': 'json',
                           'jsonBody': {'input': {'items_id': "={{  $('Extrair Decisão').first().json.chamado_id }}",
                                                  'itemtype': 'Ticket',
                                                  'content': "={{'[TRIAGEM_IA][ERRO_AUTOMACAO] O link de decisao "
                                                             'fiscal gerado pela automacao foi acionado, mas nao pode '
                                                             "ser processado. Motivo tecnico: '+$('Extrair "
                                                             "Decisão').first().json.motivo_invalidade+'. A demanda "
                                                             'deve ser revisada pela equipe responsavel pela '
                                                             'automacao; o fiscal nao precisa repetir a acao ate a '
                                                             "correcao.'}}"}},
                           'options': {}},
            'type': 'n8n-nodes-base.httpRequest',
            'typeVersion': 4.2,
            'position': [-96, 96],
            'id': 'v9-wf04-bad-fu',
            'name': 'GLPI: Anotar Link Inválido',
            'typeOptions': {'timeoutMilliseconds': 15000},
            'alwaysOutputData': True,
            'onError': 'continueRegularOutput'},
           {'parameters': {'respondWith': 'text',
                           'responseBody': 'Falha de automacao registrada no chamado para tratamento interno.',
                           'options': {'responseCode': 202,
                                       'responseHeaders': {'entries': [{'name': 'Content-Type',
                                                                        'value': 'text/plain; charset=utf-8'}]}}},
            'type': 'n8n-nodes-base.respondToWebhook',
            'typeVersion': 1.5,
            'position': [128, 96],
            'id': 'v9-wf04-bad-resp',
            'name': 'Resp: Falha Anotada'},
           {'parameters': {'url': "={{ ($env.GLPI_API_URL || 'http://host.docker.internal:9080/apirest.php') + "
                                  "'/killSession' }}",
                           'sendHeaders': True,
                           'headerParameters': {'parameters': [{'name': 'App-Token',
                                                                'value': '={{ $env.GLPI_APP_TOKEN || '
                                                                         "'' }}"},
                                                               {'name': 'Session-Token',
                                                                'value': "={{ $('GLPI: Sessão Link "
                                                                         "Inválido').first().json.session_token }}"}]},
                           'options': {}},
            'type': 'n8n-nodes-base.httpRequest',
            'typeVersion': 4.2,
            'position': [336, 96],
            'id': 'v9-wf04-bad-gk',
            'name': 'GLPI: Encerrar Sessão Link Inválido',
            'typeOptions': {'timeoutMilliseconds': 15000},
            'alwaysOutputData': True,
            'onError': 'continueRegularOutput'},
           {'parameters': {'jsCode': "console.log('[WF04][LOG] Link fiscal invalido anotado no GLPI'); return "
                                     '[{json:{ok:false,anotado:true}}];'},
            'type': 'n8n-nodes-base.code',
            'typeVersion': 2,
            'position': [560, 96],
            'id': 'v9-wf04-bad-log',
            'name': 'LOG: Link Inválido Anotado',
            'alwaysOutputData': True},
           {'parameters': {'jsCode': "console.log('[WF04][LOG] Link fiscal invalido sem chamado_id; nao ha ticket para "
                                     "anotar'); return "
                                     '[{json:{ok:false,anotado:false,motivo:$json.motivo_invalidade}}];'},
            'type': 'n8n-nodes-base.code',
            'typeVersion': 2,
            'position': [-320, 320],
            'id': 'v9-wf04-noid-log',
            'name': 'LOG: Link Sem Chamado',
            'alwaysOutputData': True},
           {'parameters': {'respondWith': 'text',
                           'responseBody': 'Falha de automacao registrada nos logs internos; nenhum chamado foi '
                                           'identificado no link.',
                           'options': {'responseCode': 202,
                                       'responseHeaders': {'entries': [{'name': 'Content-Type',
                                                                        'value': 'text/plain; charset=utf-8'}]}}},
            'type': 'n8n-nodes-base.respondToWebhook',
            'typeVersion': 1.5,
            'position': [-96, 320],
            'id': 'v9-wf04-noid-resp',
            'name': 'Resp: Falha Sem Chamado'},
           {'parameters': {'url': "={{ ($env.GLPI_API_URL || 'http://host.docker.internal:9080/apirest.php') + "
                                  "'/initSession' }}",
                           'sendHeaders': True,
                           'headerParameters': {'parameters': [{'name': 'App-Token',
                                                                'value': '={{ $env.GLPI_APP_TOKEN || '
                                                                         "'' }}"},
                                                               {'name': 'Authorization',
                                                                'value': "={{ $env.GLPI_AUTH_BASIC || 'Basic "
                                                                         "' }}"}]},
                           'options': {}},
            'type': 'n8n-nodes-base.httpRequest',
            'typeVersion': 4.2,
            'position': [-336, -112],
            'id': 'v9-wf04-fgs',
            'name': 'GLPI: Sessão Fiscal',
            'typeOptions': {'timeoutMilliseconds': 15000},
            'alwaysOutputData': True},
           {'parameters': {'operation': 'executeQuery',
                           'query': "{{ (()=>{ const d=$('Extrair Decisão').first().json; const "
                                    "id=Number(d.chamado_id); const dec=String(d.decisao||'').toLowerCase(); const "
                                    'token=String(d.token||\'\').replace(/\'/g,"\'\'"); const '
                                    "decisao=dec==='confirmar'?'PROCESSANDO_CONFIRMAR_DUP':'PROCESSANDO_REJEITAR_DUP'; "
                                    'const '
                                    "acao=dec==='confirmar'?'DECISAO_RECEBIDA_CONFIRMAR':'DECISAO_RECEBIDA_REJEITAR'; "
                                    'const esc=s=>"\'" + String(s??\'\').replace(/\'/g,"\'\'") + "\'"; const '
                                    "log=esc(JSON.stringify({wf:'WF04',acao,ts:new Date().toISOString()})); return "
                                    '`WITH alvo AS (\n'
                                    '  SELECT '
                                    'id,titulo,descricao,tipo_servico,localizacao,solicitante,email_solicitante,status_num,status_nome,data_abertura,data_ultima_mudanca,triagem_status,classificacao,duplicado_de_id,motivo_classificacao,em_aprovacao_fiscal,decisao_fiscal,classificacao_final,fiscal_decision_token,fiscal_token_expira_em\n'
                                    '  FROM tickets_processados\n'
                                    '  WHERE id=${id}\n'
                                    '),\n'
                                    'reservado AS (\n'
                                    '  UPDATE tickets_processados\n'
                                    '  SET em_aprovacao_fiscal=FALSE,\n'
                                    '      aprovacao_decidida_em=NOW(),\n'
                                    "      decisao_fiscal='${decisao}',\n"
                                    "      ultima_acao_workflow='WF04_DECISAO_RECEBIDA',\n"
                                    "      log_workflow=COALESCE(log_workflow,'[]'::jsonb)||${log}::jsonb\n"
                                    '  WHERE id=${id}\n'
                                    '    AND COALESCE(em_aprovacao_fiscal,FALSE)=TRUE\n'
                                    "    AND COALESCE(decisao_fiscal,'')=''\n"
                                    "    AND fiscal_decision_token='${token}'\n"
                                    '  RETURNING '
                                    'id,titulo,descricao,tipo_servico,localizacao,solicitante,email_solicitante,status_num,status_nome,data_abertura,data_ultima_mudanca,triagem_status,classificacao,duplicado_de_id,motivo_classificacao,em_aprovacao_fiscal,decisao_fiscal,classificacao_final,fiscal_decision_token,fiscal_token_expira_em,TRUE '
                                    'AS decisao_reservada\n'
                                    ')\n'
                                    'SELECT * FROM reservado\n'
                                    'UNION ALL\n'
                                    'SELECT '
                                    'id,titulo,descricao,tipo_servico,localizacao,solicitante,email_solicitante,status_num,status_nome,data_abertura,data_ultima_mudanca,triagem_status,classificacao,duplicado_de_id,motivo_classificacao,em_aprovacao_fiscal,decisao_fiscal,classificacao_final,fiscal_decision_token,fiscal_token_expira_em,FALSE '
                                    'AS decisao_reservada\n'
                                    'FROM alvo\n'
                                    'WHERE NOT EXISTS (SELECT 1 FROM reservado);`; })() }}',
                           'options': {}},
            'type': 'n8n-nodes-base.postgres',
            'typeVersion': 2.5,
            'position': [-64, -112],
            'id': 'v9-wf04-fbuscar',
            'name': 'PG: Buscar Chamado',
            'alwaysOutputData': True,
            'credentials': {'postgres': {'id': 'PG_TRIAGEM', 'name': 'Postgres Triagem'}}},
           {'parameters': {'jsCode': '\n'
                                     'const r = $json || {};\n'
                                     "const d = $('Extrair Decisão').first().json;\n"
                                     'const reservado = r.decisao_reservada === true || '
                                     "String(r.decisao_reservada).toLowerCase() === 'true';\n"
                                     "let acao = 'INVALIDO';\n"
                                     "let msg = '';\n"
                                     "if (!r.id) msg = 'Chamado nao encontrado.';\n"
                                     "else if (reservado && d.decisao === 'confirmar') { acao = 'CONFIRMAR'; msg = "
                                     "'Duplicidade confirmada #' + r.id; }\n"
                                     "else if (reservado && d.decisao === 'nao_duplicado') { acao = 'REJEITAR'; msg = "
                                     "'Duplicidade rejeitada #' + r.id; }\n"
                                     "else if (!reservado && r.decisao_fiscal) { acao = 'JA_REGISTRADO'; msg = "
                                     "'Decisao ja registrada ou em processamento para o chamado #' + r.id + ': ' + "
                                     "r.decisao_fiscal + '.'; }\n"
                                     "else if (!reservado && r.em_aprovacao_fiscal) msg = 'Token fiscal invalido, "
                                     "expirado ou ja utilizado para o chamado #' + r.id + '.';\n"
                                     "else if (!r.em_aprovacao_fiscal) msg = 'Chamado nao aguarda decisao fiscal.';\n"
                                     "else msg = 'Decisao invalida.';\n"
                                     "console.log('[WF04][LOG] Validacao fiscal acao=' + acao + ' reservado=' + "
                                     'reservado);\n'
                                     'return [{json:{...r,acao,msg}}];\n'},
            'type': 'n8n-nodes-base.code',
            'typeVersion': 2,
            'position': [256, -112],
            'id': 'v9-wf04-fval',
            'name': 'Validar Fiscal',
            'alwaysOutputData': True},
           {'parameters': {'rules': {'values': [{'conditions': {'options': {'caseSensitive': True,
                                                                            'leftValue': '',
                                                                            'typeValidation': 'strict',
                                                                            'version': 2},
                                                                'conditions': [{'leftValue': '={{ $json.acao }}',
                                                                                'rightValue': 'CONFIRMAR',
                                                                                'operator': {'type': 'string',
                                                                                             'operation': 'equals'},
                                                                                'id': 'c1'}],
                                                                'combinator': 'and'},
                                                 'renameOutput': True,
                                                 'outputKey': 'CONFIRMAR'},
                                                {'conditions': {'options': {'caseSensitive': True,
                                                                            'leftValue': '',
                                                                            'typeValidation': 'strict',
                                                                            'version': 2},
                                                                'conditions': [{'leftValue': '={{ $json.acao }}',
                                                                                'rightValue': 'REJEITAR',
                                                                                'operator': {'type': 'string',
                                                                                             'operation': 'equals'},
                                                                                'id': 'r1'}],
                                                                'combinator': 'and'},
                                                 'renameOutput': True,
                                                 'outputKey': 'REJEITAR'},
                                                {'conditions': {'options': {'caseSensitive': True,
                                                                            'leftValue': '',
                                                                            'typeValidation': 'strict',
                                                                            'version': 2},
                                                                'conditions': [{'leftValue': '={{ $json.acao }}',
                                                                                'rightValue': 'JA_REGISTRADO',
                                                                                'operator': {'type': 'string',
                                                                                             'operation': 'equals'},
                                                                                'id': 'j1'}],
                                                                'combinator': 'and'},
                                                 'renameOutput': True,
                                                 'outputKey': 'JA_REGISTRADO'},
                                                {'conditions': {'options': {'caseSensitive': True,
                                                                            'leftValue': '',
                                                                            'typeValidation': 'strict',
                                                                            'version': 2},
                                                                'conditions': [{'leftValue': '={{ $json.acao }}',
                                                                                'rightValue': 'INVALIDO',
                                                                                'operator': {'type': 'string',
                                                                                             'operation': 'equals'},
                                                                                'id': 'i1'}],
                                                                'combinator': 'and'},
                                                 'renameOutput': True,
                                                 'outputKey': 'INVALIDO'}]},
                           'options': {}},
            'type': 'n8n-nodes-base.switch',
            'typeVersion': 3.2,
            'position': [624, -144],
            'id': 'v9-wf04-fsw',
            'name': 'Switch Ação Fiscal'},
           {'parameters': {'respondWith': 'text',
                           'responseBody': "={{ 'Decisão recebida! O chamado #'+$json.id+' está sendo processado em "
                                           "segundo plano.' }}",
                           'options': {'responseCode': 202,
                                       'responseHeaders': {'entries': [{'name': 'Content-Type',
                                                                        'value': 'text/plain; charset=utf-8'}]}}},
            'type': 'n8n-nodes-base.respondToWebhook',
            'typeVersion': 1.5,
            'position': [912, -256],
            'id': 'v9-wf04-cf-resp',
            'name': 'Resp: Confirmado'},
           {'parameters': {'method': 'POST',
                           'url': "={{ ($env.GLPI_API_URL || 'http://host.docker.internal:9080/apirest.php') + "
                                  "'/ITILFollowup' }}",
                           'sendHeaders': True,
                           'headerParameters': {'parameters': [{'name': 'App-Token',
                                                                'value': '={{ $env.GLPI_APP_TOKEN || '
                                                                         "'' }}"},
                                                               {'name': 'Session-Token',
                                                                'value': "={{ $('GLPI: Sessão "
                                                                         "Fiscal').first().json.session_token }}"}]},
                           'sendBody': True,
                           'specifyBody': 'json',
                           'jsonBody': {'input': {'items_id': "={{  $('Validar Fiscal').first().json.id }}",
                                                  'itemtype': 'Ticket',
                                                  'content': "={{'[TRIAGEM_IA] Duplicidade CONFIRMADA pelo fiscal. O "
                                                             'chamado sera fechado por ja existir solicitacao '
                                                             "anterior. Ref: #'+($('Validar "
                                                             "Fiscal').first().json.duplicado_de_id||'N/A')}}"}},
                           'options': {}},
            'type': 'n8n-nodes-base.httpRequest',
            'typeVersion': 4.2,
            'position': [1168, -256],
            'id': 'v9-wf04-cf1',
            'name': 'GLPI: Followup Confirmado',
            'typeOptions': {'timeoutMilliseconds': 15000},
            'alwaysOutputData': True},
           {'parameters': {'method': 'PUT',
                           'url': "={{ ($env.GLPI_API_URL || 'http://host.docker.internal:9080/apirest.php') + "
                                  "'/Ticket/' + $('Validar Fiscal').first().json.id }}",
                           'sendHeaders': True,
                           'headerParameters': {'parameters': [{'name': 'App-Token',
                                                                'value': '={{ $env.GLPI_APP_TOKEN || '
                                                                         "'' }}"},
                                                               {'name': 'Session-Token',
                                                                'value': "={{ $('GLPI: Sessão "
                                                                         "Fiscal').first().json.session_token }}"}]},
                           'sendBody': True,
                           'specifyBody': 'json',
                           'jsonBody': {'input': {'id': "={{$('Validar Fiscal').first().json.id}}", 'status': 6}},
                           'options': {}},
            'type': 'n8n-nodes-base.httpRequest',
            'typeVersion': 4.2,
            'position': [1424, -256],
            'id': 'v9-wf04-cf2',
            'name': 'GLPI: Fechar Confirmado',
            'typeOptions': {'timeoutMilliseconds': 15000},
            'alwaysOutputData': True},
           {'parameters': {'operation': 'executeQuery',
                           'query': 'UPDATE tickets_processados SET '
                                    "status_num=6,status_nome='Fechado',triagem_status='DUPLICADO_FECHADO',em_aprovacao_fiscal=FALSE,aprovacao_decidida_em=NOW(),decisao_fiscal='CONFIRMOU_DUP',fiscal_decision_token=NULL,fiscal_token_expira_em=NULL,classificacao='DUPLICADO',classificacao_final='DUPLICADO',triado_em=NOW(),ultima_acao_workflow='DUPLICADO_FECHADO',log_workflow=COALESCE(log_workflow,'[]'::jsonb)||jsonb_build_object('wf','WF04','acao','DUPLICADO_FECHADO','ts',NOW()) "
                                    'WHERE id=$1::bigint RETURNING id;',
                           'options': {'queryReplacement': "={{ String($('Validar Fiscal').first().json.id) }}"}},
            'type': 'n8n-nodes-base.postgres',
            'typeVersion': 2.5,
            'position': [1680, -256],
            'id': 'v9-wf04-cf3',
            'name': 'PG: Duplicado Fechado',
            'alwaysOutputData': True,
            'credentials': {'postgres': {'id': 'PG_TRIAGEM', 'name': 'Postgres Triagem'}}},
           {'parameters': {'url': "={{ ($env.GLPI_API_URL || 'http://host.docker.internal:9080/apirest.php') + "
                                  "'/killSession' }}",
                           'sendHeaders': True,
                           'headerParameters': {'parameters': [{'name': 'App-Token',
                                                                'value': '={{ $env.GLPI_APP_TOKEN || '
                                                                         "'' }}"},
                                                               {'name': 'Session-Token',
                                                                'value': "={{ $('GLPI: Sessão "
                                                                         "Fiscal').first().json.session_token }}"}]},
                           'options': {}},
            'type': 'n8n-nodes-base.httpRequest',
            'typeVersion': 4.2,
            'position': [1952, -256],
            'id': 'v9-wf04-fgk-ok',
            'name': 'GLPI: Encerrar Sessão Fiscal',
            'typeOptions': {'timeoutMilliseconds': 15000},
            'alwaysOutputData': True,
            'onError': 'continueRegularOutput'},
           {'parameters': {'jsCode': "console.log('[WF04][LOG] Fim fiscal confirmado'); return [{json:{ok:true}}];"},
            'type': 'n8n-nodes-base.code',
            'typeVersion': 2,
            'position': [2208, -256],
            'id': 'v9-wf04-flog-ok',
            'name': 'LOG: Fim Fiscal',
            'alwaysOutputData': True},
           {'parameters': {'respondWith': 'text',
                           'responseBody': "={{ 'Decisão recebida! O chamado #'+$json.id+' está sendo processado em "
                                           "segundo plano.' }}",
                           'options': {'responseCode': 202,
                                       'responseHeaders': {'entries': [{'name': 'Content-Type',
                                                                        'value': 'text/plain; charset=utf-8'}]}}},
            'type': 'n8n-nodes-base.respondToWebhook',
            'typeVersion': 1.5,
            'position': [896, -112],
            'id': 'v9-wf04-rj-resp',
            'name': 'Resp: Rejeitado'},
           {'parameters': {'operation': 'executeQuery',
                           'query': 'UPDATE tickets_processados SET '
                                    "status_num=4,status_nome='Pendente',em_aprovacao_fiscal=FALSE,aprovacao_decidida_em=NOW(),decisao_fiscal='REJEITOU_DUP',fiscal_decision_token=NULL,fiscal_token_expira_em=NULL,classificacao=NULL,classificacao_final=NULL,duplicado_de_id=NULL,motivo_classificacao=NULL,triagem_status='CLASSIFICANDO',ultima_acao_workflow='RECLASS_FISCAL',log_workflow=COALESCE(log_workflow,'[]'::jsonb)||jsonb_build_object('wf','WF04','acao','REJEITOU_DUP','ts',NOW()) "
                                    'WHERE id=$1::bigint RETURNING '
                                    'id,titulo,descricao,tipo_servico,localizacao,solicitante,email_solicitante,status_num,status_nome,data_abertura,data_ultima_mudanca;',
                           'options': {'queryReplacement': "={{ String($('Validar Fiscal').first().json.id) }}"}},
            'type': 'n8n-nodes-base.postgres',
            'typeVersion': 2.5,
            'position': [1152, -112],
            'id': 'v9-wf04-rj1',
            'name': 'PG: Limpar Duplicidade',
            'alwaysOutputData': True,
            'credentials': {'postgres': {'id': 'PG_TRIAGEM', 'name': 'Postgres Triagem'}}},
           {'parameters': {'jsCode': '\n'
                                     "const r = $('PG: Limpar Duplicidade').first().json;\n"
                                     "const origem = $('Validar Fiscal').first().json || {};\n"
                                     "const token = String(origem.fiscal_decision_token || '').trim();\n"
                                     "const marker = token ? `[WF02_DUPLICIDADE:${origem.id || r.id}:${token}]` : '';\n"
                                     "const baseUrl = String((typeof process !== 'undefined' && "
                                     'process.env.GLPI_API_URL) || '
                                     "'http://host.docker.internal:9080/apirest.php').replace(/\\/$/, '');\n"
                                     "const appToken = String((typeof process !== 'undefined' && "
                                     "process.env.GLPI_APP_TOKEN) || '');\n"
                                     "const sessionToken = String($('GLPI: Sessão Fiscal').first().json.session_token "
                                     "|| '');\n"
                                     "const headers = {'App-Token': appToken, 'Session-Token': sessionToken, "
                                     "'Content-Type': 'application/json'};\n"
                                     'let removidos = 0;\n'
                                     'let falhas = 0;\n'
                                     'try {\n'
                                     '  const followups = await helpers.httpRequest({\n'
                                     "    method: 'GET',\n"
                                     "    url: baseUrl + '/Ticket/' + Number(r.id) + '/ITILFollowup',\n"
                                     '    headers,\n'
                                     '    json: true\n'
                                     '  });\n'
                                     '  const candidatos = [];\n'
                                     '  for (const f of Array.isArray(followups) ? followups : []) {\n'
                                     "    const fid = Number(f.id || f['2']);\n"
                                     "    const content = String(f.content || f['content'] || '');\n"
                                     '    const criadoPelaTriagem = marker && content.includes(marker);\n'
                                     '    if (!fid || !criadoPelaTriagem) continue;\n'
                                     '    candidatos.push(fid);\n'
                                     '  }\n'
                                     '  const resultados = await Promise.all(candidatos.map(async (fid) => {\n'
                                     '    try {\n'
                                     '      await helpers.httpRequest({\n'
                                     "        method: 'DELETE',\n"
                                     "        url: baseUrl + '/ITILFollowup/' + fid,\n"
                                     '        headers,\n'
                                     '        json: true\n'
                                     '      });\n'
                                     '      return {fid, ok:true};\n'
                                     '    } catch (e) {\n'
                                     "      console.log('[WF04][LOG] Falha ao remover followup #' + fid + ' do chamado "
                                     "#' + r.id + ': ' + e.message);\n"
                                     '      return {fid, ok:false};\n'
                                     '    }\n'
                                     '  }));\n'
                                     '  removidos = resultados.filter(x => x.ok).length;\n'
                                     '  falhas = resultados.length - removidos;\n'
                                     '} catch (e) {\n'
                                     "  console.log('[WF04][LOG] Falha ao remover followups de duplicidade #' + r.id + "
                                     "': ' + e.message);\n"
                                     '}\n'
                                     "console.log('[WF04][LOG] Followups de duplicidade removidos #' + r.id + ': ' + "
                                     "removidos + ' | falhas=' + falhas + ' | marker=' + (marker ? 'ok' : "
                                     "'ausente'));\n"
                                     'return '
                                     '[{json:{...r,followups_removidos:removidos,followups_remocao_falhas:falhas,marcador_followup:marker}}];\n'},
            'type': 'n8n-nodes-base.code',
            'typeVersion': 2,
            'position': [1408, -112],
            'id': 'v9-wf04-rjdel',
            'name': 'GLPI: Remover Followups Dup',
            'alwaysOutputData': True},
           {'parameters': {'method': 'PUT',
                           'url': "={{ ($env.GLPI_API_URL || 'http://host.docker.internal:9080/apirest.php') + "
                                  "'/Ticket/' + $('PG: Limpar Duplicidade').first().json.id }}",
                           'sendHeaders': True,
                           'headerParameters': {'parameters': [{'name': 'App-Token',
                                                                'value': '={{ $env.GLPI_APP_TOKEN || '
                                                                         "'' }}"},
                                                               {'name': 'Session-Token',
                                                                'value': "={{ $('GLPI: Sessão "
                                                                         "Fiscal').first().json.session_token }}"}]},
                           'sendBody': True,
                           'specifyBody': 'json',
                           'jsonBody': {'input': {'id': "={{$('PG: Limpar Duplicidade').first().json.id}}",
                                                  'name': "={{String($('PG: Limpar "
                                                          "Duplicidade').first().json.titulo||'').replace(/^\\[Duplicado\\]\\s*/i,'')}}",
                                                  'status': 4}},
                           'options': {}},
            'type': 'n8n-nodes-base.httpRequest',
            'typeVersion': 4.2,
            'position': [1664, -112],
            'id': 'v9-wf04-rj2',
            'name': 'GLPI: Restaurar Título',
            'typeOptions': {'timeoutMilliseconds': 15000},
            'alwaysOutputData': True},
           {'parameters': {'method': 'POST',
                           'url': "={{ ($env.GLPI_API_URL || 'http://host.docker.internal:9080/apirest.php') + "
                                  "'/ITILFollowup' }}",
                           'sendHeaders': True,
                           'headerParameters': {'parameters': [{'name': 'App-Token',
                                                                'value': '={{ $env.GLPI_APP_TOKEN || '
                                                                         "'' }}"},
                                                               {'name': 'Session-Token',
                                                                'value': "={{ $('GLPI: Sessão "
                                                                         "Fiscal').first().json.session_token }}"}]},
                           'sendBody': True,
                           'specifyBody': 'json',
                           'jsonBody': {'input': {'items_id': "={{  $('PG: Limpar Duplicidade').first().json.id }}",
                                                  'itemtype': 'Ticket',
                                                  'content': "={{'[TRIAGEM_IA] Duplicidade REJEITADA pelo fiscal. O "
                                                             'titulo foi higienizado, os links/dados de comparacao '
                                                             'foram removidos e o chamado sera enviado para '
                                                             'classificacao normal. Followups removidos: '
                                                             "'+String($('GLPI: Remover Followups "
                                                             "Dup').first().json.followups_removidos||0)}}"}},
                           'options': {}},
            'type': 'n8n-nodes-base.httpRequest',
            'typeVersion': 4.2,
            'position': [1936, -112],
            'id': 'v9-wf04-rjfu',
            'name': 'GLPI: Followup Rejeitado',
            'typeOptions': {'timeoutMilliseconds': 15000},
            'alwaysOutputData': True},
           {'parameters': {'url': "={{ ($env.GLPI_API_URL || 'http://host.docker.internal:9080/apirest.php') + "
                                  "'/killSession' }}",
                           'sendHeaders': True,
                           'headerParameters': {'parameters': [{'name': 'App-Token',
                                                                'value': '={{ $env.GLPI_APP_TOKEN || '
                                                                         "'' }}"},
                                                               {'name': 'Session-Token',
                                                                'value': "={{ $('GLPI: Sessão "
                                                                         "Fiscal').first().json.session_token }}"}]},
                           'options': {}},
            'type': 'n8n-nodes-base.httpRequest',
            'typeVersion': 4.2,
            'position': [2192, -112],
            'id': 'v9-wf04-fgk-rj',
            'name': 'GLPI: Encerrar Sessão Fiscal Rejeição',
            'typeOptions': {'timeoutMilliseconds': 15000},
            'alwaysOutputData': True,
            'onError': 'continueRegularOutput'},
           {'parameters': {'jsCode': '\n'
                                     "const r = $('PG: Limpar Duplicidade').first().json;\n"
                                     'const ch = {\n'
                                     '  id:r.id,\n'
                                     "  titulo:String(r.titulo||'').replace(/^\\[Duplicado\\]\\s*/i,''),\n"
                                     '  descricao:r.descricao,\n'
                                     '  tipo_servico:r.tipo_servico,\n'
                                     '  localizacao:r.localizacao,\n'
                                     '  solicitante:r.solicitante,\n'
                                     '  email_solicitante:r.email_solicitante,\n'
                                     '  status_num:4,\n'
                                     "  status_nome:'Pendente',\n"
                                     '  data_abertura:r.data_abertura,\n'
                                     '  data_ultima_mudanca:r.data_ultima_mudanca\n'
                                     '};\n'
                                     "console.log('[WF04][LOG] Reclassificacao fiscal #' + ch.id);\n"
                                     'return [{json:{chamado:ch}}];\n'},
            'type': 'n8n-nodes-base.code',
            'typeVersion': 2,
            'position': [2448, -112],
            'id': 'v9-wf04-rjprep',
            'name': 'Preparar Reclassificação',
            'alwaysOutputData': True},
           {'parameters': {'workflowId': {'__rl': True, 'mode': 'id', 'value': 'reVggSpJiaPhnfIo'},
                           'workflowInputs': {'mappingMode': 'defineBelow',
                                              'value': {},
                                              'matchingColumns': [],
                                              'schema': [],
                                              'attemptToConvertTypes': False,
                                              'convertFieldsToString': True},
                           'mode': 'each',
                           'options': {'waitForSubWorkflow': False}},
            'type': 'n8n-nodes-base.executeWorkflow',
            'typeVersion': 1.2,
            'position': [2704, -112],
            'id': 'v9-wf04-exec3',
            'name': 'Chamar WF03'},
           {'parameters': {'jsCode': "console.log('[WF04][LOG] Fim fiscal rejeicao'); return [{json:{ok:true}}];"},
            'type': 'n8n-nodes-base.code',
            'typeVersion': 2,
            'position': [2976, -112],
            'id': 'v9-wf04-flog-rj',
            'name': 'LOG: Fim Fiscal Rejeição',
            'alwaysOutputData': True},
           {'parameters': {'respondWith': 'text',
                           'responseBody': '={{ $json.msg }}',
                           'options': {'responseCode': 200,
                                       'responseHeaders': {'entries': [{'name': 'Content-Type',
                                                                        'value': 'text/plain; charset=utf-8'}]}}},
            'type': 'n8n-nodes-base.respondToWebhook',
            'typeVersion': 1.5,
            'position': [896, 48],
            'id': 'v9-wf04-already',
            'name': 'Resp: Decisão Já Registrada'},
           {'parameters': {'url': "={{ ($env.GLPI_API_URL || 'http://host.docker.internal:9080/apirest.php') + "
                                  "'/killSession' }}",
                           'sendHeaders': True,
                           'headerParameters': {'parameters': [{'name': 'App-Token',
                                                                'value': '={{ $env.GLPI_APP_TOKEN || '
                                                                         "'' }}"},
                                                               {'name': 'Session-Token',
                                                                'value': "={{ $('GLPI: Sessão "
                                                                         "Fiscal').first().json.session_token }}"}]},
                           'options': {}},
            'type': 'n8n-nodes-base.httpRequest',
            'typeVersion': 4.2,
            'position': [1152, 48],
            'id': 'v9-wf04-fgk-already',
            'name': 'GLPI: Encerrar Sessão Fiscal Já Registrada',
            'typeOptions': {'timeoutMilliseconds': 15000},
            'alwaysOutputData': True,
            'onError': 'continueRegularOutput'},
           {'parameters': {'jsCode': "console.log('[WF04][LOG] Decisao fiscal ja registrada'); return "
                                     '[{json:{ok:true,idempotente:true}}];'},
            'type': 'n8n-nodes-base.code',
            'typeVersion': 2,
            'position': [1408, 48],
            'id': 'v9-wf04-flog-already',
            'name': 'LOG: Fim Fiscal Já Registrada',
            'alwaysOutputData': True},
           {'parameters': {'respondWith': 'text',
                           'responseBody': '={{ $json.msg }}',
                           'options': {'responseCode': 409,
                                       'responseHeaders': {'entries': [{'name': 'Content-Type',
                                                                        'value': 'text/plain; charset=utf-8'}]}}},
            'type': 'n8n-nodes-base.respondToWebhook',
            'typeVersion': 1.5,
            'position': [880, 208],
            'id': 'v9-wf04-finv',
            'name': 'Resp: Inválido'},
           {'parameters': {'url': "={{ ($env.GLPI_API_URL || 'http://host.docker.internal:9080/apirest.php') + "
                                  "'/killSession' }}",
                           'sendHeaders': True,
                           'headerParameters': {'parameters': [{'name': 'App-Token',
                                                                'value': '={{ $env.GLPI_APP_TOKEN || '
                                                                         "'' }}"},
                                                               {'name': 'Session-Token',
                                                                'value': "={{ $('GLPI: Sessão "
                                                                         "Fiscal').first().json.session_token }}"}]},
                           'options': {}},
            'type': 'n8n-nodes-base.httpRequest',
            'typeVersion': 4.2,
            'position': [1136, 208],
            'id': 'v9-wf04-fgk-inv',
            'name': 'GLPI: Encerrar Sessão Fiscal Inválido',
            'typeOptions': {'timeoutMilliseconds': 15000},
            'alwaysOutputData': True,
            'onError': 'continueRegularOutput'},
           {'parameters': {'jsCode': "console.log('[WF04][LOG] Fim fiscal invalido'); return [{json:{ok:false}}];"},
            'type': 'n8n-nodes-base.code',
            'typeVersion': 2,
            'position': [1392, 208],
            'id': 'v9-wf04-flog-inv',
            'name': 'LOG: Fim Fiscal Inválido',
            'alwaysOutputData': True}],
 'pinData': {},
 'connections': {'Webhook Fiscal': {'main': [[{'node': 'Extrair Decisão', 'type': 'main', 'index': 0}]]},
                 'Extrair Decisão': {'main': [[{'node': 'Link Válido?', 'type': 'main', 'index': 0}]]},
                 'Link Válido?': {'main': [[{'node': 'GLPI: Sessão Fiscal', 'type': 'main', 'index': 0}],
                                           [{'node': 'Tem Chamado no Link?', 'type': 'main', 'index': 0}]]},
                 'Tem Chamado no Link?': {'main': [[{'node': 'GLPI: Sessão Link Inválido', 'type': 'main', 'index': 0}],
                                                   [{'node': 'LOG: Link Sem Chamado', 'type': 'main', 'index': 0}]]},
                 'GLPI: Sessão Link Inválido': {'main': [[{'node': 'GLPI: Anotar Link Inválido',
                                                           'type': 'main',
                                                           'index': 0}]]},
                 'GLPI: Anotar Link Inválido': {'main': [[{'node': 'Resp: Falha Anotada',
                                                           'type': 'main',
                                                           'index': 0}]]},
                 'Resp: Falha Anotada': {'main': [[{'node': 'GLPI: Encerrar Sessão Link Inválido',
                                                    'type': 'main',
                                                    'index': 0}]]},
                 'GLPI: Encerrar Sessão Link Inválido': {'main': [[{'node': 'LOG: Link Inválido Anotado',
                                                                    'type': 'main',
                                                                    'index': 0}]]},
                 'LOG: Link Sem Chamado': {'main': [[{'node': 'Resp: Falha Sem Chamado', 'type': 'main', 'index': 0}]]},
                 'GLPI: Sessão Fiscal': {'main': [[{'node': 'PG: Buscar Chamado', 'type': 'main', 'index': 0}]]},
                 'PG: Buscar Chamado': {'main': [[{'node': 'Validar Fiscal', 'type': 'main', 'index': 0}]]},
                 'Validar Fiscal': {'main': [[{'node': 'Switch Ação Fiscal', 'type': 'main', 'index': 0}]]},
                 'Switch Ação Fiscal': {'main': [[{'node': 'Resp: Confirmado', 'type': 'main', 'index': 0}],
                                                 [{'node': 'Resp: Rejeitado', 'type': 'main', 'index': 0}],
                                                 [{'node': 'Resp: Decisão Já Registrada', 'type': 'main', 'index': 0}],
                                                 [{'node': 'Resp: Inválido', 'type': 'main', 'index': 0}]]},
                 'Resp: Confirmado': {'main': [[{'node': 'GLPI: Followup Confirmado', 'type': 'main', 'index': 0}]]},
                 'GLPI: Followup Confirmado': {'main': [[{'node': 'GLPI: Fechar Confirmado',
                                                          'type': 'main',
                                                          'index': 0}]]},
                 'GLPI: Fechar Confirmado': {'main': [[{'node': 'PG: Duplicado Fechado', 'type': 'main', 'index': 0}]]},
                 'PG: Duplicado Fechado': {'main': [[{'node': 'GLPI: Encerrar Sessão Fiscal',
                                                      'type': 'main',
                                                      'index': 0}]]},
                 'GLPI: Encerrar Sessão Fiscal': {'main': [[{'node': 'LOG: Fim Fiscal', 'type': 'main', 'index': 0}]]},
                 'Resp: Rejeitado': {'main': [[{'node': 'PG: Limpar Duplicidade', 'type': 'main', 'index': 0}]]},
                 'PG: Limpar Duplicidade': {'main': [[{'node': 'GLPI: Remover Followups Dup',
                                                       'type': 'main',
                                                       'index': 0}]]},
                 'GLPI: Remover Followups Dup': {'main': [[{'node': 'GLPI: Restaurar Título',
                                                            'type': 'main',
                                                            'index': 0}]]},
                 'GLPI: Restaurar Título': {'main': [[{'node': 'GLPI: Followup Rejeitado',
                                                       'type': 'main',
                                                       'index': 0}]]},
                 'GLPI: Followup Rejeitado': {'main': [[{'node': 'GLPI: Encerrar Sessão Fiscal Rejeição',
                                                         'type': 'main',
                                                         'index': 0}]]},
                 'GLPI: Encerrar Sessão Fiscal Rejeição': {'main': [[{'node': 'Preparar Reclassificação',
                                                                      'type': 'main',
                                                                      'index': 0}]]},
                 'Preparar Reclassificação': {'main': [[{'node': 'Chamar WF03', 'type': 'main', 'index': 0}]]},
                 'Chamar WF03': {'main': [[{'node': 'LOG: Fim Fiscal Rejeição', 'type': 'main', 'index': 0}]]},
                 'Resp: Decisão Já Registrada': {'main': [[{'node': 'GLPI: Encerrar Sessão Fiscal Já Registrada',
                                                            'type': 'main',
                                                            'index': 0}]]},
                 'GLPI: Encerrar Sessão Fiscal Já Registrada': {'main': [[{'node': 'LOG: Fim Fiscal Já Registrada',
                                                                           'type': 'main',
                                                                           'index': 0}]]},
                 'Resp: Inválido': {'main': [[{'node': 'GLPI: Encerrar Sessão Fiscal Inválido',
                                               'type': 'main',
                                               'index': 0}]]},
                 'GLPI: Encerrar Sessão Fiscal Inválido': {'main': [[{'node': 'LOG: Fim Fiscal Inválido',
                                                                      'type': 'main',
                                                                      'index': 0}]]}},
 'active': True,
 'settings': {'executionOrder': 'v1',
              'timezone': 'America/Sao_Paulo',
              'saveExecutionProgress': True,
              'saveManualExecutions': True},
 'versionId': '4f01e6e8-1602-4ff5-94dd-c2fb0960b893',
 'meta': {'instanceId': '61b33b02f7624108f052821275a127dc5ced9722fe23c533d96378702b337c3b'},
 'id': 'ZpQ0H9uV9Fiscal04',
 'tags': []}


def _node(name: str) -> dict:
    for node in WORKFLOW["nodes"]:
        if node.get("name") == name:
            return node
    raise KeyError(f"Nó não encontrado: {name}")


def _pg_node(node_id: str, name: str, position: list[int], query: str) -> dict:
    return {
        "parameters": {"operation": "executeQuery", "query": query, "options": {}},
        "type": "n8n-nodes-base.postgres",
        "typeVersion": 2.5,
        "position": position,
        "id": node_id,
        "name": name,
        "credentials": {"postgres": {"id": "PG_TRIAGEM", "name": "Postgres Triagem"}},
        "alwaysOutputData": True,
        "onError": "continueRegularOutput",
    }


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


def _apply_robustness_updates() -> None:
    _node("Extrair Decisão")["parameters"]["jsCode"] = r"""
const q=$json.query || {};
const headers=$json.headers || {};
const dec=String(q.decisao ?? '').toLowerCase().trim();
const cid=Number(q.chamado_id);
const rid=Number(q.ref_id || 0);
const token=String(q.token || '').trim();
const fonte=String(q.fonte || '').toUpperCase().trim();
const oraculo=fonte==='ORACULO_GABARITO';
const runId=String(q.run_id || headers['x-test-run-id'] || '').trim();
const scenarioId=String(q.scenario_id || headers['x-test-scenario-id'] || '').trim();
const realizationId=String(q.realization_id || headers['x-test-realization-id'] || '').trim();
const nonce=String(headers['x-test-auto-review-nonce'] || '').trim();
const receivedSecret=String(headers['x-test-auto-review-token'] || '').trim();
const expectedSecret=String(
  (typeof $env!=='undefined' && $env.TEST_AUTO_REVIEW_TOKEN) ||
  (typeof process!=='undefined' && process.env.TEST_AUTO_REVIEW_TOKEN) || ''
);
const flag=name=>{
  let value='';
  try { value=String((typeof $env!=='undefined' && $env[name]) || (typeof process!=='undefined' && process.env[name]) || ''); } catch(e) {}
  return value.trim().toLowerCase()==='true';
};
function sameSecret(a,b){
  if(a.length!==b.length || a.length<32) return false;
  let diff=0; for(let i=0;i<a.length;i++) diff|=a.charCodeAt(i)^b.charCodeAt(i);
  return diff===0;
}
const idsOk=/^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$/.test(runId)
  && /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(scenarioId)
  && /^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$/.test(realizationId);
const oracleAuthOk=!oraculo || (
  flag('TEST_MODE') && flag('TEST_AUTO_HUMAN_CONFIRMATION') &&
  sameSecret(expectedSecret,receivedSecret) && /^[a-f0-9]{32}$/i.test(nonce) && idsOk
);
const temChamado=Number.isFinite(cid) && cid>0;
const decisaoValida=['confirmar','nao_duplicado'].includes(dec);
const tokenValidoFormato=/^[a-f0-9]{32,128}$/i.test(token);
const ok=temChamado && decisaoValida && tokenValidoFormato && oracleAuthOk;
let motivo_invalidade='';
if(!temChamado) motivo_invalidade='chamado_id ausente ou invalido';
else if(!decisaoValida) motivo_invalidade='decisao ausente ou invalida: '+(dec||'vazia');
else if(!tokenValidoFormato) motivo_invalidade='token fiscal ausente ou invalido';
else if(!oracleAuthOk) motivo_invalidade='origem ORACULO_GABARITO nao autorizada';
console.log('[WF04][LOG] decisao='+dec+' chamado='+cid+' origem='+(oraculo?'ORACULO_GABARITO':'FISCAL_GLPI')+' ok='+ok);
return [{json:{
  ok,decisao:dec,chamado_id:temChamado?cid:null,ref_id:rid>0?rid:null,
  token:tokenValidoFormato?token:null,motivo_invalidade,
  origem_decisao:oraculo?'ORACULO_GABARITO':'FISCAL_GLPI',oraculo,
  run_id:oraculo?runId:null,scenario_id:oraculo?scenarioId:null,
  realization_id:oraculo?realizationId:null,assessor_nonce:oraculo?nonce:null
}}];
"""

    _node("PG: Buscar Chamado")["parameters"]["query"] = r"""{{ (()=>{
const d=$('Extrair Decisão').first().json;
const id=Number(d.chamado_id);
const dec=String(d.decisao||'').toLowerCase();
const token=String(d.token||'').replace(/'/g,"''");
const decisao=dec==='confirmar'?'PROCESSANDO_CONFIRMAR_DUP':'PROCESSANDO_REJEITAR_DUP';
const acao=dec==='confirmar'?'DECISAO_RECEBIDA_CONFIRMAR':'DECISAO_RECEBIDA_REJEITAR';
const esc=s=>"'"+String(s??'').replace(/'/g,"''")+"'";
const oraculo=d.oraculo===true;
const runId=d.run_id?esc(d.run_id):'NULL';
const scenarioId=d.scenario_id?esc(d.scenario_id):'NULL';
const realizationId=d.realization_id?esc(d.realization_id):'NULL';
const nonce=d.assessor_nonce?esc(d.assessor_nonce):'NULL';
const origem=oraculo?'ORACULO_GABARITO':'FISCAL_GLPI';
const log=esc(JSON.stringify({wf:'WF04',acao,origem,ts:new Date().toISOString()}));
const oracleGuardExpr=oraculo ? `EXISTS (
  SELECT 1
  FROM dataset_controle dc
  JOIN experimentos_avaliacao e ON e.run_id=dc.run_id
  JOIN LATERAL (
    SELECT i.id,i.predicao,i.criado_em
    FROM ia_decisoes i
    WHERE i.ticket_id=dc.ticket_id AND i.run_id=dc.run_id
      AND i.case_id=dc.case_id AND i.etapa='DEDUPLICACAO'
    ORDER BY i.criado_em DESC,i.id DESC LIMIT 1
  ) i ON TRUE
  JOIN avaliacao_auto_confirmacoes ac
    ON ac.ticket_id=dc.ticket_id AND ac.run_id=dc.run_id
   AND ac.scenario_id=dc.scenario_id AND ac.realization_id=dc.case_id
   AND ac.tipo_confirmacao='FISCAL_DUPLICIDADE' AND ac.etapa='DEDUPLICACAO'
   AND ac.ia_decisao_id=i.id AND ac.status='RESERVADA'
  WHERE dc.ticket_id=tp.id AND dc.run_id=${runId}
    AND dc.scenario_id=${scenarioId} AND dc.case_id=${realizationId}
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
    AND i.predicao='DUPLICADO'
    AND i.criado_em<=COALESCE(tp.aprovacao_iniciada_em,NOW())
    AND ac.decisao_webhook=${esc(dec)}
    AND ac.token_hash=encode(sha256(convert_to(tp.fiscal_decision_token,'UTF8')),'hex')
    AND ac.assessor_nonce_hash=encode(sha256(convert_to(${nonce},'UTF8')),'hex')
)` : 'TRUE';
return `WITH alvo AS (
  SELECT id,titulo,descricao,tipo_servico,localizacao,solicitante,email_solicitante,status_num,status_nome,data_abertura,data_ultima_mudanca,triagem_status,classificacao,duplicado_de_id,motivo_classificacao,em_aprovacao_fiscal,decisao_fiscal,classificacao_final,fiscal_decision_token,fiscal_token_expira_em,(fiscal_token_expira_em IS NOT NULL AND fiscal_token_expira_em <= NOW()) AS fiscal_token_expirado,${oracleGuardExpr} AS oracle_guard_ok
  FROM tickets_processados tp
  WHERE id=${id}
),
reservado AS (
  UPDATE tickets_processados
  SET em_aprovacao_fiscal=FALSE,
      aprovacao_decidida_em=NOW(),
      decisao_fiscal='${decisao}',
      ultima_acao_workflow='WF04_DECISAO_RECEBIDA',
      log_workflow=COALESCE(log_workflow,'[]'::jsonb)||${log}::jsonb
  WHERE id=${id}
    AND COALESCE(em_aprovacao_fiscal,FALSE)=TRUE
    AND COALESCE(decisao_fiscal,'')=''
    AND fiscal_decision_token='${token}'
    AND (fiscal_token_expira_em IS NULL OR fiscal_token_expira_em > NOW())
    AND (SELECT oracle_guard_ok FROM alvo)
  RETURNING id,titulo,descricao,tipo_servico,localizacao,solicitante,email_solicitante,status_num,status_nome,data_abertura,data_ultima_mudanca,triagem_status,classificacao,duplicado_de_id,motivo_classificacao,em_aprovacao_fiscal,decisao_fiscal,classificacao_final,fiscal_decision_token,fiscal_token_expira_em,FALSE AS fiscal_token_expirado,TRUE AS decisao_reservada,TRUE AS oracle_guard_ok
)
SELECT * FROM reservado
UNION ALL
SELECT id,titulo,descricao,tipo_servico,localizacao,solicitante,email_solicitante,status_num,status_nome,data_abertura,data_ultima_mudanca,triagem_status,classificacao,duplicado_de_id,motivo_classificacao,em_aprovacao_fiscal,decisao_fiscal,classificacao_final,fiscal_decision_token,fiscal_token_expira_em,fiscal_token_expirado,FALSE AS decisao_reservada,oracle_guard_ok
FROM alvo
  WHERE NOT EXISTS (SELECT 1 FROM reservado);`;
})() }}"""

    _node("Validar Fiscal")["parameters"]["jsCode"] = r"""
const r = $json || {};
const d = $('Extrair Decisão').first().json;
const reservado = r.decisao_reservada === true || String(r.decisao_reservada).toLowerCase() === 'true';
const expirado = r.fiscal_token_expirado === true || String(r.fiscal_token_expirado).toLowerCase() === 'true';
const oracleGuardOk = r.oracle_guard_ok === true || String(r.oracle_guard_ok).toLowerCase() === 'true';
let acao = 'INVALIDO';
let evento_fiscal = 'TOKEN_INVALIDO';
let msg = '';
if (!r.id) { msg = 'Chamado nao encontrado.'; }
else if (d.oraculo===true && !oracleGuardOk) { evento_fiscal = 'ORACULO_BLOQUEADO_DB'; msg = 'Confirmacao automatica sem reserva ou contexto experimental valido.'; }
else if (reservado && d.decisao === 'confirmar') { acao = 'CONFIRMAR'; evento_fiscal = 'DECISAO_CONFIRMAR'; msg = 'Duplicidade confirmada #' + r.id; }
else if (reservado && d.decisao === 'nao_duplicado') { acao = 'REJEITAR'; evento_fiscal = 'DECISAO_REJEITAR'; msg = 'Duplicidade rejeitada #' + r.id; }
else if (!reservado && r.decisao_fiscal) { acao = 'JA_REGISTRADO'; evento_fiscal = 'CLIQUE_DUPLO'; msg = 'Decisao ja registrada ou em processamento para o chamado #' + r.id + ': ' + r.decisao_fiscal + '.'; }
else if (!reservado && expirado) { evento_fiscal = 'TOKEN_EXPIRADO'; msg = 'Token fiscal expirado para o chamado #' + r.id + '. Gere nova triagem ou revise manualmente no GLPI.'; }
else if (!reservado && r.em_aprovacao_fiscal) { msg = 'Token fiscal invalido ou ja utilizado para o chamado #' + r.id + '.'; }
else if (!r.em_aprovacao_fiscal) { msg = 'Chamado nao aguarda decisao fiscal.'; }
else { msg = 'Decisao invalida.'; }
console.log('[WF04][LOG] Validacao fiscal acao=' + acao + ' reservado=' + reservado + ' expirado=' + expirado);
return [{json:{...r,acao,evento_fiscal,msg,fiscal_token_expirado:expirado,origem_decisao:d.origem_decisao||'FISCAL_GLPI'}}];
"""

    registrar_link = r"""{{ (()=>{ const d=$('Extrair Decisão').first().json || {}; const esc=s=>"'"+String(s??'').replace(/'/g,"''")+"'"; const id=d.chamado_id ? Number(d.chamado_id) : 'NULL'; const erro=d.ok===true?'FALSE':'TRUE'; const origem=String(d.origem_decisao||'FISCAL_GLPI'); const acao=(d.ok===true?'LINK_FORMATO_VALIDO':'LINK_INVALIDO')+'_'+origem; return `
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
INSERT INTO workflow_eventos(ticket_id,workflow,node_name,fase,acao,status_evento,erro,mensagem_erro,inicio_em,fim_em)
VALUES(${id},'WF04','Extrair Decisão','LINK_FISCAL',${esc(acao)},${esc(d.ok===true?'OK':'INVALIDO')},${erro},${d.motivo_invalidade?esc(d.motivo_invalidade):'NULL'},NOW(),NOW());
SELECT ${id} AS ticket_id;`; })() }}"""
    _ensure_node(_pg_node("v9-wf04-pg-obs-link", "PG: Registrar Link Fiscal", [-912, 336], registrar_link))
    _connect_parallel("Extrair Decisão", "PG: Registrar Link Fiscal")

    registrar_decisao = r"""{{ (()=>{ const v=$('Validar Fiscal').first().json || {}; const esc=s=>"'"+String(s??'').replace(/'/g,"''")+"'"; const id=v.id ? Number(v.id) : 'NULL'; const origem=String(v.origem_decisao||'FISCAL_GLPI'); const evento=(origem==='ORACULO_GABARITO'?'ORACULO_GABARITO_':'')+String(v.evento_fiscal || v.acao || 'TOKEN_INVALIDO'); const erro=v.acao==='INVALIDO'?'TRUE':'FALSE'; const status=v.acao==='JA_REGISTRADO'?'IDEMPOTENTE':(v.acao==='INVALIDO'?'INVALIDO':'OK'); return `
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
INSERT INTO workflow_eventos(ticket_id,workflow,node_name,fase,acao,status_evento,status_anterior,erro,mensagem_erro,inicio_em,fim_em)
VALUES(${id},'WF04','Validar Fiscal','DECISAO_FISCAL',${esc(evento)},${esc(status)},${esc(v.status_nome || '')},${erro},${v.msg?esc(v.msg):'NULL'},NOW(),NOW());
SELECT ${id} AS ticket_id, ${esc(status)} AS status_evento;`; })() }}"""
    _ensure_node(_pg_node("v9-wf04-pg-obs-validacao", "PG: Registrar Decisão Fiscal", [-176, 352], registrar_decisao))
    _connect_parallel("Validar Fiscal", "PG: Registrar Decisão Fiscal")

    registrar_confirmado = r"""{{ (()=>{ const r=$('PG: Duplicado Fechado').first().json || {}; const v=$('Validar Fiscal').first().json || {}; const esc=s=>"'"+String(s??'').replace(/'/g,"''")+"'"; const id=Number(r.id || v.id || 0); return `
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
INSERT INTO workflow_eventos(ticket_id,workflow,node_name,fase,acao,status_evento,status_anterior,status_novo,erro,inicio_em,fim_em)
VALUES(${id},'WF04','PG: Duplicado Fechado','DECISAO_FISCAL','DUPLICIDADE_CONFIRMADA','OK',${esc(v.status_nome || '')},'Fechado',FALSE,NOW(),NOW());
SELECT ${id} AS ticket_id;`; })() }}"""
    _ensure_node(_pg_node("v9-wf04-pg-obs-confirmado", "PG: Evento Fiscal Confirmado", [1376, 144], registrar_confirmado))
    _connect_parallel("PG: Duplicado Fechado", "PG: Evento Fiscal Confirmado")

    registrar_rejeitado = r"""{{ (()=>{ const r=$('PG: Limpar Duplicidade').first().json || {}; const v=$('Validar Fiscal').first().json || {}; const esc=s=>"'"+String(s??'').replace(/'/g,"''")+"'"; const id=Number(r.id || v.id || 0); return `
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
INSERT INTO workflow_eventos(ticket_id,workflow,node_name,fase,acao,status_evento,status_anterior,status_novo,erro,inicio_em,fim_em)
VALUES(${id},'WF04','PG: Limpar Duplicidade','DECISAO_FISCAL','DUPLICIDADE_REJEITADA','OK',${esc(v.status_nome || '')},'Pendente',FALSE,NOW(),NOW());
SELECT ${id} AS ticket_id;`; })() }}"""
    _ensure_node(_pg_node("v9-wf04-pg-obs-rejeitado", "PG: Evento Fiscal Rejeitado", [1056, 560], registrar_rejeitado))
    _connect_parallel("PG: Limpar Duplicidade", "PG: Evento Fiscal Rejeitado")


_apply_robustness_updates()


def _apply_queue_classification_updates() -> None:
    _node("PG: Limpar Duplicidade")["parameters"]["query"] = """
UPDATE tickets_processados
SET status_num=4,
    status_nome='Pendente',
    em_aprovacao_fiscal=FALSE,
    aprovacao_decidida_em=NOW(),
    decisao_fiscal='REJEITOU_DUP',
    fiscal_decision_token=NULL,
    fiscal_token_expira_em=NULL,
    classificacao=NULL,
    classificacao_final=NULL,
    duplicado_de_id=NULL,
    motivo_classificacao=NULL,
    triagem_status='AGUARDANDO_FILA_CLASSIFICACAO',
    fila_etapa='CLASSIFICACAO',
    fila_liberar_em=NULL,
    fila_reservada_em=NULL,
    ultima_acao_workflow='WF04_PREPAROU_CLASSIFICACAO',
    log_workflow=COALESCE(log_workflow,'[]'::jsonb)
      || jsonb_build_object('wf','WF04','acao','REJEITOU_DUP','ts',NOW())
WHERE id=$1::bigint
RETURNING
  id,titulo,descricao,tipo_servico,localizacao,solicitante,
  email_solicitante,status_num,status_nome,data_abertura,data_ultima_mudanca;
"""

    obsolete = {"Preparar Reclassificação", "Chamar WF03"}
    WORKFLOW["nodes"] = [
        node for node in WORKFLOW["nodes"] if node.get("name") not in obsolete
    ]
    for source in obsolete:
        WORKFLOW["connections"].pop(source, None)
    for outputs in WORKFLOW["connections"].values():
        for branch in outputs.get("main", []):
            branch[:] = [
                edge for edge in branch if edge.get("node") not in obsolete
            ]

    enfileirar_query = r"""{{ (() => {
const id=Number($('PG: Limpar Duplicidade').first().json.id || 0);
const log=JSON.stringify({wf:'WF04',acao:'ENFILEIROU_CLASSIFICACAO',ts:new Date().toISOString()}).replace(/'/g,"''");
return `UPDATE tickets_processados
SET triagem_status='PENDENTE_FILA_IA',
    fila_etapa='CLASSIFICACAO',
    fila_enfileirada_em=NOW(),
    fila_liberar_em=NULL,
    fila_reservada_em=NULL,
    fila_ultimo_erro=NULL,
    ultima_acao_workflow='WF04_ENFILEIROU_CLASSIFICACAO',
    log_workflow=COALESCE(log_workflow,'[]'::jsonb) || '${log}'::jsonb,
    atualizado_em=NOW()
WHERE id=${id}
  AND triagem_status='AGUARDANDO_FILA_CLASSIFICACAO'
RETURNING id,triagem_status,fila_etapa;`;
})() }}"""
    _ensure_node(
        _pg_node(
            "v9-wf04-enfileirar-classificacao",
            "PG: Enfileirar Classificação",
            [2448, -112],
            enfileirar_query,
        )
    )
    WORKFLOW["connections"]["GLPI: Encerrar Sessão Fiscal Rejeição"] = {
        "main": [
            [
                {
                    "node": "PG: Enfileirar Classificação",
                    "type": "main",
                    "index": 0,
                }
            ]
        ]
    }
    WORKFLOW["connections"]["PG: Enfileirar Classificação"] = {
        "main": [
            [
                {
                    "node": "LOG: Fim Fiscal Rejeição",
                    "type": "main",
                    "index": 0,
                }
            ]
        ]
    }


_apply_queue_classification_updates()


def _apply_post_confirmation_updates() -> None:
    webhook = _node("Webhook Fiscal")
    webhook["parameters"]["httpMethod"] = "POST"

    extract = _node("Extrair Decisão")["parameters"]["jsCode"]
    old_query = "const q=$json.query || {};"
    if old_query not in extract:
        raise ValueError("Leitura da decisão fiscal não encontrada")
    _node("Extrair Decisão")["parameters"]["jsCode"] = extract.replace(
        old_query,
        "const q={...($json.query || {}),...($json.body || {})};",
        1,
    )

    preview_js = r"""
const q=$json.query || {};
const esc=value=>String(value ?? '').replace(/[&<>\"']/g,ch=>({
  '&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'
}[ch]));
const decisao=String(q.decisao || '').toLowerCase().trim();
const chamadoId=Number(q.chamado_id);
const refId=Number(q.ref_id || 0);
const token=String(q.token || '').trim();
const valido=['confirmar','nao_duplicado'].includes(decisao) &&
  Number.isInteger(chamadoId) && chamadoId>0 && /^[a-f0-9]{32,128}$/i.test(token);
const rotulo=decisao==='confirmar' ? 'Confirmar duplicidade' : 'Marcar como não duplicado';
const campos={decisao,chamado_id:chamadoId,token};
if (refId>0) campos.ref_id=refId;
const hidden=Object.entries(campos).map(([key,value])=>
  '<input type="hidden" name="'+esc(key)+'" value="'+esc(value)+'">'
).join('');
const html=valido
  ? '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Confirmar decisão fiscal</title></head><body><main><h1>Confirmar decisão fiscal</h1><p>Chamado #'+esc(chamadoId)+': '+esc(rotulo)+'.</p><p>Esta página não altera o chamado até você pressionar o botão.</p><form method="post" action="/webhook/fiscal-decisao-fiscal-ic-2026">'+hidden+'<button type="submit">'+esc(rotulo)+'</button></form></main></body></html>'
  : '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Link inválido</title></head><body><h1>Link inválido ou incompleto</h1><p>Revise o chamado diretamente no GLPI.</p></body></html>';
return [{json:{http_status:valido?200:400,response_html:html}}];
"""
    _ensure_node(
        {
            "parameters": {
                "path": "fiscal-confirmacao-v9",
                "httpMethod": "GET",
                "responseMode": "responseNode",
                "options": {},
            },
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [-1168, -240],
            "id": "v9-wf04-wh-confirmacao",
            "name": "Webhook Fiscal Confirmação",
            "webhookId": "v9-wf04-wh-confirmacao",
        }
    )
    _ensure_node(
        {
            "parameters": {"jsCode": preview_js},
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [-928, -240],
            "id": "v9-wf04-render-confirmacao",
            "name": "Renderizar Confirmação Fiscal",
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
            "position": [-688, -240],
            "id": "v9-wf04-resp-confirmacao",
            "name": "Resp: Confirmação Fiscal",
        }
    )
    WORKFLOW["connections"]["Webhook Fiscal Confirmação"] = {
        "main": [[{"node": "Renderizar Confirmação Fiscal", "type": "main", "index": 0}]]
    }
    WORKFLOW["connections"]["Renderizar Confirmação Fiscal"] = {
        "main": [[{"node": "Resp: Confirmação Fiscal", "type": "main", "index": 0}]]
    }


_apply_post_confirmation_updates()


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
