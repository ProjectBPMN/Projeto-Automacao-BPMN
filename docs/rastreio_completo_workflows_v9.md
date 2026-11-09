# Rastreio completo dos workflows V9

## Escopo e fonte

Este documento descreve o comportamento implementado nos seis arquivos JSON da pasta `n8n/workflows/Versão9`, e não o comportamento pretendido em documentos antigos. A leitura foi feita nó a nó, incluindo conexões, ramos, chamadas ao GLPI, comandos PostgreSQL, gateway local-first/multi-modelo e respostas de webhook. O inventário de 172 nós foi reconferido após a integração local-first. Os seis workflows foram implantados e observados ativos antes da execução integrada `VALIDACAO-20260716T145412`, que percorreu GLPI, WF06, WF02/WF03, PostgreSQL e WF04. Essa execução é evidência histórica de integração de sua revisão, não de eficácia científica nem de execução E2E da revisão atual. Em 17/08, os JSONs correntes passaram em 913 verificações estáticas, nove testes de contrato e preflight real sem mutação. Os ramos positivo e `nao_duplicado` WF04/WF05 passaram nos E2E sintéticos `VALIDACAO-POSTS-E2E-20260818T004922Z` e `VALIDACAO-POSTS-E2E-20260818T004902Z`, incluindo manifesto SHA-256 dos seis exports, token expirado e inválido, dois POSTs concorrentes com uma única transição, replay idempotente, limpeza/handoff negativo e cleanup completo. A drenagem integral da fila até classificação terminal e a calibração isolada válida do WF06 permanecem pendentes.

| Workflow | Arquivo-fonte | Nós |
|---|---|---:|
| WF01 | `V9-WF01-Sincronizador.json` | 16 |
| WF02 | `V9-WF02-Triagem.json` | 43 |
| WF03 | `V9-WF03-Classificacao.json` | 38 |
| WF04 | `V9-WF04-Decisao-Fiscal.json` | 42 |
| WF05 | `V9-WF05-Metricas.json` | 15 |
| WF06 | `V9-WF06-Fila-IA.json` | 18 |
| **Total** | **6 JSONs** | **172** |

## Natureza da validação automatizada desta etapa

Nesta etapa, os ensaios automatizados são classificados como **`VALIDACAO AUTOMATIZADA NAO CONFIRMATORIA`**. A rodada dispensa dupla revisão humana do gabarito porque seu objetivo é regressão técnica, integração e detecção de falhas; ela não deve ser apresentada como benchmark confirmatório, estimativa final de eficácia ou substituição de avaliação humana.

A dispensa de dupla revisão nesta fase **não remove, desativa nem contorna as confirmações humanas dos workflows**:

- possíveis duplicados continuam pendentes no WF02 até uma decisão fiscal processada pelo WF04;
- decisões de deduplicação ou classificação abaixo do limiar continuam encaminhadas à triagem manual;
- o webhook e os nós 9 a 12 de avaliação humana do WF05 continuam implementados;
- o harness externo `avaliacao/scripts/conferir_gabarito.py` — nunca um ramo do WF06 — pode percorrer, apenas em execução sintética `test-only`, os mesmos links/endpoints do WF04/WF05 que seriam usados pela pessoa, somente depois de persistidos predição, probabilidades e candidatos; o gabarito permanece fora da entrada do modelo;
- a chamada do oráculo determinístico externo de teste deve ser idempotente e falhar fechado sem `run_id`, split/fase sintética ou demais guardas. Reserva, tentativas e resultados ficam na tabela separada `avaliacao_auto_confirmacoes`, vinculados à decisão da IA, com hashes de token/nonce e restrições únicas;
- a automação não preenche `avaliacoes_humanas` nem atribui identidade de avaliador a uma resposta sintética.

Essa substituição operacional pelo oráculo determinístico externo de teste serve
para testar a transição contra o gabarito
pré-especificado. Não equivale a dupla revisão humana, não valida a qualidade do
gabarito e não existe na operação de produção, em que o checkpoint volta a
aguardar uma pessoa. Assim, os nós humanos permanecem parte do comportamento
operacional descrito abaixo, enquanto a evidência automatizada desta etapa
permanece técnica e não confirmatória.

## Visão ponta a ponta

1. Um chamado novo chega pelo webhook do **WF06** ou é recuperado pela sincronização periódica do **WF01**.
2. O chamado é persistido em `tickets_processados` com `triagem_status=PENDENTE_FILA_IA` e `fila_etapa=DEDUPLICACAO`.
3. O agendador do **WF06** reserva um lote, distribui horários de liberação e chama o **WF02** com autenticação interna.
4. O **WF02** confirma os dados no GLPI, corrige a categoria técnica quando uma heurística determinística encontra uma categoria local mais adequada e envia o chamado mais seus candidatos históricos ao gateway de IA. Na configuração operacional atual, o gateway tenta primeiro o serviço local híbrido; chamadas remotas são contingência explícita.
5. Se o resultado for um possível duplicado, o chamado fica pendente e o GLPI recebe links para decisão fiscal no **WF04**. Se não for duplicado com confiança suficiente, o **WF02** reenfileira o ticket como `PENDENTE_FILA_IA/CLASSIFICACAO`; o **WF06** o reserva em outro ciclo e chama o **WF03**. Qualquer decisão de deduplicação abaixo do limiar vai para triagem manual antes de fechamento ou encaminhamento.
6. O **WF04** valida token e estado de forma idempotente. A confirmação fecha o duplicado; a rejeição remove as marcas de duplicidade e reenfileira o chamado para `CLASSIFICACAO`.
7. O **WF03** usa o mesmo gateway local-first para decidir a classe semântica `OBRA`, `DEMO`, `SOB_DEMANDA` ou `TRIAGEM_MANUAL`. Uma baixa confiança gera `ABSTENCAO` operacional e revisão, sem reescrever a classe prevista como `TRIAGEM_MANUAL`. A disponibilidade da equipe DEMO altera somente a rota operacional entre atendimento imediato e planejado.
8. O **WF05** consolida observabilidade e recebe avaliações humanas. Ele é **analítico e de apoio**: não deve ser interpretado como o motor operacional da triagem nem como substituto do protocolo científico em Python e PostgreSQL.

Fluxo resumido de estados:

```text
PENDENTE_SYNC
  -> PENDENTE_FILA_IA/DEDUPLICACAO
  -> FILA_IA_LIBERADA
  -> CLASSIFICANDO_DUP
       -> PENDENTE + POSSIVEL_DUPLICADO + AGUARDANDO_FISCAL
            -> DUPLICADO_FECHADO, se o fiscal confirmar
            -> PENDENTE_FILA_IA/CLASSIFICACAO, se o fiscal rejeitar
       -> PENDENTE_FILA_IA/CLASSIFICACAO -> WF06 -> WF03, se não duplicado com confiança
       -> TRIAGEM_MANUAL, se qualquer decisão ficar abaixo do limiar
       -> PENDENTE_FILA_IA ou ERRO_IA, se a cadeia permitida não produzir JSON válido
  -> WF06 libera CLASSIFICACAO -> WF03
       -> FECHADO_OBRA
       -> ATRIBUIDO_DEMO
       -> PLANEJADO_DEMO_SEM_EQUIPE
       -> ENCAMINHADO_PLANEJADO/SOB_DEMANDA
       -> TRIAGEM_MANUAL, como classe semântica coberta
       -> ABSTENCAO -> revisão manual, sem classe automática coberta
       -> PENDENTE_FILA_IA ou ERRO_IA, se a cadeia permitida não produzir JSON válido
```

## Superfícies de dados e efeitos externos

- **GLPI:** sessões REST, leitura e atualização de `Ticket`, leitura de `ITILCategory`, criação e remoção de `ITILFollowup` e mudança dos estados numéricos 1 a 6.
- **PostgreSQL:** `tickets_processados` guarda o estado operacional; `fila_ia_controle`, `fila_ia_metricas` e `fila_ia_dead_letter` apoiam a fila; `ia_decisoes` guarda a decisão selecionada; `ia_tentativas_modelo` guarda cada chamada a provedor, inclusive falhas e fallback; `workflow_eventos` guarda eventos; `dataset_controle`, `experimentos_avaliacao` e `avaliacoes_humanas` apoiam a avaliação científica; `avaliacao_auto_confirmacoes` isola reservas e resultados do oráculo determinístico externo de teste, sem convertê-los em avaliações humanas.
- **Reconciliação de falhas históricas:** `vw_erros_ia_sem_dead_letter` lista tickets em `ERRO_IA` para os quais não existe nenhuma linha correspondente em `fila_ia_dead_letter`. A view expõe a lacuna deixada por versões anteriores para diagnóstico e análise de causa; ela não cria dead letters retroativas nem transforma ausência de registro em tentativa observada.
- **Gateway de IA:** a sequência operacional configurada é `LOCAL → SECONDARY`. `LOCAL` chama a API nativa em `IA_LOCAL_BASE_URL`, usa o candidato híbrido `local-hybrid-v1.8.0` e exige metadados que comprovem Granite Embedding 97M em PyTorch FP32, 384 dimensões, revisão congelada, hash da árvore do modelo e ausência de fallback de desenvolvimento. `SECONDARY` é `gemini-3.5-flash` e entra apenas após falha explícita em operação. O gateway ativo implementa somente esses dois papéis; DeepSeek aparece apenas como candidato bloqueado na política de pesquisa, sem executor ou chamada operacional. Cada tentativa fica em `ia_tentativas_modelo`. Em qualquer `run_id` experimental o fallback é desabilitado e o papel/modelo congelado é conferido antes da chamada; nenhum modelo substitui silenciosamente o modelo avaliado.
- **E-mail:** WF02 notifica a infraestrutura após erro terminal de deduplicação; WF03 encaminha OBRA ao DDI/DG; WF05 envia alertas operacionais.

## WF01 — Sincronizador

Objetivo: sincronizar periodicamente o GLPI com o PostgreSQL, manter o schema e recuperar chamados novos para a fila.

| # | Nó | Entrada, saída e efeito | Próximo passo |
|---:|---|---|---|
| 1 | `T1. Manual` | Disparo manual sem carga útil; inicia uma sincronização sob demanda. | `LOG: Início` |
| 2 | `T2. Schedule 06h/12h` | Cron `0 6,12 * * *`; dispara diariamente às 06h e 12h. | `LOG: Início` |
| 3 | `LOG: Início` | Registra o começo do WF01 e emite um timestamp. | `PG: Garantir Schema` |
| 4 | `PG: Garantir Schema` | Executa SQL idempotente de criação/alteração de tabelas, índices e views V9. Abrange estado operacional, fila, decisões de IA, eventos, datasets, experimentos, avaliações humanas, confirmações automáticas `test-only`, métricas e a view de reconciliação `vw_erros_ia_sem_dead_letter`. Emite `schema_ok`. | `PG: Retenção 90 dias` |
| 5 | `PG: Retenção 90 dias` | Remove de `tickets_processados` registros solucionados/fechados há mais de 90 dias que não estejam em aprovação fiscal; devolve a quantidade removida. | `LOG: Retenção 90 dias` |
| 6 | `LOG: Retenção 90 dias` | Registra a contagem removida e preserva o resultado SQL. | `GLPI: Iniciar Sessão` |
| 7 | `GLPI: Iniciar Sessão` | Faz `GET /initSession` com App-Token e autenticação básica; espera `session_token`. | `Validar Sessão GLPI` |
| 8 | `Validar Sessão GLPI` | Recusa a execução se o GLPI não devolver token de sessão; caso válido, repassa o item. | `GLPI: Buscar Chamados` |
| 9 | `GLPI: Buscar Chamados` | Faz `GET /search/Ticket`, busca estados 1 a 6, solicita título, ID, estado, descrição, localização, datas, solicitante e categoria, com faixa `0-9999`. | `Estruturar e Filtrar` |
| 10 | `Estruturar e Filtrar` | Normaliza HTML, estados, IDs e datas; consulta em paralelo detalhes, atores, usuário e e-mail de cada ticket. Mantém sempre Novo/Pendente e, para os demais estados, somente itens abertos ou alterados nos últimos 90 dias. Emite um único objeto com `chamados`, total, origem manual/agendada e dados do lote. | `Tem Chamados?` |
| 11 | `Tem Chamados?` | Testa se `chamados` é uma lista não vazia. | Verdadeiro: `PG: UPSERT Chamado`; falso: `GLPI: Encerrar Sessão` |
| 12 | `PG: UPSERT Chamado` | Faz UPSERT em lote em `tickets_processados`, preserva datas mais recentes, grava origem e log WF01 e inicia novos registros em `PENDENTE_SYNC`. Devolve total, inseridos e atualizados. | `LOG: Resumo Sync` |
| 13 | `LOG: Resumo Sync` | Registra e emite o resumo do UPSERT. | `PG: Enfileirar Pendentes WF06` |
| 14 | `PG: Enfileirar Pendentes WF06` | Para tickets GLPI em estado Novo e `PENDENTE_SYNC`, define `PENDENTE_FILA_IA`, etapa `DEDUPLICACAO`, horários da fila e ação `WF01_RECUPEROU_PARA_FILA`. | `GLPI: Encerrar Sessão` |
| 15 | `GLPI: Encerrar Sessão` | Faz `GET /killSession` com o token aberto no início. | `LOG: Fim` |
| 16 | `LOG: Fim` | Registra o término e emite `{ok:true, ts}`. | Fim |

## WF02 — Triagem e deduplicação

Objetivo: validar a entrada interna, obter o ticket real, preparar candidatos comparáveis, registrar decisão e tentativas do gateway e encaminhar para fiscal, fila de classificação, revisão manual ou tratamento de erro.

| # | Nó | Entrada, saída e efeito | Próximo passo |
|---:|---|---|---|
| 1 | `Início Subworkflow/Teste` | Recebe um item de subworkflow, normalmente liberado pelo WF06. | `Preparar Entrada` |
| 2 | `Preparar Entrada` | Extrai chamado/ID, exige origem `wf06-fila-ia` ou `wf01-sync-test` e compara a chave recebida com `GLPI_WEBHOOK_KEY`. Emite chamado autenticado ou erro. | `Entrada Válida?` |
| 3 | `Entrada Válida?` | Verifica `erro !== true`. | Válido: `GLPI: Iniciar Sessão`; inválido: `LOG: Entrada Inválida` |
| 4 | `LOG: Entrada Inválida` | Registra a recusa e emite resultado de erro sem acessar GLPI ou IA. | `LOG: Fim WF02` |
| 5 | `GLPI: Iniciar Sessão` | Abre sessão REST no GLPI. | `Validar Sessão GLPI` |
| 6 | `Validar Sessão GLPI` | Exige `session_token` não vazio. | `GLPI: Buscar Ticket` |
| 7 | `GLPI: Buscar Ticket` | Consulta `GET /search/Ticket` pelo ID e solicita os campos necessários à triagem. | `Estruturar Chamado` |
| 8 | `Estruturar Chamado` | Combina o evento recebido com a leitura atual do GLPI, normaliza HTML, status e metadados, preserva `run_id`, split e política de modelo e decide se o item representa um chamado Novo aceitável, inclusive o evento real de criação que o GLPI já tenha movido automaticamente. | `Chamado é Novo?` |
| 9 | `Chamado é Novo?` | Testa `aceitar_triagem_novo`. | Sim: `Validar Categoria Técnica`; não: `LOG: Ignorar Não Novo` |
| 10 | `LOG: Ignorar Não Novo` | Registra status atual, status do evento, origem e motivo; não altera o chamado. | `GLPI: Encerrar Sessão` |
| 11 | `Validar Categoria Técnica` | Consulta o catálogo `ITILCategory` e aplica regras determinísticas por palavras-chave para Elétrica, Hidráulica, Serviços Terceirizados, Mecânica Geral, Carpintaria/Marcenaria, Limpeza/Jardinagem e Manutenção Predial. Emite categoria atual, sugerida e chamado enriquecido; não usa LLM. | `Categoria precisa correção?` |
| 12 | `Categoria precisa correção?` | Compara categoria sugerida e categoria atual. | Sim: `GLPI: Corrigir Categoria`; não: `PG: UPSERT Webhook` |
| 13 | `GLPI: Corrigir Categoria` | Faz `PUT /Ticket/{id}` e atualiza `itilcategories_id`. | `GLPI: Followup Categoria Corrigida` |
| 14 | `GLPI: Followup Categoria Corrigida` | Cria followup auditável informando categoria anterior, nova categoria e que a correção ocorreu antes da deduplicação. | `PG: UPSERT Webhook` |
| 15 | `PG: UPSERT Webhook` | Insere/atualiza `tickets_processados`, grava o log de ingestão e só muda para `CLASSIFICANDO_DUP` quando o item veio efetivamente da fila ou ainda não está em estado terminal/protegido. Emite `deve_processar`. | `Deve processar dedup?` |
| 16 | `Deve processar dedup?` | Impede reprocessamento de ticket já em aprovação, concluído, manual ou terminal. | Sim: `PG: Histórico Dedup`; não: `GLPI: Encerrar Sessão` |
| 17 | `PG: Histórico Dedup` | Busca até 80 tickets diferentes do atual. Em operação considera estados abertos e itens recentes de até 90 dias; em experimento restringe candidatos anteriores ao atual no mesmo `run_id`/partição física. `episode_id` não filtra a recuperação, permitindo distratores de outros núcleos sem vazamento do futuro. | `Montar Payload Dedup` |
| 18 | `Montar Payload Dedup` | Limpa e limita texto, calcula relevância por local, categoria, título, descrição e tempo, remove o próprio ticket e ordena candidatos. A configuração final usa `DEDUP_CANDIDATE_LIMIT=20` e `DEDUP_LOCAL_TOP_K=20`, entregando a mesma lista e ordem de até 20 itens a todos os papéis. Em benchmark, força os dois limites em 20, preserva IDs/hash/política do snapshot pareado e bloqueia divergência. | `IA: Verificar Duplicidade` |
| 19 | `IA: Verificar Duplicidade` | Nó Code do gateway local-first. Para `LOCAL`, envia JSON nativo a `/v1/deduplicate?include_metadata=1`, usa `historico_local` e valida contrato, PyTorch FP32, 384 dimensões, revisão/hash do Granite e ausência de fallback de desenvolvimento. Para os papéis remotos, renderiza o prompt canônico e usa o histórico remoto. Em todos os casos valida transporte/schema/probabilidades; fallback só é permitido na operação sem `run_id`. Em benchmark exige papel/modelo congelados e falha fechado em divergência. Emite resposta selecionada, política e lista completa de tentativas. | `Normalizar Dedup` |
| 20 | `Normalizar Dedup` | Extrai o JSON selecionado, preserva a proveniência e valida tipos, referência e probabilidades em `[0,1]` cuja soma deve ser 1. Fora de empate, o rótulo deve concordar com a maior probabilidade; a confiança operacional é a probabilidade da classe escolhida. Erro estrutural vira `erro_ia`. Produz `ABSTENCAO` e `requer_revisao_dedup=true` diante de abstenção declarada, gate científico bloqueante, empate, confiança abaixo de `IA_CONFIANCA_MINIMA` ou probabilidade de duplicidade entre `DEDUP_NEGATIVE_THRESHOLD=0,07` e `DEDUP_POSITIVE_THRESHOLD=0,95`. A região intermediária nunca é convertida silenciosamente em “não duplicado”. | `PG: Registrar IA Dedup` |
| 21 | `PG: Registrar IA Dedup` | Antes de qualquer efeito no chamado, insere a decisão selecionada em `ia_decisoes`, cada chamada em `ia_tentativas_modelo` e o evento em `workflow_eventos`, retornando `ia_decisao_id`. Registra entrada exata, perfil/quantidade de candidatos, hashes, respostas, provedor/modelo/papel, fallback, latência, tokens, política e metadados científicos locais. Distingue `candidate_evaluation_eligible` — o bundle híbrido executou — de `pipeline_evaluation_eligible` — a linha veio de um caminho congelado permitido, inclusive gate determinístico. Somente o segundo habilita a linha do benchmark; nenhum deles equivale a validação científica concluída. | `Decisão IA Persistida?` |
| 22 | `Decisão IA Persistida?` | Exige `ia_decisao_id` inteiro positivo. Isso garante separação temporal: a predição torna-se auditável e imutável antes de fechar, encaminhar, reenfileirar ou liberar o oráculo determinístico externo de teste. | Sim: `Duplicado?`; não: `Preparar Erro Persistência IA` |
| 23 | `Preparar Erro Persistência IA` | Converte a falha de gravação em erro fechado `IA_DECISION_PERSISTENCE_FAILED`, não repetível e de configuração. Nenhuma ação de duplicidade ou classificação é executada sem a decisão persistida. | `PG: Erro IA Dedup` |
| 24 | `Duplicado?` | Switch com saídas `ERRO_IA`, `TRIAGEM_MANUAL`, `DUPLICADO`, `NAO_DUPLICADO`; saída inesperada também cai no tratamento de erro. | Direciona aos quatro ramos abaixo |
| 25 | `PG: Erro IA Dedup` | Sob o mesmo advisory lock usado pelo controle da fila, classifica o erro e incrementa tentativas. HTTP 429 respeita `Retry-After` e aplica cooldown global; 503/timeout usa backoff exponencial com jitter; erro HTTP 4xx permanente encerra sem nova tentativa. Falhas repetíveis voltam a `PENDENTE_FILA_IA/DEDUPLICACAO`, com no máximo três tentativas e teto de espera configurável; falha terminal vira `ERRO_IA` e dead letter. | `Retry Dedup?` |
| 26 | `Retry Dedup?` | Verifica se a falha foi reenfileirada. | Sim: `Preparar Retry Dedup`; não: `Preparar Erro` |
| 27 | `Preparar Retry Dedup` | Emite resumo de reenvio e quantidade de tentativas. | `GLPI: Encerrar Sessão` |
| 28 | `Preparar Erro` | Monta título `[Erro IA]`, aviso de followup e mensagem de e-mail com ID, erro e tentativas após falha terminal. | `Atualizar Título` |
| 29 | `Atualizar Título` | Faz PUT no ticket e adiciona a marca de erro ao título. | `Inserir Aviso` |
| 30 | `Inserir Aviso` | Cria followup no GLPI explicando a falha de automação. | `Notificar TI` |
| 31 | `Notificar TI` | Envia e-mail para `INFRA_EMAIL` com o incidente de deduplicação. | `GLPI: Encerrar Sessão` |
| 32 | `PG: Marcar Possível Duplicado` | Cria token fiscal com validade configurável, grava referência, justificativa, `POSSIVEL_DUPLICADO`, estado Pendente e `em_aprovacao_fiscal=true`. | `Preparar Followup Dup` |
| 33 | `Preparar Followup Dup` | Gera título `[Duplicado]`, marcador único e links assinados de confirmar ou rejeitar para o webhook do WF04. | `GLPI: Marcar [Duplicado]` |
| 34 | `GLPI: Marcar [Duplicado]` | Atualiza título e estado GLPI para Pendente. | `GLPI: Followup Links` |
| 35 | `GLPI: Followup Links` | Publica no ticket a comparação, justificativa e links de decisão fiscal. | `GLPI: Marcar Pendente2` |
| 36 | `GLPI: Marcar Pendente2` | Reforça o estado GLPI 4 após a publicação dos links. | `GLPI: Encerrar Sessão` |
| 37 | `PG: Marcar Não Duplicado` | Limpa marcas de duplicidade, mantém Pendente e grava `PENDENTE_FILA_IA/CLASSIFICACAO`, disponível para nova reserva pelo WF06. Incrementa as contagens de tentativa e registra `WF02_ENFILEIROU_CLASSIFICACAO`; não chama o WF03 diretamente. | `GLPI: Marcar Pendente` |
| 38 | `GLPI: Marcar Pendente` | Faz PUT do estado GLPI 4. | `GLPI: Encerrar Sessão` |
| 39 | `GLPI: Pendente Revisão Dedup` | No ramo de abstenção/baixa confiança de qualquer classe de deduplicação, garante estado GLPI Pendente. | `GLPI: Followup Revisão Dedup` |
| 40 | `GLPI: Followup Revisão Dedup` | Informa ao fiscal que a decisão ficou na região de abstenção, incluindo confiança e justificativa, sem executar fechamento ou classificação automática. | `PG: Triagem Manual Dedup` |
| 41 | `PG: Triagem Manual Dedup` | Define rota operacional `TRIAGEM_MANUAL`, executor `FISCAL`, mantém estado Pendente e registra confiança, motivo e tentativas. | `GLPI: Encerrar Sessão` |
| 42 | `GLPI: Encerrar Sessão` | Encerra a sessão GLPI em todos os ramos que a abriram. | `LOG: Fim WF02` |
| 43 | `LOG: Fim WF02` | Registra o encerramento e emite `{ok:true}`. | Fim |

## WF03 — Classificação e roteamento

Objetivo: classificar semanticamente o chamado e aplicar no GLPI/PostgreSQL a rota operacional correspondente.

| # | Nó | Entrada, saída e efeito | Próximo passo |
|---:|---|---|---|
| 1 | `Início Classificação` | Recebe `{chamado}` do WF06 na etapa `CLASSIFICACAO`; uma execução direta fica reservada a teste controlado de subworkflow. | `Preparar Classificação` |
| 2 | `Preparar Classificação` | Preserva status original, normaliza o objeto e prepara o estado intermediário Pendente. | `GLPI: Iniciar Sessão` |
| 3 | `GLPI: Iniciar Sessão` | Abre sessão REST no GLPI. | `Validar Sessão GLPI` |
| 4 | `Validar Sessão GLPI` | Exige token de sessão. | `Já está Pendente?` |
| 5 | `Já está Pendente?` | Compara o status original com 4. | Já pendente: `PG: Pendente Inicial`; outro: `GLPI: Marcar Pendente Inicial` |
| 6 | `GLPI: Marcar Pendente Inicial` | Faz PUT para estado GLPI 4 antes da chamada à IA. | `PG: Pendente Inicial` |
| 7 | `PG: Pendente Inicial` | Sincroniza estado Pendente e registra a ação intermediária em `tickets_processados`. | `Montar Payload Classificação` |
| 8 | `Montar Payload Classificação` | Limita título, descrição, localização, tipo de serviço, solicitante e e-mail; recusa objeto sem ID. | `IA: Classificar` |
| 9 | `IA: Classificar` | Nó Code do gateway com a mesma política local-first da deduplicação. Para `LOCAL`, envia JSON nativo a `/v1/classify?include_metadata=1` e valida o runtime PyTorch FP32 congelado; para provedores remotos, renderiza o prompt de OBRA/DEMO/SOB_DEMANDA/TRIAGEM_MANUAL. Em qualquer papel exige saída estruturada válida antes da seleção e emite proveniência/tentativas. | `Normalizar Classificação` |
| 10 | `Normalizar Classificação` | Extrai JSON, valida as quatro probabilidades e soma 1, exige concordância entre classe declarada e maior probabilidade e usa a probabilidade escolhida como confiança. `TRIAGEM_MANUAL` declarada pelo modelo permanece a quarta classe semântica coberta. Abstenção declarada, falta de informação/localização operacional ou confiança abaixo do limiar produz `decisao_operacional_classif=ABSTENCAO`, preservando separadamente `classe_semantica`, tipo/executor declarados e os scores semânticos pré-abstenção; a rota prática segue para revisão. `DEMO_EQUIPE_DISPONIVEL` altera apenas atendimento imediato versus planejado. | `PG: Registrar IA Classificação` |
| 11 | `PG: Registrar IA Classificação` | Antes de qualquer efeito no chamado, grava atomicamente a decisão em `ia_decisoes`, as chamadas em `ia_tentativas_modelo` e o evento; inclui entrada exata, hashes, saída, classe semântica antes da abstenção, decisão operacional, probabilidades, proveniência e metadados científicos locais. `ABSTENCAO` reduz cobertura e permanece distinta de `TRIAGEM_MANUAL`; scores model-based pré-abstenção podem compor AUC/Brier/Log Loss sem transformar a linha em decisão automática. | `Decisão IA Classificação Persistida?` |
| 12 | `Decisão IA Classificação Persistida?` | Exige `ia_decisao_id` inteiro positivo. Só libera o switch operacional quando a predição, as probabilidades e a proveniência já estão auditáveis e imutáveis. | Sim: `Switch Classificação`; não: `Preparar Erro Persistência IA Classif` |
| 13 | `Preparar Erro Persistência IA Classif` | Converte ausência/falha de persistência em erro fechado `IA_DECISION_PERSISTENCE_FAILED`, de configuração e não repetível como inferência. Nenhuma rota GLPI de obra, manutenção ou triagem é executada sem a decisão persistida. | `PG: Erro IA Classif` |
| 14 | `Switch Classificação` | Switch operacional para `ERRO_IA`, `TRIAGEM_MANUAL`, `OBRA`, `DEMO_SEM_EQUIPE`, `DEMO` ou `SOB_DEMANDA`; valor inesperado cai em erro. A classe semântica `TRIAGEM_MANUAL` e a `ABSTENCAO` usam o mesmo ramo humano, mas permanecem distintas na auditoria. | Direciona aos ramos abaixo |
| 15 | `PG: Erro IA Classif` | Sob o lock da fila, incrementa tentativas e diferencia rate limit, indisponibilidade/timeout, erro permanente e falha de persistência. HTTP 429 respeita `Retry-After`; 503/timeout recebe backoff exponencial com jitter; erro de configuração falha fechado. Erros repetíveis reenfileiram `CLASSIFICACAO`, no máximo até a terceira tentativa, e o restante vai para `ERRO_IA`/dead letter. | `Retry Classificação?` |
| 16 | `Retry Classificação?` | Testa se o ticket voltou a `PENDENTE_FILA_IA`. | Sim: `Preparar Retry Classificação`; não: `Preparar Erro` |
| 17 | `Preparar Retry Classificação` | Registra e emite o resumo do reenvio à fila. | `GLPI: Encerrar Sessão` |
| 18 | `Preparar Erro` | Monta título e aviso de falha terminal de classificação. | `GLPI: Atualizar Título [Erro IA]` |
| 19 | `GLPI: Atualizar Título [Erro IA]` | Adiciona `[Erro IA]` ao título do ticket. | `GLPI: Followup Aviso` |
| 20 | `GLPI: Followup Aviso` | Registra no GLPI a falha e a necessidade de tratamento interno. | `GLPI: Encerrar Sessão` |
| 21 | `GLPI: Pendente Triagem Manual` | Mantém o ticket no estado 4. | `GLPI: Followup Triagem Manual` |
| 22 | `GLPI: Followup Triagem Manual` | Explica que o fiscal deve classificar manualmente e informa justificativa/confiança. | `PG: Triagem Manual` |
| 23 | `PG: Triagem Manual` | Grava a rota operacional de revisão, executor `FISCAL`, estado Pendente e auditoria. A decisão analítica já persistida distingue classe semântica `TRIAGEM_MANUAL` de `ABSTENCAO`. | `GLPI: Encerrar Sessão` |
| 24 | `GLPI: Followup OBRA` | Informa que a demanda foi encaminhada ao DDI/DG e inclui justificativa e mensagem ao solicitante. | `GLPI: Fechar OBRA` |
| 25 | `GLPI: Fechar OBRA` | Muda o estado GLPI para Fechado, número 6. | `PG: Fechado OBRA` |
| 26 | `PG: Fechado OBRA` | Grava `FECHADO_OBRA`, classe `OBRA`, executor `DDI_DG`, confiança e motivo. | `Email DDI/DG (OBRA)` |
| 27 | `Email DDI/DG (OBRA)` | Envia ao DDI/DG os dados e a justificativa da demanda classificada como obra. | `GLPI: Encerrar Sessão` |
| 28 | `GLPI: Planejar DEMO sem equipe` | Para uma classe semântica DEMO sem disponibilidade imediata, muda o GLPI para Planejado, estado 3. | `GLPI: Followup DEMO sem equipe` |
| 29 | `GLPI: Followup DEMO sem equipe` | Registra que o serviço é interno, mas aguardará disponibilidade da equipe. | `PG: Planejado DEMO sem equipe` |
| 30 | `PG: Planejado DEMO sem equipe` | Grava classe final semântica `DEMO`, executor DEMO e rota `PLANEJADO_DEMO_SEM_EQUIPE`. | `GLPI: Encerrar Sessão` |
| 31 | `GLPI: Atribuir DEMO` | Quando a equipe está disponível, muda o GLPI para Em atendimento atribuído, estado 2. | `GLPI: Followup DEMO` |
| 32 | `GLPI: Followup DEMO` | Registra categoria e justificativa da manutenção interna. | `PG: Atribuído DEMO` |
| 33 | `PG: Atribuído DEMO` | Grava `ATRIBUIDO_DEMO`, classe final/executor DEMO, confiança e motivo. | `GLPI: Encerrar Sessão` |
| 34 | `GLPI: Planejado SOB_DEMANDA` | Muda o GLPI para Planejado, estado 3. | `GLPI: Followup SOB_DEMANDA` |
| 35 | `GLPI: Followup SOB_DEMANDA` | Registra que o serviço requer empresa especializada. | `PG: Planejado SOB_DEMANDA` |
| 36 | `PG: Planejado SOB_DEMANDA` | Grava rota `ENCAMINHADO_PLANEJADO`, classe/executor `SOB_DEMANDA`, confiança e motivo. | `GLPI: Encerrar Sessão` |
| 37 | `GLPI: Encerrar Sessão` | Fecha a sessão GLPI depois de qualquer ramo operacional. | `LOG: Fim Classificação` |
| 38 | `LOG: Fim Classificação` | Registra o término e emite `{ok:true}`. | Fim |

## WF04 — Decisão fiscal de duplicidade

Objetivo: receber os links gerados pelo WF02, garantir autenticidade, expiração e idempotência e executar a confirmação ou rejeição fiscal. Este workflow humano permanece integralmente no fluxo. Em validação sintética, o oráculo determinístico externo de teste `conferir_gabarito.py` pode chamar o mesmo endpoint depois do registro imutável da predição; a reserva/ação fica em `avaliacao_auto_confirmacoes` e nunca é registrada ou interpretada como decisão de um fiscal, dupla revisão humana ou validação externa. O WF06 não contém ramo de oráculo.

| # | Nó | Entrada, saída e efeito | Próximo passo |
|---:|---|---|---|
| 1 | `Webhook Fiscal` | Endpoint de mutação `POST fiscal-decisao-fiscal-ic-2026`; recebe decisão, chamado, referência e token somente após a confirmação explícita. | `Extrair Decisão` |
| 2 | `Extrair Decisão` | Aceita apenas `confirmar` ou `nao_duplicado`, ID positivo e token hexadecimal com 32 a 128 caracteres. Emite validade e motivo da invalidez. | `Link Válido?` e, em paralelo, `PG: Registrar Link Fiscal` |
| 3 | `PG: Registrar Link Fiscal` | Registra em `workflow_eventos` se o formato do link era válido, incluindo erro e motivo. | Fim do ramo de auditoria |
| 4 | `Link Válido?` | Separa links formalmente válidos dos inválidos. | Válido: `GLPI: Sessão Fiscal`; inválido: `Tem Chamado no Link?` |
| 5 | `Tem Chamado no Link?` | Verifica se há chamado identificável mesmo com os demais campos inválidos. | Sim: `GLPI: Sessão Link Inválido`; não: `LOG: Link Sem Chamado` |
| 6 | `GLPI: Sessão Link Inválido` | Abre sessão para registrar o erro no ticket conhecido. | `GLPI: Anotar Link Inválido` |
| 7 | `GLPI: Anotar Link Inválido` | Cria followup técnico explicando que o link não pôde ser processado e que o fiscal não deve repetir a ação. | `Resp: Falha Anotada` |
| 8 | `Resp: Falha Anotada` | Responde HTTP 202 informando que a falha foi registrada. | `GLPI: Encerrar Sessão Link Inválido` |
| 9 | `GLPI: Encerrar Sessão Link Inválido` | Fecha a sessão usada para anotação. | `LOG: Link Inválido Anotado` |
| 10 | `LOG: Link Inválido Anotado` | Registra que o GLPI recebeu a anotação. | Fim |
| 11 | `LOG: Link Sem Chamado` | Registra invalidez sem ID, quando não existe ticket no qual anotar. | `Resp: Falha Sem Chamado` |
| 12 | `Resp: Falha Sem Chamado` | Responde HTTP 202 informando que somente os logs internos receberam a falha. | Fim |
| 13 | `GLPI: Sessão Fiscal` | Abre sessão para processar uma decisão formalmente válida. | `PG: Buscar Chamado` |
| 14 | `PG: Buscar Chamado` | Busca o estado e, atomicamente, reserva a decisão somente se token, validade e aprovação pendente conferirem. Marca temporariamente `PROCESSANDO_CONFIRMAR_DUP` ou `PROCESSANDO_REJEITAR_DUP`; emite se a reserva ocorreu. | `Validar Fiscal` |
| 15 | `Validar Fiscal` | Distingue `CONFIRMAR`, `REJEITAR`, `JA_REGISTRADO` e `INVALIDO`, cobrindo token expirado, ausente, divergente, ticket inexistente e clique repetido. | `Switch Ação Fiscal` e, em paralelo, `PG: Registrar Decisão Fiscal` |
| 16 | `PG: Registrar Decisão Fiscal` | Registra o resultado da validação em `workflow_eventos`, incluindo idempotência ou erro. | Fim do ramo de auditoria |
| 17 | `Switch Ação Fiscal` | Encaminha a ação validada aos quatro ramos. | Nós de resposta correspondentes |
| 18 | `Resp: Confirmado` | Responde HTTP 202 imediatamente; o restante da confirmação continua no workflow. | `GLPI: Followup Confirmado` |
| 19 | `GLPI: Followup Confirmado` | Registra a confirmação e a referência do chamado anterior. | `GLPI: Fechar Confirmado` |
| 20 | `GLPI: Fechar Confirmado` | Muda o ticket para Fechado, estado 6. | `PG: Duplicado Fechado` |
| 21 | `PG: Duplicado Fechado` | Grava `DUPLICADO_FECHADO`, decisão `CONFIRMOU_DUP`, classe final `DUPLICADO`, limpa o token e conclui a aprovação. | `GLPI: Encerrar Sessão Fiscal` e `PG: Evento Fiscal Confirmado` |
| 22 | `PG: Evento Fiscal Confirmado` | Registra a transição para Fechado em `workflow_eventos`. | Fim do ramo de auditoria |
| 23 | `GLPI: Encerrar Sessão Fiscal` | Fecha a sessão do ramo confirmado. | `LOG: Fim Fiscal` |
| 24 | `LOG: Fim Fiscal` | Registra o fim da confirmação. | Fim |
| 25 | `Resp: Rejeitado` | Responde HTTP 202 imediatamente; a limpeza continua em segundo plano no mesmo workflow. | `PG: Limpar Duplicidade` |
| 26 | `PG: Limpar Duplicidade` | Volta o ticket a Pendente, grava `REJEITOU_DUP`, limpa token, referência, classe e motivo, e prepara `AGUARDANDO_FILA_CLASSIFICACAO/CLASSIFICACAO`. | `GLPI: Remover Followups Dup` e `PG: Evento Fiscal Rejeitado` |
| 27 | `PG: Evento Fiscal Rejeitado` | Registra a rejeição e a transição para Pendente em `workflow_eventos`. | Fim do ramo de auditoria |
| 28 | `GLPI: Remover Followups Dup` | Lista os followups do ticket e remove aqueles que contêm o marcador único emitido pelo WF02; devolve removidos e falhas. | `GLPI: Restaurar Título` |
| 29 | `GLPI: Restaurar Título` | Remove o prefixo `[Duplicado]` e mantém o estado Pendente. | `GLPI: Followup Rejeitado` |
| 30 | `GLPI: Followup Rejeitado` | Informa a rejeição, a higienização e o futuro envio à classificação normal. | `GLPI: Encerrar Sessão Fiscal Rejeição` |
| 31 | `GLPI: Encerrar Sessão Fiscal Rejeição` | Fecha a sessão usada no ramo rejeitado. | `PG: Enfileirar Classificação` |
| 32 | `PG: Enfileirar Classificação` | Muda `AGUARDANDO_FILA_CLASSIFICACAO` para `PENDENTE_FILA_IA`, etapa `CLASSIFICACAO`, e reinicia marcadores de reserva. | `LOG: Fim Fiscal Rejeição` |
| 33 | `LOG: Fim Fiscal Rejeição` | Registra o término da rejeição. | Fim |
| 34 | `Resp: Decisão Já Registrada` | Responde HTTP 200 com mensagem idempotente, sem repetir efeitos. | `GLPI: Encerrar Sessão Fiscal Já Registrada` |
| 35 | `GLPI: Encerrar Sessão Fiscal Já Registrada` | Fecha a sessão do clique repetido. | `LOG: Fim Fiscal Já Registrada` |
| 36 | `LOG: Fim Fiscal Já Registrada` | Registra a conclusão idempotente. | Fim |
| 37 | `Resp: Inválido` | Responde HTTP 409 com o motivo validado. | `GLPI: Encerrar Sessão Fiscal Inválido` |
| 38 | `GLPI: Encerrar Sessão Fiscal Inválido` | Fecha a sessão do ramo inválido. | `LOG: Fim Fiscal Inválido` |
| 39 | `LOG: Fim Fiscal Inválido` | Registra o encerramento sem alteração operacional válida. | Fim |
| 40 | `Webhook Fiscal Confirmação` | Endpoint `GET fiscal-confirmacao-v9`; recebe os parâmetros assinados sem alterar estado. | `Renderizar Confirmação Fiscal` |
| 41 | `Renderizar Confirmação Fiscal` | Valida apenas formato, escapa o conteúdo e gera HTML com formulário `POST`; não consulta nem modifica chamado. | `Resp: Confirmação Fiscal` |
| 42 | `Resp: Confirmação Fiscal` | Entrega a página com `Cache-Control: no-store` e proteções de conteúdo. A mutação só ocorre quando o fiscal pressiona o botão. | Fim |

## WF05 — Métricas e avaliação humana de apoio

Objetivo: consolidar indicadores operacionais e registrar respostas humanas previamente solicitadas. Este workflow é **apoio analítico**. Seus nós de avaliação humana permanecem disponíveis mesmo quando uma rodada automatizada dispensa dupla revisão. O oráculo determinístico externo de teste pode chamar o mesmo endpoint de avaliação somente sob as guardas sintéticas e registra essa ação em `avaliacao_auto_confirmacoes`, sem preencher identidade humana. A ação testa a transição e não constitui avaliação humana ou validação externa. As métricas científicas finais, matrizes de confusão, intervalos de confiança e comparação de modelos continuam dependentes do protocolo de avaliação, do gabarito validado e dos scripts da pasta `avaliacao`.

| # | Nó | Entrada, saída e efeito | Próximo passo |
|---:|---|---|---|
| 1 | `T1. Manual` | Disparo manual da consolidação. | `LOG: Início` |
| 2 | `T2. Schedule 23h` | Cron `0 23 * * *`; consolida diariamente às 23h. | `LOG: Início` |
| 3 | `LOG: Início` | Registra horário e fase inicial. | `PG: Garantir Schema Observabilidade` |
| 4 | `PG: Garantir Schema Observabilidade` | Executa o SQL idempotente V9 necessário às tabelas, índices e views operacionais/analíticas, inclusive `avaliacao_auto_confirmacoes`. As views finais de classificação mantêm quatro classes cobertas, excluem `ABSTENCAO` da matriz/F1/acurácia seletiva e publicam total, cobertos, abstenções, cobertura e risco-cobertura; as views de deduplicação aplicam a mesma separação e calculam recall@20 da recuperação. | `PG: Consolidar Métricas` |
| 5 | `PG: Consolidar Métricas` | Calcula totais, automação efetiva, intervenção humana, erros IA, triagem manual, aprovações pendentes, tempo médio e chamados travados; faz UPSERT em `metricas_diarias_automacao`, `metricas_prompt_version` e `metricas_workflow_performance`; registra evento WF05 e compara limites ambientais. | `Alerta necessário?` |
| 6 | `Alerta necessário?` | Avalia `gerar_alerta` com limites de erro IA, triagem manual e tickets travados. | Sim: `Email: Alerta Métricas`; não: `LOG: Fim` |
| 7 | `Email: Alerta Métricas` | Envia resumo e limites ultrapassados ao endereço de métricas/infraestrutura. | `LOG: Fim` |
| 8 | `LOG: Fim` | Registra resultado e emite resumo visual. | Fim |
| 9 | `Webhook Avaliação Humana` | Endpoint de mutação `POST avaliacao-humana-v9`; recebe token, resultado, classe correta, avaliador e motivo após confirmação explícita. | `Extrair Avaliação Humana` |
| 10 | `Extrair Avaliação Humana` | Valida token hexadecimal e resultado `correta`/`incorreta`; normaliza os demais campos. | `PG: Registrar Avaliação Humana` |
| 11 | `PG: Registrar Avaliação Humana` | Atualiza uma avaliação pendente e não expirada em `avaliacoes_humanas`, registra acerto/correção, avaliador e motivo, e cria evento. Trata token inexistente, expirado e resposta já registrada com códigos próprios. | `Resp: Avaliação Humana` |
| 12 | `Resp: Avaliação Humana` | Responde texto com o `http_status` calculado pelo PostgreSQL. | Fim |
| 13 | `Webhook Confirmação Avaliação` | Endpoint `GET avaliacao-humana-confirmacao-v9`; recebe token e proposta de avaliação sem alterar estado. | `Renderizar Confirmação Avaliação` |
| 14 | `Renderizar Confirmação Avaliação` | Valida formato, escapa os campos e monta formulário `POST` para o endpoint de avaliação. | `Resp: Confirmação Avaliação` |
| 15 | `Resp: Confirmação Avaliação` | Entrega HTML sem cache. A avaliação só é registrada após o botão de confirmação. | Fim |

## WF06 — Fila e controle de vazão da IA

Objetivo: desacoplar o ritmo de chegada do GLPI do ritmo de consumo dos provedores de IA, reservar tickets sem concorrência e encaminhar cada etapa ao subworkflow correto.

| # | Nó | Entrada, saída e efeito | Próximo passo |
|---:|---|---|---|
| 1 | `Webhook GLPI Fila` | Endpoint POST `glpi-ticket-fila-ia-v9`; recebe evento do GLPI. | `Preparar Entrada GLPI` |
| 2 | `Preparar Entrada GLPI` | Lê corpo/query/headers, valida `GLPI_WEBHOOK_KEY`, exige ID positivo e normaliza os principais campos do chamado. Emite `authorized`, código e objeto `chamado`. | `Entrada Autorizada?` |
| 3 | `Entrada Autorizada?` | Separa ingressos autenticados dos rejeitados. | Sim: `PG: Enfileirar Ticket`; não: `Resp: Rejeitado` |
| 4 | `PG: Enfileirar Ticket` | Faz UPSERT do evento em `tickets_processados`. Para chamado elegível, define `PENDENTE_FILA_IA`, etapa `DEDUPLICACAO`, disponibilidade imediata e limpa reservas/erros anteriores, sem reabrir estados terminais protegidos. | `Resp: Enfileirado 202` |
| 5 | `Resp: Enfileirado 202` | Confirma recebimento com HTTP 202. | `LOG: Ingresso Enfileirado` |
| 6 | `LOG: Ingresso Enfileirado` | Registra ID, elegibilidade e estado da fila. | Fim do ramo de ingresso |
| 7 | `Resp: Rejeitado` | Responde com o código calculado pelo nó de preparação: HTTP 401 para chave inválida ou 422 para `ticket_id` inválido. | Fim do ramo de ingresso |
| 8 | `Agendador Fila IA` | Cron `*/1 * * * *`; inicia um ciclo por minuto. | `LOG: Início Fila` |
| 9 | `Manual` | Permite iniciar o ciclo manualmente. | `LOG: Início Fila` |
| 10 | `LOG: Início Fila` | Registra o início do ciclo. | `PG: Reservar Fila IA` |
| 11 | `PG: Reservar Fila IA` | Em uma única consulta com `pg_advisory_xact_lock`, recupera leases expirados, aplica capacidade e `FOR UPDATE SKIP LOCKED`, seleciona por antiguidade, reserva até `FILA_IA_LOTE_TAMANHO`, calcula liberação espaçada, atualiza controle/métricas e anexa ao item o `run_id`, split, configuração experimental, papel e modelo esperados. Aceita Novo em `DEDUPLICACAO` e Pendente em `CLASSIFICACAO`; itens de dataset só saem quando o experimento está `EXECUTANDO` ou `CALIBRANDO`. | `Preparar Lote` |
| 12 | `Preparar Lote` | Encontra a linha que contém `tickets`, converte JSON, anexa posição, atraso, origem, evento, chave interna e objeto do chamado. Sem itens, emite `total_lote=0`; com itens, emite um item por ticket. | `Tem Chamados?` |
| 13 | `Tem Chamados?` | Testa `total_lote > 0`. | Sim: `Aguardar Janela`; não: fim do ciclo |
| 14 | `Aguardar Janela` | Aguarda o `delay_seconds` calculado para cada item, preservando o espaçamento do lote. | `É Classificação?` |
| 15 | `É Classificação?` | Compara `fila_etapa` com `CLASSIFICACAO`. | Sim: `Chamar WF03 da Fila`; não: `Chamar WF02 da Fila` |
| 16 | `Chamar WF02 da Fila` | Para deduplicação, chama WF02 com origem/evento, ID, chamado e chave interna; aguarda o subworkflow. | `LOG: Fim Fila` |
| 17 | `Chamar WF03 da Fila` | Para classificação, chama WF03 com origem/evento, ID e chamado; aguarda o subworkflow. | `LOG: Fim Fila` |
| 18 | `LOG: Fim Fila` | Registra a liberação concluída e emite `WF06_LIBERADO`. | Fim |

## Evidência de interface em navegador — 15/07/2026

A suíte foi executada em modo **`READ_ONLY_BROWSER_VALIDATION`** e aprovou **12 de 12 verificações**. O relatório registra `created_tickets=0` e `workflow_mutations=0`: ela autenticou somente para leitura, não criou chamados, não executou workflows e não alterou mensagens.

| Superfície | Verificações aprovadas | Evidência observada |
|---|---:|---|
| n8n | 5/5 | Página pública e formulário de login renderizados, `/healthz` em HTTP 200, leitura autenticada em HTTP 200 e seis workflows V9 ativos. |
| GLPI | 4/4 | Página pública e formulário de login renderizados, sessão somente leitura iniciada e página de tickets em HTTP 200. |
| Mailpit | 3/3 | Página pública em HTTP 200, título da interface identificado e `/api/v1/info` em HTTP 200. |
| **Total** | **12/12** | **Todas as verificações somente leitura foram aprovadas.** |

Os artefatos estão em `avaliacao/resultados/browser_2026-07-15/`: `resultado.json` contém o registro estruturado, `relatorio.md` contém a tabela legível e as imagens preservam as telas de login, listagem e Mailpit. Esta evidência confirma disponibilidade e leitura das interfaces naquela execução; não mede eficácia da IA, não valida decisões fiscais e não representa teste de carga.

## Pontos de controle para interpretar resultados

- Resultados do modo `VALIDACAO AUTOMATIZADA NAO CONFIRMATORIA` servem para regressão e integração. Mesmo quando comparados a um gabarito determinístico, não devem ser promovidos a benchmark confirmatório sem os gates metodológicos exigidos para essa finalidade.
- Uma resposta HTTP bem-sucedida de qualquer provedor não implica decisão válida: gateway e normalizadores ainda exigem schema, classes coerentes e probabilidades válidas.
- Uma resposta HTTP do serviço local também não basta: o gateway exige backend `granite_embedding_pytorch_fp32`, runtime `pytorch_fp32`, precisão `fp32`, dimensão 384, revisão congelada, hash do modelo e ausência de fallback de desenvolvimento.
- A configuração final entrega até 20 candidatos na mesma ordem a todos os papéis. Em benchmark, lista, IDs, hash e política pareada são obrigatórios e qualquer divergência falha fechado. O recall da referência no top-20 continua sendo reportado separadamente da decisão sobre os pares.
- `decision_ready` significa que o serviço dispõe de um bundle operacional aprovado para gerar decisões. `candidate_frozen/evaluation_eligible` congela o bundle; `candidate_evaluation_eligible=true` identifica uma resposta produzida pelo caminho híbrido e `pipeline_evaluation_eligible=true` identifica uma linha válida do pipeline congelado, inclusive uma contenção determinística anterior ao modelo. `scientific_eligible` permanece falso até a conclusão confirmatória. Nenhum desses estados equivale, sozinho, a `scientifically_validated` ou a resultado científico final.
- `confianca` operacional é derivada da probabilidade da classe escolhida; a confiança originalmente declarada pelo modelo é mantida separadamente para auditoria.
- `DEMO_SEM_EQUIPE` é rota operacional. Para métricas semânticas, a classe continua sendo `DEMO`.
- Aprovação fiscal é barreira obrigatória para uma decisão positiva de duplicidade. A automação não fecha diretamente um possível duplicado apenas com a saída do LLM.
- Baixa confiança de deduplicação ou classificação aumenta cobertura manual; por isso acurácia, cobertura, risco e tempo humano devem ser relatados em conjunto.
- `vw_decisoes_confirmatorias_elegiveis` contém somente decisões de teste com um modelo, sem fallback e coerentes com `experimentos_avaliacao.modelo_ia`; `vw_proveniencia_gateway_ia` resume tentativas, tokens e latência.
- `vw_erros_ia_sem_dead_letter` é uma superfície de reconciliação operacional para lacunas históricas de auditoria; suas linhas não devem ser tratadas automaticamente como novas dead letters nem como observações completas de desempenho do modelo.
- WF05 descreve saúde operacional. Ele não produz, isoladamente, evidência científica de eficácia do modelo e não substitui o gabarito adjudicado.

## Verificação de cobertura do documento

Foram conferidos os nomes dos nós diretamente nos seis JSONs, incluindo nova leitura de WF02, WF03, WF04 e WF05 depois da integração local-first. O inventário contém **172 nós**, dos quais **48 são `Code`**, e este documento inclui os **172 nomes**, distribuídos em 16 + 43 + 38 + 42 + 15 + 18. O WF02 não voltou a chamar o WF03 diretamente: `Preparar WF03` e `Chamar WF03` continuam removidos, e a classificação retorna à fila/WF06. WF02 e WF03 agora possuem, cada um, uma barreira persistence-first: `Decisão IA Persistida?`/`Preparar Erro Persistência IA` e `Decisão IA Classificação Persistida?`/`Preparar Erro Persistência IA Classif`. Nenhum efeito operacional prossegue sem `ia_decisao_id` válido. A verificação deve ser repetida sempre que os builders regenerarem qualquer JSON V9, pois nomes, conexões e efeitos podem mudar.
