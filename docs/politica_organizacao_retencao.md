# Política de organização, retenção e limpeza

**Estado:** canônico em 10/09/2026

Esta política mantém o projeto reproduzível sem confundir código, estado local,
evidência corrente e material histórico. “Duplicado” por hash não significa
automaticamente “descartável”: resultados podem ser cópias deliberadas de uma
mesma unidade usadas em execuções distintas.

## Estrutura e autoridade

| Área | Conteúdo | Tratamento |
|---|---|---|
| `n8n/workflows/Versão9/` | builders, JSON e testes V9 | canônico; editar o builder e regenerar o JSON |
| `n8n/history/` | versões anteriores sanitizadas | histórico; não publicar nem reativar por engano |
| `local_ai/` | serviço, modelos e testes | código canônico; modelos locais são regeneráveis, mas caros |
| `avaliacao/config/` | protocolos e parâmetros | congelar por hash antes da execução correspondente |
| `avaliacao/resultados/` | evidência e relatórios | preservar por execução; nunca sobrescrever rodada congelada |
| `avaliacao/runtime/` | estado local, backups e observações | não publicar; aplicar retenção somente após inventário |
| `backups/` e `glpi/backups/` | recuperação operacional | protegidos; remoção exige cópia validada e decisão explícita |
| `docs/` | documentação corrente e snapshots | a hierarquia em `SOURCE_OF_TRUTH.md` resolve divergências |

## Limpeza autorizada automaticamente

Somente caches sem valor científico ou operacional, como `.pytest_cache` e
`__pycache__`, podem ser removidos sem uma decisão de retenção adicional. Logs
de uma execução, bancos, exports, manifests, modelos, ambientes, imagens,
volumes, backups e resultados não são “lixo” apenas por serem grandes ou
ignorados pelo Git.

Em 10/09/2026 foram removidos 16 diretórios de cache fora de `.venv`,
recuperando 4.181.272 bytes (3,988 MiB). Foram preservados `.venv`, `.git`,
modelos, backups, resultados, observações e logs de evidência.

## Retenção pendente

Os grandes backups do volume n8n, o banco SQLite do n8n, o backup integral do
GLPI e modelos locais devem receber prazo, proprietário, teste de restauração e
destino externo antes de qualquer exclusão. Resultados históricos idênticos por
SHA-256 podem ser consolidados somente depois de registrar quais execuções os
referenciam e manter ao menos uma cópia imutável verificável.

## Inventário reproduzível

`scripts/gerar_inventario_repositorio.py` enumera todo arquivo rastreado ou não
ignorado, registra tamanho e SHA-256 e classifica sua destinação. Binários são
auditados por identidade, estrutura e gerador quando disponível; não se alega
leitura semântica linha a linha de conteúdo binário.
