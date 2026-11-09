# Limitação desta rodada

A rodada isolada produziu 1.239 respostas válidas em 1.240 unidades. Uma unidade
de deduplicação recebeu HTTP 503 por falta de memória no Granite FP32. Portanto:

- pode ser usada apenas numa comparação conservadora de sistema, contando o
  503 como erro de disponibilidade;
- não pode sustentar comparação confirmatória nem uma afirmação de estabilidade;
- não deve ser apresentada como rodada integralmente válida do modelo.

Após a falha, o serviço passou a usar micro-lotes de quatro textos. O piloto
subsequente de 30 unidades terminou com 30 respostas válidas, mas não substitui
uma repetição integral independente.

