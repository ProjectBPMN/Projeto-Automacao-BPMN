# Estado da candidata de release — 16/07/2026

> [!WARNING]
> **Snapshot histórico, superado pela auditoria de 26/08/2026.** A seleção
> citada neste documento não sustenta ranking atual: derivados de poucas
> famílias-fonte não ficaram integralmente no mesmo grupo. Toda classificação
> permanece sintética e a deduplicação antiga é subdimensionada. Use
> `auditoria_critica_completa_2026-08-26.md` e
> `resposta_professor_2026-08-26.md` como estado canônico.

> **SNAPSHOT HISTÓRICO.** Este arquivo não representa sozinho a revisão de
> 17/08/2026. Desde então, V1–V8 foram preservadas em `n8n/history`, a seleção
> comparativa v1.3 de 90 configurações terminou com recomputação por validador
> independente, no mesmo corpus de desenvolvimento, e a V9 corrente passou em
> 913 verificações estáticas, nove contratos e preflight sem mutação. O E2E
> mutante integral da revisão exata, a calibração isolada válida do WF06 e a
> confirmação científica permanecem pendentes. Consulte
> `estado_projeto_2026-08-17.md` para o estado atual.

## Conclusão

O projeto está próximo de uma versão publicável no GitHub: a estrutura de
execução, testes, tutorial e política de segredos estão organizados. Ainda não é
a versão final do experimento científico. O código pode ser apresentado como
software de pesquisa em estágio de release candidate, com resultados de
desenvolvimento claramente rotulados como não confirmatórios.

## O que está concluído

- seis workflows V9 ativos e rastreados nó a nó;
- fila WF06 com lote, lease, espaçamento, backoff e dead letter;
- gateway com modelo congelado em benchmark e auditoria de tentativa/fallback;
- modelo local v1.8, Granite 97M PyTorch FP32, vetor 384d;
- limiares distintos para duplicado, não duplicado e abstenção;
- proteção assimétrica contra manutenção enviada para OBRA;
- confirmação fiscal preservada e oráculo externo restrito a teste sintético;
- transições fiscais positiva e negativa validadas no mecanismo anterior; após
  o endurecimento, as páginas `GET` de confirmação responderam sem mutação e os
  endpoints de decisão passaram a aceitar somente `POST`;
- 56 testes locais, 79 testes de avaliação, 18 subtestes e validador V9;
- integração real dos componentes com três tickets sintéticos;
- segredos externos removidos do iniciador e exemplos de ambiente adicionados.

## O que falta para uma alegação científica final

1. Congelar o holdout e abri-lo uma única vez.
2. Obter rótulos independentes/adjudicados conforme o protocolo amostral.
3. Executar a comparação pareada da v1.8 com Gemini sem bloqueio de rede, sem
   fallback e com a cota real observada no AI Studio.
4. Executar a matriz de calibração de vazão do WF06 em repetições suficientes.
5. Estimar intervalos por núcleo/episódio; as 30 redações naturalísticas não são
   30 casos semânticos independentes.

## Decisão sobre provedores

A sequência operacional foi reduzida para `LOCAL,SECONDARY`, com
`gemini-3.5-flash` como contingência. Os demais provedores não participam do
caminho ativo. Ainda não é possível eliminar a contingência Gemini por alegação
de superioridade: a v1.8 não possui comparação pareada válida contra Gemini 3.5
nem amostra válida contra DeepSeek.

## Estado de publicação

- GitHub como software/reprodutibilidade: pronto após uma última revisão manual
  do que será selecionado para o primeiro commit;
- operação piloto local: pronta, mantendo revisão humana e monitoramento;
- artigo com eficácia final: pendente;
- afirmação “modelo local é superior ao Gemini”: não sustentada pelos dados
  atuais.
