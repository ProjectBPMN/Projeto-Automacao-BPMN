# Piloto em sombra local

> Estado do projeto em 01/09/2026: a revisão humana foi retirada do escopo.
> Este módulo permanece implementado e testado, mas o piloto humano descrito
> abaixo não será executado. Ele não deve ser substituído por autoaprovação do
> modelo; sem revisores, não há rótulo confirmatório.

Este módulo registra previsões para avaliação prospectiva, mas **não aplica
nenhuma decisão ao GLPI**. Ele só usa um banco SQLite local. Não há cliente
HTTP, adaptador do GLPI, chamada ao n8n, conexão PostgreSQL nem comando de
mudança externa.

Uma decisão `CONFIRMED` significa apenas que um rótulo humano de pesquisa foi
concluído. Ela nunca autoriza automação operacional.

## Barreiras de segurança

- o kill switch nasce ligado (`fail closed`);
- capturas feitas nesse estado ficam em `HELD_KILL_SWITCH`;
- liberar o kill switch habilita somente a fila local de revisão;
- a fila omite previsão, confiança, modelo e pareceres anteriores;
- dois revisores diferentes devem rotular o caso de modo independente;
- concordância entre os dois encerra o rótulo; divergência, rejeição ou
  abstenção exige um terceiro adjudicador, distinto dos revisores;
- todas as mutações locais usam chave de idempotência e transação SQLite;
- eventos são encadeados por SHA-256 e podem ser verificados integralmente;
- rollback só invalida o registro local e nunca pressupõe rollback externo;
- exportações são marcadas como `research_evaluation_only` e
  `external_application_allowed=false`.

O ledger é resistente a alterações acidentais e detecta modificação dos seus
eventos. Ele não substitui armazenamento imutável, assinatura externa, controle
de acesso do sistema operacional ou backup institucional.

## Fluxo obrigatório

1. Inicializar um banco novo. O kill switch permanecerá ligado.
2. Capturar previsões sem copiar o texto sensível do chamado: são armazenados
   apenas a referência local e hashes do conteúdo/resultado.
3. Conferir a fila e, após autorização do responsável pelo piloto, liberar
   somente a revisão local usando o reconhecimento literal exigido.
4. Revisor 1 e revisor 2 submetem `LABEL`, `REJECT` ou `ABSTAIN`. Para `LABEL`,
   `--label` é obrigatório.
5. Se houver divergência, um terceiro humano adjudica. O sistema rejeita o uso
   de um dos revisores como adjudicador.
6. Verificar o ledger e calcular métricas. O resultado continua sendo evidência
   de piloto, não resultado confirmatório e não comando operacional.

## Uso

Execute a partir da raiz do repositório. Use um caminho de banco próprio para
cada piloto pré-registrado.

```powershell
python -m avaliacao.piloto_sombra --db avaliacao/runtime/piloto.sqlite3 init `
  --actor responsavel-piloto

python -m avaliacao.piloto_sombra --db avaliacao/runtime/piloto.sqlite3 status

python -m avaliacao.piloto_sombra --db avaliacao/runtime/piloto.sqlite3 capture `
  --ticket-ref GLPI-123 --task classification --label OBRA --confidence 0.82 `
  --model-id candidato-congelado --model-version sha256-do-bundle `
  --trace-id trace-123 --input-sha256 <sha256> --prediction-sha256 <sha256> `
  --subgroup campus-a --idempotency-key capture-GLPI-123-v1
```

A liberação exige declarar explicitamente que o fluxo continua sem capacidade
de mutação externa:

```powershell
python -m avaliacao.piloto_sombra --db avaliacao/runtime/piloto.sqlite3 `
  release-kill-switch --actor responsavel-piloto --reason "início autorizado" `
  --acknowledge SHADOW_ONLY_NO_GLPI_MUTATION `
  --idempotency-key release-piloto-001
```

As revisões recebem somente a visão cegada devolvida por `queue`:

```powershell
python -m avaliacao.piloto_sombra --db avaliacao/runtime/piloto.sqlite3 queue

python -m avaliacao.piloto_sombra --db avaliacao/runtime/piloto.sqlite3 review `
  --case-id <uuid> --reviewer especialista-1 --decision LABEL --label OBRA `
  --rationale "evidência observada no chamado" --idempotency-key rev1-<uuid>
```

O segundo revisor usa outro identificador. Em divergência:

```powershell
python -m avaliacao.piloto_sombra --db avaliacao/runtime/piloto.sqlite3 adjudicate `
  --case-id <uuid> --adjudicator especialista-3 --outcome CONFIRM --label DEMO `
  --rationale "adjudicação independente" --idempotency-key adj-<uuid>
```

## Encerramento e rollback

O encerramento seguro começa acionando o kill switch. A operação suspende todos
os casos abertos de maneira atômica; conexões SQLite são fechadas ao fim de cada
comando.

```powershell
python -m avaliacao.piloto_sombra --db avaliacao/runtime/piloto.sqlite3 `
  engage-kill-switch --actor responsavel-piloto --reason "encerramento seguro" `
  --idempotency-key shutdown-piloto-001

python -m avaliacao.piloto_sombra --db avaliacao/runtime/piloto.sqlite3 verify-audit
```

Para invalidar um caso, use `rollback`. Isso muda apenas o ledger local para
`ROLLED_BACK`; como nunca houve aplicação externa, a saída declara
`external_rollback_required=false`.

Antes de arquivar o piloto, copie de forma controlada o arquivo SQLite e os
arquivos `-wal`/`-shm` se existirem, valide a cópia e preserve o hash fora do
diretório de execução. Não exponha referências de chamados ou rótulos humanos
em repositórios públicos.

## Saídas para pesquisa

`metrics` informa cobertura de revisão, concordância, erros críticos e recortes
por tarefa/subgrupo. Amostras pequenas ou dependentes não sustentam conclusão
de segurança.

`export-research-labels` devolve um envelope com contagem, hash da exportação,
hash de cabeça do ledger e os marcadores obrigatórios. Não existe comando para
converter essa exportação em atualizações de chamado.
