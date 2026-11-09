# Plano pré-implantação: ciência, TLS e atuação do STOP

## Escopo honesto da evidência

O projeto é uma proposta pré-implantação e não dispõe de chamados reais do campus. Portanto, a evidência atual e a próxima bateria são sintéticas/proxy. Elas podem demonstrar engenharia reprodutível, comparação justa entre modelos, robustez a famílias não vistas e limites de erro sob cenários controlados. Não podem confirmar eficácia institucional, generalização para a distribuição real, justiça, `scientific_ready` ou `production_ready`.

## Banco sintético fortalecido

A unidade independente será a família semântica, e não a paráfrase. Trocar local, saudação, ortografia, data ou solicitante não cria uma nova unidade. O plano pré-registrado exige 100 famílias por classe na classificação; na deduplicação, 186 positivas, 97 negativas difíceis completas e 75 negativas críticas. Desenvolvimento e desafio bloqueado terão hashes de dependência sem sobreposição.

As famílias cobrirão serviço, ativo, sintoma, local, temporalidade, estado anterior, solicitante, completude, ruído e ataques de prompt. Derivações superficiais serão usadas apenas para robustez secundária. O desafio bloqueado não poderá participar de escolha de representação, hiperparâmetro, limiar ou modelo.

## Comparação de modelos e estatística

Regressão logística, árvore de decisão, SVM linear, MLP e XGBoost serão comparados nos mesmos grupos, atributos e orçamento. A seleção usa validação cruzada aninhada e agrupada. Serão relatados Macro-F1, risco seletivo e cobertura para classificação; falso-negativo, falso-positivo, precisão e cobertura para deduplicação. Intervalos de 95% serão calculados por bootstrap de grupos e diferenças entre modelos pelo mesmo reamostramento pareado; comparações confirmatórias futuras deverão controlar multiplicidade por Holm.

O modelo vencedor precisa satisfazer simultaneamente os gates pré-fixados, usando limites de confiança, e não apenas possuir a maior média. Ausência de vencedor deve ser publicada como resultado válido. SHAP será usado com teste de aditividade, importância por famílias de atributos, explicações por classe, casos de erro/abstenção e estabilidade entre folds. SHAP explica o comportamento do modelo, não prova causalidade ou acerto.

## TLS preparado, sem alterar a homologação em curso

O perfil em `deploy/tls` adiciona um gateway TLS separado para n8n e GLPI, com TLS 1.2/1.3, HSTS, certificados externos ao repositório, cabeçalhos encaminhados e segredo do webhook fornecido por ambiente. A porta padrão permanece restrita ao loopback. Ele não foi iniciado durante as três janelas para não alterar o runtime observado.

Antes de qualquer exposição institucional ainda será obrigatório: certificado emitido para nomes reais, DNS, rotação dos tokens que já apareceram no histórico Git, cookies seguros do n8n, remoção dos acessos HTTP diretos e teste externo de configuração TLS. O perfil preparado não constitui aprovação de produção.

## STOP: contrato e implementação em duas fases

O contrato em `avaliacao/config/stop_operacional_v1.json` determina modo fail-closed para evidência ausente ou inválida. Drift `STOP`, DLQ aberta, erro automático crítico, cobertura incompleta ou divergência de integridade devem bloquear novas decisões automáticas, encaminhar para triagem manual e manter coleta/auditoria. Retreinamento automático é proibido; a retomada exige aprovação humana.

Durante a coleta atual o STOP permanece diagnóstico, porque conectar o atuador exigiria alterar workflows medidos por hash. Após a terceira janela, a alteração deve ser feita nos builders V9, regenerada e publicada, seguida por teste E2E específico: induzir STOP, provar que nenhuma decisão automática nova ocorre, provar encaminhamento manual, retirar a condição somente com autorização e demonstrar retomada. Até esse teste passar, `automatic_stop_enforced` deve continuar falso.

## Validação institucional futura

Se a gestão decidir avançar, a etapa confirmatória exigirá aprovação de governança/ética, amostra real desidentificada, dupla anotação independente com adjudicação, holdout temporal ou por unidade, auditoria por subgrupos e piloto prospectivo silencioso. Só então será possível estimar eficácia institucional e discutir implantação real.
