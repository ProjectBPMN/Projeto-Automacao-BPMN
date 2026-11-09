# Comparação local local-hybrid-v1.1.0 versus local-hybrid-v1.9.0

**Status:** comparação descritiva de engenharia, não confirmatória.  **Unidades pareadas:** 1240.  **Contrato das métricas:** 1.2.0.

## Validação do pareamento

Os dois testes usam exatamente os mesmos `unit_id`, entradas (`shared_input_sha256`), tarefas, gabaritos, dataset e manifesto. O arquivo de unidades é idêntico byte a byte (SHA-256 `88b6b2125e8d7ba11edfe50c09c55fd9069a1778f7a79ff0e294c8f7b233d6f6`). Os hashes das predições também correspondem aos registrados nos resumos padronizados.

## Resultados gerais

| Métrica | local-hybrid-v1.1.0 | local-hybrid-v1.9.0 | Delta local-hybrid-v1.9.0 - local-hybrid-v1.1.0 |
|---|---:|---:|---:|
| Disponibilidade | 195/1240 (15.73%) | 1239/1240 (99.92%) | 84.19 p.p. |
| Cobertura semântica | 87/1240 (7.02%) | 753/1240 (60.73%) | 53.71 p.p. |
| Automação sem revisão humana | 73/1240 (5.89%) | 586/1240 (47.26%) | 41.37 p.p. |
| Acurácia seletiva | 87/87 (100.00%) | 753/753 (100.00%) | 0.00 p.p. |
| Latência média entre respostas disponíveis | 1245.667 ms | 663.963 ms | -581.704 ms |
| Latência p50 entre respostas disponíveis | 981.759 ms | 544.940 ms | -436.819 ms |
| Latência p95 entre respostas disponíveis | 4384.264 ms | 1781.497 ms | -2602.767 ms |

As falhas operacionais passaram de 1045 em local-hybrid-v1.1.0 para 1 em local-hybrid-v1.9.0. A acurácia seletiva marginal passou de 100.00% (87 acertos em 87 decisões cobertas) para 100.00% (753 acertos em 753 decisões cobertas): são denominadores diferentes, portanto esse contraste não deve ser interpretado isoladamente.

## Contagens pareadas exatas

| Evento | Ambas | Somente local-hybrid-v1.1.0 | Somente local-hybrid-v1.9.0 | Nenhuma |
|---|---:|---:|---:|---:|
| Disponível | 194 | 1 | 1045 | 0 |
| Decisão semântica coberta | 79 | 8 | 674 | 479 |
| Automação direta | 65 | 8 | 521 | 646 |
| Correto, tratando falha/abstenção como erro | 79 | 8 | 674 | 479 |

Nas unidades cobertas pelas duas versões, a acurácia foi 100.00% em local-hybrid-v1.1.0 e 100.00% em local-hybrid-v1.9.0 (n=79). Para latência, existem 194 unidades com resposta disponível nas duas versões; a diferença média pareada (local-hybrid-v1.9.0 - local-hybrid-v1.1.0) foi -459.385 ms.

## Critérios da recomendação de engenharia

| Critério | Observado | Regra | Limite | Resultado |
|---|---:|:---:|---:|:---:|
| `availability_delta` | 0.841935 | >= | 0.000000 | PASS |
| `semantic_coverage_delta` | 0.537097 | >= | 0.000000 | PASS |
| `straight_through_automation_delta` | 0.413710 | >= | 0.000000 | PASS |
| `common_covered_accuracy_delta` | 0.000000 | >= | -0.000000 | PASS |
| `strict_correctness_delta_all_units` | 0.537097 | >= | 0.000000 | PASS |
| `mean_paired_latency_delta_ms` | -459.384809 | <= | 0.000000 | PASS |
| `common_covered_units` | 79.000000 | >= | 30.000000 | PASS |

**Decisão derivada neste contraste:** `CANDIDATE_RECOMMENDED_FOR_NEXT_ENGINEERING_STAGE`. `local-hybrid-v1.9.0` atende aos critérios explícitos somente contra a v1.1 degradada. Isso não promove a v1.9: no contraste decisório contra a v1.8 vigente, ela recebeu `CANDIDATE_NOT_RECOMMENDED` por disponibilidade e latência.

## Limite da interpretação

A recomendação acima não escolhe automaticamente uma versão por nome e não equivale a superioridade científica. Não foi demonstrada superioridade em generalização: o corpus é sintético, pertence ao desenvolvimento e possui variações do mesmo núcleo semântico. Por isso não foram executados testes de significância ou não inferioridade e este relatório não valida o modelo cientificamente em dados externos.

## Reprodução

```powershell
python avaliacao\scripts\comparar_versoes_locais.py
```
