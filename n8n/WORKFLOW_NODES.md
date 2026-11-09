# Documentação nó-a-nó — Triagem Inteligente v7

> **DOCUMENTO HISTÓRICO DA V7.** Não descreve a arquitetura V9 vigente e não
> deve ser usado como tutorial operacional atual. O rastreio corrente está em
> `docs/rastreio_completo_workflows_v9.md`; o artefato V7 publicável, inativo e
> sanitizado está em `n8n/history`.

Este documento descreve cada nó do workflow `Triagem Inteligente de Chamados - v7 (Postgres)` de forma objetiva, com função, principais parâmetros e observações de operação.

- **T1. Manual (Reprocessar / Primeira Exec)**: trigger manual para bootstrap/reprocessamento. Use para popular a tabela `tickets_processados` na primeira vez ou para ressincronizar.

- **T2. Webhook GLPI (Novo Chamado)**: webhook `POST` em `glpi-ticket-novo-v7`. Recebe eventos de novo chamado e inicia fluxo incremental por ticket.

- **T3. Schedule 06h/12h/18h**: agendador cron `0 6,12,18 * * *`. Executa refresh do BD (nao dispara IA) para manter sincronizacao de chamados nao-Novos.

- **N1. Identificar Modo**: `Code` node que determina modo de execucao: `INICIAL` (manual/primeira exec), `INCREMENTAL` (webhook) ou `SCHEDULE` (agendado). Extrai `ticket_id_evento` quando aplicavel.

- **N2. PG: Total no BD**: consulta `SELECT COUNT(*) FROM tickets_processados` para detectar BD vazio; influencia `N3`.

- **N3. Resolver Modo Final**: `Code` node que consolida o modo final (forca `INICIAL` se BD vazio) e passa contexto para o `Switch`.

- **G1. GLPI: Iniciar Sessao**: `HTTP Request` para `initSession` do GLPI. Define `App-Token` e `Authorization` e retorna `Session-Token` para as chamadas subsequentes.

- **M0. Switch: Modo**: roteador principal com saídas: `INICIAL` → busca tudo; `INCREMENTAL` → busca apenas ticket do webhook; `SCHEDULE` → refresh; `FISCAL_DECISAO` → caminho de decisao fiscal.

- **I1. GLPI: Buscar TUDO (Inicial)**: `HTTP Request` para listar tickets (Novos + Atribuido + Planejado + Pendente + Solucionado + Fechado) com `range` amplo. Usa `E1` para normalizar.

- **C1. GLPI: Buscar Ticket do Webhook**: `HTTP Request` que busca `Ticket/<id>` do evento quando em modo incremental.

- **S1. GLPI: Refresh Pend/Planej/Atrib/Soluc/Fechado**: `HTTP Request` similar a `I1` mas usado pelo `Schedule` para re-sincronizacao.

- **E1. Estruturar Chamados**: `Code` node que normaliza payload do GLPI para formato interno (`chamado`) e aplica recorte de 90 dias para status>1.

- **U1. PG: UPSERT Chamado**: `Postgres` node que faz `INSERT ... ON CONFLICT(id) DO UPDATE` em `tickets_processados`. Mantem colunas de triagem quando presentes.

- **F1. Filtrar: Apenas Novos para Triar**: `Code` node que elimina itens que nao devem passar para triagem IA: aceita apenas `Novo` (e `Pendente` em bootstrap), ignora registros com `em_aprovacao_fiscal=true`.

- **F2. Tem Chamados para Triar?**: `If` que verifica se ha itens a processar (sai para `L1` quando >0).

- **L1. SplitInBatches (3)**: divide a lista para processar 1 chamado por lote (evita sobrecarga). Configuravel via `batchSize`.

- **L2. Wait 20s entre lotes**: `Wait` node (20s) usado para espaçar chamadas de IA entre itens do lote; reduz risco de rate-limit.

- **D1. PG: Historico para Dedup**: `Postgres` query que monta conjunto de candidatos (max 60) ordenados por heuristica (localizacao, tipo_servico, titulo, data e full-text rank).

- **D2. Montar Payload IA**: `Code` node que agrega `chamado_atual` + `historico_abertos` em formato único para envio a `D3` (IA). Implementa retry wrapper quando `D3` falha.

- **D3. IA: Verificar Duplicidade**: node LangChain/Google Gemini (PaLM) configurado para receber `chamado_atual` e `historico_abertos` e retornar JSON com `duplicidade` (eh_duplicado, chamado_referencia_id, caracteristicas, justificativa). Configurado com `retryOnFail` e `waitBetweenTries`.

- **D3b. Wait 20s para Retry IA**: nó desativado (migration breadcrumb). Mantido `disabled=true`.

- **D4. Normalizar Dedup**: `Code` node que interpreta saída da IA; aplica fallback heurístico (`dedupHeuristica`) se IA não retornar decisao clara; produz objeto padronizado `duplicidade` e flags `_ia_ok`.

- **D5. E Duplicado?**: `Switch` que bifurca em `DUPLICADO` ou `NAO_DUPLICADO` com fallback `extra`.

- **DUP1. PG: Marcar Em Aprovacao Fiscal**: `Postgres` que atualiza `tickets_processados` definindo `em_aprovacao_fiscal=TRUE`, status `Pendente` e `classificacao='POSSIVEL_DUPLICADO'`.

- **DUP2. Preparar Corpo do Followup**: `Code` que monta o conteúdo do followup (texto) com links para decisao fiscal (`triagem-fiscal-duplicidade-v7?decisao=...`). Gera `_followup_corpo`, `_link_confirmar`, `_link_nao_duplicado`.

- **DUP3. GLPI: Renomear Titulo [Duplicado]**: `HTTP Request` PUT em `Ticket/<id>` definindo `name` com prefixo `[Duplicado]` e `status=4`.

- **DUP4. GLPI: Followup com Links Fiscal**: `HTTP Request` POST em `ITILFollowup` com corpo contendo `_followup_corpo` (insere comentário com links para auditor fiscal). Em seguida, o fluxo espera por clique fiscal (via `T4`).

- **DUP5..DUP9**: nós de persistência/espera históricos mantidos como `disabled=true` (migracao) — não utilizados no fluxo principal v7.

- **CL1. PG: Marcar BD (CLASSIFICANDO)**: atualiza BD para marcar `triagem_status='CLASSIFICANDO'` enquanto aguarda classificacao IA.

- **CL1b. GLPI: Mover para Pendente**: `HTTP Request` PUT que seta `status=4` no GLPI (manter em Pendente durante classificacao).

- **CL2. IA: OBRA vs Manutencao + Executor**: node LangChain/Google Gemini que pede classificacao OBRA|MANUTENCAO, executor (DEMO|SOB_DEMANDA|DDI_DG), categoria, justificativa e mensagem ao solicitante. Retry configurado.

- **CL3. Normalizar Classificacao**: `Code` node que interpreta resposta da IA; aplica heuristica local (palavras-chave) quando IA nao retorna campos validos; produz `classificacao` padronizada.

- **CL4. Switch: OBRA / DEMO / SOB_DEMANDA**: roteador que dispara caminhos:
  - `OBRA` → email para `DDI_DG` (Mailpit) + followup GLPI e fechamento (OBRA3/OBRA4).
  - `DEMO` → Atribuir no GLPI (status=2) e atualizar BD (DEMO3).
  - `SOB_DEMANDA` → marcar `Planejado` no GLPI e atualizar BD (SOB3).

- **OBRA1..OBRA4**: envio de e-mail real via SMTP (Mailpit), followup no GLPI e fechamento do chamado; atualiza BD com `FECHADO_OBRA`.

- **DEMO1..DEMO3**: atribui chamado no GLPI (status=2), posta followup e atualiza BD (`ATRIBUIDO_DEMO`).

- **SOB1..SOB3**: seta `status=3` (Planejado), posta followup e atualiza BD (`ENCAMINHADO_PLANEJADO`).

- **T4. Webhook Decisao Fiscal (Duplicidade)**: `GET` webhook em `triagem-fiscal-duplicidade-v7` que aceita `decisao=confirmar|nao_duplicado&chamado_id=ID&ref_id=ID_MATCH`.

- **FD1..FD9**: fluxo de processamento da decisao fiscal:
  - `FD1`: extrai query string e valida formato; define `modo_execucao='FISCAL_DECISAO'` quando valido.
  - `FD2`: busca registro no Postgres pelo `chamado_id` informado.
  - `FD3`: valida se o chamado existe e se estava aguardando aprovacao; decide `CONFIRMAR`|`REJEITAR`|`INVALIDO`.
  - `FD4`: switch que roteia confirmacao ou rejeicao.
  - `FD5..FD7`: quando confirmado, posta followup no GLPI, fecha no GLPI e atualiza BD (`DUPLICADO_FECHADO`).
  - `FD8..FD9`: quando rejeitado, limpa `em_aprovacao_fiscal`, restaura titulo no GLPI e reencaminha para classificacao.
  - `FD98/FD98a/FD99/FD99a`: nodes `respondToWebhook` que retornam mensagens amigaveis ao fiscal (200/400) conforme resultado.

- **Z1. Roteador Pos-Classificacao**: depois de atualizar BD para qualquer resultado de classificacao, roteia de volta para `SplitInBatches` (loop) ou responde se veio do fiscal.

Observações gerais:
- Credenciais: `PG_TRIAGEM` (Postgres) e `SMTP_MAILPIT_LOCAL` (SMTP) devem estar configuradas no n8n.
- Variáveis de ambiente: o `DUP2` usa `FISCAL_DECISION_BASE_URL` se presente; por padrão aponta para `http://localhost:5678`.
- Fallbacks: os `Code` nodes `D4` e `CL3` possuem heurísticas locais confiáveis caso a IA esteja indisponivel.

Se desejar, eu posso:
- Gerar uma versão HTML desta documentação;
- Inserir comentários inline adicionais nos `Code` nodes (se preferir mais detalhes para apresentação).

---
Arquivo gerado automaticamente em 2026-04-29 por auditoria do repositório.
