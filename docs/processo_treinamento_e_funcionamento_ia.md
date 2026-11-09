# Processo de treinamento e funcionamento da IA

**Revisão:** 26/08/2026

## O que é treinado

O projeto não treina uma LLM do zero. O Granite Embedding 97M é um modelo
pré-treinado e congelado. Sobre seus vetores e os atributos TF-IDF, o projeto
treina classificadores supervisionados de menor porte e calibra seus escores.

O bundle operacional `local-hybrid-v1.8.0` já foi ajustado e congelado, mas
isso não significa “treinamento científico concluído”. A classificação
comparativa V2.1 terminou apenas em desenvolvimento sintético, sem vencedor
qualificado; deduplicação, gabarito independente e holdout institucional ainda
estão pendentes.

## Pipeline de desenvolvimento

1. **Definição da tarefa:** classificação em OBRA, DEMO, SOB_DEMANDA ou
   TRIAGEM_MANUAL; deduplicação em DUPLICADO/NAO_DUPLICADO com abstenção.
2. **Unidade e grupo:** cada registro recebe uma família-fonte; todos os
   derivados dessa fonte ficam na mesma dobra.
3. **Normalização:** título, descrição, local e metadados permitidos são
   normalizados sem usar campos que vazem o rótulo.
4. **Representação:** TF-IDF de palavras/caracteres, embedding ou fusão.
5. **Ajuste interno:** hiperparâmetros são escolhidos somente nas dobras
   internas do desenvolvimento.
6. **Calibração:** predições fora de dobra ajustam a sigmoide; nunca o holdout.
7. **Política seletiva:** limiares transformam probabilidade em ação automática
   ou revisão humana, respeitando custos assimétricos.
8. **Avaliação externa:** a dobra externa estima desempenho interno sem usar a
   própria unidade-fonte no treino.
9. **Congelamento:** config, dataset, código, dependências, bundle, manifesto,
   embedding/revisão e hashes são registrados.
10. **Holdout:** somente depois da seleção, o candidato congelado é executado
    uma vez em dados institucionais intocados.

## Comparação V2.1

São avaliados três embeddings (Granite, E5-small e MiniLM multilíngue), cinco
representações aplicáveis e cinco classificadores (logística, árvore, SVM,
MLP, XGBoost). As ablações isolam o valor incremental de TF-IDF, embedding e
metadados. O ranking segue gates de segurança e só depois usa desempenho.

O corpus completo tem 128 famílias-fonte de classificação, mas o estrato
efetivamente submetido ao classificador contém 1.114 registros e 111 famílias.
A deduplicação tem somente 12 famílias. A segunda tarefa é inviável no desenho
atual; a evidência classificatória serve para desenvolvimento, não para concluir
eficácia real.

## Inferência em operação

```text
GLPI
  → WF06 autentica/enfileira/reserva
  → WF02 consulta candidatos e decide deduplicação
  → WF03 classifica quando não há duplicidade automática
  → regra de segurança/abstenção
  → ação GLPI ou revisão humana
  → PostgreSQL registra tentativa, decisão, evento e proveniência
```

O runtime verifica versão/hash do bundle e do embedding. Em experimento, modelo
e papel devem coincidir com o protocolo; fallback falha fechado. Em operação,
o fallback só ocorre segundo a política configurada e toda tentativa é
auditada.

## Diagnóstico de acertos

O diagnóstico correto não é uma taxa única. Deve separar:

- disponibilidade de transporte;
- cobertura semântica e automática;
- erro nos casos cobertos e erro global;
- classe, cenário, completude e origem da decisão;
- deduplicação: recuperação de candidatos versus decisão final;
- gates determinísticos versus saída probabilística;
- calibração, latência e consumo de memória.

Predições precisam ser comparadas a gabarito humano independente. Sem gabarito,
um log de decisão demonstra execução, não acerto.

## XAI e monitoramento

SHAP ajuda a localizar sinais espúrios e explicar o escore do finalista, mas
não valida a decisão. Em produção, monitorar distribuição de texto, cobertura,
abstenção, erros adjudicados, latência, falhas, drift e mudanças de versão.
Queda de cobertura ou aumento de risco deve reduzir automação, não disparar
retreinamento automático sem revisão.

## Estado atual

- bundle v1.8: treinado/calibrado e operacionalmente congelado;
- E2E V9: validado tecnicamente em um caso sintético isolado;
- seleção antiga: invalidada;
- seleção V2.1: classificação parcial validada, sem vencedor qualificado;
  deduplicação bloqueada por insuficiência de grupos;
- validação científica institucional: pendente.
