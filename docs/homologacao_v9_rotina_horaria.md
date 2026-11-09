# Rotina horária V9

Modelo da automação: GPT-5.6 Terra, esforço Medium, uma execução por hora,
diretamente neste projeto. Não treinar modelos nem modificar workflows na rotina.

1. Executar `.venv\Scripts\python.exe avaliacao\operacional\check_homologation.py --repair`.
   O script lê os dois artefatos, consulta o processo exato e emite JSON compacto.
   `QUIET` encerra o ciclo sem mensagem. Alertas exigem aviso apenas se forem
   novos ou exigirem ação. Não reiniciar processo existente, mesmo com status
   desatualizado; não encerrar instâncias duplicadas automaticamente.
2. `FINALIZE` exige ao menos três janelas reais e reconciliação. Registrar os
   três resultados individualmente: cobertura temporal, número de decisões,
   todos os checks SLO e drift. Zero decisões não mede taxa de erro, latência
   de inferência nem drift. Manter `INSUFFICIENT_DATA` e a reprovação histórica
   do backup da primeira janela. O reparo posterior não apaga a reprovação.
3. Executar `capture_runtime_state.py --output` em arquivo novo sob
   `avaliacao/resultados/operacional/`. Confirmar os três contadores da mesma
   instrução SQL: `active_queue`, `open_dlq`, `erro_ia`.
4. Executar uma vez os testes `avaliacao/operacional/tests` e a validação
   `n8n/workflows/Versão9/validate_v9_static.py`. Não repetir a suíte global.
5. Atualizar o relatório de homologação em docs, README e SOURCE_OF_TRUTH,
   citando artefatos, hora, limitações e quaisquer lacunas. Não declarar
   `scientific_ready`, `production_ready` ou eficácia institucional.
6. Notificar o resultado final e remover a automação ao concluir. Preservar o
   daemon e evidências. Não criar outro monitor para uma série já finalizada.

## Estado verificado em 14/09/2026

A finalização inicial já ocorreu em 11/09 e a automação antiga foi removida.
O novo agendamento solicitado em 14/09 foi conferido em Terra Medium/hora.
A confirmação final terminou com 53 testes e validação estática aprovados,
fila/DLQ/ERRO_IA em zero, e a automação foi removida após cumprir seu objetivo.
O verificador e esta rotina permanecem disponíveis para nova série autorizada.
As primeiras três janelas tiveram 240 observações cada, cobertura/reconciliação
completa e zero decisões. Janela 1: SLO `FAIL` por idade do backup; janelas 2/3:
`INSUFFICIENT_DATA`; drift das três: `INSUFFICIENT_DATA`.

A série posterior contém lacuna de 160.392,27 segundos entre
2026-09-12T23:22:54Z e 2026-09-14T19:56:06Z (44h33m12s). Ela não atravessa as
primeiras três janelas, mas impede descrever toda a série até 14/09 como contínua.
