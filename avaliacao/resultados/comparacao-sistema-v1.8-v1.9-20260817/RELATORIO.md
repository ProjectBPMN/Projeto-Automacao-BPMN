# Comparação local local-hybrid-v1.8.0 versus local-hybrid-v1.9.0

**Status:** comparação descritiva de engenharia, não confirmatória.  **Unidades pareadas:** 1240.  **Contrato das métricas:** 1.2.0.

## Validação do pareamento

Os dois testes usam exatamente os mesmos `unit_id`, entradas (`shared_input_sha256`), tarefas, gabaritos, dataset e manifesto. O arquivo de unidades é idêntico byte a byte (SHA-256 `88b6b2125e8d7ba11edfe50c09c55fd9069a1778f7a79ff0e294c8f7b233d6f6`). Os hashes das predições também correspondem aos registrados nos resumos padronizados.

## Resultados gerais

| Métrica | local-hybrid-v1.8.0 | local-hybrid-v1.9.0 | Delta local-hybrid-v1.9.0 - local-hybrid-v1.8.0 |
|---|---:|---:|---:|
| Disponibilidade | 1240/1240 (100.00%) | 1239/1240 (99.92%) | -0.08 p.p. |
| Cobertura semântica | 671/1240 (54.11%) | 753/1240 (60.73%) | 6.61 p.p. |
| Automação sem revisão humana | 505/1240 (40.73%) | 586/1240 (47.26%) | 6.53 p.p. |
| Acurácia seletiva | 669/671 (99.70%) | 753/753 (100.00%) | 0.30 p.p. |
| Latência média entre respostas disponíveis | 414.331 ms | 663.963 ms | 249.632 ms |
| Latência p50 entre respostas disponíveis | 306.280 ms | 544.940 ms | 238.660 ms |
| Latência p95 entre respostas disponíveis | 838.088 ms | 1781.497 ms | 943.409 ms |

As falhas operacionais passaram de 0 em local-hybrid-v1.8.0 para 1 em local-hybrid-v1.9.0. A acurácia seletiva marginal passou de 99.70% (669 acertos em 671 decisões cobertas) para 100.00% (753 acertos em 753 decisões cobertas): são denominadores diferentes, portanto esse contraste não deve ser interpretado isoladamente.

## Contagens pareadas exatas

| Evento | Ambas | Somente local-hybrid-v1.8.0 | Somente local-hybrid-v1.9.0 | Nenhuma |
|---|---:|---:|---:|---:|
| Disponível | 1239 | 1 | 0 | 0 |
| Decisão semântica coberta | 652 | 19 | 101 | 468 |
| Automação direta | 486 | 19 | 100 | 635 |
| Correto, tratando falha/abstenção como erro | 651 | 18 | 102 | 469 |

Nas unidades cobertas pelas duas versões, a acurácia foi 99.85% em local-hybrid-v1.8.0 e 100.00% em local-hybrid-v1.9.0 (n=652). Para latência, existem 1239 unidades com resposta disponível nas duas versões; a diferença média pareada (local-hybrid-v1.9.0 - local-hybrid-v1.8.0) foi 249.838 ms.

## Critérios da recomendação de engenharia

| Critério | Observado | Regra | Limite | Resultado |
|---|---:|:---:|---:|:---:|
| `availability_delta` | -0.000806 | >= | 0.000000 | FAIL |
| `semantic_coverage_delta` | 0.066129 | >= | 0.000000 | PASS |
| `straight_through_automation_delta` | 0.065323 | >= | 0.000000 | PASS |
| `common_covered_accuracy_delta` | 0.001534 | >= | -0.000000 | PASS |
| `strict_correctness_delta_all_units` | 0.067742 | >= | 0.000000 | PASS |
| `mean_paired_latency_delta_ms` | 249.837733 | <= | 0.000000 | FAIL |
| `common_covered_units` | 652.000000 | >= | 30.000000 | PASS |

**Decisão derivada:** `CANDIDATE_NOT_RECOMMENDED`. local-hybrid-v1.9.0 não é recomendado pela política desta execução; critérios não atendidos: availability_delta, mean_paired_latency_delta_ms.

## Limite da interpretação

A recomendação acima não escolhe automaticamente uma versão por nome e não equivale a superioridade científica. Não foi demonstrada superioridade em generalização: o corpus é sintético, pertence ao desenvolvimento e possui variações do mesmo núcleo semântico. Por isso não foram executados testes de significância ou não inferioridade e este relatório não valida o modelo cientificamente em dados externos.

## Reprodução

```powershell
python avaliacao\scripts\comparar_versoes_locais.py
```
