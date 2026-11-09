# Cenários do dataset episódico

O registro auditável fica em `datasets/cenarios_v2.json`. Cada `D` possui dois
tickets relacionados; cada `C` possui um. IDs são globais por split/seed e não
aparecem no texto.

## Deduplicação

| Código | Contraste | Segundo ticket |
| D01 | mesmo ar, descrição detalhada e curta | duplicado |
| D02 | lâmpadas diferentes na mesma sala | não duplicado |
| D03 | mesmo solicitante, tomadas diferentes | não duplicado |
| D04 | mesmo bloco sem sala exata | não duplicado |
| D05 | mesmo ar, sintomas diferentes | não duplicado |
| D06 | defeito persistiu após manutenção | duplicado |
| D07 | mesma porta, paráfrase curta | duplicado |
| D08 | objetos próximos mas distintos | não duplicado |
| D09 | mesmo defeito em salas diferentes | não duplicado |
| D10 | genérico seguido de específico | não duplicado |
| D11 | relatos vagos do mesmo equipamento | não duplicado |
| D12 | reabertura explícita por outra pessoa | duplicado |
| D13 | referência explícita ao ticket anterior | duplicado |
| D14 | mesmo serviço em locais diferentes | não duplicado |
| D15 | mesmo ativo com baixa sobreposição lexical | duplicado |

Falso positivo é o erro prioritário porque pode bloquear um chamado legítimo.
A referência também deve apontar ao ticket anterior correto.

## Classificação

| Código | Contraste | Esperado |
| C01 | ampliação/parede estrutural | `OBRA` |
| C02 | divisória interna simples | `DEMO` |
| C03 | telhado integral com estrutura | `OBRA` |
| C04 | telhas localizadas em instalação rural | `DEMO` |
| C05 | climatização especializada | `SOB_DEMANDA` |
| C06 | elétrica simples | `DEMO` |
| C07 | disponibilidade citada no texto | `DEMO`; ignorar estado textual |
| C08 | ativo/local insuficientes | `TRIAGEM_MANUAL` |
| C09 | sistema/senha fora do escopo | `TRIAGEM_MANUAL` |
| C10 | categoria GLPI errada | usar descrição |
| C11 | prompt injection | ignorar comando; `DEMO` |
| C12 | contradição | `TRIAGEM_MANUAL` |
| C13 | rampa nova com fundação | `OBRA` |
| C14 | reparo de rampa | `DEMO` |
| C15 | portão automático | `SOB_DEMANDA` |
| C16 | CFTV | `SOB_DEMANDA` |
| C17 | problemas de executores distintos | `TRIAGEM_MANUAL` |
| C18 | erros, abreviações e gírias | `DEMO` |
| C19 | urgência não muda serviço simples | `DEMO` |
| C20 | texto acima de 4.000 caracteres | `SOB_DEMANDA` |

`DEMO_SEM_EQUIPE` é desfecho operacional, não classe semântica da LLM. Ele é
testado repetindo casos DEMO com `DEMO_EQUIPE_DISPONIVEL=false` congelado.

## Volume

- Piloto: 50 tickets, 35 episódios e 94 decisões cegas.
- Benchmark mínimo planejado: 33 variações, 1.650 tickets e 1.155 episódios.
- A auditoria final cobre riscos/erros e uma amostra estratificada dos demais.

A distribuição é deliberadamente estratificada para teste defronteiras. Ela não deve ser chamada de realista sem prevalências estimadas em dados reais anonimizados.
