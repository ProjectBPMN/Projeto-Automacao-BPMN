# Avaliação confirmatória de deduplicação

Este módulo implementa a infraestrutura do estudo; ele não contém famílias
reais, não fabrica gabarito e não abre o holdout por conta própria.

> Estado em 01/09/2026: o projeto decidiu não realizar verificação humana nem
> em pares. Como as garantias abaixo exigem gabarito independente, o módulo
> permanece bloqueado e não deve ser usado com rótulos sintéticos como se fosse
> confirmação.

## Garantias implementadas

- Só importa famílias marcadas `REAL_INSTITUTIONAL`, com proveniência,
  atestação de independência, duas revisões cegas e adjudicação independente
  quando há discordância.
- Impede reutilização exata de grupo, registro ou conteúdo e permite confrontar
  o holdout com hashes de exclusão do desenvolvimento.
- Calcula o limite unilateral exato de Clopper--Pearson. Com zero eventos,
  confiança de 95% e gate estrito `<2%`, o mínimo é **149 exposições
  independentes efetivas**. Prevalência, abstenção, perdas e correlação residual
  elevam o recrutamento necessário.
- Congela dataset, manifesto, candidato, configuração, hipóteses, métricas,
  subgrupos, gates e aprovações por SHA-256 antes da avaliação.
- Liga o ledger ao hash do dataset. A reserva exclusiva ocorre antes de ler ou
  verificar o dataset/candidato; sucesso, falha ou interrupção consome a única
  abertura. Um segundo claim exclusivo consome a primeira tentativa de registrar
  predições, inclusive quando o bundle é inválido.
- Calcula Brier, log loss, ECE com número de bins congelado, risco-cobertura,
  subgrupos descritivos e erros críticos com limite exato unilateral.

SHA-256 detecta alteração acidental e torna a trilha reproduzível, mas não é
assinatura digital. Proteção contra alteração maliciosa exige copiar o
pré-registro congelado e seu hash para um repositório externo, institucional e
com carimbo de tempo antes da abertura.

## Sequência operacional

1. Preencher o template de família com dados institucionais protegidos e
   reunir uma família por linha em JSONL. O template, por conter placeholders,
   é deliberadamente inválido para execução.
2. Importar o registro real de modo imutável:

   `python avaliacao/scripts/gerenciar_confirmatorio.py importar-familias --origem familias.jsonl --dataset holdout.jsonl --manifesto holdout.manifest.json --exclusoes exclusoes_desenvolvimento.json`

3. Preencher e aprovar `templates/config_confirmatoria.template.json`; congelar
   também um único artefato do candidato já selecionado e treinado.
4. Criar o rascunho, revisá-lo e congelá-lo:

   `python avaliacao/scripts/gerenciar_confirmatorio.py criar-rascunho --config config.json --dataset holdout.jsonl --manifesto holdout.manifest.json --candidato candidate.manifest.json --exclusoes exclusoes_desenvolvimento.json --saida prereg.draft.json`

   `python avaliacao/scripts/gerenciar_confirmatorio.py congelar --rascunho prereg.draft.json --saida prereg.frozen.json`

5. Registrar externamente o SHA-256 do arquivo congelado. Antes de disponibilizar
   qualquer conteúdo do holdout ao executor do candidato, reservar a abertura:

   `python avaliacao/scripts/gerenciar_confirmatorio.py reservar-abertura --preregistro prereg.frozen.json --confirmar-abertura-irreversivel`

6. Somente após a reserva, o custodiante executa o candidato congelado em ambiente
   cego aos rótulos e gera o bundle vinculado a `attempt_id` e
   `reservation_contract_sha256` retornados pela reserva.
7. Registrar e avaliar o bundle uma única vez:

   `python avaliacao/scripts/gerenciar_confirmatorio.py registrar-predicoes --preregistro prereg.frozen.json --predicoes predicoes.json --confirmar-registro-irreversivel`

Não há comando de reset. Um ledger `FAILED_CONSUMED` exige novo estudo, novo
holdout independente e novo pré-registro; não autoriza corrigir e repetir.
