# Relatório de validação — atualizado em 03/09/2026

## Resultado final de 03/09

- E2E sintético final: `passed=true`, WF06→WF02→WF03, paridade dos três
  workflows e cleanup completo;
- estado pós-E2E: zero `ERRO_IA`, zero fila ativa e zero DLQ aberta;
- homologação isolada: nove serviços saudáveis, zero tickets copiados e role
  PostgreSQL runtime sem privilégios administrativos;
- três janelas proxy aceleradas: 372/371/371 registros, 37 grupos disjuntos em
  cada janela e drift técnico PASS;
- histórico V1–V8: 10 JSONs, cobertura integral e hashes válidos;
- n8n e GLPI autenticados no navegador em inspeção somente leitura; seis
  workflows V9 publicados, execuções recentes WF06 em `Success` e listagem de
  chamados visível;
- E2E final `e2e-pipeline-local-v1.8.0-20260903-final.json`: `passed=true`, sem
  fallback/interferência e com cleanup completo;
- quatro janelas temporais completas já constam dos relatórios versionados; o
  estado local chegou a seis, todas com SLO proposto `FAIL`, e as recentes
  acionaram `STOP` de drift;
- varredura: árvore candidata PASS/0; histórico Git alcançável FAIL/15;
- resultados são técnicos/de desenvolvimento por proxy; não confirmam
  semântica nem disponibilidade longitudinal.

## Resultado executado

| Verificação | Resultado |
|---|---:|
| suíte hermética `local_ai` + `avaliacao` + operacional + V9 + histórico | 363 aprovados e 117 subtestes aprovados em 80,15 s |
| testes unitários/contratuais do protocolo V2.1 | 23 aprovados |
| seleção classificatória V2.1 | 35 configurações, 175 dobras, 38.990 predições OOF; `VALID_PARTIAL_TASK_SCOPE` |
| seleção de deduplicação V2.1 | bloqueada: 55 configurações `FAILED` antes do ajuste por insuficiência de grupos |
| smokes live seguros | 3 aprovados |
| contratos V9 focados | 9 aprovados |
| histórico público V1–V8 | 8 testes e 10 subtestes aprovados |
| validação estática V9 | aprovada |
| gate regex documental limitado | aprovado nos arquivos/padrões configurados; não substitui auditoria semântica |
| validação histórica `--check-sources` | aprovada, 10 JSONs cobrindo V1–V8 |
| `git diff --check` | aprovado |

## E2E histórico de 26/08

Artefato:
`../avaliacao/resultados/e2e-pipeline-local-v1-20260826-final.json`

- `run_id`: `VALIDACAO-WF06-E2E-20260826T223056234436Z`;
- natureza: técnica, sintética e não confirmatória;
- WF06 → WF02 → WF03;
- terminal `TRIAGEM_MANUAL`;
- duas reservas, duas decisões e duas tentativas;
- DLQ zero, sem fallback e sem interferência estranha;
- paridade do WF06 final e hash `dc78c11...14a0`;
- purge GLPI, limpeza do banco e restauração de controlador/runtime completos.

## Navegador — inspeção final de 03/09

Artefato estruturado:
`../avaliacao/resultados/operacional/validacao-navegador-20260903.json`.

- o n8n abriu autenticado em `Workflows - n8n` e mostrou os seis workflows V9
  como `Published`;
- a página de execuções mostrou IDs 61048–61057 do WF06 como `Success`;
- o GLPI aceitou a credencial local armazenada, abriu como `Super-Admin` e
  exibiu a listagem de chamados;
- nenhum workflow, credencial ou chamado foi alterado;
- títulos históricos com `[Erro IA]` permanecem visíveis porque os registros
  foram preservados. A fila PostgreSQL pós-E2E, medida separadamente, está em
  zero.

A inspeção visual é pontual e não prova correção semântica. A prova durável do
E2E e da fila são os artefatos JSON independentes identificados neste relatório.

## Interpretação

Esses resultados demonstram regressão técnica e integração nos cenários
exercitados. Não medem acurácia institucional, não cobrem todas as falhas
  concorrentes e não autorizam “100% correto”. A classificação comparativa foi
  concluída apenas em desenvolvimento sintético. A deduplicação permanece
  subdimensionada; pela decisão de não produzir gabarito humano, não haverá
  holdout confirmatório neste escopo.

O relatório histórico detalhado de contratos WF04/WF05 permanece em
`../n8n/workflows/Versão9/TEST_REPORT.md`.

## Atualização operacional de 01/09

- n8n recebeu healthcheck e foi observado `running healthy`;
- WF05 deixou de executar DDL no runtime e foi republicado;
- os seis workflows foram relidos após o deploy e tiveram paridade de lógica;
- carga classificatória híbrida: 40/40 HTTP 200 com concorrência 1; com
  concorrência 4, 18/40 HTTP 200 e 22/40 HTTP 429;
- as 20 execuções mais recentes eram sucessos do agendador WF06, porém sem
  decisões de IA novas; isso não equivale a E2E;
- naquele snapshot existiam 84 DLQs históricas não resolvidas. Em 02/09 elas e
  os 129 estados `ERRO_IA` foram reconciliados formalmente sem apagar o
  histórico; a captura pós-E2E de 03/09 confirma 0/0/0.

## Carga final de 03/09

- concorrência 1: 40/40 HTTP 200, 19,73 req/s e p95 35,30 ms;
- concorrência 4: 17/40 HTTP 200, 23/40 HTTP 429, saturação 57,5% e p95
  1.736,30 ms;
- erros 5xx: zero nos dois cenários;
- conclusão: usar pacing conservador; não alegar capacidade multiusuário ou
  eficácia científica.
