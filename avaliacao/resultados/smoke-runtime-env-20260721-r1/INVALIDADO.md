# Execução invalidada

Esta rodada não pode ser usada como calibração de vazão nem alimentar gráficos.

Motivo: o coletor v2.2 media a primeira decisão a partir de
`fila_enfileirada_em`, campo que é atualizado quando o ticket muda da etapa de
deduplicação para classificação. Isso produziu esperas negativas nos tickets
279, 280, 281 e 283 e fez o arquivo gerado registrar uma aprovação inválida.

Os seis tickets foram processados e a fila terminou vazia, de modo que a rodada
continua sendo evidência de que a correção de acesso a `$env` funcionou no
runtime. Ela não é evidência temporal.

- Runs afetados: `CALQ-20260721T193634-Q1-R1`,
  `CALQ-20260721T194004-Q1-R2` e `CALQ-20260721T194408-Q1-R3`.
- Protocolo inválido: `calibracao-fila-v2.2.0`.
- Correção: coletor `calibracao-fila-v2.3.0`, com início estável, primeira
  reserva real do WF06, decisão restrita ao mesmo `run_id` e validação temporal
  fail-closed.

O arquivo `calibracao_aprovada.json` foi preservado sem alterações para manter
a trilha de auditoria do defeito; este marcador tem precedência sobre seu campo
`approved`.
