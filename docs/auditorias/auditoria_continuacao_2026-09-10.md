# Continuação da auditoria V9 — 2026-09-10

## Estado executivo

O E2E final, a confirmação atômica da fila/DLQ e a inspeção visual atual de
n8n/GLPI foram concluídos em 10/09/2026. Em 11/09/2026 a coleta separada de
três janelas técnicas intradiárias locais/sintéticas também foi concluída, após
as três durações de quatro horas e a defasagem de reconciliação. Essa coleta
verifica o mecanismo técnico; não substitui observação longitudinal de produção
nem reclassifica telemetria legada como evidência válida.

## Evidência verificada nesta rodada

- `validate_v9_static.py`: aprovado.
- Novo E2E final: terminal `TRIAGEM_MANUAL`, duas reservas, duas decisões, duas
  tentativas, DLQ zero, sem fallback, cleanup completo, chamado sintético
  removido e controlador/perfil restaurados exatamente. Evidência:
  `avaliacao/resultados/e2e-pipeline-local-v1.8.0-20260910-final.json`.
- Capturas atômicas antes e depois do E2E: `erro_ia=0`, `active_queue=0` e
  `open_dlq=0`.
- Navegador atual: sessão autenticada do n8n com seis workflows, WF06 publicado
  e execuções recentes visíveis como `Success`; login GLPI com a conta técnica e
  lista de chamados aberta. Nenhum chamado foi criado ou editado pelo navegador.
- 41 testes localizados e 17 subtestes de E2E, recuperação e integridade do
  monitoramento: aprovados em 10/09/2026.
- Último E2E preservado: `passed=true`, terminal `TRIAGEM_MANUAL`, duas
  reservas, duas tentativas, DLQ zero, controlador e perfil restaurados.
- O contexto Docker ativo estava apontando para `nuvem`; os recursos vazios
  criados pela tentativa foram removidos desse contexto. Nenhum dado remoto
  preexistente foi alterado.
- O Docker Desktop local foi recuperado e os containers operacionais e de
  homologação estavam ativos e saudáveis no contexto fixo `desktop-linux`.
- A tentativa atual, às 03:30 BRT de 10/09/2026, reproduziu o erro do Docker
  Desktop 4.79.0 no socket AF_UNIX `dockerInference`. O inicializador voltou a
  selecionar o contexto remoto `nuvem`; nenhuma operação de criação, alteração
  ou consulta de dados do projeto foi executada nesse host.
- Os endpoints locais `:5678`, `:9180` e `:8090` responderam. O Granite 97M foi
  aquecido e conferido por dimensão, revisão e hash; o serviço permaneceu
  corretamente com `scientific_ready=false`.
- O ambiente científico estava com uma instalação interrompida de `pandas` e
  sem `SHAP`/`XGBoost`. As versões congeladas em
  `local_ai/requirements-benchmark.txt` foram restauradas. A validação
  independente da tarefa de classificação foi então aprovada como
  `VALID_PARTIAL_TASK_SCOPE`: 35 configurações, 38.990 predições OOF, 175
  dobras, métricas/ranking recalculados e um finalista XAI. O próprio validador
  manteve `development_only=true` e `confirmatory_eligible=false`.
- A documentação voltou a referenciar, para essa rodada congelada, o arquivo
  `selecao_modelos_supervisionados_v2.json` e o hash
  `3a58410ecbe440b3a759c2673a9f4de5e9329dcae78e18e7b1d2da6cdda73c3e`.
  A configuração 2.1.1 de classificação é posterior/prospectiva e não pode
  revalidar retroativamente a execução de 26/08.
- A revisão independente encontrou e a implementação corrigiu duas lacunas:
  todas as chamadas Docker do E2E agora fixam `desktop-linux`, validam que seu
  endpoint é local e recusam `ssh://`, `tcp://` e HTTP(S); o coletor agora
  reconsulta decisões desde o primeiro intervalo válido, deduplica por ID e
  exige um snapshot PostgreSQL cumulativo válido em ou após cinco minutos do
  fim da janela. Tempo transcorrido com o banco indisponível não satisfaz essa
  reconciliação. Isso evita perder uma decisão criada antes do corte mas
  confirmada depois do snapshot.
- A revisão independente adicional encontrou que o estado agregado ignorava a
  saúde Docker e que fila/DLQ eram consultadas em instantes distintos. A
  implementação agora exige os quatro containers locais em execução e com
  saúde aceitável, fixa `desktop-linux` também no coletor e consulta as três
  contagens em uma única instrução SQL. Os testes localizados foram ampliados.
- Homologação temporal final em
  `avaliacao/runtime/monitoring-homolog-20260910-v2/windows.json`: três janelas
  completas, 240 observações cada, cobertura de decisão/reconciliação completa
  e zero decisões únicas em cada intervalo. A disponibilidade de todos os
  serviços foi 1,0 nos probes amostrados; isso não é uptime contínuo. Drift,
  p95 de inferência/espera, taxa de erro e demais métricas sem decisões ficaram
  `INSUFFICIENT_DATA`. A janela 1 falhou o SLO técnico proposto apenas por
  `backup.restore_age_hours=206,05` acima de 168; as janelas 2 e 3 são
  `INSUFFICIENT_DATA`. Os limiares são proposta pré-registrada, não política
  institucional aprovada.
- Captura atômica final em 11/09:
  `avaliacao/resultados/operacional/estado-runtime-final-homolog-v2-20260911.json`
  registrou `ERRO_IA=0`, fila ativa `=0` e DLQ aberta `=0`, sem exclusão de
  histórico. Foram aprovados 45 testes de `avaliacao/operacional/tests` e
  `n8n/workflows/Versão9/validate_v9_static.py`. Essas evidências não confirmam
  semântica, eficácia institucional ou prontidão produtiva.

## Situação científica

A avaliação disponível é exclusivamente de desenvolvimento com rótulos proxy:

- dataset sintético: `true`;
- uso: `development_only=true`;
- elegibilidade confirmatória: `false`;
- classificação: 1.114 registros e 111 grupos independentes;
- deduplicação: 1.000 pares, mas somente 12 grupos independentes;
- a tarefa de deduplicação é inviável no protocolo agrupado atual.

Comparação homogênea no recorte híbrido com Granite 97M, sempre OOF agrupado e
não confirmatório:

| Classificador | Macro-F1 | Cobertura automática | Risco seletivo | Situação |
|---|---:|---:|---:|---|
| Árvore de decisão | 0,6045 | 0,0000 | não estimável | desenvolvimento |
| SVM linear | 0,7891 | 0,6203 | 0,0738 | desenvolvimento |
| MLP | 0,7903 | 0,4048 | 0,0754 | desenvolvimento |
| XGBoost | 0,6768 | 0,0000 | não estimável | desenvolvimento |
| Regressão logística | 0,7755 | 0,4533 | 0,0594 | desenvolvimento |

O maior valor pontual global foi obtido por
`classification__hybrid__multilingual_e5_small__linear_svm`, com macro-F1
0,7987, cobertura automática 0,6086 e risco seletivo 0,0693. O candidato segue
`UNDERPOWERED`: os intervalos de confiança se sobrepõem e nenhum vencedor foi
qualificado pelos gates pré-registrados.

O SHAP (`LinearExplainer`) foi concluído para esse candidato provisório. O
resíduo máximo de aditividade foi aproximadamente `5,77e-15`, confirmando a
coerência matemática da decomposição. Isso explica associações no escore-base
antes da calibração e dos limiares; não demonstra causalidade, validade externa,
justiça, correção semântica ou eficácia institucional.

Os IC95% publicados são bootstrap agrupado nominal por configuração. Como o
candidato provisório foi escolhido depois de explorar 35 configurações, esses
intervalos não corrigem a incerteza pós-seleção. A correção de Holm cobre apenas
os oito contrastes pré-especificados. Também não há atributos institucionais de
subgrupo nem prevalências representativas: equidade/fairness não foi avaliada,
e a ausência dessa análise não é evidência de ausência de viés.

## Organização e limpeza

O inventário do workspace encontrou 56.578 arquivos (6,733 GiB), dos quais 975
estavam rastreados e 26 não rastreados. Grande parte do volume pertence a
ambiente virtual, modelos, backups e evidências, que foram preservados. Foram
removidos somente 16 diretórios `.pytest_cache`/`__pycache__` fora de `.venv`,
recuperando 4.181.272 bytes (3,988 MiB). A política de retenção está em
`docs/politica_organizacao_retencao.md`; exclusão de backups, modelos ou
resultados exige decisão explícita e teste de restauração.

## Condições obrigatórias ainda pendentes

1. Obter rótulos independentes, adjudicados por especialistas, em holdout
   institucional não usado em desenvolvimento. Sem isso não existe resultado
   científico confirmatório nem demonstração honesta de “melhor modelo”.
2. Aumentar as famílias independentes de deduplicação. Com 12 grupos, a seleção
   agrupada de árvore, SVM, MLP e XGBoost permanece inviável.

## Declarações de prontidão

- `scientific_ready=false`
- `production_ready=false`
- `semantic_correctness_confirmed=false`
- `browser_validation_current=true`
- `three_new_observation_windows_complete=true`
- `production_slo_estimated=false`
- `final_e2e_current=true`

## Continuidade automática

A coleta de `avaliacao/runtime/monitoring-homolog-20260910-v2` foi encerrada
tecnicamente com a captura final e as validações localizadas. Seu daemon e
evidências são preservados; a automação de acompanhamento pode ser removida.

### Confirmação em 14/09/2026

A captura `estado-runtime-fechamento-homolog-20260914.json` confirmou novamente
fila ativa, DLQ aberta e ERRO_IA em zero na mesma instrução SQL. Foram aprovados
53 testes operacionais e a validação estática V9. O resumo
`resumo-homolog-v2-fechamento-20260914.json` registra o daemon exato único,
14 janelas técnicas acumuladas, 14 com cobertura temporal e zero com todos os
SLOs aprovados. Uma lacuna posterior de 44h33m12s não atravessa as primeiras
três janelas. O fechamento e os limites de interpretação estão em
`docs/homologacao_v9_confirmacao_2026-09-14.md`.
