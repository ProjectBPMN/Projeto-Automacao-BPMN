# Resultado consolidado — estado em 17/08/2026

> [!WARNING]
> **Snapshot histórico, superado pela auditoria de 26/08/2026.** A seleção
> citada neste documento não sustenta ranking atual: derivados de poucas
> famílias-fonte não ficaram integralmente no mesmo grupo. Toda classificação
> permanece sintética e a deduplicação antiga é subdimensionada. Use
> `auditoria_critica_completa_2026-08-26.md` e
> `resposta_professor_2026-08-26.md` como estado canônico.

A versão anterior deste arquivo apresentava números da v1.1 como resultado
final. Essa interpretação foi invalidada porque a v1.1 falhou em 1.045 das
1.240 unidades e sua acurácia seletiva considerava apenas sobreviventes.

Use os documentos atuais:

- `estado_projeto_2026-08-17.md`: parecer auditado mais recente;
- `TEST_REPORT.md`: testes e comparação v1.1/v1.8;
- `estado_release_candidate_2026-07-16.md`: snapshot histórico de prontidão;
- `auditoria_amostral_v4.md`: desenho amostral;
- `plano_avaliacao_cientifica_v3.md`: protocolo e gates;
- `../avaliacao/resultados/local-only-desenvolvimento-v1.8.0-20260716/`:
  predições e resumo brutos.

Em 17/08/2026, a seleção supervisionada v1.3 terminou e foi recalculada no
mesmo corpus de desenvolvimento por um validador independente: 90
configurações, 50.780 predições fora da dobra, 450
dobras, 18 comparações pareadas por grupos, 100 comparações dos objetivos, duas
explicações XAI e três cenários de latência. O melhor candidato provisório de
classificação foi Granite + TF-IDF + SVM linear; o de deduplicação foi Granite
+ TF-IDF + regressão logística. Ambos ficaram `UNDERPOWERED` pelos limites de
confiança e não foram promovidos como vencedores científicos.

A materialização v1.9 respondeu 1.239/1.240 unidades. Em relação à v1.8, ganhou
6,61 pontos percentuais de cobertura semântica e 6,53 pontos de automação
direta, mas perdeu 0,08 ponto de disponibilidade e acrescentou 249,84 ms de
latência média pareada. A política de engenharia devolveu
`CANDIDATE_NOT_RECOMMENDED`; a v1.8 permanece vigente. A variante v1.9.1 foi
apenas piloto de 30 unidades e também não demonstrou ganho de latência.

Não existe, até 17/08/2026, evidência confirmatória que autorize afirmar que o
modelo local supera o Gemini em eficácia sobre chamados reais. A tabela CSV ao
lado permanece um snapshot histórico e só deve ser substituída por planilha
final quando holdout, comparação remota e calibração WF06 estiverem completos.
