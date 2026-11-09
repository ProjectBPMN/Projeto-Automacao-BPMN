# Protocolo de limiares e automação seletiva

**Revisão:** 26/08/2026

## Princípio

Um limiar não é uma garantia. Ele troca cobertura por risco e só é válido para
a distribuição em que foi calibrado. Limiares ajustados no sintético são
parâmetros operacionais provisórios, não segurança institucional comprovada.

## Estado v1.8

A configuração local usa limiar geral de classificação 0,76, guarda de OBRA
0,90 e região de deduplicação com decisão negativa até 0,07 e positiva a
partir de 0,95. A região intermediária abstém. Esses valores pertencem ao
bundle v1.8 congelado e não devem ser alterados em produção sem nova versão,
manifesto, regressão e rollback.

## Ajuste científico

1. defina antes os máximos de risco e mínimos de cobertura por tarefa;
2. ajuste limiar somente em treino/calibração agrupados;
3. estime risco/cobertura fora de dobra por unidade-fonte;
4. exija limites de confiança, não apenas estimativas pontuais;
5. congele o limiar antes do holdout;
6. avalie uma vez no holdout e publique cobertura, risco e denominadores;
7. no piloto, use sombra/revisão humana e regra de rollback.

Para classificação, a promoção precisa proteger OBRA e relatar risco por
classe. Para deduplicação, decisões negativas e positivas têm custos e
denominadores diferentes; publicar FN/NPV e FP/precisão separadamente.

## Mudança gradual

Alterar cobertura somente em versões explícitas. Cada passo exige mínimo de
unidades independentes, ausência de aumento de erro crítico, calibração
aceitável, latência/SLO e revisão dos erros. Se o intervalo não qualifica o
gate, manter ou reduzir automação. Não usar meta de cobertura como obrigação de
forçar decisões.
