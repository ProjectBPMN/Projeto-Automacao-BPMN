# Workflow v7 - Documentacao por No

> **DOCUMENTO HISTÓRICO DA V7.** O fluxo ativo foi substituído pela V9. Este
> arquivo preserva apenas a explicação da revisão antiga; consulte
> `docs/rastreio_completo_workflows_v9.md` para o comportamento vigente e
> `n8n/history` para as cópias públicas sanitizadas.

Este arquivo descreve o funcionamento de cada no do workflow v7 publicado.

## Triggers

- T1. Manual (Reprocessar / Primeira Exec): dispara execucao manual para bootstrap ou reprocessamento.
- T2. Webhook GLPI (Novo Chamado): recebe `POST /webhook/glpi-ticket-novo-v7` com `ticket_id` e inicia triagem incremental.
- T3. Schedule 06h/12h/18h: agenda a sincronizacao periodica do GLPI para atualizar o Postgres sem IA.
- T4. Webhook Decisao Fiscal (Duplicidade): recebe `GET /webhook/triagem-fiscal-duplicidade-v7` para confirmar ou rejeitar duplicidade.

## Modo e roteamento inicial

- N1. Identificar Modo: detecta o modo bruto (MANUAL, INCREMENTAL, SCHEDULE ou FISCAL_DECISAO) a partir do trigger.
- N2. PG: Total no BD: conta registros no Postgres para decidir se e primeira execucao.
- N3. Resolver Modo Final: combina N1 + N2 e define o modo final (ex: primeira carga vs incremental).
- M0. Switch: Modo: roteia para busca inicial, busca do webhook, refresh agendado ou fluxo fiscal.

## Sessao GLPI e busca de chamados

- G1. GLPI: Iniciar Sessao: abre sessao na API REST do GLPI e retorna `session_token`.
- I1. GLPI: Buscar TUDO (Inicial): consulta chamados novos/pendentes e historico recente para bootstrap.
- C1. GLPI: Buscar Ticket do Webhook: busca apenas o chamado recebido no webhook incremental.
- S1. GLPI: Refresh Pend/Planej/Atrib/Soluc/Fechado: atualiza o Postgres com chamados nao-novos no modo schedule.

## Normalizacao e persistencia

- E1. Estruturar Chamados: normaliza o payload do GLPI para o schema interno do workflow.
- U1. PG: UPSERT Chamado: grava/atualiza os dados do chamado em `tickets_processados`.

## Filtro e lotes

- F1. Filtrar: Apenas Novos para Triar: libera apenas chamados novos (e pendentes no bootstrap) para IA.
- F2. Tem Chamados para Triar?: encerra o fluxo caso nao existam itens para triagem.
- L1. SplitInBatches (3): processa em lote de 1 item (nome mantido por historico).
- L2. Wait 20s entre lotes: atualmente e um no de codigo pass-through (sem espera real).

## Deduplicacao (IA + regras locais)

- D1. PG: Historico para Dedup: consulta candidatos de duplicidade no Postgres com ranking.
- D2. Montar Payload IA: monta entrada da IA com chamado atual + historico elegivel.
- D3. IA: Verificar Duplicidade: chama a IA (Gemini) para avaliar duplicidade.
- D3b. Wait 20s para Retry IA: no desabilitado, mantido como bypass tecnico.
- D4. Normalizar Dedup: normaliza saida da IA e aplica heuristica local de fallback.
- D5. E Duplicado?: decide se segue fluxo de duplicidade ou classificacao normal.

## Fluxo de duplicidade (pendente de fiscal)

- DUP1. PG: Marcar Em Aprovacao Fiscal: marca chamado como PENDENTE e em aprovacao fiscal.
- DUP2. Preparar Corpo do Followup: monta texto com justificativa e links do fiscal.
- DUP3. GLPI: Renomear Titulo [Duplicado]: adiciona prefixo `[Duplicado]` e move status para Pendente.
- DUP4. GLPI: Followup com Links Fiscal: registra followup com links de confirmacao e rejeicao.
- DUP5. Aguardar Decisao Fiscal (infinito): espera a decisao via webhook fiscal.
- DUP6. Decisao Fiscal: Confirmou?: bifurca entre confirmacao e rejeicao.
- DUP6a. Extrair IDs da Decisao: extrai `chamado_id` e `ref_id` do webhook fiscal.
- DUP7a. GLPI: Fechar Chamado Duplicado (status=6): fecha o chamado duplicado no GLPI.
- DUP7b. PG: Atualizar BD (DUPLICADO_FECHADO): registra status final no Postgres.
- DUP8. PG: Limpar em_aprovacao (Fiscal Rejeitou): remove flag de aprovacao e libera reclassificacao.
- DUP9. Reformatar para Classificacao: converte a rejeicao fiscal em payload de classificacao.

## Webhook fiscal (confirmar ou rejeitar)

- FD1. Extrair Decisao Fiscal: le `decisao`, `chamado_id` e `ref_id` do webhook.
- FD1b. Link Fiscal Valido?: valida parametros e rota erros.
- FD2. PG: Buscar Registro Fiscal: busca registro do chamado em aprovacao.
- FD3. Validar Registro Fiscal: garante consistencia do chamado antes de seguir.
- FD4. Switch Decisao Fiscal: bifurca entre confirmar duplicidade e nao duplicado.
- FD5. GLPI: Followup Duplicidade Confirmada: registra confirmacao no chamado.
- FD6. GLPI: Fechar Duplicado Confirmado: fecha o chamado como duplicado.
- FD7. PG: Confirmar Duplicidade Fiscal: atualiza status final no Postgres.
- FD8. PG: Limpar Aprovacao e Reclassificar: limpa flags e prepara reclassificacao.
- FD8b. GLPI: Restaurar Titulo Nao Duplicado: remove o prefixo `[Duplicado]` do titulo.
- FD9. Reformatar Rejeicao para Classificacao: prepara payload para o fluxo de classificacao.
- FD98. Responder Decisao Fiscal: responde ao webhook com o resumo da decisao.
- FD98a. Responder Confirmacao Duplicidade: resposta direta ao confirmar duplicidade.
- FD99. Responder Link Fiscal Invalido: responde 200 com mensagem de link invalido.
- FD99a. Responder Registro Fiscal Invalido: responde 200 quando o chamado nao esta elegivel.

## Classificacao OBRA/DEMO/SOB_DEMANDA

- CL1. PG: Marcar BD (CLASSIFICANDO): marca o chamado como CLASSIFICANDO no Postgres.
- CL1b. GLPI: Mover para Pendente: ajusta status do chamado para Pendente no GLPI.
- CL2. IA: OBRA vs Manutencao + Executor: classifica OBRA vs MANUTENCAO e executor.
- CL3. Normalizar Classificacao: normaliza saida da IA e aplica heuristica local.
- CL4. Switch: OBRA / DEMO / SOB_DEMANDA: direciona para o fluxo correto.

## Saidas por classificacao

- OBRA1. Enviar Email DDI/DG (Mailpit): envia e-mail ao setor responsavel.
- OBRA2. GLPI: Followup com Justificativa ao Solicitante: registra justificativa no chamado.
- OBRA3. GLPI: Fechar Chamado (status=6): fecha o chamado como obra.
- OBRA4. PG: Atualizar BD (FECHADO_OBRA): registra fechamento e classificacao.
- DEMO1. GLPI: Atribuir (status=2): atribui o chamado para DEMO.
- DEMO2. GLPI: Followup Atribuicao DEMO: registra followup de encaminhamento.
- DEMO3. PG: Atualizar BD (ATRIBUIDO_DEMO): grava status final no Postgres.
- SOB1. GLPI: Em Atendimento Planejado (status=3): move para Planejado.
- SOB2. GLPI: Followup Sob Demanda: registra followup de encaminhamento.
- SOB3. PG: Atualizar BD (ENCAMINHADO_PLANEJADO): grava status final no Postgres.

## Pos-classificacao

- Z1. Roteador Pos-Classificacao: separa origem do fluxo (TRIAGEM ou FISCAL) para respostas ou continuidade.
