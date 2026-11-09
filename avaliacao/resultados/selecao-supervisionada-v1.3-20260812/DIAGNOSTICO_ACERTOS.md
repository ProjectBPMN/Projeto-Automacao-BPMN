# Diagnóstico de Acertos da IA

## 1. Análise por Classe (Top-3 Candidatos)

### Modelo: `classification__hybrid__multilingual_minilm_l12__mlp`
- **Macro F1:** 0.8028
- **Acurácia:** 0.8504

| Classe | Precision | Recall | F1-Score |
|---|---|---|---|
| OBRA | 0.8514 | 0.9474 | 0.8968 |
| DEMO | 0.8611 | 0.7799 | 0.8185 |
| SOB_DEMANDA | 0.8895 | 0.9684 | 0.9273 |
| TRIAGEM_MANUAL | 0.6591 | 0.5000 | 0.5686 |


### Modelo: `classification__hybrid__granite97m__linear_svm`
- **Macro F1:** 0.8006
- **Acurácia:** 0.8465

| Classe | Precision | Recall | F1-Score |
|---|---|---|---|
| OBRA | 0.8732 | 0.9323 | 0.9018 |
| DEMO | 0.8255 | 0.7736 | 0.7987 |
| SOB_DEMANDA | 0.8851 | 0.9747 | 0.9277 |
| TRIAGEM_MANUAL | 0.6744 | 0.5000 | 0.5743 |


### Modelo: `classification__hybrid__multilingual_minilm_l12__linear_svm`
- **Macro F1:** 0.7920
- **Acurácia:** 0.8425

| Classe | Precision | Recall | F1-Score |
|---|---|---|---|
| OBRA | 0.8552 | 0.9323 | 0.8921 |
| DEMO | 0.8378 | 0.7799 | 0.8078 |
| SOB_DEMANDA | 0.8994 | 0.9620 | 0.9297 |
| TRIAGEM_MANUAL | 0.6087 | 0.4828 | 0.5385 |


## 2. Matrizes de Confusão (Melhor Modelo)

**Melhor Modelo:** `classification__hybrid__multilingual_minilm_l12__mlp`

| Verdadeiro \ Predito | DEMO | OBRA | SOB_DEMANDA | TRIAGEM_MANUAL |
|---|---|---|---|---|
| **DEMO** | 124 | 15 | 7 | 13 |
| **OBRA** | 6 | 126 | 1 | 0 |
| **SOB_DEMANDA** | 2 | 1 | 153 | 2 |
| **TRIAGEM_MANUAL** | 12 | 6 | 11 | 29 |

## 3. Análise de Padrões de Erro

As classes mais confundidas frequentemente são:

- Verdadeiro **DEMO** classificado como **OBRA**: 15 vezes
- Verdadeiro **DEMO** classificado como **TRIAGEM_MANUAL**: 13 vezes
- Verdadeiro **TRIAGEM_MANUAL** classificado como **DEMO**: 12 vezes
- Verdadeiro **TRIAGEM_MANUAL** classificado como **SOB_DEMANDA**: 11 vezes
- Verdadeiro **DEMO** classificado como **SOB_DEMANDA**: 7 vezes

## 4. Comparação de Representações (Ablação de Embeddings)

| Representação | Média macro_f1 | Máx macro_f1 | Qtd Modelos |
|---|---|---|---|
| embedding | 0.5933 | 0.7201 | 15 |
| hybrid | 0.6980 | 0.8028 | 15 |
| hybrid_metadata | nan | nan | 0 |
| metadata | nan | nan | 0 |
| tfidf | 0.6813 | 0.7828 | 5 |

## 5. Comparação de Classificadores

| Classificador | Representação | Melhor macro_f1 |
|---|---|---|
| mlp | hybrid | 0.8028 |
| linear_svm | hybrid | 0.8006 |
| linear_svm | tfidf | 0.7828 |
| logistic_regression | hybrid | 0.7804 |
| mlp | tfidf | 0.7593 |
| logistic_regression | tfidf | 0.7592 |
| linear_svm | embedding | 0.7201 |
| mlp | embedding | 0.6970 |
| logistic_regression | embedding | 0.6959 |
| xgboost | hybrid | 0.6200 |
| decision_tree | hybrid | 0.5686 |
| xgboost | tfidf | 0.5635 |
| xgboost | embedding | 0.5535 |
| decision_tree | tfidf | 0.5414 |
| decision_tree | embedding | 0.4147 |
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

- **Macro F1:** 0.8028 (CI: 0.7273 - 0.8620)
- **Largura do CI:** 0.1347
- *Conclusão:* O intervalo de confiança é relativamente amplo. O corpus pode precisar de mais amostras para confirmar a superioridade com alta confiança estatística.

## 7. Importância de Atributos (SHAP)

Análise baseada no `xai.json`:

| Família de Features | Importância Média (Abs SHAP) | Fração |
|---|---|---|
| tfidf_character | 1.0608 | 44.9430% |
| embedding | 0.6600 | 27.9616% |
| tfidf_word | 0.6396 | 27.0955% |

## 8. Separação de Responsabilidades: IA vs Operacional

Segundo dados observados (184 ERRO_IA em 315 decisões no DB):

- **Decisões Totais:** 315
- **Erros Reportados (ERRO_IA):** 184

**Conclusão Analítica:**
A métrica operacional indica uma alta taxa de erro (~58%), enquanto as métricas off-line da IA demonstram uma precisão muito superior. Isso sugere fortemente que as falhas rotuladas como 'ERRO_IA' no sistema são primariamente de natureza operacional (ex: falhas de integração N8N, erros de formatação de payload, parsing de JSON ou interrupção de fluxo), e não falhas de classificação semântica do modelo de IA.