# Triagem Inteligente GLPI + n8n + Postgres - v7

> **DOCUMENTO HISTÓRICO.** A V7 não é o workflow ativo atual. A release
> operacional é a V9, dividida em seis workflows sob
> `n8n/workflows/Versão9`. A linha “Workflow ativo” abaixo descreve somente o
> estado da época. Para publicação, use a cópia inativa e sanitizada em
> `n8n/history`; os exports brutos antigos não devem ser publicados.

Workflow ativo: `Triagem Inteligente de Chamados - v7 (Postgres)`
ID no n8n: `TriagemV7Pg20260429`

Arquivos principais:

- `scripts/build_v7_workflow.js`: gerador do workflow v7 a partir do JSON v6.
- `n8n/workflows/Teste01_v7.json`: workflow gerado para importar no n8n.
- `n8n/workflows/v7_current.json`: ultimo export do workflow publicado.
- `n8n/credentials/SMTP_Mailpit_Local.json`: credencial SMTP local para Mailpit.
- `Banco de dados chamados/init_v2.sql`: schema da tabela `tickets_processados`.

## Comportamento

Triggers:

- `T1. Manual`: primeira execucao/bootstrap ou ressincronizacao manual.
- `T2. Webhook GLPI`: dia a dia, recebe chamados novos em `POST /webhook/glpi-ticket-novo-v7`.
- `T3. Schedule`: atualiza o banco as `06:00`, `12:00` e `18:00`.
- `T4. Webhook Decisao Fiscal`: recebe cliques de duplicidade em `GET /webhook/triagem-fiscal-duplicidade-v7`.

Regras de busca:

- Primeira execucao: busca `Novo`, `Pendente`, `Atribuido`, `Planejado`, `Solucionado` e `Fechado`; para `Atribuido/Planejado/Solucionado/Fechado`, aplica recorte de 90 dias.
- Depois da primeira execucao: o webhook busca apenas o ticket recebido e so tria se o status atual ainda for `Novo`.
- Schedule: busca `Pendente`, `Atribuido`, `Planejado`, `Solucionado` e `Fechado`, atualiza o Postgres e nao chama IA.

Campos persistidos por chamado:

`id`, `titulo`, `status_num`, `status_nome`, `tipo_servico`, `descricao`, `localizacao`, `data_abertura`, `data_ultima_mudanca`, `solicitante`, `email_solicitante`, alem dos campos de triagem (`triagem_status`, `classificacao`, `executor`, `duplicado_de_id`, `decisao_fiscal`, etc.).

## Fluxo de decisao

1. O chamado novo entra no Postgres.
2. O historico elegivel e reduzido para ate 60 candidatos antes da IA.
3. A IA avalia duplicidade. Se a IA negar, uma regra local ainda marca como duplicado quando ha similaridade forte no mesmo local.
4. Se for possivel duplicado:
   - GLPI recebe prefixo `[Duplicado]`;
   - status vai para `Pendente`;
   - um followup registra o chamado de referencia, justificativa e links do fiscal.
5. Se o fiscal confirma duplicidade:
   - GLPI fecha o chamado;
   - Postgres marca `DUPLICADO_FECHADO`.
6. Se o fiscal rejeita duplicidade:
   - Postgres limpa `em_aprovacao_fiscal`;
   - GLPI restaura o titulo sem `[Duplicado]`;
   - o chamado segue para classificacao OBRA/DEMO/SOB_DEMANDA.
7. Se nao for duplicado:
   - OBRA: envia e-mail real via Mailpit para DDI/DG, registra followup e fecha o chamado.
   - DEMO: status GLPI `Atribuido` e Postgres `ATRIBUIDO_DEMO`.
   - SOB_DEMANDA: status GLPI `Planejado` e Postgres `ENCAMINHADO_PLANEJADO`.

Protecoes contra sobrecarga:

- `SplitInBatches` com lote de 1 chamado.
- `Wait` real de 20 segundos antes de cada chamada de IA.
- Historico de duplicidade limitado a 60 candidatos pre-ranqueados no Postgres.
- Gemini com retry automatico de 3 tentativas e 20 segundos entre tentativas.

## Endpoints

Novo chamado:

```powershell
$body = @{ ticket_id = 293; event = 'new' } | ConvertTo-Json -Compress
Invoke-RestMethod -Method Post `
  -Uri 'http://localhost:5678/webhook/glpi-ticket-novo-v7' `
  -ContentType 'application/json' `
  -Body $body
```

Decisao fiscal:

```text
http://localhost:5678/webhook/triagem-fiscal-duplicidade-v7?decisao=confirmar&chamado_id=290&ref_id=289
http://localhost:5678/webhook/triagem-fiscal-duplicidade-v7?decisao=nao_duplicado&chamado_id=292&ref_id=291
```

## Atualizar o workflow no Docker

Execute a partir da raiz do projeto (`.`):

```powershell
docker run --rm --entrypoint node `
  -v ".:/work" `
  -w /work `
  n8nio/n8n:latest `
  scripts/build_v7_workflow.js

docker cp .\n8n\workflows\Teste01_v7.json n8n:/home/node/.n8n/Teste01_v7.json
docker exec n8n n8n import:workflow --input=/home/node/.n8n/Teste01_v7.json
docker exec n8n n8n publish:workflow --id=TriagemV7Pg20260429
docker restart n8n
```

Se a credencial SMTP do Mailpit ainda nao existir:

```powershell
docker cp .\n8n\credentials\SMTP_Mailpit_Local.json n8n:/home/node/.n8n/SMTP_Mailpit_Local.json
docker exec n8n n8n import:credentials --input=/home/node/.n8n/SMTP_Mailpit_Local.json
```

Checar se publicou:

```powershell
docker exec n8n n8n export:workflow --id=TriagemV7Pg20260429 --output=/home/node/.n8n/v7_current.json
docker cp n8n:/home/node/.n8n/v7_current.json .\n8n\workflows\v7_current.json
```

## Testes executados

Ambiente: Docker local com n8n `2.10.3`, GLPI em `localhost:8080`, Mailpit em `localhost:8025`, Postgres `glpi-dedup-db`.

Resultados finais:

| Caso | Chamado | Resultado |
| --- | ---: | --- |
| OBRA | 286 | GLPI `Fechado`, Postgres `FECHADO_OBRA`, e 1 e-mail no Mailpit |
| DEMO | 280 | GLPI `Atribuido`, Postgres `ATRIBUIDO_DEMO` |
| SOB_DEMANDA | 281 | GLPI `Planejado`, Postgres `ENCAMINHADO_PLANEJADO` |
| Duplicidade confirmada | 290 -> 289 | GLPI `Fechado`, Postgres `DUPLICADO_FECHADO` |
| Duplicidade rejeitada | 292 -> 291 | Titulo restaurado, GLPI `Atribuido`, Postgres `ATRIBUIDO_DEMO`, `decisao_fiscal=REJEITOU_DUP` |
| Webhook para chamado nao-novo | 280 | Nao retriou e nao alterou a classificacao |
| Link fiscal invalido | `decisao=invalida` | Execucao encerrou sem alterar dados |
| Smoke final apos Wait real | 293 | GLPI `Atribuido`, Postgres `ATRIBUIDO_DEMO` |

As ultimas execucoes verificadas do workflow (`1777` a `1784`) terminaram com status `success`. O workflow publicado esta ativo, com `triggerCount=3`, e o no `L2. Wait 20s entre lotes` esta como `n8n-nodes-base.wait`.

## Observacoes

- O retorno HTTP dos webhooks de decisao fiscal e o padrao do n8n (`Workflow was started`). A validacao real deve ser feita no GLPI e no Postgres.
- Nos `Respond to Webhook` foram removidos porque o n8n `2.10.3` acusava `Unused Respond to Webhook node` quando havia multiplos webhooks no mesmo workflow.
- Os workflows antigos foram despublicados durante a correcao; o workflow ativo esperado e o v7.
