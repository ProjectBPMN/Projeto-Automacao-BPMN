# Estado auditado do projeto — 17/08/2026

> [!WARNING]
> **Snapshot histórico, superado pela auditoria de 26/08/2026.** A seleção
> citada neste documento não sustenta ranking atual: derivados de poucas
> famílias-fonte não ficaram integralmente no mesmo grupo. Toda classificação
> permanece sintética e a deduplicação antiga é subdimensionada. Use
> `auditoria_critica_completa_2026-08-26.md` e
> `resposta_professor_2026-08-26.md` como estado canônico.

## Conclusão executiva

O projeto está tecnicamente avançado e possui boa rastreabilidade, mas ainda não
está 100% validado para uma afirmação científica final. A V9 apresenta alta
integridade estática e contratos automatizados; a seleção comparativa do modelo
local terminou corretamente; e a v1.8 continua sendo a configuração operacional
mais estável dentre as versões materializadas. Permanecem pendentes o holdout
institucional independente, o benchmark pareado válido com Gemini, o E2E mutante
integral da revisão corrente e a calibração isolada de vazão do WF06.

## Seleção científica de modelos

A seleção v1.3 comparou 90 configurações:

- 35 para classificação;
- 55 para deduplicação;
- Granite 97M, multilingual-e5-small e multilingual MiniLM;
- TF-IDF isolado, embedding isolado, híbrido textual, metadados isolados e
  híbrido com metadados;
- regressão logística, árvore de decisão, SVM linear, MLP e XGBoost.

O validador independente marcou a rodada como `VALID` e recalculou 50.780
predições fora da dobra, 450 dobras, ranking, intervalos, comparações pareadas,
XAI e latência. O corpus foi separado por núcleo narrativo ou episódio para que
variações naturalísticas do mesmo caso não vazassem entre treino e teste.

Resultados provisórios:

| Tarefa | Candidato | Resultado de desenvolvimento | Limite científico |
|---|---|---|---|
| Classificação | Granite + TF-IDF + SVM linear | macro-F1 0,8006; recall OBRA 0,9323; cobertura 58,07%; 0 não-OBRA→OBRA | UCB95 do evento crítico 5,93%; `UNDERPOWERED` |
| Deduplicação | Granite + TF-IDF + regressão logística | 0 FP/FN automáticos em 600 pares; NPV 1,0; automação integral 50% | UCB95 de FN por grupo 4,87%; `UNDERPOWERED` |

Com zero eventos críticos, o protocolo exige pelo menos 149 grupos independentes
para sustentar um limite unilateral de 95% menor ou igual a 2%. O corpus atual
não atinge esse tamanho nos estratos relevantes. A conclusão válida é “melhor
candidato de desenvolvimento”, não “modelo cientificamente validado”.

O SHAP foi concluído para os dois finalistas, agregado por famílias de
atributos. Ele explica o escore do classificador-base e não implica causalidade.

## Comparação das versões locais

| Versão | Evidência | Disponibilidade | Cobertura semântica | Automação direta | Acurácia seletiva | Latência média |
|---|---|---:|---:|---:|---:|---:|
| v1.1 | regressão histórica | 195/1.240 | 7,02% | 5,89% | 100% sobre 87 cobertos | 1.245,67 ms |
| v1.8 | regressão vigente | 1.240/1.240 | 54,11% | 40,73% | 99,70% | 414,33 ms |
| v1.9 | regressão com limitação | 1.239/1.240 | 60,73% | 47,26% | 100% | 663,96 ms |

A v1.9 melhorou cobertura e automação em relação à v1.8, mas teve uma falha
HTTP 503 por memória e acrescentou 249,84 ms de latência média pareada. Ela
falhou nos critérios explícitos de disponibilidade e latência e recebeu
`CANDIDATE_NOT_RECOMMENDED`. A v1.9.1 reduziu o custo do classificador depois do
embedding, mas seu piloto de 30 unidades também foi mais lento de ponta a ponta.
Nenhuma das duas foi promovida.

As tentativas v1.9 com token inválido, concorrência involuntária ou execução
interrompida possuem marcador `INVALIDADO.md`. A rodada 1.239/1.240 possui
`LIMITACAO.md`. Elas permanecem como trilha de auditoria e não são misturadas
com resultados válidos.

O endpoint local foi restaurado para `local-hybrid-bundle-v1.8.0`, Granite
PyTorch FP32 de 384 dimensões e micro-lote máximo de quatro textos. O health
declara `scientific_ready=false`, de forma coerente com as pendências.

## Workflows n8n

As evidências atuais permitem afirmar alta integridade estática, não correção
universal:

- seis workflows V9 ativos e alinhados semanticamente com os JSONs canônicos na
  auditoria de deploy;
- 913 verificações estáticas aprovadas;
- nove testes de contrato do WF04/WF06 aprovados;
- preflight real sem mutação aprovado;
- E2E sintético `VALIDACAO-POSTS-E2E-20260818T004922Z` aprovado para confirmação
  positiva WF04/WF05: GET sem mutação, token expirado e inválido rejeitados,
  dois POSTs concorrentes com exatamente um HTTP 202 e uma transição, replay
  idempotente e dois tickets sintéticos encerrados sem alerta de limpeza;
- E2E sintético `VALIDACAO-POSTS-E2E-20260818T004902Z` aprovado para
  `nao_duplicado`: as mesmas barreiras de token/concorrência, `REJEITOU_DUP`,
  campos de duplicidade limpos, evento único, handoff
  `PENDENTE_FILA_IA/CLASSIFICACAO`, trava WF06 liberada e dois tickets
  sintéticos encerrados sem resíduo;
- histórico V1–V8 preservado em cópias sanitizadas e inativas, com manifesto,
  hashes e validador próprio.

Ainda faltam, na revisão exata destinada à publicação:

- drenagem completa WF06 → WF02 → WF03;
- calibração de vazão isolada, repetida, com chegada determinística, Poisson e
  rajadas, medindo fila p50/p95/p99, 429, retries e dead letter.

A auditoria viva também encontrou dívida histórica que deve ser separada dos
ensaios atuais: 83 linhas em `fila_ia_dead_letter` (nenhuma criada nos últimos
sete dias) e 46 erros legados expostos por `vw_erros_ia_sem_dead_letter`. Esses
registros não provam falha da revisão corrente, mas precisam de reconciliação e
política de arquivamento antes de uma implantação institucional limpa.

O log do n8n registrou uma tentativa horária com `SQLITE_CONSTRAINT: FOREIGN KEY
constraint failed`. `PRAGMA foreign_key_check` retornou zero violações
persistidas, portanto a evidência aponta para uma operação de manutenção que
falha e reverte, não para corrupção já materializada. A causa do job horário
ainda precisa ser identificada e corrigida.

O calibrador v2.6 agora exige o manifesto explícito do modelo, identifica o
`run_id` e não pode reutilizar silenciosamente uma versão antiga. Antes do
ensaio, ele captura os parâmetros não sensíveis do WF06 e o controlador da
fila; ao terminar, restaura exatamente esse estado e falha fechado se não puder
comprovar a restauração. Nenhum valor final de lote ou intervalo deve ser
publicado antes da rodada isolada.

## Modelos remotos

O caminho operacional permanece `LOCAL → SECONDARY`, com
`gemini-3.5-flash` como contingência explícita. Benchmarks desativam fallback e
fixam um modelo por execução. O executor remoto controla RPM, TPM e RPD, reserva
20% de margem e aborta no primeiro 429, erro HTTP ou violação de contrato.

A execução pareada remota válida da revisão congelada corrente ainda não foi
iniciada, porque a cota efetiva precisa ser confirmada no AI Studio para o
projeto autenticado. Tentativas históricas abortadas por cota/rede não formam
uma comparação válida. O DeepSeek V4 Flash está
bloqueado: não há gratuidade garantida e ainda não existe executor pareado
próprio. Nenhuma conclusão local ≥ Gemini/DeepSeek foi registrada.

## Estado de publicação

A suíte de avaliação passou em 222 testes e 43 subtestes. A barreira pública
analisou 162 arquivos da lista permitida e encontrou zero problemas. O histórico
V1–V8 é publicável somente em sua forma sanitizada; exports brutos, `.env`,
credenciais, bancos, ZIPs, corpora internos, resultados brutos e bundles
derivados continuam fora da distribuição.

No computador atual, o `.env` privado ainda não contém as cinco variáveis
`PG*` necessárias aos scripts executados no host. Os E2E usaram a credencial
PostgreSQL viva do n8n apenas em memória e removeram o arquivo temporário ao
final. Antes de alegar reprodução a partir de uma instalação limpa, o operador
deve sincronizar ou rotacionar essa configuração sem registrar o segredo no Git.
O valor privado atual de `N8N_API_KEY` também não autenticou a API REST local e
deve ser rotacionado ou reconciliado com a credencial realmente usada no deploy.

O repositório pode ser preparado como release técnico ou repositório de método,
desde que declare as limitações acima. Para publicar resultados científicos de
eficácia e superioridade, ainda são necessários holdout independente, rótulos
institucionais/adjudicados, comparação remota pareada e execução integrada final.

## Próximos gates, em ordem

1. confirmar no AI Studio a cota ativa e a condição de faturamento do projeto;
2. executar o pareado LOCAL/Gemini numa janela exclusiva, sem fallback;
3. congelar e abrir um holdout institucional nunca usado no desenvolvimento;
4. executar a drenagem WF06→WF02/WF03 até estados terminais na revisão atual;
5. executar a calibração isolada do WF06 com repetições suficientes;
6. somente então consolidar a planilha e os gráficos confirmatórios.
