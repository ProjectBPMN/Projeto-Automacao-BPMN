# Validação E2E dos webhooks WF04 e WF05

- run_id: `VALIDACAO-POSTS-E2E-20260722T040652Z`
- natureza: validação técnica automatizada, sintética e não confirmatória
- resultado: **APROVADO**
- chamados GLPI sintéticos: `302, 303`
- chamados sintéticos encerrados ao final: `True`

Tokens, nonces e segredos não são persistidos neste artefato.

## Evidências

- WF04 GET preview: HTTP 200, sem mutação.
- WF04 POST válido: HTTP 202; replay: HTTP 409 e sem nova transição.
- WF05 GET preview: HTTP 200, sem mutação.
- WF05 POST válido: HTTP 200; replay: HTTP 403 e sem nova transição.

O histórico completo das tentativas e o cleanup auditável estão em `RELATORIO_CONSOLIDADO.md` e `tentativas_consolidadas.json`.
