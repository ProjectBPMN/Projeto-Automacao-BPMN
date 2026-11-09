# Justificativa da modelagem local híbrida

> [!WARNING]
> **Snapshot histórico, superado pela auditoria de 26/08/2026.** A seleção
> citada neste documento não sustenta ranking atual: derivados de poucas
> famílias-fonte não ficaram integralmente no mesmo grupo. Toda classificação
> permanece sintética e a deduplicação antiga é subdimensionada. Use
> `auditoria_critica_completa_2026-08-26.md` e
> `resposta_professor_2026-08-26.md` como estado canônico.

## Decisão arquitetural

O sistema não usa um único modelo para “raciocinar livremente” sobre todo o
chamado. Ele combina sinais complementares e aplica regras de segurança:

```text
texto e metadados disponíveis
  → normalização e checagem de suficiência
  → TF-IDF de palavras e caracteres + embedding Granite 97M
  → regressão logística calibrada
  → limiares assimétricos + abstenção
  → ação automática ou revisão humana
```

Essa escolha é uma resposta às restrições do estudo: computador i3 de sétima
geração com 8 GB de RAM, português informal, erros de digitação, pouco dado
institucional rotulado, decisões auditáveis e instabilidade observada nas APIs
gratuitas. Ela não significa que a arquitetura já tenha superado modelos
generativos em eficácia; essa comparação continua pendente no conjunto
independente.

## Papel de cada componente

### TF-IDF de palavras e caracteres

O TF-IDF transforma o corpus em uma matriz termo-documento ponderada. No
projeto, os n-gramas de palavras preservam vocabulário específico — ativo,
sintoma, bloco, sala e tipo de serviço — e os n-gramas de caracteres ajudam
quando há abreviações ou grafias imperfeitas. A representação é esparsa, rápida
em CPU e permite inspecionar quais termos influenciaram o classificador. A
documentação do scikit-learn define o `TfidfVectorizer` como a transformação de
documentos brutos em uma matriz de atributos TF-IDF
([scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html)).

Limite: coincidência lexical não basta para reconhecer todas as paráfrases e
pode superestimar textos que repetem palavras, mas descrevem ocorrências
diferentes.

### Granite Embedding 97M Multilingual R2

O embedding acrescenta um sinal semântico denso. Assim, descrições como “não
está gelando” e “sem refrigeração” podem ficar próximas mesmo sem compartilhar
todas as palavras. A IBM descreve o modelo como multilíngue, com português
entre os idiomas de suporte reforçado, aproximadamente 97 milhões de
parâmetros e saída de 384 dimensões
([model card da IBM](https://huggingface.co/ibm-granite/granite-embedding-97m-multilingual-r2)).

O tamanho reduzido foi determinante para o equipamento-alvo. Na medição local
já preservada, o backend PyTorch FP32 aquecido, com quatro threads, registrou
p95 de 119,9 ms para um texto, p95 de 501,9 ms para sete textos e RSS máximo
amostrado de 822,0 MB. Esses valores medem apenas o embedding nesse computador;
não são latência ponta a ponta nem uma garantia para outro hardware.

Limite: semântica parecida não significa identidade do evento. Dois aparelhos
no mesmo local ou dois defeitos do mesmo aparelho podem ter embeddings muito
próximos. Por isso o vetor não decide duplicidade sozinho.

### Regressão logística calibrada

A regressão logística combina os atributos esparsos do TF-IDF com os atributos
densos do embedding e produz uma fronteira de decisão de baixo custo. A
implementação do scikit-learn aceita entradas densas e esparsas e aplica
regularização
([scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html)).
Isso favorece reprodução, ablação e inspeção em um corpus menor do que seria
necessário para ajustar uma LLM de ponta a ponta.

A calibração não serve para “aumentar a acurácia” por si só. Ela busca tornar o
escore utilizável como probabilidade para definir automação, abstenção e risco.
O `CalibratedClassifierCV` usa validação cruzada para ajustar o calibrador; a
própria documentação alerta que calibrar sobre dados usados no treino produz
probabilidades enviesadas
([guia de calibração](https://scikit-learn.org/stable/modules/calibration.html)).
Neste projeto, a seleção de hiperparâmetros, a calibração e os limiares usam
predições fora de dobra e agrupamento por núcleo/episódio para reduzir
vazamento entre paráfrases.

Limite: coeficientes e probabilidades continuam dependentes da distribuição do
corpus. Uma probabilidade calibrada no desenvolvimento sintético não é
automaticamente calibrada em chamados reais.

### Granite 4.0 H 350M

O Granite 350M é um extrator generativo opcional, não o classificador principal
nem um árbitro de baixa confiança. A IBM lista português, extração de texto,
classificação e function calling entre as capacidades do modelo
([model card da IBM](https://huggingface.co/ibm-granite/granite-4.0-h-350m)).
Isso o torna útil para propor campos estruturados, como ativo, sintoma e local,
quando o texto contém essas informações.

O artefato local previsto no manifesto usa a variante GGUF `Q4_K_M`. Ele fica
desligado por padrão porque uma segunda inferência generativa aumenta RAM,
latência e variabilidade. Além disso, nenhuma LLM consegue extrair com
segurança uma sala ou um ativo que o usuário não informou. Quando ativado, sua
saída deve ser validada por schema, registrada e tratada como apoio; nunca deve
substituir silenciosamente o candidato avaliado.

## Por que não usar apenas uma alternativa

| Alternativa | Vantagem | Motivo para não ser o caminho principal atual |
|---|---|---|
| Regras fixas | Máxima previsibilidade | Não cobrem paráfrases e fronteiras contextuais; permanecem úteis como guardas. |
| TF-IDF isolado | Muito leve e interpretável | Perde sinal quando a mesma situação é descrita com vocabulário diferente. |
| Embedding + cosseno | Recuperação semântica simples | Similaridade não é probabilidade de duplicidade nem considera sozinha os riscos das classes. |
| LLM remota | Boa interpretação geral e pouca infraestrutura local | Cota, latência e disponibilidade ficam fora do controle; as falhas observadas são operacionais, não prova de menor inteligência. |
| LLM pequena local como decisor | Operação offline e flexível | Maior variabilidade generativa, mais custo por chamado e validação mais difícil no i3/8 GB. |
| Fine-tuning integral de LLM | Pode aprender o domínio com muitos rótulos | O corpus institucional atual é pequeno e sintético para esse objetivo; aumenta custo e risco de sobreajuste. |
| Híbrido atual | Combina sinal lexical e semântico, probabilidade, abstenção e baixo custo | Ainda depende de holdout independente e pode exigir mais revisão quando falta informação. |

A arquitetura v1.8 foi adotada como candidata de engenharia por adequação e
testabilidade, não como resultado de uma busca exaustiva. O protocolo corrigido
V2.1 compara Granite 97M, multilingual-e5-small e multilingual MiniLM,
TF-IDF/embedding/híbrido realmente isolados, metadados e híbrido+metadados, com
regressão logística, árvore, SVM, MLP e XGBoost. A comparação posterior com
Gemini deve usar os mesmos casos, sem fallback e com falhas no denominador.

## Matriz de adequação às restrições do projeto

Esta matriz formaliza os critérios que orientaram as decisões durante o
desenvolvimento. Ela foi consolidada depois dos primeiros experimentos e,
portanto, não deve ser descrita como seleção pré-registrada nem como prova de
superioridade universal.

| Família | Português informal | CPU/8 GB | Offline | Probabilidade/abstenção | Auditabilidade | Papel adotado |
|---|---:|---:|---:|---:|---:|---|
| Regras e catálogo | parcial | alta | sim | determinística | alta | guardas e validação de schema |
| TF-IDF palavra+caractere | boa para vocabulário e ruído ortográfico | alta | sim | requer classificador | alta | sinal lexical principal |
| Embedding multilíngue leve | boa para paráfrases | média/alta | sim | requer classificador | média | sinal semântico Granite 97M |
| LLM pequena local | potencialmente boa | média/baixa | sim | instável sem calibração externa | baixa/média | extração opcional Granite 350M |
| LLM remota | boa em linguagem geral | alta localmente | não | depende do provedor | média | comparador/fallback operacional |
| Fine-tuning integral de LLM | depende de muitos rótulos | baixa | possível | difícil de calibrar | baixa | rejeitado para o corpus/hardware atual |

Os critérios eliminatórios foram: execução no i3/8 GB, suporte a português,
operação sem cota por chamado e possibilidade de congelar versão e hash. Os
critérios de desempate foram latência, capacidade de representar erros de
digitação, probabilidade calibrável, inspeção do erro e simplicidade de
reprodução. A rodada comparativa anterior foi invalidada por dependência entre
derivados e divergência de hash. No protocolo V2.1 corrigido, a classificação
foi validada apenas no escopo de desenvolvimento e não qualificou vencedor; a
deduplicação ficou bloqueada por insuficiência de grupos. Até o holdout
independente, não há evidência suficiente para afirmar que o Granite 97M é o melhor embedding do domínio —
muito menos o melhor embedding existente.

## Configuração reproduzível do candidato v1.8

Os valores abaixo foram extraídos do código de treinamento e do manifesto
congelado `local_ai/artifacts/local_hybrid_manifest.json`:

- TF-IDF de palavras: unigramas e bigramas, `min_df=1`, frequência sublinear e
  remoção de acentos Unicode;
- TF-IDF de caracteres: analisador `char_wb`, n-gramas de 3 a 5 caracteres,
  `min_df=1` e frequência sublinear;
- classificação: regressão logística com `C=3,0` e pesos balanceados, escolhida
  por macro-F1 em validação cruzada estratificada por grupo com cinco dobras;
- deduplicação: regressão logística com `C=0,03` e sem peso de classe, escolhida
  por custo esperado agrupado com custo FN:FP igual a 5:1;
- calibração de classificação: sigmoide, probabilidades fora de dobra em três
  dobras agrupadas, seguida de reajuste completo;
- calibração de deduplicação: sigmoide, probabilidades fora de dobra em cinco
  dobras agrupadas, seguida de reajuste completo;
- embedding: `ibm-granite/granite-embedding-97m-multilingual-r2`, revisão
  `835ad14087e140460703cf0fae09f97d469d65c2`, 384 dimensões, vetores
  normalizados e backend PyTorch FP32.

Na classificação, entram título, descrição e localização; a categoria GLPI foi
excluída do sinal principal para não reforçar o rótulo informado incorretamente
pelo próprio usuário. Na deduplicação, o modelo usa diferenças e produtos dos
vetores TF-IDF/embedding, cossenos e indicadores explícitos de local, categoria,
solicitante, urgência e impacto. Os hashes, seeds, grupos e auditoria das dobras
permanecem no manifesto para permitir conferência independente.

## Custos assimétricos e limiares atuais

Os riscos operacionais não são simétricos:

- uma decisão automática `NAO_DUPLICADO` não passa pela confirmação fiscal;
  por isso falso negativo de duplicidade recebe a maior penalidade;
- um possível duplicado ainda passa por confirmação, mas falso positivo em
  excesso aumenta a carga humana e reduz a utilidade da automação;
- classificar manutenção como `OBRA` pode enviar mensagem automática a um
  órgão relevante; por isso OBRA usa trava própria mais conservadora;
- forçar uma classe quando faltam local, ativo ou sintoma é pior do que abster.

No candidato v1.8 congelado, os pontos vigentes são: confiança interna de
classificação 0,76; trava adicional de OBRA 0,90; duplicidade positiva 0,95;
não duplicidade 0,07; e margem mínima de 0,035 entre a melhor e a segunda
referência. `IA_CONFIANCA_MINIMA=0,65` é uma trava externa comum do workflow e
não substitui os limiares internos. Todos esses valores vieram da calibração de
desenvolvimento e permanecem provisórios até o holdout.

## O que a evidência permite concluir

A regressão v1.8 sobre o corpus sintético de desenvolvimento demonstra que o
pipeline local está funcional e que a política seletiva consegue abster. As
comparações históricas com a v1.1 descrevem engenharia no corpus usado, não uma
estimativa válida de eficácia cotidiana nem superioridade sobre Gemini ou
DeepSeek.

A afirmação científica final exige, no mínimo:

1. congelar código, bundle, prompts, limiares e casos antes de abrir o teste;
2. usar uma amostra independente com rótulos humanos ou adjudicados;
3. manter núcleos/episódios separados e calcular incerteza nessa unidade;
4. relatar cobertura, abstenção, falhas, matriz de confusão, risco seletivo,
   latência e intervenção humana;
5. comparar o híbrido e o Gemini no mesmo subconjunto pareado, cada qual sem
   fallback;
6. concluir a calibração repetida do WF06 antes de apresentar sua vazão como
   configuração ótima.

O piloto pareado de 40 unidades não é um teste de não inferioridade. Ele serve
para descrever concordância, falhas, cobertura, latência e consumo sob entradas
idênticas. O estimando disponível no executor é a diferença de acurácia geral
LOCAL menos Gemini, com abstenções como incorretas; não corresponde ao risco
crítico H2. A adoção depende também de análises específicas para falso negativo
de duplicidade e para manutenção encaminhada indevidamente como OBRA.

## Texto curto para o artigo

> Foi implementado como candidato operacional um modelo híbrido local composto por representações TF-IDF
> de palavras e caracteres, embeddings multilíngues Granite 97M e regressão
> logística calibrada. O TF-IDF preserva termos discriminativos e ruído
> ortográfico do domínio, enquanto o embedding de 384 dimensões acrescenta
> proximidade semântica entre paráfrases. A regressão calibrada combina esses
> sinais com baixo custo em CPU e permite definir limiares assimétricos e uma
> região explícita de abstenção. O Granite 350M foi reservado à extração
> estruturada opcional, fora do caminho decisório padrão, para limitar consumo
> de memória e variabilidade generativa. A escolha foi motivada por
> reprodutibilidade, auditabilidade e adequação ao hardware. A comparação entre
> Granite, E5 e MiniLM e entre cinco classificadores foi especificada no
> protocolo V2.1 com validação agrupada por família-fonte; sua eficácia
> externa e eventual não inferioridade ao Gemini dependem de avaliação pareada
> no conjunto independente congelado.
