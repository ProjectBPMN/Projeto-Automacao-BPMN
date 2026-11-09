# Status auditado da rodada V2.1

**Executada:** 26/08/2026  
**Auditada:** 27/08/2026  
**Conclusão global:** rodada integral não válida; classificação válida apenas
no escopo de desenvolvimento e deduplicação bloqueada por inviabilidade
amostral.

## Integridade

- dataset: `desenvolvimento-local-v2.1.0`;
- SHA-256 do dataset:
  `305e84164d663a19a2e224b2dc8bf08e8d3173bf50bc15c7675f9de553d2de9a`;
- SHA-256 do protocolo:
  `3a58410ecbe440b3a759c2673a9f4de5e9329dcae78e18e7b1d2da6cdda73c3e`;
- fingerprint da execução:
  `6b112d9f1d331c571e47ffbe4e9478813d748a50f1e5536c45d024c336dec211`;
- fontes exatas da execução preservadas em `source_snapshot/`;
- classificação agrupada por `source_dependency_group_sha256`;
- 1.114 registros classificatórios, 111 grupos independentes efetivamente
  usados, 35 configurações, 175 dobras e 38.990 predições OOF;
- validador independente: `VALID_PARTIAL_TASK_SCOPE`, com métricas, ranking,
  2.000 detalhes de recuperação, oito contrastes, 40 objetivos pareados, XAI e
  latência recalculados/verificados.

## Classificação

Nenhum candidato satisfez os limites de confiança do protocolo. Portanto, não
há vencedor qualificado. O candidato provisório pela estimativa pontual foi:

`classification__hybrid__multilingual_e5_small__linear_svm`

| Medida | Estimativa | IC95% agrupado |
|---|---:|---:|
| Macro-F1 | 0,7987 | 0,7266–0,8598 |
| Acurácia | 0,8312 | 0,7653–0,8889 |
| Cobertura automática | 60,86% | 52,29%–68,95% |
| Risco entre decisões automáticas | 6,93% | 2,29%–13,21% |

Esses intervalos são bootstrap agrupado nominal de cada configuração. Como o
candidato provisório foi escolhido exploratoriamente entre 35 configurações,
eles não são intervalos pós-seleção nem foram ajustados para a busca múltipla.
Os oito contrastes pré-especificados usam correção de Holm separadamente; isso
não transforma o candidato de maior estimativa pontual em vencedor inferencial.

### Proveniência da configuração

Esta execução de 2026-08-26 foi congelada com
`avaliacao/config/selecao_modelos_supervisionados_v2.json`, cujo SHA-256 é
`3a58410ecbe440b3a759c2673a9f4de5e9329dcae78e18e7b1d2da6cdda73c3e`.
A configuração posterior
`avaliacao/config/selecao_classificacao_supervisionada_v2_1.json` (protocolo
2.1.1, escopo apenas de classificação) é prospectiva e não é idêntica ao
protocolo desta execução. Ela não deve ser usada para revalidar estes artefatos
congelados.

Foram observados zero encaminhamentos automáticos não-OBRA→OBRA em 64 grupos
expostos, mas o limite superior unilateral de 95% foi 4,57%, acima do gate de
2%. Zero observado não significa risco zero.

Desempenho semântico por classe do candidato provisório:

| Classe | Precisão | Recall | F1 | Suporte |
|---|---:|---:|---:|---:|
| OBRA | 0,8699 | 0,9264 | 0,8973 | 231 |
| DEMO | 0,8141 | 0,8118 | 0,8129 | 356 |
| SOB_DEMANDA | 0,8727 | 0,9600 | 0,9143 | 350 |
| TRIAGEM_MANUAL | 0,6797 | 0,4915 | 0,5705 | 177 |

O recall baixo de `TRIAGEM_MANUAL` é um ponto fraco importante: o corpus
sintético ainda não sustenta confiar que ambiguidade será reconhecida de forma
consistente.

### Comparações que respondem à escolha do embedding

No mesmo classificador logístico híbrido, E5 menos Granite apresentou diferença
de Macro-F1 de +0,0157, mas IC95% pareado agrupado de −0,0077 a +0,0408. MiniLM
menos Granite foi −0,0061, IC95% −0,0416 a +0,0248. Logo, esta rodada não
demonstra superioridade inequívoca de um embedding sobre os demais.

Para Granite + regressão logística, embedding isolado ficou abaixo do híbrido
em −0,0668 de Macro-F1, IC95% −0,1331 a −0,0062. Já TF-IDF isolado menos o
híbrido foi −0,0015, IC95% −0,0329 a +0,0255. Assim, os dados sintéticos
sugerem que o embedding isolado perde informação lexical, mas não demonstram
que o híbrido supera TF-IDF isolado de forma relevante.

Árvore e XGBoost ficaram abaixo da regressão logística no contraste Granite
híbrido. SVM e MLP tiveram estimativas pontuais ligeiramente maiores, porém os
intervalos cruzaram zero. Complexidade adicional não foi justificada de forma
conclusiva.

## Recuperação para deduplicação

As 500 consultas positivas sintéticas produziram:

| Representação | Recall@1 | Recall@5 | Recall@20 | MRR |
|---|---:|---:|---:|---:|
| TF-IDF | 32,4% | 65,8% | 78,8% | 0,4698 |
| Granite 97M | 19,0% | 49,6% | 87,8% | 0,3396 |
| E5 small | 21,8% | 52,2% | 75,6% | 0,3574 |
| MiniLM L12 | 9,0% | 25,4% | 49,6% | 0,1730 |

Granite recuperou mais referências no top-20; TF-IDF foi melhor no topo curto
e no MRR. Esses 500 textos descendem de somente seis famílias positivas, então
os números são diagnósticos descritivos e não uma estimativa institucional.

## Deduplicação supervisionada

As 55 configurações falharam antes do primeiro ajuste. O protocolo exigia, por
classe, cinco grupos para ajuste e quatro para calibração dentro do treino
externo; o corpus possui apenas seis grupos por classe antes da divisão. O
artefato `preflight_viabilidade_pos_auditoria.json` reproduz o bloqueio e mostra
limite superior unilateral de 95% de 39,3% para zero eventos em seis grupos.

Reduzir os mínimos depois de observar a falha produziria um ranking instável e
pós-hoc. A correção adotada foi fail-fast e escopo classificatório explícito. A
correção científica é ampliar famílias independentes, preferencialmente reais
e adjudicadas.

## XAI e desempenho

SHAP explicou o escore-base do candidato provisório com residual máximo de
aditividade `5,77e-15`. A importância absoluta agregada foi 52,99% TF-IDF de
caracteres, 29,64% TF-IDF de palavras e 17,37% embedding. Isso descreve o modelo
ajustado; não prova causalidade nem correção.

Fairness não foi avaliada: o corpus sintético não contém subgrupos
institucionais válidos nem prevalências representativas. Qualquer análise de
disparidade exige atributos autorizados, subgrupos pré-especificados, tamanho
mínimo por grupo e rótulos humanos independentes. A ausência atual desses dados
não pode ser interpretada como ausência de viés.

No benchmark local de 20 registros, o candidato provisório teve p50 de 81,82 ms
e p95 de 105,41 ms para texto bruto até predição-base, com encoder já carregado;
não inclui GLPI, n8n, rede, calibração ou limiar.

## Decisão

- não promover E5 nem alterar `local-hybrid-v1.8.0` por esta rodada;
- não publicar acurácia institucional;
- usar o resultado para orientar coleta de dados, revisão de ambiguidade e novo
  protocolo;
- considerar a rodada integral incompleta, apesar da classificação auditada.
