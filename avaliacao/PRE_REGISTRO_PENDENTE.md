# Decisões necessárias antes do teste confirmatório

> Decisão de escopo em 01/09/2026: o projeto não realizará verificação humana
> nem revisão em pares. Portanto, não existe gabarito independente elegível
> para a avaliação confirmatória descrita nesta pasta. Os validadores não serão
> afrouxados: o holdout one-shot permanece bloqueado e resultados com rótulos
> sintéticos, heurísticos ou derivados do próprio sistema devem ser chamados
> apenas de evidência técnica, desenvolvimento ou avaliação por rótulo-proxy.

O software pode ser testado tecnicamente sem dupla revisão humana, mas os
resultados dessa etapa são regressão, integração ou piloto. Um artigo não deve
chamar esses resultados de validação confirmatória enquanto as decisões abaixo
não forem congeladas antes da abertura de um holdout independente.

## 1. Unidade independente e gabarito

- Unidade primária: núcleo semântico/episódio, não cada paráfrase.
- Variações ortográficas do mesmo núcleo medem robustez, mas não aumentam o
  tamanho amostral inferencial.
- Gabarito confirmatório: rótulo institucional definido sem consultar a saída
  do modelo. A execução automatizada com gabarito sintético permanece
  não confirmatória.

### O plano 33 x 30 não equivale a 990 observações independentes

As 30 variações de cada cenário medem robustez a ortografia, abreviação e
formulação, mas continuam agrupadas pelo mesmo núcleo lógico. Para inferência,
o plano oferece 33 famílias de cenário, e não 990 réplicas independentes. Além
disso, a contagem operacional não é 990 tickets no GLPI: os 14 cenários de
deduplicação precisam de dois tickets por episódio. Assim, são 840 tickets de
deduplicação mais 570 de classificação, totalizando 1.410 tickets.

O plano continua útil como ensaio de regressão e estresse. Para validação
confirmatória, a amostra deve aumentar o número de núcleos novos. O planejamento
automatizado vigente propõe, como referência operacional não confirmatória,
100 núcleos independentes por classe de classificação, 189 episódios positivos
de duplicidade, 97 controles negativos difíceis completos e 73 controles
negativos críticos. Esses números não substituem a aprovação institucional da
margem e do desfecho primário.

## 2. Desfecho primário

Deve ser escolhida e registrada uma única opção antes do holdout:

1. diferença pareada de acurácia geral, contando abstenção e falha técnica como
   resultado não correto;
2. diferença pareada de custo ponderado, com matriz de custos aprovada pelo
   campus;
3. diferença no risco crítico, separando falso negativo de duplicidade e
   `MANUTENÇÃO → OBRA`.

O executor atual só pode avaliar não inferioridade para a opção 1 quando a
margem é fornecida explicitamente. H2, formulada em termos de risco crítico,
não pode ser provada por esse estimando.

## 3. Margem de não inferioridade

A margem não será inferida dos resultados observados. Ela deve representar a
maior perda considerada aceitável pelo campus e ser registrada com assinatura
ou aceite do orientador/responsável antes da chamada remota válida. Sem margem,
o relatório será apenas descritivo.

## 4. Erro crítico `MANUTENÇÃO → OBRA`

O requisito operacional é observar zero encaminhamentos automáticos desse tipo
no holdout, mas zero ocorrências não prova risco zero. Se não houver eventos, a
regra aproximada de três fornece os seguintes tamanhos mínimos de casos de
manutenção para limitar o extremo superior unilateral de 95%:

| Limite superior desejado | Casos de manutenção sem o erro |
|---:|---:|
| 5% | 60 |
| 2% | 150 |
| 1% | 300 |

O limite aceitável deve ser escolhido pelo responsável institucional antes do
holdout. Abstenções não contam como `MANUTENÇÃO → OBRA`, mas entram na cobertura
e na carga humana.

## 5. Falhas técnicas e abstenções

- Uma resposta 429, timeout, schema inválido ou transporte inválido impede uma
  conclusão de não inferioridade naquela rodada.
- A análise operacional deve manter todas as falhas no denominador.
- O modelo secundário nunca substitui silenciosamente o modelo avaliado.
- Abstenção é relatada separadamente e, no desfecho de acurácia geral, não é
  tratada como acerto.

## 6. Vazão e eficiência

A configuração do WF06 só pode ser chamada de ótima quando houver critérios
numéricos congelados para falha, p95, tempo de drenagem e uso de recursos. Sem
esses valores, a calibração escolhe somente uma configuração operacionalmente
elegível entre as testadas.

Para H4, ainda é necessário cronometrar uma amostra do processo manual e definir
como contabilizar confirmação fiscal, triagem, correção de falso positivo e
chamados abstidos.

## Estado

`BLOQUEADO_SEM_GABARITO_INDEPENDENTE`. Nenhuma margem, limite institucional ou
baseline manual foi inventado pelo código. Sem revisão humana, o piloto pode
validar somente contrato, estabilidade e coleta técnica; não sustenta uma
conclusão confirmatória de eficácia ou não inferioridade.
