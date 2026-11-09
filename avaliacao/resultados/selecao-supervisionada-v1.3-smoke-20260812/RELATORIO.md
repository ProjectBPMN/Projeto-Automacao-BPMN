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
| tfidf | 35.33% | 72.67% | 79.67% | 0.4991 | 0.5642 |

## Classificação OBRA/DEMO/SOB_DEMANDA/TRIAGEM_MANUAL

| Rank | Configuração | Evidência | Macro-F1 | Não-OBRA→OBRA | UCB95 por grupo | Cobertura | LCB95 cobertura |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | `classification__hybrid__granite97m__logistic_regression` | FAIL | 0.7804 | 1 | 8.80% | 52.56% | 44.07% |
| 2 | `classification__tfidf__none__logistic_regression` | FAIL | 0.7592 | 1 | 9.32% | 44.69% | 36.14% |
| 3 | `classification__embedding__granite97m__logistic_regression` | FAIL | 0.6619 | 0 | 12.21% | 18.90% | 12.04% |

Nenhum candidato satisfez sequer os gates pontuais.

## Deduplicação

| Rank | Configuração | Evidência | FN automáticos | UCB95 FN por grupo | Custo 5:1 | NPV | Automação integral | Cobertura de decisão |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 1 | `deduplication__tfidf__none__logistic_regression` | UNDERPOWERED | 0 | 4.87% | 0.00 | 1.0000 | 50.00% | 100.00% |
| 2 | `deduplication__hybrid_metadata__granite97m__logistic_regression` | UNDERPOWERED | 0 | 4.87% | 0.00 | 1.0000 | 50.00% | 100.00% |
| 3 | `deduplication__hybrid__granite97m__logistic_regression` | UNDERPOWERED | 0 | 4.87% | 0.00 | 1.0000 | 50.00% | 100.00% |
| 4 | `deduplication__embedding__granite97m__logistic_regression` | UNDERPOWERED | 3 | 10.12% | 19.00 | 0.9897 | 48.50% | 97.00% |
| 5 | `deduplication__metadata__none__logistic_regression` | FAIL | 0 | 4.87% | 0.00 | 0.0000 | 0.00% | 0.00% |

Nenhum candidato foi qualificado pelos limites de confiança. Candidato provisório pela estimativa pontual: `deduplication__tfidf__none__logistic_regression`; não validado.

## XAI

SHAP explica o escore do classificador-base antes da calibração e dos limiares. Ele não prova causalidade e dimensões individuais do embedding não recebem interpretação linguística; por isso as contribuições são também agregadas por família.

## Limites da conclusão

- os rótulos são sintéticos e não representam prevalência real;
- os intervalos agrupam variações, mas não substituem holdout institucional;
- a escolha é válida apenas como seleção de desenvolvimento;
- o vencedor não deve substituir o bundle operacional antes do congelamento e do teste confirmatório;
- ausência de diferença significativa não demonstra equivalência.
