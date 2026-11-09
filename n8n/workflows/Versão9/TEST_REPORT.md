# Relatorio de verificacao dos contratos V9

> **Atualização de 26/08/2026.** Após a correção final do WF06, a suíte
> hermética combinada aprovou 316 testes e 114 subtestes, a validação estática
> passou, três smokes live seguros passaram e o E2E sintético
> `VALIDACAO-WF06-E2E-20260826T223056234436Z` percorreu WF06→WF02→WF03 com
> duas reservas/decisões/tentativas, DLQ zero, paridade, cleanup e restauração
> completos. A execução manual n8n 52143 também terminou com sucesso. Consulte
> `../../../docs/TEST_REPORT.md`. A evidência continua técnica e não
> confirmatória.

Data da última reexecução: 2026-08-17, America/Sao_Paulo.

## Conclusao

Os contratos estaticos dos webhooks atuais passaram novamente em 17/08/2026, e
o preflight local sem mutacao tambem passou. Isso sustenta que os testes automatizados estao
alinhados com a arquitetura V9 atual; nao constitui, isoladamente, garantia de
execucao E2E completa da revisao publicada.

O relatorio anterior, de 2026-05-21, usava o webhook legado do WF02 e acionava
a decisao fiscal por `GET` sem token. Seus resultados sao evidencia historica
de outra revisao e nao devem ser citados como validacao da V9 atual.

## Correcoes nos testes

- Removidas credenciais literais. `GLPI_APP_TOKEN`, `GLPI_AUTH_BASIC` e demais
  segredos sao lidos exclusivamente do ambiente.
- O ingresso de chamados passou a usar `POST /webhook/glpi-ticket-fila-ia-v9`
  do WF06.
- O contrato fiscal passou a usar:
  - `GET /webhook/fiscal-confirmacao-v9` apenas para exibir o formulario;
  - `POST /webhook/fiscal-decisao-fiscal-ic-2026` para alterar o estado.
- O modo padrao do teste runtime e um preflight sem mutacao de ticket/banco.
- O POST E2E exige opt-in duplo e bloqueia qualquer ticket sem prefixo
  sintetico.
- Foram adicionadas verificacoes locais para token invalido, token expirado,
  replay, concorrencia e ramo `nao_duplicado`.

## Evidencia produzida nesta revisao

Comandos executados:

```powershell
python -m py_compile `
  "n8n\workflows\Versão9\test_v9_runtime.py" `
  "n8n\workflows\Versão9\test_v9_hard.py"

python "n8n\workflows\Versão9\test_v9_hard.py"
python -m pytest -q "n8n\workflows\Versão9\test_v9_hard.py"

python "n8n\workflows\Versão9\validate_v9_static.py"

$env:N8N_BASE_URL = "http://127.0.0.1:5678"
python "n8n\workflows\Versão9\test_v9_runtime.py" --mode preflight
```

Resultados:

| Evidencia | Resultado |
|---|---:|
| Compilacao dos dois scripts | PASS |
| Contratos estaticos/mocados | 9/9 PASS |
| Validador estatico integral da V9 | 913 PASS, 0 FAIL |
| Preflight local n8n | PASS |
| WF06 rejeita chave incorreta | HTTP 401, PASS |
| WF04 rejeita preview com token malformado | HTTP 400 e sem formulario, PASS |
| Testes focados do executor E2E | 11/11 PASS |
| E2E sintético WF04/WF05 positivo | run `VALIDACAO-POSTS-E2E-20260818T004922Z`, PASS |
| E2E sintético WF04/WF05 `nao_duplicado` | run `VALIDACAO-POSTS-E2E-20260818T004902Z`, PASS |

Nos dois E2E, WF04 GET respondeu 200 sem mutação; tokens expirado e inválido
responderam 409 sem alterar o ticket; dois POSTs reais concorrentes produziram
um HTTP 202, um HTTP 200 e exatamente uma transição; o replay respondeu 409 sem
nova transição. WF05 GET respondeu 200, o POST respondeu 200 e o replay respondeu
403. Cada `resultado.json` congela ID, nome, quantidade de nós e SHA-256 dos seis
exports V9 canônicos. Essa evidência é técnica e não confirmatória.

No E2E negativo, WF04 registrou `REJEITOU_DUP`, removeu os campos de
duplicidade, gravou exatamente um evento `DUPLICIDADE_REJEITADA` e entregou o
ticket em `PENDENTE_FILA_IA/CLASSIFICACAO`. A reserva WF06 ficou bloqueada por
advisory lock apenas durante os asserts e o cleanup; a trava foi liberada ao
final. WF05 registrou a predição como incorreta e `NAO_DUPLICADO`. Os tickets
314 e 315 foram encerrados sem estado residual de fila. No ramo positivo, os
tickets 316 e 317 também foram encerrados sem alerta de cleanup.

## O que os nove testes provam

1. O WF06 expoe o caminho atual e compara a chave recebida com
   `GLPI_WEBHOOK_KEY` do ambiente.
2. O GET do WF04 so percorre os nos de renderizacao e resposta; nao alcanca
   PostgreSQL nem GLPI.
3. O formulario GET envia a decisao ao endpoint POST atual.
4. O POST exige decisao valida, ID positivo e token hexadecimal.
5. A reserva fiscal e um `UPDATE` condicional unico: exige aprovacao pendente,
   decisao vazia, token correspondente e prazo nao expirado.
6. O fluxo distingue token invalido, token expirado, clique repetido e decisao
   aceita.
7. `nao_duplicado` limpa match/token e reenfileira o ticket na etapa
   `CLASSIFICACAO` do WF06.
8. O WF06 usa bloqueio transacional, capacidade de lote e `SKIP LOCKED` para
   impedir consumo duplicado da fila.
9. Os clientes mocados usam exatamente WF06 POST, WF04 GET-preview e WF04
   POST-decisao, sem credencial literal.

## E2E integrado ainda necessario

Para afirmar que a revisao corrente funciona ponta a ponta, ainda e necessario
executar, em ambiente de teste isolado e congelado:

- drenagem completa WF06 -> WF02 -> WF03 com um chamado criado pelo GLPI.

Os casos fiscais acima foram executados com estado persistido sintético e
cleanup. A drenagem terminal não foi executada nesta revisão; inventar esse
resultado ou reutilizar o resultado de maio violaria a rastreabilidade
científica.

## Execucao segura do E2E fiscal preparado

O operador deve preparar um chamado sintetico em `POSSIVEL_DUPLICADO`, guardar
seu token apenas no ambiente e escolher `confirmar` ou `nao_duplicado`:

```powershell
$env:TEST_MODE = "true"
$env:V9_E2E_MUTATION_TESTS = "true"
$env:N8N_BASE_URL = "http://127.0.0.1:5678"
$env:GLPI_API_URL = "http://127.0.0.1:9080/apirest.php"
$env:GLPI_APP_TOKEN = "<segredo>"
$env:GLPI_AUTH_BASIC = "Basic <base64>"
$env:V9_E2E_FISCAL_TICKET_ID = "<id-sintetico>"
$env:V9_E2E_FISCAL_TOKEN = "<token-hex-do-ticket>"
$env:V9_E2E_FISCAL_DECISION = "nao_duplicado"
$env:V9_E2E_SYNTHETIC_PREFIX = "[TESTE_AUTOMATIZADO_E2E_"

python "n8n\workflows\Versão9\test_v9_runtime.py" `
  --mode fiscal-preparado
```

O roteiro verifica o prefixo no proprio GLPI antes de qualquer POST, abre o
preview, testa um token incorreto e envia dois POSTs concorrentes. O esperado e
exatamente uma resposta 202; a tentativa concorrente pode receber 200 ou 409,
mas nunca pode reservar uma segunda transicao. Um replay sequencial posterior
deve receber 409 e não pode causar outra transição.

O roteiro mais amplo
`avaliacao/scripts/validar_webhooks_confirmacao_e2e.py` continua sendo a opcao
para criar e encerrar chamados sinteticos do contrato WF04/WF05. Seus artefatos
devem registrar hash/revisao dos workflows e ser classificados como validacao
tecnica, nao como resultado confirmatorio do modelo.
