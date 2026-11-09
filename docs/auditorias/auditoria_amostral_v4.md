# Auditoria amostral e decisão da etapa automatizada V4/V4.1

> [!WARNING]
> **Snapshot histórico.** Alguns artefatos citados na redação original não
> estão presentes no snapshot atual do repositório; essas referências são
> mantidas abaixo como nomes históricos, sem link e sem valor de evidência
> verificável. Para o estado vigente, consulte
> `auditoria_critica_completa_2026-08-26.md`.

## Estado e escopo da decisão

Esta auditoria registra a decisão metodológica tomada em 15/07/2026. A etapa
imediata executará todas as validações automatizadas possíveis, sem dupla
revisão humana dos rótulos. Essa decisão não remove, desvia ou simula como
humana nenhuma confirmação existente nos workflows. Os pontos de aprovação
fiscal e de triagem continuam no fluxo; durante o experimento, o oráculo
determinístico externo de teste pode responder conforme o gabarito somente
depois de a predição da IA ter sido persistida. Essa ação não é revisão humana
nem validação externa.

Os resultados desta etapa medem:

- concordância do modelo com o gabarito sintético determinístico;
- regressões funcionais e integridade ponta a ponta do projeto;
- comportamento diante de ambiguidade, falta de informação e contraste;
- latência, vazão, fila, falha, retentativa e custo observado.

Eles não medem validade real dos rótulos subjetivos. Sem avaliação humana
independente, não se pode chamar o rótulo sintético de padrão-ouro humano nem
generalizar a concordância observada como acurácia no cotidiano do GLPI.

Esta auditoria é um plano. O corpus V4/V4.1 ainda não foi gerado e nenhuma
contagem planejada abaixo constitui resultado de eficácia. A revisão V4.1
corrige especificamente a potência necessária para o limite inferencial de
falso negativo de deduplicação; ela não autoriza gerar novos casos nesta etapa.

## Fontes locais auditadas

- [`corpus_v3_teste_manifest.json`](../avaliacao/datasets/corpus_v3_teste_manifest.json):
  contagens, dependência entre realizações e gates do corpus atual;
- [`catalogo_corpus_v3.json`](../avaliacao/datasets/catalogo_corpus_v3.json):
  famílias, perfis, templates e estratos semânticos;
- [`planejamento_amostral_v2.json`](../avaliacao/datasets/planejamento_amostral_v2.json):
  margem de 10%, IC95% e requisito aproximado de 155 pares para McNemar;
- [`plano_seed_33x30.json`](../avaliacao/config/plano_seed_33x30.json):
  contabilidade das realizações e dos tickets do conjunto naturalístico atual;
- [`plano_amostral_automatizado_v4.json`](../avaliacao/config/plano_amostral_automatizado_v4.json):
  contrato executável schema `4.1.0`, com meta de 189 episódios positivos,
  expansão de 878 tickets e total lógico planejado de 2.078;
- [`metodologia_avaliacao.md`](../avaliacao/metodologia_avaliacao.md): unidade
  experimental, bootstrap hierárquico e limites de validade;
- `resultados_tecnicos_2026-07-14.md`: evidência técnica histórica anterior à
  ampliação amostral; artefato ausente do snapshot atual;
- `contrato_provedores_2026-07-14.json`: ensaio histórico dos contratos dos
  provedores; artefato ausente do snapshot atual.

## Suficiência do corpus V3

O V3 contém 1.200 chamados, mas suas cinco realizações superficiais não são
cinco observações semânticas independentes. Para proporções no pior caso
`p=0,5`, o IC95% de Wilson aproximado é:

| Estrato | Linhas nominais | Núcleos independentes | Meia largura do IC95% pelos núcleos |
|---|---:|---:|---:|
| Classificação total | 200 | 40 | 14,8 pontos percentuais |
| Cada classe semântica | 50 | 10 | 26,3 pontos percentuais |
| Deduplicação `challenge_only` | 500 | 100 | 9,6 pontos percentuais |
| Duplicado verdadeiro | 200 | 40 | 14,8 pontos percentuais |
| Não duplicado difícil | 300 | 60 | 12,3 pontos percentuais |
| Cada família de contraste | 20 | 4 | 35,0 pontos percentuais |
| Negativo crítico/insuficiente | 60 | 12 | 24,6 pontos percentuais |
| Positivo com informação parcial | 20 | 4 | 35,0 pontos percentuais |

Há duas fontes explícitas de agrupamento:

1. cinco paráfrases compartilham o mesmo `narrative_core`;
2. os 100 núcleos dedup combinam 25 famílias com somente 20 perfis-base de
   ativos, que aparecem em mais de uma família.

Por isso, outra execução com um novo valor de `seed` não aumenta a amostra
semântica. Ela muda namespace, ordem e atributos derivados, mas reutiliza os
mesmos núcleos. Execuções repetidas continuam úteis para estabilidade do
serviço e desempenho, mas são medidas repetidas.

O planejamento local exige 97 observações independentes por classe para margem
aproximada de dez pontos percentuais e 155 pares independentes para 80% de
poder na comparação McNemar assumida. O V3 não atinge esses requisitos por
classe quando a pseudorreplicação é removida.

## Interpretação do seed `primary33` com 30 realizações

O conjunto solicitado para a etapa automatizada possui 33 cenários principais:
D01–D14 e C01–C19. Trinta realizações por cenário produzem 990 realizações de
cenário, mas não 990 chamados. Os cenários D são episódios pareados e os C são
casos unitários:

| Parcela | Realizações | Tickets por realização | Chamados GLPI |
|---|---:|---:|---:|
| D01–D14 | 420 | 2 | 840 |
| C01–C19 | 570 | 1 | 570 |
| **`primary33`** | **990** | — | **1.410** |

O conjunto `stress2`, formado por D15 e C20, permanece suplementar. Se ambos
forem executados 30 vezes, adicionam 90 tickets; a união `all35` produz 1.500
tickets. Esses 90 casos não são contabilizados no volume do `primary33`.

Essa ampliação nominal é valiosa para testar erros ortográficos, abreviações,
urgência textual e estabilidade da fila. Entretanto, as 30 versões continuam
compartilhando a estrutura semântica de seu cenário. Elas devem ser tratadas
como medidas repetidas de robustez, agrupadas por `scenario_id` e, nos pares,
por `episode_id`; não equivalem a 30 novos núcleos narrativos. Assim, o seed
33×30 não substitui uma expansão com núcleos/episódios semanticamente novos e
não autoriza usar `n=990` no cálculo como se houvesse independência total.

Também é necessário separar dimensão de rótulo: D significa “caso da tarefa de
deduplicação”, e não “duplicado verdadeiro”. D01, D06, D07, D12 e D13 são
positivos; os demais D do `primary33` são controles negativos, além de cada
primeiro ticket âncora receber `expected_dedup=false`.

## Desenho revisado para o corpus V4.1

A expansão deve adicionar conteúdo semanticamente novo, não apenas novas
saudações ou outra seed. O alvo aprovado é:

| Estrato primário | Núcleos atuais | Meta V4.1 | Novos núcleos | Novos chamados GLPI |
|---|---:|---:|---:|---:|
| Classificação, quatro classes | 40 | 400, 100 por classe | 360 | 360 |
| Dedup positivo | 40 | 189 | 149 | 298 |
| Dedup negativo completo | 48 | 97 | 49 | 98 |
| Dedup negativo crítico/insuficiente | 12 | 73 | 61 | 122 |
| **Total** | **140** | **759** | **619** | **878** |

O aumento futuro revisado é, portanto, de 878 chamados originados por 619 novos
núcleos/episódios independentes. Somados aos 1.200 chamados existentes, o
corpus lógico terá aproximadamente 2.078 chamados. A revisão acrescenta 89
episódios positivos, ou 178 tickets, ao desenho V4 anterior de 700 chamados.
Nenhum desses casos adicionais é gerado na etapa corrente.

No V3, 960 chamados são realizações adicionais de núcleos já apresentados: 800
na deduplicação e 160 na classificação. Eles são preservados como conjunto
secundário de robustez linguística. Na análise primária, apenas uma realização
por núcleo pode contribuir como unidade independente; a realização escolhida
deve ser sorteada e balanceada entre estilos.

As metas produzem:

- margem Wilson de aproximadamente 9,6 pontos por classe com 100 núcleos;
- margem de aproximadamente 9,8 pontos para 97 negativos completos;
- limite superior Wilson bilateral de aproximadamente 1,99% se forem
  observados zero falsos negativos em 189 episódios positivos independentes;
- limite superior Wilson de aproximadamente 5% se forem observados zero falsos
  positivos entre 73 negativos críticos;
- mais de 155 casos independentes nas análises agregadas de comparação entre
  modelos.

Se ocorrer um falso positivo no estrato crítico, 73 casos deixam de sustentar o
limite superior de 5%; seriam necessários pelo menos 110 casos nesse estrato
sob o mesmo cálculo. Resultados individuais das 25 famílias permanecem
exploratórios, pois mesmo dez núcleos por família geram intervalos largos.
Os 189 positivos são o mínimo otimista para zero FN. Se houver qualquer FN, o
gate de 2% não é satisfeito nesse tamanho; não se acrescentam casos pós-hoc
somente para estreitar o intervalo. Isso exige novo protocolo/amostra ou leva à
rejeição do candidato no critério pré-registrado.

### Uso permitido do V3 antes da expansão

O V3 reservado contém 200 linhas positivas, mas elas derivam de somente 40
núcleos positivos independentes, com cinco realizações superficiais por núcleo.
Tratar `n=200` como independente daria um intervalo artificialmente estreito e
contradiria a unidade experimental deste protocolo. Com zero FN, o limite
superior Wilson bilateral é aproximadamente 8,76% para `n=40`; portanto, o V3
não demonstra o gate inferencial de 2%.

Nesta etapa, o candidato LOCAL pode ser executado nas 200 linhas para medir a
concordância no corpus V3 fixo e a robustez entre paráfrases. A incerteza deve
ser obtida por bootstrap hierárquico/agrupado por núcleo. “0/200 no corpus
fixo”, se observado, não pode ser reescrito como “taxa populacional abaixo de
2%”.

O `primary33` contém 420 desafios D, mas somente D01, D06, D07, D12 e D13 são
positivos: 150 linhas positivas derivadas de cinco cenários. Ele também não
fornece 150 episódios semanticamente independentes para esse gate.

Uma comparação Gemini limitada a aproximadamente 100 linhas positivas é
exploratória. Ela pode ser pareada caso a caso com LOCAL e reportar deltas no
subconjunto, mas não sustenta não inferioridade no limite de 2%.

## Estratos prioritários para os novos núcleos

- ausência de sala, ativo, identificador ou sintoma;
- mesmo ambiente com ativos distintos;
- mesmo ativo com sintomas diferentes;
- problema não resolvido versus novo incidente após encerramento;
- descrição curta versus detalhada e solicitantes diferentes;
- telhado integral versus reparo localizado, inclusive estrutura rural;
- parede estrutural versus divisória leve;
- fronteiras `OBRA`–`DEMO` e `DEMO`–`SOB_DEMANDA`;
- múltiplos problemas, contradição, ruído e instrução maliciosa no texto.

Os perfis-base também devem ser ampliados. Recombinar repetidamente os mesmos
20 ativos com novas famílias não equivale a criar 619 exemplos independentes.

## Regra de publicação desta etapa

Os relatórios devem usar expressões como “concordância com referência sintética
pré-especificada”, “teste automatizado controlado” e “validade interna da
simulação”. Devem evitar “padrão-ouro”, “decisão correta no mundo real” e
“eficácia confirmada” enquanto não houver validação humana ou externa.

As matrizes de confusão, F1 e intervalos podem ser calculados, desde que o
título das tabelas identifique o gabarito sintético e que as realizações sejam
agrupadas por família, perfil-base, núcleo e episódio. A dupla revisão permanece
como uma fase futura opcional para transformar a evidência sintética em
evidência confirmatória; ela não bloqueia os testes automatizados desta etapa.
