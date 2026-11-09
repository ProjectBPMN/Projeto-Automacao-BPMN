# Resultados estatísticos e comparações

**Revisão:** 03/09/2026
**Escopo:** desenvolvimento sintético com rótulos-proxy; não confirmatório.

## Conclusão correta

Não há vencedor cientificamente confirmado nem estimativa de eficácia em
chamados institucionais. A rodada V2.1 é reproduzível no escopo classificatório,
mas `development_only=true`, `confirmatory_eligible=false` e nenhum candidato
passou simultaneamente todos os gates. O runtime continua em
`local-hybrid-v1.8.0` por estabilidade de engenharia, não porque a V2.1 tenha
provado que Granite é superior.

## Desenho comparativo executado

A mesma avaliação agrupada comparou:

- representações TF-IDF, embedding e híbrida;
- Granite Embedding 97M Multilingual R2, `multilingual-e5-small` e
  `paraphrase-multilingual-MiniLM-L12-v2`;
- regressão logística, árvore de decisão, SVM linear, MLP e XGBoost;
- 1.114 registros proxy em 111 grupos de dependência-fonte;
- cinco dobras agrupadas, calibração fora de dobra, risco-cobertura,
  bootstrap por grupo e comparações pareadas;
- 35 configurações de classificação, 175 linhas de dobra e 38.990 predições
  OOF.

O validador classificou a rodada como `VALID_PARTIAL_TASK_SCOPE`. A seleção de
deduplicação foi interrompida antes do ajuste porque havia somente 12 famílias
independentes, seis por classe; isso é um gate correto, não um resultado nulo.

## Resultados classificatórios

O primeiro colocado pela regra hierárquica pré-definida foi híbrido + E5 + SVM
linear:

| Métrica proxy | Estimativa | IC95% agrupado |
|---|---:|---:|
| Macro-F1 | 0,7987 | 0,7266–0,8598 |
| Acurácia | 0,8312 | 0,7653–0,8889 |
| Cobertura automática | 0,6086 | 0,5229–0,6895 |
| Risco seletivo | 0,0693 | 0,0229–0,1321 |
| ECE, 10 bins | 0,0449 | — |

Houve zero eventos proxy não-OBRA→OBRA em 64 grupos expostos, mas o limite
superior unilateral de 95% foi 4,57%, acima do gate de 2%. Portanto o status é
`UNDERPOWERED`. Com zero eventos, são necessárias pelo menos 149 exposições
independentes para um limite estritamente inferior a 2%; duas direções
disjuntas podem exigir inicialmente 298 grupos, antes de perdas e efeito de
desenho.

O maior Macro-F1 pontual bruto foi do MLP com embedding E5 isolado (0,8036),
mas sua cobertura automática foi zero sob a política. O SVM com E5 isolado
teve Macro-F1 0,8004, cobertura 0,4767, risco seletivo 0,1111 e um erro crítico
proxy; falhou os gates. Esses exemplos mostram por que escolher somente a maior
acurácia ou Macro-F1 seria metodologicamente incorreto.

Resumo do melhor ponto bruto por família de classificador:

| Classificador | Representação/embedding | Macro-F1 | Acurácia | Cobertura | Risco seletivo | Estado |
|---|---|---:|---:|---:|---:|---|
| Árvore | híbrido/MiniLM | 0,6962 | 0,7136 | 0,0000 | — | FAIL |
| SVM | embedding/E5 | 0,8004 | 0,8339 | 0,4767 | 0,1111 | FAIL |
| Regressão logística | híbrido/E5 | 0,7912 | 0,8232 | 0,5799 | 0,0650 | UNDERPOWERED |
| MLP | embedding/E5 | 0,8036 | 0,8357 | 0,0000 | — | FAIL |
| XGBoost | híbrido/E5 | 0,7493 | 0,7747 | 0,0844 | 0,0638 | FAIL |

## Ablações e embeddings

As comparações pareadas não demonstraram uma superioridade geral do híbrido ou
de um embedding:

- E5 híbrido/logístico versus Granite: Δ Macro-F1 +0,0157; IC95%
  -0,0077 a +0,0408;
- MiniLM versus Granite: Δ -0,0061; IC95% -0,0416 a +0,0248;
- Granite embedding isolado versus híbrido: Δ -0,0668; IC95%
  -0,1331 a -0,0062;
- TF-IDF isolado versus híbrido: Δ -0,0015; IC95% -0,0329 a +0,0255.

Assim, embedding semântico permanece uma hipótese plausível para paráfrases,
enquanto TF-IDF continua baseline obrigatório. Não é válido dizer que Granite,
E5 ou o híbrido “ganhou” de forma confirmatória.

## Recuperação para deduplicação

Em 500 consultas sintéticas derivadas de apenas seis famílias positivas:

| Representação | Recall@1 | Recall@5 | Recall@20 | MRR |
|---|---:|---:|---:|---:|
| TF-IDF | 0,324 | 0,658 | 0,788 | 0,4698 |
| Granite 97M | 0,190 | 0,496 | 0,878 | 0,3396 |
| E5-small | 0,218 | 0,522 | 0,756 | 0,3574 |
| MiniLM-L12 | 0,090 | 0,254 | 0,496 | 0,1730 |

Granite teve o maior Recall@20 e TF-IDF o melhor Recall@1/MRR. As 500 consultas
não são 500 unidades independentes; por isso esses números são descritivos.

## XAI/SHAP

O SHAP teve residual máximo de aditividade de `5,77e-15`. A importância
agregada foi 52,99% TF-IDF de caracteres, 29,64% TF-IDF de palavras e 17,37%
embedding. Isso explica atribuições no classificador analisado e sugere forte
dependência lexical neste corpus; não prova causalidade, justiça ou acerto.

## Três janelas proxy aceleradas

Foram construídas três partições determinísticas, sem sobreposição de grupos,
com 372/371/371 registros e 37 grupos em cada. Todas as sondagens locais e os
checks de drift passaram. Macro-F1 por janela foi 0,7758, 0,7221 e 0,8580; o
risco seletivo foi 0,1391, 0,0177 e 0,0495. A heterogeneidade, especialmente na
primeira janela, desaconselha uma narrativa baseada apenas na média agregada.

Essas janelas não usam chamados reais, não esperam dias e validam apenas o
mecanismo técnico de particionamento/SLO/drift. Elas não estimam disponibilidade
longitudinal nem confirmam correção semântica.

## Telemetria operacional separada

As partições proxy acima não são as janelas temporais do coletor. Em 03/09, o
estado local do monitor acumulava seis janelas intradiárias completas; todas
falharam os SLOs propostos, e as mais recentes acionaram `STOP` por PSI de
confiança. Isso é um resultado operacional negativo válido e não altera as
métricas de classificação. O ponto vivo mais recente via HTTP estava saudável,
mas uma fotografia saudável não apaga as falhas agregadas na janela.

Na carga limitada de 03/09, concorrência 1 obteve 40/40 HTTP 200, enquanto
concorrência 4 obteve 17/40 HTTP 200 e 23/40 HTTP 429. Não houve 5xx. Essa
saturação mede capacidade do serviço local neste host, não qualidade semântica.

## Gemini

Não existe rodada Gemini atual, pareada e conjuntamente válida que permita
comparar qualidade semântica. Rodadas históricas sofreram falhas de cota,
transporte, saldo ou desenho. Falha operacional do provedor não é evidência de
inferioridade semântica. Uma nova comparação remota só pode ser publicada com
os mesmos casos, ordem, prompt, candidatos, política e denominadores, sem
fallback e com cota/janela previamente confirmadas.

## Evidências reproduzíveis

- `avaliacao/resultados/selecao-supervisionada-v2.1-20260826/`;
- `avaliacao/resultados/operacional/janelas-aceleradas-proxy-20260902.json`;
- `avaliacao/resultados/e2e-pipeline-local-v1.8.0-20260903-final.json`;
- `avaliacao/resultados/operacional/carga-classificacao-c1-20260903.json`;
- `avaliacao/resultados/operacional/carga-classificacao-c4-20260903.json`;
- `avaliacao/resultados/operacional/estado-runtime-pos-e2e-20260903.json`;
- `avaliacao/resultados/operacional/varredura-segredos-20260903.json`.

Todos os números desta página são evidência técnica/de desenvolvimento por
proxy. `scientific_ready=false` e `confirmatory_claim_allowed=false` permanecem
obrigatórios.
