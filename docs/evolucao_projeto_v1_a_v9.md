# Evolução do projeto até a V9

> [!WARNING]
> **Snapshot histórico, superado pela auditoria de 26/08/2026.** A seleção
> citada neste documento não sustenta ranking atual: derivados de poucas
> famílias-fonte não ficaram integralmente no mesmo grupo. Toda classificação
> permanece sintética e a deduplicação antiga é subdimensionada. Use
> `auditoria_critica_completa_2026-08-26.md` e
> `resposta_professor_2026-08-26.md` como estado canônico.

## Nota sobre a reconstrução histórica

O repositório preserva a V9 como única release operacional. A evolução anterior
foi reconstruída em `n8n/history`: dez workflows inativos e sanitizados cobrem
V1–V8, acompanhados por manifesto com hashes das fontes privadas, objetos
selecionados e cópias públicas. A V6 foi recuperada de um bundle agregado; a V7
canônica é o snapshot mais recente auditado, com 66 nós; e a V8 possui três
workflows. Os exports brutos permanecem privados porque contêm referências e
valores sensíveis. O histórico prova proveniência e evolução, não correção em
produção nem compatibilidade retroativa. Datas ou resultados ausentes não são
inferidos.

## V1 — automação linear

A primeira ideia conectava GLPI e n8n para receber chamados, comparar textos e
encaminhar manutenção. A IA generativa concentrava a decisão. Ainda não havia
separação clara entre ingestão, duplicidade, classificação, confirmação e
avaliação científica.

## V2 — separação de responsabilidades

O processamento foi dividido em sincronização, deduplicação, classificação e
decisão fiscal. A interface humana permaneceu dentro do GLPI, evitando obrigar
o fiscal a abrir o n8n.

## V3 — memória de chamados

O WF01 passou a manter no PostgreSQL uma janela de chamados recentes e os
estados relevantes. Isso permitiu comparar novos chamados com histórico e
reduziu dependência de consultas completas repetidas ao GLPI.

## V4 — confirmação fiscal assíncrona

Chamados marcados como possíveis duplicados passaram a receber dois links:
confirmar ou rejeitar. O fluxo deixou de bloquear outros tickets enquanto
aguardava a decisão humana. Uma rejeição limpa o marcador e devolve o chamado à
classificação.

## V5 — observabilidade e avaliação

O projeto passou a registrar predição, probabilidade, modelo, prompt, latência e
eventos de workflow. O WF05 ganhou papel analítico e apoio à avaliação humana,
sem se tornar o motor de decisão.

## V6 — desenho científico

Foram definidos cenários de duplicidade e controle, variações naturalísticas,
matriz de confusão, risco-cobertura e custos assimétricos. A distinção entre
diagnóstico operacional, desenvolvimento sintético e resultado confirmatório
foi formalizada. O conjunto primary33 representa 990 realizações e 1.410
tickets, não 990 observações independentes.

## V7 — gateway e auditoria de provedores

O acesso aos modelos foi encapsulado em um gateway. Toda tentativa passou a
registrar provedor, papel, latência, erro e fallback. Em benchmark, o papel é
fixado e o fallback é proibido, impedindo que outro modelo substitua
silenciosamente o avaliado.

## V8 — modelo local híbrido

A instabilidade das APIs motivou uma alternativa local: TF-IDF, embedding
Granite 97M e regressão logística calibrada. O Granite 350M ficou restrito à
extração opcional. As versões do bundle foram avaliadas no desenvolvimento;
candidatos com regressão foram preservados como diagnósticos e não promovidos.

O arranjo não foi escolhido por alegada superioridade universal. TF-IDF de
palavras/caracteres preserva vocabulário técnico e ruído ortográfico; o
embedding de 384 dimensões acrescenta semântica entre paráfrases; e a regressão
calibrada permite limiares assimétricos, abstenção e inferência viável no
i3/8 GB. A fundamentação, as alternativas e os limites estão em
`justificativa_modelagem_local.md`.

## V9 — fila, segurança e release candidate

A arquitetura atual contém seis workflows:

- WF01 sincroniza e conserva a memória;
- WF02 recupera candidatos e decide duplicidade;
- WF03 classifica e encaminha;
- WF04 valida e executa a decisão fiscal;
- WF05 mede, alerta e apoia avaliação;
- WF06 recebe, enfileira, reserva e controla a vazão.

A v1.8 do modelo local adicionou margem mínima entre referências de
deduplicação e concluiu 1.240/1.240 casos de desenvolvimento sem falha. A
integração de 16/07 percorreu GLPI, WF06, WF02/WF03, PostgreSQL e WF04. Essa
execução pertence a uma revisão anterior dos workflows e não valida por
herança os JSONs atuais. Na revisão auditada em 12/08, existem 913 verificações
estáticas aprovadas, nove testes de contrato e preflight real sem mutação; o
E2E mutante integral da revisão exata e a calibração isolada do WF06 continuam
pendentes. A cadeia ativa foi simplificada para modelo local e um único
secundário Gemini.

Os links humanos passaram a usar confirmação em duas etapas: a abertura por
`GET` apenas apresenta uma página, e a mutação exige `POST`. Os serviços Docker
ficaram vinculados a `127.0.0.1`, os segredos passaram a ser obrigatórios via
ambiente e o projeto ganhou política de segurança, licença e citação.

O avanço mais importante não é apenas a troca de modelo: a V9 trata incerteza
como abstenção, preserva confirmação humana, registra proveniência antes da ação
e impede que resultados sintéticos sejam apresentados como evidência externa.

Em 17/08 terminou a seleção comparativa v1.3, com três embeddings,
representações isoladas e híbridas e cinco classificadores, totalizando 90
configurações para classificação e deduplicação. O validador independente
recalculou e aceitou a matriz. Granite híbrido + SVM linear e Granite híbrido +
regressão logística foram os candidatos provisórios, mas ambos ficaram
`UNDERPOWERED`. Até o holdout independente, a v1.8 continua sendo uma referência
operacional, não uma vencedora científica.
