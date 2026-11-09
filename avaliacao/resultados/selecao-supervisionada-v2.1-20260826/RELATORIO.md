# Seleção comparativa de embeddings e classificadores

> **RODADA PARCIALMENTE VÁLIDA.** As 35 configurações de classificação foram
> concluídas e validadas independentemente, mas as 55 configurações de
> deduplicação são `FAILED` porque as 12 famílias-fonte não comportam a
> separação agrupada exigida. Não interprete este arquivo como seleção integral
> válida. O parecer corrigido está em `STATUS_PARCIAL.md` e a auditoria em
> `validacao_resultados_classification.json`.

> Status: seleção interna no corpus sintético de desenvolvimento. Este relatório não é validação confirmatória nem evidência de eficácia em produção.

## Integridade do protocolo

- dataset: `avaliacao\datasets\desenvolvimento_local_v2.jsonl`;
- SHA-256: `305e84164d663a19a2e224b2dc8bf08e8d3173bf50bc15c7675f9de553d2de9a`;
- registros: 2800;
- classificação agrupada por `source_dependency_group_sha256`;
- deduplicação agrupada por `source_dependency_group_sha256`;
- cinco dobras externas; TF-IDF, modelo e calibração ajustados sem usar a dobra externa;
- `corpus_v3_teste`, primary33 e datasets V2 não foram usados.

## Recuperação semântica

| Representação | Recall@1 | Recall@5 | Recall@20 | MRR | nDCG@20 |
|---|---:|---:|---:|---:|---:|
| granite97m | 19.00% | 49.60% | 87.80% | 0.3396 | 0.4572 |
| tfidf | 32.40% | 65.80% | 78.80% | 0.4698 | 0.5411 |
| multilingual_e5_small | 21.80% | 52.20% | 75.60% | 0.3574 | 0.4434 |
| multilingual_minilm_l12 | 9.00% | 25.40% | 49.60% | 0.1730 | 0.2365 |

## Classificação OBRA/DEMO/SOB_DEMANDA/TRIAGEM_MANUAL

| Rank | Configuração | Evidência | Macro-F1 | Não-OBRA→OBRA | UCB95 por grupo | Cobertura | LCB95 cobertura |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | `classification__hybrid__multilingual_e5_small__linear_svm` | UNDERPOWERED | 0.7987 | 0 | 4.57% | 60.86% | 52.29% |
| 2 | `classification__hybrid__multilingual_e5_small__logistic_regression` | UNDERPOWERED | 0.7912 | 0 | 4.44% | 57.99% | 49.27% |
| 3 | `classification__hybrid__multilingual_minilm_l12__mlp` | UNDERPOWERED | 0.7734 | 0 | 5.70% | 51.53% | 42.71% |
| 4 | `classification__embedding__multilingual_e5_small__mlp` | FAIL | 0.8036 | 0 | n/a | 0.00% | 0.00% |
| 5 | `classification__embedding__multilingual_e5_small__linear_svm` | FAIL | 0.8004 | 1 | 8.34% | 47.67% | 39.45% |
| 6 | `classification__hybrid__granite97m__mlp` | FAIL | 0.7903 | 0 | 7.22% | 40.48% | 31.55% |
| 7 | `classification__hybrid__granite97m__linear_svm` | FAIL | 0.7891 | 4 | 6.89% | 62.03% | 53.59% |
| 8 | `classification__tfidf__none__mlp` | FAIL | 0.7855 | 0 | 20.58% | 12.48% | 6.45% |
| 9 | `classification__tfidf__none__linear_svm` | FAIL | 0.7849 | 4 | 11.60% | 37.16% | 28.33% |
| 10 | `classification__hybrid__multilingual_e5_small__mlp` | FAIL | 0.7822 | 0 | 7.39% | 40.48% | 31.28% |

Nenhum candidato foi qualificado pelos limites de confiança. Candidato provisório pela estimativa pontual: `classification__hybrid__multilingual_e5_small__linear_svm`; não validado.

## Deduplicação

| Rank | Configuração | Evidência | FN automáticos | UCB95 FN por grupo | Custo 5:1 | NPV | Automação integral | Cobertura de decisão |
|---:|---|---|---:|---:|---:|---:|---:|---:|

Nenhum candidato satisfez sequer os gates pontuais.

## XAI

SHAP explica o escore do classificador-base antes da calibração e dos limiares. Ele não prova causalidade e dimensões individuais do embedding não recebem interpretação linguística; por isso as contribuições são também agregadas por família.
- `classification__hybrid__multilingual_e5_small__linear_svm`: COMPLETED (LinearExplainer).

## Desempenho dos finalistas

A tabela mede texto bruto até a predição do classificador-base. O carregamento frio do encoder é separado e os tempos não incluem GLPI, n8n, rede, calibração nem efeitos externos.

| Tarefa | Cenário | Configuração | p50 (ms) | p95 (ms) | itens/s | Pico RSS (MB) |
|---|---|---|---:|---:|---:|---:|
| classification | classification_raw_text | `classification__hybrid__multilingual_e5_small__linear_svm` | 81.82 | 105.41 | 11.91 | 483.6 |
| deduplication | falha | `` | n/a | n/a | n/a | n/a |

### Métricas por classe do candidato classificatório

| Classe | Precisão | Recall | F1 | Suporte |
|---|---:|---:|---:|---:|
| OBRA | 0.8699 | 0.9264 | 0.8973 | 231 |
| DEMO | 0.8141 | 0.8118 | 0.8129 | 356 |
| SOB_DEMANDA | 0.8727 | 0.9600 | 0.9143 | 350 |
| TRIAGEM_MANUAL | 0.6797 | 0.4915 | 0.5705 | 177 |

Motivos de encaminhamento para revisão humana:
- `LOW_CONFIDENCE`: 146 registros.
- `OBRA_BELOW_SAFETY_THRESHOLD`: 162 registros.
- `SEMANTIC_TRIAGE`: 128 registros.

## Falhas

- `deduplication__tfidf__none__logistic_regression`: SelectionGuardError: deduplication__tfidf__none__logistic_regression/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__tfidf__none__decision_tree`: SelectionGuardError: deduplication__tfidf__none__decision_tree/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__tfidf__none__linear_svm`: SelectionGuardError: deduplication__tfidf__none__linear_svm/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__tfidf__none__mlp`: SelectionGuardError: deduplication__tfidf__none__mlp/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__tfidf__none__xgboost`: SelectionGuardError: deduplication__tfidf__none__xgboost/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__embedding__granite97m__logistic_regression`: SelectionGuardError: deduplication__embedding__granite97m__logistic_regression/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__embedding__granite97m__decision_tree`: SelectionGuardError: deduplication__embedding__granite97m__decision_tree/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__embedding__granite97m__linear_svm`: SelectionGuardError: deduplication__embedding__granite97m__linear_svm/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__embedding__granite97m__mlp`: SelectionGuardError: deduplication__embedding__granite97m__mlp/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__embedding__granite97m__xgboost`: SelectionGuardError: deduplication__embedding__granite97m__xgboost/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__embedding__multilingual_e5_small__logistic_regression`: SelectionGuardError: deduplication__embedding__multilingual_e5_small__logistic_regression/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__embedding__multilingual_e5_small__decision_tree`: SelectionGuardError: deduplication__embedding__multilingual_e5_small__decision_tree/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__embedding__multilingual_e5_small__linear_svm`: SelectionGuardError: deduplication__embedding__multilingual_e5_small__linear_svm/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__embedding__multilingual_e5_small__mlp`: SelectionGuardError: deduplication__embedding__multilingual_e5_small__mlp/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__embedding__multilingual_e5_small__xgboost`: SelectionGuardError: deduplication__embedding__multilingual_e5_small__xgboost/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__embedding__multilingual_minilm_l12__logistic_regression`: SelectionGuardError: deduplication__embedding__multilingual_minilm_l12__logistic_regression/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__embedding__multilingual_minilm_l12__decision_tree`: SelectionGuardError: deduplication__embedding__multilingual_minilm_l12__decision_tree/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__embedding__multilingual_minilm_l12__linear_svm`: SelectionGuardError: deduplication__embedding__multilingual_minilm_l12__linear_svm/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__embedding__multilingual_minilm_l12__mlp`: SelectionGuardError: deduplication__embedding__multilingual_minilm_l12__mlp/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__embedding__multilingual_minilm_l12__xgboost`: SelectionGuardError: deduplication__embedding__multilingual_minilm_l12__xgboost/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid__granite97m__logistic_regression`: SelectionGuardError: deduplication__hybrid__granite97m__logistic_regression/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid__granite97m__decision_tree`: SelectionGuardError: deduplication__hybrid__granite97m__decision_tree/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid__granite97m__linear_svm`: SelectionGuardError: deduplication__hybrid__granite97m__linear_svm/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid__granite97m__mlp`: SelectionGuardError: deduplication__hybrid__granite97m__mlp/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid__granite97m__xgboost`: SelectionGuardError: deduplication__hybrid__granite97m__xgboost/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid__multilingual_e5_small__logistic_regression`: SelectionGuardError: deduplication__hybrid__multilingual_e5_small__logistic_regression/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid__multilingual_e5_small__decision_tree`: SelectionGuardError: deduplication__hybrid__multilingual_e5_small__decision_tree/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid__multilingual_e5_small__linear_svm`: SelectionGuardError: deduplication__hybrid__multilingual_e5_small__linear_svm/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid__multilingual_e5_small__mlp`: SelectionGuardError: deduplication__hybrid__multilingual_e5_small__mlp/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid__multilingual_e5_small__xgboost`: SelectionGuardError: deduplication__hybrid__multilingual_e5_small__xgboost/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid__multilingual_minilm_l12__logistic_regression`: SelectionGuardError: deduplication__hybrid__multilingual_minilm_l12__logistic_regression/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid__multilingual_minilm_l12__decision_tree`: SelectionGuardError: deduplication__hybrid__multilingual_minilm_l12__decision_tree/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid__multilingual_minilm_l12__linear_svm`: SelectionGuardError: deduplication__hybrid__multilingual_minilm_l12__linear_svm/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid__multilingual_minilm_l12__mlp`: SelectionGuardError: deduplication__hybrid__multilingual_minilm_l12__mlp/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid__multilingual_minilm_l12__xgboost`: SelectionGuardError: deduplication__hybrid__multilingual_minilm_l12__xgboost/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__metadata__none__logistic_regression`: SelectionGuardError: deduplication__metadata__none__logistic_regression/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__metadata__none__decision_tree`: SelectionGuardError: deduplication__metadata__none__decision_tree/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__metadata__none__linear_svm`: SelectionGuardError: deduplication__metadata__none__linear_svm/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__metadata__none__mlp`: SelectionGuardError: deduplication__metadata__none__mlp/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__metadata__none__xgboost`: SelectionGuardError: deduplication__metadata__none__xgboost/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid_metadata__granite97m__logistic_regression`: SelectionGuardError: deduplication__hybrid_metadata__granite97m__logistic_regression/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid_metadata__granite97m__decision_tree`: SelectionGuardError: deduplication__hybrid_metadata__granite97m__decision_tree/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid_metadata__granite97m__linear_svm`: SelectionGuardError: deduplication__hybrid_metadata__granite97m__linear_svm/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid_metadata__granite97m__mlp`: SelectionGuardError: deduplication__hybrid_metadata__granite97m__mlp/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid_metadata__granite97m__xgboost`: SelectionGuardError: deduplication__hybrid_metadata__granite97m__xgboost/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid_metadata__multilingual_e5_small__logistic_regression`: SelectionGuardError: deduplication__hybrid_metadata__multilingual_e5_small__logistic_regression/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid_metadata__multilingual_e5_small__decision_tree`: SelectionGuardError: deduplication__hybrid_metadata__multilingual_e5_small__decision_tree/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid_metadata__multilingual_e5_small__linear_svm`: SelectionGuardError: deduplication__hybrid_metadata__multilingual_e5_small__linear_svm/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid_metadata__multilingual_e5_small__mlp`: SelectionGuardError: deduplication__hybrid_metadata__multilingual_e5_small__mlp/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid_metadata__multilingual_e5_small__xgboost`: SelectionGuardError: deduplication__hybrid_metadata__multilingual_e5_small__xgboost/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid_metadata__multilingual_minilm_l12__logistic_regression`: SelectionGuardError: deduplication__hybrid_metadata__multilingual_minilm_l12__logistic_regression/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid_metadata__multilingual_minilm_l12__decision_tree`: SelectionGuardError: deduplication__hybrid_metadata__multilingual_minilm_l12__decision_tree/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid_metadata__multilingual_minilm_l12__linear_svm`: SelectionGuardError: deduplication__hybrid_metadata__multilingual_minilm_l12__linear_svm/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid_metadata__multilingual_minilm_l12__mlp`: SelectionGuardError: deduplication__hybrid_metadata__multilingual_minilm_l12__mlp/outer-0: não foi possível separar ajuste e calibração por grupo.
- `deduplication__hybrid_metadata__multilingual_minilm_l12__xgboost`: SelectionGuardError: deduplication__hybrid_metadata__multilingual_minilm_l12__xgboost/outer-0: não foi possível separar ajuste e calibração por grupo.

## Limites da conclusão

- os rótulos são sintéticos e não representam prevalência real;
- os intervalos agrupam variações, mas não substituem holdout institucional;
- a escolha é válida apenas como seleção de desenvolvimento;
- nenhum vencedor ou candidato provisório deve substituir o bundle operacional antes do congelamento e do teste confirmatório;
- ausência de diferença significativa não demonstra equivalência.
