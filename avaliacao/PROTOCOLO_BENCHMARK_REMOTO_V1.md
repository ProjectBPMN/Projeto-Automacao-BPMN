# Protocolo de benchmark remoto pareado (v1)

Status em 17/08/2026: protocolo Gemini implementado e bloqueado por padrão; nenhuma
chamada remota foi feita nesta revisão. O braço DeepSeek ainda não está autorizado nem
implementado como executor científico.

## Modelos e evidência documental

- O identificador estável congelado para o primeiro piloto é `gemini-3.5-flash`.
  A página oficial o classifica como estável, com saída estruturada e raciocínio:
  <https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash>.
- A tabela oficial registra uso Standard gratuito no Free Tier para esse modelo:
  <https://ai.google.dev/gemini-api/docs/pricing>. Isso não prova que o projeto ligado
  à chave esteja sem faturamento; essa condição deve ser conferida no AI Studio. A
  mesma tabela informa que dados do Free Tier podem ser usados para melhorar produtos
  do provedor. O benchmark remoto deve usar apenas narrativas sintéticas autorizadas,
  nunca chamados reais identificáveis.
- RPM, TPM e RPD variam por projeto e tier, são compartilhados por projeto (não por
  chave), e a capacidade publicada não é garantida. A fonte oficial determina a
  conferência do limite ativo no AI Studio e informa que o RPD reinicia à meia-noite do
  horário do Pacífico: <https://ai.google.dev/gemini-api/docs/rate-limits>.
- Os identificadores atuais do DeepSeek são `deepseek-v4-flash` e
  `deepseek-v4-pro`; os aliases `deepseek-chat` e `deepseek-reasoner` foram retirados.
  A API oficial é tarifada por token e saldo concedido não equivale a uma camada
  gratuita garantida: <https://api-docs.deepseek.com/quick_start/pricing>.
- O DeepSeek informa limite de concorrência, não uma cota pública geral de RPM/TPM/RPD:
  <https://api-docs.deepseek.com/quick_start/rate_limit>.

Consequência: os valores 15 RPM, 1.000.000 TPM e 1.500 RPD não são tratados como
constantes científicas. Eles só podem ser passados ao executor depois de serem
confirmados para o projeto no momento do ensaio.

## Desenho do piloto Gemini

O arquivo `scripts/benchmark_pareado_local_gemini.py` mantém as seguintes condições:

1. Mesmas unidades, ordem, entradas e candidatos nos braços LOCAL e Gemini.
2. Modelo, prompt, seed, esquema, limites e hashes congelados antes da execução.
3. Uma única tentativa remota por unidade, sem retry e sem fallback.
4. Erros de transporte, HTTP, contrato e abstenções não são convertidos em acertos.
5. O braço LOCAL é executado primeiro; qualquer resposta local inválida impede todas as
   chamadas remotas.
6. A primeira resposta 429, qualquer outro HTTP não bem-sucedido ou a primeira violação
   de contrato interrompe a execução e gera artefato parcial não comparável.
7. Um ledger conservador conta tentativas iniciadas em janela móvel de 24 horas.
8. Um limitador de janela móvel reserva RPM e TPM antes de cada chamada. Por padrão,
   utiliza somente 80% das cotas informadas. A reserva de tokens superestima o consumo
   usando bytes UTF-8, overhead fixo e saída máxima.

Essa proteção reduz o risco de 429, mas não pode eliminá-lo se outro processo consumir a
mesma cota do projeto. Antes do ensaio, é obrigatório confirmar que não há outro
consumidor ativo.

O corpus atual de desenvolvimento continua sendo sintético e exposto. Portanto, o
piloto LOCAL versus Gemini é exclusivamente descritivo (`scientific_result=false`) e
não autoriza alegação de superioridade, equivalência ou não inferioridade. Uma conclusão
confirmatória exige holdout independente, rótulos humanos adjudicados e margens de risco
pré-registradas.

## Execução segura

Primeiro congele o plano, sem API:

```powershell
python avaliacao/scripts/benchmark_pareado_local_gemini.py `
  --development-paired `
  --dataset avaliacao/datasets/desenvolvimento_local_v1.jsonl `
  --dataset-manifest avaliacao/datasets/desenvolvimento_local_v1_manifest.json `
  --local-model-manifest local_ai/artifacts/local_hybrid_manifest.json `
  --output-dir avaliacao/resultados/pareado-local-gemini-desenvolvimento-v1 `
  --classification-cores 40 --dedup-cores 100 --realizations-per-core 1 `
  --candidate-limit 20 --max-output-tokens-per-call 768 `
  --max-remote-calls 140 --max-remote-tokens 2000000 `
  --max-rpm <RPM_ATIVO> --max-tpm <TPM_ATIVO> --max-remote-rpd <RPD_ATIVO> `
  --gemini-key-env GEMINI_API_KEY_SECONDARY
```

Somente depois de revisar o plano, conferir tier/faturamento e cotas no AI Studio e
garantir exclusividade do projeto durante o ensaio, repita exatamente o comando com:

```text
--execute --confirm-remote-execution --confirm-active-quota-checked
--confirm-billing-status-checked --confirm-exclusive-quota-window
```

A chave deve existir apenas na variável de ambiente indicada por `--gemini-key-env`.
Não colocar chave em argumento, código, plano, resultado, documentação ou Git.
O manifesto acima congela o braço LOCAL operacional v1.8. A v1.9 permanece um
experimento exploratório rejeitado pelos gates de disponibilidade e latência e
não pode substituí-la silenciosamente neste pareado.

## Braço DeepSeek pendente

Não se deve reutilizar o executor Gemini trocando apenas a URL. O DeepSeek usa contrato
OpenAI Chat Completions, `response_format=json_object` (sem o mesmo JSON Schema do
Gemini), `thinking.type=enabled` e `reasoning_effort=high`. Um executor próprio precisa:

- congelar `deepseek-v4-flash` e o perfil de raciocínio;
- reutilizar exatamente as mesmas unidades e o mesmo conteúdo sem gabarito;
- validar JSON, classes, referência de duplicidade, `finish_reason` e uso de tokens;
- usar diretório e ledger exclusivos;
- interromper na primeira falha sem retry/fallback;
- registrar que a API é paga e exigir autorização explícita de custo;
- manter os resultados descritivos até existir holdout confirmatório.

Até esses itens serem implementados e testados com transporte simulado, nenhuma chave
DeepSeek deve ser usada e nenhuma comparação de eficácia com DeepSeek pode ser alegada.
