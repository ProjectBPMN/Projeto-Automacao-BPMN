# Diagnóstico de Acertos da IA

> **INVALIDADO EM 2026-08-26:** este diagnóstico deriva da execução V2 com
> corpus não reproduzível e agrupamento insuficiente das famílias-fonte. Os
> valores permanecem apenas para auditoria histórica e não são evidência de
> desempenho.

## 1. Análise por Classe (Top-3 Candidatos)

### Modelo: `classification__hybrid__granite97m__linear_svm`
- **Macro F1:** 0.9520
- **Acurácia:** 0.9551

| Classe | Precision | Recall | F1-Score |
|---|---|---|---|
| OBRA | 0.9782 | 0.9697 | 0.9739 |
| DEMO | 0.9530 | 0.9691 | 0.9610 |
| SOB_DEMANDA | 0.9570 | 0.9543 | 0.9557 |
| TRIAGEM_MANUAL | 0.9253 | 0.9096 | 0.9174 |


### Modelo: `classification__hybrid__multilingual_e5_small__linear_svm`
- **Macro F1:** 0.9466
- **Acurácia:** 0.9497

| Classe | Precision | Recall | F1-Score |
|---|---|---|---|
| OBRA | 0.9779 | 0.9567 | 0.9672 |
| DEMO | 0.9475 | 0.9635 | 0.9554 |
| SOB_DEMANDA | 0.9540 | 0.9486 | 0.9513 |
| TRIAGEM_MANUAL | 0.9101 | 0.9153 | 0.9127 |


### Modelo: `classification__hybrid__multilingual_minilm_l12__linear_svm`
- **Macro F1:** 0.9460
- **Acurácia:** 0.9515

| Classe | Precision | Recall | F1-Score |
|---|---|---|---|
| OBRA | 0.9573 | 0.9697 | 0.9634 |
| DEMO | 0.9503 | 0.9663 | 0.9582 |
| SOB_DEMANDA | 0.9497 | 0.9714 | 0.9605 |
| TRIAGEM_MANUAL | 0.9500 | 0.8588 | 0.9021 |


## 2. Matrizes de Confusão (Melhor Modelo)

**Melhor Modelo:** `classification__hybrid__granite97m__linear_svm`

| Verdadeiro \ Predito | DEMO | OBRA | SOB_DEMANDA | TRIAGEM_MANUAL |
|---|---|---|---|---|
| **DEMO** | 345 | 5 | 5 | 1 |
| **OBRA** | 7 | 224 | 0 | 0 |
| **SOB_DEMANDA** | 4 | 0 | 334 | 12 |
| **TRIAGEM_MANUAL** | 6 | 0 | 10 | 161 |

## 3. Análise de Padrões de Erro

As classes mais confundidas frequentemente são:

- Verdadeiro **SOB_DEMANDA** classificado como **TRIAGEM_MANUAL**: 12 vezes
- Verdadeiro **TRIAGEM_MANUAL** classificado como **SOB_DEMANDA**: 10 vezes
- Verdadeiro **OBRA** classificado como **DEMO**: 7 vezes
- Verdadeiro **TRIAGEM_MANUAL** classificado como **DEMO**: 6 vezes
- Verdadeiro **DEMO** classificado como **OBRA**: 5 vezes

## 4. Comparação de Representações (Ablação de Embeddings)

| Representação | Média macro_f1 | Máx macro_f1 | Qtd Modelos |
|---|---|---|---|
| embedding | 0.7814 | 0.9244 | 15 |
| hybrid | 0.8709 | 0.9520 | 15 |
| hybrid_metadata | nan | nan | 0 |
| metadata | nan | nan | 0 |
| tfidf | 0.8746 | 0.9296 | 5 |

## 5. Comparação de Classificadores

| Classificador | Representação | Melhor macro_f1 |
|---|---|---|
| linear_svm | hybrid | 0.9520 |
| mlp | hybrid | 0.9414 |
| linear_svm | tfidf | 0.9296 |
| mlp | tfidf | 0.9251 |
| linear_svm | embedding | 0.9244 |
| logistic_regression | tfidf | 0.9227 |
| logistic_regression | hybrid | 0.9154 |
| mlp | embedding | 0.9009 |
| logistic_regression | embedding | 0.8996 |
| xgboost | tfidf | 0.8708 |
| xgboost | hybrid | 0.8705 |
| xgboost | embedding | 0.7621 |
| decision_tree | tfidf | 0.7246 |
| decision_tree | hybrid | 0.7121 |
| decision_tree | embedding | 0.5573 |
| decision_tree | hybrid_metadata | nan |
| decision_tree | metadata | nan |
| linear_svm | hybrid_metadata | nan |
| linear_svm | metadata | nan |
| logistic_regression | hybrid_metadata | nan |
| logistic_regression | metadata | nan |
| mlp | hybrid_metadata | nan |
| mlp | metadata | nan |
| xgboost | hybrid_metadata | nan |
| xgboost | metadata | nan |

## 6. Avaliação de Poder Estatístico

Baseado nos intervalos de confiança de bootstrap (95% CI) do melhor modelo:

- **Macro F1:** 0.9520 (CI: 0.9267 - 0.9711)
- **Largura do CI:** 0.0444
- *Conclusão:* O intervalo de confiança é estreito, indicando que o tamanho do corpus é adequado.

## 7. Importância de Atributos (SHAP)

Análise baseada no `xai.json`:

| Família de Features | Importância Média (Abs SHAP) | Fração |
|---|---|---|
| tfidf_character | 1.2509 | 46.5671% |
| embedding | 0.7183 | 26.7400% |
| tfidf_word | 0.7171 | 26.6928% |

## 8. Separação de Responsabilidades: IA vs Operacional

Segundo dados observados (184 ERRO_IA em 315 decisões no DB):

- **Decisões Totais:** 315
- **Erros Reportados (ERRO_IA):** 184

**Conclusão Analítica:**
A métrica operacional indica uma alta taxa de erro (~58%), enquanto as métricas off-line da IA demonstram uma precisão muito superior. Isso sugere fortemente que as falhas rotuladas como 'ERRO_IA' no sistema são primariamente de natureza operacional (ex: falhas de integração N8N, erros de formatação de payload, parsing de JSON ou interrupção de fluxo), e não falhas de classificação semântica do modelo de IA.
