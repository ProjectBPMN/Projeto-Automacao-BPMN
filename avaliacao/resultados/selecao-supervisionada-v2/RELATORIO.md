# Seleção comparativa de embeddings e classificadores

> **RESULTADO INVALIDADO EM 2026-08-26.** O corpus congelado desta execução
> (`620a...`) não corresponde ao corpus versionado/regerável e o protocolo
> separava, entre dobras, paráfrases e episódios produzidos pelas mesmas
> famílias-fonte. Isso viola a independência exigida para interpretar os
> intervalos por grupo. As tabelas abaixo são mantidas somente como trilha de
> auditoria; seus números não podem justificar escolha de modelo, desempenho em
> produção ou afirmação científica. Consulte `INVALIDADO.md`.

> Status: seleção interna no corpus sintético de desenvolvimento. Este relatório não é validação confirmatória nem evidência de eficácia em produção.

## Integridade do protocolo

- dataset: `avaliacao\datasets\desenvolvimento_local_v2.jsonl`;
- SHA-256: `620a2004ace1b2fb86673d753e967083539775d82ad417046ea1dd8510b80219`;
- registros: 2800;
- classificação agrupada por `narrative_core_sha256`;
- deduplicação agrupada por `episode_id`;
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
| 1 | `classification__hybrid__granite97m__linear_svm` | UNDERPOWERED | 0.9520 | 0 | 2.30% | 69.03% | 63.22% |
| 2 | `classification__hybrid__multilingual_e5_small__linear_svm` | UNDERPOWERED | 0.9466 | 0 | 2.26% | 69.84% | 64.07% |
| 3 | `classification__hybrid__multilingual_minilm_l12__linear_svm` | UNDERPOWERED | 0.9460 | 0 | 2.28% | 70.92% | 65.19% |
| 4 | `classification__hybrid__multilingual_minilm_l12__mlp` | UNDERPOWERED | 0.9414 | 0 | 2.23% | 76.30% | 70.68% |
| 5 | `classification__hybrid__granite97m__mlp` | UNDERPOWERED | 0.9383 | 0 | 2.26% | 73.79% | 68.01% |
| 6 | `classification__hybrid__multilingual_e5_small__mlp` | UNDERPOWERED | 0.9361 | 0 | 2.30% | 71.81% | 66.03% |
| 7 | `classification__tfidf__none__linear_svm` | UNDERPOWERED | 0.9296 | 0 | 2.45% | 65.89% | 60.00% |
| 8 | `classification__tfidf__none__mlp` | UNDERPOWERED | 0.9251 | 0 | 2.30% | 71.45% | 65.77% |
| 9 | `classification__tfidf__none__logistic_regression` | UNDERPOWERED | 0.9227 | 0 | 2.30% | 67.06% | 61.31% |
| 10 | `classification__hybrid__granite97m__logistic_regression` | UNDERPOWERED | 0.9154 | 0 | 2.33% | 67.77% | 61.83% |

Nenhum candidato foi qualificado pelos limites de confiança. Candidato provisório pela estimativa pontual: `classification__hybrid__granite97m__linear_svm`; não validado.

## Deduplicação

| Rank | Configuração | Evidência | FN automáticos | UCB95 FN por grupo | Custo 5:1 | NPV | Automação integral | Cobertura de decisão |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 1 | `deduplication__tfidf__none__logistic_regression` | UNDERPOWERED | 0 | 2.95% | 0.00 | 1.0000 | 50.00% | 100.00% |
| 2 | `deduplication__tfidf__none__linear_svm` | UNDERPOWERED | 0 | 2.95% | 0.00 | 1.0000 | 50.00% | 100.00% |
| 3 | `deduplication__hybrid__multilingual_minilm_l12__logistic_regression` | UNDERPOWERED | 0 | 2.95% | 0.00 | 1.0000 | 50.00% | 100.00% |
| 4 | `deduplication__hybrid_metadata__granite97m__logistic_regression` | UNDERPOWERED | 0 | 2.95% | 0.00 | 1.0000 | 50.00% | 100.00% |
| 5 | `deduplication__hybrid__granite97m__logistic_regression` | UNDERPOWERED | 0 | 2.95% | 0.00 | 1.0000 | 50.00% | 100.00% |
| 6 | `deduplication__hybrid_metadata__multilingual_e5_small__logistic_regression` | UNDERPOWERED | 0 | 2.95% | 0.00 | 1.0000 | 50.00% | 100.00% |
| 7 | `deduplication__hybrid_metadata__multilingual_minilm_l12__logistic_regression` | UNDERPOWERED | 0 | 2.95% | 0.00 | 1.0000 | 50.00% | 100.00% |
| 8 | `deduplication__hybrid__multilingual_minilm_l12__linear_svm` | UNDERPOWERED | 0 | 2.95% | 0.00 | 1.0000 | 50.00% | 100.00% |
| 9 | `deduplication__hybrid__multilingual_e5_small__logistic_regression` | UNDERPOWERED | 0 | 2.95% | 0.00 | 1.0000 | 50.00% | 100.00% |
| 10 | `deduplication__hybrid__multilingual_e5_small__linear_svm` | UNDERPOWERED | 0 | 2.95% | 0.00 | 1.0000 | 50.00% | 100.00% |

Nenhum candidato foi qualificado pelos limites de confiança. Candidato provisório pela estimativa pontual: `deduplication__tfidf__none__logistic_regression`; não validado.

## XAI

SHAP explica o escore do classificador-base antes da calibração e dos limiares. Ele não prova causalidade e dimensões individuais do embedding não recebem interpretação linguística; por isso as contribuições são também agregadas por família.
- `classification__hybrid__granite97m__linear_svm`: COMPLETED (LinearExplainer).
- `deduplication__tfidf__none__logistic_regression`: COMPLETED (LinearExplainer).

## Desempenho dos finalistas

A tabela mede texto bruto até a predição do classificador-base. O carregamento frio do encoder é separado e os tempos não incluem GLPI, n8n, rede, calibração nem efeitos externos.

| Tarefa | Cenário | Configuração | p50 (ms) | p95 (ms) | itens/s | Pico RSS (MB) |
|---|---|---|---:|---:|---:|---:|
| classification | classification_raw_text | `classification__hybrid__granite97m__linear_svm` | 143.96 | 242.86 | 6.51 | 969.7 |
| deduplication | deduplication_raw_text_tfidf | `deduplication__tfidf__none__logistic_regression` | 9.32 | 15.39 | 98.54 | 682.3 |

### Métricas por classe do candidato classificatório

| Classe | Precisão | Recall | F1 | Suporte |
|---|---:|---:|---:|---:|
| OBRA | 0.9782 | 0.9697 | 0.9739 | 231 |
| DEMO | 0.9530 | 0.9691 | 0.9610 | 356 |
| SOB_DEMANDA | 0.9570 | 0.9543 | 0.9557 | 350 |
| TRIAGEM_MANUAL | 0.9253 | 0.9096 | 0.9174 | 177 |

Motivos de encaminhamento para revisão humana:
- `LOW_CONFIDENCE`: 115 registros.
- `OBRA_BELOW_SAFETY_THRESHOLD`: 56 registros.
- `SEMANTIC_TRIAGE`: 174 registros.

## Limites da conclusão

- os rótulos são sintéticos e não representam prevalência real;
- os intervalos agrupam variações, mas não substituem holdout institucional;
- a escolha é válida apenas como seleção de desenvolvimento;
- o vencedor não deve substituir o bundle operacional antes do congelamento e do teste confirmatório;
- ausência de diferença significativa não demonstra equivalência.
