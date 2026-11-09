# Run invalidado por interferência concorrente

## Identificação

- Run: `CALQ-20260722T040044-Q1-R2`
- Protocolo: `calibracao-fila-v2.3.0`
- Início registrado: `2026-07-22 01:01:36.741424-03:00`
- Invalidação concluída: `2026-07-22 01:17:27.306302-03:00`
- Status final: `INVALIDADO_INTERFERENCIA_E2E`
- Natureza: evidência operacional inválida; não usar métricas deste run em tabelas,
  gráficos, seleção do WF06 ou comparação científica.

O teste foi interrompido porque uma validação E2E executou concorrentemente durante
a janela que deveria estar isolada. A mistura viola o protocolo de calibração e
impede atribuir latência, vazão ou falha exclusivamente ao tratamento `Q1-R2`.

## Escopo confirmado

O vínculo foi obtido diretamente de `dataset_controle`. Foram encontrados exatamente
12 tickets, todos com `split=CALIBRACAO`:

| Ticket | Estado no banco antes da invalidação | Status GLPI antes | Status final |
|---:|---|---:|---|
| 284 | `TRIAGEM_MANUAL` | 4 | `ERRO_IA` / GLPI 6 |
| 285 | `TRIAGEM_MANUAL` | 4 | `ERRO_IA` / GLPI 6 |
| 286 | `ATRIBUIDO_DEMO` | 2 | `ERRO_IA` / GLPI 6 |
| 287 | `FECHADO_OBRA` | 6 | `ERRO_IA` / GLPI 6 |
| 288 | `TRIAGEM_MANUAL` | 4 | `ERRO_IA` / GLPI 6 |
| 289 | `TRIAGEM_MANUAL` | 4 | `ERRO_IA` / GLPI 6 |
| 290 | `FILA_IA_LIBERADA` | 4 | `ERRO_IA` / GLPI 6 |
| 291 | `TRIAGEM_MANUAL` | 4 | `ERRO_IA` / GLPI 6 |
| 294 | `TRIAGEM_MANUAL` | 4 | `ERRO_IA` / GLPI 6 |
| 295 | `FILA_IA_LIBERADA` | 4 | `ERRO_IA` / GLPI 6 |
| 296 | `FILA_IA_LIBERADA` | 4 | `ERRO_IA` / GLPI 6 |
| 297 | `PENDENTE_FILA_IA` | 1 | `ERRO_IA` / GLPI 6 |

`ERRO_IA` foi usado como estado terminal fail-closed para impedir reprocessamento.
Ele não significa que o modelo falhou. Os campos `ultimo_erro_ia` e
`fila_ultimo_erro` registram explicitamente
`RUN_INVALIDADO_INTERFERENCIA_E2E_NAO_E_FALHA_MODELO`.

## Ações de contenção e auditoria

1. Os 12 IDs foram comparados com seus títulos no GLPI antes de qualquer alteração.
2. Onze tickets abertos foram fechados pela API do GLPI; o ticket 287 já estava
   fechado. A leitura posterior confirmou status GLPI 6 nos 12 tickets.
3. Uma única transação atualizou somente os tickets vinculados ao run, limpou os
   campos de disponibilidade e reserva da fila e encerrou aprovações pendentes.
4. Foram gravados 12 registros em `workflow_eventos`, um por ticket, com workflow
   `CALIBRACAO_FILA`, ação `INVALIDAR_INTERFERENCIA_E2E`, estado anterior e estado
   novo `ERRO_IA`.
5. `experimentos_avaliacao` recebeu `validation_status` igual a
   `INVALIDATED_E2E_INTERFERENCE`, `scientific_result=false` e
   `confirmatory_eligible=false`.
6. Nenhuma linha de dataset, decisão, tentativa, evento ou artefato foi apagada.

Durante o encerramento, o processo de calibração ainda ativo substituiu o status do
experimento por `FALHOU`. Após confirmar que o processo havia terminado, o status
foi restaurado para `INVALIDADO_INTERFERENCIA_E2E`; essa corrida também ficou
registrada em `generation_config` por `status_race_corrected=true` e
`status_race_previous_value=FALHOU`.

## Verificação final da fila

Na leitura final:

- tickets ativos na fila: `0`;
- resíduos E2E excluídos da contagem operacional: `0`;
- tickets operacionais ativos após excluir E2E: `0`;
- tickets deste run fechados, em `ERRO_IA` e sem timestamps de fila ativos: `12/12`;
- eventos específicos de invalidação: `12/12`.

Uma nova calibração deve usar outro `run_id` e outro diretório de resultados. Este
diretório deve permanecer preservado como trilha negativa de auditoria.
