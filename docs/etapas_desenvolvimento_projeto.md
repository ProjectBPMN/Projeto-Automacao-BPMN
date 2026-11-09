# Etapas de desenvolvimento do projeto

**Revisão:** 26/08/2026

## Concluído como engenharia

1. GLPI, n8n, PostgreSQL e Mailpit conteinerizados localmente.
2. Evolução V1–V8 preservada em snapshots sanitizados/inativos com hashes.
3. V9 dividida em seis workflows gerados por builders.
4. Fila assíncrona, leases, retentativa, DLQ, telemetria e revisão humana.
5. Runtime local estruturado com Granite 97M + TF-IDF e bundle v1.8 congelado.
6. Registro de modelo, tentativa, decisão, evento, input e proveniência.
7. Testes de contratos, validação estática e paridade de deploy.
8. E2E sintético isolado WF06 → WF02 → WF03 com cleanup/restore.
9. Quarentena de linhas ligadas a experiências encerradas.
10. Remoção de segredos, backups, caches e binários do versionamento.

## Auditoria metodológica de 26/08

A seleção comparativa anterior foi invalidada. O gerador usava 32 moldes-fonte
por classe para criar 80 especificações nominais e 12 famílias-fonte para criar
200 episódios nominais. O agrupamento não reunia todos os derivados; o hash da
saída antiga também não reproduzia o corpus disponível.

Correções:

- dataset `desenvolvimento-local-v2.1.0` regenerado;
- grupo `source_dependency_group_sha256` em todas as linhas;
- 128 famílias-fonte no corpus completo; 111 famílias e 1.114 registros no
  estrato efetivamente submetido ao classificador; 12 famílias de deduplicação;
- config, launcher, executor, validador e testes alinhados ao V2.1;
- saída antiga marcada `INVALIDATED_POST_AUDIT`;
- documentação quantitativa antiga removida ou marcada como histórica.

## Resultado V2.1 parcial

A classificação comparou três embeddings, ablações e cinco classificadores em
35 configurações e foi recalculada por validador independente. Nenhum candidato
passou todos os gates; E5 + híbrido + SVM linear é apenas candidato provisório
`UNDERPOWERED` e não substituiu o runtime. A deduplicação foi bloqueada antes do
ajuste porque seis grupos por classe não comportam a separação exigida entre
ajuste e calibração.

## Pendente para ciência

1. ampliar famílias independentes, sobretudo deduplicação;
2. coletar dados reais autorizados;
3. manual de rótulos, dois revisores independentes cegos às predições e aos
   rótulos um do outro, com adjudicação das divergências;
4. pré-registro e planejamento amostral por grupo;
5. repetir seleção/calibração em dados adequados sem acesso ao holdout;
6. congelamento do candidato;
7. execução única no holdout institucional;
8. relatório com incerteza, calibração, risco-cobertura e subgrupos.

## Pendente para produção

Carga/concorrência, segurança, menor privilégio, rotação de segredos,
backup/restore, SLOs/alertas, homologação separada, rollback, drift e aceite
formal do processo.
