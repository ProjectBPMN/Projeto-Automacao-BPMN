# Serviço local de decisão

Esta API atende os workflows V9 sem depender de uma chamada remota. O caminho
operacional candidato combina normalização determinística, TF-IDF de palavras e caracteres,
embeddings IBM Granite 97M e regressão logística calibrada. O backend oficial é
PyTorch FP32 e produz vetores com 384 dimensões.

```text
texto normalizado
  -> regras de suficiência e segurança
  -> TF-IDF + embedding Granite 97M
  -> regressão logística calibrada
  -> limiar positivo / limiar negativo / abstenção
  -> contrato JSON dos workflows V9
```

O Granite 350M é apenas um extrator estruturado experimental. A implementação
local usa o arquivo Q4_K_M do repositório
[`ibm-granite/granite-4.0-h-350m-GGUF`](https://huggingface.co/ibm-granite/granite-4.0-h-350m-GGUF),
fica desligada por padrão e nunca substitui silenciosamente o classificador.
Sua saída não participa da decisão congelada da v1.8.

## Versão vigente

- versão do modelo: `local-hybrid-v1.8.0`;
- versão do bundle: `local-hybrid-bundle-v1.8.0`;
- embedding: `ibm-granite/granite-embedding-97m-multilingual-r2`;
- revisão: `835ad14087e140460703cf0fae09f97d469d65c2`;
- backend: `pytorch_fp32`;
- dimensão: 384;
- deduplicação: limiar positivo 0,95, negativo 0,07 e margem mínima entre a
  primeira e a segunda referência de 0,035;
- estado científico: `PENDING_CONFIRMATORY_HOLDOUT`.

"Vigente" significa implantada para desenvolvimento, não selecionada como a
melhor entre todas as alternativas. O protocolo comparativo v1.3 avaliou três
embeddings, ablações isoladas, híbrido+metadados e cinco classificadores em 90
configurações. A rodada completa terminou e foi aceita pelo validador
independente em 17/08/2026. O melhor candidato provisório de classificação foi
o híbrido Granite + TF-IDF com SVM linear; em deduplicação, o híbrido Granite +
TF-IDF com regressão logística.

Nenhum dos dois passou pelos limites de confiança: ambos ficaram
`UNDERPOWERED`, embora tenham satisfeito os gates por estimativa pontual. Assim,
o resultado orienta a próxima etapa de engenharia, mas não promove
automaticamente um bundle nem substitui o holdout independente. A v1.8 continua
como referência operacional congelada.

O SHA-256 do bundle vigente é
`f518b7f9699aa9e23aab7eb2479990619ad5085994569b3f7c3f253e5207bb5d`.
O manifesto e o bundle canônicos ficam em `local_ai/artifacts`. Os pesos ficam
fora do GitHub e são verificados pelo `local_ai/models/manifest.json`.

O embedding 97M e o Granite 350M são modelos de terceiros publicados pela IBM
sob Apache-2.0; consulte os respectivos model cards e preserve seus avisos. O
manifesto congela o embedding 97M por revisão e SHA-256. Para o GGUF opcional,
o manifesto atual registra repositório, quantização e SHA-256 local, mas ainda
tem `revision=null`. Portanto, o extrator não está congelado por revisão
imutável upstream e não deve compor um experimento confirmatório enquanto essa
lacuna não for resolvida.

## Instalação e execução

```powershell
python -m pip install -r local_ai\requirements-granite.txt
python -m pip install -r local_ai\requirements-hybrid.txt
python -m pip check
.\local_ai\scripts\start-local-ai.ps1
```

O iniciador exige `IA_LOCAL_API_TOKEN` em `n8n/.env`, bloqueia download durante
a operação, valida hashes e aquece o embedding antes de informar que o serviço
está pronto. O extrator opcional pode ser iniciado com `-WithExtractor`.

```powershell
.\local_ai\scripts\status-local-ai.ps1
.\local_ai\scripts\stop-local-ai.ps1
```

## Contratos

- `POST /v1/classify`: classificação DEMO, SOB_DEMANDA, OBRA ou
  TRIAGEM_MANUAL;
- `POST /v1/deduplicate`: decisão e referência de duplicidade;
- `POST /v1/extract`: extração estruturada;
- `POST /v1/embed`: embedding e proveniência;
- `GET /health`: disponibilidade, bundle e elegibilidade.

O token deve ser enviado em `Authorization: Bearer <token>`. A API rejeita
corpos acima do limite, mais de 20 candidatos, backend diferente do congelado,
hash incompatível e respostas sem proveniência.

## Treinamento

O corpus interno de desenvolvimento é
`avaliacao/datasets/desenvolvimento_local_v1.jsonl`. Seu manifesto o classifica
como `USO_INTERNO_ACADEMICO_IF_SUDESTE_MG` e não autoriza redistribuição sem
revisão institucional. Por isso, esse caminho existe no workspace autorizado,
mas não em um clone público. O treinador mantém todos os itens do mesmo
núcleo/episódio no mesmo split e bloqueia conjuntos de teste ou benchmark.

```powershell
python avaliacao\scripts\treinar_modelo_local.py `
  --dados avaliacao\datasets\desenvolvimento_local_v1.jsonl `
  --saida avaliacao\resultados\novo-candidato `
  --embedding-backend granite `
  --embedding-model-path local_ai\models\granite-embedding-97m-multilingual-r2 `
  --embedding-model-revision 835ad14087e140460703cf0fae09f97d469d65c2 `
  --cpu-threads 4 `
  --custo-fn-dedup 5 `
  --fn-dedup-maximo 0.02 `
  --fp-dedup-maximo 0.05 `
  --vpn-dedup-minimo 0.98 `
  --precisao-dedup-minima 0.90
```

O comando acima reproduz o treinamento somente no ambiente interno que possui
o corpus autorizado. Em uma instalação pública, forneça um JSONL compatível,
com procedência e licença documentadas, e altere `--dados`. Não use conjuntos
de manutenção urbana como substitutos automáticos: o domínio deste projeto é a
manutenção patrimonial de campus federal. Um bundle treinado com outro corpus é
um novo candidato e precisa de novo manifesto, calibração e avaliação.

O custo maior do falso negativo reflete o fluxo: uma decisão automática “não
duplicado” não passa pelo WF04. A faixa intermediária sempre resulta em
abstenção e revisão.

## Evidência atual

No replay do corpus sintético de desenvolvimento, a v1.8 processou 1.240/1.240
itens sem falha de contrato. A cobertura semântica foi 54,11%, a acurácia
seletiva foi 99,70% e 40,73% dos itens concluíram diretamente; os demais foram
abstidos, encaminhados à revisão exigida pela política ou ficaram fora da
cobertura semântica. A deduplicação cobriu 35,5% e não apresentou FP ou FN nos
213 itens automatizados. A classificação teve uma decisão automática errada e
nenhum encaminhamento automático de manutenção para OBRA. A latência geral foi
414 ms em média e 838 ms no p95.

Esses números reutilizam o corpus de desenvolvimento empregado no ajuste e na
calibração. Portanto, são regressão técnica aparente, não estimativa fora da
amostra. Não são resultado confirmatório, não estimam desempenho em chamados
reais e não autorizam marcar `scientifically_validated=true`.

A materialização experimental v1.9 do resultado da seleção aumentou a cobertura
semântica global para 60,73% e a automação direta para 47,26% no mesmo replay,
mas respondeu 1.239/1.240 itens, sofreu uma falha HTTP 503 por memória e ficou
aproximadamente 250 ms mais lenta em média nas unidades pareadas com a v1.8.
Pela política previamente codificada, ela não foi promovida. Uma variante
v1.9.1 reduziu o número de estimadores do calibrador, mas o piloto de ponta a
ponta também não demonstrou vantagem estável. Esses artefatos permanecem
experimentos auditáveis; o serviço foi restaurado para a v1.8, com micro-lote
máximo de quatro textos para reduzir picos transitórios de RAM.

## Distribuição pública

O código deste serviço pode ser distribuído sob a licença do repositório, mas
isso não concede licença aos dados nem aos artefatos treinados. Em especial,
`local_ai/artifacts/local_hybrid_bundle.joblib`, quando derivado do corpus
interno citado acima, não deve ser publicado até existir autorização
institucional explícita para o artefato derivado. Sem essa autorização, remova
o bundle do índice público e documente que cada instalação deve fornecê-lo ou
treiná-lo com dados redistribuíveis. O arquivo `NOTICE` na raiz é a referência
de escopo da distribuição.
