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

## Classificação OBRA/DEMO/SOB_DEMANDA

| Rank | Configuração | Elegível | Macro-F1 | Não-OBRA→OBRA automática | Cobertura |
|---:|---|---|---:|---:|---:|
| 1 | `classification__tfidf__none__logistic_regression` | não | 0.8148 | 0 | 49.80% |

Nenhum candidato satisfez todos os gates operacionais.

## Deduplicação

| Rank | Configuração | Elegível | FN automáticos | Custo 5:1 | NPV | Automação integral | Cobertura de decisão |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | `deduplication__tfidf__none__logistic_regression` | sim | 0 | 0.00 | 1.0000 | 50.00% | 100.00% |

Vencedor interno pelo critério hierárquico: `deduplication__tfidf__none__logistic_regression`.

## XAI

SHAP explica o escore do classificador-base antes da calibração e dos limiares. Ele não prova causalidade e dimensões individuais do embedding não recebem interpretação linguística; por isso as contribuições são também agregadas por família.

## Limites da conclusão

- os rótulos são sintéticos e não representam prevalência real;
- os intervalos agrupam variações, mas não substituem holdout institucional;
- a escolha é válida apenas como seleção de desenvolvimento;
- o vencedor não deve substituir o bundle operacional antes do congelamento e do teste confirmatório;
- ausência de diferença significativa não demonstra equivalência.
