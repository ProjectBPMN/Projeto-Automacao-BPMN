# Guia de métricas e interpretação

**Revisão:** 26/08/2026

Este guia define como relatar resultados futuros. Ele não contém métricas da
seleção anterior, invalidada por dependência entre derivados e divergência de
hash.

## Denominadores obrigatórios

Todo relatório deve informar:

- unidades brutas e unidades-fonte independentes;
- respostas recebidas, falhas técnicas e schema inválido;
- predições semânticas, gates determinísticos e fallback;
- casos cobertos automaticamente e abstidos;
- suporte por classe/cenário e quantidade de grupos no intervalo.

## Classificação

- **Macro-F1:** média não ponderada do F1 das classes; evita que a classe maior
  domine, mas deve vir com métricas por classe.
- **Recall de OBRA e erro crítico:** reportar separadamente encaminhamento
  indevido para OBRA e perda de OBRA.
- **Acurácia global:** acertos sobre todas as unidades avaliáveis, com política
  explícita para falha/abstenção.
- **Cobertura seletiva:** decisões automáticas divididas pelo total elegível.
- **Risco seletivo:** erros entre decisões automáticas. Sempre publicar junto
  da cobertura.
- **Log loss/Brier/calibração:** avaliam probabilidades, não apenas a classe.

## Deduplicação

Separar recuperação e decisão:

- recall@k: presença da referência correta na lista de candidatos;
- falso negativo e NPV da decisão `NAO_DUPLICADO`;
- falso positivo e precisão de `DUPLICADO`;
- cobertura automática positiva, negativa e total;
- custo ponderado, com relação FN:FP pré-definida.

Se a referência não entrou no top-k, o classificador final não teve chance de
acertar; esse erro pertence à recuperação.

## Incerteza e comparação

Intervalos e bootstrap devem reamostrar a unidade-fonte, não paráfrases. Modelos
são comparados de forma pareada nos mesmos grupos. P-valor isolado não define
relevância: publicar diferença, intervalo, direção, critérios de segurança e
multiplicidade planejada.

Zero erro observado não significa risco zero. Informar tamanho independente e
limite superior de confiança. Resultado `UNDERPOWERED` não pode ser promovido a
empate ou superioridade.

## Desempenho computacional

Separar:

1. embedding/classificador aquecido;
2. API local completa;
3. workflow E2E com banco e GLPI.

Relatar hardware, threads, batch, warm-up, p50, p95, memória máxima, vazão e
falhas. Não comparar a latência local de uma camada com a latência E2E de um
provedor remoto.

## Linguagem permitida

- “observado no desenvolvimento sintético”;
- “candidato provisório/subdimensionado”;
- “evidência técnica do cenário exercitado”;
- “intervalo compatível com...”.

Evitar “garantido”, “risco zero”, “100% correto”, “melhor modelo” ou “supera”
sem protocolo, estimando, dados e intervalo que sustentem a frase.
