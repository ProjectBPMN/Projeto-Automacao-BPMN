# Auditoria de Estado do Projeto (18/08/2026)

> [!WARNING]
> **Snapshot histórico, superado pela auditoria de 26/08/2026.** A seleção
> citada neste documento não sustenta ranking atual: derivados de poucas
> famílias-fonte não ficaram integralmente no mesmo grupo. Toda classificação
> permanece sintética e a deduplicação antiga é subdimensionada. Use
> `auditoria_critica_completa_2026-08-26.md` e
> `resposta_professor_2026-08-26.md` como estado canônico.

Este documento reflete o estado atual da infraestrutura, workflows, banco de dados e experimentos científicos do projeto de automação de tickets GLPI.

## 1. Estado da Infraestrutura
- **Docker Containers**:
  - `n8n`: Up 25min (UI acessível em http://localhost:5678 - HTTP 200)
  - `glpi`: Up 5d (Acessível em http://localhost:9080 - HTTP 200)
  - `glpi-db`: Up 5d, healthy
  - `glpi-dedup-db`: Up 5d, healthy
  - `mailpit`: Up 5d, healthy

## 2. Workflows Ativos (V9)
A arquitetura V9 é composta por 6 workflows divididos e ativos:

| ID | Nome | Status |
|---|---|---|
| `BCrENoTzdW20owz4` | V9 - WF01 Sincronizador | Ativo |
| `nmNEsgC8kXmCVOsX` | V9 - WF02 Triagem | Ativo |
| `reVggSpJiaPhnfIo` | V9 - WF03 Classificação | Ativo |
| `ZpQ0H9uV9Fiscal04` | V9 - WF04 Decisão Fiscal | Ativo |
| `ZpQ0H9uV9Metric05` | V9 - WF05 Métricas | Ativo |
| `ZpQ0H9uV9Fila06` | V9 - WF06 Fila IA | Ativo |

## 3. Estado do Banco de Dados
- **Tabelas PostgreSQL**: 15 tabelas.
- **Registros de Processamento**:
  - 210 chamados processados.
  - 209 registros de tentativas de modelos de IA (`ia_tentativas_modelo`).
  - 315 decisões de IA registradas (`ia_decisoes`).
- **Gateway Multi-Modelo (Status: Parcialmente Funcional)**:
  - O sistema implementou fallback, mas enfrenta alta taxa de falhas de transporte/rate limit.
  - **LOCAL (`local-hybrid-v1.8.0`)**: 38 tentativas VÁLIDAS.
  - **PRIMARY (`gemini-3.5-flash`)**: 7 VÁLIDAS, 81 TRANSPORT_ERROR, 2 RATE_LIMIT.
  - **SECONDARY (`gemini-2.5-flash`)**: 22 VÁLIDAS, 25 TRANSPORT_ERROR, 2 RATE_LIMIT.
  - **TERTIARY (`deepseek-v4-flash`)**: 25 TRANSPORT_ERROR (todas falharam).
  - **FREE_CONTINGENCY (`gemini-3.1-flash-lite`)**: 7 VÁLIDAS.
- **Taxa de Erro**: 184 de 315 decisões resultaram em `ERRO_IA` (58%). A maioria é devido a problemas de infraestrutura (transporte/rate limit), não falhas de classificação da IA.

## 4. Estado dos Experimentos Científicos
- **Seleção Supervisionada (v1.3)**: CONCLUÍDO (90 configurações, 50.780 predições, VÁLIDO).
- **Candidatos (Modelos Atuais)**: Todos "UNDERPOWERED" ou "FAIL". Nenhum passou nos "confidence gates".
- **Vencedor (Provisório)**: `hybrid__granite97m__linear_svm` (Macro-F1 = 0.80).
- **XAI/SHAP**: CONCLUÍDO.
- **Confirmatório Holdout**: BLOQUEADO (`confirmatory_eligible=false`).
- **Rótulos Humanos (Human labels)**: PENDENTE.

## 5. Lacunas Identificadas (Gaps)
- **[ALTA] Alta Taxa de Falhas de Transporte da API (Gateway)**: 58% das decisões são erros devido a falha de transporte ou rate limit, prejudicando o gateway multimodelo (principalmente Gemini 3.5/2.5 Flash e DeepSeek). A contingência local e gratuita suportou a maioria das requisições válidas.
- **[ALTA] Bloqueio no Pipeline Científico (Holdout Blocked)**: Os modelos avaliados não alcançaram a confiança mínima, bloqueando a avaliação de holdout confirmatório.
- **[MÉDIA] Dependência de Rótulos Humanos Pendentes**: Os rótulos humanos necessários para a avaliação final estão pendentes, o que pode atrasar a aprovação definitiva de um modelo.
