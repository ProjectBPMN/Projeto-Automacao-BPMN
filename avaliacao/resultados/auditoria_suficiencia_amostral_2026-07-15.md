# Auditoria de suficiência amostral — fase automatizada

## Conclusão

O corpus V3 é suficiente para regressão funcional automatizada, mas não para estimativas precisas por classe/estrato.
Aumentar somente o número bruto ou trocar a seed não corrige a dependência entre paráfrases.
Esta fase dispensa dupla revisão humana, preserva as confirmações dos workflows e permanece não confirmatória.

## Unidade independente observada

- Tickets nominais: `1200`.
- Núcleos de desafio dedup: `100`.
- Núcleos dedup positivos: `40`.
- Núcleos negativos completos: `48`.
- Núcleos negativos críticos/insuficientes: `12`.
- Núcleos classificatórios: `40`, `{'DEMO': 10, 'OBRA': 10, 'SOB_DEMANDA': 10, 'TRIAGEM_MANUAL': 10}`.

## Precisão e decisão de ampliação

- Para margem conservadora de ±10 pp são necessárias `97` unidades independentes.
- Para ±5 pp são necessárias `385`.
- Com zero falsos positivos, são necessários `73` negativos independentes para limite superior Wilson ≤ 5%.
- Com zero falsos negativos, são necessários `189` episódios positivos independentes para limite superior Wilson ≤ 2%.
- Recomendação V4.1: acrescentar `878` tickets baseados em núcleos novos, totalizando `2078`.

As repetições superficiais existentes continuam úteis para estabilidade linguística, mas ficam fora do n independente primário.
