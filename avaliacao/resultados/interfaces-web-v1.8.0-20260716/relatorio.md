# Teste de navegador somente leitura

Resultado geral: `PASSOU`.

| Serviço | Verificação | Resultado | Detalhe |
|---|---|---:|---|
| n8n | public_page | PASSOU | HTTP 200 |
| n8n | login_form | PASSOU | formulário de login renderizado |
| n8n | healthz | PASSOU | HTTP 200 |
| n8n | authenticated_read | PASSOU | HTTP 200 |
| n8n | six_active_v9_workflows | PASSOU | 6 workflows V9 ativos em sessão autenticada somente leitura |
| GLPI | public_page | PASSOU | HTTP 200 |
| GLPI | login_form | PASSOU | formulário de login renderizado |
| GLPI | authenticated_read | PASSOU | sessão somente leitura iniciada |
| GLPI | tickets_page_read_only | PASSOU | HTTP 200 |
| Mailpit | public_page | PASSOU | HTTP 200 |
| Mailpit | ui_title | PASSOU | Mailpit - 127.0.0.1 |
| Mailpit | api_info | PASSOU | HTTP 200 |

A suíte não cria chamados, não executa workflows e não altera mensagens.
As credenciais são lidas somente de variáveis/arquivos locais e nunca entram nos artefatos.
