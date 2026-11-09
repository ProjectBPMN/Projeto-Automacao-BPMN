# Validação E2E dos webhooks WF04 e WF05

- run_id: `VALIDACAO-POSTS-E2E-20260818T004035Z`
- decisão fiscal testada: `nao_duplicado`
- natureza: validação técnica automatizada, sintética e não confirmatória
- resultado: **APROVADO**
- chamados GLPI sintéticos: `310, 311`
- chamados sintéticos encerrados ao final: `True`

Tokens, nonces e segredos não são persistidos neste artefato.

## Evidências

- WF04 GET preview: HTTP 200, sem mutação.
- WF04 token expirado antes da decisão válida: HTTP 409, ticket imutável e validade restaurada.
- WF04 token inválido após a reserva do oráculo: HTTP 409, ticket imutável.
- WF04 corrida com dois POSTs reais: códigos `[202, 200]`, exatamente um HTTP 202 e uma única transição persistida.
- WF04 replay após conclusão: HTTP 409 e sem nova transição.
- WF05 GET preview: HTTP 200, sem mutação.
- WF05 POST válido: HTTP 200; replay: HTTP 403 e sem nova transição.
