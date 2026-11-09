# Auditoria crítica completa — 26 de agosto de 2026

> Atualizada em 27/08/2026 após a conclusão parcial e a validação independente
> da seleção V2.1.
>
> **Snapshot histórico.** O estado corrente e as novas correções operacionais
> estão em `auditoria_critica_completa_2026-09-01.md`. As observações de
> navegador abaixo ocorreram em 26–27/08 e não equivalem a uma rechecagem atual.

## Parecer executivo

O projeto é uma plataforma de engenharia funcional para pesquisa aplicada, mas
ainda não é um sistema cientificamente validado para decisão autônoma em
produção. A arquitetura V9, o serviço local e o caminho GLPI → n8n → PostgreSQL
foram exercitados com evidência técnica. A eficácia do modelo em chamados
institucionais reais continua sem prova confirmatória.

A conclusão central desta auditoria é dupla:

1. o candidato `local-hybrid-v1.8.0` é uma escolha de engenharia razoável,
   congelada e operacional, não o vencedor de uma seleção científica válida;
2. a seleção comparativa executada anteriormente deve ser descartada como
   evidência de desempenho, porque unidades derivadas do mesmo molde-fonte
   podiam aparecer em dobras diferentes e o SHA-256 do corpus publicado não
   reproduzia o corpus congelado da rodada.

O protocolo 2.1 corrigiu esse problema com o grupo
`source_dependency_group_sha256` e foi reexecutado. A classificação completou
35 configurações e foi validada independentemente no escopo da tarefa; a
deduplicação falhou corretamente antes do ajuste por insuficiência de grupos.
Os números classificatórios são exploratórios/sintéticos e nenhum candidato
foi qualificado pelos limites de confiança.

## Escopo e método da auditoria

Foi gerado um [inventário mecânico do snapshot](inventario_arquivos_versionados_2026-08-26.md)
e foram examinados em profundidade os artefatos de maior risco:

- builders e JSONs dos seis workflows V9;
- scripts de implantação, validação estática e E2E;
- serviço `local_ai`, manifesto e bundle operacional;
- geradores de corpus, configs, executores, validadores e testes científicos;
- relatórios Markdown, resultados estruturados e hashes;
- infraestrutura Docker, variáveis de ambiente e arquivos potencialmente
  sensíveis;
- estado implantado no n8n, PostgreSQL e GLPI, inclusive inspeção manual no
  navegador.

O inventário automatizado enumerou 956 arquivos rastreados ou não ignorados no
snapshot; arquivos ignorados de runtime/backups ficaram fora desse manifesto.
A revisão semântica linha a linha foi priorizada por risco. Arquivos gerados,
modelos e datasets foram conferidos por schema, tamanho, hash, proveniência e
relação com os scripts que os produzem. Isso é mais defensável do que afirmar
uma revisão manual indistinta de centenas de binários e linhas JSONL.

## Respostas às perguntas do professor

### Como o modelo atual foi escolhido?

O `local-hybrid-v1.8.0` foi adotado por adequação às restrições do projeto:
português, execução local em CPU/8 GB, baixa latência, congelamento por hash,
probabilidades calibráveis, possibilidade de abstenção e auditabilidade. Ele
combina TF-IDF de palavras/caracteres, Granite Embedding 97M Multilingual R2 e
classificadores lineares calibrados.

Essa foi uma seleção de engenharia baseada em requisitos e em desenvolvimento
sintético. Não foi uma busca exaustiva nem uma validação confirmatória. Os
resultados numéricos que pareciam eleger Granite na rodada anterior foram
formalmente invalidados nesta auditoria.

### Qual pesquisa motiva embedding semântico?

Embeddings multilíngues são candidatos plausíveis porque projetam textos em um
espaço vetorial no qual paráfrases podem ficar próximas mesmo quando o
vocabulário difere. O relatório técnico da família E5 descreve treinamento de
embeddings de texto e sua extensão multilíngue; os model cards de Granite 97M
e MiniLM documentam dimensões, idiomas e usos pretendidos.

Essas fontes justificam testar os modelos, não escolher antecipadamente um
vencedor para chamados deste campus. Validade externa só pode vir de dados do
domínio, rótulos independentes e avaliação intocada.

Fontes principais:

- [Granite Embedding 97M Multilingual R2 — model card](https://huggingface.co/ibm-granite/granite-embedding-97m-multilingual-r2);
- [Multilingual E5 Text Embeddings: A Technical Report](https://arxiv.org/abs/2402.05672);
- [Text Embeddings by Weakly-Supervised Contrastive Pre-training — E5](https://arxiv.org/abs/2212.03533);
- [paraphrase-multilingual-MiniLM-L12-v2 — model card](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2).

### Por que não usar só TF-IDF ou só embedding?

TF-IDF preserva termos raros, códigos, nomes de ativos, grafias e fragmentos
lexicais. Embeddings podem reconhecer proximidade semântica entre formulações
diferentes. Cada um também falha de forma própria: TF-IDF perde paráfrases;
embedding pode aproximar ocorrências semanticamente parecidas, porém distintas.

O híbrido é, portanto, uma hipótese testável. A justificativa científica não é
“os dois sempre são melhores”, mas “medir se a combinação melhora o desfecho
predefinido sob o mesmo split e o mesmo classificador”. As ablações obrigatórias
são TF-IDF isolado, embedding isolado, híbrido e, em deduplicação, metadados e
híbrido+metadados.

### O treinamento terminou?

O bundle operacional v1.8 foi treinado/calibrado e está congelado. O embedding
Granite é pré-treinado e permanece congelado; o projeto treina os cabeçalhos
supervisionados e calibra seus escores, não faz fine-tuning integral do
embedding ou de uma LLM.

O trabalho científico não terminou. A parte classificatória da seleção 2.1
terminou, mas a deduplicação supervisionada, a rotulagem humana e o holdout
institucional ainda faltam. Por isso o runtime informa
`scientific_ready=false` e os manifests mantêm
`scientifically_validated=false`.

### O n8n está 100% correto?

Não é possível garantir 100% de correção. Foi possível demonstrar:

- build determinístico e validação estática dos seis workflows V9;
- paridade da lógica publicada no n8n;
- execução sintética isolada WF06 → WF02 → WF03;
- registro de decisões/tentativas, ausência de DLQ na rodada, terminal seguro e
  limpeza do caso sintético;
- inspeção manual no editor e no histórico de execuções do n8n;
- inspeção manual de chamados e transições no GLPI;
- rejeição de webhook com chave inválida sem persistir ticket.

Isso reduz risco nos cenários exercitados, mas não cobre toda combinação de
concorrência, indisponibilidade, permissão GLPI, dado malformado ou atualização
futura das dependências.

Na conferência final pelo navegador, os seis workflows V9 apareceram publicados
e o WF06 exibiu os nós esperados de ingresso, reserva, lote, pacing e despacho.
A execução manual `52143` terminou como `Succeeded` em 123 ms. Após o reinício
dos serviços e a rotação do token local, as execuções agendadas `52145` a
`52153` também apareceram como `Succeeded`; a mais recente, `52153`, levou
130 ms. No GLPI, o chamado 230 preserva as transições `Novo → Pendente → Em
atendimento (atribuído)`, correção de categoria e acompanhamentos. O chamado
266, ligado a uma experiência encerrada, permaneceu `Novo` e com apenas os dois
eventos de criação; sua quarentena ocorre no banco da fila, sem reescrever o
histórico do GLPI.

### As outras oito versões dos workflows estão guardadas?

Sim. `n8n/history/` preserva snapshots sanitizados e inativos de V1–V8. São dez
JSONs, pois a V8 contém WF01, WF02 e WF03. O manifesto vincula cada cópia à
origem e ao SHA-256; o validador e oito testes confirmaram cobertura V1–V8,
hashes, determinismo, inatividade e ausência dos padrões de segredo/runtime
verificados. Elas são reprodutíveis como histórico, mas não devem ser ativadas
sem revisão nem interpretadas como prova de correção produtiva.

## Análise científica da seleção comparativa

### Candidatos e ablações implementados no protocolo 2.1

| Dimensão | Opções |
|---|---|
| Embeddings | Granite 97M, multilingual-e5-small, multilingual MiniLM-L12-v2 |
| Representações | TF-IDF, embedding, híbrido; metadados e híbrido+metadados em deduplicação |
| Classificadores | regressão logística, árvore, SVM linear, MLP, XGBoost |
| Validação | `StratifiedGroupKFold` externo 5-fold e interno 3-fold |
| Calibração | sigmoide com predições fora de dobra |
| Incerteza | bootstrap por grupo e comparações pareadas por grupo |
| XAI | SHAP no finalista de cada tarefa, com auditoria de aditividade |

O uso de grupos é obrigatório porque múltiplas realizações textuais descendem
da mesma unidade-fonte. O scikit-learn documenta que `GroupKFold` impede que o
mesmo grupo apareça em treino e teste. A validação aninhada reduz o viés de
usar os mesmos dados para selecionar hiperparâmetros e estimar desempenho.

Referências:

- [GroupKFold — scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.GroupKFold.html);
- [Nested versus non-nested cross-validation — scikit-learn](https://scikit-learn.org/stable/auto_examples/model_selection/plot_nested_cross_validation_iris.html);
- [Varma e Simon, viés na estimativa de erro após seleção](https://pubmed.ncbi.nlm.nih.gov/16504092/).

### Falha descoberta na rodada anterior

O dataset dizia ter 80 núcleos independentes por classe e 200 episódios de
deduplicação. A origem real era menor:

- classificação: 32 moldes-fonte por classe, depois reamostrados/parafraseados;
- deduplicação: 12 famílias-fonte, expandidas para 200 episódios nominais.

Os identificadores antigos separavam derivados da mesma fonte. Isso permite
dependência entre treino e teste e estreita artificialmente a incerteza. Além
disso, o SHA-256 congelado na saída anterior não coincide com o corpus que o
gerador do repositório produzia. Consequências:

- Macro-F1, acurácia, cobertura, matrizes e p-valores anteriores não podem ser
  citados como desempenho do projeto;
- SHAP da rodada antiga explica um modelo ajustado em um experimento inválido;
- qualquer materialização derivada daquela seleção deve permanecer bloqueada;
- o resultado antigo foi preservado em `INVALIDADO.md` apenas para auditoria.

### Limitação que permanece mesmo após a correção

O V2.1 melhora o isolamento, mas não aumenta magicamente a informação. Há 128
famílias-fonte no corpus classificatório completo; após as regras de
elegibilidade, o estrato efetivamente submetido ao modelo tem 1.114 registros e
111 famílias (28/32/32/19 por classe). A deduplicação tem apenas 12
famílias-fonte, seis por classe. O desenho 5+4 grupos para ajuste/calibração não
cabe nem dentro do treino externo; por isso as 55 configurações falharam antes
do primeiro ajuste.

A classificação produziu um candidato provisório E5 + híbrido + SVM linear,
`UNDERPOWERED`: Macro-F1 0,7987 (IC95% 0,7266–0,8598), cobertura 60,86% e risco
seletivo 6,93% (IC95% 2,29%–13,21%). Nenhum candidato passou os limites de
confiança e a comparação pareada não demonstrou superioridade inequívoca de E5
sobre Granite. Esses resultados não promovem o bundle operacional.

Logo, o novo corpus serve para desenvolvimento e detecção de regressões. Não
serve como estimativa final de desempenho institucional.

## Uso dos classificadores supervisionados

| Algoritmo | Pode ser usado? | Papel e crítica |
|---|---|---|
| Regressão logística | Sim | baseline forte, rápido e auditável; adequado a TF-IDF esparso; precisa calibração e regularização. |
| Árvore de decisão | Sim | baseline interpretável e não linear; alto risco de sobreajuste/instabilidade no espaço textual de alta dimensão. |
| SVM linear | Sim | candidato forte para texto esparso; margem não é probabilidade, portanto a calibração deve ficar dentro do CV. |
| MLP | Sim, exploratório | captura não linearidade, mas exige mais dados, ajuste e memória; variância entre sementes deve ser relatada. |
| XGBoost | Sim, exploratório | aceita atributos tabulares/esparsos e interações; pode ser caro e sobreajustar com poucos grupos independentes. |

Nenhum algoritmo deve ser escolhido por acurácia isolada. O protocolo usa
critérios hierárquicos de segurança, depois desempenho, calibração, cobertura e
custo. Um modelo mais complexo só deve substituir o linear se o ganho pareado,
com intervalo de confiança, compensar latência e complexidade.

## XAI e SHAP

SHAP pode ser usado para:

- mostrar quais famílias de atributos sustentam uma predição;
- detectar atalhos espúrios, como localização ou categoria dominando o texto;
- comparar dependência de sinal lexical, semântico e metadados;
- produzir exemplos de erro para revisão humana.

O protocolo explica o escore-base do classificador, não promete explicar a
probabilidade após calibração. O residual de aditividade é auditado. Limites:

- SHAP não prova que a decisão está correta;
- atribuição não é causalidade;
- atributos correlacionados podem dividir crédito de modo instável;
- explicações de um corpus sintético não garantem comportamento em produção.

Fonte: [Lundberg e Lee, A Unified Approach to Interpreting Model Predictions](https://papers.nips.cc/paper_files/paper/2017/hash/8a20a8621978632d76c43dfd28b67767-Abstract.html).

## Crítica às métricas e estatísticas

### Pontos fortes

- separação explícita entre cobertura seletiva e risco/acurácia seletiva;
- classes de segurança e abstenção em vez de forçar automação;
- custos assimétricos de falso negativo e falso positivo na deduplicação;
- métricas por classe e objetivos hierárquicos, não um escore composto opaco;
- proveniência de modelo, dataset, config, seed e hashes;
- intenção de usar predições fora de dobra, calibração e bootstrap agrupado;
- latência separada entre inferência, API e E2E.

### Pontos fracos

- dados predominantemente sintéticos e altamente derivados;
- rótulos definidos pelo próprio processo de geração, não por especialistas
  independentes;
- poucas famílias independentes, especialmente em deduplicação;
- múltiplas comparações elevam a chance de achados ocasionais;
- limiares e políticas foram iterados no desenvolvimento, logo não podem ser
  avaliados honestamente no mesmo conjunto;
- métricas históricas misturam gates determinísticos, predição probabilística,
  abstenção e disponibilidade de transporte;
- zero erro observado foi por vezes narrado como segurança, quando só fornece
  um limite superior dependente do tamanho amostral;
- comparações com Gemini/DeepSeek sofreram falhas de transporte/cota e não
  medem superioridade semântica.

### Conjunto mínimo de resultados futuros

Para classificação: matriz, macro-F1, recall/F1 por classe, erro crítico
não-OBRA→OBRA, log loss, Brier, curva de calibração, cobertura e risco-cobertura.
Para deduplicação: recall@k da recuperação, FN/FP da decisão, NPV, precisão,
cobertura e custo ponderado. Para ambos: intervalos de confiança agrupados,
latência p50/p95, memória, taxa de falha e análise de subgrupos.

O relatório deve sempre informar o denominador e separar:

1. disponibilidade técnica;
2. cobertura semântica;
3. cobertura automática;
4. eficácia nos casos cobertos;
5. eficácia global contando falhas e abstenções conforme o estimando.

## Pontos fortes de engenharia

- seis workflows com builders determinísticos e IDs estáveis;
- política local-first, fallback controlado e modo de benchmark fail-closed;
- persistência de tentativa, decisão, modelo, versão, input e resultado;
- locks, leases, DLQ, retentativas e telemetria de fila;
- caminhos explícitos de revisão humana e abstenção;
- modelo e embedding congelados por revisão/hash;
- E2E sintético com escopo isolado, detecção de interferência e rollback;
- testes de contrato e validação estática extensos;
- separação entre `candidate_evaluation_eligible`,
  `pipeline_evaluation_eligible` e validade científica.

## Pontos fracos e correções implementadas

| Problema | Risco | Correção de 26/08 |
|---|---|---|
| Agrupamento por episódio/núcleo nominal | leakage entre derivados | grupo-fonte único `source_dependency_group_sha256` e testes de pureza/contagem |
| SHA da seleção antiga não reproduzível | resultado não auditável | resultado formalmente invalidado; dataset/config 2.1 regenerados e congelados |
| Launcher selecionava protocolo V1 por padrão | reprodução silenciosa errada | default e atalho PowerShell apontam explicitamente para V2.1 |
| Teste “live” criava ticket real e guardava segredos | mutação e vazamento | substituído por health/SELECT/probe 401 sem persistência; opt-in explícito |
| `local_ai/run_server.py` continha token local fixo | credencial previsível e já exposta no Git | valor removido, token externo obrigatório, gate estático ampliado e credencial local rotacionada em 27/08 sem registrar o novo valor |
| WF06 contava filas de experiências encerradas | backlog e capacidade falsos | fila elegível e quarentena `EXPERIMENTO_ENCERRADO` |
| Runtime carregava bundle diferente do n8n | decisões sem paridade | manifesto local e ambiente alinhados ao v1.8 operacional congelado |
| Modo de teste automático permaneceu habilitado | risco de confirmação indevida | `TEST_MODE=false` e `TEST_AUTO_HUMAN_CONFIRMATION=false` restaurados |
| Backups, binários, caches e segredos versionados | segurança e repositório inchado | removidos do índice e protegidos por `.gitignore`; cópias locais não foram destruídas |
| Documentação declarava números inválidos | inflação de evidência | banners de invalidação, README e documentos canônicos reescritos |
| Histórico V1–V8 precisava de prova verificável | rastreabilidade ambígua | `n8n/history/` validado: dez JSONs sanitizados, manifesto, hashes, teste de determinismo e cobertura V1–V8 |
| Deduplicação V2.1 não cabia nos grupos disponíveis | horas de treino seguidas de falha e risco de afrouxamento pós-hoc | preflight antes de embeddings/ajuste e escopo classificatório congelável; deduplicação permanece bloqueada |

## Validação técnica observada

Na rodada final pós-correção, preservada em
`avaliacao/resultados/e2e-pipeline-local-v1-20260826-final.json`:

- natureza: validação técnica sintética, não confirmatória;
- caminho: WF06 → WF02 → WF03;
- resultado terminal: `TRIAGEM_MANUAL`;
- duas reservas, duas decisões e duas tentativas;
- zero entrada em DLQ e zero interferência externa detectada;
- somente `local-hybrid-v1.8.0`, sem fallback;
- cleanup completo no GLPI e PostgreSQL, com controlador e perfil restaurados.
- hash final do WF06
  `dc78c11f6b221b8e8ba20c76069652ede5e11470e1576927f24ded7830146ab0`
  e paridade implantada confirmada;
- `run_id` `VALIDACAO-WF06-E2E-20260826T223056234436Z`, encerrado em
  26/08/2026 19:33:28 (America/Sao_Paulo).

## Organização e limpeza

A limpeza retirou do versionamento:

- exports de credenciais e arquivos `.env` reais;
- backup integral do GLPI e dumps de banco;
- sessões/exports repetidos do n8n;
- executáveis e DLLs do runtime local;
- caches de embeddings e resultados intermediários regeneráveis.

No total, 15.874 arquivos (500,27 MiB no snapshot Git) foram retirados do
versionamento. A decomposição e a política de recuperação estão em
`relatorio_limpeza_2026-08-26.md`.

Esses itens permanecem no disco quando necessários ao ambiente, mas agora são
ignorados pelo Git. Não foi feita exclusão física ampla, para preservar
recuperação, Docker e trabalho do usuário. Datasets, manifests, bundles e
resultados científicos foram mantidos quando necessários à rastreabilidade.

Ainda existe custo de manutenção: o repositório versiona muitos artefatos
binários/resultados. A próxima etapa recomendada é definir uma política formal
para promover somente resultados citados e mover bundles grandes para um
registro de artefatos com hash e retenção.

## O que falta para finalizar com máxima validade científica

### Bloqueadores científicos

1. obter autorização/LGPD e extrair amostra representativa de chamados reais;
2. definir unidade independente por ocorrência/ativo/local/tempo para impedir
   leakage institucional;
3. criar manual de rotulagem e fazer calibração pequena entre especialistas;
4. executar revisão por dois especialistas independentes, cegos às predições e
   aos rótulos um do outro, com adjudicação e medida de concordância;
5. pré-registrar desfechos, margens, subgrupos, exclusões e tamanho amostral;
6. ampliar as famílias independentes de deduplicação e executar novo protocolo
   apenas no desenvolvimento; a classificação V2.1 já foi concluída;
7. congelar candidato, código, dependências, limiares e container;
8. abrir uma única vez o holdout institucional intocado;
9. relatar intervalos, calibração, risco-cobertura, falhas e análise de erro;
10. executar piloto prospectivo em sombra antes de qualquer automação produtiva.

TRIPOD+AI e PROBAST+AI são referências úteis para transparência e risco de viés
em estudos de modelos preditivos; o NIST AI RMF ajuda a estruturar governança e
monitoramento. São guias, não selos automáticos de validade.

- [TRIPOD+AI](https://www.bmj.com/content/385/bmj-2023-078378)
- [PROBAST+AI](https://www.bmj.com/content/388/bmj-2024-082505)
- [NIST AI Risk Management Framework 1.0](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-ai-rmf-10)

### Bloqueadores de produção

1. testes de carga/concorrência e recuperação de falhas;
2. backup e restauração ensaiados para bancos e credenciais;
3. observabilidade com alertas, SLOs e runbooks;
4. rotação de segredos e contas de menor privilégio;
5. homologação GLPI/n8n separada de produção;
6. revisão de segurança dos links de decisão humana;
7. política de rollback de modelo/workflow e retenção de versões;
8. monitoramento de drift, cobertura, abstenção e risco por classe;
9. aceite formal dos responsáveis pelo processo.

## Veredito final

O projeto está forte como protótipo auditável e base de pesquisa aplicada. A
principal melhoria desta auditoria foi substituir uma narrativa de desempenho
aparente por um estado verificável: pipeline técnico funcionando, candidato de
engenharia congelado, seleção antiga invalidada, classificação V2.1 auditada
como exploratória e deduplicação corretamente bloqueada aguardando dados
independentes.

Não falta “só terminar o treinamento”. Falta completar o ciclo científico e o
ciclo operacional de produção. Até lá, o uso responsável é assistência com
abstenção e supervisão humana, sem alegar acurácia institucional ou correção
total.
