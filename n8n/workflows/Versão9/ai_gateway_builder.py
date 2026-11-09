"""Gera o nó Code que executa a política multi-modelo com proveniência.

O JavaScript retornado é executado dentro do n8n. Segredos são lidos somente
do ambiente do container e nunca são incluídos na saída do item.
"""

from __future__ import annotations

import json


def build_gateway_js(*, task: str, prompt: str, schema: dict) -> str:
    if task not in {"DEDUPLICACAO", "CLASSIFICACAO"}:
        raise ValueError(f"Tarefa de IA inválida: {task}")

    template = r"""
const payload = $input.first().json || {};
const TASK = __TASK__;
const PROMPT_TEMPLATE = __PROMPT__;
const RESPONSE_SCHEMA = __SCHEMA__;

// Configuração operacional não secreta congelada no artefato publicável.
// Segredos ficam fora do Code node e são injetados pelos proxies internos.
const STATIC_CONFIG = Object.freeze({
  IA_CONFIANCA_MINIMA:'0.65',
  IA_EXECUTION_MODE:'OPERATIONAL',
  IA_FAILOVER_ENABLED:'false',
  IA_FIXED_MODEL_ROLE:'LOCAL',
  IA_GENERATION_SEED:'20260702',
  IA_HTTP_TIMEOUT_MS:'30000',
  IA_LOCAL_BASE_URL:'http://local-ai-credential-proxy:8080',
  IA_LOCAL_TIMEOUT_MS:'60000',
  IA_MODEL_LOCAL:'local-hybrid-v1.8.0',
  IA_MODEL_SECONDARY:'gemini-3.5-flash',
  IA_OPERATIONAL_SEQUENCE:'LOCAL',
  IA_PROVIDER_BACKOFF_BASE_MS:'1500',
  IA_PROVIDER_BACKOFF_MAX_MS:'15000',
  IA_PROVIDER_MAX_RETRIES:'3',
  LOCAL_AI_EMBED_BACKEND:'pytorch_fp32',
  LOCAL_AI_EMBED_MODEL_REVISION:'835ad14087e140460703cf0fae09f97d469d65c2'
});

function envValue(name, fallback='') {
  return Object.prototype.hasOwnProperty.call(STATIC_CONFIG, name)
    ? String(STATIC_CONFIG[name]) : String(fallback);
}

function truthy(value) {
  return ['1','true','yes','sim','on'].includes(String(value || '').toLowerCase().trim());
}

function boundedInteger(value, fallback, minimum, maximum) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(minimum, Math.min(maximum, Math.floor(parsed)));
}

function safeError(value) {
  return String(value?.message || value || 'Erro desconhecido')
    .replace(/(authorization|api[_ -]?key|token)\s*[:=]\s*[^\s,;]+/gi, '$1=[REDACTED]')
    .slice(0, 2000);
}

function positiveIntegerOrNull(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? Math.floor(number) : null;
}

function headerValue(headers, name) {
  if (!headers) return null;
  try {
    if (typeof headers.get === 'function') {
      const value = headers.get(name);
      if (value !== undefined && value !== null && value !== '') return value;
    }
  } catch (e) {}
  const expected = String(name || '').toLowerCase();
  for (const [key,value] of Object.entries(headers || {})) {
    if (String(key).toLowerCase() === expected) return value;
  }
  return null;
}

function parseRetryAfter(value) {
  if (value === undefined || value === null || value === '') return null;
  const numeric = Number(value);
  if (Number.isFinite(numeric) && numeric >= 0) return Math.ceil(numeric);
  const when = Date.parse(String(value));
  if (!Number.isFinite(when)) return null;
  return Math.max(0, Math.ceil((when - Date.now()) / 1000));
}

function bodyText(value) {
  if (typeof value === 'string') return value;
  try { return JSON.stringify(value ?? {}); } catch (e) { return ''; }
}

function transportMetadata(error, providerBody=null) {
  const response = error?.response || error?.cause?.response || {};
  const body = providerBody ?? response?.data ?? response?.body ?? error?.body ?? null;
  const nestedError = body?.error || error?.error || {};
  const status = positiveIntegerOrNull(
    response?.statusCode ?? response?.status ??
    error?.statusCode ?? error?.status ?? error?.cause?.statusCode ??
    nestedError?.code
  );
  const headers = response?.headers || error?.headers || error?.cause?.headers || {};
  let retryAfterSeconds = parseRetryAfter(headerValue(headers, 'retry-after'));
  if (retryAfterSeconds === null) {
    const match = bodyText(body).match(/retryDelay[^0-9]*([0-9]+(?:\.[0-9]+)?)s/i);
    if (match) retryAfterSeconds = Math.ceil(Number(match[1]));
  }
  const rawCode = String(error?.code || error?.cause?.code || '').toUpperCase();
  const timeout = ['ECONNABORTED','ETIMEDOUT','ESOCKETTIMEDOUT'].includes(rawCode)
    || /timeout|timed out/i.test(String(error?.message || ''));
  const retryable = status === 429
    || [408,425,500,502,503,504].includes(status)
    || timeout
    || ['ECONNRESET','ECONNREFUSED','EAI_AGAIN','ENETUNREACH','ENOTFOUND','UND_ERR_CONNECT_TIMEOUT'].includes(rawCode);
  const errorType = status === 429 ? 'RATE_LIMIT'
    : [500,502,503,504].includes(status) ? 'SERVICE_UNAVAILABLE'
    : timeout ? 'TIMEOUT'
    : status !== null && status >= 400 && status < 500 ? 'PERMANENT_HTTP'
    : 'TRANSPORT';
  return {
    http_status:status,
    retry_after_seconds:retryAfterSeconds,
    retryable,
    error_type:errorType,
    error_code:status !== null ? `HTTP_${status}` : (rawCode || 'TRANSPORT_ERROR')
  };
}

function parseJson(value) {
  if (value && typeof value === 'object') return value;
  if (typeof value !== 'string') return null;
  const clean = value.replace(/```json/gi, '').replace(/```/g, '').trim();
  try { return JSON.parse(clean); } catch (e) {}
  const match = clean.match(/\{[\s\S]*\}/);
  if (!match) return null;
  try { return JSON.parse(match[0]); } catch (e) { return null; }
}

function extractParsed(raw) {
  const candidates = [
    raw?.result,
    raw?.content?.parts?.[0]?.text,
    raw?.candidates?.[0]?.content?.parts?.[0]?.text,
    raw?.response?.candidates?.[0]?.content?.parts?.[0]?.text,
    raw?.choices?.[0]?.message?.content,
    raw?.message?.content,
    raw?.output,
    raw?.text,
    raw?.response?.text
  ];
  for (const candidate of candidates) {
    const parsed = parseJson(candidate);
    if (parsed) return parsed;
  }
  return parseJson(raw);
}

function validateDedup(parsed) {
  const data = parsed?.duplicidade || parsed;
  if (!data || typeof data !== 'object') return {valid:false, reason:'JSON de deduplicação ausente'};
  const rawDecision = data.eh_duplicado ?? data.ehDuplicado ?? data.duplicado ?? data.is_duplicate;
  if (rawDecision === undefined || rawDecision === null) {
    return {valid:false, reason:'eh_duplicado ausente'};
  }
  const decision = typeof rawDecision === 'boolean'
    ? rawDecision
    : ['true','sim','yes','1'].includes(String(rawDecision).toLowerCase());
  const probs = data.probabilidades || data.probabilities || {};
  const pd = Number(probs.duplicado ?? probs.DUPLICADO ?? probs.duplicate);
  const pn = Number(probs.nao_duplicado ?? probs.NAO_DUPLICADO ?? probs['não_duplicado'] ?? probs.not_duplicate);
  if (!Number.isFinite(pd) || !Number.isFinite(pn) || pd < 0 || pd > 1 || pn < 0 || pn > 1 || Math.abs(pd + pn - 1) > 0.001) {
    return {valid:false, reason:'vetor probabilístico de deduplicação inválido'};
  }
  if (Math.abs(pd-pn) > 0.000001 && decision !== (pd > pn)) {
    return {valid:false, reason:'decisão diverge da maior probabilidade'};
  }
  const confidence = Number(data.confianca ?? data.confidence ?? data.score);
  if (!Number.isFinite(confidence) || confidence < 0 || confidence > 1) {
    return {valid:false, reason:'confiança de deduplicação inválida'};
  }
  const reference = Number(data.chamado_referencia_id ?? data.chamadoReferenciaId ?? data.reference_id);
  if (decision && (!Number.isInteger(reference) || reference <= 0)) {
    return {valid:false, reason:'duplicidade sem referência positiva'};
  }
  return {valid:true, reason:null};
}

function validateClassification(parsed) {
  if (!parsed || typeof parsed !== 'object') return {valid:false, reason:'JSON de classificação ausente'};
  const type = String(parsed.tipo || '').toUpperCase().trim();
  const executor = String(parsed.executor || '').toUpperCase().trim().replace(/[\s-]+/g,'_');
  const validPair = (
    (type === 'OBRA' && executor === 'DDI_DG') ||
    (type === 'MANUTENCAO' && ['DEMO','SOB_DEMANDA'].includes(executor)) ||
    (type === 'TRIAGEM_MANUAL' && executor === 'FISCAL')
  );
  if (!validPair) return {valid:false, reason:'par tipo/executor inválido'};
  const classes = ['OBRA','DEMO','SOB_DEMANDA','TRIAGEM_MANUAL'];
  const probs = parsed.probabilidades || parsed.probabilities || {};
  let sum = 0;
  for (const label of classes) {
    const value = Number(probs[label]);
    if (!Number.isFinite(value) || value < 0 || value > 1) {
      return {valid:false, reason:'vetor probabilístico de classificação inválido'};
    }
    sum += value;
  }
  if (Math.abs(sum - 1) > 0.001) return {valid:false, reason:'probabilidades de classificação não somam 1'};
  const declared = type === 'OBRA' ? 'OBRA'
    : type === 'MANUTENCAO' && executor === 'DEMO' ? 'DEMO'
    : type === 'MANUTENCAO' && executor === 'SOB_DEMANDA' ? 'SOB_DEMANDA'
    : 'TRIAGEM_MANUAL';
  const largest = classes.reduce((best,label) => Number(probs[label]) > Number(probs[best]) ? label : best, classes[0]);
  if (declared !== largest) return {valid:false, reason:'classe diverge da maior probabilidade'};
  const confidence = Number(parsed.confianca ?? parsed.confidence ?? parsed.score);
  if (!Number.isFinite(confidence) || confidence < 0 || confidence > 1) {
    return {valid:false, reason:'confiança de classificação inválida'};
  }
  return {valid:true, reason:null};
}

function validateLocalRuntime(raw) {
  const metadata = raw?.metadata;
  const embedding = metadata?.embedding;
  const decisionPath = String(metadata?.decision_path || '');
  const deterministicPaths = new Set([
    'deterministic_insufficient_information',
    'deterministic_contradiction',
    'deterministic_out_of_scope',
    'deterministic_specialized_asset',
    'deterministic_empty_history'
  ]);
  const hybridPaths = new Set(['hybrid_model','hybrid_model_abstention']);
  const features = metadata?.features && typeof metadata.features === 'object'
    ? metadata.features : {};
  const expectedRuntime = envValue('LOCAL_AI_EMBED_BACKEND','pytorch_fp32').toLowerCase().trim();
  const expectedBackend = expectedRuntime === 'pytorch_fp32'
    ? 'granite_embedding_pytorch_fp32' : `granite_embedding_${expectedRuntime}`;
  const expectedRevision = envValue(
    'LOCAL_AI_EMBED_MODEL_REVISION',
    '835ad14087e140460703cf0fae09f97d469d65c2'
  ).trim();
  if (!metadata || typeof metadata !== 'object') {
    return {valid:false,reason:'Metadados científicos do backend local ausentes',error_code:'LOCAL_METADATA_MISSING'};
  }
  if (metadata.pipeline_evaluation_eligible !== true) {
    return {valid:false,reason:'Caminho local não é elegível para avaliação do pipeline congelado',error_code:'LOCAL_PIPELINE_NOT_ELIGIBLE'};
  }
  if (deterministicPaths.has(decisionPath)) {
    if (metadata.candidate_evaluation_eligible === true) {
      return {valid:false,reason:'Regra determinística não pode alegar uso do candidato estatístico',error_code:'LOCAL_DECISION_PATH_MISMATCH'};
    }
    return {valid:true,reason:null};
  }
  if (!hybridPaths.has(decisionPath)) {
    return {valid:false,reason:'decision_path local não pertence ao pipeline congelado',error_code:'LOCAL_DECISION_PATH_INVALID'};
  }
  if (TASK === 'CLASSIFICACAO') {
    const labels = ['OBRA','DEMO','SOB_DEMANDA','TRIAGEM_MANUAL'];
    const semanticClass = String(features.semantic_class_prediction || '').toUpperCase();
    const semanticProbabilities = features.semantic_probabilities;
    if (!labels.includes(semanticClass) || !semanticProbabilities || typeof semanticProbabilities !== 'object') {
      return {valid:false,reason:'Metadados semânticos do candidato local ausentes',error_code:'LOCAL_SEMANTIC_METADATA_INVALID'};
    }
    let semanticSum = 0;
    for (const label of labels) {
      const value = Number(semanticProbabilities[label]);
      if (!Number.isFinite(value) || value < 0 || value > 1) {
        return {valid:false,reason:'Probabilidades semânticas locais inválidas',error_code:'LOCAL_SEMANTIC_METADATA_INVALID'};
      }
      semanticSum += value;
    }
    if (Math.abs(semanticSum - 1) > 0.001) {
      return {valid:false,reason:'Probabilidades semânticas locais não somam 1',error_code:'LOCAL_SEMANTIC_METADATA_INVALID'};
    }
    const semanticWinner = labels.reduce(
      (best,label) => Number(semanticProbabilities[label]) > Number(semanticProbabilities[best]) ? label : best,
      labels[0]
    );
    if (semanticWinner !== semanticClass) {
      return {valid:false,reason:'Classe semântica local diverge da maior probabilidade',error_code:'LOCAL_SEMANTIC_METADATA_INVALID'};
    }
  }
  if (TASK === 'DEDUPLICACAO' && decisionPath === 'hybrid_model_abstention') {
    const rawProbability = Number(features.duplicate_probability_before_abstention);
    if (!Number.isFinite(rawProbability) || rawProbability < 0 || rawProbability > 1) {
      return {valid:false,reason:'Probabilidade bruta pré-abstenção ausente',error_code:'LOCAL_SEMANTIC_METADATA_INVALID'};
    }
  }
  if (metadata.candidate_evaluation_eligible !== true || !embedding || typeof embedding !== 'object') {
    return {valid:false,reason:'Decisão model-based sem proveniência elegível do candidato',error_code:'LOCAL_CANDIDATE_NOT_ELIGIBLE'};
  }
  if (String(embedding.backend || '') !== expectedBackend) {
    return {
      valid:false,
      reason:`Backend local divergente: esperado ${expectedBackend}, recebido ${embedding.backend || 'ausente'}`,
      error_code:'LOCAL_RUNTIME_MISMATCH'
    };
  }
  if (
    String(embedding.runtime_backend || '').toLowerCase() !== expectedRuntime ||
    String(embedding.precision || '').toLowerCase() !== 'fp32'
  ) {
    return {valid:false,reason:'Runtime local não comprova PyTorch FP32',error_code:'LOCAL_PRECISION_MISMATCH'};
  }
  if (Number(embedding.dimension) !== 384) {
    return {valid:false,reason:'Granite local não retornou 384 dimensões',error_code:'LOCAL_DIMENSION_MISMATCH'};
  }
  if (expectedRevision && String(embedding.model_revision || '') !== expectedRevision) {
    return {valid:false,reason:'Revisão do Granite local diverge da revisão congelada',error_code:'LOCAL_REVISION_MISMATCH'};
  }
  if (!/^[a-f0-9]{64}$/i.test(String(embedding.model_tree_sha256 || ''))) {
    return {valid:false,reason:'Hash da árvore do Granite local ausente ou inválido',error_code:'LOCAL_MODEL_HASH_INVALID'};
  }
  if (
    metadata.fallback_used === true || embedding.fallback_used === true ||
    embedding.development_only === true || embedding.scientific_eligible !== true
  ) {
    return {valid:false,reason:'Backend local utilizou fallback ou modo de desenvolvimento',error_code:'LOCAL_DEVELOPMENT_FALLBACK'};
  }
  return {valid:true,reason:null};
}

function validateRaw(raw, config=null) {
  const parsed = extractParsed(raw);
  if (!parsed) return {valid:false, reason:'resposta não contém JSON válido'};
  const schemaValidation = TASK === 'DEDUPLICACAO'
    ? validateDedup(parsed) : validateClassification(parsed);
  if (!schemaValidation.valid) return schemaValidation;
  if (config?.provider === 'local-native') return validateLocalRuntime(raw);
  return schemaValidation;
}

function modelHistory(config) {
  const remoteHistory = Array.isArray(payload.historico) ? payload.historico : [];
  if (TASK === 'DEDUPLICACAO' && benchmark) {
    return Array.isArray(payload.historico_benchmark) ? payload.historico_benchmark : [];
  }
  if (TASK !== 'DEDUPLICACAO' || config?.provider !== 'local-native') return remoteHistory;
  return Array.isArray(payload.historico_local) ? payload.historico_local : remoteHistory;
}

function modelClassificationPayload() {
  const compact = payload.chamado_modelo;
  return compact && typeof compact === 'object' ? compact : payload;
}

function renderPrompt(config=null) {
  let text = String(PROMPT_TEMPLATE || '');
  if (text.startsWith('=')) text = text.slice(1);
  const confidence = Number(envValue('IA_CONFIANCA_MINIMA', '0.65'));
  text = text.split('{{ Number($env.IA_CONFIANCA_MINIMA || 0.65) }}')
    .join(String(Number.isFinite(confidence) ? confidence : 0.65));
  if (TASK === 'DEDUPLICACAO') {
    text = text.split('{{ JSON.stringify($json.chamado_atual) }}')
      .join(JSON.stringify(payload.chamado_atual || {}));
    text = text.split('{{ JSON.stringify($json.historico) }}')
      .join(JSON.stringify(modelHistory(config)));
  } else {
    text = text.split('{{ JSON.stringify($json) }}').join(JSON.stringify(modelClassificationPayload()));
  }
  return text;
}

function usageFor(provider, raw) {
  if (provider === 'google') {
    const usage = raw?.usageMetadata || {};
    return {
      input_tokens:Number(usage.promptTokenCount || 0) || null,
      output_tokens:Number(usage.candidatesTokenCount || 0) || null,
      total_tokens:Number(usage.totalTokenCount || 0) || null
    };
  }
  const usage = raw?.usage || {};
  return {
    input_tokens:Number(usage.prompt_tokens || 0) || null,
    output_tokens:Number(usage.completion_tokens || 0) || null,
    total_tokens:Number(usage.total_tokens || 0) || null
  };
}

const context = TASK === 'DEDUPLICACAO' ? (payload.chamado_atual || {}) : payload;
const runId = String(context.run_id || context.experiment_run_id || '').trim();
const split = String(context.experiment_split || '').toUpperCase().trim();
const experimentConfig = context.experiment_generation_config && typeof context.experiment_generation_config === 'object'
  ? context.experiment_generation_config : {};
const executionMode = String(
  context.ia_execution_mode || experimentConfig.ia_execution_mode || envValue('IA_EXECUTION_MODE','OPERATIONAL')
).toUpperCase().trim();
const researchMode = ['EXPERIMENTAL','VALIDATION','VALIDACAO','CALIBRATION','CALIBRACAO','BENCHMARK'].includes(executionMode);
const experimental = Boolean(runId) || researchMode;
const benchmark = executionMode === 'BENCHMARK' || ['TEST','TESTE','BENCHMARK'].includes(split);
function candidateIds(items) {
  return Array.isArray(items) ? items.map(item=>String(item?.id ?? '')) : [];
}
function sameCandidateOrder(left, right) {
  const a=candidateIds(left), b=candidateIds(right);
  return a.length===b.length && a.every((value,index)=>value===b[index]);
}
const candidatePolicy = payload.candidate_policy && typeof payload.candidate_policy==='object'
  ? payload.candidate_policy : {};
const benchmarkHistory = Array.isArray(payload.historico_benchmark) ? payload.historico_benchmark : null;
const pairedCandidateSetValid = TASK !== 'DEDUPLICACAO' || !benchmark || Boolean(
  benchmarkHistory && benchmarkHistory.length <= 20 &&
  candidatePolicy.mode === 'BENCHMARK_PAIRED_FROZEN' &&
  candidatePolicy.benchmark_paired === true &&
  candidatePolicy.same_list_and_order === true &&
  Number(candidatePolicy.configured_remote_limit) === 20 &&
  Number(candidatePolicy.configured_local_limit) === 20 &&
  sameCandidateOrder(payload.historico, benchmarkHistory) &&
  sameCandidateOrder(payload.historico_local, benchmarkHistory) &&
  sameCandidateOrder(candidatePolicy.candidate_ids?.map(id=>({id})), benchmarkHistory)
);
const requestedRole = String(
  context.ia_fixed_model_role || experimentConfig.ia_fixed_model_role || envValue('IA_FIXED_MODEL_ROLE','LOCAL')
).toUpperCase().trim();
// Mantido como cadeia remota canônica para compatibilidade e auditoria histórica.
const roles = ['LOCAL','SECONDARY'];
const supportedRoles = [...roles];
const requestedRoleValid = supportedRoles.includes(requestedRole);
const fixedRole = supportedRoles.includes(requestedRole) ? requestedRole : 'LOCAL';
const failoverRequested = truthy(envValue('IA_FAILOVER_ENABLED','false'));
const failoverAllowed = failoverRequested && !experimental && !benchmark;
const expectedModel = String(
  context.ia_expected_model || experimentConfig.ia_expected_model || experimentConfig.model || ''
).trim();
const seed = Number(envValue('IA_GENERATION_SEED','20260702')) || 20260702;
const ticketId = Number(context.id || context.ticket_id || 0) || null;
const cycleId = `${TASK}-${ticketId || 'NA'}-${Date.now()}-${Math.random().toString(16).slice(2)}`;

const localBaseUrl = envValue('IA_LOCAL_BASE_URL','http://local-ai-credential-proxy:8080').replace(/\/+$/, '');
const localEndpointPath = TASK === 'DEDUPLICACAO' ? '/v1/deduplicate' : '/v1/classify';
const providers = {
  SECONDARY: {
    role:'SECONDARY', provider:'google', model:envValue('IA_MODEL_SECONDARY','gemini-3.5-flash'),
    key:envValue('GEMINI_API_KEY_SECONDARY', envValue('GEMINI_API_KEY','')), thinking_profile:'provider_default'
  },
  LOCAL: {
    role:'LOCAL', provider:'local-native', model:envValue('IA_MODEL_LOCAL','local-hybrid-v1.8.0'),
    key:envValue('IA_LOCAL_API_TOKEN',''), thinking_profile:'disabled', requires_key:false,
    endpoint:`${localBaseUrl}${localEndpointPath}?include_metadata=1`,
    timeout_ms:boundedInteger(envValue('IA_LOCAL_TIMEOUT_MS','60000'),60000,2000,120000)
  }
};
const fixedProvider = providers[fixedRole] || providers.LOCAL;
const frozenModelDeclared = Boolean(expectedModel);
const modelMatchesExperiment = !expectedModel || fixedProvider.model === expectedModel;
const policyViolation = (experimental || benchmark) && (
  !requestedRoleValid || !frozenModelDeclared || !modelMatchesExperiment || !pairedCandidateSetValid
);
function remotePolicyChain() {
  const startAt = Math.max(0,roles.indexOf(fixedRole));
  const chain = policyViolation ? [] : (failoverAllowed ? roles.slice(startAt) : [fixedRole]);
  return chain;
}
function operationalChain(role) {
  const configured = envValue('IA_OPERATIONAL_SEQUENCE','').split(',')
    .map(item=>item.trim().toUpperCase())
    .filter((item,index,array)=>supportedRoles.includes(item) && array.indexOf(item)===index);
  if (configured.length > 0) return configured;
  if (role === 'LOCAL') return ['LOCAL'];
  return [role];
}
const chain = policyViolation ? [] : (failoverAllowed ? operationalChain(fixedRole) : [fixedRole]);

async function callProvider(config, order) {
  const startedAt = new Date();
  const startedMs = Date.now();
  const nativeLocalBody = config.provider === 'local-native'
    ? (TASK === 'DEDUPLICACAO'
      ? {chamado_atual:payload.chamado_atual || {},historico:modelHistory(config)}
      : {chamado:modelClassificationPayload()})
    : null;
  const prompt = config.provider === 'local-native' ? '' : renderPrompt(config);
  const inputChars = config.provider === 'local-native'
    ? JSON.stringify(nativeLocalBody).length : prompt.length;
  const modelCandidateTotal = TASK === 'DEDUPLICACAO' ? modelHistory(config).length : null;
  const inputProfile = TASK === 'DEDUPLICACAO'
    ? (benchmark ? 'DEDUP_BENCHMARK_PAIRED_FROZEN'
      : (config.provider === 'local-native' ? 'DEDUP_LOCAL_TOP_K' : 'DEDUP_REMOTE_CANDIDATES'))
    : 'CLASSIFICACAO_COMPACTA';
  const maxProviderAttempts = config.provider === 'local-native'
    ? 1
    : boundedInteger(envValue('IA_PROVIDER_MAX_RETRIES', '3'), 3, 1, 5);
  const baseBackoffMs = boundedInteger(envValue('IA_PROVIDER_BACKOFF_BASE_MS', '1500'), 1500, 500, 30000);
  const maxBackoffMs = boundedInteger(envValue('IA_PROVIDER_BACKOFF_MAX_MS', '15000'), 15000, 1000, 60000);
  const httpTimeoutMs = boundedInteger(envValue('IA_HTTP_TIMEOUT_MS', '30000'), 30000, 5000, 120000);
  let raw = null;
  let transportOk = false;
  let errorCode = null;
  let errorMessage = null;
  let httpStatus = null;
  let retryAfterSeconds = null;
  let retryable = false;
  let errorType = null;
  let endpointUsed = config.endpoint || null;
  let providerAttempt = 0;

  while (providerAttempt < maxProviderAttempts) {
    providerAttempt++;
    raw = null;
    transportOk = false;
    errorCode = null;
    errorMessage = null;
    httpStatus = null;
    retryAfterSeconds = null;
    retryable = false;
    errorType = null;
    endpointUsed = config.endpoint || null;

    try {
      if (config.requires_key !== false && !config.key) {
        errorCode = 'MISSING_CREDENTIAL';
        errorType = 'CONFIGURATION';
        throw new Error(`Credencial ausente para ${config.role}`);
      }
      if (config.provider === 'google') {
        endpointUsed = `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(config.model)}:generateContent`;
        const generationConfig = {
          responseMimeType:'application/json',
          responseJsonSchema:RESPONSE_SCHEMA,
          maxOutputTokens:4096,
          seed
        };
        if (config.role === 'PRIMARY') {
          generationConfig.thinkingConfig = {thinkingLevel:'MEDIUM'};
        }
        raw = await helpers.httpRequest({
          method:'POST',
          url:endpointUsed,
          headers:{'x-goog-api-key':config.key,'Content-Type':'application/json'},
          body:{
            contents:[{role:'user',parts:[{text:prompt}]}],
            generationConfig
          },
          json:true,
          timeout:httpTimeoutMs
        });
      } else if (config.provider === 'local-native') {
        const localHeaders = {'Content-Type':'application/json'};
        if (config.key) localHeaders.Authorization = `Bearer ${config.key}`;
        raw = await helpers.httpRequest({
          method:'POST',
          url:config.endpoint,
          headers:localHeaders,
          body:nativeLocalBody,
          json:true,
          timeout:config.timeout_ms
        });
      } else {
        errorCode = 'UNSUPPORTED_PROVIDER';
        errorType = 'CONFIGURATION';
        throw new Error(`Provedor não suportado: ${config.provider}`);
      }
      if (raw?.error || raw?.errorMessage) {
        const metadata = transportMetadata(raw, raw);
        httpStatus = metadata.http_status;
        retryAfterSeconds = metadata.retry_after_seconds;
        retryable = metadata.retryable;
        errorType = metadata.error_type;
        errorCode = metadata.error_code || String(raw?.error?.status || 'PROVIDER_ERROR');
        errorMessage = safeError(raw?.errorMessage || raw?.error?.message || raw?.error);
        raw = {
          ...raw,
          http_status:httpStatus,
          retry_after_seconds:retryAfterSeconds,
          retryable,
          error_type:errorType
        };
      } else {
        transportOk = true;
      }
    } catch (error) {
      const metadata = transportMetadata(error);
      httpStatus = metadata.http_status;
      retryAfterSeconds = metadata.retry_after_seconds;
      retryable = retryable || metadata.retryable;
      errorType = errorType || metadata.error_type;
      errorCode = errorCode || metadata.error_code;
      errorMessage = safeError(error);
      raw = {
        error:true,errorMessage,errorCode,
        http_status:httpStatus,
        retry_after_seconds:retryAfterSeconds,
        retryable,
        error_type:errorType
      };
    }

    if (!transportOk && retryable && providerAttempt < maxProviderAttempts) {
      const delayMs = Math.min(
        maxBackoffMs,
        retryAfterSeconds !== null
          ? retryAfterSeconds * 1000
          : Math.floor(baseBackoffMs * Math.pow(2, providerAttempt - 1) + Math.random() * 500)
      );
      console.log(`[AI_GATEWAY][BACKOFF] Provedor ${config.role} tentativa ${providerAttempt}/${maxProviderAttempts} falhou (${errorCode || errorType}). Aguardando ${delayMs}ms com backoff exponencial...`);
      await new Promise(resolve => setTimeout(resolve, delayMs));
      continue;
    }
    break;
  }
  const parsedResult = transportOk ? extractParsed(raw) : null;
  const validation = transportOk ? validateRaw(raw, config) : {valid:false,reason:errorMessage};
  if (transportOk && !validation.valid) {
    const localConfigurationError = config.provider === 'local-native' && Boolean(validation.error_code);
    retryable = localConfigurationError ? false : true;
    errorType = localConfigurationError ? 'CONFIGURATION' : 'INVALID_SCHEMA';
    errorCode = validation.error_code || 'INVALID_SCHEMA';
  }
  const endedAt = new Date();
  const usage = usageFor(config.provider, raw);
  return {
    cycle_id:cycleId,
    attempt_order:order,
    role:config.role,
    provider:config.provider,
    model:config.model,
    thinking_profile:config.thinking_profile,
    endpoint:endpointUsed,
    input_profile:inputProfile,
    prompt_chars:prompt.length,
    input_chars:inputChars,
    candidate_count:modelCandidateTotal,
    fallback_used:order > 1,
    started_at:startedAt.toISOString(),
    ended_at:endedAt.toISOString(),
    duration_ms:Math.max(0,Date.now()-startedMs),
    transport_ok:transportOk,
    schema_ok:Boolean(validation.valid),
    status:validation.valid ? 'VALID' : (transportOk ? 'INVALID_SCHEMA' : (errorType || 'TRANSPORT_ERROR')),
    error_code:errorCode,
    error_message:validation.valid ? null : safeError(validation.reason || errorMessage),
    http_status:httpStatus,
    retry_after_seconds:retryAfterSeconds,
    retryable,
    error_type:errorType,
    response_raw:raw,
    result_v9:validation.valid ? parsedResult : null,
    scientific_metadata:config.provider === 'local-native' && raw?.metadata && typeof raw.metadata === 'object'
      ? raw.metadata : null,
    ...usage
  };
}

const attempts = [];
let selected = null;
if (policyViolation) {
  const now = new Date().toISOString();
  const policyCode = !requestedRoleValid ? 'EXPERIMENT_ROLE_INVALID'
    : !frozenModelDeclared ? 'EXPERIMENT_MODEL_NOT_FROZEN'
    : !modelMatchesExperiment ? 'EXPERIMENT_MODEL_MISMATCH'
    : 'BENCHMARK_CANDIDATE_SET_INVALID';
  const policyMessage = !requestedRoleValid
    ? `Papel experimental inválido: ${requestedRole || 'ausente'}`
    : !frozenModelDeclared
      ? 'Modelo experimental esperado não foi congelado'
      : !modelMatchesExperiment
        ? `Modelo congelado ${expectedModel} diverge do papel ${fixedRole} (${fixedProvider.model})`
        : 'Benchmark de deduplicação sem lista pareada, ordenada e congelada de até 20 candidatos';
  attempts.push({
    cycle_id:cycleId,attempt_order:1,role:fixedRole,
    provider:fixedProvider.provider,model:fixedProvider.model,
    thinking_profile:fixedProvider.thinking_profile,fallback_used:false,
    started_at:now,ended_at:now,duration_ms:0,transport_ok:false,schema_ok:false,
    status:'POLICY_ERROR',error_code:policyCode,
    error_message:policyMessage,
    http_status:null,retry_after_seconds:null,retryable:false,error_type:'POLICY',
    response_raw:{error:true,errorCode:policyCode},
    input_tokens:null,output_tokens:null,total_tokens:null
  });
}
for (let index=0; index<chain.length; index++) {
  const attempt = await callProvider(providers[chain[index]], index+1);
  attempts.push(attempt);
  if (attempt.schema_ok) {
    selected = attempt;
    break;
  }
}
const last = selected || attempts[attempts.length-1] || {
  cycle_id:cycleId,attempt_order:0,role:fixedRole,provider:'unknown',model:'unknown',
  response_raw:{error:true,errorMessage:'Nenhum provedor configurado'}
};
const finalRaw = selected
  ? selected.result_v9
  : {error:true,errorMessage:last.error_message || 'Todos os modelos falharam',provider:last.provider,model:last.model};
const retryableFailures = selected ? [] : attempts.filter(item => item.retryable === true);
const retryAfterSeconds = retryableFailures.reduce(
  (maximum,item) => Math.max(maximum,Number(item.retry_after_seconds) || 0), 0
) || null;
const dominantFailure = selected ? {} : (
  retryableFailures.find(item => item.http_status === 429)
  || retryableFailures.find(item => item.error_type === 'SERVICE_UNAVAILABLE')
  || retryableFailures.find(item => item.error_type === 'TIMEOUT')
  || retryableFailures[0]
  || last
);

return [{json:{
  ...payload,
  ia_raw:finalRaw,
  ia_provider:last.provider,
  ia_model:last.model,
  ia_model_role:last.role,
  ia_attempt_order:last.attempt_order,
  ia_cycle_id:cycleId,
  ia_failover_used:Boolean(last.fallback_used),
  ia_attempts:attempts,
  ia_http_status:selected ? null : (dominantFailure.http_status || null),
  ia_retry_after_seconds:selected ? null : retryAfterSeconds,
  ia_retryable:!selected && retryableFailures.length > 0,
  ia_error_type:selected ? null : (dominantFailure.error_type || 'NON_RETRYABLE'),
  ia_policy:{
    execution_mode:executionMode,
    experimental,
    benchmark,
    fixed_role:fixedRole,
    requested_role:requestedRole || null,
    requested_role_valid:requestedRoleValid,
    expected_model:expectedModel || null,
    frozen_model_declared:frozenModelDeclared,
    model_matches_experiment:modelMatchesExperiment,
    paired_candidate_set_valid:pairedCandidateSetValid,
    candidate_policy:candidatePolicy,
    policy_violation:policyViolation,
    failover_requested:failoverRequested,
    failover_allowed:failoverAllowed,
    operational_sequence:operationalChain(fixedRole),
    chain_attempted:attempts.map(item=>item.role),
    local_endpoint:providers.LOCAL.endpoint,
    attempt_input_profiles:attempts.map(item=>({
      role:item.role,input_profile:item.input_profile,prompt_chars:item.prompt_chars,input_chars:item.input_chars,
      candidate_count:item.candidate_count,endpoint:item.endpoint,
      scientific_metadata:item.scientific_metadata || null
    }))
  }
}}];
"""

    return (
        template.replace("__TASK__", json.dumps(task, ensure_ascii=False))
        .replace("__PROMPT__", json.dumps(prompt, ensure_ascii=False))
        .replace("__SCHEMA__", json.dumps(schema, ensure_ascii=False, separators=(",", ":")))
    )
