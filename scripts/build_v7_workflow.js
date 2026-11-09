const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const inputPath = path.join(root, 'n8n', 'workflows', 'Teste01_v6.json');
const outputPath = path.join(root, 'n8n', 'workflows', 'Teste01_v7.json');

const wf = JSON.parse(fs.readFileSync(inputPath, 'utf8'));

function node(name) {
  const found = wf.nodes.find((n) => n.name === name);
  if (!found) throw new Error(`Node not found: ${name}`);
  return found;
}

function upsertNode(newNode) {
  const idx = wf.nodes.findIndex((n) => n.name === newNode.name);
  if (idx >= 0) wf.nodes[idx] = newNode;
  else wf.nodes.push(newNode);
}

function connect(from, outputs) {
  wf.connections[from] = { main: outputs };
}

function one(to, index = 0) {
  return [{ node: to, type: 'main', index }];
}

function emptyOutputs(count) {
  return Array.from({ length: count }, () => []);
}

wf.id = 'TriagemV7Pg20260429';
wf.name = 'Triagem Inteligente de Chamados - v7 (Postgres)';
wf.active = false;
wf.settings = {
  ...(wf.settings || {}),
  executionOrder: 'v1',
  timezone: 'America/Sao_Paulo',
  saveExecutionProgress: true,
  saveManualExecutions: true,
};
wf.meta = {
  ...(wf.meta || {}),
  description:
    'v7: bootstrap/refresh em Postgres, triagem incremental por webhook, decisao fiscal por webhook separado, envio real via Mailpit.',
};

// ---------------------------------------------------------------------
// Triggers and routing
// ---------------------------------------------------------------------
node('T2. Webhook GLPI (Novo Chamado)').parameters.path = 'glpi-ticket-novo-v7';
node('T2. Webhook GLPI (Novo Chamado)').webhookId = 'b1f7e6d2-9a8c-4b13-a4e5-202604290701';

upsertNode({
  parameters: {
    httpMethod: 'GET',
    path: 'triagem-fiscal-duplicidade-v7',
    options: {},
  },
  type: 'n8n-nodes-base.webhook',
  typeVersion: 2,
  position: [-1180, 480],
  id: 'v7-webhook-fiscal-decisao',
  name: 'T4. Webhook Decisao Fiscal (Duplicidade)',
  webhookId: 'b1f7e6d2-9a8c-4b13-a4e5-202604290702',
  notes:
    'Recebe os cliques do fiscal: ?decisao=confirmar|nao_duplicado&chamado_id=ID&ref_id=ID_MATCH',
});

upsertNode({
  parameters: {
    jsCode: `
const q = $json.query || {};
const b = $json.body || {};
const decisao = String(q.decisao ?? b.decisao ?? '').toLowerCase().trim();
const chamadoId = Number(q.chamado_id ?? b.chamado_id ?? q.ticket_id ?? b.ticket_id ?? q.id ?? b.id);
const refId = Number(q.ref_id ?? b.ref_id ?? '');
const fiscalValido = Number.isFinite(chamadoId) && chamadoId > 0 && ['confirmar', 'nao_duplicado'].includes(decisao);

return [{
  json: {
    modo_execucao: 'FISCAL_DECISAO',
    fiscal_valido: fiscalValido,
    decisao,
    chamado_id: fiscalValido ? chamadoId : null,
    chamado_id_sql: fiscalValido ? chamadoId : -1,
    ref_id: Number.isFinite(refId) && refId > 0 ? refId : null,
    recebido_em: new Date().toISOString(),
    mensagem_resposta: fiscalValido
      ? 'Decisao recebida. Processando...'
      : 'Link invalido: informe decisao=confirmar ou decisao=nao_duplicado e chamado_id valido.',
  }
}];
`.trim(),
  },
  type: 'n8n-nodes-base.code',
  typeVersion: 2,
  position: [-940, 480],
  id: 'v7-fd-extrair-decisao',
  name: 'FD1. Extrair Decisao Fiscal',
});

upsertNode({
  parameters: {
    conditions: {
      options: {
        caseSensitive: true,
        leftValue: '',
        typeValidation: 'strict',
        version: 3,
      },
      conditions: [
        {
          id: 'fiscal-valido',
          leftValue: '={{ $json.fiscal_valido }}',
          rightValue: true,
          operator: { type: 'boolean', operation: 'true' },
        },
      ],
      combinator: 'and',
    },
  },
  type: 'n8n-nodes-base.if',
  typeVersion: 2.2,
  position: [-720, 480],
  id: 'v7-fd-link-valido',
  name: 'FD1b. Link Fiscal Valido?',
});

// Switch mode now accepts the fiscal webhook path too.
const modeExpr =
  "={{ (() => { try { return $('N3. Resolver Modo Final').first().json.modo_execucao; } catch (e) {} try { return $('FD1. Extrair Decisao Fiscal').first().json.modo_execucao; } catch (e) {} return ''; })() }}";
const switchMode = node('M0. Switch: Modo');
switchMode.parameters.rules.values.forEach((rule) => {
  rule.conditions.conditions[0].leftValue = modeExpr;
});
switchMode.parameters.rules.values.push({
  conditions: {
    options: {
      caseSensitive: true,
      leftValue: '',
      typeValidation: 'strict',
      version: 3,
    },
    conditions: [
      {
        leftValue: modeExpr,
        rightValue: 'FISCAL_DECISAO',
        operator: { type: 'string', operation: 'equals' },
        id: 'c-f',
      },
    ],
    combinator: 'and',
  },
  renameOutput: true,
  outputKey: 'FISCAL_DECISAO',
});

connect('T4. Webhook Decisao Fiscal (Duplicidade)', [one('FD1. Extrair Decisao Fiscal')]);
connect('FD1. Extrair Decisao Fiscal', [one('FD1b. Link Fiscal Valido?')]);
connect('FD1b. Link Fiscal Valido?', [
  one('G1. GLPI: Iniciar Sessao'),
  [],
]);
connect('M0. Switch: Modo', [
  one('I1. GLPI: Buscar TUDO (Inicial)'),
  one('C1. GLPI: Buscar Ticket do Webhook'),
  one('S1. GLPI: Refresh Pend/Planej/Atrib/Soluc/Fechado'),
  one('FD2. PG: Buscar Registro Fiscal'),
]);

// ---------------------------------------------------------------------
// Code fixes and business rules
// ---------------------------------------------------------------------
node('F1. Filtrar: Apenas Novos para Triar').parameters.jsCode = `
// SCHEDULE apenas atualiza o BD. A triagem IA roda na primeira carga/manual
// para Novo/Pendente e, depois disso, pelo webhook somente para Novo.
const ctx = $('N3. Resolver Modo Final').first().json;
if (ctx.modo_execucao === 'SCHEDULE') return [];

const items = $input.all();
const allE1 = $('E1. Estruturar Chamados').all();
const saida = [];

for (const it of items) {
  const upsert = it.json;
  const orig = allE1.find(x => Number(x.json.chamado.id) === Number(upsert.id));
  if (!orig) continue;
  const c = orig.json.chamado;

  const statusPermitidos = ctx.modo_execucao === 'INCREMENTAL' ? [1] : [1, 4];
  if (!statusPermitidos.includes(c.status_num)) continue;
  if (upsert.triagem_status && !['PENDENTE', 'CLASSIFICANDO'].includes(upsert.triagem_status)) continue;
  if (upsert.em_aprovacao_fiscal === true) continue;

  saida.push({ json: { chamado: c, _origem_fluxo: 'TRIAGEM' } });
}
return saida;
`.trim();

const waitBetweenBatches = node('L2. Wait 20s entre lotes');
waitBetweenBatches.parameters = { amount: 20 };
waitBetweenBatches.type = 'n8n-nodes-base.wait';
waitBetweenBatches.typeVersion = 1.1;
waitBetweenBatches.notes = 'Espera 20 segundos antes de chamar IA para o proximo item. Reduz risco de rate limit em bootstrap grande.';

node('D1. PG: Historico para Dedup').parameters.query = `
WITH atual AS (
  SELECT id, titulo, descricao, tipo_servico, localizacao, data_abertura
    FROM tickets_processados
   WHERE id = {{ $json.chamado.id }}
),
historico AS (
  SELECT h.*
    FROM tickets_processados h
   WHERE h.id <> {{ $json.chamado.id }}
     AND (
       h.status_num = 4
       OR (h.status_num IN (2,3,5,6) AND h.data_abertura >= NOW() - INTERVAL '90 days')
     )
),
rankeado AS (
  SELECT h.id, h.titulo, h.descricao, h.tipo_servico, h.localizacao,
         h.solicitante, h.email_solicitante, h.status_num, h.status_nome,
         h.data_abertura, h.data_ultima_mudanca,
         (
           CASE WHEN lower(coalesce(h.localizacao,'')) = lower(coalesce(a.localizacao,'')) AND coalesce(h.localizacao,'') <> '' THEN 40 ELSE 0 END +
           CASE WHEN lower(coalesce(h.tipo_servico,'')) = lower(coalesce(a.tipo_servico,'')) AND coalesce(h.tipo_servico,'') <> '' THEN 15 ELSE 0 END +
           CASE WHEN lower(coalesce(h.titulo,'')) = lower(coalesce(a.titulo,'')) AND coalesce(h.titulo,'') <> '' THEN 30 ELSE 0 END +
           CASE WHEN h.data_abertura BETWEEN a.data_abertura - INTERVAL '30 days' AND a.data_abertura + INTERVAL '30 days' THEN 10 ELSE 0 END +
           COALESCE(ts_rank_cd(
             to_tsvector('portuguese', coalesce(h.titulo,'') || ' ' || coalesce(h.descricao,'')),
             plainto_tsquery('portuguese', left(coalesce(a.titulo,'') || ' ' || coalesce(a.descricao,''), 500))
           ) * 100, 0)
         ) AS score_pre_ia
    FROM historico h
    CROSS JOIN atual a
)
SELECT id, titulo, descricao, tipo_servico, localizacao, solicitante, email_solicitante,
       status_num, status_nome, data_abertura, data_ultima_mudanca, score_pre_ia
  FROM rankeado
 ORDER BY score_pre_ia DESC, data_abertura DESC
 LIMIT 60;
`.trim();
node('D1. PG: Historico para Dedup').alwaysOutputData = true;

node('D2. Montar Payload IA').parameters.jsCode = `
// Monta payload para IA. D1 usa alwaysOutputData para permitir historico vazio.
const entrada = $input.all();
const itensHist = entrada
  .map(i => i.json)
  .filter(h => Number.isFinite(Number(h.id)) && Number(h.id) > 0);
const atual = $('L1. SplitInBatches (3)').item.json.chamado;
return [{
  json: {
    chamado_atual: atual,
    historico_abertos: itensHist,
  }
}];
`.trim();

const d4Node = node('D4. Normalizar Dedup');
const d4OldFallback = `
  if (duplicidadeOut.eh_duplicado === null || duplicidadeOut.eh_duplicado === undefined) {
    duplicidadeOut = dedupHeuristica(atual, historico);
  }
`.trim();
const d4NewFallback = `
  const heuristicaLocal = dedupHeuristica(atual, historico);
  if (duplicidadeOut.eh_duplicado === null || duplicidadeOut.eh_duplicado === undefined) {
    duplicidadeOut = heuristicaLocal;
  } else if (duplicidadeOut.eh_duplicado === false && heuristicaLocal.eh_duplicado) {
    duplicidadeOut = {
      ...heuristicaLocal,
      justificativa_para_fiscal: 'Regra local marcou duplicidade mesmo apos IA negar: ' + heuristicaLocal.justificativa_para_fiscal,
      caracteristicas_match: ['ia_negou_mas_regra_local_marcou', ...(heuristicaLocal.caracteristicas_match || [])],
    };
  }
`.trim();
if (!d4Node.parameters.jsCode.includes(d4OldFallback)) {
  throw new Error('D4 fallback block not found');
}
d4Node.parameters.jsCode = d4Node.parameters.jsCode.replace(d4OldFallback, d4NewFallback);

const d3 = node('D3. IA: Verificar Duplicidade');
d3.retryOnFail = true;
d3.maxTries = 3;
d3.waitBetweenTries = 20000;
d3.alwaysOutputData = false;
d3.onError = 'continueErrorOutput';

const cl2 = node('CL2. IA: OBRA vs Manutencao + Executor');
cl2.retryOnFail = true;
cl2.maxTries = 3;
cl2.waitBetweenTries = 20000;
cl2.alwaysOutputData = false;
cl2.onError = 'continueErrorOutput';

node('DUP2. Preparar Corpo do Followup').parameters.jsCode = `
const src = $('D4. Normalizar Dedup').item.json;
const c = src.chamado;
const dup = src.duplicidade;
const ref = dup.chamado_referencia || {};
const refId = dup.chamado_referencia_id;
const titulo = (c.titulo || '').startsWith('[Duplicado]') ? c.titulo : \`[Duplicado] \${c.titulo || 'Chamado #' + c.id}\`;
const baseUrl = 'http://localhost:5678/webhook/triagem-fiscal-duplicidade-v7';
const linkConfirmar = \`\${baseUrl}?decisao=confirmar&chamado_id=\${encodeURIComponent(c.id)}&ref_id=\${encodeURIComponent(refId || '')}\`;
const linkNaoDuplicado = \`\${baseUrl}?decisao=nao_duplicado&chamado_id=\${encodeURIComponent(c.id)}&ref_id=\${encodeURIComponent(refId || '')}\`;

const corpo = [
  '[TRIAGEM_IA][PENDENTE_DECISAO_DUPLICIDADE]',
  '',
  \`Chamado #\${c.id} foi marcado como POSSIVEL DUPLICATA pela IA.\`,
  '',
  \`Match identificado: chamado #\${ref.id || refId || 'N/A'}\`,
  \`Titulo do match: \${ref.titulo || 'N/A'}\`,
  \`Status do match: \${ref.status_nome || 'N/A'}\`,
  \`Descricao do match: \${ref.descricao || 'N/A'}\`,
  \`Localizacao do match: \${ref.localizacao || 'N/A'}\`,
  \`Solicitante do match: \${ref.solicitante || 'N/A'} <\${ref.email_solicitante || 'sem-email'}>\`,
  '',
  \`Motivo: \${dup.justificativa_para_fiscal}\`,
  \`Caracteristicas: \${(dup.caracteristicas_match||[]).join(', ') || 'N/A'}\`,
  '',
  \`Solicitante atual: \${c.solicitante} <\${c.email_solicitante || 'sem-email'}>\`,
  \`Localizacao atual: \${c.localizacao}\`,
  \`Tipo servico atual: \${c.tipo_servico}\`,
  \`Descricao atual: \${c.descricao}\`,
  '',
  'DECIDA clicando em um dos links abaixo:',
  \`Duplicado: \${linkConfirmar}\`,
  \`Nao duplicado: \${linkNaoDuplicado}\`,
].join('\\n');

return [{ json: { ...src, _titulo_novo: titulo, _followup_corpo: corpo, _link_confirmar: linkConfirmar, _link_nao_duplicado: linkNaoDuplicado } }];
`.trim();

node('DUP1. PG: Marcar Em Aprovacao Fiscal').parameters.query = `
UPDATE tickets_processados
   SET status_num=4, status_nome='Pendente',
       triagem_status='PENDENTE',
       em_aprovacao_fiscal=TRUE,
       aprovacao_iniciada_em=NOW(),
       classificacao='POSSIVEL_DUPLICADO',
       duplicado_de_id={{ $json.duplicidade.chamado_referencia_id || 'NULL' }},
       motivo_classificacao=$1,
       ultima_acao_workflow='AGUARDANDO_DECISAO_FISCAL_DUPLICIDADE'
 WHERE id={{ $json.chamado.id }}
RETURNING id;
`.trim();

node('CL1. PG: Marcar BD (CLASSIFICANDO)').parameters.query = `
UPDATE tickets_processados
   SET status_num=4, status_nome='Pendente',
       triagem_status='CLASSIFICANDO',
       ultima_acao_workflow='CLASSIFICANDO_OBRA_MANUTENCAO'
 WHERE id={{ $json.chamado.id }}
RETURNING id, titulo, descricao, tipo_servico, localizacao,
          solicitante, email_solicitante, status_num, status_nome,
          data_abertura, data_ultima_mudanca,
          '{{ (($json._origem_fluxo || $json.chamado._origem_fluxo || "TRIAGEM") + "").split("'").join("''") }}'::text AS origem_fluxo;
`.trim();

node('CL3. Normalizar Classificacao').parameters.jsCode = `
function tryParse(t){ try { return JSON.parse(t); } catch { return null; } }
function extrair(j){
  let d = j;
  const t1 = d?.content?.parts?.[0]?.text;
  if (typeof t1 === 'string') { const p = tryParse(t1); if (p) d = p; }
  const t2 = d?.message?.content;
  if (typeof t2 === 'string') { const p = tryParse(t2); if (p) d = p; }
  return d;
}
function heuristica(ch){
  const txt = [ch.titulo, ch.descricao, ch.localizacao].join(' ').toLowerCase();
  const obraKeys = ['construcao','construir','ampliacao','ampliar','nova sala','novo predio','obra','reforma completa','pavimentacao'];
  const sobKeys = ['ar-condicionado','ar condicionado','split','chiller','elevador','incendio','servidor','switch','projetor','laboratorio especializado'];
  const isObra = obraKeys.some(k => txt.includes(k));
  if (isObra) {
    return {
      tipo: 'OBRA', executor: 'DDI_DG', categoria: 'OBRA_CIVIL',
      justificativa: 'Fallback sem IA: texto indica criacao/ampliacao/reforma estrutural.',
      mensagem_solicitante: 'Sua solicitacao foi classificada como OBRA e encaminhada ao setor responsavel (DDI/DG).'
    };
  }
  const isSob = sobKeys.some(k => txt.includes(k));
  return {
    tipo: 'MANUTENCAO',
    executor: isSob ? 'SOB_DEMANDA' : 'DEMO',
    categoria: isSob ? 'MANUTENCAO_ESPECIALIZADA' : 'MANUTENCAO_PREDIAL',
    justificativa: isSob
      ? 'Fallback sem IA: item especializado identificado no texto.'
      : 'Fallback sem IA: reparo/manutencao predial simples.',
    mensagem_solicitante: 'Sua solicitacao foi classificada como manutencao e encaminhada para atendimento.'
  };
}
const saida = [];
for (const it of $input.all()) {
  const r = extrair(it.json) || {};
  const cl1Row = $('CL1. PG: Marcar BD (CLASSIFICANDO)').item.json;
  const chamado = {
    id: cl1Row.id,
    titulo: cl1Row.titulo,
    descricao: cl1Row.descricao,
    tipo_servico: cl1Row.tipo_servico,
    localizacao: cl1Row.localizacao,
    solicitante: cl1Row.solicitante,
    email_solicitante: cl1Row.email_solicitante,
    status_num: cl1Row.status_num,
    status_nome: cl1Row.status_nome,
    data_abertura: cl1Row.data_abertura,
    data_ultima_mudanca: cl1Row.data_ultima_mudanca,
    _origem_fluxo: cl1Row.origem_fluxo || 'TRIAGEM',
  };

  let tipo = String(r.tipo || '').toUpperCase();
  let executor = String(r.executor || '').toUpperCase();
  const tipoVal = ['OBRA','MANUTENCAO'].includes(tipo);
  const execVal = ['DDI_DG','DEMO','SOB_DEMANDA'].includes(executor);

  let out;
  if (!tipoVal || !execVal || (tipo === 'OBRA' && executor !== 'DDI_DG')) {
    out = heuristica(chamado);
  } else {
    if (tipo === 'OBRA') executor = 'DDI_DG';
    out = {
      tipo,
      executor,
      categoria: r.categoria || '',
      justificativa: r.justificativa || '',
      mensagem_solicitante: r.mensagem_solicitante || ''
    };
  }

  saida.push({ json: { chamado, classificacao: out } });
}
return saida;
`.trim();

// ---------------------------------------------------------------------
// HTTP body expression fixes
// ---------------------------------------------------------------------
function glpiInputExpr(fields) {
  return `={{ Object.fromEntries([["input", Object.fromEntries([${fields}])]]) }}`;
}

node('DUP4. GLPI: Followup com Links Fiscal').parameters.jsonBody =
  glpiInputExpr('["items_id", $("DUP2. Preparar Corpo do Followup").item.json.chamado.id], ["itemtype", "Ticket"], ["content", $("DUP2. Preparar Corpo do Followup").item.json._followup_corpo]');

node('DUP3. GLPI: Renomear Titulo [Duplicado]').parameters.jsonBody =
  glpiInputExpr('["id", $json.chamado.id], ["name", $json._titulo_novo], ["status", 4]');

node('CL1b. GLPI: Mover para Pendente').parameters.jsonBody =
  glpiInputExpr('["id", $json.id], ["status", 4]');

node('OBRA2. GLPI: Followup com Justificativa ao Solicitante').parameters.jsonBody =
  glpiInputExpr('["items_id", $("CL3. Normalizar Classificacao").item.json.chamado.id], ["itemtype", "Ticket"], ["content", "[TRIAGEM_IA][CLASSIFICADO_COMO_OBRA]\\n\\n" + $("CL3. Normalizar Classificacao").item.json.classificacao.mensagem_solicitante + "\\n\\nA demanda foi encaminhada por e-mail ao DDI/DG e este chamado sera FECHADO no GLPI por nao se tratar de servico da equipe DEMO de manutencao.\\n\\nJustificativa tecnica: " + $("CL3. Normalizar Classificacao").item.json.classificacao.justificativa]');
node('OBRA3. GLPI: Fechar Chamado (status=6)').parameters.url =
  "={{ 'http://host.docker.internal:8080/apirest.php/Ticket/' + $('CL3. Normalizar Classificacao').item.json.chamado.id }}";
node('OBRA3. GLPI: Fechar Chamado (status=6)').parameters.jsonBody =
  glpiInputExpr('["id", $("CL3. Normalizar Classificacao").item.json.chamado.id], ["status", 6]');
node('DEMO1. GLPI: Atribuir (status=2)').parameters.jsonBody =
  glpiInputExpr('["id", $json.chamado.id], ["status", 2]');
node('DEMO2. GLPI: Followup Atribuicao DEMO').parameters.jsonBody =
  glpiInputExpr('["items_id", $("CL3. Normalizar Classificacao").item.json.chamado.id], ["itemtype", "Ticket"], ["content", "[TRIAGEM_IA][ATRIBUIDO_DEMO]\\n\\nClassificado como MANUTENCAO executavel pela equipe DEMO.\\nCategoria sugerida: " + $("CL3. Normalizar Classificacao").item.json.classificacao.categoria + "\\n\\nJustificativa: " + $("CL3. Normalizar Classificacao").item.json.classificacao.justificativa]');
node('SOB1. GLPI: Em Atendimento Planejado (status=3)').parameters.jsonBody =
  glpiInputExpr('["id", $json.chamado.id], ["status", 3]');
node('SOB2. GLPI: Followup Sob Demanda').parameters.jsonBody =
  glpiInputExpr('["items_id", $("CL3. Normalizar Classificacao").item.json.chamado.id], ["itemtype", "Ticket"], ["content", "[TRIAGEM_IA][SOB_DEMANDA]\\n\\nClassificado como MANUTENCAO mas FORA do escopo da equipe DEMO. Necessario contratacao/orcamento externo.\\nCategoria: " + $("CL3. Normalizar Classificacao").item.json.classificacao.categoria + "\\n\\nJustificativa: " + $("CL3. Normalizar Classificacao").item.json.classificacao.justificativa]');
node('DUP7a. GLPI: Fechar Chamado Duplicado (status=6)').parameters.jsonBody =
  glpiInputExpr('["id", $json._chamado_id], ["status", 6]');

// ---------------------------------------------------------------------
// Real email via Mailpit
// ---------------------------------------------------------------------
const obraEmail = node('OBRA1. Enviar Email DDI/DG (Mailpit)');
obraEmail.parameters = {
  fromEmail: 'triagem@campus.local',
  toEmail: 'ddi-dg@campus.local',
  subject: "={{ '[Triagem IA] OBRA detectada - chamado #' + $json.chamado.id }}",
  emailFormat: 'text',
  text:
    "={{ 'Chamado #' + $json.chamado.id + '\\nTitulo: ' + $json.chamado.titulo + '\\nLocalizacao: ' + ($json.chamado.localizacao || 'N/A') + '\\nSolicitante: ' + ($json.chamado.solicitante || 'N/A') + ' <' + ($json.chamado.email_solicitante || 'sem-email') + '>' + '\\n\\nClassificacao: OBRA' + '\\nCategoria: ' + ($json.classificacao.categoria || 'N/A') + '\\nJustificativa: ' + ($json.classificacao.justificativa || 'N/A') + '\\n\\nDescricao:\\n' + ($json.chamado.descricao || '') }}",
  options: {
    appendAttribution: false,
  },
};
obraEmail.type = 'n8n-nodes-base.emailSend';
obraEmail.typeVersion = 2.1;
obraEmail.credentials = {
  smtp: {
    id: 'SMTP_MAILPIT_LOCAL',
    name: 'SMTP Mailpit Local',
  },
};
delete obraEmail.onError;
delete obraEmail.alwaysOutputData;

// Final PG nodes return origin so the fiscal rejection path can respond,
// while the normal batch path loops back to SplitInBatches.
node('OBRA4. PG: Atualizar BD (FECHADO_OBRA)').parameters.query = `
UPDATE tickets_processados
   SET status_num=6, status_nome='Fechado',
       triagem_status='FECHADO_OBRA',
       classificacao='OBRA',
       executor='DDI_DG',
       em_aprovacao_fiscal=FALSE,
       motivo_classificacao=$1,
       triado_em=NOW(),
       ultima_acao_workflow='FECHADO_POR_OBRA'
 WHERE id={{ $('CL3. Normalizar Classificacao').item.json.chamado.id }}
RETURNING id, triagem_status, status_num, status_nome,
          '{{ ($("CL3. Normalizar Classificacao").item.json.chamado._origem_fluxo || "TRIAGEM").split("'").join("''") }}'::text AS origem_fluxo;
`.trim();

node('DEMO3. PG: Atualizar BD (ATRIBUIDO_DEMO)').parameters.query = `
UPDATE tickets_processados
   SET status_num=2, status_nome='Atribuido',
       triagem_status='ATRIBUIDO_DEMO',
       classificacao='MANUTENCAO',
       executor='DEMO',
       em_aprovacao_fiscal=FALSE,
       motivo_classificacao=$1,
       triado_em=NOW(),
       ultima_acao_workflow='ATRIBUIDO_EQUIPE_DEMO'
 WHERE id={{ $('CL3. Normalizar Classificacao').item.json.chamado.id }}
RETURNING id, triagem_status, status_num, status_nome,
          '{{ ($("CL3. Normalizar Classificacao").item.json.chamado._origem_fluxo || "TRIAGEM").split("'").join("''") }}'::text AS origem_fluxo;
`.trim();

node('SOB3. PG: Atualizar BD (ENCAMINHADO_PLANEJADO)').parameters.query = `
UPDATE tickets_processados
   SET status_num=3, status_nome='Planejado',
       triagem_status='ENCAMINHADO_PLANEJADO',
       classificacao='MANUTENCAO',
       executor='SOB_DEMANDA',
       em_aprovacao_fiscal=FALSE,
       motivo_classificacao=$1,
       triado_em=NOW(),
       ultima_acao_workflow='ENCAMINHADO_SOB_DEMANDA'
 WHERE id={{ $('CL3. Normalizar Classificacao').item.json.chamado.id }}
RETURNING id, triagem_status, status_num, status_nome,
          '{{ ($("CL3. Normalizar Classificacao").item.json.chamado._origem_fluxo || "TRIAGEM").split("'").join("''") }}'::text AS origem_fluxo;
`.trim();

upsertNode({
  parameters: {
    rules: {
      values: [
        {
          conditions: {
            options: {
              caseSensitive: true,
              leftValue: '',
              typeValidation: 'strict',
              version: 3,
            },
            conditions: [
              {
                leftValue: '={{ $json.origem_fluxo }}',
                rightValue: 'FISCAL_REJEITOU_DUP',
                operator: { type: 'string', operation: 'equals' },
                id: 'origem-fiscal',
              },
            ],
            combinator: 'and',
          },
          renameOutput: true,
          outputKey: 'FISCAL',
        },
        {
          conditions: {
            options: {
              caseSensitive: true,
              leftValue: '',
              typeValidation: 'strict',
              version: 3,
            },
            conditions: [
              {
                leftValue: '={{ $json.origem_fluxo || "TRIAGEM" }}',
                rightValue: 'TRIAGEM',
                operator: { type: 'string', operation: 'equals' },
                id: 'origem-triagem',
              },
            ],
            combinator: 'and',
          },
          renameOutput: true,
          outputKey: 'TRIAGEM',
        },
      ],
    },
    options: {
      fallbackOutput: 'extra',
    },
  },
  type: 'n8n-nodes-base.switch',
  typeVersion: 3.4,
  position: [3880, 260],
  id: 'v7-pos-classificacao-router',
  name: 'Z1. Roteador Pos-Classificacao',
});

// ---------------------------------------------------------------------
// Fiscal decision branch
// ---------------------------------------------------------------------
upsertNode({
  parameters: {
    operation: 'executeQuery',
    query: `
WITH encontrado AS (
  SELECT id, titulo, descricao, tipo_servico, localizacao, solicitante, email_solicitante,
         status_num, status_nome, data_abertura, data_ultima_mudanca,
         triagem_status, classificacao, duplicado_de_id, motivo_classificacao,
         em_aprovacao_fiscal
    FROM tickets_processados
   WHERE id = {{ $('FD1. Extrair Decisao Fiscal').first().json.chamado_id_sql }}
),
alvo AS (
  SELECT {{ $('FD1. Extrair Decisao Fiscal').first().json.chamado_id_sql }}::bigint AS id
)
SELECT COALESCE(e.id, alvo.id) AS id,
       e.titulo, e.descricao, e.tipo_servico, e.localizacao,
       e.solicitante, e.email_solicitante, e.status_num, e.status_nome,
       e.data_abertura, e.data_ultima_mudanca, e.triagem_status,
       e.classificacao, e.duplicado_de_id, e.motivo_classificacao,
       COALESCE(e.em_aprovacao_fiscal, FALSE) AS em_aprovacao_fiscal,
       (e.id IS NOT NULL) AS encontrado,
       '{{ $("FD1. Extrair Decisao Fiscal").first().json.decisao }}'::text AS decisao,
       {{ $('FD1. Extrair Decisao Fiscal').first().json.ref_id || 'NULL' }}::bigint AS ref_id
  FROM alvo
  LEFT JOIN encontrado e ON e.id = alvo.id;
`.trim(),
    options: {},
  },
  type: 'n8n-nodes-base.postgres',
  typeVersion: 2.6,
  position: [560, 520],
  id: 'v7-fd-pg-buscar-registro',
  name: 'FD2. PG: Buscar Registro Fiscal',
  credentials: {
    postgres: {
      id: 'PG_TRIAGEM',
      name: 'Postgres Triagem',
    },
  },
});

upsertNode({
  parameters: {
    jsCode: `
const r = $json;
let acao = 'INVALIDO';
let mensagem = '';

if (!r.encontrado) {
  mensagem = \`Chamado #\${r.id} nao encontrado no banco de triagem.\`;
} else if (!r.em_aprovacao_fiscal) {
  mensagem = \`Chamado #\${r.id} nao esta aguardando decisao fiscal de duplicidade.\`;
} else if (r.decisao === 'confirmar') {
  acao = 'CONFIRMAR';
  mensagem = \`Duplicidade confirmada pelo fiscal para o chamado #\${r.id}.\`;
} else if (r.decisao === 'nao_duplicado') {
  acao = 'REJEITAR';
  mensagem = \`Duplicidade rejeitada pelo fiscal para o chamado #\${r.id}. O chamado seguira para classificacao.\`;
} else {
  mensagem = 'Decisao fiscal invalida.';
}

return [{ json: { ...r, acao, mensagem_resposta: mensagem } }];
`.trim(),
  },
  type: 'n8n-nodes-base.code',
  typeVersion: 2,
  position: [800, 520],
  id: 'v7-fd-validar-registro',
  name: 'FD3. Validar Registro Fiscal',
});

upsertNode({
  parameters: {
    rules: {
      values: [
        {
          conditions: {
            options: { caseSensitive: true, leftValue: '', typeValidation: 'strict', version: 3 },
            conditions: [
              {
                leftValue: '={{ $json.acao }}',
                rightValue: 'CONFIRMAR',
                operator: { type: 'string', operation: 'equals' },
                id: 'fd-confirmar',
              },
            ],
            combinator: 'and',
          },
          renameOutput: true,
          outputKey: 'CONFIRMAR',
        },
        {
          conditions: {
            options: { caseSensitive: true, leftValue: '', typeValidation: 'strict', version: 3 },
            conditions: [
              {
                leftValue: '={{ $json.acao }}',
                rightValue: 'REJEITAR',
                operator: { type: 'string', operation: 'equals' },
                id: 'fd-rejeitar',
              },
            ],
            combinator: 'and',
          },
          renameOutput: true,
          outputKey: 'NAO_DUPLICADO',
        },
        {
          conditions: {
            options: { caseSensitive: true, leftValue: '', typeValidation: 'strict', version: 3 },
            conditions: [
              {
                leftValue: '={{ $json.acao }}',
                rightValue: 'INVALIDO',
                operator: { type: 'string', operation: 'equals' },
                id: 'fd-invalido',
              },
            ],
            combinator: 'and',
          },
          renameOutput: true,
          outputKey: 'INVALIDO',
        },
      ],
    },
    options: {},
  },
  type: 'n8n-nodes-base.switch',
  typeVersion: 3.4,
  position: [1040, 520],
  id: 'v7-fd-switch-acao',
  name: 'FD4. Switch Decisao Fiscal',
});

function glpiHeaders() {
  return {
    parameters: [
      { name: 'App-Token', value: 'bdEeA72JRgRrGMnBSop06TYGCRwusEhKs0uOobUw' },
      { name: 'Session-Token', value: "={{ $('G1. GLPI: Iniciar Sessao').first().json.session_token }}" },
    ],
  };
}

upsertNode({
  parameters: {
    method: 'POST',
    url: 'http://host.docker.internal:8080/apirest.php/ITILFollowup',
    sendHeaders: true,
    headerParameters: glpiHeaders(),
    sendBody: true,
    specifyBody: 'json',
    jsonBody:
      glpiInputExpr('["items_id", $json.id], ["itemtype", "Ticket"], ["content", "[TRIAGEM_IA][DUPLICIDADE_CONFIRMADA_FISCAL]\\n\\nO fiscal confirmou que este chamado e duplicado do chamado #" + ($json.duplicado_de_id || $json.ref_id || "N/A") + ".\\n\\nMotivo original da IA: " + ($json.motivo_classificacao || "N/A")]'),
    options: {},
  },
  type: 'n8n-nodes-base.httpRequest',
  typeVersion: 4.2,
  position: [1320, 360],
  id: 'v7-fd-followup-confirmado',
  name: 'FD5. GLPI: Followup Duplicidade Confirmada',
});

upsertNode({
  parameters: {
    method: 'PUT',
    url: "={{ 'http://host.docker.internal:8080/apirest.php/Ticket/' + $('FD3. Validar Registro Fiscal').item.json.id }}",
    sendHeaders: true,
    headerParameters: glpiHeaders(),
    sendBody: true,
    specifyBody: 'json',
    jsonBody: glpiInputExpr('["id", $("FD3. Validar Registro Fiscal").item.json.id], ["status", 6]'),
    options: {},
  },
  type: 'n8n-nodes-base.httpRequest',
  typeVersion: 4.2,
  position: [1560, 360],
  id: 'v7-fd-glpi-fechar-confirmado',
  name: 'FD6. GLPI: Fechar Duplicado Confirmado',
});

upsertNode({
  parameters: {
    operation: 'executeQuery',
    query: `
UPDATE tickets_processados
   SET status_num=6, status_nome='Fechado',
       triagem_status='DUPLICADO_FECHADO',
       em_aprovacao_fiscal=FALSE,
       aprovacao_decidida_em=NOW(),
       decisao_fiscal='CONFIRMOU_DUP',
       classificacao='DUPLICADO',
       triado_em=NOW(),
       ultima_acao_workflow='FECHADO_DUPLICIDADE_CONFIRMADA'
 WHERE id={{ $('FD3. Validar Registro Fiscal').item.json.id }}
RETURNING id, triagem_status, status_num, status_nome;
`.trim(),
    options: {},
  },
  type: 'n8n-nodes-base.postgres',
  typeVersion: 2.6,
  position: [1800, 360],
  id: 'v7-fd-pg-confirmado',
  name: 'FD7. PG: Confirmar Duplicidade Fiscal',
  credentials: {
    postgres: {
      id: 'PG_TRIAGEM',
      name: 'Postgres Triagem',
    },
  },
});

upsertNode({
  parameters: {
    operation: 'executeQuery',
    query: `
UPDATE tickets_processados
   SET em_aprovacao_fiscal=FALSE,
       aprovacao_decidida_em=NOW(),
       decisao_fiscal='REJEITOU_DUP',
       classificacao=NULL,
       motivo_classificacao=NULL,
       ultima_acao_workflow='FISCAL_REJEITOU_DUPLICIDADE_SEGUE_CLASSIFICACAO'
 WHERE id={{ $json.id }}
RETURNING id, titulo, descricao, tipo_servico, localizacao,
          solicitante, email_solicitante, status_num, status_nome,
          data_abertura, data_ultima_mudanca,
          'FISCAL_REJEITOU_DUP'::text AS origem_fluxo;
`.trim(),
    options: {},
  },
  type: 'n8n-nodes-base.postgres',
  typeVersion: 2.6,
  position: [1320, 560],
  id: 'v7-fd-pg-rejeitar',
  name: 'FD8. PG: Limpar Aprovacao e Reclassificar',
  credentials: {
    postgres: {
      id: 'PG_TRIAGEM',
      name: 'Postgres Triagem',
    },
  },
});

upsertNode({
  parameters: {
    method: 'PUT',
    url: "={{ 'http://host.docker.internal:8080/apirest.php/Ticket/' + $json.id }}",
    sendHeaders: true,
    headerParameters: glpiHeaders(),
    sendBody: true,
    specifyBody: 'json',
    jsonBody: glpiInputExpr('["id", $json.id], ["name", String($json.titulo || "").replace("[Duplicado] ", "").replace("[Duplicado]", "")]'),
    options: {},
  },
  type: 'n8n-nodes-base.httpRequest',
  typeVersion: 4.2,
  position: [1440, 560],
  id: 'v7-fd-glpi-restaurar-titulo',
  name: 'FD8b. GLPI: Restaurar Titulo Nao Duplicado',
});

upsertNode({
  parameters: {
    jsCode: `
const r = $('FD8. PG: Limpar Aprovacao e Reclassificar').item.json;
return [{
  json: {
    _origem_fluxo: r.origem_fluxo || 'FISCAL_REJEITOU_DUP',
    chamado: {
      id: r.id,
      titulo: r.titulo,
      descricao: r.descricao,
      tipo_servico: r.tipo_servico,
      localizacao: r.localizacao,
      solicitante: r.solicitante,
      email_solicitante: r.email_solicitante,
      status_num: r.status_num,
      status_nome: r.status_nome,
      data_abertura: r.data_abertura,
      data_ultima_mudanca: r.data_ultima_mudanca,
      _origem_fluxo: r.origem_fluxo || 'FISCAL_REJEITOU_DUP',
    }
  }
}];
`.trim(),
  },
  type: 'n8n-nodes-base.code',
  typeVersion: 2,
  position: [1680, 560],
  id: 'v7-fd-formatar-reclassificacao',
  name: 'FD9. Reformatar Rejeicao para Classificacao',
});

// ---------------------------------------------------------------------
// Connections
// ---------------------------------------------------------------------
connect('D3. IA: Verificar Duplicidade', [
  one('D4. Normalizar Dedup'),
  one('D4. Normalizar Dedup'),
]);
connect('D5. E Duplicado?', [
  one('DUP1. PG: Marcar Em Aprovacao Fiscal'),
  one('CL1. PG: Marcar BD (CLASSIFICANDO)'),
  one('D4. Normalizar Dedup'),
]);
connect('DUP4. GLPI: Followup com Links Fiscal', [one('L1. SplitInBatches (3)')]);

connect('CL2. IA: OBRA vs Manutencao + Executor', [
  one('CL3. Normalizar Classificacao'),
  one('CL3. Normalizar Classificacao'),
]);
connect('OBRA4. PG: Atualizar BD (FECHADO_OBRA)', [one('Z1. Roteador Pos-Classificacao')]);
connect('DEMO3. PG: Atualizar BD (ATRIBUIDO_DEMO)', [one('Z1. Roteador Pos-Classificacao')]);
connect('SOB3. PG: Atualizar BD (ENCAMINHADO_PLANEJADO)', [one('Z1. Roteador Pos-Classificacao')]);
connect('Z1. Roteador Pos-Classificacao', [
  [],
  one('L1. SplitInBatches (3)'),
  one('L1. SplitInBatches (3)'),
]);

connect('FD2. PG: Buscar Registro Fiscal', [one('FD3. Validar Registro Fiscal')]);
connect('FD3. Validar Registro Fiscal', [one('FD4. Switch Decisao Fiscal')]);
connect('FD4. Switch Decisao Fiscal', [
  one('FD5. GLPI: Followup Duplicidade Confirmada'),
  one('FD8. PG: Limpar Aprovacao e Reclassificar'),
  [],
]);
connect('FD5. GLPI: Followup Duplicidade Confirmada', [one('FD6. GLPI: Fechar Duplicado Confirmado')]);
connect('FD6. GLPI: Fechar Duplicado Confirmado', [one('FD7. PG: Confirmar Duplicidade Fiscal')]);
connect('FD8. PG: Limpar Aprovacao e Reclassificar', [one('FD8b. GLPI: Restaurar Titulo Nao Duplicado')]);
connect('FD8b. GLPI: Restaurar Titulo Nao Duplicado', [one('FD9. Reformatar Rejeicao para Classificacao')]);
connect('FD9. Reformatar Rejeicao para Classificacao', [one('CL1. PG: Marcar BD (CLASSIFICANDO)')]);

// Old wait-based nodes are intentionally left in the file disabled and unconnected
// as migration breadcrumbs, but the v7 flow does not use them.
['DUP5. Aguardar Decisao Fiscal (infinito)', 'DUP6. Decisao Fiscal: Confirmou?', 'DUP6a. Extrair IDs da Decisao', 'DUP7a. GLPI: Fechar Chamado Duplicado (status=6)', 'DUP7b. PG: Atualizar BD (DUPLICADO_FECHADO)', 'DUP8. PG: Limpar em_aprovacao (Fiscal Rejeitou)', 'DUP9. Reformatar para Classificacao', 'D3b. Wait 20s para Retry IA'].forEach((name) => {
  const n = wf.nodes.find((x) => x.name === name);
  if (n) n.disabled = true;
  delete wf.connections[name];
});

// Make sure no remaining connection points to disabled wait-based migration nodes.
for (const [from, value] of Object.entries(wf.connections)) {
  if (!value.main) continue;
  value.main = value.main.map((output) =>
    output.filter(
      (edge) =>
        ![
          'DUP5. Aguardar Decisao Fiscal (infinito)',
          'DUP6. Decisao Fiscal: Confirmou?',
          'DUP6a. Extrair IDs da Decisao',
          'DUP7a. GLPI: Fechar Chamado Duplicado (status=6)',
          'DUP7b. PG: Atualizar BD (DUPLICADO_FECHADO)',
          'DUP8. PG: Limpar em_aprovacao (Fiscal Rejeitou)',
          'DUP9. Reformatar para Classificacao',
          'D3b. Wait 20s para Retry IA',
        ].includes(edge.node)
    )
  );
}

fs.writeFileSync(outputPath, `${JSON.stringify(wf, null, 2)}\n`, 'utf8');
console.log(`Wrote ${outputPath}`);
