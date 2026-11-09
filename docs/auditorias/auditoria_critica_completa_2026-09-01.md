# Auditoria crítica completa — 1 de setembro de 2026

## Parecer executivo

O projeto está tecnicamente consistente como protótipo local auditável, mas
**não está cientificamente validado nem pronto para operação autônoma em
produção**. Os seis workflows V9 são reproduzíveis, o serviço local responde,
o caminho de integração tem evidência sintética e a suíte automatizada é
extensa. Isso demonstra engenharia nos cenários exercitados; não demonstra
acurácia institucional, segurança universal ou correção de 100% das entradas.

O resultado científico corrente é deliberadamente conservador:

- a seleção V2 foi invalidada por dependência entre derivados e corpus não
  reproduzível;
- a V2.1 classificatória é desenvolvimento sintético, agrupado e auditável,
  mas nenhum candidato passou os gates de confiança;
- a deduplicação supervisionada não foi estimada: seis grupos por classe são
  insuficientes para o desenho pré-definido;
- em 01/09/2026 foi decidido não produzir revisão humana nem em pares. Sem
  gabarito independente, não é metodologicamente lícito abrir um holdout e
  chamar o resultado de avaliação confirmatória.

O `local-hybrid-v1.8.0` continua sendo candidato de engenharia operacional. A
rodada V2.1 não justificou promovê-lo nem substituí-lo pelo candidato E5.

## Escopo e limites da revisão

O repositório foi enumerado mecanicamente por caminho, tamanho e SHA-256. A
revisão semântica foi priorizada por risco: builders e JSONs V9, serviço de IA,
schemas, protocolos, datasets, predições individuais, resultados, testes,
Docker, histórico e documentação. Arquivos binários/gerados foram verificados
por identidade, estrutura, proveniência e relação com o gerador. Não se alega
leitura manual linha a linha de cada modelo, CSV ou JSONL.

O inventário corrente contém 900 arquivos publicáveis, 820 já rastreados e 80
novos/não rastreados, somando aproximadamente 212,27 MB. O CSV associado traz
uma linha e um SHA-256 por arquivo; a condição de “não rastreado” não significa
erro, mas exige revisão antes do commit.

Esta auditoria distingue quatro níveis:

| Nível | O que pode sustentar |
|---|---|
| teste técnico | contratos, regressões e cenários simulados |
| evidência de desenvolvimento | comparação e ajuste em dados sintéticos/treino |
| piloto | comportamento prospectivo no processo, sem eficácia confirmatória |
| confirmação | estimativa pré-registrada em holdout real com gabarito independente |

Somente os dois primeiros níveis possuem evidência atual suficiente. O piloto
humano e a confirmação estão fora do escopo por decisão explícita.

## Validações repetidas nesta auditoria

| Verificação | Resultado e interpretação |
|---|---|
| suíte Python principal | 339 testes aprovados, 3 ignorados e 117 subtestes aprovados; regressão técnica |
| validação estática V9 | aprovada após regeneração dos builders |
| histórico V1–V8 | 10 JSONs, cobertura V1–V8, hashes, determinismo, inatividade e saneamento aprovados |
| implantação n8n | seis workflows reconstruídos, publicados, ativados e relidos; hashes da superfície lógica implantada coincidiram com os artefatos canônicos |
| execuções recentes n8n | as 20 mais recentes, IDs 58918–58937, eram WF06 `success`; não houve decisão de IA nas últimas 24 h, portanto comprovam o agendador vazio, não o E2E |
| healthcheck n8n | adicionado ao Compose; contêiner observado como `running healthy`, `/healthz` 200 |
| GLPI HTTP | três leituras 200 em 638, 290 e 250 ms; o timeout pontual anterior não se repetiu |
| IA local | serviço iniciado, saúde técnica OK; `scientific_ready=false` permanece correto |
| carga limitada | saúde: 100/100 respostas 200; classificação híbrida real: concorrência 1 teve 40/40 respostas 200, enquanto concorrência 4 teve 18/40 respostas 200 e 22 respostas 429; não mede E2E |
| restauração isolada | schema PostgreSQL restaurado; dump GLPI restaurou 87 tickets, 15 usuários e 7 categorias em alvos efêmeros |
| falhas isoladas | GLPI 503, timeout da IA e PostgreSQL recusado tratados pelo harness; não é caos no ambiente completo |
| inventário Git | limpeza histórica preservada; intermediários recuperáveis agora ignorados |
| `git diff --check` | aprovado |

Os testes automatizados não autorizam “100% correto”. Três testes ignorados e
os cenários não modelados precisam continuar explícitos no relatório.

## Verificação manual no navegador

Foram abertas as interfaces locais em `127.0.0.1:5678` e `127.0.0.1:9080`.
Ambas apresentaram telas de autenticação e não havia sessão autenticada. Para
não capturar nem reutilizar senhas sem confirmação, nenhuma credencial foi
digitada automaticamente. Assim:

- a publicação/ativação atual do n8n foi verificada pela implantação REST e
  pelos artefatos, mas a inspeção visual autenticada atual ficou pendente;
- a disponibilidade da tela do GLPI foi verificada, mas chamados, histórico e
  acompanhamentos atuais não foram reinspecionados visualmente;
- as observações autenticadas de 26–27/08 continuam sendo evidência histórica,
  sem screenshot imutável, e não devem ser apresentadas como nova conferência.

Para concluir essa parte, o responsável deve entrar diretamente nas duas abas;
depois a auditoria pode ler, sem mutar, os seis workflows, suas execuções e os
chamados escolhidos no GLPI.

## Pontos fortes

### Engenharia

- builders determinísticos, IDs estáveis, snapshots e paridade de implantação;
- filas com lock transacional, lease, backoff, DLQ e telemetria;
- persistência de entrada, hash, tentativa, provedor, versão e saída;
- abstinência e fail-closed nos contratos críticos;
- imagens Docker congeladas por digest e portas locais em loopback;
- serviço local com embedding congelado por revisão e sem fallback silencioso;
- E2E sintético isolado com `run_id`, cleanup e restauração de perfil;
- histórico V1–V8 sanitizado em vez de backups runtime com segredos;
- backup/restore em destinos efêmeros e testes de falha sem tocar dados vivos.

### Método científico

- comparação inclui Granite 97M, multilingual-e5-small e MiniLM multilíngue;
- ablações TF-IDF, embedding, híbrido e, para deduplicação, metadados;
- regressão logística, árvore, SVM, MLP e XGBoost sob o mesmo protocolo;
- validação aninhada e agrupada por dependência-fonte;
- calibração fora de dobra, bootstrap agrupado e comparação pareada;
- cobertura e risco seletivo separados da acurácia global;
- SHAP com verificação de aditividade e limites interpretativos explícitos;
- invalidação formal de uma rodada metodologicamente defeituosa.

## Pontos fracos e riscos

### Científicos

1. O corpus é sintético e seus rótulos vêm do gerador; validade interna do
   código não equivale a validade no campus.
2. Há 111 grupos independentes elegíveis na classificação e apenas 12 na
   deduplicação. Contar paráfrases como amostra inflaria precisão e confiança.
3. O mesmo conjunto de desenvolvimento sustentou iterações de política. Ele
   não pode virar holdout por mudança de nome.
4. Nenhum candidato cumpriu simultaneamente os gates de desempenho,
   calibração, risco crítico e cobertura.
5. Muitas configurações aumentam risco de seleção oportunista; comparações
   pareadas e intervalos reduzem, mas não eliminam, esse risco.
6. Sem gabarito humano independente, métricas futuras medirão concordância
   com rótulo sintético, regra ou outro modelo — não acerto institucional.
7. SHAP descreve atribuição do classificador; não prova causalidade nem acerto.

### Operacionais e de segurança

1. A conta PostgreSQL atual ainda acumula bootstrap e runtime e possui
   `SUPERUSER`, `CREATEROLE`, `CREATEDB`, `REPLICATION` e `BYPASSRLS`.
2. O n8n permanece com sandbox desabilitada e acesso amplo do Code node às
   variáveis de ambiente. A arquitetura atual depende disso; endurecer exige
   refatorar credenciais/configuração, não apenas trocar flags.
3. O WF05 não executa mais DDL, mas a migração de roles ainda precisa de uma
   credencial administrativa distinta e uma janela com rollback.
4. A inferência real satura na configuração atual: com concorrência 4, 55%
   das 40 requisições receberam 429. Faltam concorrência WF06 e saturação
   combinada de n8n/IA/bancos; aumentar paralelismo sem medir RAM pode piorar.
5. Restore de schema/dump foi isolado; faltam volume n8n, credenciais e ensaio
   cronometrado de RTO/RPO.
6. SLO e drift estão implementados como ferramentas/propostas, sem três
   janelas completas, baseline aprovado, alertas instalados e runbook exercido.
7. Não há ambiente de homologação claramente separado do ambiente local vivo.
8. O banco contém 84 entradas DLQ ainda não resolvidas, todas históricas entre
   10/07 e 18/08 (70 deduplicação, 14 classificação), e 129 tickets em
   `ERRO_IA`. Não houve nova DLQ nem decisão de IA nas últimas 24 h e a fila
   pronta estava vazia, mas a ausência de política de encerramento/explicação
   mantém o SLO de DLQ reprovado.

## Crítica aos resultados e estatísticas

### Classificação V2.1

Foram analisados 1.114 registros, 111 grupos-fonte, 35 configurações, 175
dobras e 38.990 predições fora de dobra. O validador independente registrou
`VALID_PARTIAL_TASK_SCOPE`, `development_only=true` e
`confirmatory_eligible=false`.

O candidato provisório E5 + híbrido + SVM linear obteve:

- Macro-F1 0,7987; IC95% agrupado 0,7266–0,8598;
- acurácia 0,8312; IC95% 0,7653–0,8889;
- cobertura automática 60,86%; IC95% 52,29–68,95;
- risco seletivo 6,93%; IC95% 2,29–13,21.

A classe `TRIAGEM_MANUAL` foi fraca: precisão 0,6797, recall 0,4915 e F1
0,5705 em 177 exemplos. Isso é relevante porque uma política de abstinência
não pode ser julgada apenas pelas classes fáceis.

Em 64 grupos expostos, zero erros críticos não-OBRA→OBRA produziram limite
superior unilateral de 95% de 4,57%, acima do gate de 2%. Zero observado não é
risco zero. Pela regra exata binomial, são necessárias pelo menos 149
exposições independentes sem evento para que o limite fique estritamente abaixo
de 2%. Se duas direções críticas exigirem amostras disjuntas, o planejamento
inicial pode chegar a 298 grupos, antes de perdas e efeito de desenho; se um
mesmo grupo for elegível para ambos os estimandos, o cálculo não deve somar
automaticamente os denominadores.

### Comparações e ablações

- E5 híbrido/logístico versus Granite: diferença de Macro-F1 +0,0157, IC95%
  -0,0077 a +0,0408; não demonstra superioridade.
- MiniLM versus Granite: -0,0061, IC95% -0,0416 a +0,0248.
- Granite embedding isolado versus híbrido: -0,0668, IC95% -0,1331 a -0,0062;
  há sinal de que embedding isolado foi pior nessa configuração.
- TF-IDF isolado versus híbrido: -0,0015, IC95% -0,0329 a +0,0255; não há
  evidência clara de vantagem do híbrido sobre o baseline lexical.

Logo, a justificativa para embedding é uma hipótese plausível sobre paráfrases,
não uma superioridade demonstrada neste domínio. O resultado atual favorece
manter TF-IDF como baseline obrigatório e não promover Granite ou E5 por
narrativa.

### Deduplicação e recuperação

A seleção supervisionada de 55 configurações falhou cedo porque seis grupos
por classe não comportam ajuste, calibração e validação agrupados. O limite
superior de 95% associado a zero evento com somente seis grupos é cerca de
39,3%; não existe base para alegar segurança.

O ensaio de recuperação usa 500 consultas sintéticas derivadas de apenas seis
famílias positivas. TF-IDF teve recall@1 0,324, recall@5 0,658, recall@20 0,788
e MRR 0,4698; Granite 0,190/0,496/0,878 e MRR 0,3396; E5
0,218/0,522/0,756 e MRR 0,3574; MiniLM 0,090/0,254/0,496 e MRR 0,1730.
Esses números são descritivos e dependentes das seis famílias; não podem ser
tratados como 500 unidades independentes.

### XAI e desempenho

O residual de aditividade SHAP foi 5,77e-15. A importância agregada foi 52,99%
TF-IDF de caracteres, 29,64% TF-IDF de palavras e 17,37% embedding. Isso sugere
forte dependência lexical neste corpus, mas não é decomposição causal.

O benchmark finalista de 20 registros teve p50 81,82 ms e p95 105,41 ms com
encoder aquecido; exclui GLPI, n8n, fila, banco e cold start. Na carga de
classificação híbrida Granite, concorrência 1 teve 40/40 sucessos, p50 11,66
ms, p95 33,30 ms e 37,48 req/s, com máximo de 492,40 ms. Em concorrência 4,
apenas 18/40 tiveram 200, 22/40 receberam 429, p95 1,57 s e vazão 21,19 req/s.
Logo, a configuração corrente deve manter pacing/concurrency conservadores; os
números não incluem o E2E e não justificam elevar paralelismo em produção.

## Correções implementadas nesta rodada

1. healthcheck explícito do n8n, aplicado e observado como saudável;
2. DDL removido do JSON runtime do WF05; `database/init_v9.sql` passa a ser a
   fonte de migração, e o workflow apenas verifica relações antes de consolidar;
3. WF05 regenerado, snapshot atualizado, validado, publicado e reativado;
4. implantação passou a reler cada workflow e falhar se nome, nós, conexões,
   configurações ou estado ativo divergirem da lógica canônica;
5. auditoria operacional atual preservada em
   `avaliacao/resultados/operacional/auditoria-operacional-20260901.json`;
6. carga real de classificação preservada em cenários de concorrência 1 e 4,
   documentando a saturação/429 em vez de ocultá-la;
7. logs e `partials/` recuperáveis da seleção passaram a ser ignorados, sem
   apagar evidência final, bundles ou runtime necessário;
8. gerador de inventário deixou de fixar a data de 26/08 e inclui os novos
   módulos de pré-registro, confirmação, operação e piloto;
9. documentação atualizada para registrar a decisão de não usar revisão
   humana e bloquear alegações confirmatórias incompatíveis.

## Organização e retenção

Estrutura recomendada e mantida:

- `avaliacao/`: protocolos, datasets, ferramentas, testes e resultados;
- `database/`: migração administrada e schema;
- `docs/`: fontes canônicas e snapshots históricos rotulados;
- `glpi/`: infraestrutura, plugin e seed;
- `local_ai/`: API, treinamento, artefatos, modelos e testes;
- `n8n/history/`: V1–V8 sanitizado/inativo;
- `n8n/workflows/Versão9/`: única release operacional;
- `scripts/`: verificações transversais.

Já haviam sido retirados do índice 15.874 arquivos, cerca de 500,27 MiB, entre
backups, dumps, segredos, binários e caches. A exclusão foi do versionamento,
não uma destruição ampla do disco. Nesta rodada, os 90 `partials/` e dois logs
de execução foram preservados localmente e excluídos do conjunto publicável por
`.gitignore`. Não se apagou `local_ai/runtime`, porque o serviço em execução o
utiliza. Também foram preservadas as exclusões preexistentes dos BPMN, que não
foram assumidas como descartáveis pela auditoria.

## O que falta para finalizar

### Limite científico imposto pela decisão atual

Sem revisão humana ou em pares, não é possível concluir 100% da validação
científica pedida originalmente. O projeto pode concluir apenas avaliação
técnica/de desenvolvimento por proxy. Para máxima honestidade, deve manter:

- `scientific_ready=false`;
- `confirmatory_claim_allowed=false`;
- `BLOQUEADO_SEM_GABARITO_INDEPENDENTE` no pré-registro;
- nenhum “holdout confirmatório” aberto ou renomeado a partir de dados atuais.

Ainda é útil ampliar famílias independentes e repetir comparações, mas o
resultado será validade interna contra rótulos sintéticos/regras, não eficácia
institucional.

### Pendências técnicas para produção

1. criar roles separadas de migração e runtime, aplicar menor privilégio com
   rollback e provar negação de DDL;
2. adicionar healthcheck ao contêiner GLPI e validar sua degradação, não apenas
   a resposta HTTP pontual;
3. retirar a dependência de Code nodes em acesso irrestrito ao ambiente e
   reabilitar a sandbox;
4. ajustar capacidade somente após perfil de RAM/CPU; repetir concorrência
   completa WF06→WF02/WF03, com cold start, fila, GLPI e bancos;
5. ensaiar falhas reais controladas e recuperação do volume n8n/credenciais;
6. instalar coleta, dashboards e alertas; acumular três janelas de SLO e uma
   referência de drift aprovada;
7. classificar e encerrar, sem apagar a trilha, as 84 DLQs históricas e explicar
   os 129 estados `ERRO_IA` antes de medir backlog/SLO corrente;
8. separar homologação, documentar RTO/RPO, rotação de segredos e runbooks;
9. concluir a inspeção visual autenticada no n8n e GLPI;
10. obter aceite formal dos responsáveis antes de qualquer ação autônoma.

## Governança NIST AI RMF

O projeto possui cobertura parcial, não certificação:

| Função | Evidência atual | Lacuna principal |
|---|---|---|
| GOVERN | fontes de verdade, manifests, gates e bloqueios | aprovação institucional e responsabilidades |
| MAP | escopo, falhas críticas, dependências e subgrupos propostos | contexto real e impacto sobre usuários |
| MEASURE | testes, intervalos, calibração, carga limitada, restore e drift implementável | dados reais, SLO acumulado e monitoramento instalado |
| MANAGE | abstenção, rollback, DLQ, fail-closed e planos de menor privilégio | exercícios E2E, resposta operacional e aceite |

O NIST AI RMF é uma estrutura de governança; não concede conformidade nem
valida o modelo automaticamente.

## Veredito

O trabalho tem boa rastreabilidade, controles técnicos acima da média para um
protótipo acadêmico e uma auditoria científica que agora impede conclusões
infladas. Seu principal ponto fraco não é “falta de mais um algoritmo”: é a
ausência de unidades reais independentes, gabarito externo e evidência
operacional acumulada. A opção de não usar revisão humana torna esse limite
permanente enquanto a decisão não mudar.

Portanto, o projeto pode ser apresentado como **protótipo local funcional e
plataforma de avaliação reproduzível**, com resultados sintéticos de
desenvolvimento. Não deve ser apresentado como IA treinada e validada para o
campus, sistema produtivo autônomo, nem workflow 100% correto.
