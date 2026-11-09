# Comparação local v1.1 versus v1.8

**Status:** comparação descritiva de engenharia, não confirmatória.  **Unidades pareadas:** 1240.  **Contrato das métricas:** 1.2.0.

## Validação do pareamento

Os dois testes usam exatamente os mesmos `unit_id`, entradas (`shared_input_sha256`), tarefas, gabaritos, dataset e manifesto. O arquivo de unidades é idêntico byte a byte (SHA-256 `88b6b2125e8d7ba11edfe50c09c55fd9069a1778f7a79ff0e294c8f7b233d6f6`). Os hashes das predições também correspondem aos registrados nos resumos padronizados.

## Resultados gerais

| Métrica | local-hybrid-v1.1.0 | local-hybrid-v1.8.0 | Delta v1.8 - v1.1 |
|---|---:|---:|---:|
| Disponibilidade | 195/1240 (15.73%) | 1240/1240 (100.00%) | 84.27 p.p. |
| Cobertura semântica | 87/1240 (7.02%) | 671/1240 (54.11%) | 47.10 p.p. |
| Automação sem revisão humana | 73/1240 (5.89%) | 505/1240 (40.73%) | 34.84 p.p. |
| Acurácia seletiva | 87/87 (100.00%) | 669/671 (99.70%) | -0.30 p.p. |
| Latência média entre respostas disponíveis | 1245.667 ms | 414.331 ms | -831.336 ms |
| Latência p50 entre respostas disponíveis | 981.759 ms | 306.280 ms | -675.479 ms |
| Latência p95 entre respostas disponíveis | 4384.264 ms | 838.088 ms | -3546.176 ms |

A v1.8 eliminou as 1.045 falhas operacionais observadas na v1.1 e aumentou fortemente a cobertura e a automação direta. A acurácia seletiva marginal caiu de 100% (87 decisões cobertas) para 99,70% (669 acertos em 671 decisões cobertas): são denominadores diferentes, portanto esse contraste não deve ser interpretado isoladamente.

## Contagens pareadas exatas

| Evento | Ambas | Somente local-hybrid-v1.1.0 | Somente local-hybrid-v1.8.0 | Nenhuma |
|---|---:|---:|---:|---:|
| Disponível | 195 | 0 | 1045 | 0 |
| Decisão semântica coberta | 80 | 7 | 591 | 562 |
| Automação direta | 66 | 7 | 439 | 728 |
| Correto, tratando falha/abstenção como erro | 80 | 7 | 589 | 564 |

Nas unidades cobertas pelas duas versões, a acurácia foi 100.00% na v1.1 e 100.00% na v1.8 (n=80). Para latência, existem 195 unidades com resposta disponível nas duas versões; a diferença média pareada (v1.8 - v1.1) foi -835.056 ms.

## Interpretação permitida

A v1.8 é a melhor candidata para a próxima etapa de engenharia neste replay de desenvolvimento, porque melhorou disponibilidade, cobertura, automação direta e latência. Não foi demonstrado que ela é superior em generalização: o corpus é sintético, pertence ao desenvolvimento e possui variações do mesmo núcleo semântico. Por isso não foram executados testes de significância ou não inferioridade e este relatório não valida o modelo cientificamente em dados externos.

## Reprodução

```powershell
python avaliacao\scripts\comparar_versoes_locais.py
```
