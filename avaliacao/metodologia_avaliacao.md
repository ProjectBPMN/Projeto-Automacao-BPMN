# Metodologia de avaliação

> [!WARNING]
> **Snapshot histórico, substituído em 27/08/2026.** Este texto usa unidades
> de dependência e resultados anteriores à auditoria de famílias-fonte. Não o
> use como protocolo corrente nem cite suas métricas históricas. A metodologia
> canônica está em `metodologia_avaliacao_v2_1.md`; a rodada V2.1 classificatória
> foi validada apenas no escopo parcial e a deduplicação ficou bloqueada por
> insuficiência de grupos independentes.

## Pergunta de pesquisa e hipóteses

Pergunta principal: o candidato híbrido local — TF-IDF, Granite Embedding 97M
em PyTorch FP32 e regressão logística calibrada — reduz o trabalho humano na
triagem de manutenção do patrimônio de um campus federal sem produzir risco de
decisão inaceitável, e como seus riscos, cobertura, custo e latência se comparam
ao Gemini no mesmo conjunto de teste congelado?

- H1: o candidato local supera regra fixa, classe majoritária e TF-IDF isolado
  em F1 macro de classificação.
- H2, pendente de pré-registro: o candidato local respeita simultaneamente os
  limites de falso negativo e falso positivo de deduplicação e não ultrapassa
  as margens institucionais de risco crítico em relação ao
  `gemini-3.5-flash`, sob comparação pareada. Cada risco exige estimando, margem
  e regra de decisão próprios; enquanto esses itens não forem aprovados antes
  do holdout, H2 não é testada como não inferioridade.
- H3: a configuração aprovada da fila processa a carga sem perda, inversão ou
  duplicação de lease e com taxa de falha e p95 dentro dos limites
  pré-registrados.
- H4: a automação reduz intervenções e tempo humano por chamado em relação ao
  fluxo integralmente manual, sem violar os limites de risco.

O estudo não pressupõe que raciocínio generativo seja sempre superior. A
hipótese é testável: um classificador calibrado com recuperação semântica pode
ser suficiente para as decisões repetitivas, enquanto a abstenção e as
confirmações humanas absorvem informação ausente ou fronteiras subjetivas.

O estudo separa três conceitos:

- **eficácia**: qualidade das decisões de duplicidade e classificação;
- **eficiência**: trabalho humano, chamadas, tokens e custo consumidos para
  produzir decisões corretas;
- **desempenho**: latência, vazão, espera, falhas, retentativas e estabilidade
  da fila.

## Escopo da etapa automatizada de 15/07/2026

Nesta etapa não será realizada dupla revisão humana dos rótulos. Essa escolha
antecipa testes de engenharia e concordância sintética, mas não altera os
pontos de confirmação humana dos workflows. Aprovações fiscais, triagens e
links de confirmação continuam presentes exatamente onde a operação os exige.
O oráculo determinístico externo de teste pode responder a esses pontos durante
o experimento, sempre depois de a predição ter sido persistida, para testar o
caminho completo. A ação não é avaliação humana, dupla revisão ou validação
externa.

### Contrato do oráculo determinístico externo de teste

O oráculo substitui operacionalmente o clique do revisor **somente** em uma
execução sintética identificada por `test-only`. O harness externo
`avaliacao/scripts/conferir_gabarito.py` chama os mesmos links assinados e
endpoints do WF04/WF05; ele não é um ramo do WF06, não atualiza diretamente o
estado final no banco e não remove os checkpoints humanos do workflow. Fora do
modo experimental, os links continuam aguardando uma pessoa.

Uma rodada automatizada só é válida quando todas estas guardas forem satisfeitas:

1. `run_id`, split/fase sintética e flag `test-only` estão presentes e
   registrados antes da liberação do primeiro chamado;
2. o modelo recebe apenas os campos canônicos do chamado e candidatos. O
   gabarito permanece estruturalmente fora do payload e inacessível ao gateway;
3. a resposta bruta, a normalização, as probabilidades, o snapshot de candidatos
   e o estado pré-decisão são persistidos antes de o oráculo ler o rótulo;
4. somente então o oráculo escolhe a ação prevista no gabarito e percorre o
   link/endpoint real. A operação deve ser idempotente: repetição do mesmo token
   não pode duplicar fechamento, followup ou transição;
5. cada reserva/tentativa fica na trilha separada
   `avaliacao_auto_confirmacoes`, vinculada à `ia_decisao_id`, com `run_id`,
   ticket/episódio, predição, gabarito, ação enviada, hashes de token/nonce,
   status, tentativas, resposta/erro e instantes. A restrição única por execução,
   realização, tipo e etapa, somada ao nonce único, garante idempotência. O
   harness nunca se identifica como avaliador humano;
6. ausência de qualquer guarda faz o oráculo falhar fechado, deixando o
   checkpoint pendente para revisão e invalidando a completude automatizada.

Essa separação temporal e estrutural evita *label leakage*: o gabarito só move o
workflow depois que a decisão a ser avaliada se tornou imutável. Ela permite
validar transições e concordância contra a regra pré-especificada, mas não
equivale a dupla revisão humana, não mede defeitos do gabarito e não prova sua
qualidade.

Consequentemente, as métricas desta etapa são descritas como **concordância com
gabarito sintético pré-especificado**. Elas não estimam erro do próprio gabarito
nem demonstram validade da decisão para chamados reais. A evidência operacional
é separada da evidência de eficácia, conforme a
[`PRE_REGISTRO_PENDENTE.md`](PRE_REGISTRO_PENDENTE.md). Os relatórios históricos
locais ficam fora da distribuição pública e não constituem evidência
confirmatória.

### Estados do candidato local

O protocolo usa quatro estados que não podem ser tratados como sinônimos:

1. **runtime verificado**: modelo de embedding, dimensão, precisão, revisão,
   hash e latência/RAM foram medidos; isso não mede eficácia;
2. **candidato calibrado**: o treino de desenvolvimento encontrou limiares que
   satisfazem os critérios pontuais internos;
3. **candidato congelado e elegível para avaliação**: bundle, dados de
   desenvolvimento, split, hiperparâmetros, limiares, adaptadores/gates,
   workflows e hashes estão fixos, sem uso do holdout, depois da regressão de
   desenvolvimento; esse estado permite gerar predições no teste independente;
4. **resultado cientificamente validado**: o candidato congelado concluiu o
   holdout e todos os gates analíticos/humanos aplicáveis à alegação.

Logo, `candidate_frozen=true` ou `evaluation_eligible=true` não pode ser
convertido em `scientifically_validated=true` no momento do treinamento. Ao
mesmo tempo, a ausência de validação científica prévia não pode bloquear a
execução do holdout que produzirá essa validação. A elegibilidade da predição
para análise e a conclusão científica agregada são registradas separadamente.
Os dois flags do manifesto de treinamento congelam o bundle candidato; o
preflight e o `freeze_manifest.json` precisam comprovar separadamente a revisão
exata do pipeline completo.
Uma resposta do bundle congelado pode carregar
`candidate_evaluation_eligible=true` enquanto `scientific_eligible=false`; o
primeiro habilita a linha para avaliar o candidato, e o segundo só muda depois
da conclusão confirmatória.

O runtime registra ainda `pipeline_evaluation_eligible`. Esse campo é o gate de
inclusão por linha do sistema completo: fica verdadeiro tanto quando o caminho
híbrido usa o bundle candidato válido quanto quando uma regra determinística de
segurança abstém/encaminha antes do modelo. Nesse segundo caso,
`candidate_evaluation_eligible` permanece falso, evitando atribuir ao modelo uma
decisão produzida pelo gate.

## Unidade experimental, candidatos e prevenção de contaminação

O `run_id` isola uma execução experimental da operação normal e de outros
splits. Dentro de um mesmo `run_id`, o WF02 deve receber candidatos elegíveis
de todos os episódios do corpus experimental, respeitando a mesma janela e os
mesmos estados usados pela operação. Essa regra mantém distratores realistas e
evita transformar a deduplicação em uma comparação fechada entre apenas dois
tickets conhecidos.

O `episode_id` identifica tickets relacionados e é usado como unidade mínima de
dependência estatística. Ele não deve filtrar a lista de candidatos. A
referência esperada de um duplicado precisa anteceder o segundo ticket, mas
outros episódios do mesmo `run_id` permanecem visíveis como distratores.

A deduplicação é decomposta em duas etapas: recuperação da referência na lista
de candidatos e decisão sobre os pares recuperados. Devem ser reportados
`recall@k` da referência esperada e qualidade da decisão condicionada à
referência estar presente. Uma referência ausente no top-k é erro do estágio de
recuperação, não deve ser atribuída integralmente à regressão de decisão.

Na configuração final, `LOCAL` e os papéis remotos recebem a mesma lista e
ordem de até 20 candidatos: `DEDUP_CANDIDATE_LIMIT=20` e
`DEDUP_LOCAL_TOP_K=20`. Em benchmark, os IDs, a ordem, o hash e a política do
snapshot são congelados; ausência ou divergência bloqueia a chamada. Assim, o
delta pareado não fica confundido por quantidades diferentes de candidatos.

Piloto, calibração e teste usam namespaces, seeds, `run_id`, `episode_id`,
`case_id` e famílias textuais separados. O gabarito fica fora do texto enviado
ao GLPI e nunca é incluído em título, descrição, prompt ou payload da IA.
Nenhum ajuste de prompt, regra, limiar, modelo ou código é permitido após o
hash do teste ser congelado.

Cada execução confirmatória possui exatamente um `model_id` previamente
registrado. O modelo não pode mudar dentro do `run_id`: uma resposta produzida
por modelo secundário ou de contingência não é atribuída ao modelo inicialmente
avaliado. Tentativa de fallback durante um benchmark torna aquela decisão
inelegível para a análise confirmatória do modelo e exige repetição controlada
em novo `run_id`, sem substituir ou apagar a tentativa original.

A validação entre splits deve verificar IDs e textos idênticos, mas também a
família narrativa. Mudanças apenas em saudação, ortografia, local ou wrapper não
constituem uma família linguística independente. `template_family` deve
identificar o núcleo narrativo que originou o caso.

### Unidade do seed naturalístico `primary33`

O conjunto principal desta etapa automatizada contém D01–D14 e C01–C19. São
33 cenários com 30 realizações naturalísticas cada, ou 990 realizações de
cenário. Essa contagem não equivale ao número de tickets:

- cada uma das 420 realizações D é um episódio com dois tickets, totalizando
  840 tickets de deduplicação;
- as 570 realizações C geram um ticket cada;
- o total operacional do `primary33` é, portanto, 1.410 chamados GLPI.

O prefixo D indica que o cenário avalia deduplicação; não significa que a
resposta correta seja sempre “duplicado”. D01, D06, D07, D12 e D13 são
positivos; D02, D03, D04, D05, D08, D09, D10, D11 e D14 são controles
negativos. Todo primeiro ticket de um episódio D é a âncora e também recebe
resposta esperada negativa.

D15 e C20 ficam fora do conjunto principal e compõem `stress2`. Trinta
realizações de cada acrescentam 90 tickets; executar `all35` gera 1.500 tickets
no total. Resultados desse conjunto de estresse devem ser apresentados em
estrato suplementar, sem aumentar artificialmente o suporte do `primary33`.

As variações ortográficas, abreviações, mudanças de urgência e demais ruídos
naturalísticos medem invariância linguística do sistema. Como compartilham o
mesmo desenho semântico, são observações agrupadas dentro de cenário, não novos
núcleos semânticos independentes. O relatório deve distinguir `n=990`
realizações, `N=1.410` tickets e o número de núcleos efetivamente novos; os
intervalos não podem tratar as 30 versões como 30 problemas independentes.

Para cenários sem urgência pré-fixada, a urgência é amostrada de modo
determinístico e reprodutível pela seed: níveis 1 a 5 recebem pesos 5%, 15%,
45%, 25% e 10%. C19 é exceção deliberada e permanece no nível 5. A urgência é
uma variável de superfície/robustez e não cria um núcleo semântico adicional.

## Gabarito, especialistas e adjudicação

O rótulo criado pelo gerador é uma hipótese sintética inicial. Ele não é, por
si só, o padrão-ouro de decisões subjetivas como OBRA versus DEMO, suficiência
de informação ou recorrência versus novo defeito.

O piloto é rotulado da seguinte forma:

1. dois especialistas avaliam independentemente e de forma cega as 94 decisões;
2. os especialistas não veem rótulo sintético, saída do modelo ou identidade
   um do outro;
3. a concordância e o Cohen's kappa são calculados separadamente para
   deduplicação e classificação;
4. concordâncias formam o rótulo humano aceito;
5. divergências são decididas por um terceiro especialista, também sem acesso
   ao resultado da IA;
6. o conjunto adjudicado é congelado antes da calibração e do teste.

Baixa concordância não deve ser escondida por adjudicação. Ela indica que a
política operacional ou a instrução de rotulagem precisa ser esclarecida. O
perfil e a experiência dos avaliadores, a versão das instruções, os hashes da
planilha e as decisões adjudicadas são preservados.

O oráculo determinístico externo de teste pode clicar nos links fiscais conforme
o gabarito para
permitir que o fluxo experimental termine. Essa ação ocorre somente depois do
registro da predição e não conta como avaliação humana nem como evidência de
acerto. Aplicam-se obrigatoriamente as guardas `test-only`, a separação contra
*label leakage*, a idempotência e a trilha `avaliacao_auto_confirmacoes`
definidas acima.

O protocolo de especialistas abaixo permanece definido para uma futura fase
confirmatória, mas está explicitamente adiado na etapa automatizada de
15/07/2026. Não preencher as planilhas humanas não autoriza marcar a execução
automatizada como gabarito adjudicado.

## Desenho experimental

### Fase L — desenvolvimento e congelamento local

O treinamento usa exclusivamente
`avaliacao/datasets/desenvolvimento_local_v1.jsonl`. O corpus contém 1.360
registros sintéticos do domínio de manutenção do patrimônio predial de campus
federal: 640 registros classificatórios, derivados de 128 núcleos, e 720
registros de deduplicação, derivados de 120 episódios. Suas variações não são
tratadas como observações independentes.

O corpus V3 de teste, `primary33`, `stress2`, `all35` e qualquer resultado
posterior são bloqueados pelo treinador. O split entre ajuste e calibração é
agrupado por núcleo/episódio; a auditoria também compara IDs, famílias e hashes
de texto para impedir versões do mesmo caso em lados diferentes.

Para classificação, a matriz combina TF-IDF de palavras/caracteres e o vetor
Granite de 384 dimensões. Para deduplicação, combina diferença absoluta,
produto elemento a elemento e cosseno dos vetores TF-IDF/embedding, além de
atributos estruturados do par. Regressões logísticas têm hiperparâmetros
selecionados por validação cruzada estratificada e agrupada. As probabilidades
e os limiares são obtidos por calibração fora de dobra no split independente de
calibração, seguida do refit final congelado.

O WF02 faz uma pré-seleção determinística por localização, tipo, texto e
recência antes da API local. O Granite não consulta sozinho todo o histórico:
ele participa do reranqueamento/decisão híbrida sobre os candidatos recebidos.
Essa decomposição é preservada para que recall de recuperação não seja
confundido com erro do classificador de pares.

A deduplicação usa dois limiares:

- `p(duplicado) >= t_positivo`: possível duplicado, ainda sujeito à confirmação
  fiscal;
- `p(duplicado) <= t_negativo`: não duplicado automático, segue para
  classificação;
- entre os limiares: abstenção e revisão, sem decisão automática forçada.

O custo de falso negativo é 5 e o de falso positivo é 1. O falso negativo é
mais grave neste fluxo porque evita a confirmação fiscal de duplicidade. O
falso positivo continua limitado, pois encaminhar casos demais ao fiscal reduz
a automação e pode gerar fadiga de alertas.

O treinamento somente produz um candidato. Mesmo quando os limiares internos
são aprovados, o manifesto mantém `scientific_result=false`,
`scientifically_validated=false`, `test_data_used=false` e
`primary33_used=false`. A avaliação independente é obrigatória para promover o
resultado científico.

O candidato vigente é o bundle congelado `local-hybrid-v1.8.0`. Seus limiares
de classificação, OBRA, deduplicação positiva, deduplicação negativa e margem
entre referências são, respectivamente, 0,76, 0,90, 0,95, 0,07 e 0,035. Na
calibração agrupada de desenvolvimento, o pipeline classificatório teve 165
registros, acurácia semântica 94,55%, macro-F1 94,34%, cobertura automática
51,52% e nenhum erro entre as 85 rotas automáticas. O gate assimétrico também
observou zero manutenção encaminhada automaticamente como OBRA. A deduplicação
teve 65 TP, 80 TN, 0 FP e 0 FN em 145 pares no ponto interno. Esses valores são
diagnóstico de desenvolvimento, não eficácia externa. Os próprios intervalos
de Wilson preservados no manifesto permanecem não nulos mesmo quando nenhum
erro é observado, razão pela qual o resultado não pode ser descrito como
garantia de erro zero.

O `local-hybrid-v1.1.0` permanece apenas como marco histórico. A comparação
ponta a ponta sobre os mesmos 1.240 `unit_id` mostrou 195 respostas válidas e
1.045 falhas na v1.1, contra 1.240 respostas válidas e nenhuma falha na v1.8.
Esse resultado sustenta ganho de disponibilidade, cobertura e latência no
desenvolvimento; não substitui o holdout nem prova superioridade contra modelo
remoto.

O bundle treinado e seus limiares são versionados separadamente das regras
determinísticas que decidem se um texto dispõe de informação suficiente para
chegar ao modelo. Uma ampliação dessas regras não altera TF-IDF, embedding,
features, pesos ou probabilidades calibradas, mas pode alterar a cobertura
ponta a ponta. Logo, qualquer revisão da extração precisa passar por regressão
no desenvolvimento, receber novo hash no freeze e permanecer imutável desde a
abertura do holdout.

Uma ablação no mesmo split/seed removeu os embeddings e manteve todo o restante
do pipeline. Na classificação de desenvolvimento, o híbrido obteve acurácia
0,95625 e macro-F1 0,95230, contra 0,92500 e 0,92140 no TF-IDF isolado; também
reduziu Log Loss/Brier e aumentou a cobertura seletiva de 0,68125 para 0,85 com
risco semelhante. Na deduplicação, ambos tiveram AP aproximadamente 1 e zero
erros no ponto interno; a diferença de Log Loss foi mínima, 0,019472 versus
0,019316. Essa é evidência de ablação sintética interna, usada para justificar
o candidato, não eficácia final nem prova de ganho no GLPI real.

Antes de abrir o holdout, a regressão ponta a ponta pode usar o modo
`--local-only` de `benchmark_pareado_local_gemini.py`. O padrão percorre todo o
desenvolvimento em 1.240 chamadas locais — 640 classificações e 600 desafios de
deduplicação — com lista de até 20 candidatos, sem chave, chamada ou cota
Gemini. O resumo discrimina tarefa, núcleo, `decision_path`, sistema completo
(`pipeline_evaluation_eligible`) e modelo efetivamente executado
(`candidate_evaluation_eligible` em caminho híbrido), sempre com
`scientific_result=false`.

O modo reservado para V3 exige confirmação one-shot explícita e ledger
exclusivo criado atomicamente. Uma tentativa iniciada não pode ser repetida
silenciosamente. Essa guarda evita uso iterativo do holdout; a promoção
científica continua dependente dos demais gates.

### Fase T — validação automatizada controlada

Antes de qualquer alegação confirmatória, o projeto executa a suíte completa de
testes estáticos, unitários, de contrato, navegador, integração e carga. O
corpus usa rótulos sintéticos determinísticos e o oráculo determinístico externo
de teste encerra somente os passos fiscais necessários. Essa ação não é revisão
humana nem validação externa. As confirmações humanas permanecem implantadas e
devem voltar a aguardar uma pessoa quando o modo experimental automático não
estiver ativo.

São permitidos nesta fase: matriz de confusão, F1, risco-cobertura e IC95%,
desde que o relatório declare a referência sintética e agrupe as realizações
dependentes. Não são permitidas conclusões de eficácia real, superioridade no
cotidiano do GLPI ou qualidade de padrão-ouro humano.

### Fase A — piloto e consolidação da política

O piloto atual contém 50 tickets, 35 episódios e 94 decisões. Ele é usado para:

- validar as instruções com dois especialistas e adjudicador;
- identificar cenários sem rótulo operacional estável;
- corrigir prompt, schema e taxonomia antes do teste;
- estimar taxa de erro, discordância e faixa de limiar;
- provar o caminho GLPI → WF06 → WF02/WF03 → WF04/GLPI.

O novo piloto usa `IA_CONFIANCA_MINIMA=0.50` para não truncar a curva de
sensibilidade. Resultados do piloto não são resultados confirmatórios, porque
podem orientar ajustes posteriores.

### Fase B — calibração de fila e vazão

A calibração ocorre em janela isolada e com fila operacional vazia. Cada
repetição é registrada no banco antes da recriação do n8n. Durante essa
recriação, `FILA_IA_RUN_SCOPE` recebe o `run_id` da repetição: o WF06 passa a
reservar e medir somente tickets vinculados a esse experimento em
`dataset_controle`. O relógio global do escalonador é reiniciado antes da carga,
para que uma liberação futura de uma repetição anterior não contamine o próximo
tratamento.

O início e o fim da janela usam o relógio do PostgreSQL. Ao término, uma
auditoria procura ingresso, reserva ou decisão de IA pertencente a tickets
externos ao `run_id`. Qualquer ocorrência reprova a repetição. Registros
históricos fechados não são contados só por existirem: é necessário haver um
evento na janela ou um estado ativo de fila alterado dentro dela. No bloco
`finally`, o n8n é sempre recriado com o escopo vazio, restabelecendo a fila
operacional.

Primeiro é feito um rastreio de configurações:

- três configurações de lote/intervalo;
- três repetições randomizadas por configuração;
- 12 tickets por repetição;
- dois warm-ups excluídos somente das latências.

Esse rastreio elimina configurações claramente instáveis, mas não sustenta uma
estimativa final de p95 ou p99. As duas melhores configurações seguem para a
confirmação:

- cinco blocos randomizados por configuração;
- 30 tickets por bloco;
- 300 tickets no total;
- 140 observações úteis de latência por configuração após warm-up.

Depois da escolha, rajadas de 25, 50 e 100 tickets verificam aceite rápido,
persistência, espera e drenagem. P95 é a métrica confirmatória de cauda; p99 é
exploratória enquanto não houver volume maior. Falha zero observada deve ser
acompanhada do limite superior de confiança da taxa de falha, nunca descrita
como garantia absoluta.

### Fase C — benchmark confirmatório futuro

O corpus V3 gerado possui 1.200 tickets:

- 500 episódios pareados de deduplicação, totalizando 1.000 tickets;
- entre os segundos tickets, cerca de 200 duplicados e 300 não duplicados
  difíceis;
- aproximadamente 200 chamados classificatórios de fronteira adicionais;
- 50 realizações nominais, mas somente dez núcleos narrativos independentes por
  classe semântica.

O volume mantém aproximadamente o suporte desafiador do plano antigo de 33
variações, mas reduz a multiplicação de negativos fáceis. O corpus deve conter,
no mínimo:

- 25 famílias de contraste de deduplicação;
- quatro núcleos narrativos independentes por família;
- cinco realizações superficiais por núcleo;
- ao menos dez núcleos narrativos por classe de classificação;
- variação de ativo, local, solicitante, tempo, estado anterior, sintoma,
  completude, ruído e quantidade de distratores.

As cinco realizações superficiais de cada núcleo são distribuídas em partições
físicas distintas. Cada partição mantém distratores de outros núcleos, mas não
expõe ao modelo outra paráfrase do mesmo núcleo. A análise posterior agrega as
dez partições sob um único corpus lógico e reamostra por núcleo/episódio.

A auditoria amostral demonstrou que o volume nominal não atende à margem de dez
pontos percentuais por classe depois de considerar a dependência. O desenho
revisado V4.1 planeja aproximadamente 2.078 chamados: 1.200 preservados do V3 e
878 novos, originados por 619 novos núcleos/episódios. As metas primárias são
100 núcleos por classe de classificação, 189 dedup positivos, 97 dedup
negativos completos e 73 dedup negativos críticos/insuficientes. As 960
repetições superficiais do V3 ficam em análise secundária de robustez. A
distribuição e os cálculos estão registrados em
[`PRE_REGISTRO_PENDENTE.md`](PRE_REGISTRO_PENDENTE.md). Essa expansão é
futura e nenhum novo caso é gerado na etapa corrente.

Antes da expansão, as 200 linhas positivas do V3 permitem concordância no
corpus fixo, mas representam somente 40 núcleos positivos independentes. A
incerteza é agrupada por núcleo e o gate inferencial FN ≤ 2% permanece não
demonstrável. Uma execução Gemini limitada a aproximadamente 100 linhas
positivas é exploratória.

Uma execução confirmatória usa o corpus congelado uma vez. Para medir
instabilidade do serviço remoto, uma amostra estratificada de 20% pode ser
repetida em três novos `run_id`. Repetições do mesmo caso não aumentam o número
de exemplos independentes e são analisadas como medidas repetidas.

Para comparação entre modelos, cada modelo é executado em `run_id` próprio,
vinculado ao mesmo `comparison_group_id`. As execuções recebem os mesmos
`case_id`, textos, campos, histórico de candidatos, ordem de apresentação,
prompt canônico, schema, limiar e configuração de fila. O conteúdo canônico
enviado à tarefa é preservado por hash; envelopes específicos de cada provedor
também são arquivados. Assim, diferenças de resultado não ficam confundidas
com diferenças de casos ou de contexto.

## Métricas de eficácia

### Deduplicação

A análise primária é `challenge_only`: considera o segundo ticket dos episódios
de deduplicação, onde existe uma relação real a distinguir. São reportados TP,
FP, FN, TN, precisão, recall, especificidade, F1, taxa de falso positivo, taxa
de falso negativo, valor preditivo negativo e cobertura automática.

A decisão automática `NAO_DUPLICADO` recebe prioridade de segurança: um falso
negativo segue para classificação sem passar pela confirmação fiscal de
duplicidade. Já a saída positiva ainda é uma hipótese submetida ao humano no
WF04. Por isso, o treinamento usa custo FN:FP de 5:1 e o relatório destaca FN e
VPN. Isso não autoriza falsos positivos ilimitados: precisão dos alertas e carga
fiscal permanecem critérios de automação.

A análise de todos os tickets é secundária e representa a operação global. Ela
não substitui `challenge_only`, pois âncoras iniciais e casos exclusivamente
classificatórios geram negativos estruturalmente fáceis.

Também são reportados:

- recall@k da referência esperada na recuperação e distribuição por cenário;
- métricas decisórias condicionadas à referência estar presente nos candidatos;
- acurácia da referência entre verdadeiros positivos;
- falso positivo por cenário, dificuldade, completude e quantidade de
  distratores;
- ROC-AUC, Average Precision, Log Loss e Brier quando os vetores de
  probabilidade forem válidos.

### Classificação

São reportados:

- matriz absoluta e normalizada;
- precisão, recall e F1 por classe;
- acurácia e F1 macro, incluindo zero para classe suportada sem predição
  positiva;
- F1 e recall de `OBRA`;
- ROC-AUC/AP um-contra-todos, Log Loss e Brier;
- `TRIAGEM_MANUAL` como quarta classe semântica coberta, incluída normalmente na
  matriz e nas métricas por classe;
- `ABSTENCAO` como decisão operacional distinta, incluída no denominador de
  cobertura e excluída da matriz/acurácia seletiva dos casos cobertos;
- curva risco-cobertura, sem contar abstenção como acerto automático nem como
  predição da classe `TRIAGEM_MANUAL`;
- resultados por cenário, risco, dificuldade e completude do chamado.

### Estratos de risco crítico na comparação local–Gemini

O relatório pareado separa dois eventos operacionais que a acurácia global não
representa adequadamente:

- **falso negativo automático de deduplicação**: gabarito `DUPLICADO` e saída
  `NAO_DUPLICADO` sem revisão humana;
- **manutenção encaminhada automaticamente como OBRA**: gabarito `DEMO` ou
  `SOB_DEMANDA` e saída `OBRA` sem revisão humana.

Em cada estrato são preservados o número de oportunidades, pares observáveis,
pares inválidos ou incompletos, eventos por provedor, tabela pareada
`ambos/local apenas/Gemini apenas/nenhum` e diferença de risco local menos
Gemini. Abstenções e rotas humanas não são contadas como esses eventos, mas sua
carga é reportada separadamente. Falha, ausência, duplicação de registro ou
divergência de tarefa, gabarito ou hash não é interpretada como decisão segura:
o par fica fora do denominador observável e aparece como incompleto.

Na etapa de desenvolvimento esses resultados são exclusivamente descritivos.
Não se calcula p-valor, não inferioridade ou conclusão de adoção para os
estratos críticos, porque ainda não há margem específica pré-registrada. Zero
eventos observados também não implica risco populacional zero.

## Métricas de eficiência

Por execução e por 100 tickets devem ser registrados:

- chamadas de IA, retentativas e chamadas por decisão final;
- provedor e modelo efetivos de cada tentativa, ordem da tentativa e motivo de
  qualquer troca de modelo;
- tokens de entrada, saída e total, quando retornados pelo provedor;
- custo estimado e custo efetivo da API;
- para o modelo local, tempo de CPU, RSS máximo, tamanho de artefato e energia,
  se houver instrumento válido, no lugar de inventar tokens ou preço de API;
- decisões automáticas corretas;
- triagens manuais e intervenções fiscais;
- minutos humanos de revisão e operação;
- custo por ticket e por decisão automática correta;
- redução de trabalho humano em relação ao fluxo manual de referência.

Se o provedor não expuser tokens ou preço de uma execução, a ausência é
declarada; valores não são inventados. Preços usados no cálculo são versionados
com data e moeda.

## Métricas de desempenho

São medidos separadamente:

- latência de aceite do webhook;
- espera em fila;
- tempo de serviço da IA;
- latência ponta a ponta;
- média, p50 e p95; p99 apenas com suporte suficiente;
- throughput de ingresso e de conclusão;
- erro, timeout, rate limit, retentativa e dead-letter;
- perda, processamento fora de ordem, reserva expirada e lease duplicado.

O benchmark de embedding é diagnóstico de componente. O artefato
`benchmark_embedding_pytorch_fp32_2026-07-15.json` compara os lotes operacionais
de um texto e sete textos e recomenda quatro threads neste computador. Seus
valores não podem ser apresentados como latência ponta a ponta: faltam
vetorização TF-IDF, regressão, HTTP, PostgreSQL, n8n e GLPI.

O intervalo do WF06 permanece fixo dentro de cada tratamento. Um controlador
adaptativo é outro experimento e não pode alterar a variável independente no
meio da comparação.

## Inferência estatística

Os intervalos usam no mínimo 2.000 reamostragens. O bootstrap é hierárquico:

1. reamostrar a família de contraste;
2. reamostrar o perfil-base do ativo dentro das famílias selecionadas;
3. reamostrar `narrative_core` e episódios sem separar suas realizações;
4. manter juntas todas as decisões do mesmo episódio;
5. em comparações de modelos, manter as previsões pareadas do mesmo caso.

Uma única realização sorteada e balanceada por núcleo compõe a estimativa
primária. As demais medem robustez linguística e não aumentam `n`. Novo valor de
`seed` com o mesmo catálogo também não aumenta o número de exemplos semânticos
independentes.

O bootstrap pareado estima o intervalo do delta de F1 macro, F1 de duplicidade,
taxa de falso positivo, risco, cobertura, custo e latência. Wilson 95% é usado
como complemento para proporções. McNemar exato é secundário para diferença de
acerto pareado e não substitui o intervalo do delta de F1.

A acurácia global local menos Gemini é um estimando diferente dos riscos
críticos. Portanto, eventual não inferioridade da acurácia global não testa H2.
Até que as margens específicas sejam aprovadas, os dois estratos críticos usam
somente estimativas pareadas descritivas; seus denominadores e discordâncias não
são combinados em uma pontuação única.

Quando houver vários comparadores, uma comparação primária é declarada antes do
teste; as demais são secundárias e usam correção de multiplicidade ou são
interpretadas como exploratórias. Ausência de significância não prova
equivalência ou não inferioridade.

## Proposta de critérios a pré-registrar

Antes da abertura do teste devem ser aprovados pelos responsáveis técnicos:

- limite superior de 95% da taxa de falso negativo `challenge_only` ≤ 2%;
- limite superior de 95% da taxa de falso positivo `challenge_only` ≤ 5%;
- valor preditivo negativo de deduplicação ≥ 98% e precisão dos alertas de
  possível duplicidade ≥ 90% no ponto congelado;
- limite superior de 95% do risco seletivo de classificação ≤ 10%;
- limite inferior de 95% da cobertura automática ≥ 60%;
- zero erros automáticos observados `MANUTENÇÃO → OBRA`, acompanhado do limite
  superior unilateral de 95% escolhido institucionalmente antes do holdout;
- para casos realmente `OBRA`, relato separado do recall automático sobre todos
  os casos e da acurácia seletiva apenas entre os casos cobertos; nenhum dos
  dois pode ser chamado simplesmente de “recall de OBRA” sem denominador;
- referência correta em duplicados dentro do limite aprovado;
- nenhuma perda ou duplicação de lease observada, acompanhada do limite
  superior de confiança da taxa de falha;
- p95 e custo dentro dos SLAs e orçamento registrados antes do teste.

Esses valores são proposta inicial, ainda não aprovada. O arquivo
[`PRE_REGISTRO_PENDENTE.md`](PRE_REGISTRO_PENDENTE.md) registra as decisões em
aberto. Depois de aprovados e antes de abrir o holdout, eles não podem ser
alterados; mudança posterior exige nova versão do protocolo e novo conjunto
confirmatório. A regressão de desenvolvimento atual não satisfaz a proposta de
cobertura automática mínima de 60%, portanto essa meta não pode ser descrita
como alcançada.

Na Fase L, esses limites são aplicados como gates pontuais de desenvolvimento e
os intervalos são descritivos, pois o corpus sintético de calibração não é o
holdout científico. Na avaliação independente, a conclusão usa os intervalos
pré-especificados e não promove automaticamente o candidato só porque o ponto
estimado interno foi aprovado.

## Auditoria humana reduzida

Esta seção descreve a futura extensão confirmatória. Ela não será executada na
etapa automatizada de 15/07/2026 e não deve ser falsamente satisfeita pelo
oráculo determinístico externo de teste. Ele testa as transições do workflow;
não cria concordância entre especialistas, revisão humana ou validação externa.

O benchmark não exige dupla leitura manual de todos os tickets. A auditoria é
dividida em três camadas:

1. antes do teste, dupla revisão dos templates ambíguos ou de alto risco;
2. revisão simples dos templates fáceis, com segundo especialista em amostra
   estratificada de 20%;
3. depois da geração, auditoria cega de cerca de 200 textos renderizados.

Depois da inferência, todos os desacordos modelo–gabarito são examinados para
atribuição causal, além de 150 a 200 aparentes acertos sorteados de forma
estratificada. A amostra aleatória estima defeito do gabarito; a revisão de
erros serve para diagnóstico e não é usada isoladamente para recalcular
acurácia. Erro sistemático reabre toda a família narrativa afetada.

## Modelo, prompts e reprodutibilidade

O papel operacional inicial é `LOCAL`, implementado pelo candidato
`local-hybrid-v1.8.0`. O embedding é
`ibm-granite/granite-embedding-97m-multilingual-r2`, revisão
`835ad14087e140460703cf0fae09f97d469d65c2`, dimensão 384, backend
`pytorch_fp32` e precisão FP32 em CPU. O serviço trabalha offline, com download
automático desativado, quatro threads e uma requisição concorrente por processo
na configuração medida neste computador. O Granite 350M é extractor opcional e
permanece desligado no caminho síncrono normal.

O único papel remoto na sequência operacional vigente é `SECONDARY`, associado
a `gemini-3.5-flash`. Não existe executor pareado DeepSeek validado no estado
atual; a configuração registra `deepseek-v4-flash` apenas como candidato remoto
bloqueado, pois sua API é tarifada e seu contrato difere do Gemini. A configuração
ativa não o chama. Essa política operacional não autoriza misturar modelos numa estimativa
de eficácia. WF02/WF03 usam contrato canônico estruturado; o remoto recebe
prompt e JSON Schema, enquanto o local recebe payload JSON nativo. Seed e
perfil são registrados quando suportados, mas não tornam uma API remota
perfeitamente determinística. Qualquer mudança de modelo ou perfil exige novo
manifesto e novo `run_id`.

Prompts, schemas, modelo, configuração, dataset, código, limiar e calibração de
fila são congelados por hash. Resposta bruta, resposta normalizada,
probabilidades, tempos, erro e tentativa são preservados para auditoria.

Para `LOCAL`, também são congelados o SHA-256 do bundle, a árvore do embedding,
a revisão do repositório, a dimensão, a precisão, o backend, as versões de
PyTorch/sentence-transformers/scikit-learn e o perfil de candidatos. Uma
resposta local sem esses metadados ou com fallback de desenvolvimento falha
fechado no gateway.

O executor inclui no freeze os seis artefatos JSON V9, todos os helpers e
builders Python de `n8n/workflows/Versão9`, os scripts de avaliação, os módulos
Python, scripts PowerShell e requisitos de `local_ai`, o manifesto dos modelos
e o bundle/manifesto híbridos. O `freeze_manifest.json` conserva o SHA-256 de
cada arquivo e um hash agregado. Qualquer alteração nessas superfícies —
inclusive nas regras determinísticas de extração — invalida a identidade do
freeze e requer outro `run_id`.

O manifesto de cada execução registra, no mínimo: papel do modelo, provedor,
identificador exato do modelo, versão ou alias observado, versão da API e do
adaptador, data/hora, parâmetros de geração, hashes de prompt, schema, dataset,
entrada canônica e código. Se um alias remoto puder mudar sem novo nome, a data
e toda versão retornada pelo provedor são indispensáveis para delimitar a
reprodutibilidade.

### Contingência operacional e sua separação do benchmark

Na operação, o encadeamento permitido é:

1. `LOCAL`, somente quando bundle e runtime atendem ao contrato;
2. `SECONDARY` (`gemini-3.5-flash`) após falha local explicitamente
   classificada.

O sistema registra cada tentativa sem sobrescrita, incluindo modelo solicitado,
modelo efetivo, erro, timeout, rate limit, tempo e motivo do failover. A decisão
final conserva a cadeia completa de proveniência. O secundário nunca substitui
silenciosamente o modelo local. Em benchmark, a função de fallback é bloqueada
e qualquer troca de modelo torna a linha inelegível para a comparação.

`ia_tentativas_modelo` é a unidade de observação de disponibilidade, latência,
tokens e falha por provedor; `ia_decisoes` é a unidade da decisão selecionada.
Para eficácia confirmatória usam-se somente decisões presentes em
`vw_decisoes_confirmatorias_elegiveis`: split de teste, modelo igual ao modelo
congelado, uma tentativa no ciclo e `fallback_utilizado=false`. Erros e
retentativas permanecem no relatório de desempenho, ainda que a decisão final
venha a ser válida.

No caso local, uma linha do holdout pode ser elegível quando veio do candidato
congelado aprovado para avaliação, com hashes/runtime corretos e sem fallback.
Essa elegibilidade de linha não marca o bundle como cientificamente validado; a
promoção somente ocorre depois da análise agregada e dos gates aplicáveis.

Disponibilidade e failover constituem experimento operacional separado. Esse
experimento mede taxa de sucesso por etapa, latência adicional, retentativas,
tempo de recuperação e proporção de decisões concluídas por cada modelo. Seus
resultados não entram na matriz de confusão confirmatória do modelo principal.
Se for desejado estimar a eficácia do secundário ou de um adaptador histórico,
cada modelo é executado diretamente, sem fallback, em seu próprio `run_id`
pareado.

## Comparadores e decisão sobre modelo próprio

O mesmo teste congelado é aplicado a:

1. regra fixa e classe majoritária do piloto;
2. Jaccard para duplicidade;
3. TF-IDF isolado + regressão logística e similaridade cosseno TF-IDF;
4. candidato híbrido `LOCAL`, em execução exclusiva;
5. `gemini-3.5-flash`, em execução exclusiva;
6. comparadores remotos históricos, somente se forem explicitamente
   pré-registrados e executados de forma exclusiva.

Todos os comparadores recebem os mesmos casos e entradas canônicas, e toda
predição é vinculada ao identificador e à versão efetivamente usados. O
encadeamento operacional `LOCAL → SECONDARY` é avaliado à parte como política
de disponibilidade, não como um modelo composto na comparação confirmatória.

Para preservar a quota Gemini, o número máximo de chamadas remotas é calculado
e aprovado antes da abertura dos resultados. RPM, TPM e RPD são copiados dos
limites ativos do projeto no AI Studio imediatamente antes do ensaio; o executor
aplica por padrão 80% desses valores, reserva RPM/TPM em janela móvel e mantém um
ledger conservador de tentativas em 24 horas. Como a cota é compartilhada por
projeto, também se exige ausência de outro consumidor durante o ensaio. Se o orçamento não cobrir o
holdout completo, usa-se uma subamostra estratificada, pareada entre modelos e
congelada previamente por `case_id` e hash. Falha de quota durante a execução
interrompe no primeiro HTTP 429 e não autoriza retry nem completar os casos
restantes com outro papel. O protocolo detalhado está em
`avaliacao/PROTOCOLO_BENCHMARK_REMOTO_V1.md`.

A adoção do candidato local só poderá ser recomendada após aprovação das
margens institucionais, avaliação confirmatória separada dos riscos críticos e
vantagem mensurável em F1, custo, latência, privacidade, operação local ou
dependência externa. A comparação descritiva atual não autoriza essa decisão.
Se os erros forem dominados por ausência de sala, ativo ou sintoma, a conclusão
prioritária é melhorar o formulário e o catálogo do GLPI, não treinar outro
modelo sobre entradas insuficientes.

## Validade e limites de conclusão

O benchmark sintético estratificado estima desempenho em fronteiras conhecidas,
não a prevalência real. Sem chamados reais anonimizados e autorizados, a
conclusão é limitada à validade interna da simulação controlada.

Uma validação externa posterior, independente do oráculo de teste, deve usar
chamados reais separados por tempo, unidade ou origem, com autorização e
anonimização. Dados usados para treinar um
modelo próprio não podem aparecer no teste. Resultados de infraestrutura,
piloto, calibração e benchmark são sempre apresentados separadamente.
Resultados de failover também permanecem separados dos resultados de eficácia
de cada modelo fixo.
