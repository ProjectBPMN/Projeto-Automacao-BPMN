# Protocolo de seleção de embeddings e classificadores

Versão do protocolo: 1.3.0  
Data de congelamento: 12 de agosto de 2026  
Status: seleção interna de desenvolvimento, não confirmatória

## 1. Pergunta de pesquisa

Entre representações textuais executáveis localmente e classificadores
supervisionados compatíveis com o computador-alvo, qual combinação oferece o
melhor compromisso entre:

- qualidade semântica para chamados de manutenção patrimonial universitária;
- segurança nas decisões automáticas;
- cobertura de automação;
- latência e consumo de memória;
- capacidade de auditoria e reprodução?

A seleção não parte da hipótese de que um embedding mais novo, maior ou melhor
colocado em um benchmark genérico será necessariamente o melhor neste domínio.
O MTEB mostrou que nenhum método de embedding domina todas as tarefas. Por isso,
a evidência externa serviu para formar a lista de candidatos, e a escolha final
é feita no corpus do projeto, sem consultar o conjunto confirmatório
([Muennighoff et al., 2023](https://aclanthology.org/2023.eacl-main.148/)).

## 2. Por que embeddings semânticos

TF-IDF representa diretamente palavras e fragmentos de palavras e é uma base
forte para coincidências lexicais, abreviações e erros recorrentes. Entretanto,
duas descrições podem relatar o mesmo problema usando palavras diferentes.
Sentence encoders foram desenvolvidos para projetar sentenças em vetores que
podem ser comparados eficientemente por similaridade
([Reimers e Gurevych, 2019](https://aclanthology.org/D19-1410/)).

No projeto, embeddings não substituem regras, metadados ou decisão humana. Eles
são uma fonte adicional de atributos. A comparação contém três ablações:

1. **TF-IDF isolado:** mede o que é obtido apenas com sinais lexicais;
2. **embedding isolado:** mede o sinal semântico denso sem TF-IDF;
3. **híbrido:** combina os dois sinais.

Na deduplicação há ainda um controle **metadados isolados**, contendo somente
local, categoria, solicitante, urgência e impacto. TF-IDF isolado, embedding
isolado e híbrido textual não recebem esses sete atributos. Uma quinta família,
**híbrido + metadados**, reproduz explicitamente o espaço de atributos do
candidato operacional. Assim, as ablações são realmente isoladas e a contribuição
incremental dos metadados também pode ser medida, sem apresentar uma combinação
como se ela contivesse menos informação do que realmente contém.

Essa ablação permite verificar se o embedding realmente acrescenta informação.
Se o híbrido não superar a alternativa mais simples de modo consistente, não há
justificativa empírica para seu custo adicional.

## 3. Embeddings candidatos

Todos são modelos abertos, multilíngues, com saída de 384 dimensões e execução
local em CPU. As revisões e os hashes completos dos diretórios estão congelados
em `avaliacao/config/selecao_modelos_supervisionados_v1.json`.

| Candidato | Motivo de inclusão | Revisão congelada |
|---|---|---|
| Granite Embedding 97M Multilingual R2 | candidato compacto atual, multilíngue e voltado a recuperação; a ficha da IBM declara 97 milhões de parâmetros e 384 dimensões | `835ad14087e140460703cf0fae09f97d469d65c2` |
| multilingual-e5-small | controle forte e maduro, treinado com pares multilíngues e aprendizagem contrastiva | `614241f622f53c4eeff9890bdc4f31cfecc418b3` |
| paraphrase-multilingual-MiniLM-L12-v2 | baseline amplamente usado para similaridade de sentenças em 50 idiomas | `e8f8c211226b894fcb81acc59f3b34ba3efd5f42` |

Fontes dos candidatos:

- [ficha do Granite 97M Multilingual R2](https://huggingface.co/ibm-granite/granite-embedding-97m-multilingual-r2);
- [relatório técnico do multilingual E5](https://arxiv.org/abs/2402.05672);
- [ficha do paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2).

Números publicados nas fichas dos modelos são apenas motivação para inclusão,
não evidência de desempenho no projeto.

## 4. Classificadores candidatos

Cada representação é avaliada com os mesmos cinco classificadores:

- regressão logística calibrada, baseline linear simples e interpretável;
- árvore de decisão, para relações não lineares e regras por limiares;
- SVM linear, apropriada a espaços textuais esparsos de alta dimensão;
- MLP pequena, para interações não lineares entre atributos;
- XGBoost, árvores impulsionadas com suporte eficiente a dados esparsos.

A SVM segue a família de classificadores de margem proposta por
[Cortes e Vapnik (1995)](https://doi.org/10.1007/BF00994018). A inclusão da MLP
testa se a capacidade não linear de redes multicamadas traz ganho no corpus,
sem pressupor que maior capacidade implique melhor generalização
([Hornik, Stinchcombe e White, 1989](https://doi.org/10.1016/0893-6080(89)90020-8)).
O XGBoost foi incluído por ser um sistema de boosting com tratamento explícito
de matrizes esparsas
([Chen e Guestrin, 2016](https://doi.org/10.1145/2939672.2939785)).

O espaço amostral do projeto é pequeno em relação ao número de atributos.
Portanto, árvore, MLP e XGBoost são hipóteses a testar, não escolhas
automaticamente superiores; seus resultados devem ser examinados quanto a
instabilidade entre dobras e sobreajuste.

## 5. Unidade experimental e prevenção de vazamento

O único corpus permitido nesta seleção é:

`avaliacao/datasets/desenvolvimento_local_v1.jsonl`

SHA-256:

`0de50381c0dfaefeb1a940cd697f9c9a8e87b5efee9252a1f4ca43c9d904f204`

O corpus é sintético e reservado ao desenvolvimento. O script encerra com erro
se o hash divergir. `corpus_v3_teste.jsonl` e os conjuntos V2 são
explicitamente bloqueados.

Variações naturalísticas derivadas do mesmo texto-base não são observações
independentes. Para impedir que uma variação apareça no treino e outra no teste:

- classificação é agrupada por `narrative_core_sha256`;
- duplicidade é agrupada por `episode_id`.

São usadas cinco dobras externas de `StratifiedGroupKFold`. Dentro de cada dobra
externa, os grupos de treino são novamente separados em ajuste (60%) e
calibração (40%). A separação exige, em cada classe, pelo menos cinco núcleos no
ajuste e quatro na calibração. As duas meias-dobras do calibrador exigem ao menos
dois núcleos por classe em cada lado. Esses requisitos evitam confundir várias
paráfrases do mesmo núcleo com evidência independente, mas a classe rara
TRIAGEM_MANUAL ainda deixa a calibração exploratória. A busca de
hiperparâmetros usa três dobras internas agrupadas. Vocabulário e IDF do TF-IDF
são ajustados dentro do pipeline em cada dobra, sem observar a dobra externa.

## 6. Calibração, abstenção e custos assimétricos

O classificador-base é calibrado por sigmoide somente com grupos separados para
calibração. Os limiares são escolhidos usando previsões fora da dobra de
calibração e depois aplicados, sem alteração, à dobra externa.

Para classificação:

- qualquer classe real diferente de OBRA enviada automaticamente como OBRA é
  erro crítico, incluindo TRIAGEM_MANUAL;
- OBRA exige confiança mínima específica;
- previsões intermediárias resultam em `TRIAGEM_MANUAL` e nunca contam como
  automação, mesmo quando TRIAGEM_MANUAL é a classe semântica de maior
  probabilidade;
- as confirmações humanas existentes não são removidas.

Para duplicidade:

- falso negativo tem custo 5;
- falso positivo tem custo 1;
- há um limiar positivo, um limiar negativo e uma faixa intermediária de
  abstenção;
- casos na faixa intermediária permanecem sujeitos a confirmação humana.

A cobertura é separada em cobertura de decisão e automação integral. Uma
decisão positiva de duplicidade ainda exige confirmação humana; somente a
decisão negativa é considerada totalmente automática.

Não é usado um escore composto arbitrário. Os candidatos são ordenados por uma
regra hierárquica congelada, começando pelos gates de segurança e depois pelas
métricas de qualidade, cobertura e tempo. O relatório separa três estados:

- `PASS`: estimativa pontual e limites de confiança satisfazem os gates;
- `UNDERPOWERED`: estimativa pontual satisfaz os gates, mas a amostra não
  sustenta o limite de segurança;
- `FAIL`: a própria estimativa pontual viola ao menos um gate.

Um candidato `UNDERPOWERED` pode orientar o desenvolvimento, mas não é chamado
de vencedor validado nem promovido automaticamente ao runtime. Para um limite
unilateral de 95% menor ou igual a 2% com zero eventos, são necessários ao menos
149 grupos independentes; o corpus atual não possui esse tamanho nos estratos
críticos.

## 7. Métricas

### Recuperação

- Recall@1, Recall@5 e Recall@20;
- Mean Reciprocal Rank (MRR);
- nDCG@20;
- latência unitária e em lote;
- pico de memória residente.

### Classificação

- macro-F1, acurácia e matriz de confusão;
- precisão, recall e F1 por classe;
- recall de OBRA;
- log loss, Brier score e erro esperado de calibração;
- risco seletivo, cobertura automática e contagem de manutenção enviada
  automaticamente como OBRA.

### Duplicidade

- average precision, ROC-AUC, F1 e acurácia semântica;
- falsos positivos e falsos negativos nas decisões automáticas;
- precisão, valor preditivo negativo, cobertura e custo ponderado 5:1;
- log loss, Brier score e erro esperado de calibração.

Intervalos de 95% são obtidos por bootstrap dos grupos, não por reamostragem de
variações individuais. Para eventos de segurança também é reportado o limite
unilateral de Clopper-Pearson por grupo; zero eventos observados não é descrito
como risco zero. Os contrastes pareados foram congelados antes da execução:
Granite versus E5 e MiniLM, híbrido versus TF-IDF e embedding isolado, e
regressão logística versus árvore, SVM, MLP e XGBoost, mantendo os demais
fatores fixos. Um bootstrap pareado por grupo estima diferenças nos objetivos
operacionais, como risco seletivo, cobertura, erro crítico, FN, FP e custo 5:1.
Wilcoxon-Pratt sobre a acurácia semântica permanece apenas descritivo, com
correção de Holm. Ausência de diferença significativa não será descrita como
prova de equivalência.

## 8. XAI

SHAP é usado no vencedor qualificado ou, se a amostra for insuficiente, no
candidato pontual provisório. Se nenhum candidato passar sequer pelos gates
pontuais, o primeiro colocado ainda é explicado, mas marcado como exploratório
e inelegível. O estado de evidência fica registrado:

- `LinearExplainer` para regressão logística e SVM linear;
- `TreeExplainer` para árvore de decisão e XGBoost;
- MLP usa importância por permutação agrupada por família em amostra delimitada,
  pois aplicar SHAP model-agnostic em milhares de atributos excederia o orçamento
  do i3/8 GB. O resultado é identificado como fallback e não é chamado de SHAP.

O método explica o escore do classificador-base, antes da calibração e dos
limiares. As explicações locais preservam classe-alvo, sinal, valor-base e
contribuições positivas e negativas. Contribuições globais são agregadas nas
famílias TF-IDF de palavras, TF-IDF de caracteres, embedding e metadados. Uma
dimensão isolada do embedding não recebe uma interpretação linguística
inventada. SHAP explica associações do modelo, não causalidade
([Lundberg e Lee, 2017](https://papers.neurips.cc/paper/2017/hash/8a20a8621978632d76c43dfd28b67767-Abstract.html)).

## 9. Matriz experimental

Há sete representações textuais efetivas:

- TF-IDF;
- Granite isolado e Granite híbrido;
- E5 isolado e E5 híbrido;
- MiniLM isolado e MiniLM híbrido.

Classificação usa as sete. Deduplicação usa essas sete, acrescenta o controle de
metadados isolados e três combinações híbridas + metadados, uma para cada
embedding. Com cinco classificadores, a execução possui:

`(7 × 5) + (11 × 5) = 90 configurações`

Cada configuração produz previsões externas fora da amostra para todos os
registros elegíveis.

## 10. Reprodução

Criar um ambiente virtual e instalar as dependências:

```powershell
python -m venv .venv-benchmark
.\.venv-benchmark\Scripts\Activate.ps1
python -m pip install -r local_ai\requirements-benchmark.txt
```

Baixar exatamente os snapshots indicados no JSON, preservando os caminhos
locais. O executor valida revisão lógica, árvore de arquivos e dimensão antes de
usar os vetores. Exemplo para E5:

```powershell
hf download intfloat/multilingual-e5-small `
  --revision 614241f622f53c4eeff9890bdc4f31cfecc418b3 `
  --local-dir local_ai\models\multilingual-e5-small `
  --exclude ".eval_results/*" "onnx/*" "openvino/*" `
            "pytorch_model.bin" "tf_model.h5"
```

Executar a seleção:

```powershell
python avaliacao\scripts\selecionar_modelos_supervisionados.py `
  --saida avaliacao\resultados\selecao-supervisionada-v1.3-20260812 `
  --resume
```

`--resume` reutiliza somente resultados completos cujo fingerprint coincide com
o JSON, os códigos do executor e do helper, os arquivos de dependências e as
versões instaladas. Os embeddings são armazenados em cache identificado pelo
hash do corpus, revisão, prefixos, hash da árvore do modelo e hashes dos arquivos
de vetores.

O tempo de predição registrado nas dobras mede somente o pipeline posterior aos
embeddings pré-computados e, portanto, não é comparado diretamente com TF-IDF.
Para o primeiro colocado de cada tarefa há um benchmark separado de texto bruto
até a predição do classificador-base, com aquecimento, p50, p95, throughput e
pico de RSS. Na deduplicação são medidos tanto o cenário com embedding da
referência em cache quanto o cenário sem cache. O carregamento frio do encoder é
reportado separadamente. Essa medição não inclui rede, GLPI, n8n, calibração nem
efeitos externos e não deve ser apresentada como latência ponta a ponta do
sistema institucional.

## 11. Limite da conclusão

Esta execução responde qual candidato é mais promissor no corpus sintético de
desenvolvimento. Ela não mede eficácia institucional real e não autoriza
publicar uma taxa de acerto confirmatória. A conclusão científica final requer
um conjunto congelado que não participou da seleção e rótulos validados no
protocolo de avaliação do projeto.
