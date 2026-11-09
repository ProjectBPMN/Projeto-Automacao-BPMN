# Estado dos resultados técnico-científicos — 15/07/2026

> [!WARNING]
> **Snapshot histórico, superado pela auditoria de 26/08/2026.** A seleção
> citada neste documento não sustenta ranking atual: derivados de poucas
> famílias-fonte não ficaram integralmente no mesmo grupo. Toda classificação
> permanece sintética e a deduplicação antiga é subdimensionada. Use
> `auditoria_critica_completa_2026-08-26.md` e
> `resposta_professor_2026-08-26.md` como estado canônico.

> DOCUMENTO HISTÓRICO. Não representa o bundle v1.8 nem o estado dos testes de
> 16/07 ou 12/08. Consulte `resposta_professor_selecao_modelos_2026-08-12.md`,
> `../n8n/workflows/Versão9/TEST_REPORT.md` e o README da raiz antes de citar
> qualquer número. A seleção v1.3 de 90 configurações terminou em 17/08/2026;
> seus resultados atuais estão em `estado_projeto_2026-08-17.md`.

## Conclusão executiva

O projeto possui evidência atual de que os componentes de software, os
contratos de dados e as interfaces principais estão estruturalmente íntegros.
Isso autoriza prosseguir com ensaios controlados. Ainda não existe, porém, uma
estimativa válida de acurácia, precisão, recall, F1 ou eficácia do modelo de IA.

Na mesma data, o projeto também produziu um bundle candidato local PyTorch FP32
calibrado e congelado apenas em dados sintéticos de desenvolvimento. Esse
resultado autoriza abrir uma avaliação independente, mas não altera a conclusão
acima: ainda não há eficácia científica demonstrada nem comparação válida com
Gemini.

A execução `VALIDACAO-AUTOMATIZADA-20260715-A` falhou por indisponibilidade do
provedor principal e ficou contaminada por registro parcial do controle
experimental. Ela foi encerrada de forma auditável e deve ser tratada como
diagnóstico operacional negativo, não como resultado de eficácia. Nenhum índice
de acerto é calculado a partir dessa execução.

Depois das correções, a microvalidação
`VALIDACAO-FREE-SMOKE-20260715-C` concluiu o caminho real de três chamados com
o `gemini-3.1-flash-lite` fixo: cinco chamadas válidas ao modelo, fila drenada
em 175 segundos, uma ação no endpoint fiscal acionada pelo oráculo determinístico
externo de teste e
zero erro técnico. Esse resultado comprova integração e proveniência, não
acurácia científica.

Em termos científicos, há três conjuntos de evidência que não devem ser
misturados:

1. testes de engenharia, que verificam código, configuração, interfaces e fila;
2. testes de contrato dos provedores, que verificam disponibilidade e formato
   da resposta em uma chamada mínima;
3. experimentos de eficácia, que exigem execução completa, proveniência íntegra,
   modelo fixo e análise na unidade experimental correta.

## 1. Testes de engenharia aprovados

As verificações abaixo foram reexecutadas ou conferidas em 15/07/2026.

| Verificação | Resultado | O que demonstra | O que não demonstra |
|---|---:|---|---|
| Suítes automatizadas da revisão atual | fechamento pendente após o freeze | A contagem final será publicada somente depois da última regeneração dos workflows e da promoção/rejeição do candidato local | Funcionamento de todos os serviços externos sob carga real |
| Validação estática V9 da revisão atual | fechamento pendente após o freeze | Evita reutilizar a contagem de uma revisão anterior depois da inclusão da barreira persistence-first no WF03 | Qualidade das decisões produzidas pela IA |
| Configuração Docker Compose | aprovada | A configuração combinada de `n8n/.env`, `n8n/.env.local` e `n8n/docker-compose.yml` é válida | Capacidade máxima ou estabilidade prolongada |
| Inventário canônico após as correções locais | 6 workflows, 166 nós, 46 nós `Code` | O pacote WF01–WF06 inclui barreira de persistência antes da ação no WF02 e no WF03, além da integração local-first | Implantação final ou eficácia das decisões da IA |
| Navegador, somente leitura | 12/12 verificações aprovadas | n8n, GLPI e Mailpit responderam; login/leitura funcionaram; os seis workflows V9 estavam ativos | Processamento correto de chamados ou eficácia da IA |

O ensaio de navegador criou zero chamados e fez zero alterações em workflows.
O resultado detalhado está em
[`browser_2026-07-15/resultado.json`](../avaliacao/resultados/browser_2026-07-15/resultado.json).

Na republicação anterior à revisão local-first, uma leitura REST autenticada
confirmou, nos seis workflows, `active=true`, `activeVersionId=versionId` e
igualdade entre o hash canônico então vigente e a lógica publicada. Essa
evidência não comprova a implantação dos JSONs atuais de 166 nós; o mesmo teste
deve ser repetido depois do deploy final. O backup daquela republicação está em
`backups/n8n/workflows-v9/rest-session-20260715-114117`. Os dois utilitários de
deploy também passaram a tratar `--help` sem executar implantação; o teste
terminou com código zero e não criou novo backup.

Comandos usados para as verificações locais reproduzíveis:

```powershell
python -m unittest `
  avaliacao.tests.test_gateway_multimodelo `
  avaliacao.tests.test_oraculo_deterministico `
  avaliacao.tests.test_correcao_cientifica `
  avaliacao.tests.test_retry_backoff_queue `
  avaliacao.tests.test_validacao_automatizada `
  avaliacao.tests.test_validar_rotulos_nucleos_v3 -v
python n8n/workflows/Versão9/validate_v9_static.py
docker compose --env-file n8n/.env --env-file n8n/.env.local `
  -f n8n/docker-compose.yml config --quiet
```

Esses resultados permitem afirmar que a infraestrutura de avaliação está
tecnicamente preparada para novos testes. Eles não permitem afirmar que o
modelo classifica corretamente chamados reais.

## 2. Contrato observado dos provedores

O teste de contrato enviou uma solicitação sintética mínima pelo mesmo ambiente
do n8n. Seu propósito foi verificar disponibilidade, latência pontual e retorno
em JSON; não houve avaliação de chamados do corpus.

| Papel | Provedor/modelo | HTTP | JSON conforme o contrato | Latência observada | Interpretação restrita |
|---|---|---:|---:|---:|---|
| `PRIMARY` | Google `gemini-3.5-flash` | 429 | não | 1.079 ms | quota indisponível no instante do teste |
| `SECONDARY` | Google `gemini-2.5-flash` | 429 | não | 738 ms | quota indisponível no instante do teste |
| `FREE_CONTINGENCY` | Google `gemini-3.1-flash-lite` | 200 | sim | 1.491 ms | contrato mínimo operacional nesta chamada |
| `TERTIARY` | DeepSeek `deepseek-v4-flash` | 402 | não | 1.808 ms | conta sem saldo suficiente |

Fonte histórica declarada na redação original:
`contrato_provedores_2026-07-15.json`. O arquivo não está presente no snapshot
atual e, portanto, os valores desta tabela não são evidência revalidável aqui.

O código HTTP 429 não prova que o modelo principal ou o secundário seja menos
inteligente ou intrinsecamente instável; prova apenas que não havia quota útil
para essas chamadas. Da mesma forma, um único HTTP 200 com JSON válido não prova
que o `gemini-3.1-flash-lite` erre menos. Ele é, neste momento, o único dos
quatro papéis que passou no contrato mínimo e foi, por isso, usado no smoke
test controlado descrito adiante.

O papel `FREE_CONTINGENCY` usa a credencial Google secundária configurada no
projeto. Portanto, sua disponibilidade deve continuar sendo medida, e não
presumida. Em experimentos de comparação, cada papel deve ser congelado em um
`run_id` próprio, com fallback desabilitado. O fallback é aceitável para a
operação cotidiana, mas não pode substituir silenciosamente o modelo avaliado.

## 3. Execução automatizada encerrada sem resultado de eficácia

### 3.1 Identificação e desenho executado

- `run_id`: `VALIDACAO-AUTOMATIZADA-20260715-A`;
- fase: `VALIDACAO` automatizada e não confirmatória;
- modelo fixo: `PRIMARY`, `gemini-3.5-flash`;
- fallback: desabilitado;
- dataset efetivamente criado: uma realização dos 35 cenários então
  registrados, totalizando 50 tickets GLPI;
- manifesto congelado histórico:
  `VALIDACAO-AUTOMATIZADA-20260715-A/freeze_manifest.json` (ausente do snapshot
  atual);
- resumo histórico da carga:
  `VALIDACAO-AUTOMATIZADA-20260715-A/dataset_resumo.md` (ausente do snapshot
  atual).

Essa execução antecede a separação explícita entre `primary33` e `stress2`.
Logo, seus 50 tickets não correspondem ao futuro ensaio `primary33` com 30
realizações por cenário.

### 3.2 Falha e contaminação

O experimento atingiu o limite de 3.600 segundos com nove itens ainda pendentes
naquele instante e predominância de respostas HTTP 429. Além disso, uma falha
no registro inicial permitiu que apenas parte das associações do
`dataset_controle` estivesse presente enquanto alguns workflows já eram
executados. As 50 associações foram restauradas por replay SQL e a proveniência
foi reparada para auditoria, mas reparo posterior não transforma o ensaio em
execução experimental limpa.

O registro final do experimento contém explicitamente:

- `status = FALHOU_AUTOMATIZADO`;
- `scientific_result = false`;
- `confirmatory_eligible = false`;
- `contaminated_by_partial_control = true`;
- `provenance_repaired = true`;
- `validation_status = FAILED_INTEGRITY_AND_RATE_LIMIT`.

### 3.3 Estado final auditado

Uma consulta de encerramento ao PostgreSQL encontrou os 50 tickets associados
ao `run_id`:

| Estado final observado | Tickets |
|---|---:|
| `ATRIBUIDO_DEMO` | 11 |
| `PENDENTE` | 2 |
| `ERRO_IA` | 37 |
| **Total** | **50** |

Após o encerramento e a recuperação auditável, a fila de IA ativa global estava
em zero. Os dois casos `PENDENTE` não justificam remover confirmações humanas:
os pontos de confirmação permanecem parte do comportamento esperado dos
workflows, mesmo sem dupla revisão humana de rótulos nesta etapa de testes.

Esses estados são resultados operacionais, não rótulos de acerto. Por exemplo,
`ATRIBUIDO_DEMO` informa qual caminho foi concluído, mas não prova que DEMO era o
gabarito correto. Como a execução foi incompleta e contaminada, não devem ser
geradas a partir dela matriz de confusão, acurácia, F1, taxa de falso positivo
ou comparação entre modelos. O resultado publicável é apenas: a execução
detectou um gargalo de quota, falhou de modo controlado, preservou a auditoria e
terminou sem itens ativos na fila.

## 4. Microvalidação ponta a ponta com o modelo gratuito

A primeira tentativa curta, `VALIDACAO-FREE-SMOKE-20260715-B`, revelou antes da
IA que o Windows enviava SQL acentuado ao `psql` em CP-1252 enquanto o banco
esperava UTF-8. O ensaio foi marcado como `FALHOU_AUTOMATIZADO`, o ticket parcial
foi associado ao `run_id` e a falha ficou auditável. O gerador passou a enviar
bytes UTF-8 explícitos, ganhou um teste de regressão e a correção foi comprovada
contra o PostgreSQL real.

A repetição limpa `VALIDACAO-FREE-SMOKE-20260715-C` produziu:

| Evidência | Resultado |
|---|---:|
| Cenários suplementares | D15 e C20 |
| Chamados GLPI | 3/3 registrados (`#230`–`#232`) |
| Tentativas de deduplicação | 3 válidas, schema válido |
| Tentativas de classificação | 2 válidas, schema válido |
| Papel/modelo em todas as tentativas | `FREE_CONTINGENCY` / `gemini-3.1-flash-lite` |
| Fallback | desabilitado |
| Ações no endpoint fiscal pelo oráculo externo de teste | 1 |
| Erros técnicos | 0 |
| Tempo até fila zerada | 175 s |
| Estado do experimento | `CONCLUIDO_AUTOMATIZADO` |
| Resultado científico confirmatório | não |

Os estados finais foram `ATRIBUIDO_DEMO`, `DUPLICADO_FECHADO` e
`ENCAMINHADO_PLANEJADO`. Eles demonstram que WF06, WF02, WF03 e WF04
completaram seus caminhos, inclusive a confirmação de duplicidade, preservando
`run_id`, papel e modelo desde o início. A execução continuou marcada com
`scientific_result=false`, `confirmatory_eligible=false`, sem rótulos humanos e
sem auditoria humana. A redação original citava
`VALIDACAO-FREE-SMOKE-20260715-C/relatorio.md`, artefato ausente do snapshot
atual e que não pode ser revalidado por este repositório.

Essa ação da microvalidação foi acionada pelo oráculo determinístico externo de
teste, não por uma pessoa. Ela comprova que o endpoint real do WF04
aceitou a transição depois da predição; não constitui dupla revisão nem valida o
gabarito. Nas próximas rodadas, o novo contrato exige guardas `test-only`,
separação temporal/estrutural contra *label leakage*, idempotência e trilha
separada em `avaliacao_auto_confirmacoes`, conduzida pelo harness externo
`conferir_gabarito.py` através dos mesmos endpoints WF04/WF05, nunca por ramo do
WF06 ou identidade humana. Ela não é dupla revisão humana, avaliação humana nem
validação externa. Os checkpoints permanecem inalterados em produção.

Três chamados não estimam taxa de erro. Esta microvalidação só autoriza a
afirmação de que o caminho automatizado funciona com o modelo gratuito quando
ele é fixado e está disponível.

## 5. Contabilidade correta do plano `primary33`

O plano possui 33 cenários: 14 episódios de deduplicação, D01–D14, e 19 casos
unitários de classificação/controle, C01–C19. Com 30 realizações naturalísticas
por cenário:

| Bloco | Realizações de cenário | Tickets por realização | Tickets GLPI |
|---|---:|---:|---:|
| D01–D14 | 14 × 30 = 420 episódios | 2 | 840 |
| C01–C19 | 19 × 30 = 570 casos | 1 | 570 |
| **Total `primary33`** | **990 realizações** | — | **1.410 tickets** |

Portanto, `33 × 30 = 990` está correto como número de realizações de cenário,
mas não como volume de tickets a ser liberado no GLPI. O volume operacional é
1.410 tickets. O conjunto suplementar `stress2` contém D15 e C20; com 30
realizações de cada, ele acrescenta 90 tickets e leva `all35` a 1.500 tickets.

Fonte: [`plano_seed_33x30.json`](../avaliacao/config/plano_seed_33x30.json).

Há também uma distinção de rótulo importante. O prefixo D identifica uma tarefa
de deduplicação, não um duplicado verdadeiro. No plano atual, D01, D06, D07,
D12 e D13 são cenários positivos; D02, D03, D04, D05, D08, D09, D10, D11 e
D14 são controles negativos. Além disso, o primeiro ticket de cada episódio é
a âncora e recebe `expected_dedup=false`. Essa definição deve ser pré-registrada
e mantida idêntica entre gerador, banco e análise.

## 6. Risco de pseudorreplicação

As 30 versões de um cenário variam ortografia, abreviações, urgência e estilo,
mas continuam derivadas do mesmo núcleo semântico. Elas são úteis para medir
robustez linguística e repetibilidade operacional; não equivalem a 30 casos
semânticos independentes.

Usar `n = 990` como se todas as observações fossem independentes produziria
intervalos de confiança artificialmente estreitos e aumentaria o risco de uma
conclusão excessiva. A análise deve respeitar a estrutura hierárquica:

- `episode_id` é a unidade do teste de deduplicação;
- `case_id` é a unidade do teste de classificação;
- as realizações devem permanecer agrupadas por `scenario_id`;
- intervalos devem usar reamostragem/estimativa agrupada, sem quebrar episódios;
- resultados por variação superficial são análises de robustez, não aumento da
  amostra semântica.

A auditoria amostral concluiu que o corpus atual é suficiente para regressão
funcional automatizada, mas não para estimativas científicas precisas por
classe e o gate inferencial de FN ≤ 2%. O plano futuro V4.1 recomenda
acrescentar 619 núcleos/episódios semanticamente novos, correspondentes a 878
novos tickets, para um corpus lógico próximo de 2.078 tickets. Nenhum caso novo
é gerado nesta etapa. Detalhes:
[`auditoria_amostral_v4.md`](auditoria_amostral_v4.md)
e
[`auditoria_suficiencia_amostral_2026-07-15.json`](../avaliacao/resultados/auditoria_suficiencia_amostral_2026-07-15.json).

## 7. Próximos resultados que podem ser considerados válidos

### 7.1 Validade de engenharia e disponibilidade

1. Repetir o contrato de cada provedor em horários pré-definidos. Reportar
   disponibilidade, HTTP, latência e JSON válido separadamente de eficácia.
2. Calibrar vazão com cargas crescentes e critério de parada pré-registrado,
   medindo throughput, p50/p95 de latência, tamanho máximo da fila, retentativas,
   erros e tempo de drenagem.

### 7.2 Validade da avaliação automatizada

1. Congelar dataset, prompts, schema, modelo, papel, seed e configuração antes
   da primeira chamada.
2. Executar `primary33` em ordem controlada pela fila: 990 realizações e 1.410
   tickets, sem misturar modelos dentro do mesmo `run_id`.
3. Comparar modelos em execuções separadas sobre exatamente os mesmos casos.
   A ordem pode ser balanceada, mas o fallback deve permanecer desabilitado.
4. Calcular concordância com a referência sintética, explicitando essa natureza
   no título das tabelas. Para deduplicação, reportar também falsos positivos nos
   controles; para classificação, matriz de confusão e métricas por classe;
   para operação, latência, vazão, erros e cobertura de triagem humana.
5. Estimar incerteza respeitando `scenario_id`, `episode_id` e os núcleos
   semânticos, sem contar paráfrases como observações independentes.

Sem dupla revisão humana nesta fase, um ensaio íntegro poderá produzir
**concordância com gabarito sintético pré-especificado** e resultados válidos de
engenharia/robustez interna. Ele ainda não estabelecerá validade externa nem
“acurácia no cotidiano do GLPI”. Para uma afirmação confirmatória futura, será
necessária validação humana ou externa de uma amostra independente, além da
expansão de núcleos semânticos indicada na auditoria V4.

## 8. Regra de uso no artigo

Pode ser usado agora:

- “a suíte de engenharia foi aprovada”;
- “o teste de contrato observou disponibilidade apenas no papel
  `FREE_CONTINGENCY` naquele instante”;
- “a primeira execução automatizada revelou gargalo de quota e foi invalidada
  para eficácia por contaminação de proveniência”;
- “a fila foi encerrada sem itens ativos após a recuperação”;
- “uma microvalidação de três chamados concluiu o fluxo com o Flash-Lite fixo,
  sem fallback e sem erros técnicos”;
- “o plano `primary33` contém 990 realizações e 1.410 tickets”.

Não pode ser usado a partir da evidência atual:

- “o modelo alcançou X% de acurácia”;
- “o modelo gratuito erra menos”;
- “37 casos de `ERRO_IA` equivalem a 37 decisões incorretas”;
- “as 990 realizações são 990 observações semânticas independentes”;
- “o projeto já comprovou eficácia no cotidiano do GLPI”.

## 9. Candidato local PyTorch FP32 — evidência histórica da mesma data

A política operacional daquela revisão foi alterada para local-first, ainda com
a cadeia `LOCAL → PRIMARY → SECONDARY → FREE_CONTINGENCY → TERTIARY`. Essa
cadeia foi substituída em 16/07/2026 por `LOCAL → SECONDARY`, sendo
`SECONDARY=gemini-3.5-flash`. O papel `LOCAL` combina TF-IDF, Granite Embedding 97M de 384
dimensões em PyTorch FP32 e regressão logística calibrada. Essa alteração de
arquitetura não muda retroativamente os resultados das execuções remotas
descritas nas seções anteriores.

### 9.1 Runtime de embedding

O benchmark isolado de 1, 2 e 4 threads selecionou quatro threads pelo critério
pré-definido de menor p95 no lote de deduplicação de sete textos. O resultado
selecionado registrou p95 de 501,9 ms nesse lote, p95 de 119,9 ms no lote de
classificação de um texto e RSS máximo amostrado de 822,0 MB. A redação
original citava `benchmark_embedding_pytorch_fp32_2026-07-15.json`; esse
artefato está ausente do snapshot atual, então os valores são apenas registro
histórico não revalidado.

Esses valores medem apenas embeddings aquecidos no processo Python. Não medem
vetorização TF-IDF, regressão, HTTP, n8n, banco, GLPI ou latência ponta a ponta.

### 9.2 Treino e calibração de desenvolvimento

O treino preservado em
`avaliacao/resultados/treino-local-pytorch-fp32-v1.1.0-conservador-20260715`
produziu o bundle candidato conservador `CALIBRATED`, `candidate_frozen=true` e
`evaluation_eligible=true`. O próprio manifesto mantém
`scientifically_validated=false`, `scientific_result=false`,
`test_data_used=false` e `primary33_used=false`.

Os limiares internos selecionados foram 0,67 para classificação, 0,95 para
duplicidade positiva e 0,08 para não duplicidade. Na calibração sintética
agrupada, a classificação cobriu 136/160 casos e acertou 135/136 dos cobertos;
a deduplicação observou 70 TP, 80 TN, 0 FP e 0 FN. Esses números descrevem o
desenvolvimento, não a eficácia final.

Mesmo com zero erros observados na deduplicação, os limites superiores de
Wilson preservados no manifesto são aproximadamente 4,58% para FP e 5,20% para
FN. Portanto, não é válido escrever que o candidato garante erro zero ou já
cumpre o limite confirmatório de FN ≤ 2%.

Hashes congelados:

- bundle:
  `6aed1363ca932f04173d66f82e1d901bd983ed519f93df32a8c5cce7339b674a`;
- arquivo de manifesto:
  `2a70b6699819ddbbe82f8d5178d839642b5ca58194cc54ad0999a01d4d4e6afe`;
- script de treinamento:
  `a063c35bb05b8f8a32a2dd89bbb2341646446bbdaa895d3c1ab87c21dc576857`.

Depois do treino, as regras determinísticas de suficiência textual foram
ampliadas para reconhecer variantes naturais como “não está gelando” e “sem
refrigeração”, sem mudar TF-IDF, embedding, features, pesos ou limiares do
joblib. A mudança pode alterar a cobertura do sistema completo. Por isso, ela
não herda automaticamente o status congelado do bundle: precisa concluir a
regressão ponta a ponta no desenvolvimento e entrar no novo freeze do código
antes da abertura do V3.

Pode ser afirmado: “o bundle candidato local foi treinado, calibrado e congelado
sem usar o holdout”. A aptidão do pipeline completo ainda exige regressão de
desenvolvimento e freeze dos adaptadores/gates/workflows exatos. Ainda não pode
ser afirmado: “o modelo local foi cientificamente validado”, “superou o Gemini”
ou “atinge os mesmos índices no cotidiano do GLPI”.

### 9.3 Ablação interna do embedding

No mesmo split, seed e pipeline sintético de desenvolvimento, o híbrido Granite
obteve acurácia 0,95625 e macro-F1 0,95230 em classificação, contra 0,92500 e
0,92140 do TF-IDF isolado. Também reduziu Log Loss de 0,23497 para 0,18756,
Brier de 0,11800 para 0,08651 e aumentou a cobertura seletiva de 68,125% para
85%, mantendo risco pontual próximo (0,917% contra 0,735%).

Na deduplicação, ambos observaram 0 FP/0 FN e AP aproximadamente 1; o Log Loss
mudou de 0,019472 para 0,019316. Assim, a ablação apoia internamente o uso do
Granite na classificação, mas não demonstra ganho material de deduplicação nem
eficácia fora do corpus sintético de desenvolvimento. O artefato TF-IDF está em
`avaliacao/resultados/ablacao-tfidf-v1.1.0-20260715`.
