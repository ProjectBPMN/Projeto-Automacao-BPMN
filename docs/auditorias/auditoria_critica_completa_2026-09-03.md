# Auditoria crítica completa — 3 de setembro de 2026

> Retificação em 09/09/2026: o coletor desta rodada reutilizava métricas de
> 30 dias e snapshots históricos. As conclusões temporais de SLO/drift abaixo
> foram invalidadas e substituídas pela auditoria de 09/09. A evidência original
> permanece preservada; este documento não descreve o estado operacional atual.

## Parecer executivo

O projeto está funcional como protótipo local e ambiente sintético isolado. A
rodada final exercitou a cadeia WF06→WF02→WF03, restaurou o estado de teste e
deixou `ERRO_IA=0`, fila ativa `=0` e DLQ aberta `=0`. Isso é evidência técnica,
não garantia de correção universal, prontidão produtiva ou confirmação
semântica.

Todas as avaliações de qualidade usam rótulos-proxy. Pela decisão explícita de
não usar chamados reais, revisão humana ou revisão em pares, não existe gabarito
independente elegível e nenhum resultado pode ser chamado de confirmatório.

## Evidência atual

| Área | Resultado de 03/09 | Limite obrigatório |
|---|---|---|
| E2E sintético | `passed=true`, sem fallback/interferência, cleanup completo | um cenário exercitado não prova todas as entradas |
| Fila e DLQ | 0 `ERRO_IA`, 0 fila ativa, 0 DLQ aberta | fotografia operacional; histórico não apagado |
| n8n no navegador | seis workflows V9 `Published`; execuções WF06 visíveis em `Success` | tela não prova semântica |
| GLPI no navegador | login local aprovado e listagem de chamados visível | leitura somente; títulos históricos preservados |
| Homologação | nove serviços, 40 tabelas, zero tickets e role runtime mínima | infraestrutura sintética, sem dados reais |
| Carga C1 | 40/40 HTTP 200; 19,73 req/s; p95 35,30 ms | loopback e 40 requisições |
| Carga C4 | 17/40 HTTP 200; 23/40 HTTP 429; p95 1.736,30 ms | saturação real do cenário; não ocultar |
| Monitor | contagens de coletas preservadas | interpretação temporal invalidada; métricas repetidas de 30 dias |
| Drift | diagnóstico histórico calculado repetidamente | não mede drift entre as janelas temporais |
| Segredos | árvore candidata PASS/0; histórico FAIL/15 | rotacionar credenciais históricas |
| Histórico | dez snapshots cobrem V1–V8 e passam integridade | versões antigas não são workflows ativos |
| Regressão | 363 testes e 117 subtestes aprovados em 80,15 s | não substitui validação externa |

## Crítica científica

A classificação V2.1 compara, no mesmo protocolo agrupado, TF-IDF, embeddings e
híbridos; Granite 97M, multilingual-e5-small e MiniLM-L12; e regressão
logística, árvore, SVM linear, MLP e XGBoost. Há 1.114 registros proxy, 111
grupos, 35 configurações, 175 dobras e 38.990 predições OOF. O validador
independente aceita apenas o escopo parcial de classificação.

O primeiro colocado pela regra hierárquica foi híbrido/E5/SVM, com Macro-F1
proxy 0,7987, acurácia 0,8312, cobertura 0,6086 e risco seletivo 0,0693. O maior
Macro-F1 bruto foi MLP/E5, 0,8036, mas com cobertura automática zero. Logo não é
correto alegar que o MLP ou qualquer embedding “venceu” apenas pela média.

A deduplicação continua bloqueada com 12 famílias independentes. Com zero
eventos críticos, 149 exposições independentes são o mínimo matemático para um
limite unilateral estritamente inferior a 2%; duas direções disjuntas sugerem
298 famílias antes de perdas e efeito de desenho. SHAP descreve atribuições do
modelo, mas não valida acerto, causalidade ou justiça. Não existe comparação
Gemini atual, pareada e válida; falhas históricas de cota/transporte não provam
inferioridade semântica.

## Pontos fortes

- builders determinísticos, paridade publicada e hashes;
- DDL fora do WF05 e PostgreSQL runtime de menor privilégio;
- sandbox/runners externos, segredos fora de Code nodes e portas em loopback;
- fila com lease, retry, DLQ, reconciliação e cleanup isolado;
- E2E, restore, carga, falhas, homologação e monitoramento com artefatos;
- ablações, agrupamento por fonte, calibração, risco-cobertura e SHAP;
- histórico V1–V8 preservado e sanitizado na ponta atual.

## Pontos fracos e pendências reais

- as métricas temporais legadas são insuficientes; a política permanece não aprovada;
- o `STOP` de drift é diagnóstico somente leitura, sem bloqueio automático do runtime;
- concorrência 4 satura o serviço local; pacing maior não é suportado;
- deduplicação é subdimensionada e classificação permanece `UNDERPOWERED`;
- sem gabarito independente, a correção semântica não pode ser confirmada;
- 15 achados permanecem no histórico Git e exigem rotação de credenciais;
- TLS, retenção/LGPD, responsáveis, alertas externos e aceite institucional
  continuam fora da evidência atual.

## Conclusão

O projeto pode ser apresentado como protótipo técnico reproduzível, com
classificação proxy comparativa e mecanismos operacionais verificados. Não deve
ser apresentado como “100% correto”, “melhor modelo comprovado”, SLO aprovado ou
sistema pronto para produção. Os estados corretos continuam
`production_ready=false`, `scientific_ready=false` e
`semantic_correctness_confirmed=false`.
