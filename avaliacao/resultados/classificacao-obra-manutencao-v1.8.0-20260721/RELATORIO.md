# Classificacao OBRA, DEMO e SOB_DEMANDA — modelo local v1.8

## Conclusao

A classificacao foi avaliada, mas o resultado ainda e **descritivo de desenvolvimento**, nao confirmatorio. No subconjunto com gabarito acionavel (OBRA, DEMO ou SOB_DEMANDA), o sistema automatizou 400/480 casos (83.33%) e acertou todos os casos automatizados. Os demais seguiram para revisao humana.

O erro de maior risco — classificar manutencao como OBRA — ocorreu **0 vez(es)** no subconjunto automatizado. Esse zero observado nao prova risco zero em producao.

## Resultados hierarquicos

| Etapa | Casos | Automatizados | Revisao humana | Cobertura automatica | Acuracia seletiva |
|---|---:|---:|---:|---:|---:|
| OBRA vs MANUTENCAO | 480 | 400 | 80 | 83.33% | 100.00% |
| DEMO vs SOB_DEMANDA | 320 | 299 | 21 | 93.44% | 100.00% |

### OBRA versus MANUTENCAO

| Gabarito | OBRA | MANUTENCAO | Revisao humana | Total |
|---|---:|---:|---:|---:|
| OBRA | 101 | 0 | 59 | 160 |
| MANUTENCAO | 0 | 299 | 21 | 320 |

- Manutencao enviada automaticamente como OBRA: 0/320. 
- OBRA enviada automaticamente como manutencao: 0/160. 
- Cobertura automatica de OBRA: 101/160 (63.12%).
- Cobertura automatica de manutencao: 299/320 (93.44%).

### DEMO versus SOB_DEMANDA

| Gabarito | DEMO | SOB_DEMANDA | Revisao humana | Total |
|---|---:|---:|---:|---:|
| DEMO | 144 | 0 | 16 | 160 |
| SOB_DEMANDA | 0 | 155 | 5 | 160 |

Nao houve troca automatica DEMO→SOB_DEMANDA (0) nem SOB_DEMANDA→DEMO (0) nesse conjunto.

## Leitura completa de quatro classes

Foram processados 640/640 registros validos, sem falha de contrato. Houve 182 abstencoes operacionais e 239 encaminhamentos humanos. A cobertura semantica foi 458/640 (71.56%), com acuracia seletiva de 99.56%. A automacao direta, sem rota humana, foi 401/640 (62.66%).

A matriz de quatro classes registra 2 divergencias semanticas em casos cobertos. Entre as rotas diretas houve 1 erro: TRIAGEM_MANUAL→SOB_DEMANDA. Esse caso nao e manutencao→OBRA, mas impede afirmar perfeicao global.

Latencia da classificacao no computador de teste: media 141.911 ms, mediana 159.782 ms e p95 242.037 ms.

## Evidencia de treinamento separada do benchmark

No recorte cross-fitted do pipeline completo (165 registros), a acuracia semantica foi 94.55%, o macro-F1 foi 0.943419, a cobertura automatica foi 85/165 (51.52%) e houve 0 erros automaticos. Essa evidencia serviu para congelar limiares; nao substitui holdout confirmatorio.

Limiar geral: 0.76. Limiar especifico para OBRA: 0.90. O manifesto declara o candidato congelado, mas ainda como `PENDING_CONFIRMATORY_HOLDOUT`.

## Unidade amostral e limitacoes

As 640 linhas correspondem a 128 nucleos narrativos distintos e 5 realizacoes de superficie por nucleo. No recorte acionavel sao 480 linhas, mas apenas 96 nucleos distintos; no recorte de manutencao, 320 linhas e 64 nucleos distintos. Hashes distintos definem clusters, mas nao demonstram independencia estatistica entre nucleos sinteticos.

Consequencias:

- nao tratar as 640 linhas como observacoes independentes em testes ou intervalos de confianca;
- agrupar por `narrative_core_sha256` em bootstrap, validacao ou comparacoes;
- nao usar estes numeros para afirmar que o modelo local supera Gemini ou DeepSeek; falta comparacao pareada valida;
- preservar a revisao humana: 59/160 casos OBRA e 21/320 manutencoes nao receberam encaminhamento automatico;
- confirmar em holdout congelado, com rotulos independentes do treinamento, antes da alegacao cientifica final.

## Rastreabilidade

| Fonte | SHA-256 |
|---|---|
| `avaliacao/resultados/local-only-desenvolvimento-v1.8.0-20260716/local_only_predictions.jsonl` | `258106f1eebbaee5a56e118c1b4bda09c193719de8af4ce7f40e565562103603` |
| `avaliacao/resultados/local-only-desenvolvimento-v1.8.0-20260716/local_only_summary_metrics_v1.1.json` | `57def48701719c8abf243c56b32e91a251ef110841b9301e21a2854b13af94f7` |
| `avaliacao/resultados/local-only-desenvolvimento-v1.8.0-20260716/local_only_plan.json` | `ae7ed0b9ae262b165e15c86af57805639a892fb9fbc3908901c7209e1402d618` |
| `avaliacao/resultados/local-only-desenvolvimento-v1.8.0-20260716/local_only_units.jsonl` | `88b6b2125e8d7ba11edfe50c09c55fd9069a1778f7a79ff0e294c8f7b233d6f6` |
| `local_ai/artifacts/local_hybrid_manifest.json` | `3e818b5513bdaa4b7f037f2d4ada743d9b47ade1e882e8d90ae216d0b215eb25` |
| `local_ai/models/manifest.json` | `e596681fa782b49242ff60f887e000e999b7d02b5f710fa69570221f4d2bbd80` |
| `local_ai/artifacts/local_hybrid_bundle.joblib` | `f518b7f9699aa9e23aab7eb2479990619ad5085994569b3f7c3f253e5207bb5d` |
| `avaliacao/datasets/desenvolvimento_local_v1.jsonl` | `0de50381c0dfaefeb1a940cd697f9c9a8e87b5efee9252a1f4ca43c9d904f204` |

O JSON ao lado deste relatorio contem as contagens, matrizes, casos de erro e metadados em formato legivel por maquina.
