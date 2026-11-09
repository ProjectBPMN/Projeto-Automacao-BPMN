# Diagnóstico de validação científica

**Revisão:** 01/09/2026

> O projeto decidiu não realizar verificação humana nem revisão em pares. O
> gabarito independente e o holdout confirmatório deixam de ser pendências
> executáveis e passam a ser um limite declarado do escopo.

## Quadro oficial

| Componente | Estado | Interpretação permitida |
|---|---|---|
| Bundle operacional v1.8 | congelado e carregável | candidato de engenharia |
| Runtime local | `decision_ready=true` | apto a decidir segundo contratos locais |
| Prontidão científica | `scientific_ready=false` | nenhuma alegação confirmatória |
| E2E V9 | aprovado em caso sintético isolado | integração exercitada, não acurácia |
| Seleção antiga | `INVALIDATED_POST_AUDIT` | somente histórico |
| Protocolo V2.1 | classificação executada e validada no escopo parcial | deduplicação bloqueada por 12 grupos; nenhum vencedor qualificado |
| Gabarito humano | retirado do escopo | bloqueia eficácia institucional |
| Holdout institucional | não executado | bloqueia resultado final |
| Comparação remota pareada | não concluída | sem ranking local versus Gemini/DeepSeek |

## Por que a seleção antiga foi invalidada

O corpus nominal escondia dependências de geração:

- 80 especificações nominais por classe vinham de 32 moldes-fonte por classe;
- 200 episódios nominais de deduplicação vinham de 12 famílias-fonte.

O agrupamento antigo não mantinha todos os derivados juntos. Além disso, o
hash do dataset na saída não correspondia ao corpus reproduzível pelo gerador
disponível. Portanto, não são válidos como evidência os rankings, métricas,
intervalos, p-valores, SHAP ou limiares derivados daquela rodada.

## Correção metodológica

O corpus `desenvolvimento-local-v2.1.0` usa
`source_dependency_group_sha256` em ambas as tarefas. O SHA-256 congelado é:

```text
305e84164d663a19a2e224b2dc8bf08e8d3173bf50bc15c7675f9de553d2de9a
```

O protocolo compara Granite 97M, multilingual-e5-small e multilingual MiniLM;
TF-IDF/embedding/híbrido; regressão logística, árvore, SVM, MLP e XGBoost; CV
aninhado agrupado, calibração fora de dobra, bootstrap por grupo, SHAP e
latência.

Mesmo após a correção, 12 famílias de deduplicação são poucas para uma
conclusão forte. A saída deve permanecer `development_only=true` e ser tratada
como exploratória.

## Gates para conclusão científica

1. amostra real autorizada e representativa;
2. unidade independente definida antes do split;
3. dois revisores cegos, adjudicação e concordância;
4. protocolo/hashes congelados antes do holdout;
5. seleção e calibração restritas ao desenvolvimento;
6. execução única do candidato no holdout;
7. intervalos, calibração, risco-cobertura e análise de erro;
8. auditoria de subgrupos e piloto prospectivo em sombra.

Até todos os gates serem cumpridos, as formulações corretas são “protótipo
operacional”, “candidato congelado” e “evidência técnica sintética”. Não usar
“IA validada”, “melhor modelo”, “100% correto” ou “pronto para produção”.

Veja `SOURCE_OF_TRUTH.md` e `auditoria_critica_completa_2026-08-26.md`.
