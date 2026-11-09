# Atualização de 15/07/2026

> **Documento histórico.** Registra o estado observado em 15/07 e não descreve
> a configuração vigente. A v1.8 substituiu v1.1/v1.4 e a cadeia operacional
> atual é `LOCAL → SECONDARY`, com `SECONDARY=gemini-3.5-flash`. Consulte
> `TEST_REPORT.md` e `estado_release_candidate_2026-07-16.md` antes de citar
> qualquer conclusão.

## Últimas modificações

- A suíte do `local_ai` voltou a executar com sucesso depois da correção dos imports relativos em `local_ai/tests`.
- O manifesto canônico de prompts/modelos foi regenerado e validado com `avaliacao/scripts/sincronizar_manifesto.py --check`.
- A validação estática dos seis workflows V9 passou sem divergências.
- Foi criada uma planilha consolidada em `avaliacao/resultados/resumo_validacoes_2026-07-15.csv` com os principais resultados técnicos e comparativos.
- Naquela revisão, o benchmark passou a aceitar `gemini-3.1-flash-lite` e se
  limitava a 15 RPM para reduzir o risco de 429. Esse valor não era garantia e
  não deve ser reutilizado sem conferir a cota ativa do projeto.

## Conclusões atuais

- O modelo local v1.4 não superou a baseline v1.1; houve regressão em classificação e no pipeline após o gate de localização.
- O benchmark remoto confirmatório ainda não pode ser usado como evidência científica forte porque o `gemini-3.5-flash` e o `gemini-2.5-flash` estavam sem quota no smoke observado.
- O `gemini-3.1-flash-lite` foi o único modelo Google que respondeu 200 naquele
  contrato mínimo. Isso não determinou a configuração posterior e não prova
  maior estabilidade geral ou eficácia.
- O projeto está estruturalmente íntegro, mas a comparação remota final ainda precisa ser executada em janela de cota válida para produzir resultado publicável.
