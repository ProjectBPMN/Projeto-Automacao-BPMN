# Validação E2E consolidada de WF04 e WF05

Esta é uma validação técnica automatizada, exclusivamente sintética e não confirmatória. Ela comprova o contrato operacional dos links; não mede eficácia científica do classificador.

## Resultado válido final

O run `VALIDACAO-POSTS-E2E-20260722T040652Z` foi aprovado:

- tickets sintéticos: referência `302` e alvo `303`;
- reservas do oráculo: `7` (WF05) e `8` (WF04);
- GET de WF04: HTTP `200`, exibiu formulário e não alterou o estado;
- POST válido de WF04: HTTP `202`, mudou o alvo uma única vez de `AGUARDANDO_APROVACAO_FISCAL` para `DUPLICADO_FECHADO`;
- replay de WF04: HTTP `409`, sem nova transição de negócio e com auditoria da tentativa bloqueada;
- GET de WF05: HTTP `200`, exibiu formulário e não alterou o estado;
- POST válido de WF05: HTTP `200`, concluiu uma única avaliação com fonte `ORACULO_GABARITO`;
- replay de WF05: HTTP `403`, sem nova transição;
- tokens, nonces e segredos não foram persistidos nos artefatos.

## Histórico das tentativas

| Run | IDs | Resultado | Uso na conclusão |
|---|---:|---|---|
| `VALIDACAO-POSTS-E2E-20260722T040208Z` | `292`, `293` | Abortado antes dos webhooks por corrida do WF01 na preparação | Não usar |
| `VALIDACAO-POSTS-E2E-20260722T040402Z` | `298`, `299` | Abortado antes dos webhooks por erro do leitor do ID do cursor | Não usar |
| `VALIDACAO-POSTS-E2E-20260722T040445Z` | `300`, `301` | Aprovado; captura inicial não aguardava a auditoria assíncrona do replay | Evidência auxiliar |
| `VALIDACAO-POSTS-E2E-20260722T040652Z` | `302`, `303` | Aprovado com espera da auditoria assíncrona | Evidência técnica final |

As duas tentativas abortadas não chegaram aos POSTs de WF04 ou WF05 e não podem ser contadas como repetições do teste funcional.

## Isolamento e limpeza

O WF01 preencheu campos de fila em alguns tickets sintéticos durante as tentativas. Foi executado cleanup restrito aos IDs `292`, `293`, `298`, `299`, `300`, `301`, `302` e `303`, sempre condicionado ao prefixo exato `[TESTE_AUTOMATIZADO_E2E_WF04_WF05]`.

O run final começou antes de chegar o aviso de que uma calibração de vazão estava ativa. Os tickets `302` e `303` não foram processados por WF06 e não produziram decisão de IA fora do contexto E2E; porém `302` permaneceu `PENDENTE_FILA_IA` entre `01:06:54` e `01:09:18` (America/Sao_Paulo). Portanto, este run continua válido para o contrato isolado de WF04/WF05, mas não pode ser usado como evidência de vazão, e qualquer repetição de calibração que use profundidade global nesse intervalo deve ser marcada como potencialmente contaminada.

Após o cleanup:

- todos os oito tickets estão fechados (`status_num=6`);
- `301` e `303` permanecem `DUPLICADO_FECHADO`;
- os demais estão `VALIDACAO_E2E_ENCERRADO`;
- todos os campos `fila_*` foram limpos;
- a contagem de resíduos desses IDs na fila é `0`;
- oito eventos `REMOVER_RESIDUO_E2E_DA_FILA` foram gravados para auditoria.

O arquivo `resultado.json` contém os estados antes/depois e os códigos HTTP do run final. `tentativas_consolidadas.json` contém o histórico estruturado das quatro tentativas.

O executor do ensaio agora bloqueia novas execuções enquanto existir experimento com status `CALIBRANDO`.
