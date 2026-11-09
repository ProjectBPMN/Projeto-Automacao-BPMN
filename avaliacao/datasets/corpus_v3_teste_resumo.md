# Corpus de avaliação V3 — resumo de construção

> Este arquivo descreve um corpus sintético ainda pendente de validação humana. 
> Não contém predições da IA nem resultados de eficácia.

- Corpus lógico: `CORPUS-V3-TESTE-EFE4F26CB2`
- Versão: `dataset-v3.0.0-contrastes-agrupados`
- Split: `TESTE`
- Seed: `20260710`
- Chamados: `1200`
- Episódios pareados de deduplicação: `500`
- Desafios duplicados: `200`
- Desafios não duplicados difíceis: `300`
- Casos classificatórios: `200`
- Famílias de contraste: `25`
- Núcleos dedup: `100` (quatro por família)
- Realizações por núcleo: `5`

## Classes semânticas

- `DEMO`: 50
- `OBRA`: 50
- `SOB_DEMANDA`: 50
- `TRIAGEM_MANUAL`: 50

## Partições físicas de execução

As cinco realizações de um mesmo núcleo não podem compartilhar o mesmo `run_id` 
físico: caso contrário, tornam-se candidatas entre si e contaminam a tarefa de 
deduplicação. O corpus lógico deve agregar as dez partições abaixo.

- `CLASS-R01`: 40 chamados
- `CLASS-R02`: 40 chamados
- `CLASS-R03`: 40 chamados
- `CLASS-R04`: 40 chamados
- `CLASS-R05`: 40 chamados
- `DEDUP-R01`: 200 chamados
- `DEDUP-R02`: 200 chamados
- `DEDUP-R03`: 200 chamados
- `DEDUP-R04`: 200 chamados
- `DEDUP-R05`: 200 chamados

## Gates antes do benchmark

1. Dois revisores independentes, cegos às predições e aos rótulos um do outro,
   com adjudicação das divergências.
2. Auditoria dos 100 núcleos dedup e 40 núcleos classificatórios.
3. Auditoria estratificada de aproximadamente 200 textos renderizados.
4. Congelamento dos hashes deste manifesto, prompt, schema, código e configuração.
5. Executor adaptado para preservar o corpus lógico e usar um `run_id` por partição.

## Integridade

- SHA-256 JSONL: `26e692ba247ef7439b9a057873c7034318423214b9797b2dbe72f9f24e6801f0`
- SHA-256 catálogo: `4b2e9b69a4659588bca205180be3ce70f5b436f31d2b22f7a906b0d214afaef7`
- SHA-256 gerador: `b6dd63c93dc319f37c7a70fff0868560fac572a0583a9c174414a3c3713d9794`
