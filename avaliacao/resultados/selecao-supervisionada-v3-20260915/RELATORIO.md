# Seleção comparativa de embeddings e classificadores

> Status: seleção interna no corpus sintético de desenvolvimento. Este relatório não é validação confirmatória nem evidência de eficácia em produção.

## Integridade do protocolo

- dataset: `avaliacao\datasets\semantico_v3\desenvolvimento_semantico_v3_1.jsonl`;
- SHA-256: `437e516f6d198927817a9fb2dd730105e7814958c37656f864f35b90d9ac4bbb`;
- registros: 1516;
- classificação agrupada por `source_dependency_group_sha256`;
- deduplicação agrupada por `source_dependency_group_sha256`;
- dobras externas agrupadas; TF-IDF, modelo e calibração ajustados sem usar a dobra externa;
- tarefas executadas: classification, deduplication;
- `corpus_v3_teste`, primary33 e datasets V2 não foram usados.

## Recuperação semântica

| Representação | Recall@1 | Recall@5 | Recall@20 | MRR | nDCG@20 |
|---|---:|---:|---:|---:|---:|
| tfidf | 100.00% | 100.00% | 100.00% | 1.0000 | 1.0000 |
| multilingual_e5_small | 97.31% | 100.00% | 100.00% | 0.9866 | 0.9901 |

## Classificação OBRA/DEMO/SOB_DEMANDA/TRIAGEM_MANUAL

| Rank | Configuração | Evidência | Macro-F1 | Não-OBRA→OBRA | UCB95 por grupo | Cobertura | LCB95 cobertura |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | `classification__hybrid__multilingual_e5_small__mlp` | UNDERPOWERED | 0.9867 | 0 | 7.22% | 88.84% | 82.30% |
| 2 | `classification__hybrid__multilingual_e5_small__logistic_regression` | UNDERPOWERED | 0.9691 | 0 | 7.22% | 88.84% | 82.30% |
| 3 | `classification__hybrid__multilingual_e5_small__linear_svm` | UNDERPOWERED | 0.9691 | 0 | 7.22% | 88.62% | 82.06% |
| 4 | `classification__hybrid__multilingual_e5_small__xgboost` | UNDERPOWERED | 0.9624 | 0 | 7.05% | 88.84% | 83.24% |
| 5 | `classification__hybrid__multilingual_e5_small__decision_tree` | FAIL | 0.8827 | 0 | 8.68% | 68.53% | 58.15% |

Nenhum candidato foi qualificado pelos limites de confiança. Candidato provisório pela estimativa pontual: `classification__hybrid__multilingual_e5_small__mlp`; não validado.

## Deduplicação

| Rank | Configuração | Evidência | FN automáticos | UCB95 FN por grupo | Custo 5:1 | NPV | Automação integral | Cobertura de decisão |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 1 | `deduplication__hybrid_metadata__multilingual_e5_small__logistic_regression` | UNDERPOWERED | 0 | 9.21% | 0.00 | 1.0000 | 48.04% | 100.00% |
| 2 | `deduplication__hybrid_metadata__multilingual_e5_small__linear_svm` | UNDERPOWERED | 0 | 9.21% | 0.00 | 1.0000 | 48.04% | 100.00% |
| 3 | `deduplication__hybrid_metadata__multilingual_e5_small__mlp` | UNDERPOWERED | 0 | 9.21% | 0.00 | 1.0000 | 48.04% | 100.00% |
| 4 | `deduplication__hybrid_metadata__multilingual_e5_small__xgboost` | UNDERPOWERED | 0 | 9.21% | 4.00 | 1.0000 | 44.41% | 91.34% |
| 5 | `deduplication__hybrid_metadata__multilingual_e5_small__decision_tree` | FAIL | 7 | 23.15% | 36.00 | 0.7500 | 7.82% | 16.20% |

Nenhum candidato foi qualificado pelos limites de confiança. Candidato provisório pela estimativa pontual: `deduplication__hybrid_metadata__multilingual_e5_small__logistic_regression`; não validado.

## XAI

SHAP explica o escore do classificador-base antes da calibração e dos limiares. Ele não prova causalidade e dimensões individuais do embedding não recebem interpretação linguística; por isso as contribuições são também agregadas por família.
- `classification__hybrid__multilingual_e5_small__mlp`: COMPLETED_FALLBACK (GroupedPermutationImportance).
- `deduplication__hybrid_metadata__multilingual_e5_small__logistic_regression`: COMPLETED (LinearExplainer).

## Desempenho dos finalistas

A tabela mede texto bruto até a predição do classificador-base. O carregamento frio do encoder é separado e os tempos não incluem GLPI, n8n, rede, calibração nem efeitos externos.

| Tarefa | Cenário | Configuração | p50 (ms) | p95 (ms) | itens/s | Pico RSS (MB) |
|---|---|---|---:|---:|---:|---:|
| classification | classification_raw_text | `classification__hybrid__multilingual_e5_small__mlp` | 70.31 | 84.83 | 14.01 | 450.5 |
| deduplication | deduplication_reference_embedding_cached | `deduplication__hybrid_metadata__multilingual_e5_small__logistic_regression` | 109.72 | 164.78 | 8.72 | 655.9 |
| deduplication | deduplication_no_embedding_cache | `deduplication__hybrid_metadata__multilingual_e5_small__logistic_regression` | 161.97 | 217.01 | 6.29 | 659.0 |

### Métricas por classe do candidato classificatório

| Classe | Precisão | Recall | F1 | Suporte |
|---|---:|---:|---:|---:|
| OBRA | 1.0000 | 1.0000 | 1.0000 | 80 |
| DEMO | 0.9756 | 1.0000 | 0.9877 | 200 |
| SOB_DEMANDA | 1.0000 | 0.9833 | 0.9916 | 120 |
| TRIAGEM_MANUAL | 1.0000 | 0.9375 | 0.9677 | 48 |

Motivos de encaminhamento para revisão humana:
- `LOW_CONFIDENCE`: 5 registros.
- `SEMANTIC_TRIAGE`: 45 registros.

## Limites da conclusão

- os rótulos são sintéticos e não representam prevalência real;
- os intervalos agrupam variações, mas não substituem holdout institucional;
- a escolha é válida apenas como seleção de desenvolvimento;
- nenhum vencedor ou candidato provisório deve substituir o bundle operacional antes do congelamento e do teste confirmatório;
- ausência de diferença significativa não demonstra equivalência.
