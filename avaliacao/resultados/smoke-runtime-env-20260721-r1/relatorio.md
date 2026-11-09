# Calibração repetida da fila WF06

- Início: `2026-07-21T19:36:34`
- Repetições por configuração: `3`
- Tickets por repetição: `2`
- Warm-up excluído da latência: `0`
- Concorrência de ingresso GLPI: `2`
- SLA p95: `None` segundos
- Configuração aprovada: `{'id': 'Q1', 'batch': 1, 'interval_seconds': 1}`
- Aprovada: `SIM`

Uma configuração só é aprovada quando todas as repetições terminam sem erro de IA, rate limit, probabilidade inválida, timeout ou violação de ordem.

## CALQ-20260721T193634-Q1-R1

- Configuração: lote `1`, intervalo `1s`
- Repetição: `1`
- Resultado: `OK`
- Métricas: `{"total": 2, "total_medido": 2, "warmup_descartado": 0, "terminal": 2, "espera_ia_media_s": "25.952", "espera_ia_p50_s": "25.952", "espera_ia_p95_s": "49.375", "espera_ia_p99_s": "51.457", "latencia_total_media_s": "56.564", "latencia_total_p50_s": "56.564", "latencia_total_p95_s": "60.242", "latencia_total_p99_s": "60.569", "erros_ia": 0, "probabilidades_invalidas": 0, "rate_limits": 0, "violacoes_ordem": 0, "drain_elapsed_s": 168.872, "throughput_tickets_per_minute": 0.710595, "p99_confirmatorio": false, "nota_p99": "exploratório; requer pelo menos 500 latências medidas por tratamento", "success": true}`

## CALQ-20260721T194004-Q1-R2

- Configuração: lote `1`, intervalo `1s`
- Repetição: `2`
- Resultado: `OK`
- Métricas: `{"total": 2, "total_medido": 2, "warmup_descartado": 0, "terminal": 2, "espera_ia_media_s": "-0.142", "espera_ia_p50_s": "-0.142", "espera_ia_p95_s": "-0.103", "espera_ia_p99_s": "-0.100", "latencia_total_media_s": "60.104", "latencia_total_p50_s": "60.104", "latencia_total_p95_s": "60.212", "latencia_total_p99_s": "60.222", "erros_ia": 0, "probabilidades_invalidas": 0, "rate_limits": 0, "violacoes_ordem": 0, "drain_elapsed_s": 177.346, "throughput_tickets_per_minute": 0.676644, "p99_confirmatorio": false, "nota_p99": "exploratório; requer pelo menos 500 latências medidas por tratamento", "success": true}`

## CALQ-20260721T194408-Q1-R3

- Configuração: lote `1`, intervalo `1s`
- Repetição: `3`
- Resultado: `OK`
- Métricas: `{"total": 2, "total_medido": 2, "warmup_descartado": 0, "terminal": 2, "espera_ia_media_s": "7.244", "espera_ia_p50_s": "7.244", "espera_ia_p95_s": "13.884", "espera_ia_p99_s": "14.475", "latencia_total_media_s": "37.728", "latencia_total_p50_s": "37.728", "latencia_total_p95_s": "58.011", "latencia_total_p99_s": "59.814", "erros_ia": 0, "probabilidades_invalidas": 0, "rate_limits": 0, "violacoes_ordem": 0, "drain_elapsed_s": 132.009, "throughput_tickets_per_minute": 0.909029, "p99_confirmatorio": false, "nota_p99": "exploratório; requer pelo menos 500 latências medidas por tratamento", "success": true}`

## Resumo por configuração

### Lote 1 a cada 1s

- Elegível: `SIM`
- Resumo: `{"id": "Q1", "batch": 1, "interval_seconds": 1, "runs_expected": 3, "runs_observed": 3, "successful_runs": 3, "all_runs_successful": true, "run_success_wilson_95": {"lower": 0.4385029682449546, "upper": 1.0, "confidence": 0.95}, "tickets_total": 6, "latency_observations_after_warmup": 6, "espera_ia_s": {"mean": 11.018, "p50": -0.0865, "p95": 42.638999999999996, "p99": 50.110200000000006}, "latencia_total_s": {"mean": 51.46533333333333, "p50": 60.104, "p95": 60.553749999999994, "p99": 60.63075}, "throughput_tickets_per_minute": {"mean_between_runs": 0.7654226666666667, "p50_between_runs": 0.710595, "minimum_between_runs": 0.676644}, "p95_sla_seconds": null, "p95_sla_met": null, "p99_confirmatory": false, "eligible_for_selection": true}`

