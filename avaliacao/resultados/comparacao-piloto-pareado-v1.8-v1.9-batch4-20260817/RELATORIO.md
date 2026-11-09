# Comparação local local-hybrid-v1.8.0 versus local-hybrid-v1.9.0

**Status:** comparação descritiva de engenharia, não confirmatória.  **Unidades pareadas:** 30.  **Contrato das métricas:** 1.2.0.

## Validação do pareamento

Os dois testes usam exatamente os mesmos `unit_id`, entradas (`shared_input_sha256`), tarefas, gabaritos, dataset e manifesto. O arquivo de unidades é idêntico byte a byte (SHA-256 `a69fc8c207b140d3166e36e788f19d33356d8ea1cafaec4d7531c4653b863fc1`). Os hashes das predições também correspondem aos registrados nos resumos padronizados.

## Resultados gerais

| Métrica | local-hybrid-v1.8.0 | local-hybrid-v1.9.0 | Delta local-hybrid-v1.9.0 - local-hybrid-v1.8.0 |
|---|---:|---:|---:|
| Disponibilidade | 30/30 (100.00%) | 30/30 (100.00%) | 0.00 p.p. |
| Cobertura semântica | 16/30 (53.33%) | 16/30 (53.33%) | 0.00 p.p. |
| Automação sem revisão humana | 16/30 (53.33%) | 16/30 (53.33%) | 0.00 p.p. |
| Acurácia seletiva | 16/16 (100.00%) | 16/16 (100.00%) | 0.00 p.p. |
| Latência média entre respostas disponíveis | 434.209 ms | 454.931 ms | 20.722 ms |
| Latência p50 entre respostas disponíveis | 114.655 ms | 120.310 ms | 5.655 ms |
| Latência p95 entre respostas disponíveis | 1337.585 ms | 1464.240 ms | 126.655 ms |

As falhas operacionais passaram de 0 em local-hybrid-v1.8.0 para 0 em local-hybrid-v1.9.0. A acurácia seletiva marginal passou de 100.00% (16 acertos em 16 decisões cobertas) para 100.00% (16 acertos em 16 decisões cobertas): são denominadores diferentes, portanto esse contraste não deve ser interpretado isoladamente.

## Contagens pareadas exatas

| Evento | Ambas | Somente local-hybrid-v1.8.0 | Somente local-hybrid-v1.9.0 | Nenhuma |
|---|---:|---:|---:|---:|
| Disponível | 30 | 0 | 0 | 0 |
| Decisão semântica coberta | 16 | 0 | 0 | 14 |
| Automação direta | 16 | 0 | 0 | 14 |
| Correto, tratando falha/abstenção como erro | 16 | 0 | 0 | 14 |

Nas unidades cobertas pelas duas versões, a acurácia foi 100.00% em local-hybrid-v1.8.0 e 100.00% em local-hybrid-v1.9.0 (n=16). Para latência, existem 30 unidades com resposta disponível nas duas versões; a diferença média pareada (local-hybrid-v1.9.0 - local-hybrid-v1.8.0) foi 20.722 ms.

## Critérios da recomendação de engenharia

| Critério | Observado | Regra | Limite | Resultado |
|---|---:|:---:|---:|:---:|
| `availability_delta` | 0.000000 | >= | 0.000000 | PASS |
| `semantic_coverage_delta` | 0.000000 | >= | 0.000000 | PASS |
| `straight_through_automation_delta` | 0.000000 | >= | 0.000000 | PASS |
| `common_covered_accuracy_delta` | 0.000000 | >= | -0.000000 | PASS |
| `strict_correctness_delta_all_units` | 0.000000 | >= | 0.000000 | PASS |
| `mean_paired_latency_delta_ms` | 20.722400 | <= | 0.000000 | FAIL |
| `common_covered_units` | 16.000000 | >= | 1.000000 | PASS |

**Decisão derivada:** `CANDIDATE_NOT_RECOMMENDED`. local-hybrid-v1.9.0 não é recomendado pela política desta execução; critérios não atendidos: mean_paired_latency_delta_ms.

## Limite da interpretação

A recomendação acima não escolhe automaticamente uma versão por nome e não equivale a superioridade científica. Não foi demonstrada superioridade em generalização: o corpus é sintético, pertence ao desenvolvimento e possui variações do mesmo núcleo semântico. Por isso não foram executados testes de significância ou não inferioridade e este relatório não valida o modelo cientificamente em dados externos.

## Reprodução

```powershell
python avaliacao\scripts\comparar_versoes_locais.py
```
