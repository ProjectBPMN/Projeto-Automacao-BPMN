# Protocolo few-shot secundário

O benchmark principal permanece zero-shot. Exemplos não serão adicionados antes
de seu congelamento, pois isso alteraria o tratamento e contaminaria a
comparação.

Após concluir o benchmark zero-shot, pode-se criar uma rodada secundária com
dois ou três exemplos por tarefa, escolhidos exclusivamente entre casos
adjudicados do piloto. É proibido selecionar exemplos a partir de erros do
conjunto de teste.

O experimento deve:

1. criar novas versões de prompt e novos hashes;
2. manter modelo, schemas, limiar, seed, dataset de teste e fila congelados;
3. gerar novo `run_id` sem reutilizar decisões;
4. comparar as previsões pareadas com McNemar e bootstrap episódico;
5. relatar o delta de F1 com intervalo de confiança, inclusive se não houver
   melhora.

Os exemplos só podem ser materializados depois da adjudicação do piloto. Até
lá, inserir exemplos sintéticos escolhidos pelos autores criaria viés.
