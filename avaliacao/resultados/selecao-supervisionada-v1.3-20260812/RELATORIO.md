# Seleção comparativa de embeddings e classificadores

> Status: seleção interna no corpus sintético de desenvolvimento. Este relatório não é validação confirmatória nem evidência de eficácia em produção.

## Integridade do protocolo

- dataset: `avaliacao\datasets\desenvolvimento_local_v1.jsonl`;
- SHA-256: `0de50381c0dfaefeb1a940cd697f9c9a8e87b5efee9252a1f4ca43c9d904f204`;
- registros: 1360;
- classificação agrupada por `narrative_core_sha256`;
- deduplicação agrupada por `episode_id`;
- cinco dobras externas; TF-IDF, modelo e calibração ajustados sem usar a dobra externa;
- `corpus_v3_teste`, primary33 e datasets V2 não foram usados.

## Recuperação semântica

| Representação | Recall@1 | Recall@5 | Recall@20 | MRR | nDCG@20 |
|---|---:|---:|---:|---:|---:|
| granite97m | 24.00% | 65.33% | 94.67% | 0.4206 | 0.5404 |
| multilingual_e5_small | 29.00% | 61.00% | 84.33% | 0.4382 | 0.5268 |
| tfidf | 35.33% | 72.67% | 79.67% | 0.4991 | 0.5642 |
| multilingual_minilm_l12 | 11.67% | 29.00% | 57.67% | 0.2164 | 0.2886 |

## Classificação OBRA/DEMO/SOB_DEMANDA/TRIAGEM_MANUAL

| Rank | Configuração | Evidência | Macro-F1 | Não-OBRA→OBRA | UCB95 por grupo | Cobertura | LCB95 cobertura |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | `classification__hybrid__granite97m__linear_svm` | UNDERPOWERED | 0.8006 | 0 | 5.93% | 58.07% | 49.20% |
| 2 | `classification__hybrid__multilingual_minilm_l12__linear_svm` | UNDERPOWERED | 0.7920 | 0 | 6.58% | 54.53% | 45.40% |
| 3 | `classification__hybrid__multilingual_minilm_l12__logistic_regression` | UNDERPOWERED | 0.7448 | 0 | 6.18% | 53.35% | 44.75% |
| 4 | `classification__hybrid__multilingual_minilm_l12__mlp` | FAIL | 0.8028 | 2 | 12.80% | 54.92% | 46.35% |
| 5 | `classification__hybrid__multilingual_e5_small__linear_svm` | FAIL | 0.7877 | 0 | 7.98% | 38.19% | 29.55% |
| 6 | `classification__tfidf__none__linear_svm` | FAIL | 0.7828 | 0 | 7.78% | 36.61% | 28.42% |
| 7 | `classification__hybrid__granite97m__logistic_regression` | FAIL | 0.7804 | 1 | 8.80% | 52.56% | 44.07% |
| 8 | `classification__hybrid__granite97m__mlp` | FAIL | 0.7708 | 1 | 11.89% | 42.72% | 33.66% |
| 9 | `classification__hybrid__multilingual_e5_small__logistic_regression` | FAIL | 0.7627 | 0 | 6.05% | 47.83% | 38.85% |
| 10 | `classification__hybrid__multilingual_e5_small__mlp` | FAIL | 0.7602 | 0 | 6.18% | 49.02% | 40.24% |

Nenhum candidato foi qualificado pelos limites de confiança. Candidato provisório pela estimativa pontual: `classification__hybrid__granite97m__linear_svm`; não validado.

## Deduplicação

| Rank | Configuração | Evidência | FN automáticos | UCB95 FN por grupo | Custo 5:1 | NPV | Automação integral | Cobertura de decisão |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 1 | `deduplication__hybrid__granite97m__logistic_regression` | UNDERPOWERED | 0 | 4.87% | 0.00 | 1.0000 | 50.00% | 100.00% |
| 2 | `deduplication__hybrid__multilingual_minilm_l12__logistic_regression` | UNDERPOWERED | 0 | 4.87% | 0.00 | 1.0000 | 50.00% | 100.00% |
| 3 | `deduplication__hybrid__multilingual_e5_small__logistic_regression` | UNDERPOWERED | 0 | 4.87% | 0.00 | 1.0000 | 50.00% | 100.00% |
| 4 | `deduplication__hybrid_metadata__multilingual_minilm_l12__logistic_regression` | UNDERPOWERED | 0 | 4.87% | 0.00 | 1.0000 | 50.00% | 100.00% |
| 5 | `deduplication__hybrid_metadata__granite97m__logistic_regression` | UNDERPOWERED | 0 | 4.87% | 0.00 | 1.0000 | 50.00% | 100.00% |
| 6 | `deduplication__hybrid_metadata__multilingual_e5_small__logistic_regression` | UNDERPOWERED | 0 | 4.87% | 0.00 | 1.0000 | 50.00% | 100.00% |
| 7 | `deduplication__hybrid__multilingual_minilm_l12__linear_svm` | UNDERPOWERED | 0 | 4.87% | 0.00 | 1.0000 | 50.00% | 100.00% |
| 8 | `deduplication__hybrid__multilingual_e5_small__linear_svm` | UNDERPOWERED | 0 | 4.87% | 0.00 | 1.0000 | 50.00% | 100.00% |
| 9 | `deduplication__hybrid__granite97m__linear_svm` | UNDERPOWERED | 0 | 4.87% | 0.00 | 1.0000 | 50.00% | 100.00% |
| 10 | `deduplication__hybrid_metadata__multilingual_minilm_l12__linear_svm` | UNDERPOWERED | 0 | 4.87% | 0.00 | 1.0000 | 50.00% | 100.00% |

Nenhum candidato foi qualificado pelos limites de confiança. Candidato provisório pela estimativa pontual: `deduplication__hybrid__granite97m__logistic_regression`; não validado.

## XAI

SHAP explica o escore do classificador-base antes da calibração e dos limiares. Ele não prova causalidade e dimensões individuais do embedding não recebem interpretação linguística; por isso as contribuições são também agregadas por família.
- `classification__hybrid__granite97m__linear_svm`: COMPLETED (LinearExplainer).
- `deduplication__hybrid__granite97m__logistic_regression`: COMPLETED (LinearExplainer).

## Desempenho dos finalistas

A tabela mede texto bruto até a predição do classificador-base. O carregamento frio do encoder é separado e os tempos não incluem GLPI, n8n, rede, calibração nem efeitos externos.

| Tarefa | Cenário | Configuração | p50 (ms) | p95 (ms) | itens/s | Pico RSS (MB) |
|---|---|---|---:|---:|---:|---:|
| classification | classification_raw_text | `classification__hybrid__granite97m__linear_svm` | 115.21 | 135.32 | 9.21 | 925.2 |
| deduplication | deduplication_reference_embedding_cached | `deduplication__hybrid__granite97m__logistic_regression` | 95.74 | 115.58 | 10.32 | 932.5 |
| deduplication | deduplication_no_embedding_cache | `deduplication__hybrid__granite97m__logistic_regression` | 140.53 | 187.38 | 6.87 | 935.4 |

### Métricas por classe do candidato classificatório

| Classe | Precisão | Recall | F1 | Suporte |
|---|---:|---:|---:|---:|
| OBRA | 0.8732 | 0.9323 | 0.9018 | 133 |
| DEMO | 0.8255 | 0.7736 | 0.7987 | 159 |
| SOB_DEMANDA | 0.8851 | 0.9747 | 0.9277 | 158 |
| TRIAGEM_MANUAL | 0.6744 | 0.5000 | 0.5743 | 58 |

Motivos de encaminhamento para revisão humana:
- `LOW_CONFIDENCE`: 37 registros.
- `NO_ELIGIBLE_POLICY`: 93 registros.
- `OBRA_BELOW_SAFETY_THRESHOLD`: 41 registros.
- `SEMANTIC_TRIAGE`: 42 registros.

## Limites da conclusão

- os rótulos são sintéticos e não representam prevalência real;
- os intervalos agrupam variações, mas não substituem holdout institucional;
- a escolha é válida apenas como seleção de desenvolvimento;
- o vencedor não deve substituir o bundle operacional antes do congelamento e do teste confirmatório;
- ausência de diferença significativa não demonstra equivalência.
