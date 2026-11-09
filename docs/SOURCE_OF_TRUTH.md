# Hierarquia das fontes de verdade

**Estado:** canônico em 14/09/2026
**Escopo:** triagem GLPI, workflows V9, modelo local e avaliação científica

Esta hierarquia impede que um texto, dashboard ou resultado antigo prevaleça
sobre a evidência que realmente sustenta uma afirmação. Um arquivo com hash
continua podendo estar metodologicamente errado; integridade criptográfica
prova identidade, não validade científica.

## Regra por tipo de afirmação

| Afirmação | Fonte primária | Verificação obrigatória |
|---|---|---|
| O que o código faz | builders Python e testes | JSON regenerado, validação estática e teste de contrato |
| O que está publicado | API/estado live do n8n | paridade canônica versus implantada e workflow ativo |
| O que aconteceu em uma execução | linhas brutas de banco/log e artefato E2E | `run_id`, janela temporal, hashes, terminal e cleanup |
| Qual modelo está carregado | `/health`, manifesto e bundle | versão, revisão/tree hash do embedding e ausência de fallback |
| Como o estudo deveria ser conduzido | protocolo/config pré-congelado | hash do protocolo anterior à abertura do conjunto final |
| Qual foi o desempenho | predições individuais e gabarito | dataset/hash, independência de grupos e recálculo independente |
| Como interpretar | relatório/documentação | deve concordar com todas as fontes acima e declarar limitações |

## Ordem de autoridade

1. **Evidência bruta identificável:** dataset, predição por unidade, eventos,
   decisões, tentativas e estado live observado, todos vinculados a versão,
   `run_id` e hash quando aplicável.
2. **Implementação executável:** builders, scripts, schemas e testes que geram
   ou recalculam a evidência.
3. **Protocolos congelados:** objetivos, splits, grupos, limiares, exclusões e
   plano estatístico definidos antes da avaliação correspondente.
4. **Manifests e validadores:** registram identidade, proveniência e checks. Um
   manifest não transforma um desenho inválido em desenho válido.
5. **Relatórios gerados:** agregações recalculáveis a partir das linhas brutas.
6. **Documentação narrativa:** README, guias, pareceres e apresentações.
7. **Material histórico/invalidado:** útil para rastreabilidade, proibido como
   evidência corrente sem revalidação explícita.

Em conflito, prevalece a fonte de maior autoridade pertinente ao tipo de
afirmação. Se a evidência bruta não puder ser reproduzida pelo hash/config
publicado, o resultado é invalidado, mesmo que um relatório diga `VALID`.

## Regras de não contradição

1. `scientifically_validated=false`, `scientific_ready=false` ou
   `confirmatory_claim_allowed=false` proíbe alegação de validação
   confirmatória.
2. Dados sintéticos ou de desenvolvimento nunca são chamados de desempenho
   institucional/real.
3. Acurácia sobre casos cobertos é **acurácia seletiva** e sempre vem com
   cobertura, abstenção e denominadores.
4. Zero erro observado não é risco zero; informar intervalo/limite superior e
   número de unidades independentes.
5. Falhas de transporte ficam no denominador de disponibilidade e não provam
   inferioridade semântica do provedor.
6. Gates determinísticos, regras, predições probabilísticas e fallback são
   estratificados; não podem ser agregados como se viessem do mesmo modelo.
7. Seleção de hiperparâmetro, calibração e limiar ocorre sem acesso ao holdout
   final e dentro do agrupamento correto.
8. Paráfrases/reamostragens com a mesma fonte ficam sempre no mesmo grupo.
9. SHAP descreve atribuição no modelo analisado; não prova acerto, causalidade
   ou validade externa.
10. Teste técnico, paridade e E2E não autorizam a expressão “100% correto”.

## Estado oficial atual

- modelo operacional: `local-hybrid-v1.8.0` / bundle v1.8.0;
- finalidade: candidato de engenharia, não resultado confirmatório;
- seleção anterior em `avaliacao/resultados/selecao-supervisionada-v2/`:
  `INVALIDATED_POST_AUDIT`;
- protocolo corrente: V2.1, desenvolvimento apenas, agrupado por
  `source_dependency_group_sha256`; classificação concluída e validada no
  escopo parcial, deduplicação bloqueada por inviabilidade com 12 grupos;
- candidato classificatório da rodada: E5 + híbrido + SVM linear,
  `UNDERPOWERED`; não promovido ao runtime;
- workflow operacional: V9;
- histórico: V1–V8 sanitizado/inativo em `n8n/history/`, V9 em
  `n8n/workflows/Versão9/`;
- evidência E2E: sintética, isolada e não confirmatória;
- última recuperação E2E preservada:
  `avaliacao/resultados/operacional/recuperacao-e2e-20260909.json`, com
  `passed=true`, chamado sintético ausente, controlador/perfil restaurados e
  nenhuma linha residual na DLQ da própria tentativa. Isso é evidência
  histórica, não confirmação do estado vivo atual;
- estado operacional final observado em 14/09 na captura SQL atômica
  `avaliacao/resultados/operacional/estado-runtime-fechamento-homolog-20260914.json`:
  `ERRO_IA=0`, fila ativa `=0` e DLQ aberta `=0`, sem exclusão de histórico.
  Esta contagem não confirma correção semântica;
- as três janelas técnicas intradiárias locais/sintéticas corrigidas foram
  concluídas em 11/09 (240 observações cada e reconciliação completa), mas com
  zero decisões únicas em cada uma. Drift é `INSUFFICIENT_DATA`; métricas de
  latência, fila e erro sem decisões também permanecem insuficientes. A janela
  1 falhou o SLO técnico proposto pela idade de restore de backup (206,05 h,
  acima de 168 h); janelas 2 e 3 são `INSUFFICIENT_DATA`. Portanto
  `production_slo_estimated=false` e nenhum SLO institucional foi demonstrado;
- confirmação de 14/09: 53 testes operacionais e validação estática V9 aprovados;
  daemon exato preservado. A série posterior contém lacuna de 44h33m12s,
  fora das primeiras três janelas. Detalhes em
  `docs/homologacao_v9_confirmacao_2026-09-14.md`;
- última homologação isolada preservada em 09/09, com nove serviços e sem
  chamados reais copiados; é evidência histórica, não estado vivo atual;
- navegador: a evidência preservada de 09/09 registra seis workflows V9 e
  acesso autenticado ao GLPI. A tentativa de 10/09 recebeu
  `ERR_CONNECTION_REFUSED` em n8n e GLPI; validação visual atual está pendente;
- segredo: árvore candidata `PASS` com zero achado; histórico alcançável `FAIL`
  com 15 achados que exigem rotação;
- conclusão científica: avaliação apenas com rótulos proxy/sintéticos; não há
  gabarito humano institucional independente, avaliação válida de equidade nem
  holdout confirmatório. O candidato é `UNDERPOWERED` e não há base para
  afirmar superioridade ou prontidão produtiva.

## Documentos canônicos

- `README.md`
- `docs/auditoria_continuacao_2026-09-10.md`
- `docs/auditoria_critica_completa_2026-09-03.md`
- `docs/auditoria_critica_completa_2026-09-02.md`
- `docs/auditoria_critica_completa_2026-09-01.md`
- `docs/auditoria_critica_completa_2026-08-26.md`
- `docs/resposta_professor_2026-08-26.md`
- `docs/SOURCE_OF_TRUTH.md`
- `avaliacao/metodologia_avaliacao_v2_1.md`
- `avaliacao/config/selecao_modelos_supervisionados_v2.json`
- `avaliacao/resultados/selecao-supervisionada-v2/INVALIDADO.md`
- `n8n/history/manifest.json`
- `n8n/workflows/Versão9/TEST_REPORT.md`
- `docs/tutorial_reproducao_e_implantacao.md`
- `docs/TEST_REPORT.md`

`avaliacao/metodologia_avaliacao.md` e
`docs/plano_avaliacao_cientifica_v3.md` são snapshots históricos.

Qualquer documento anterior deve ser lido como snapshot histórico quando
divergir desta lista ou dos artefatos estruturados atuais.
