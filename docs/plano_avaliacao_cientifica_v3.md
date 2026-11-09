# Plano executável de avaliação científica V3/V4

> [!WARNING]
> **Snapshot histórico, superado pela auditoria de 26/08/2026.** A seleção
> citada neste documento não sustenta ranking atual: derivados de poucas
> famílias-fonte não ficaram integralmente no mesmo grupo. Toda classificação
> permanece sintética e a deduplicação antiga é subdimensionada. Use
> `auditoria_critica_completa_2026-08-26.md` e
> `resposta_professor_2026-08-26.md` como estado canônico.

> Atualização operacional de 16/07/2026: o candidato atual é
> `local-hybrid-v1.8.0` e a sequência ativa foi reduzida a
> `LOCAL → SECONDARY`, com `gemini-3.5-flash` como única contingência. As
> referências a v1.1 e à cadeia de cinco papéis abaixo registram a evolução do
> protocolo; não descrevem a configuração implantada. O estado atual e os
> limites de publicação estão em `estado_release_candidate_2026-07-16.md`.

> Atualização metodológica de 17/08/2026: a seleção supervisionada v1.3 comparou
> três embeddings, ablações isoladas/híbridas e cinco classificadores em 90
> configurações. A rodada terminou e foi aceita pelo validador independente. O
> híbrido Granite + TF-IDF foi o candidato provisório nas duas tarefas, mas os
> limites permaneceram `UNDERPOWERED`. A v1.8 continua sendo a referência
> operacional. Esta seleção usa somente desenvolvimento sintético e não
> substitui o holdout independente nem os rótulos humanos/adjudicados previstos
> abaixo.

## Objetivo e regra de interpretação

Este documento organiza a avaliação de eficácia, eficiência e desempenho do
fluxo GLPI → WF06 → WF02/WF03 → WF04/GLPI e a comparação pareada do candidato
local híbrido com Gemini, baselines e demais alternativas. A política
operacional atual é local-first: `LOCAL → SECONDARY`. O papel `LOCAL`
usa TF-IDF de palavras/caracteres, Granite Embedding 97M com vetores de 384
dimensões em PyTorch FP32 e regressões logísticas calibradas. O único papel
remoto ativo é `SECONDARY`, associado a `gemini-3.5-flash`; os demais
papéis permanecem somente como registros históricos. O gateway ativo implementa
apenas `LOCAL` e `SECONDARY`; DeepSeek é um candidato bloqueado, sem executor
pareado nem chamada operacional. Essa política de disponibilidade
não pode ser misturada com a comparação de eficácia: cada modelo é avaliado
sozinho, em `run_id` próprio e sem fallback.

Uma infraestrutura implementada não é um resultado científico. Um comando que
compila, um workflow ativo ou um dataset gerado prova prontidão técnica, mas não
prova acurácia, F1, vazão final ou superioridade do modelo.

Decisão de 15/07/2026: a etapa corrente executa validação automatizada sem
dupla revisão humana. As confirmações humanas permanecem nos workflows; quando
necessário, o oráculo determinístico externo de teste percorre esses pontos após
o registro da predição. Ele não é dupla revisão humana, avaliação humana ou
validação externa. Os resultados medem concordância com gabarito sintético e
prontidão operacional, não validade real. A fundamentação e o redimensionamento estão em
[`auditoria_amostral_v4.md`](auditoria_amostral_v4.md).

Os estados usados neste plano são:

- **existente**: artefato conferido no repositório;
- **evidência preliminar**: teste técnico ou histórico útil, mas não
  confirmatório;
- **resultado final**: saída de execução V3 congelada, com gates cumpridos,
  intervalos e auditoria;
- **gate**: condição obrigatória ainda não satisfeita.

Para o modelo local, há uma distinção adicional obrigatória:

- **candidato congelado e elegível para avaliação**: bundle treinado somente no
  desenvolvimento, calibração agrupada aprovada e, para o sistema completo,
  adaptadores/gates/workflows aprovados na regressão de desenvolvimento; todos
  os hashes ficam fixos sem uso do teste. Esse estado autoriza abrir o holdout,
  mas ainda não autoriza uma alegação de eficácia. Os flags do manifesto do
  bundle, isoladamente, não congelam o pipeline inteiro;
- **resultado cientificamente validado**: predições do candidato congelado no
  conjunto independente, sem fallback, com todos os gates e análises previstos
  concluídos. Só esse segundo estado pode sustentar a conclusão científica.

## Estado rastreável em 15/07/2026

### Artefatos existentes

| Artefato | Estado | O que demonstra |
|---|---|---|
| `avaliacao/datasets/cenarios_v2.json` | existente | Registro dos conjuntos `primary33` (D01–D14 + C01–C19) e `stress2` (D15 + C20). |
| `avaliacao/datasets/dataset_piloto_v2.jsonl` | existente | Piloto com 50 tickets e 35 episódios. |
| `avaliacao/datasets/validacao_rotulos_piloto_v2.csv` | existente, não preenchido | 94 decisões cegas aguardando especialistas. |
| `avaliacao/datasets/dataset_avaliacao_v2.jsonl` | existente | 250 tickets de desenvolvimento; continua sendo split de piloto, não benchmark. |
| `avaliacao/datasets/desenvolvimento_local_v1.jsonl` | existente, somente desenvolvimento | 1.360 registros sintéticos do patrimônio predial de campus federal: 640 classificatórios e 720 de deduplicação, agrupados por 128 núcleos e 120 episódios. Não é holdout nem padrão-ouro. |
| `avaliacao/datasets/desenvolvimento_local_v1_manifest.json` | existente | Registra geração determinística, fontes, política de rótulos, hashes, agrupamento e bloqueio confirmatório; documenta sobreposição zero com o corpus V3 nos identificadores/hashes auditados. |
| `avaliacao/config/plano_seed_33x30.json` | existente | Contabilidade executável do seed principal: 990 realizações de cenário e 1.410 chamados GLPI; não é resultado. |
| `avaliacao/datasets/planejamento_amostral_v2.json` | existente | Planejamento amostral anterior; não é resultado. |
| `avaliacao/datasets/corpus_v3_teste.jsonl` | existente, pendente de validação humana | Corpus lógico V3 com 1.200 tickets, 700 episódios e dez partições físicas. |
| `avaliacao/datasets/corpus_v3_teste_manifest.json` | existente | Contagens, gates, limitações e hashes do corpus V3; declara `scientific_result=false`. |
| `avaliacao/prompts` e `avaliacao/schemas` | existentes | Fontes canônicas de prompt e saída estruturada. |
| `avaliacao/manifesto_modelo_prompts.json` | existente | Modelo, versões e hashes congeláveis. |
| `avaliacao/config/modelos_ia_v1.json` | existente | Sequência operacional local-first, papéis comparativos e contrato reprodutível do runtime local. |
| `local_ai/models/manifest.json` | existente | Revisão, dimensão, tamanhos e SHA-256 do Granite Embedding; registra o extractor opcional e os artefatos OpenVINO experimentais desativados. |
| `local_ai/artifacts/local_hybrid_manifest.json` | candidato vigente congelado, não resultado científico | Registra `local-hybrid-v1.8.0`, limiares, hashes, proveniência do pipeline e estado `PENDING_CONFIRMATORY_HOLDOUT`; mantém `scientifically_validated=false`. |
| `avaliacao/resultados/benchmark_embedding_pytorch_fp32_2026-07-15.json` | evidência técnica, não eficácia | Compara 1, 2 e 4 threads no i3 usando os lotes reais de 1 e 7 textos; recomenda quatro threads. Mede somente embedding. |
| `avaliacao/resultados/treino-local-pytorch-fp32-v1.1.0-conservador-20260715` | candidato histórico substituído | Preserva o treino/calibração agrupados da v1.1 para auditoria. Seus limiares não descrevem a configuração implantada. |
| `avaliacao/resultados/ablacao-tfidf-v1.1.0-20260715` | ablação interna sintética | Repete split, seed e pipeline sem embeddings para isolar o ganho de desenvolvimento do Granite. Não é comparação no holdout. |
| `avaliacao/scripts` | existente | Geração, execução, rotulagem, calibração, métricas e baselines. |
| `avaliacao/sql/consultas_metricas_avaliacao.sql` | existente | Consultas para extração dos resultados. |
| `avaliacao/resultados` | diagnósticos e execuções não confirmatórias | Preserva contratos, testes técnicos e rodadas automatizadas; não há resultado científico final V3. |

### Evidências preliminares

- builders e scripts críticos compilam;
- a validação estática dos seis workflows passa;
- prompts e schemas estruturados estão incorporados aos workflows;
- existem telemetria de fila, retentativa, lease, dead-letter e decisões da IA;
- testes históricos cobriram rotas operacionais e observaram rate limit;
- o oráculo determinístico externo de teste consegue acionar automaticamente os
  endpoints fiscais depois que a predição já foi registrada, sem se apresentar
  como pessoa ou validação externa.
- o Granite local foi verificado com dimensão 384 e parâmetros FP32; no ensaio
  isolado de threads, quatro threads obteve p95 de 119,9 ms no lote de
  classificação com um texto e 501,9 ms no lote de deduplicação com sete
  textos, com RSS máximo amostrado de 822,0 MB;
- WF02/WF03 usam o papel operacional `LOCAL`, exigem metadados do backend e
  registram cada tentativa local ou remota sem sobrescrita.
- a versão vigente v1.8 usa limiar 0,76 para classificação, trava 0,90 para
  OBRA, 0,95 para duplicidade positiva, 0,07 para não duplicidade e margem
  0,035 entre referências. O bundle canônico tem SHA-256
  `f518b7f9699aa9e23aab7eb2479990619ad5085994569b3f7c3f253e5207bb5d`
  e continua com validação confirmatória pendente;
- a v1.1 e seus hashes permanecem nas subseções históricas abaixo, sem efeito
  sobre a configuração atual.

Essas evidências não permitem afirmar que o candidato local ou o Gemini têm
bons índices, que a fila suporta uma vazão definitiva ou que um modelo próprio
é superior. A medição do embedding também não equivale à latência completa da
API, do workflow ou do GLPI.

### Resultados científicos existentes

Nenhum. Ainda não existem, sob o protocolo V3:

- gabarito piloto adjudicado;
- limiar aprovado;
- calibração confirmatória de vazão;
- execução do benchmark congelado de 1.200 tickets já gerados;
- matriz de confusão e intervalos finais;
- custos por decisão;
- comparação confirmatória entre o candidato local congelado e os modelos
  remotos selecionados.

Isso não impede a etapa automatizada V4. Ela produz evidência exploratória
claramente rotulada e não muda o estado dos gates humanos confirmatórios.

## Seed naturalístico `primary33` — unidade e contabilidade

O seed pedido para a validação automatizada usa exatamente 33 cenários:

- deduplicação: D01 a D14, 14 cenários;
- classificação/controle: C01 a C19, 19 cenários;
- 30 realizações naturalísticas por cenário, incluindo ruído ortográfico,
  abreviações e níveis de urgência.

Nos casos sem urgência fixada pelo cenário, o gerador sorteia esse campo de
forma determinística pela seed, com pesos 5%, 15%, 45%, 25% e 10% para os níveis
1, 2, 3, 4 e 5, respectivamente. C19 permanece fixado em urgência 5 para isolar
o teste de “tom urgente não muda a classe”. Isso mantém reprodutibilidade sem
produzir uma distribuição artificialmente uniforme.

O produto `33 × 30 = 990` conta **realizações de cenário**, não chamados
criados no GLPI. Cada realização D é um episódio pareado — ticket âncora mais
ticket-desafio —, enquanto cada realização C gera um ticket. Portanto:

| Componente | Cálculo | Chamados GLPI |
|---|---:|---:|
| D01–D14 | 14 × 30 episódios × 2 tickets | 840 |
| C01–C19 | 19 × 30 realizações × 1 ticket | 570 |
| **Total `primary33`** | **990 realizações de cenário** | **1.410** |

O prefixo D identifica a **tarefa de deduplicação**, não uma resposta positiva.
No gabarito atual, D01, D06, D07, D12 e D13 são duplicados positivos; D02,
D03, D04, D05, D08, D09, D10, D11 e D14 são controles negativos deliberados.
Além disso, o primeiro ticket de todo episódio pareado é âncora e recebe
`expected_dedup=false`.

D15 e C20 formam o conjunto suplementar `stress2`. Com 30 realizações de cada,
ele acrescenta 90 tickets (60 de D15 e 30 de C20); `all35` totaliza 1.500
tickets. Esses dois cenários medem baixa sobreposição semântica e truncamento
de texto, mas não aumentam o tamanho declarado do corpus principal.

As 30 realizações de um cenário são medidas repetidas de robustez linguística.
Erros de português, abreviações, tom de urgência ou outra seed não criam, por
si, novos núcleos semânticos independentes. A análise deve preservar
`scenario_id` e `episode_id`, tratar as realizações como agrupadas e não usar
`n=990` como se fossem 990 problemas semanticamente independentes. Este seed é
adequado para validação automatizada naturalística e estresse, mas não substitui
os 619 novos núcleos/episódios previstos para uma futura ampliação V4.1.

## Fase T — validação automatizada sem dupla revisão

Nesta fase devem ser executados todos os testes automatizados seguros:

- validação estática, builders, schemas e testes unitários;
- contratos dos provedores e persistência de toda tentativa;
- navegador, GLPI, webhooks, fila, confirmações fiscais e estados terminais;
- rajadas, vazão, retentativa, rate limit, lease e dead-letter;
- matriz de confusão e intervalos contra o gabarito sintético.

O relatório deve incluir `reference_type=SINTETICA_PRE_ESPECIFICADA` ou
descrição equivalente. Não pode usar `PADRAO_OURO_HUMANO`, `EFICACIA_REAL` ou
`BENCHMARK_CONFIRMATORIO` sem cumprir os gates humanos. O oráculo determinístico
externo de teste não substitui revisor: ele apenas permite provar que a resposta fiscal correta
para o caso de teste percorre o workflow completo.

Para evitar vazamento de rótulo e contornar produção, o oráculo determinístico
externo de teste deve cumprir um contrato fechado. O harness
`avaliacao/scripts/conferir_gabarito.py`, e não um ramo do WF06, opera apenas com
`run_id`/split sintético e flag `test-only`; mantém o gabarito fora do payload do
modelo; aguarda a persistência imutável da predição, probabilidades e candidatos;
e aciona os mesmos links/endpoints assinados usados pelo fiscal/revisor. Reserva,
tentativa e resultado ficam em `avaliacao_auto_confirmacoes`, com chaves únicas
por realização/etapa e nonce para idempotência, sem identidade humana. Falha de
guarda deixa o checkpoint pendente e invalida a completude da rodada. Em
produção, nenhuma dessas guardas autoriza clique automático: os checkpoints
continuam humanos.

## Gate G0 — alinhar implementação e protocolo

Antes de abrir o piloto V3, confirmar por validação estática e inspeção do JSON
implantado que:

- candidatos experimentais de deduplicação são isolados por `run_id`, mas não
  limitados ao mesmo `episode_id`;
- `episode_id` permanece disponível para cluster estatístico;
- as métricas publicam `challenge_only` e todos os tickets separadamente;
- `template_family` identifica núcleo narrativo real;
- classes sem predição positiva entram com F1 igual a zero;
- concluir benchmark exige rótulos e auditoria humana registrados;
- respostas, probabilidades, tokens, tempos e configuração ficam auditáveis.
- cada `run_id` confirmatório usa um único modelo congelado;
- modelo solicitado, modelo efetivo e toda tentativa de fallback ficam
  registrados sem sobrescrita;
- execuções comparativas usam os mesmos casos e entradas canônicas, vinculadas
  por `comparison_group_id` e hashes.
- para `LOCAL`, backend, precisão, dimensão, revisão e hash da árvore do
  embedding são conferidos no gateway e persistidos com a tentativa;
- o banco e o executor distinguem um candidato congelado elegível para abrir o
  holdout de um resultado que já concluiu a validação científica; o primeiro
  não pode ser recusado por ainda não possuir o segundo estado;
- `historico_local` e `historico` usam a mesma lista e ordem de até 20
  candidatos (`DEDUP_CANDIDATE_LIMIT=20` e `DEDUP_LOCAL_TOP_K=20`); no
  benchmark, IDs, hash e política pareada são obrigatórios.

Comando técnico inicial:

```powershell
python "n8n\workflows\Versão9\validate_v9_static.py"
python "avaliacao\scripts\sincronizar_manifesto.py" --check
```

Se o validador ainda afirmar isolamento por episódio, G0 não está cumprido para
o protocolo V3, mesmo que todos os demais checks estejam verdes.

## Fase L — treinar e congelar o candidato local

Esta fase ocorre antes do piloto/holdout e usa somente o corpus de
desenvolvimento. `corpus_v3_teste`, `primary33`, `all35`, `stress2` e qualquer
resultado do benchmark são proibidos no ajuste de pesos, hiperparâmetros,
calibração ou limiares.

Comando reproduzível previsto:

```powershell
python "avaliacao\scripts\treinar_modelo_local.py" `
  --dados "avaliacao\datasets\desenvolvimento_local_v1.jsonl" `
  --saida "avaliacao\resultados\treino-local-pytorch-fp32-v1.1.0-conservador-20260715" `
  --embedding-backend granite `
  --embedding-model-path "local_ai\models\granite-embedding-97m-multilingual-r2" `
  --embedding-model-revision "835ad14087e140460703cf0fae09f97d469d65c2" `
  --cpu-threads 4 `
  --custo-fn-dedup 5 `
  --fn-dedup-maximo 0.02 `
  --fp-dedup-maximo 0.05 `
  --vpn-dedup-minimo 0.98 `
  --precisao-dedup-minima 0.90
```

O pipeline mantém núcleos/episódios inteiros no mesmo split, seleciona
hiperparâmetros por validação cruzada estratificada e agrupada, calibra
probabilidades fora de dobra e escolhe dois limiares de deduplicação: um para
afirmar possível duplicidade e outro para afirmar não duplicidade. A região
intermediária é abstenção/revisão, não resposta automática forçada.
Entre pontos com o mesmo erro ponderado, número de FN e cobertura, o desempate
é conservador: maior limiar positivo e menor limiar negativo.

O falso negativo de deduplicação recebe custo 5 e o falso positivo custo 1.
Isso reflete o fluxo real: um falso negativo segue para classificação sem passar
pela confirmação de duplicidade, enquanto um falso positivo ainda encontra a
barreira fiscal. O limite de falso positivo permanece rígido, porque excesso de
alertas também reduz a automação.

Gate L:

- fonte aceita como desenvolvimento e auditoria anti-vazamento aprovada;
- embedding exatamente PyTorch FP32, dimensão 384, revisão e hash registrados;
- limiares de classificação, duplicidade positiva e duplicidade negativa
  aprovados pelos critérios pré-especificados;
- `test_data_used=false` e `primary33_used=false`;
- bundle e manifesto com SHA-256 fixos;
- `candidate_frozen=true` e elegibilidade para **executar** a avaliação;
- respostas do holdout podem registrar `candidate_evaluation_eligible=true`
  quando o caminho híbrido realmente usar bundle/runtime/hashes corretos e não
  houver fallback;
- toda linha analisável exige `pipeline_evaluation_eligible=true`; caminhos
  determinísticos de segurança podem satisfazer esse gate sem alegar que o
  bundle produziu a decisão;
- `scientifically_validated=false` e `scientific_result=false` até a conclusão
  do holdout independente.

Falha em Gate L não pode ser resolvida afrouxando critérios depois de consultar
o teste. Corrige-se o desenvolvimento e gera-se uma nova versão do candidato,
mantendo o candidato anterior e seu diagnóstico auditáveis.

### Resultado interno histórico da Fase L em 15/07/2026

Esta subseção preserva a calibração da v1.1 para rastreabilidade. Seus limiares
foram substituídos na configuração vigente pela v1.8: classificação 0,76,
trava de OBRA 0,90, duplicidade positiva 0,95, não duplicidade 0,07 e margem
entre referências 0,035. O resultado atual de regressão está em
`TEST_REPORT.md`; nenhum dos dois constitui validação externa.

O bundle candidato conservador `local-hybrid-v1.1.0` foi treinado e congelado em
`avaliacao/resultados/treino-local-pytorch-fp32-v1.1.0-conservador-20260715` com status
`CALIBRATED`. O manifesto confirma `evaluation_eligible=true`,
`candidate_frozen=true`, `test_data_used=false`, `primary33_used=false`,
`scientifically_validated=false` e `scientific_result=false`.

Na calibração agrupada sintética de desenvolvimento:

| Tarefa | Ponto selecionado | Resultado interno | Interpretação permitida |
|---|---|---|---|
| Classificação | limiar 0,67 | 136/160 cobertos (85%); 135/136 cobertos corretos; risco seletivo pontual 0,735% | O limiar passou o gate interno; não estima eficácia no GLPI real. |
| Deduplicação | positivo 0,95; negativo 0,08 | 70 TP, 80 TN, 0 FP e 0 FN em 150 pares; cobertura 100% | O ponto conservador passou o gate interno sintético; zero erro observado não é garantia de erro zero. |

Os intervalos de Wilson preservados no manifesto reforçam a limitação: mesmo
com 0 FP e 0 FN observados, os limites superiores descritivos são
aproximadamente 4,58% para FP e 5,20% para FN. Portanto, a calibração não prova
o limite confirmatório de FN ≤ 2%; ela somente autoriza avaliar o candidato
congelado no holdout independente. Nenhum ajuste futuro pode consultar esse
holdout e depois manter a mesma alegação confirmatória.

O bundle e seus limiares não foram alterados pela ampliação posterior das regras
determinísticas de suficiência textual. Essa alteração pode mudar a cobertura do
pipeline completo, embora não mude TF-IDF, embedding, features, pesos ou
probabilidades calibradas. Por isso, a revisão externa do pipeline só pode abrir
o V3 depois de uma regressão ponta a ponta no corpus de desenvolvimento e do
congelamento do novo hash de `local_ai/extraction.py`; depois da abertura do
holdout, nenhuma regra pode ser ajustada no mesmo experimento.

### Ablação interna TF-IDF versus híbrido Granite

Com o mesmo split, seed e pipeline de desenvolvimento, o híbrido elevou a
acurácia de classificação de 92,50% para 95,625% (+3,125 pp) e o macro-F1 de
0,92140 para 0,95230 (+3,09 pp). Log Loss caiu de 0,23497 para 0,18756 e Brier
de 0,11800 para 0,08651. No ponto seletivo, a cobertura subiu de 68,125% para
85%, com risco pontual de 0,917% e 0,735%, respectivamente.

Na deduplicação, os dois candidatos observaram 0 FP/0 FN e AP aproximadamente
1 no mesmo desenvolvimento. O Log Loss mudou apenas de 0,019472 para 0,019316,
ganho mínimo. A conclusão permitida é que o embedding trouxe sinal interno
relevante para classificação e ganho não demonstrado para deduplicação neste
corpus sintético; nenhuma superioridade final é inferida antes do holdout.
O bundle TF-IDF tem SHA-256
`4fa0eca109b4e1981e5b227e87257f5d787abd67574ef68aabfeb93254dd5135`
e seu manifesto,
`f20129cc3a9b091dbc0a269dbc2b08f08eab3a5ac2baeed84a53eea1a21a3e16`.

### Regressão `local-only` do pipeline completo

O script `avaliacao/scripts/benchmark_pareado_local_gemini.py` dispõe de modo
`--local-only`. Por padrão ele usa somente o corpus de desenvolvimento e prepara
1.240 chamadas locais: 640 classificações, derivadas de 128 núcleos × cinco
realizações, e 600 desafios de deduplicação, derivados de 120 episódios × cinco
realizações. Não lê chave Gemini, não consome cota remota e mantém
`scientific_result=false`.

O relatório separa métricas gerais, por tarefa, núcleo e `decision_path`, além
de dois estratos: sistema completo (`pipeline_evaluation_eligible=true`) e
modelo executado (`candidate_evaluation_eligible=true` em caminho híbrido).
Abstenção de deduplicação não pode ser convertida em `NAO_DUPLICADO`. O limite
de candidatos padrão é 20; qualquer valor menor no modo local é exploração
registrada, não configuração do benchmark pareado.

O corpus reservado V3 nunca é selecionado por acidente. Sua execução local
exige confirmação explícita `--confirm-reserved-local-one-shot` e um ledger
exclusivo criado de forma atômica, impedindo segunda abertura silenciosa. Essa
execução one-shot ainda não equivale, por si, a resultado científico validado.

## Fase A — piloto, especialistas e limiar

### A1. Preparar a janela

1. garantir que a fila operacional esteja vazia;
2. reservar início e fim da janela experimental;
3. configurar `IA_CONFIANCA_MINIMA=0.50`;
4. recriar o serviço n8n e verificar o valor efetivo;
5. congelar modelo, prompts, schemas, seed e código;
6. conferir que o modo confirmatório impede fallback e que o manifesto contém
   o identificador exato do modelo escolhido.
7. para o piloto local, iniciar a API com o bundle congelado, confirmar
   `decision_ready=true` e registrar `scientific_ready` sem confundi-lo com a
   elegibilidade do candidato para ser avaliado.

### A2. Executar o piloto

```powershell
python "avaliacao\scripts\executar_avaliacao.py" piloto `
  --model-role LOCAL `
  --confidence-threshold 0.50 `
  --run-id "PILOTO-V3-AAAAMMDD"
```

O diretório do `run_id` deve conter dataset, manifesto congelado, predições e
relatório. O oráculo determinístico externo de teste pode resolver cliques
fiscais para completar o caminho, mas somente pelo contrato `test-only` acima e
depois da persistência da predição; ele não valida o gabarito, não é revisão
humana e não constitui validação externa.

### A3. Rotular e adjudicar

Preencher primeiro:

- `avaliacao/datasets/perfil_avaliadores_template.json`;
- `avaliacao/datasets/validacao_rotulos_piloto_v2.csv`.

Depois validar e incorporar:

```powershell
python "avaliacao\scripts\validar_rotulos_especialistas.py" `
  --dataset "avaliacao\datasets\dataset_piloto_v2.jsonl" `
  --planilha "avaliacao\datasets\validacao_rotulos_piloto_v2.csv" `
  --perfil-avaliadores "avaliacao\datasets\perfil_avaliadores_template.json" `
  --incorporar `
  --saida-validacao "avaliacao\resultados\PILOTO-V3-AAAAMMDD\rotulos_validados.json"
```

Gate A:

- 94 decisões com dois revisores válidos;
- divergências com terceiro adjudicador;
- perfil, instruções, kappa e hashes preservados;
- taxonomia revisada se a concordância revelar ambiguidade sistêmica.

### A4. Calibrar o limiar

Os limites abaixo precisam ser aprovados antes de executar o comando:

```powershell
python "avaliacao\scripts\calibrar_limiar.py" `
  --run-id "PILOTO-V3-AAAAMMDD" `
  --saida "avaliacao\resultados\PILOTO-V3-AAAAMMDD\limiar_aprovado.json" `
  --min 0.50 --max 0.95 --passo 0.05 `
  --risco-maximo 0.10 `
  --cobertura-minima 0.60 `
  --fp-dedup-maximo 0.05
```

O limiar do piloto é calibratório. Sua confirmação ocorre no teste congelado;
não se escolhe novo limiar depois de observar o benchmark.

## Fase B — calibração de vazão

### B1. Rastreio

```powershell
python "avaliacao\scripts\calibrar_vazao.py" `
  --configuracoes "1@60,2@45,3@30" `
  --repeticoes 3 `
  --tickets-por-repeticao 12 `
  --warmup 2 `
  --concorrencia-ingresso 4 `
  --randomizar-ordem `
  --saida-dir "avaliacao\resultados\calibracao-fila-v3-rastreio"
```

Essa etapa elimina tratamentos inviáveis; não define p95 final.

### B2. Confirmação

Substituir as duas configurações abaixo pelas vencedoras do rastreio:

```powershell
python "avaliacao\scripts\calibrar_vazao.py" `
  --configuracoes "2@45,3@30" `
  --repeticoes 5 `
  --tickets-por-repeticao 30 `
  --warmup 2 `
  --concorrencia-ingresso 4 `
  --randomizar-ordem `
  --saida-dir "avaliacao\resultados\calibracao-fila-v3-confirmatoria"
```

Gate B:

- 300 tickets confirmatórios concluídos;
- p95, throughput e espera por tratamento;
- falha, rate limit, timeout, ordem, lease e DLQ contabilizados;
- configuração aprovada por critérios pré-registrados;
- arquivo de calibração aprovado congelado.

Rajadas de 25, 50 e 100 tickets são executadas depois, com a configuração
selecionada, para testar persistência e drenagem sob chegada irregular.

## Fase C — benchmark confirmatório

### Regra de modelo fixo

Cada benchmark congela um único candidato antes da abertura dos resultados. O
candidato local e o comparador atual `SECONDARY=gemini-3.5-flash` são
executados, quando comparados, em `run_id` distintos e ligados ao mesmo
`comparison_group_id`. Não há fallback dentro dessas execuções. Para `LOCAL`,
o bundle precisa estar congelado e elegível para avaliação; sua validação
científica é a saída do holdout, não uma pré-condição circular para produzir as
predições desse holdout. Adaptadores de outros provedores permanecem apenas
para reprodutibilidade histórica e exigem um protocolo comparativo separado se
forem reativados.

Na implementação, o executor grava em `generation_config`:
`ia_execution_mode=BENCHMARK`, `ia_failover_enabled=false`,
`ia_fixed_model_role` e `ia_expected_model`. O WF06 propaga esses campos e o
gateway recusa a chamada se o modelo efetivo divergir. Cada chamada fica em
`ia_tentativas_modelo`; a decisão final só recebe
`elegivel_eficacia_confirmatoria=true` quando houve uma tentativa válida, com o
modelo congelado e sem fallback. A elegibilidade dessa linha para o cálculo não
significa que o resultado agregado já foi auditado ou validado.

Uma tentativa do principal seguida por resposta do secundário ou da
contingência não pode ser registrada como predição do principal. Se isso ocorrer
por indisponibilidade, a tentativa permanece no log operacional, a decisão é
marcada inelegível para aquela análise confirmatória e a execução necessária é
refeita de forma controlada em novo `run_id`.

### C1. Auditar o V3 e preparar a expansão V4

O corpus estrutural existente contém 1.200 tickets:

- 500 episódios pareados, com 200 duplicados e 300 não duplicados difíceis no
  segundo ticket;
- aproximadamente 200 casos classificatórios de fronteira;
- 50 realizações e somente dez núcleos independentes por classe;
- 25 famílias de deduplicação, quatro núcleos narrativos por família e cinco
  realizações por núcleo;
- distratores de outros episódios do mesmo `run_id`.

O artefato `corpus_v3_teste.jsonl` cumpre as contagens e passou pelas validações
estruturais automáticas. Isso autoriza seu uso na validação automatizada desta
etapa, identificada como concordância sintética, mas não sua promoção a
benchmark confirmatório com validade humana. Para essa promoção futura, os
rótulos sintéticos precisam de revisão/adjudicação e os textos precisam da
auditoria descrita abaixo. As cinco realizações de cada núcleo foram separadas
em dez partições físicas; usar um único `run_id` contaminaria a lista de
candidatos com paráfrases do mesmo núcleo.

A auditoria de 15/07/2026 concluiu que o V3 é suficiente para regressão,
integração e estresse, mas insuficiente para precisão de aproximadamente dez
pontos percentuais por classe e para demonstrar o limite inferencial de FN ≤ 2%.
O plano revisado V4.1 prevê, futuramente, 878 chamados gerados a partir de 619
núcleos/episódios realmente novos:

| Estrato | Atual independente | Meta V4.1 | Novos chamados |
|---|---:|---:|---:|
| Classificação | 40 | 400, 100 por classe | 360 |
| Dedup positivo | 40 | 189 | 298 |
| Dedup negativo completo | 48 | 97 | 98 |
| Dedup negativo crítico/insuficiente | 12 | 73 | 122 |
| **Total** | **140** | **759** | **878** |

O corpus planejado terá aproximadamente 2.078 chamados. As 960 realizações
repetidas já existentes permanecem úteis para robustez, mas uma única
realização sorteada por núcleo entra na estimativa primária. Trocar somente a
seed não cria um novo núcleo e não aumenta a amostra de eficácia. Os cálculos,
estratos prioritários e regras de interpretação estão no relatório local
[`auditoria_amostral_v4.md`](auditoria_amostral_v4.md).

O contrato executável desse planejamento é
[`plano_amostral_automatizado_v4.json`](../avaliacao/config/plano_amostral_automatizado_v4.json),
schema `4.1.0`. O arquivo registra metas futuras e critérios de parada; sua
existência não significa que os 878 tickets adicionais tenham sido gerados.

Nenhum caso V4.1 será gerado nesta etapa. O LOCAL será executado nas 200 linhas
positivas do V3 como concordância no corpus fixo, com incerteza agrupada pelos
40 núcleos positivos. Essas linhas não podem ser tratadas como `n=200`
independente; o gate populacional de FN ≤ 2% permanece não demonstrável. Uma
comparação Gemini limitada a aproximadamente 100 linhas positivas é
exploratória e não sustenta esse gate.

### C2. Auditoria prévia reduzida

Os itens abaixo ficam adiados durante a etapa automatizada atual e são
necessários somente se a execução for promovida posteriormente a benchmark
confirmatório com validade humana:

- dupla revisão de todos os templates ambíguos ou de alto risco;
- revisão simples dos templates fáceis;
- segundo especialista em 20% estratificado dos fáceis;
- auditoria cega de aproximadamente 200 textos finais renderizados;
- qualquer erro sistemático reabre toda a família afetada.

### C3. Executar

O executor confirmatório `executar_benchmark_v3.py` descrito em versões
anteriores deste plano **não existe no repositório atual**. Portanto não há um
comando V3 confirmatório executável e essa etapa permanece bloqueada até que o
executor implemente e teste todos os gates G0, A e B. O executor V2 e
`--por-cenario 33` não substituem o desenho congelado.

O script disponível `benchmark_pareado_local_gemini.py` executa comparação
direta LOCAL versus `gemini-3.5-flash`, sem fallback, e pode ser usado apenas
como piloto pareado não confirmatório no corpus de desenvolvimento. Ele exige o
braço LOCAL integralmente válido antes de qualquer chamada remota; confirmações
explícitas de cota ativa, situação de faturamento e janela exclusiva; RPM, TPM e
RPD conferidos no AI Studio; uso padrão de 80% dessas cotas; reserva em janelas
móveis e ledger de 24 horas. Cada unidade possui uma tentativa, sem retry nem
fallback. A primeira falha remota, resposta HTTP não 2xx ou violação de contrato
aborta a execução e preserva um parcial marcado como não comparável. O modo
`--development-paired` é estritamente descritivo e recusa
`--noninferiority-margin`; parciais nunca são completados por seleção de
sobreviventes ou nova tentativa silenciosa.

No corpus reservado, uma margem de não inferioridade somente pode ser avaliada
quando foi definida antes da execução e congelada no dry-run. Além disso, todas
as unidades planejadas precisam ter exatamente uma resposta LOCAL e uma Gemini,
ambas válidas. Qualquer resposta ausente, duplicada, inválida ou pertencente a
uma unidade não planejada bloqueia a inferência e a decisão de não
inferioridade. O resumo ainda preserva três descrições distintas: estabilidade
e códigos de falha por provedor; estimativa de casos completos, identificada
como suscetível a viés de sobrevivência; e um composto operacional conservador,
no qual falha, ausência e abstenção contam como incorreto. Esse composto não
produz decisão de não inferioridade.

O estimando implementado é a diferença de **acurácia geral** LOCAL menos Gemini,
agregando unidades de classificação e deduplicação e contando abstenção como
incorreta. Ele não testa a hipótese de risco crítico H2. Falsos negativos de
duplicidade e manutenção encaminhada incorretamente como OBRA exigem estimandos,
intervalos e critérios estratificados próprios; uma conclusão favorável na
acurácia global não substitui esses gates de segurança.

O futuro executor confirmatório deverá manter idênticos `case_id`, texto e
campos do chamado, snapshot e ordem dos candidatos, prompt canônico, schema,
limiar e fila. Também deverá congelar os seis JSONs V9 efetivamente importados,
helpers/builders, scripts de avaliação, módulos e requisitos de `local_ai`,
manifestos e bundle, registrando SHA-256 individual e agregado. Qualquer mudança
em regra de extração, adaptador, workflow ou modelo exigirá novo manifesto e
novo `run_id`.

O gateway final envia até 20 candidatos na mesma ordem a todos os papéis. No
benchmark pareado, os dois limites são congelados em 20 e o gateway bloqueia
qualquer diferença de IDs, ordem, hash ou política. O relatório inclui
recall@20 da referência e separa falha de recuperação de erro de decisão.

Antes de qualquer execução remota, o preflight deve calcular o limite superior
de chamadas a partir do número de tickets/etapas e compará-lo ao orçamento de
quota aprovado. Se a quota não comportar o corpus inteiro, seleciona-se antes
dos resultados uma subamostra estratificada e pareada, congelada por hash; não
se inicia uma execução integral esperando que a API falhe no meio. Nenhuma
chamada de fallback é incluída para “completar” um modelo remoto avaliado.

### C4. Auditoria posterior

- revisar todos os desacordos modelo–gabarito;
- sortear 150 a 200 aparentes acertos por cenário, risco e confiança;
- separar erro do modelo, erro de referência e caso realmente ambíguo;
- registrar conclusão da auditoria antes de marcar o benchmark como concluído.

Gate C:

- dataset, código, modelo, prompt, schema, limiar e fila congelados;
- um único modelo efetivo por `run_id`, sem substituição silenciosa;
- casos e entradas pareados por `comparison_group_id`, com versões e hashes
  registrados;
- todos os tickets terminais;
- `challenge_only` e métrica global separadas;
- intervalos hierárquicos e deltas pareados gerados;
- auditoria humana concluída;
- relatório e CSVs preservados no diretório do `run_id`.

## Quadro de métricas para o artigo

| Dimensão | Métricas primárias | Métricas de apoio |
|---|---|---|
| Eficácia da duplicidade | FN/FP `challenge_only`, F1, recall@20 da recuperação, referência correta | Métrica global, VPN, precisão, ROC-AUC, AP, Log Loss, Brier |
| Eficácia da classificação | F1 macro, recall/F1 de OBRA, risco-cobertura | Matriz, métricas por classe e cenário |
| Eficiência | intervenções e minutos humanos/100 tickets, custo por decisão automática correta | chamadas, retentativas, tokens, cobertura |
| Desempenho | taxa de falha e p95 ponta a ponta | p50, throughput, espera, rate limit, DLQ |

Na classificação, `TRIAGEM_MANUAL` é uma das quatro classes semânticas cobertas
e entra na matriz de confusão. `ABSTENCAO` é estado operacional distinto: reduz
a cobertura e fica fora da matriz/acurácia seletiva dos casos cobertos. Na
deduplicação, a região 0,07–0,95 da v1.8 também é abstenção; nunca pode ser contada como
“não duplicado”.

## Critérios pré-registrados propostos

- limite superior de 95% do FN `challenge_only` ≤ 2%, porque uma decisão
  automática “não duplicado” não atravessa a confirmação fiscal de
  duplicidade;
- limite superior de 95% do FP `challenge_only` ≤ 5%;
- valor preditivo negativo de deduplicação ≥ 98% e precisão dos alertas de
  possível duplicidade ≥ 90% no ponto operacional congelado;
- limite superior de 95% do risco seletivo ≤ 10%;
- limite inferior de 95% da cobertura automática ≥ 60%;
- limite inferior de 95% do recall de `OBRA` ≥ 90%;
- nenhuma perda ou duplicação de lease observada, com limite superior de
  confiança reportado;
- p95, custo e carga humana dentro dos limites aprovados antes do teste.

## Comparação e decisão sobre modelo próprio

As predições de todos os modelos usam o mesmo teste congelado, os mesmos casos
e as mesmas entradas canônicas. Comparar em execuções exclusivas:

- regra fixa e maioria;
- Jaccard;
- TF-IDF isolado + regressão logística e TF-IDF cosseno;
- candidato híbrido local: TF-IDF + Granite Embedding 97M PyTorch FP32 +
  regressão logística calibrada;
- `gemini-3.5-flash` (`SECONDARY` na configuração operacional, mas executado
  isoladamente no benchmark);
- outros modelos próprios, se futuramente treinados.

O encadeamento operacional `LOCAL → SECONDARY` não participa dessa comparação
como se fosse um único modelo. Ele constitui experimento separado de
disponibilidade/failover, medindo sucesso por etapa, erros, retentativas,
latência adicional, tempo de recuperação e proporção de decisões concluídas
por modelo. Toda troca deve ser explícita e atribuída ao modelo que realmente
produziu a saída. Gemini 2.5, Gemini 3.1 e DeepSeek podem ser preservados em
diagnósticos históricos, mas não integram o caminho ativo nem o comparador
confirmatório atual.

O artigo deve apresentar deltas pareados com intervalo, e não somente rankings
de valores pontuais. A adoção do candidato híbrido local só é recomendada se
os gates estratificados de risco crítico forem satisfeitos e houver ganho
mensurável em custo, latência, privacidade ou estabilidade operacional. A
eventual não inferioridade da acurácia geral calculada pelo piloto pareado não
autoriza, isoladamente, essa adoção.

Se os erros forem explicados principalmente por sala, ativo ou sintoma ausentes,
o resultado favorece modificar o formulário e o catálogo do GLPI. Trocar ou
treinar o modelo não corrige informação que nunca foi fornecida.

## Entregáveis finais

- manifesto congelado do piloto e benchmark;
- rótulos dos especialistas, kappa e adjudicações;
- calibração aprovada de limiar e fila;
- dataset V3 e registro de famílias narrativas;
- predições brutas e normalizadas;
- proveniência por tentativa, modelo efetivo, versões, hashes e motivos de
  failover;
- matriz de confusão e métricas com IC 95%;
- relatório `challenge_only` e global;
- custo, tokens, tempo humano, latência e throughput;
- comparação pareada com baselines e alternativa;
- relatório operacional de disponibilidade/failover separado das matrizes de
  eficácia dos modelos fixos;
- catálogo de erros e limites de validade.
