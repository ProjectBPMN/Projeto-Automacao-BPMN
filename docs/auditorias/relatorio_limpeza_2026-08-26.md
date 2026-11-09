# Relatório de organização e limpeza — 26/08/2026

## Resultado

Foram retirados do versionamento 15.874 arquivos, somando 524.572.641 bytes
(500,27 MiB no snapshot Git). A ação foi feita no índice do Git; backups,
runtime e memória local que ainda eram úteis permaneceram no disco e agora são
ignorados. Arquivos sensíveis que já não estavam fisicamente presentes
continuam marcados para remoção do repositório.

| Área | Arquivos retirados do versionamento |
|---|---:|
| backup integral do GLPI | 15.635 |
| sessões/backups n8n | 135 |
| runtime/cache local de IA | 76 |
| backups redundantes V1–V8 | 24 |
| `.env`/export de credenciais | 3 |
| memória local do Codex | 1 |
| **Total** | **15.874** |

O [inventário reproduzível do snapshot publicável](inventario_arquivos_versionados_2026-08-26.md)
enumera 956 arquivos rastreados ou não ignorados, com tamanho, SHA-256, papel e
destinação recomendada. Ele não inclui backups/runtimes ignorados e não implica
que cada binário foi revisado semanticamente linha a linha.

## Preservado

- código, builders e seis workflows V9;
- arquivo público V1–V8 em `n8n/history/`;
- datasets, manifests, predições e bundles necessários à auditoria;
- Docker/compose, plugin GLPI, schemas e testes;
- configurações `.env.example` sem valores reais;
- backups locais no disco, sem exclusão física ampla.

## Justificativa

Backups integrais, dumps, vendor do GLPI, binários/DLLs, caches de embeddings e
exports runtime não pertencem ao código-fonte. Eles aumentavam tempo de clone,
superfície de segredo e ambiguidade sobre qual workflow era canônico. O
histórico V1–V8 foi mantido por um pacote específico sanitizado, inativo e
validado, evitando depender das cópias redundantes em `backups/workflows/`.

## Proteções adicionadas

O `.gitignore` cobre:

- `.env` e `.env.local`, preservando apenas exemplos;
- `backups/n8n/**`, `backups/workflows/**` e `glpi/backups/**`;
- `local_ai/runtime/**` e modelos baixados, salvo manifesto;
- export de credenciais n8n;
- caches Python/testes, PIDs, bancos e binários locais;
- `.codex/Memória.md`.

## Itens mantidos apesar do tamanho

Resultados científicos e datasets continuam ocupando espaço porque permitem
recálculo/auditoria. Há várias rodadas históricas `local-only` e arquivos OOF.
Eles não foram apagados automaticamente: uma política futura deve definir quais
resultados são citados, qual retenção é obrigatória e quais bundles vão para um
registro externo com SHA-256.

## Limite da limpeza

Retirar um segredo do estado atual do Git não o elimina do histórico anterior.
O token local encontrado em `local_ai/run_server.py` foi removido do código e
rotacionado em 27/08/2026; o novo valor permaneceu somente no ambiente local
ignorado. Outros tokens/senhas potencialmente expostos ainda devem ser
rotacionados conforme inventário institucional. Reescrever todo o histórico Git
seria uma ação destrutiva e não foi executada. A exclusão física dos backups
locais também não foi feita, para preservar recuperação.
