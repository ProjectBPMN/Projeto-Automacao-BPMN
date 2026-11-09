# Metodologia corrente de avaliação — protocolo 2.1

**Revisão:** 01/09/2026  
**Escopo:** seleção de desenvolvimento, diagnóstico de acertos e preparação de
validação institucional  
**Estado:** canônico; não confirmatório

> Decisão de escopo: não haverá verificação humana nem revisão em pares. As
> etapas que dependem de gabarito independente permanecem descritas como
> requisito metodológico, mas estão bloqueadas. Métricas contra rótulos
> sintéticos/regras continuam sendo desenvolvimento por proxy.

## 1. Perguntas e estimandos

O estudo separa quatro perguntas que não podem ser respondidas por um único
número:

1. qual representação recupera um chamado relacionado entre os primeiros
   candidatos de deduplicação;
2. qual representação/classificador discrimina as quatro classes de triagem;
3. qual política seletiva automatiza casos com risco aceitável e encaminha os
   demais à revisão humana;
4. qual é a disponibilidade e a latência do sistema integrado.

Desempenho semântico, cobertura automática, segurança da decisão e
disponibilidade técnica são estimandos distintos. Falha de transporte não é
erro semântico; abstenção não é acerto; acurácia entre casos cobertos não é
acurácia global.

## 2. Dados e validade

O corpus `desenvolvimento-local-v2.1.0` é sintético, sem dados pessoais e
destinado somente a desenvolvimento. Seu SHA-256 é
`305e84164d663a19a2e224b2dc8bf08e8d3173bf50bc15c7675f9de553d2de9a`.
Ele não estima prevalência, eficácia institucional nem desempenho em produção.

Todos os derivados de uma mesma fonte usam
`source_dependency_group_sha256`. Nenhum grupo pode aparecer simultaneamente
em treino, calibração e teste. Os denominadores relevantes são:

- corpus completo: 128 famílias-fonte de classificação;
- estrato efetivamente submetido ao classificador: 1.114 registros e 111
  famílias-fonte (28 OBRA, 32 DEMO, 32 SOB_DEMANDA e 19 TRIAGEM_MANUAL);
- deduplicação: 1.000 pares derivados de somente 12 famílias-fonte, seis por
  classe.

O número de linhas não substitui o número de unidades independentes.

## 3. Candidatos e ablações

Embeddings congelados, todos com 384 dimensões:

- IBM Granite Embedding 97M Multilingual R2;
- `multilingual-e5-small`;
- `paraphrase-multilingual-MiniLM-L12-v2`.

Representações:

- TF-IDF de palavras e caracteres isolado;
- embedding isolado;
- TF-IDF + embedding;
- metadados isolados, apenas como diagnóstico de deduplicação;
- TF-IDF + embedding + metadados, como hipótese operacional de deduplicação.

Classificadores:

- regressão logística;
- árvore de decisão;
- SVM linear;
- MLP;
- XGBoost.

O híbrido não é presumido superior. Ele só pode ser preferido se a comparação
pareada, sob o mesmo split, justificar o ganho e se custo/latência continuarem
aceitáveis.

## 4. Desenho de validação

Para classificação, o protocolo congelado usa:

- `StratifiedGroupKFold` externo com cinco dobras;
- busca interna agrupada com três dobras;
- separação agrupada e disjunta entre ajuste e calibração;
- calibração sigmoide avaliada fora de dobra;
- predição externa OOF: cada unidade é prevista uma única vez por configuração;
- 2.000 reamostragens bootstrap por grupo para incerteza;
- comparações pareadas no mesmo universo e correção de Holm onde aplicável.

A seleção de hiperparâmetro, calibração e limiar ocorre sem a dobra externa. O
holdout institucional futuro não pode ser usado nessas etapas.

### Bloqueio de deduplicação

O desenho 2.1 exige, por classe e dentro do treino externo, no mínimo cinco
grupos para ajuste e quatro para calibração. Existem somente seis grupos por
classe antes da divisão externa. Portanto, o desenho é matematicamente
inviável. A tentativa completa falhou antes de ajustar as 55 configurações de
deduplicação, como deveria ocorrer em um sistema fail-closed.

Não se reduziram os mínimos apenas para obter números. Com seis grupos e zero
eventos observados, o limite superior unilateral de 95% para uma taxa ainda é
aproximadamente 39,3%. Para que zero eventos coloque esse limite abaixo de 2%,
são necessários ao menos 149 grupos independentes; abaixo de 5%, ao menos 59.
Esses cálculos são planejamento conservador, não promessa de poder para todos
os desfechos.

O novo preflight `validar_viabilidade_protocolo_selecao.py` executa todas as
divisões antes de embeddings/treino. O protocolo classificatório isolado fica
em `config/selecao_classificacao_supervisionada_v2_1.json`. A deduplicação só
deve ser reaberta após ampliar fontes independentes e congelar novo protocolo.

## 5. Métricas

### Classificação

- Macro-F1 e acurácia semântica;
- precisão, recall e F1 por classe;
- recall de OBRA;
- log loss, Brier e erro esperado de calibração;
- cobertura automática e risco seletivo;
- não-OBRA encaminhado automaticamente como OBRA;
- intervalos agrupados e matriz de confusão.

`TRIAGEM_MANUAL` semântica nunca conta como automação. Uma política sem limiar
elegível tem cobertura automática zero.

### Deduplicação

- recuperação: Recall@1, @5 e @20, MRR e nDCG@20;
- decisão: falso negativo, falso positivo, NPV, precisão, cobertura e custo
  assimétrico FN 5:1 FP;
- latência com e sem cache do embedding de referência.

As métricas de recuperação atuais são descritivas e altamente dependentes das
12 famílias sintéticas. Não validam o classificador de deduplicação.

## 6. Regra de seleção e interpretação da rodada

A regra é hierárquica: segurança e cobertura precedem Macro-F1. Não há escore
composto inventado após observar os resultados. Um candidato pode ser:

- `PASS`: satisfaz estimativas pontuais e limites de confiança;
- `UNDERPOWERED`: satisfaz apenas os gates pontuais;
- `FAIL`: viola pelo menos um gate pontual.

Na rodada de 26/08, as 35 configurações classificatórias completaram 175
dobras e 38.990 predições OOF. O validador recalculou métricas, ranking,
recuperação, contrastes, XAI e latência e registrou
`VALID_PARTIAL_TASK_SCOPE`. Nenhum candidato classificatório obteve `PASS`.
O candidato provisório foi E5 + híbrido + SVM linear; `UNDERPOWERED` não
autoriza substituir o bundle operacional Granite v1.8.

## 7. XAI

SHAP é aplicado ao escore do classificador-base, antes de calibração e limiar.
Ele serve para inspecionar sinais lexicais, semânticos e metadados, detectar
atalhos e selecionar casos para revisão. O residual de aditividade é auditado.

SHAP não prova acerto, causalidade ou validade externa. Dimensões individuais
de embedding não recebem interpretação linguística. A explicação da rodada é
exploratória porque os dados são sintéticos e o candidato é provisório.

## 8. Gabarito institucional e holdout

Antes de qualquer alegação de eficácia:

1. obter autorização institucional e definir minimização/LGPD;
2. definir a unidade independente por ocorrência, ativo, local e tempo;
3. elaborar manual de rótulos e fazer uma calibração pequena dos revisores;
4. usar dois revisores independentes, cegos às predições e aos rótulos um do
   outro, com adjudicação;
5. medir concordância e registrar divergências;
6. congelar protocolo, código, candidato, limiares e exclusões;
7. abrir o holdout uma única vez;
8. publicar todos os denominadores, intervalos, falhas e análises de erro.

Depois, executar piloto prospectivo em sombra, sempre com revisão humana,
rollback e monitoramento de drift, cobertura e risco por classe.

## 9. Reprodutibilidade

Cada rodada deve congelar config, dataset/hash, revisões e hashes dos
embeddings, fontes do executor, versões de pacotes, seed, predições OOF e
tempos. O validador é independente do agregador e recalcula a evidência bruta.

Comandos atuais:

```powershell
# Detecta inviabilidade antes do treino completo
python avaliacao/scripts/validar_viabilidade_protocolo_selecao.py `
  --config avaliacao/config/selecao_modelos_supervisionados_v2.json

# Reproduz somente a tarefa classificatória viável em uma nova saída
powershell -ExecutionPolicy Bypass `
  -File avaliacao/scripts/executar_selecao_modelos.ps1 `
  -Config avaliacao/config/selecao_classificacao_supervisionada_v2_1.json `
  -Saida avaliacao/resultados/selecao-classificacao-v2.1.1-NOVA
```

Resultados sintéticos nunca devem ser promovidos automaticamente a bundle
operacional nem citados como desempenho do campus.

## 10. Referências metodológicas

- [Multilingual E5 technical report](https://arxiv.org/abs/2402.05672)
- [E5: weakly-supervised contrastive pre-training](https://arxiv.org/abs/2212.03533)
- [GroupKFold — scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.GroupKFold.html)
- [Nested cross-validation — scikit-learn](https://scikit-learn.org/stable/auto_examples/model_selection/plot_nested_cross_validation_iris.html)
- [Varma e Simon — viés após seleção](https://pubmed.ncbi.nlm.nih.gov/16504092/)
- [Lundberg e Lee — SHAP](https://papers.nips.cc/paper_files/paper/2017/hash/8a20a8621978632d76c43dfd28b67767-Abstract.html)
- [TRIPOD+AI](https://www.bmj.com/content/385/bmj-2023-078378)
- [PROBAST+AI](https://www.bmj.com/content/388/bmj-2024-082505)
