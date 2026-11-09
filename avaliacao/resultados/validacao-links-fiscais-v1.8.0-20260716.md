# Validação dos links fiscais — v1.8.0

Natureza: teste sintético de integração, não confirmatório.

## Confirmar duplicidade

- execução: `VALIDACAO-20260716T145412`;
- ticket: 252;
- endpoint: link real produzido pelo WF02 e processado pelo WF04;
- resposta: HTTP 202;
- decisão persistida: `CONFIRMOU_DUP`;
- estado final: `DUPLICADO_FECHADO` / `DUPLICADO`;
- tentativa automática: uma, status `CONFIRMADA`.

## Não é duplicado

- ticket sintético: 249;
- chamada: link/token já produzido pelo WF02, sem cabeçalhos do oráculo;
- decisão enviada: `nao_duplicado`;
- resposta: HTTP 202;
- decisão persistida: `REJEITOU_DUP`;
- estado seguinte: `PENDENTE_FILA_IA`, etapa `CLASSIFICACAO`;
- ação: `WF04_ENFILEIROU_CLASSIFICACAO`.

Eventos de auditoria observados:

- `LINK_FORMATO_VALIDO_FISCAL_GLPI`;
- `DECISAO_REJEITAR`;
- `DUPLICIDADE_REJEITADA`.

Conclusão: os dois links são gerados no formato aceito, chegam ao WF04,
respondem de modo assíncrono e produzem as transições esperadas. Isso comprova o
contrato técnico, não a qualidade da decisão do modelo.

