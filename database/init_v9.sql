-- =============================================================
-- Schema V9 — Banco de triagem de chamados GLPI
-- Executado pelo docker-entrypoint ou pelo workflow WF01
-- =============================================================

CREATE TABLE IF NOT EXISTS tickets_processados (
  id                    BIGINT PRIMARY KEY,
  titulo                TEXT NOT NULL DEFAULT '',
  descricao             TEXT,
  tipo_servico          TEXT,
  tipo_servico_id       BIGINT,
  localizacao           TEXT,
  solicitante           TEXT,
  solicitante_id        BIGINT,
  email_solicitante     TEXT,
  status_num            INTEGER NOT NULL DEFAULT 0,
  status_nome           TEXT NOT NULL DEFAULT '',
  data_abertura         TIMESTAMPTZ,
  data_ultima_mudanca   TIMESTAMPTZ,
  origem_ingestao       TEXT NOT NULL DEFAULT 'SYNC',
  triagem_status        TEXT,
  classificacao         TEXT,
  classificacao_final   TEXT,
  executor              TEXT,
  duplicado_de_id       BIGINT,
  decisao_fiscal        TEXT,
  fiscal_decision_token TEXT,
  fiscal_token_expira_em TIMESTAMPTZ,
  motivo_classificacao  TEXT,
  confianca_ia          NUMERIC(5,4),
  triagem_manual        BOOLEAN DEFAULT FALSE,
  em_aprovacao_fiscal   BOOLEAN DEFAULT FALSE,
  aprovacao_iniciada_em TIMESTAMPTZ,
  aprovacao_decidida_em TIMESTAMPTZ,
  triado_em             TIMESTAMPTZ,
  ultima_acao_workflow  TEXT,
  tentativas_ia_dedup   INTEGER DEFAULT 0,
  tentativas_ia_classificacao INTEGER DEFAULT 0,
  tentativas_ia         INTEGER DEFAULT 0,
  ultimo_erro_ia        TEXT,
  fila_enfileirada_em    TIMESTAMPTZ,
  fila_disponivel_em     TIMESTAMPTZ,
  fila_liberar_em        TIMESTAMPTZ,
  fila_reservada_em      TIMESTAMPTZ,
  fila_tentativas        INTEGER DEFAULT 0,
  fila_ultimo_erro       TEXT,
  fila_etapa             TEXT NOT NULL DEFAULT 'DEDUPLICACAO',
  log_workflow          JSONB DEFAULT '[]'::jsonb,
  wf_version            TEXT DEFAULT 'v9',
  criado_em             TIMESTAMPTZ DEFAULT NOW(),
  atualizado_em         TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS tentativas_ia_dedup INTEGER DEFAULT 0;
ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS tentativas_ia_classificacao INTEGER DEFAULT 0;
ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS tentativas_ia INTEGER DEFAULT 0;
ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS ultimo_erro_ia TEXT;
ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS log_workflow JSONB DEFAULT '[]'::jsonb;
ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS wf_version TEXT DEFAULT 'v9';
ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS classificacao_final TEXT;
ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS tipo_servico_id BIGINT;
ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS solicitante_id BIGINT;
ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS confianca_ia NUMERIC(5,4);
ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS triagem_manual BOOLEAN DEFAULT FALSE;
ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS fiscal_decision_token TEXT;
ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS fiscal_token_expira_em TIMESTAMPTZ;
ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS fila_enfileirada_em TIMESTAMPTZ;
ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS fila_disponivel_em TIMESTAMPTZ;
ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS fila_liberar_em TIMESTAMPTZ;
ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS fila_reservada_em TIMESTAMPTZ;
ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS fila_tentativas INTEGER DEFAULT 0;
ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS fila_ultimo_erro TEXT;
ALTER TABLE tickets_processados ADD COLUMN IF NOT EXISTS fila_etapa TEXT NOT NULL DEFAULT 'DEDUPLICACAO';

CREATE INDEX IF NOT EXISTS idx_tp_status ON tickets_processados(status_num);
CREATE INDEX IF NOT EXISTS idx_tp_data_abertura ON tickets_processados(data_abertura);
CREATE INDEX IF NOT EXISTS idx_tp_mudanca ON tickets_processados(data_ultima_mudanca);
CREATE INDEX IF NOT EXISTS idx_tp_localizacao ON tickets_processados(localizacao);
CREATE INDEX IF NOT EXISTS idx_tp_triagem ON tickets_processados(triagem_status);
CREATE INDEX IF NOT EXISTS idx_tp_aprovacao ON tickets_processados(em_aprovacao_fiscal);
CREATE INDEX IF NOT EXISTS idx_tp_classificacao_final ON tickets_processados(classificacao_final);
CREATE INDEX IF NOT EXISTS idx_tp_tipo_servico_id ON tickets_processados(tipo_servico_id);
CREATE INDEX IF NOT EXISTS idx_tp_solicitante_id ON tickets_processados(solicitante_id);
CREATE INDEX IF NOT EXISTS idx_tp_triagem_manual ON tickets_processados(triagem_manual);
CREATE INDEX IF NOT EXISTS idx_tp_fiscal_decision_token ON tickets_processados(fiscal_decision_token);
CREATE INDEX IF NOT EXISTS idx_tp_fiscal_token_expira ON tickets_processados(fiscal_token_expira_em);
CREATE INDEX IF NOT EXISTS idx_tp_fila_pronta
  ON tickets_processados(triagem_status, fila_disponivel_em, fila_enfileirada_em)
  WHERE triagem_status IN ('PENDENTE_FILA_IA','FILA_IA_LIBERADA');

CREATE TABLE IF NOT EXISTS fila_ia_controle (
  id                    SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  proxima_liberacao_em   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  intervalo_segundos     INTEGER NOT NULL DEFAULT 45,
  lote_tamanho           INTEGER NOT NULL DEFAULT 3,
  atualizado_em          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO fila_ia_controle(id)
VALUES (1)
ON CONFLICT(id) DO NOTHING;

CREATE TABLE IF NOT EXISTS fila_ia_metricas (
  id                    BIGSERIAL PRIMARY KEY,
  run_id                TEXT,
  pendentes             INTEGER NOT NULL DEFAULT 0,
  reservados            INTEGER NOT NULL DEFAULT 0,
  liberados_ciclo       INTEGER NOT NULL DEFAULT 0,
  espera_media_segundos NUMERIC,
  espera_p95_segundos   NUMERIC,
  intervalo_segundos    INTEGER NOT NULL,
  lote_tamanho          INTEGER NOT NULL,
  criado_em             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fila_ia_metricas_run
  ON fila_ia_metricas(run_id, criado_em DESC)
  WHERE run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fila_ia_metricas_criado
  ON fila_ia_metricas(criado_em DESC);

CREATE TABLE IF NOT EXISTS fila_ia_dead_letter (
  id                BIGSERIAL PRIMARY KEY,
  ticket_id         BIGINT NOT NULL,
  etapa             TEXT NOT NULL,
  tentativa_numero  INTEGER NOT NULL,
  erro              TEXT NOT NULL,
  run_id            TEXT,
  case_id           TEXT,
  episode_id        TEXT,
  payload_contexto  JSONB NOT NULL DEFAULT '{}'::jsonb,
  resolvido         BOOLEAN NOT NULL DEFAULT FALSE,
  resolvido_em      TIMESTAMPTZ,
  criado_em         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(ticket_id, etapa, tentativa_numero)
);

CREATE INDEX IF NOT EXISTS idx_fila_ia_dead_letter_aberta
  ON fila_ia_dead_letter(criado_em DESC)
  WHERE resolvido = FALSE;
CREATE INDEX IF NOT EXISTS idx_fila_ia_dead_letter_run
  ON fila_ia_dead_letter(run_id, etapa)
  WHERE run_id IS NOT NULL;

-- Expõe falhas operacionais históricas que não receberam uma dead-letter na
-- versão do workflow vigente à época. A view não fabrica eventos retroativos:
-- ela mantém a lacuna explícita para reconciliação e análise de causa.
CREATE OR REPLACE VIEW vw_erros_ia_sem_dead_letter AS
SELECT
  tp.id AS ticket_id,
  tp.triagem_status,
  tp.fila_etapa,
  tp.fila_tentativas,
  tp.ultimo_erro_ia,
  tp.fila_ultimo_erro,
  tp.atualizado_em
FROM tickets_processados tp
WHERE tp.triagem_status='ERRO_IA'
  AND NOT EXISTS (
    SELECT 1
    FROM fila_ia_dead_letter dlq
    WHERE dlq.ticket_id=tp.id
  );

-- Observabilidade operacional e base para metricas/pesquisa
CREATE TABLE IF NOT EXISTS ia_decisoes (
  id                  BIGSERIAL PRIMARY KEY,
  ticket_id           BIGINT,
  workflow_origem     TEXT NOT NULL,
  etapa               TEXT NOT NULL,
  modelo_ia           TEXT DEFAULT 'Gemini',
  versao_modelo       TEXT,
  prompt_version      TEXT,
  input_hash          TEXT,
  input_resumo        JSONB,
  output_raw          JSONB,
  api_response_raw    JSONB,
  output_normalizado  JSONB,
  predicao            TEXT,
  classe_referencia_id BIGINT,
  confianca           NUMERIC(5,4),
  justificativa       TEXT,
  tempo_resposta_ms   INTEGER,
  tentativa_numero    INTEGER,
  run_id              TEXT,
  case_id             TEXT,
  episode_id          TEXT,
  generation_profile  TEXT,
  operational_config  JSONB,
  probabilidades_validas BOOLEAN,
  referencia_presente_candidatos BOOLEAN,
  total_candidatos    INTEGER,
  provedor_ia         TEXT,
  papel_modelo        TEXT,
  fallback_utilizado  BOOLEAN NOT NULL DEFAULT FALSE,
  ciclo_tentativa     TEXT,
  total_modelos_tentados INTEGER,
  modo_execucao       TEXT,
  elegivel_eficacia_confirmatoria BOOLEAN NOT NULL DEFAULT FALSE,
  erro_ia             BOOLEAN DEFAULT FALSE,
  mensagem_erro       TEXT,
  criado_em           TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ia_decisoes_ticket ON ia_decisoes(ticket_id);
CREATE INDEX IF NOT EXISTS idx_ia_decisoes_etapa ON ia_decisoes(etapa);
CREATE INDEX IF NOT EXISTS idx_ia_decisoes_prompt ON ia_decisoes(prompt_version);
CREATE INDEX IF NOT EXISTS idx_ia_decisoes_modelo ON ia_decisoes(modelo_ia, versao_modelo);
CREATE INDEX IF NOT EXISTS idx_ia_decisoes_criado ON ia_decisoes(criado_em);
CREATE INDEX IF NOT EXISTS idx_ia_decisoes_predicao ON ia_decisoes(predicao);
ALTER TABLE ia_decisoes ADD COLUMN IF NOT EXISTS run_id TEXT;
ALTER TABLE ia_decisoes ADD COLUMN IF NOT EXISTS case_id TEXT;
ALTER TABLE ia_decisoes ADD COLUMN IF NOT EXISTS episode_id TEXT;
ALTER TABLE ia_decisoes ADD COLUMN IF NOT EXISTS generation_profile TEXT;
ALTER TABLE ia_decisoes ADD COLUMN IF NOT EXISTS api_response_raw JSONB;
ALTER TABLE ia_decisoes ADD COLUMN IF NOT EXISTS operational_config JSONB;
ALTER TABLE ia_decisoes ADD COLUMN IF NOT EXISTS probabilidades_validas BOOLEAN;
ALTER TABLE ia_decisoes ADD COLUMN IF NOT EXISTS referencia_presente_candidatos BOOLEAN;
ALTER TABLE ia_decisoes ADD COLUMN IF NOT EXISTS total_candidatos INTEGER;
ALTER TABLE ia_decisoes ADD COLUMN IF NOT EXISTS provedor_ia TEXT;
ALTER TABLE ia_decisoes ADD COLUMN IF NOT EXISTS papel_modelo TEXT;
ALTER TABLE ia_decisoes ADD COLUMN IF NOT EXISTS fallback_utilizado BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE ia_decisoes ADD COLUMN IF NOT EXISTS ciclo_tentativa TEXT;
ALTER TABLE ia_decisoes ADD COLUMN IF NOT EXISTS total_modelos_tentados INTEGER;
ALTER TABLE ia_decisoes ADD COLUMN IF NOT EXISTS modo_execucao TEXT;
ALTER TABLE ia_decisoes ADD COLUMN IF NOT EXISTS elegivel_eficacia_confirmatoria BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_ia_decisoes_run ON ia_decisoes(run_id, etapa);
CREATE INDEX IF NOT EXISTS idx_ia_decisoes_run_etapa_criado
  ON ia_decisoes(run_id, etapa, criado_em DESC)
  WHERE run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ia_decisoes_prompt_modelo
  ON ia_decisoes(prompt_version, versao_modelo, criado_em DESC);
CREATE INDEX IF NOT EXISTS idx_ia_decisoes_proveniencia
  ON ia_decisoes(provedor_ia, versao_modelo, papel_modelo, criado_em DESC);
CREATE INDEX IF NOT EXISTS idx_ia_decisoes_confirmatoria
  ON ia_decisoes(run_id, etapa, elegivel_eficacia_confirmatoria)
  WHERE run_id IS NOT NULL;

-- Uma linha por chamada efetiva a um provedor. A decisão final acima aponta o
-- modelo selecionado; esta tabela preserva também falhas e fallbacks anteriores.
CREATE TABLE IF NOT EXISTS ia_tentativas_modelo (
  id                  BIGSERIAL PRIMARY KEY,
  ia_decisao_id       BIGINT REFERENCES ia_decisoes(id) ON DELETE CASCADE,
  ticket_id           BIGINT,
  run_id              TEXT,
  case_id             TEXT,
  episode_id          TEXT,
  workflow_origem     TEXT NOT NULL,
  etapa               TEXT NOT NULL,
  ciclo_tentativa     TEXT NOT NULL,
  ordem_tentativa     INTEGER NOT NULL CHECK (ordem_tentativa > 0),
  papel_modelo        TEXT NOT NULL,
  provedor_ia         TEXT NOT NULL,
  versao_modelo       TEXT NOT NULL,
  perfil_pensamento   TEXT,
  fallback_utilizado  BOOLEAN NOT NULL DEFAULT FALSE,
  iniciado_em         TIMESTAMPTZ,
  finalizado_em       TIMESTAMPTZ,
  duracao_ms          INTEGER,
  transporte_ok       BOOLEAN,
  schema_ok           BOOLEAN,
  status_tentativa    TEXT NOT NULL,
  codigo_erro         TEXT,
  mensagem_erro       TEXT,
  resposta_raw        JSONB,
  endpoint             TEXT,
  perfil_entrada       TEXT,
  prompt_chars         INTEGER,
  input_chars          INTEGER,
  total_candidatos     INTEGER,
  http_status          INTEGER,
  retry_after_seconds  INTEGER,
  retryable            BOOLEAN,
  tipo_erro            TEXT,
  metadata_cientifica  JSONB,
  input_tokens        INTEGER,
  output_tokens       INTEGER,
  total_tokens        INTEGER,
  politica_execucao   JSONB NOT NULL DEFAULT '{}'::jsonb,
  criado_em           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(ciclo_tentativa, ordem_tentativa)
);

ALTER TABLE ia_tentativas_modelo ADD COLUMN IF NOT EXISTS endpoint TEXT;
ALTER TABLE ia_tentativas_modelo ADD COLUMN IF NOT EXISTS perfil_entrada TEXT;
ALTER TABLE ia_tentativas_modelo ADD COLUMN IF NOT EXISTS prompt_chars INTEGER;
ALTER TABLE ia_tentativas_modelo ADD COLUMN IF NOT EXISTS input_chars INTEGER;
ALTER TABLE ia_tentativas_modelo ADD COLUMN IF NOT EXISTS total_candidatos INTEGER;
ALTER TABLE ia_tentativas_modelo ADD COLUMN IF NOT EXISTS http_status INTEGER;
ALTER TABLE ia_tentativas_modelo ADD COLUMN IF NOT EXISTS retry_after_seconds INTEGER;
ALTER TABLE ia_tentativas_modelo ADD COLUMN IF NOT EXISTS retryable BOOLEAN;
ALTER TABLE ia_tentativas_modelo ADD COLUMN IF NOT EXISTS tipo_erro TEXT;
ALTER TABLE ia_tentativas_modelo ADD COLUMN IF NOT EXISTS metadata_cientifica JSONB;

CREATE INDEX IF NOT EXISTS idx_ia_tentativas_decisao
  ON ia_tentativas_modelo(ia_decisao_id, ordem_tentativa);
CREATE INDEX IF NOT EXISTS idx_ia_tentativas_run
  ON ia_tentativas_modelo(run_id, etapa, criado_em DESC)
  WHERE run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ia_tentativas_modelo
  ON ia_tentativas_modelo(provedor_ia, versao_modelo, status_tentativa, criado_em DESC);

-- A lista de colunas desta view evolui com a auditoria do gateway. PostgreSQL
-- não permite que CREATE OR REPLACE renomeie/reordene colunas existentes;
-- recriá-la é seguro porque views não armazenam linhas e evita quebrar a
-- atualização idempotente de volumes já inicializados.
DROP VIEW IF EXISTS vw_proveniencia_gateway_ia CASCADE;
CREATE VIEW vw_proveniencia_gateway_ia AS
SELECT
  d.id AS ia_decisao_id,d.ticket_id,d.run_id,d.case_id,d.episode_id,
  d.workflow_origem,d.etapa,d.provedor_ia,d.versao_modelo,d.papel_modelo,
  d.predicao,d.erro_ia,d.fallback_utilizado,d.total_modelos_tentados,
  d.modo_execucao,d.elegivel_eficacia_confirmatoria,d.ciclo_tentativa,
  d.tempo_resposta_ms,d.criado_em,
  COUNT(t.id)::int AS tentativas_persistidas,
  COUNT(t.id) FILTER (WHERE t.transporte_ok)::int AS transportes_ok,
  COUNT(t.id) FILTER (WHERE t.schema_ok)::int AS schemas_ok,
  COUNT(t.id) FILTER (WHERE t.fallback_utilizado)::int AS fallbacks_persistidos,
  COUNT(t.id) FILTER (WHERE t.retryable)::int AS falhas_retentaveis,
  COALESCE(
    jsonb_agg(t.metadata_cientifica) FILTER (
      WHERE t.papel_modelo='LOCAL' AND t.metadata_cientifica IS NOT NULL
    ),
    '[]'::jsonb
  ) AS metadata_local,
  COALESCE(SUM(t.input_tokens),0)::bigint AS input_tokens,
  COALESCE(SUM(t.output_tokens),0)::bigint AS output_tokens,
  COALESCE(SUM(t.total_tokens),0)::bigint AS total_tokens
FROM ia_decisoes d
LEFT JOIN ia_tentativas_modelo t ON t.ia_decisao_id=d.id
GROUP BY d.id;

CREATE TABLE IF NOT EXISTS avaliacoes_humanas (
  id                 BIGSERIAL PRIMARY KEY,
  ticket_id          BIGINT,
  etapa              TEXT NOT NULL,
  avaliador          TEXT,
  decisao_ia         TEXT,
  decisao_humana     TEXT,
  classe_correta     TEXT,
  ia_estava_correta  BOOLEAN,
  tipo_erro          TEXT,
  gravidade_erro     TEXT,
  motivo_divergencia TEXT,
  observacao         TEXT,
  avaliacao_token    TEXT,
  avaliacao_token_expira_em TIMESTAMPTZ,
  status_avaliacao   TEXT DEFAULT 'CONCLUIDA',
  origem_amostra     TEXT,
  run_id             TEXT,
  case_id            TEXT,
  episode_id         TEXT,
  fonte_gabarito     TEXT,
  revisao_id         TEXT,
  adjudicada         BOOLEAN DEFAULT FALSE,
  solicitado_em      TIMESTAMPTZ,
  concluido_em       TIMESTAMPTZ,
  avaliado_em        TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE avaliacoes_humanas ADD COLUMN IF NOT EXISTS avaliacao_token TEXT;
ALTER TABLE avaliacoes_humanas ADD COLUMN IF NOT EXISTS avaliacao_token_expira_em TIMESTAMPTZ;
ALTER TABLE avaliacoes_humanas ADD COLUMN IF NOT EXISTS status_avaliacao TEXT DEFAULT 'CONCLUIDA';
ALTER TABLE avaliacoes_humanas ADD COLUMN IF NOT EXISTS origem_amostra TEXT;
ALTER TABLE avaliacoes_humanas ADD COLUMN IF NOT EXISTS solicitado_em TIMESTAMPTZ;
ALTER TABLE avaliacoes_humanas ADD COLUMN IF NOT EXISTS concluido_em TIMESTAMPTZ;
ALTER TABLE avaliacoes_humanas ADD COLUMN IF NOT EXISTS run_id TEXT;
ALTER TABLE avaliacoes_humanas ADD COLUMN IF NOT EXISTS case_id TEXT;
ALTER TABLE avaliacoes_humanas ADD COLUMN IF NOT EXISTS episode_id TEXT;
ALTER TABLE avaliacoes_humanas ADD COLUMN IF NOT EXISTS fonte_gabarito TEXT;
ALTER TABLE avaliacoes_humanas ADD COLUMN IF NOT EXISTS revisao_id TEXT;
ALTER TABLE avaliacoes_humanas ADD COLUMN IF NOT EXISTS adjudicada BOOLEAN DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_avaliacoes_ticket ON avaliacoes_humanas(ticket_id);
CREATE INDEX IF NOT EXISTS idx_avaliacoes_etapa ON avaliacoes_humanas(etapa);
CREATE INDEX IF NOT EXISTS idx_avaliacoes_correta ON avaliacoes_humanas(ia_estava_correta);
CREATE INDEX IF NOT EXISTS idx_avaliacoes_tipo_erro ON avaliacoes_humanas(tipo_erro);
CREATE INDEX IF NOT EXISTS idx_avaliacoes_data ON avaliacoes_humanas(avaliado_em);
CREATE UNIQUE INDEX IF NOT EXISTS idx_avaliacoes_token ON avaliacoes_humanas(avaliacao_token) WHERE avaliacao_token IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_avaliacoes_pendente ON avaliacoes_humanas(ticket_id, etapa) WHERE status_avaliacao = 'PENDENTE';
CREATE INDEX IF NOT EXISTS idx_avaliacoes_status ON avaliacoes_humanas(status_avaliacao);
CREATE INDEX IF NOT EXISTS idx_avaliacoes_run ON avaliacoes_humanas(run_id, etapa);

-- Assessor determinístico usado exclusivamente em execuções sintéticas. A
-- decisão da IA continua em ia_decisoes; esta tabela registra, em outra linha
-- e somente depois da inferência, qual ação do gabarito foi enviada aos mesmos
-- webhooks disponíveis ao fiscal/revisor. Tokens são persistidos apenas como
-- hash e a chave única torna o clique idempotente por realização e etapa.
CREATE TABLE IF NOT EXISTS avaliacao_auto_confirmacoes (
  id                    BIGSERIAL PRIMARY KEY,
  ticket_id             BIGINT NOT NULL CHECK (ticket_id > 0),
  run_id                TEXT NOT NULL CHECK (run_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$'),
  scenario_id           TEXT NOT NULL CHECK (scenario_id ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'),
  realization_id        TEXT NOT NULL CHECK (realization_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$'),
  episode_id            TEXT,
  etapa                  TEXT NOT NULL CHECK (etapa IN ('DEDUPLICACAO','CLASSIFICACAO')),
  tipo_confirmacao       TEXT NOT NULL CHECK (
    tipo_confirmacao IN ('FISCAL_DUPLICIDADE','AVALIACAO_METRICA')
  ),
  ia_decisao_id          BIGINT NOT NULL REFERENCES ia_decisoes(id),
  avaliacao_id           BIGINT REFERENCES avaliacoes_humanas(id),
  predicao_ia            TEXT NOT NULL,
  classe_gabarito        TEXT NOT NULL,
  decisao_webhook        TEXT NOT NULL CHECK (
    decisao_webhook IN ('confirmar','nao_duplicado','correta','incorreta')
  ),
  label_source           TEXT NOT NULL,
  token_hash             TEXT NOT NULL CHECK (token_hash ~ '^[a-f0-9]{64}$'),
  assessor_nonce_hash    TEXT NOT NULL CHECK (assessor_nonce_hash ~ '^[a-f0-9]{64}$'),
  status                 TEXT NOT NULL DEFAULT 'RESERVADA' CHECK (
    status IN ('RESERVADA','ENVIADA','CONFIRMADA','FALHA')
  ),
  tentativas             INTEGER NOT NULL DEFAULT 1 CHECK (tentativas > 0),
  resposta_resumo        TEXT,
  mensagem_erro          TEXT,
  proxima_tentativa_em   TIMESTAMPTZ,
  reservada_em           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  enviada_em             TIMESTAMPTZ,
  confirmada_em          TIMESTAMPTZ,
  atualizado_em          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  criado_em              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(run_id, realization_id, tipo_confirmacao, etapa)
);

CREATE INDEX IF NOT EXISTS idx_auto_confirmacoes_pendentes
  ON avaliacao_auto_confirmacoes(status, proxima_tentativa_em, criado_em)
  WHERE status IN ('RESERVADA','ENVIADA','FALHA');
CREATE INDEX IF NOT EXISTS idx_auto_confirmacoes_run
  ON avaliacao_auto_confirmacoes(run_id, scenario_id, realization_id, etapa);
CREATE UNIQUE INDEX IF NOT EXISTS idx_auto_confirmacoes_nonce
  ON avaliacao_auto_confirmacoes(assessor_nonce_hash);

CREATE TABLE IF NOT EXISTS workflow_eventos (
  id              BIGSERIAL PRIMARY KEY,
  ticket_id       BIGINT,
  workflow        TEXT NOT NULL,
  node_name       TEXT,
  fase            TEXT,
  acao            TEXT,
  status_evento   TEXT,
  status_anterior TEXT,
  status_novo     TEXT,
  erro            BOOLEAN DEFAULT FALSE,
  mensagem_erro   TEXT,
  execution_id    TEXT,
  inicio_em       TIMESTAMPTZ,
  fim_em          TIMESTAMPTZ,
  duracao_ms      INTEGER,
  criado_em       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workflow_eventos_ticket ON workflow_eventos(ticket_id);
CREATE INDEX IF NOT EXISTS idx_workflow_eventos_workflow ON workflow_eventos(workflow);
CREATE INDEX IF NOT EXISTS idx_workflow_eventos_fase ON workflow_eventos(fase);
CREATE INDEX IF NOT EXISTS idx_workflow_eventos_criado ON workflow_eventos(criado_em);
CREATE INDEX IF NOT EXISTS idx_workflow_eventos_erro ON workflow_eventos(erro);

CREATE TABLE IF NOT EXISTS dataset_controle (
  id                              BIGSERIAL PRIMARY KEY,
  ticket_id                       BIGINT,
  origem                          TEXT NOT NULL DEFAULT 'SEED_CONTROLADO',
  cenario_controle                TEXT,
  duplicado_esperado              BOOLEAN,
  referencia_duplicado_esperada   BIGINT,
  classificacao_esperada          TEXT,
  executor_esperado               TEXT,
  status_final_esperado           TEXT,
  nivel_dificuldade               TEXT,
  run_id                          TEXT,
  case_id                         TEXT,
  episode_id                      TEXT,
  scenario_id                     TEXT,
  dimension                       TEXT,
  order_in_episode                INTEGER,
  reference_case_id               TEXT,
  requires_human_review           BOOLEAN DEFAULT FALSE,
  risk                            TEXT,
  rationale                       TEXT,
  label_source                    TEXT DEFAULT 'GABARITO_SINTETICO',
  template_family                 TEXT,
  dataset_version                 TEXT,
  split                           TEXT DEFAULT 'TEST',
  observacao                      TEXT,
  criado_em                       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dataset_ticket ON dataset_controle(ticket_id);
CREATE INDEX IF NOT EXISTS idx_dataset_cenario ON dataset_controle(cenario_controle);
CREATE INDEX IF NOT EXISTS idx_dataset_origem ON dataset_controle(origem);
ALTER TABLE dataset_controle ADD COLUMN IF NOT EXISTS run_id TEXT;
ALTER TABLE dataset_controle ADD COLUMN IF NOT EXISTS case_id TEXT;
ALTER TABLE dataset_controle ADD COLUMN IF NOT EXISTS episode_id TEXT;
ALTER TABLE dataset_controle ADD COLUMN IF NOT EXISTS scenario_id TEXT;
ALTER TABLE dataset_controle ADD COLUMN IF NOT EXISTS dimension TEXT;
ALTER TABLE dataset_controle ADD COLUMN IF NOT EXISTS order_in_episode INTEGER;
ALTER TABLE dataset_controle ADD COLUMN IF NOT EXISTS reference_case_id TEXT;
ALTER TABLE dataset_controle ADD COLUMN IF NOT EXISTS requires_human_review BOOLEAN DEFAULT FALSE;
ALTER TABLE dataset_controle ADD COLUMN IF NOT EXISTS risk TEXT;
ALTER TABLE dataset_controle ADD COLUMN IF NOT EXISTS rationale TEXT;
ALTER TABLE dataset_controle ADD COLUMN IF NOT EXISTS label_source TEXT DEFAULT 'GABARITO_SINTETICO';
ALTER TABLE dataset_controle ADD COLUMN IF NOT EXISTS template_family TEXT;
ALTER TABLE dataset_controle ADD COLUMN IF NOT EXISTS dataset_version TEXT;
ALTER TABLE dataset_controle ADD COLUMN IF NOT EXISTS split TEXT DEFAULT 'TEST';
CREATE UNIQUE INDEX IF NOT EXISTS idx_dataset_run_case
  ON dataset_controle(run_id, case_id)
  WHERE run_id IS NOT NULL AND case_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_dataset_episode ON dataset_controle(run_id, episode_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_dataset_run_ticket
  ON dataset_controle(run_id, ticket_id)
  WHERE run_id IS NOT NULL AND ticket_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS experimentos_avaliacao (
  run_id                    TEXT PRIMARY KEY,
  origem                    TEXT NOT NULL,
  dataset_version           TEXT NOT NULL,
  dataset_sha256            TEXT NOT NULL,
  seed                      BIGINT NOT NULL,
  split                     TEXT NOT NULL DEFAULT 'TEST',
  modelo_ia                 TEXT NOT NULL,
  prompt_dedup_version      TEXT NOT NULL,
  prompt_classif_version    TEXT NOT NULL,
  generation_profile        TEXT NOT NULL,
  generation_config         JSONB NOT NULL DEFAULT '{}'::jsonb,
  protocolo_version         TEXT NOT NULL,
  status                    TEXT NOT NULL DEFAULT 'PREPARADO',
  rotulos_validados         BOOLEAN NOT NULL DEFAULT FALSE,
  protocolo_rotulagem_validado BOOLEAN NOT NULL DEFAULT FALSE,
  auditoria_humana_concluida BOOLEAN NOT NULL DEFAULT FALSE,
  congelado_em              TIMESTAMPTZ,
  iniciado_em               TIMESTAMPTZ,
  concluido_em              TIMESTAMPTZ,
  criado_em                 TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE experimentos_avaliacao
  ADD COLUMN IF NOT EXISTS protocolo_rotulagem_validado BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE experimentos_avaliacao
  ADD COLUMN IF NOT EXISTS auditoria_humana_concluida BOOLEAN NOT NULL DEFAULT FALSE;

CREATE OR REPLACE VIEW vw_decisoes_confirmatorias_elegiveis AS
SELECT d.*
FROM ia_decisoes d
JOIN experimentos_avaliacao e ON e.run_id=d.run_id
WHERE UPPER(e.split) IN ('TEST','TESTE','BENCHMARK')
  AND e.rotulos_validados=TRUE
  AND e.protocolo_rotulagem_validado=TRUE
  AND e.auditoria_humana_concluida=TRUE
  AND d.elegivel_eficacia_confirmatoria=TRUE
  AND d.fallback_utilizado=FALSE
  AND d.total_modelos_tentados=1
  AND d.versao_modelo=e.modelo_ia
  AND EXISTS (
    SELECT 1
    FROM avaliacoes_humanas a
    WHERE a.run_id=d.run_id
      AND a.ticket_id=d.ticket_id
      AND a.etapa=d.etapa
      AND COALESCE(a.status_avaliacao,'CONCLUIDA')='CONCLUIDA'
      AND COALESCE(NULLIF(a.classe_correta,''),NULLIF(a.decisao_humana,'')) IS NOT NULL
      AND a.fonte_gabarito IN ('ADJUDICADO','REVISAO_HUMANA')
  );

DROP VIEW IF EXISTS vw_log_loss_deduplicacao CASCADE;
DROP VIEW IF EXISTS vw_average_precision_deduplicacao CASCADE;
DROP VIEW IF EXISTS vw_pr_deduplicacao CASCADE;
DROP VIEW IF EXISTS vw_auc_deduplicacao CASCADE;
DROP VIEW IF EXISTS vw_roc_deduplicacao CASCADE;
DROP VIEW IF EXISTS vw_scores_deduplicacao CASCADE;
DROP VIEW IF EXISTS vw_recall_candidatos_deduplicacao CASCADE;
DROP VIEW IF EXISTS vw_metricas_deduplicacao_desafio CASCADE;
DROP VIEW IF EXISTS vw_decisoes_deduplicacao_desafio CASCADE;
DROP VIEW IF EXISTS vw_metricas_deduplicacao CASCADE;
DROP VIEW IF EXISTS vw_decisoes_deduplicacao CASCADE;
DROP VIEW IF EXISTS vw_risco_cobertura_classificacao CASCADE;
DROP VIEW IF EXISTS vw_brier_classificacao CASCADE;
DROP VIEW IF EXISTS vw_log_loss_classificacao CASCADE;
DROP VIEW IF EXISTS vw_average_precision_classificacao CASCADE;
DROP VIEW IF EXISTS vw_pr_classificacao CASCADE;
DROP VIEW IF EXISTS vw_auc_classificacao CASCADE;
DROP VIEW IF EXISTS vw_roc_classificacao CASCADE;
DROP VIEW IF EXISTS vw_scores_classificacao CASCADE;
DROP VIEW IF EXISTS vw_kpi_classificacao CASCADE;
DROP VIEW IF EXISTS vw_metricas_assertividade_classificacao CASCADE;
DROP VIEW IF EXISTS vw_matriz_confusao_classificacao CASCADE;
DROP VIEW IF EXISTS vw_decisoes_classificacao CASCADE;
DROP VIEW IF EXISTS vw_gabarito_final CASCADE;
DROP VIEW IF EXISTS metricas_ia_duplicidade_v9 CASCADE;
DROP VIEW IF EXISTS vw_dataset_controle_resultados CASCADE;

CREATE OR REPLACE VIEW vw_dataset_controle_resultados AS
SELECT
  d.id AS dataset_id,
  d.ticket_id,
  d.origem,
  d.cenario_controle,
  d.duplicado_esperado,
  d.referencia_duplicado_esperada,
  d.classificacao_esperada,
  d.executor_esperado,
  d.status_final_esperado,
  d.nivel_dificuldade,
  t.classificacao_final AS classificacao_obtida,
  t.executor AS executor_obtido,
  t.status_nome AS status_final_obtido,
  t.duplicado_de_id AS referencia_duplicado_obtida,
  CASE
    WHEN d.duplicado_esperado IS NULL THEN NULL
    WHEN d.duplicado_esperado = TRUE THEN COALESCE(t.duplicado_de_id IS NOT NULL OR t.classificacao_final='DUPLICADO', FALSE)
    ELSE COALESCE(t.duplicado_de_id IS NULL AND COALESCE(t.classificacao_final,'') <> 'DUPLICADO', FALSE)
  END AS duplicidade_ok,
  CASE
    WHEN d.classificacao_esperada IS NULL THEN NULL
    ELSE COALESCE(t.classificacao_final = d.classificacao_esperada, FALSE)
  END AS classificacao_ok,
  CASE
    WHEN d.executor_esperado IS NULL THEN NULL
    ELSE COALESCE(t.executor = d.executor_esperado, FALSE)
  END AS executor_ok,
  CASE
    WHEN d.status_final_esperado IS NULL THEN NULL
    ELSE COALESCE(t.status_nome = d.status_final_esperado, FALSE)
  END AS status_final_ok,
  t.ultima_acao_workflow,
  t.atualizado_em
FROM dataset_controle d
LEFT JOIN tickets_processados t ON t.id = d.ticket_id;

-- Trigger para atualizar atualizado_em automaticamente
CREATE OR REPLACE FUNCTION trg_atualizado_em() RETURNS trigger AS $$
BEGIN NEW.atualizado_em = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tickets_atualizado ON tickets_processados;
CREATE TRIGGER trg_tickets_atualizado
  BEFORE UPDATE ON tickets_processados
  FOR EACH ROW EXECUTE FUNCTION trg_atualizado_em();

CREATE OR REPLACE VIEW metricas_ia_duplicidade_v9 AS
WITH base AS (
  SELECT
    COUNT(*) FILTER (
      WHERE classificacao = 'POSSIVEL_DUPLICADO'
         OR classificacao_final IN ('POSSIVEL_DUPLICADO','DUPLICADO')
         OR decisao_fiscal IN ('CONFIRMOU_DUP','REJEITOU_DUP')
    ) AS suspeitas_ia,
    COUNT(*) FILTER (WHERE decisao_fiscal = 'CONFIRMOU_DUP') AS confirmadas_fiscal,
    COUNT(*) FILTER (WHERE decisao_fiscal = 'REJEITOU_DUP') AS rejeitadas_fiscal,
    COUNT(*) FILTER (WHERE em_aprovacao_fiscal = TRUE) AS pendentes_fiscal
  FROM tickets_processados
)
SELECT
  suspeitas_ia,
  confirmadas_fiscal,
  rejeitadas_fiscal,
  pendentes_fiscal,
  CASE
    WHEN confirmadas_fiscal + rejeitadas_fiscal = 0 THEN NULL
    ELSE ROUND((confirmadas_fiscal::numeric * 100.0) / (confirmadas_fiscal + rejeitadas_fiscal), 2)
  END AS assertividade_percentual
FROM base;

CREATE OR REPLACE VIEW vw_matriz_confusao_classificacao AS
WITH base AS (
  SELECT
    COALESCE(NULLIF(classe_correta, ''), NULLIF(decisao_humana, '')) AS classe_correta,
    NULLIF(decisao_ia, '') AS classe_predita_pela_ia
  FROM avaliacoes_humanas
  WHERE etapa = 'CLASSIFICACAO'
    AND COALESCE(status_avaliacao, 'CONCLUIDA') = 'CONCLUIDA'
    AND COALESCE(NULLIF(classe_correta, ''), NULLIF(decisao_humana, '')) IS NOT NULL
    AND NULLIF(decisao_ia, '') IS NOT NULL
)
SELECT
  classe_correta,
  classe_predita_pela_ia,
  COUNT(*)::int AS quantidade,
  ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (PARTITION BY classe_correta), 0), 2) AS percentual
FROM base
GROUP BY classe_correta, classe_predita_pela_ia;

CREATE OR REPLACE VIEW vw_kpi_classificacao AS
WITH classes(classe) AS (VALUES ('OBRA'), ('DEMO'), ('SOB_DEMANDA'), ('TRIAGEM_MANUAL')),
aval AS (
  SELECT decisao_ia, COALESCE(NULLIF(classe_correta, ''), NULLIF(decisao_humana, '')) AS classe_correta, ia_estava_correta
  FROM avaliacoes_humanas
  WHERE etapa = 'CLASSIFICACAO'
    AND COALESCE(status_avaliacao, 'CONCLUIDA') = 'CONCLUIDA'
),
metricas AS (
  SELECT
    c.classe,
    COUNT(*) FILTER (WHERE a.decisao_ia = c.classe AND a.classe_correta = c.classe)::numeric AS tp,
    COUNT(*) FILTER (WHERE a.decisao_ia = c.classe AND a.classe_correta <> c.classe)::numeric AS fp,
    COUNT(*) FILTER (WHERE a.decisao_ia <> c.classe AND a.classe_correta = c.classe)::numeric AS fn
  FROM classes c CROSS JOIN aval a
  GROUP BY c.classe
),
por_classe AS (
  SELECT
    classe,
    tp / NULLIF(tp + fp, 0) AS precisao,
    tp / NULLIF(tp + fn, 0) AS recall,
    (2 * (tp / NULLIF(tp + fp, 0)) * (tp / NULLIF(tp + fn, 0))) / NULLIF((tp / NULLIF(tp + fp, 0)) + (tp / NULLIF(tp + fn, 0)), 0) AS f1
  FROM metricas
)
SELECT
  ROUND(AVG((ia_estava_correta::int)::numeric) FILTER (WHERE ia_estava_correta IS NOT NULL), 4) AS acuracia_geral,
  ROUND(MAX(precisao) FILTER (WHERE classe='OBRA'), 4) AS precisao_obra,
  ROUND(MAX(recall) FILTER (WHERE classe='OBRA'), 4) AS recall_obra,
  ROUND(MAX(f1) FILTER (WHERE classe='OBRA'), 4) AS f1_obra,
  ROUND(MAX(precisao) FILTER (WHERE classe='DEMO'), 4) AS precisao_demo,
  ROUND(MAX(recall) FILTER (WHERE classe='DEMO'), 4) AS recall_demo,
  ROUND(MAX(f1) FILTER (WHERE classe='DEMO'), 4) AS f1_demo,
  ROUND(MAX(precisao) FILTER (WHERE classe='SOB_DEMANDA'), 4) AS precisao_sob_demanda,
  ROUND(MAX(recall) FILTER (WHERE classe='SOB_DEMANDA'), 4) AS recall_sob_demanda,
  ROUND(MAX(f1) FILTER (WHERE classe='SOB_DEMANDA'), 4) AS f1_sob_demanda,
  ROUND(MAX(precisao) FILTER (WHERE classe='TRIAGEM_MANUAL'), 4) AS precisao_triagem_manual,
  ROUND(MAX(recall) FILTER (WHERE classe='TRIAGEM_MANUAL'), 4) AS recall_triagem_manual,
  ROUND(MAX(f1) FILTER (WHERE classe='TRIAGEM_MANUAL'), 4) AS f1_triagem_manual,
  ROUND(AVG(f1), 4) AS f1_macro
FROM por_classe, aval;

CREATE OR REPLACE VIEW vw_scores_classificacao AS
WITH classes(classe) AS (VALUES ('OBRA'), ('DEMO'), ('SOB_DEMANDA'), ('TRIAGEM_MANUAL')),
aval AS (
  SELECT
    a.ticket_id,
    COALESCE(NULLIF(a.classe_correta, ''), NULLIF(a.decisao_humana, '')) AS classe_correta,
    NULLIF(a.decisao_ia, '') AS classe_predita,
    a.ia_estava_correta,
    a.avaliado_em
  FROM avaliacoes_humanas a
  WHERE a.etapa = 'CLASSIFICACAO'
    AND COALESCE(a.status_avaliacao, 'CONCLUIDA') = 'CONCLUIDA'
    AND COALESCE(NULLIF(a.classe_correta, ''), NULLIF(a.decisao_humana, '')) IS NOT NULL
    AND NULLIF(a.decisao_ia, '') IS NOT NULL
),
base AS (
  SELECT
    a.ticket_id,
    c.classe,
    a.classe_correta,
    COALESCE(d.predicao, a.classe_predita) AS classe_predita,
    (a.classe_correta = c.classe) AS classe_positiva,
    COALESCE(d.confianca, CASE WHEN a.ia_estava_correta THEN 1 ELSE 0 END::numeric) AS confianca_decisao,
    CASE
      WHEN d.output_normalizado IS NOT NULL
       AND jsonb_typeof(d.output_normalizado->'probabilidades') = 'object'
       AND (d.output_normalizado->'probabilidades'->>c.classe) ~ '^[0-9]+(\.[0-9]+)?$'
      THEN (d.output_normalizado->'probabilidades'->>c.classe)::numeric
      WHEN COALESCE(d.predicao, a.classe_predita) = c.classe THEN COALESCE(d.confianca, CASE WHEN a.ia_estava_correta THEN 1 ELSE 0 END::numeric)
      ELSE GREATEST(0, (1 - COALESCE(d.confianca, CASE WHEN a.ia_estava_correta THEN 1 ELSE 0 END::numeric)) / 4.0)
    END AS score_classe,
    d.prompt_version,
    d.modelo_ia,
    d.versao_modelo,
    a.avaliado_em
  FROM aval a
  CROSS JOIN classes c
  LEFT JOIN LATERAL (
    SELECT predicao, confianca, output_normalizado, prompt_version, modelo_ia, versao_modelo
    FROM ia_decisoes d
    WHERE d.ticket_id = a.ticket_id
      AND d.etapa = 'CLASSIFICACAO'
      AND d.erro_ia = FALSE
    ORDER BY d.criado_em DESC, d.id DESC
    LIMIT 1
  ) d ON TRUE
)
SELECT
  ticket_id,
  classe,
  classe_correta,
  classe_predita,
  classe_positiva,
  LEAST(0.999999, GREATEST(0.000001, COALESCE(score_classe, 0.000001))) AS score_classe,
  confianca_decisao,
  prompt_version,
  modelo_ia,
  versao_modelo,
  avaliado_em
FROM base;

CREATE OR REPLACE VIEW vw_metricas_assertividade_classificacao AS
WITH metricas AS (
  SELECT
    classe,
    COUNT(*)::numeric AS total,
    COUNT(*) FILTER (WHERE classe_positiva = TRUE AND classe_predita = classe)::numeric AS tp,
    COUNT(*) FILTER (WHERE classe_positiva = FALSE AND classe_predita = classe)::numeric AS fp,
    COUNT(*) FILTER (WHERE classe_positiva = TRUE AND classe_predita <> classe)::numeric AS fn,
    COUNT(*) FILTER (WHERE classe_positiva = FALSE AND classe_predita <> classe)::numeric AS tn
  FROM vw_scores_classificacao
  GROUP BY classe
)
SELECT
  classe,
  total::int,
  tp::int,
  fp::int,
  fn::int,
  tn::int,
  ROUND((tp + tn) / NULLIF(total, 0), 4) AS acuracia,
  ROUND(tp / NULLIF(tp + fp, 0), 4) AS precisao,
  ROUND(tp / NULLIF(tp + fn, 0), 4) AS recall_sensitivity,
  ROUND(tn / NULLIF(tn + fp, 0), 4) AS especificidade,
  ROUND((2 * tp) / NULLIF((2 * tp) + fp + fn, 0), 4) AS f1_score
FROM metricas;

CREATE OR REPLACE VIEW vw_roc_classificacao AS
WITH thresholds AS (
  SELECT classe, score_classe AS threshold FROM vw_scores_classificacao
  UNION
  SELECT DISTINCT classe, 0::numeric AS threshold FROM vw_scores_classificacao
  UNION
  SELECT DISTINCT classe, 1::numeric AS threshold FROM vw_scores_classificacao
)
SELECT
  t.classe,
  t.threshold,
  ROUND(COUNT(*) FILTER (WHERE s.classe_positiva = TRUE AND s.score_classe >= t.threshold)::numeric / NULLIF(COUNT(*) FILTER (WHERE s.classe_positiva = TRUE), 0), 6) AS recall_tpr,
  ROUND(COUNT(*) FILTER (WHERE s.classe_positiva = FALSE AND s.score_classe >= t.threshold)::numeric / NULLIF(COUNT(*) FILTER (WHERE s.classe_positiva = FALSE), 0), 6) AS falso_positivo_fpr,
  COUNT(*) FILTER (WHERE s.classe_positiva = TRUE)::int AS positivos,
  COUNT(*) FILTER (WHERE s.classe_positiva = FALSE)::int AS negativos
FROM thresholds t
JOIN vw_scores_classificacao s ON s.classe = t.classe
GROUP BY t.classe, t.threshold;

CREATE OR REPLACE VIEW vw_auc_classificacao AS
WITH ordenado AS (
  SELECT
    classe,
    falso_positivo_fpr,
    recall_tpr,
    LAG(falso_positivo_fpr) OVER (PARTITION BY classe ORDER BY falso_positivo_fpr, recall_tpr) AS prev_fpr,
    LAG(recall_tpr) OVER (PARTITION BY classe ORDER BY falso_positivo_fpr, recall_tpr) AS prev_tpr
  FROM vw_roc_classificacao
  WHERE falso_positivo_fpr IS NOT NULL
    AND recall_tpr IS NOT NULL
),
auc AS (
  SELECT
    classe,
    SUM((falso_positivo_fpr - prev_fpr) * (recall_tpr + prev_tpr) / 2.0) AS auc_roc
  FROM ordenado
  WHERE prev_fpr IS NOT NULL
    AND prev_tpr IS NOT NULL
  GROUP BY classe
)
SELECT classe, ROUND(auc_roc, 6) AS auc_roc
FROM auc;

CREATE OR REPLACE VIEW vw_log_loss_classificacao AS
WITH por_classe AS (
  SELECT
    classe,
    COUNT(*)::int AS total_avaliado,
    ROUND(AVG(
      CASE
        WHEN classe_positiva THEN -LN(score_classe)
        ELSE -LN(1 - score_classe)
      END
    ), 6) AS log_loss_binario
  FROM vw_scores_classificacao
  GROUP BY classe
)
SELECT classe, total_avaliado, log_loss_binario
FROM por_classe
UNION ALL
SELECT 'MACRO' AS classe, SUM(total_avaliado)::int AS total_avaliado, ROUND(AVG(log_loss_binario), 6) AS log_loss_binario
FROM por_classe;

-- =============================================================
-- Metricas experimentais V2
-- Estas definicoes substituem as views legadas acima. Nenhum score
-- probabilistico e inferido a partir do acerto ou do gabarito.
-- =============================================================

DROP VIEW IF EXISTS vw_log_loss_classificacao CASCADE;
DROP VIEW IF EXISTS vw_auc_classificacao CASCADE;
DROP VIEW IF EXISTS vw_roc_classificacao CASCADE;
DROP VIEW IF EXISTS vw_scores_classificacao CASCADE;
DROP VIEW IF EXISTS vw_kpi_classificacao CASCADE;
DROP VIEW IF EXISTS vw_metricas_assertividade_classificacao CASCADE;
DROP VIEW IF EXISTS vw_matriz_confusao_classificacao CASCADE;

CREATE OR REPLACE VIEW vw_gabarito_final AS
SELECT DISTINCT ON (COALESCE(a.run_id, d.run_id, ''), a.ticket_id, a.etapa)
  COALESCE(a.run_id, d.run_id) AS run_id,
  COALESCE(a.case_id, d.case_id) AS case_id,
  COALESCE(a.episode_id, d.episode_id) AS episode_id,
  a.ticket_id,
  a.etapa,
  COALESCE(NULLIF(a.classe_correta, ''), NULLIF(a.decisao_humana, '')) AS classe_correta,
  a.decisao_ia,
  a.fonte_gabarito,
  COALESCE(a.fonte_gabarito,'') IN ('ADJUDICADO','REVISAO_HUMANA') AS gabarito_humano,
  (
    COALESCE(a.fonte_gabarito,'')='ORACULO_GABARITO'
    OR COALESCE(a.fonte_gabarito,'') LIKE 'SINTETICO_%'
  ) AS gabarito_sintetico,
  a.adjudicada,
  a.avaliado_em
FROM avaliacoes_humanas a
LEFT JOIN dataset_controle d
  ON d.ticket_id = a.ticket_id
 AND (a.run_id IS NULL OR d.run_id = a.run_id)
WHERE COALESCE(a.status_avaliacao, 'CONCLUIDA') = 'CONCLUIDA'
  AND COALESCE(NULLIF(a.classe_correta, ''), NULLIF(a.decisao_humana, '')) IS NOT NULL
ORDER BY
  COALESCE(a.run_id, d.run_id, ''),
  a.ticket_id,
  a.etapa,
  a.adjudicada DESC,
  CASE COALESCE(a.fonte_gabarito, '')
    WHEN 'ADJUDICADO' THEN 3
    WHEN 'REVISAO_HUMANA' THEN 2
    ELSE 1
  END DESC,
  a.avaliado_em DESC,
  a.id DESC;

CREATE OR REPLACE VIEW vw_decisoes_classificacao AS
SELECT
  g.run_id,
  g.case_id,
  g.episode_id,
  g.ticket_id,
  dc.dimension,
  dc.order_in_episode,
  dc.scenario_id,
  dc.template_family,
  g.classe_correta,
  i.id AS ia_decisao_id,
  COALESCE(NULLIF(i.predicao, ''), NULLIF(g.decisao_ia, ''), 'SEM_DECISAO') AS classe_predita,
  i.confianca,
  i.input_resumo,
  i.total_candidatos,
  i.output_normalizado,
  i.prompt_version,
  i.modelo_ia,
  i.versao_modelo,
  i.generation_profile,
  i.erro_ia,
  (
    COALESCE(i.erro_ia, FALSE)
    OR COALESCE(NULLIF(i.predicao, ''), NULLIF(g.decisao_ia, ''), 'SEM_DECISAO')
       NOT IN ('OBRA','DEMO','SOB_DEMANDA','TRIAGEM_MANUAL')
    OR CASE
      WHEN LOWER(COALESCE(i.output_normalizado->>'abstained', '')) IN ('true','false')
        THEN (i.output_normalizado->>'abstained')::boolean
      ELSE FALSE
    END
  ) AS abstencao,
  i.operational_config,
  i.provedor_ia,
  i.papel_modelo,
  COALESCE(
    NULLIF(i.operational_config->>'local_probability_semantics', ''),
    NULLIF(i.operational_config->'local_scientific_metadata'->>'probability_semantics', '')
  ) AS probability_semantics
FROM vw_gabarito_final g
LEFT JOIN dataset_controle dc
  ON dc.ticket_id = g.ticket_id
 AND dc.run_id IS NOT DISTINCT FROM g.run_id
LEFT JOIN experimentos_avaliacao e ON e.run_id = g.run_id
LEFT JOIN LATERAL (
  SELECT d.*
  FROM ia_decisoes d
  WHERE d.ticket_id = g.ticket_id
    AND d.etapa = 'CLASSIFICACAO'
    AND d.run_id IS NOT DISTINCT FROM g.run_id
  ORDER BY d.criado_em DESC, d.id DESC
  LIMIT 1
) i ON TRUE
WHERE g.etapa = 'CLASSIFICACAO'
  AND (
    g.gabarito_humano
    OR (
      COALESCE(UPPER(e.split),'') NOT IN ('TEST','TESTE','BENCHMARK')
      AND LOWER(COALESCE(e.generation_config->>'confirmatory_eligible','false')) <> 'true'
      AND LOWER(COALESCE(e.generation_config->>'scientific_result','false')) <> 'true'
    )
  );

CREATE OR REPLACE VIEW vw_matriz_confusao_classificacao AS
SELECT
  run_id,
  classe_correta,
  classe_predita AS classe_predita_pela_ia,
  COUNT(*)::int AS quantidade,
  ROUND(
    COUNT(*)::numeric /
    NULLIF(SUM(COUNT(*)) OVER (PARTITION BY run_id, classe_correta), 0),
    6
  ) AS proporcao
FROM vw_decisoes_classificacao
WHERE NOT abstencao
GROUP BY run_id, classe_correta, classe_predita;

CREATE OR REPLACE VIEW vw_metricas_assertividade_classificacao AS
WITH classes(classe) AS (
  VALUES ('OBRA'), ('DEMO'), ('SOB_DEMANDA'), ('TRIAGEM_MANUAL')
),
runs AS (
  SELECT DISTINCT run_id FROM vw_decisoes_classificacao
),
m AS (
  SELECT
    r.run_id,
    c.classe,
    COUNT(d.ticket_id)::numeric AS total,
    COUNT(*) FILTER (WHERE d.classe_correta = c.classe AND d.classe_predita = c.classe)::numeric AS tp,
    COUNT(*) FILTER (WHERE d.classe_correta <> c.classe AND d.classe_predita = c.classe)::numeric AS fp,
    COUNT(*) FILTER (WHERE d.classe_correta = c.classe AND d.classe_predita <> c.classe)::numeric AS fn,
    COUNT(*) FILTER (WHERE d.classe_correta <> c.classe AND d.classe_predita <> c.classe)::numeric AS tn
  FROM runs r
  CROSS JOIN classes c
  LEFT JOIN vw_decisoes_classificacao d
    ON d.run_id IS NOT DISTINCT FROM r.run_id
   AND NOT d.abstencao
  GROUP BY r.run_id, c.classe
)
SELECT
  run_id,
  classe,
  total::int,
  tp::int,
  fp::int,
  fn::int,
  tn::int,
  ROUND((tp + tn) / NULLIF(total, 0), 6) AS acuracia_binaria,
  ROUND(tp / NULLIF(tp + fp, 0), 6) AS precisao,
  ROUND(tp / NULLIF(tp + fn, 0), 6) AS recall_sensitivity,
  ROUND(tn / NULLIF(tn + fp, 0), 6) AS especificidade,
  ROUND((2 * tp) / NULLIF((2 * tp) + fp + fn, 0), 6) AS f1_score
FROM m;

CREATE OR REPLACE VIEW vw_kpi_classificacao AS
WITH base AS (
  SELECT
    run_id,
    COUNT(*)::int AS total,
    COUNT(*) FILTER (WHERE NOT abstencao)::int AS cobertos,
    COUNT(*) FILTER (WHERE abstencao)::int AS abstencoes,
    COUNT(*) FILTER (WHERE NOT abstencao AND classe_predita = classe_correta)::numeric /
      NULLIF(COUNT(*), 0) AS acuracia_geral,
    COUNT(*) FILTER (WHERE NOT abstencao)::numeric /
      NULLIF(COUNT(*), 0) AS cobertura_automatica,
    AVG((classe_predita = classe_correta)::int::numeric)
      FILTER (WHERE NOT abstencao) AS acuracia_sob_cobertura
  FROM vw_decisoes_classificacao
  GROUP BY run_id
),
macro AS (
  SELECT run_id, AVG(f1_score) FILTER (WHERE f1_score IS NOT NULL) AS f1_macro
  FROM vw_metricas_assertividade_classificacao
  GROUP BY run_id
)
SELECT
  b.run_id,
  b.total,
  b.cobertos,
  b.abstencoes,
  ROUND(b.acuracia_geral, 6) AS acuracia_geral,
  ROUND(m.f1_macro, 6) AS f1_macro,
  ROUND(b.cobertura_automatica, 6) AS cobertura_automatica,
  ROUND(b.acuracia_sob_cobertura, 6) AS acuracia_sob_cobertura
FROM base b
LEFT JOIN macro m ON m.run_id IS NOT DISTINCT FROM b.run_id;

CREATE OR REPLACE VIEW vw_scores_classificacao AS
WITH classes(classe) AS (
  VALUES ('OBRA'), ('DEMO'), ('SOB_DEMANDA'), ('TRIAGEM_MANUAL')
),
candidatas AS (
  SELECT
    d.*,
    COALESCE(
      d.output_normalizado->'probabilidades_semanticas',
      d.output_normalizado->'probabilidades'
    ) AS probabilidades_modelo
  FROM ia_decisoes d
  WHERE d.etapa = 'CLASSIFICACAO'
    AND d.erro_ia = FALSE
    AND d.predicao IN ('OBRA','DEMO','SOB_DEMANDA','TRIAGEM_MANUAL')
    -- Regras determinísticas pertencem à eficácia do pipeline, mas seus
    -- vetores one-hot não são probabilidades calibradas do candidato local.
    AND (
      COALESCE(UPPER(NULLIF(d.papel_modelo, '')), '') <> 'LOCAL'
      OR (
        LOWER(COALESCE(
          d.operational_config->>'local_candidate_evaluation_eligible', 'false'
        )) = 'true'
        AND COALESCE(d.operational_config->>'local_decision_path', '')
          IN ('hybrid_model','hybrid_model_abstention')
      )
    )
),
validas AS (
  SELECT
    d.*,
    (
      SELECT SUM(value::numeric)
      FROM jsonb_each_text(d.probabilidades_modelo)
      WHERE value ~ '^[0-9]+([.][0-9]+)?$'
    ) AS soma_prob
  FROM candidatas d
  WHERE jsonb_typeof(d.probabilidades_modelo) = 'object'
    AND d.probabilidades_modelo ?& ARRAY[
      'OBRA','DEMO','SOB_DEMANDA','TRIAGEM_MANUAL'
    ]
)
SELECT
  g.run_id,
  g.case_id,
  g.ticket_id,
  c.classe,
  g.classe_correta,
  u.predicao AS classe_predita,
  (g.classe_correta = c.classe) AS classe_positiva,
  LEAST(
    0.999999999999999,
    GREATEST(0.000000000000001, (u.probabilidades_modelo->>c.classe)::numeric)
  ) AS score_classe,
  u.confianca AS confianca_decisao,
  u.prompt_version,
  u.modelo_ia,
  u.versao_modelo,
  u.generation_profile,
  u.criado_em AS decidido_em,
  u.provedor_ia,
  u.papel_modelo,
  COALESCE(
    NULLIF(u.operational_config->>'local_probability_semantics', ''),
    NULLIF(u.operational_config->'local_scientific_metadata'->>'probability_semantics', '')
  ) AS probability_semantics,
  u.operational_config->>'local_decision_path' AS local_decision_path
FROM vw_decisoes_classificacao g
JOIN validas u ON u.id = g.ia_decisao_id
CROSS JOIN classes c
WHERE u.soma_prob BETWEEN 0.999 AND 1.001
;

CREATE OR REPLACE VIEW vw_roc_classificacao AS
WITH thresholds AS (
  SELECT DISTINCT run_id, classe, score_classe AS threshold FROM vw_scores_classificacao
  UNION SELECT DISTINCT run_id, classe, 0::numeric FROM vw_scores_classificacao
  UNION SELECT DISTINCT run_id, classe, 1::numeric FROM vw_scores_classificacao
)
SELECT
  t.run_id,
  t.classe,
  t.threshold,
  COUNT(*) FILTER (WHERE s.classe_positiva AND s.score_classe >= t.threshold)::numeric /
    NULLIF(COUNT(*) FILTER (WHERE s.classe_positiva), 0) AS recall_tpr,
  COUNT(*) FILTER (WHERE NOT s.classe_positiva AND s.score_classe >= t.threshold)::numeric /
    NULLIF(COUNT(*) FILTER (WHERE NOT s.classe_positiva), 0) AS falso_positivo_fpr
FROM thresholds t
JOIN vw_scores_classificacao s
  ON s.run_id IS NOT DISTINCT FROM t.run_id AND s.classe = t.classe
GROUP BY t.run_id, t.classe, t.threshold;

CREATE OR REPLACE VIEW vw_auc_classificacao AS
WITH pontos AS (
  SELECT
    *,
    LAG(falso_positivo_fpr) OVER (
      PARTITION BY run_id, classe ORDER BY falso_positivo_fpr, recall_tpr
    ) AS fpr_anterior,
    LAG(recall_tpr) OVER (
      PARTITION BY run_id, classe ORDER BY falso_positivo_fpr, recall_tpr
    ) AS tpr_anterior
  FROM vw_roc_classificacao
  WHERE falso_positivo_fpr IS NOT NULL AND recall_tpr IS NOT NULL
)
SELECT
  run_id,
  classe,
  ROUND(
    SUM((falso_positivo_fpr - fpr_anterior) * (recall_tpr + tpr_anterior) / 2.0),
    6
  ) AS auc_roc
FROM pontos
WHERE fpr_anterior IS NOT NULL AND tpr_anterior IS NOT NULL
GROUP BY run_id, classe;

CREATE OR REPLACE VIEW vw_pr_classificacao AS
WITH thresholds AS (
  SELECT DISTINCT run_id, classe, score_classe AS threshold
  FROM vw_scores_classificacao
  UNION SELECT DISTINCT run_id, classe, 0::numeric FROM vw_scores_classificacao
  UNION SELECT DISTINCT run_id, classe, 1::numeric FROM vw_scores_classificacao
)
SELECT
  t.run_id,
  t.classe,
  t.threshold,
  COUNT(*) FILTER (
    WHERE s.classe_positiva AND s.score_classe >= t.threshold
  )::numeric / NULLIF(COUNT(*) FILTER (WHERE s.classe_positiva),0) AS recall,
  COUNT(*) FILTER (
    WHERE s.classe_positiva AND s.score_classe >= t.threshold
  )::numeric / NULLIF(COUNT(*) FILTER (WHERE s.score_classe >= t.threshold),0) AS precision
FROM thresholds t
JOIN vw_scores_classificacao s
  ON s.run_id IS NOT DISTINCT FROM t.run_id AND s.classe=t.classe
GROUP BY t.run_id,t.classe,t.threshold;

CREATE OR REPLACE VIEW vw_average_precision_classificacao AS
WITH ranked AS (
  SELECT
    run_id,
    classe,
    ticket_id,
    classe_positiva,
    score_classe,
    ROW_NUMBER() OVER (
      PARTITION BY run_id,classe ORDER BY score_classe DESC,ticket_id
    ) AS k,
    SUM(classe_positiva::int) OVER (
      PARTITION BY run_id,classe ORDER BY score_classe DESC,ticket_id
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS tp_acumulado,
    SUM(classe_positiva::int) OVER (PARTITION BY run_id,classe) AS positivos
  FROM vw_scores_classificacao
)
SELECT
  run_id,
  classe,
  ROUND(
    SUM((tp_acumulado::numeric/k) * classe_positiva::int) /
    NULLIF(MAX(positivos),0),
    6
  ) AS average_precision
FROM ranked
GROUP BY run_id,classe;

CREATE OR REPLACE VIEW vw_log_loss_classificacao AS
WITH por_ticket AS (
  SELECT
    run_id,
    ticket_id,
    MAX(score_classe) FILTER (WHERE classe_positiva) AS probabilidade_classe_correta
  FROM vw_scores_classificacao
  GROUP BY run_id, ticket_id
)
SELECT
  run_id,
  COUNT(*)::int AS total_avaliado,
  ROUND(AVG(-LN(probabilidade_classe_correta)), 6) AS log_loss_multiclasse
FROM por_ticket
GROUP BY run_id;

CREATE OR REPLACE VIEW vw_brier_classificacao AS
SELECT
  run_id,
  COUNT(DISTINCT ticket_id)::int AS total_avaliado,
  ROUND(
    SUM(POWER(score_classe - CASE WHEN classe_positiva THEN 1 ELSE 0 END, 2)) /
    NULLIF(COUNT(DISTINCT ticket_id), 0),
    6
  ) AS brier_multiclasse
FROM vw_scores_classificacao
GROUP BY run_id;

CREATE OR REPLACE VIEW vw_risco_cobertura_classificacao AS
WITH thresholds AS (
  SELECT DISTINCT run_id, confianca AS threshold
  FROM vw_decisoes_classificacao
  WHERE NOT abstencao AND confianca IS NOT NULL
  UNION SELECT DISTINCT run_id, 0::numeric FROM vw_decisoes_classificacao
  UNION SELECT DISTINCT run_id, 1::numeric FROM vw_decisoes_classificacao
)
SELECT
  t.run_id,
  t.threshold,
  COUNT(*) FILTER (
    WHERE NOT d.abstencao AND d.confianca >= t.threshold
  )::numeric / NULLIF(COUNT(*), 0) AS cobertura,
  1 - AVG((d.classe_predita = d.classe_correta)::int::numeric) FILTER (
    WHERE NOT d.abstencao AND d.confianca >= t.threshold
  ) AS risco
FROM thresholds t
JOIN vw_decisoes_classificacao d ON d.run_id IS NOT DISTINCT FROM t.run_id
GROUP BY t.run_id, t.threshold;

CREATE OR REPLACE VIEW vw_decisoes_deduplicacao AS
SELECT
  g.run_id,
  g.case_id,
  g.episode_id,
  g.ticket_id,
  dc.dimension,
  dc.order_in_episode,
  dc.scenario_id,
  dc.template_family,
  g.classe_correta,
  COALESCE(NULLIF(i.predicao, ''), NULLIF(g.decisao_ia, ''), 'SEM_DECISAO') AS classe_predita,
  i.classe_referencia_id,
  dc.referencia_duplicado_esperada,
  i.confianca,
  i.input_resumo,
  i.total_candidatos,
  i.output_normalizado,
  i.prompt_version,
  i.modelo_ia,
  i.versao_modelo,
  i.generation_profile,
  i.erro_ia,
  CASE
    WHEN LOWER(COALESCE(i.output_normalizado->>'requer_revisao', '')) IN ('true','false')
      THEN (i.output_normalizado->>'requer_revisao')::boolean
    ELSE FALSE
  END AS requer_revisao,
  (
    COALESCE(i.erro_ia, FALSE)
    OR COALESCE(NULLIF(i.predicao, ''), NULLIF(g.decisao_ia, ''), 'SEM_DECISAO')
       NOT IN ('DUPLICADO','NAO_DUPLICADO')
    OR CASE
      WHEN LOWER(COALESCE(i.output_normalizado->>'requer_revisao', '')) IN ('true','false')
        THEN (i.output_normalizado->>'requer_revisao')::boolean
      ELSE FALSE
    END
  ) AS abstencao,
  i.operational_config,
  i.provedor_ia,
  i.papel_modelo,
  COALESCE(
    NULLIF(i.operational_config->>'local_probability_semantics', ''),
    NULLIF(i.operational_config->'local_scientific_metadata'->>'probability_semantics', '')
  ) AS probability_semantics
FROM vw_gabarito_final g
LEFT JOIN dataset_controle dc
  ON dc.ticket_id = g.ticket_id
 AND dc.run_id IS NOT DISTINCT FROM g.run_id
LEFT JOIN experimentos_avaliacao e ON e.run_id = g.run_id
LEFT JOIN LATERAL (
  SELECT d.*
  FROM ia_decisoes d
  WHERE d.ticket_id = g.ticket_id
    AND d.etapa = 'DEDUPLICACAO'
    AND d.run_id IS NOT DISTINCT FROM g.run_id
  ORDER BY d.criado_em DESC, d.id DESC
  LIMIT 1
) i ON TRUE
WHERE g.etapa = 'DEDUPLICACAO'
  AND (
    g.gabarito_humano
    OR (
      COALESCE(UPPER(e.split),'') NOT IN ('TEST','TESTE','BENCHMARK')
      AND LOWER(COALESCE(e.generation_config->>'confirmatory_eligible','false')) <> 'true'
      AND LOWER(COALESCE(e.generation_config->>'scientific_result','false')) <> 'true'
    )
  );

CREATE OR REPLACE VIEW vw_recall_candidatos_deduplicacao AS
WITH positivos AS (
  SELECT
    d.run_id,
    d.ticket_id,
    d.referencia_duplicado_esperada,
    d.total_candidatos,
    EXISTS (
      SELECT 1
      FROM jsonb_array_elements(COALESCE(d.input_resumo->'historico','[]'::jsonb)) item
      WHERE (item->>'id') ~ '^[0-9]+$'
        AND (item->>'id')::bigint = d.referencia_duplicado_esperada
    ) AS referencia_recuperada
  FROM vw_decisoes_deduplicacao d
  WHERE d.classe_correta='DUPLICADO'
    AND d.referencia_duplicado_esperada IS NOT NULL
)
SELECT
  run_id,
  COUNT(*)::int AS positivos_avaliados,
  COUNT(*) FILTER (WHERE referencia_recuperada)::int AS referencias_recuperadas,
  ROUND(AVG(referencia_recuperada::int::numeric),6) AS recall_candidatos,
  ROUND(AVG(total_candidatos::numeric),2) AS candidatos_medios
FROM positivos
GROUP BY run_id;

CREATE OR REPLACE VIEW vw_decisoes_deduplicacao_desafio AS
SELECT *
FROM vw_decisoes_deduplicacao
WHERE dimension = 'DEDUPLICACAO'
  AND order_in_episode > 1;

CREATE OR REPLACE VIEW vw_metricas_deduplicacao AS
WITH m AS (
  SELECT
    run_id,
    COUNT(*)::numeric AS total,
    COUNT(*) FILTER (WHERE NOT abstencao AND classe_predita IN ('DUPLICADO','NAO_DUPLICADO'))::numeric AS cobertos,
    COUNT(*) FILTER (WHERE abstencao OR classe_predita NOT IN ('DUPLICADO','NAO_DUPLICADO'))::numeric AS abstencoes,
    COUNT(*) FILTER (WHERE classe_correta='DUPLICADO')::numeric AS positivos_total,
    COUNT(*) FILTER (WHERE NOT abstencao AND classe_correta='DUPLICADO' AND classe_predita='DUPLICADO')::numeric AS tp,
    COUNT(*) FILTER (WHERE NOT abstencao AND classe_correta='NAO_DUPLICADO' AND classe_predita='DUPLICADO')::numeric AS fp,
    COUNT(*) FILTER (WHERE NOT abstencao AND classe_correta='DUPLICADO' AND classe_predita='NAO_DUPLICADO')::numeric AS fn,
    COUNT(*) FILTER (WHERE NOT abstencao AND classe_correta='NAO_DUPLICADO' AND classe_predita='NAO_DUPLICADO')::numeric AS tn,
    COUNT(*) FILTER (
      WHERE NOT abstencao
        AND classe_correta='DUPLICADO'
        AND classe_predita='DUPLICADO'
        AND classe_referencia_id = referencia_duplicado_esperada
    )::numeric AS referencias_corretas
  FROM vw_decisoes_deduplicacao
  GROUP BY run_id
)
SELECT
  run_id,
  total::int,
  cobertos::int,
  abstencoes::int,
  tp::int,
  fp::int,
  fn::int,
  tn::int,
  ROUND(cobertos/NULLIF(total,0),6) AS cobertura_automatica,
  ROUND((tp+tn)/NULLIF(cobertos,0),6) AS acuracia,
  ROUND(tp/NULLIF(tp+fp,0),6) AS precisao,
  ROUND(tp/NULLIF(tp+fn,0),6) AS recall,
  ROUND(tp/NULLIF(positivos_total,0),6) AS recall_automatizado_global,
  ROUND((2*tp)/NULLIF((2*tp)+fp+fn,0),6) AS f1,
  ROUND(fp/NULLIF(fp+tn,0),6) AS taxa_falso_positivo,
  ROUND(fn/NULLIF(fn+tp,0),6) AS taxa_falso_negativo,
  ROUND(referencias_corretas/NULLIF(tp,0),6) AS acuracia_referencia_entre_tp
FROM m;

CREATE OR REPLACE VIEW vw_metricas_deduplicacao_desafio AS
WITH m AS (
  SELECT
    run_id,
    COUNT(*)::numeric AS total,
    COUNT(*) FILTER (WHERE NOT abstencao AND classe_predita IN ('DUPLICADO','NAO_DUPLICADO'))::numeric AS cobertos,
    COUNT(*) FILTER (WHERE abstencao OR classe_predita NOT IN ('DUPLICADO','NAO_DUPLICADO'))::numeric AS abstencoes,
    COUNT(*) FILTER (WHERE classe_correta='DUPLICADO')::numeric AS positivos_total,
    COUNT(*) FILTER (WHERE NOT abstencao AND classe_correta='DUPLICADO' AND classe_predita='DUPLICADO')::numeric AS tp,
    COUNT(*) FILTER (WHERE NOT abstencao AND classe_correta='NAO_DUPLICADO' AND classe_predita='DUPLICADO')::numeric AS fp,
    COUNT(*) FILTER (WHERE NOT abstencao AND classe_correta='DUPLICADO' AND classe_predita='NAO_DUPLICADO')::numeric AS fn,
    COUNT(*) FILTER (WHERE NOT abstencao AND classe_correta='NAO_DUPLICADO' AND classe_predita='NAO_DUPLICADO')::numeric AS tn,
    COUNT(*) FILTER (
      WHERE NOT abstencao
        AND classe_correta='DUPLICADO'
        AND classe_predita='DUPLICADO'
        AND classe_referencia_id = referencia_duplicado_esperada
    )::numeric AS referencias_corretas
  FROM vw_decisoes_deduplicacao_desafio
  GROUP BY run_id
)
SELECT
  run_id,
  total::int,
  cobertos::int,
  abstencoes::int,
  tp::int,
  fp::int,
  fn::int,
  tn::int,
  ROUND(cobertos/NULLIF(total,0),6) AS cobertura_automatica,
  ROUND((tp+tn)/NULLIF(cobertos,0),6) AS acuracia,
  ROUND(tp/NULLIF(tp+fp,0),6) AS precisao,
  ROUND(tp/NULLIF(tp+fn,0),6) AS recall,
  ROUND(tp/NULLIF(positivos_total,0),6) AS recall_automatizado_global,
  ROUND((2*tp)/NULLIF((2*tp)+fp+fn,0),6) AS f1,
  ROUND(fp/NULLIF(fp+tn,0),6) AS taxa_falso_positivo,
  ROUND(fn/NULLIF(fn+tp,0),6) AS taxa_falso_negativo,
  ROUND(referencias_corretas/NULLIF(tp,0),6) AS acuracia_referencia_entre_tp
FROM m;

CREATE OR REPLACE VIEW vw_scores_deduplicacao AS
WITH candidatas AS (
  SELECT
    d.*,
    COALESCE(
      d.output_normalizado->'probabilidades_semanticas',
      d.output_normalizado->'probabilidades'
    ) AS probabilidades_modelo
  FROM vw_decisoes_deduplicacao d
)
SELECT
  run_id,
  case_id,
  ticket_id,
  (classe_correta='DUPLICADO') AS positivo,
  LEAST(
    0.999999999999999,
    GREATEST(
      0.000000000000001,
      (probabilidades_modelo->>'duplicado')::numeric
    )
  ) AS score_duplicado,
  provedor_ia,
  papel_modelo,
  probability_semantics,
  operational_config->>'local_decision_path' AS local_decision_path
FROM candidatas
WHERE erro_ia = FALSE
  AND (
    COALESCE(UPPER(NULLIF(papel_modelo, '')), '') <> 'LOCAL'
    OR (
      LOWER(COALESCE(
        operational_config->>'local_candidate_evaluation_eligible', 'false'
      )) = 'true'
      AND COALESCE(operational_config->>'local_decision_path', '')
        IN ('hybrid_model','hybrid_model_abstention')
    )
  )
  AND jsonb_typeof(probabilidades_modelo)='object'
  AND (probabilidades_modelo->>'duplicado') ~ '^[0-9]+([.][0-9]+)?$'
  AND (probabilidades_modelo->>'nao_duplicado') ~ '^[0-9]+([.][0-9]+)?$'
  AND (
    (probabilidades_modelo->>'duplicado')::numeric +
    (probabilidades_modelo->>'nao_duplicado')::numeric
  ) BETWEEN 0.999 AND 1.001
  AND (probabilidades_modelo->>'duplicado')::numeric BETWEEN 0 AND 1
  AND (probabilidades_modelo->>'nao_duplicado')::numeric BETWEEN 0 AND 1;

CREATE OR REPLACE VIEW vw_roc_deduplicacao AS
WITH thresholds AS (
  SELECT DISTINCT run_id,score_duplicado AS threshold FROM vw_scores_deduplicacao
  UNION SELECT DISTINCT run_id,0::numeric FROM vw_scores_deduplicacao
  UNION SELECT DISTINCT run_id,1::numeric FROM vw_scores_deduplicacao
)
SELECT
  t.run_id,
  t.threshold,
  COUNT(*) FILTER (
    WHERE s.positivo AND s.score_duplicado >= t.threshold
  )::numeric / NULLIF(COUNT(*) FILTER (WHERE s.positivo),0) AS recall_tpr,
  COUNT(*) FILTER (
    WHERE NOT s.positivo AND s.score_duplicado >= t.threshold
  )::numeric / NULLIF(COUNT(*) FILTER (WHERE NOT s.positivo),0) AS falso_positivo_fpr
FROM thresholds t
JOIN vw_scores_deduplicacao s ON s.run_id IS NOT DISTINCT FROM t.run_id
GROUP BY t.run_id,t.threshold;

CREATE OR REPLACE VIEW vw_auc_deduplicacao AS
WITH pontos AS (
  SELECT
    *,
    LAG(falso_positivo_fpr) OVER (
      PARTITION BY run_id ORDER BY falso_positivo_fpr,recall_tpr
    ) AS fpr_anterior,
    LAG(recall_tpr) OVER (
      PARTITION BY run_id ORDER BY falso_positivo_fpr,recall_tpr
    ) AS tpr_anterior
  FROM vw_roc_deduplicacao
  WHERE falso_positivo_fpr IS NOT NULL AND recall_tpr IS NOT NULL
)
SELECT
  run_id,
  ROUND(
    SUM((falso_positivo_fpr-fpr_anterior)*(recall_tpr+tpr_anterior)/2.0),
    6
  ) AS auc_roc
FROM pontos
WHERE fpr_anterior IS NOT NULL AND tpr_anterior IS NOT NULL
GROUP BY run_id;

CREATE OR REPLACE VIEW vw_pr_deduplicacao AS
WITH thresholds AS (
  SELECT DISTINCT run_id,score_duplicado AS threshold FROM vw_scores_deduplicacao
  UNION SELECT DISTINCT run_id,0::numeric FROM vw_scores_deduplicacao
  UNION SELECT DISTINCT run_id,1::numeric FROM vw_scores_deduplicacao
)
SELECT
  t.run_id,
  t.threshold,
  COUNT(*) FILTER (
    WHERE s.positivo AND s.score_duplicado >= t.threshold
  )::numeric / NULLIF(COUNT(*) FILTER (WHERE s.positivo),0) AS recall,
  COUNT(*) FILTER (
    WHERE s.positivo AND s.score_duplicado >= t.threshold
  )::numeric / NULLIF(COUNT(*) FILTER (WHERE s.score_duplicado >= t.threshold),0) AS precision
FROM thresholds t
JOIN vw_scores_deduplicacao s ON s.run_id IS NOT DISTINCT FROM t.run_id
GROUP BY t.run_id,t.threshold;

CREATE OR REPLACE VIEW vw_average_precision_deduplicacao AS
WITH ranked AS (
  SELECT
    run_id,
    ticket_id,
    positivo,
    score_duplicado,
    ROW_NUMBER() OVER (
      PARTITION BY run_id ORDER BY score_duplicado DESC,ticket_id
    ) AS k,
    SUM(positivo::int) OVER (
      PARTITION BY run_id ORDER BY score_duplicado DESC,ticket_id
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS tp_acumulado,
    SUM(positivo::int) OVER (PARTITION BY run_id) AS positivos
  FROM vw_scores_deduplicacao
)
SELECT
  run_id,
  ROUND(
    SUM((tp_acumulado::numeric/k)*positivo::int) / NULLIF(MAX(positivos),0),
    6
  ) AS average_precision
FROM ranked
GROUP BY run_id;

CREATE OR REPLACE VIEW vw_log_loss_deduplicacao AS
SELECT
  run_id,
  COUNT(*)::int AS total_avaliado,
  ROUND(AVG(
    CASE WHEN positivo THEN -LN(score_duplicado) ELSE -LN(1-score_duplicado) END
  ),6) AS log_loss,
  ROUND(AVG(POWER(score_duplicado - positivo::int, 2)),6) AS brier_score
FROM vw_scores_deduplicacao
GROUP BY run_id;
