# Validação E2E dos webhooks WF04 e WF05

- run_id: `VALIDACAO-POSTS-E2E-20260818T002942Z`
- decisão fiscal testada: `confirmar`
- natureza: validação técnica automatizada, sintética e não confirmatória
- resultado: **APROVADO**
- chamados GLPI sintéticos: `308, 309`
- chamados sintéticos encerrados ao final: `True`

Tokens, nonces e segredos não são persistidos neste artefato.

## Evidências

- WF04 GET preview: HTTP 200, sem mutação.
- WF04 POST válido: HTTP 202; replay: HTTP 409 e sem nova transição.
- WF05 GET preview: HTTP 200, sem mutação.
- WF05 POST válido: HTTP 200; replay: HTTP 403 e sem nova transição.
