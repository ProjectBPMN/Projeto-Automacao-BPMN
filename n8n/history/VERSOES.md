# Histórico de Versões dos Workflows (V1 - V9)

Este documento descreve a evolução da arquitetura dos workflows do n8n para a triagem de chamados do GLPI.

| Versão | Data | Principais Mudanças / Descrição | Estrutura | Status | SHA-256 (JSON Sanitizado) |
|---|---|---|---|---|---|
| V1 | Anterior a Ago/2026 | Prova de conceito inicial. Teste básico de integração. | Monolito (14 nós) | Obsoleto / Histórico | `794180c23940558d9fcc5af388e21b6df6822a2e70e4af5dc89889b09b4f4079` |
| V2 | Anterior a Ago/2026 | Evolução da triagem inteligente com GLPI + IA. | Monolito (32 nós) | Obsoleto / Histórico | `ba901844a5d6e6733c37aa07447d460ed9d2b0f707909335156ce7e578fcbad6` |
| V3 | Anterior a Ago/2026 | Introdução de Webhook Runtime. | Monolito (49 nós) | Obsoleto / Histórico | `f7cd61d671747f6b33198acb08a2e20279c9e2b6ab3cbda4e9720ba969c5c96b` |
| V4 | Anterior a Ago/2026 | Refinamento do fluxo de triagem inteligente. | Monolito (52 nós) | Obsoleto / Histórico | `3399539214abbb88e56d1622940616c91a4fd28e1bb2908f9df8f2c3bb422e80` |
| V5 | Anterior a Ago/2026 | Simplificação e otimização antes da adoção de BD. | Monolito (39 nós) | Obsoleto / Histórico | `070a13f154542cd2bd96ede152af77b5caff42960a17e5865d4bc045875fe0ad` |
| V6 | Abr/2026 | Primeira versão com persistência no PostgreSQL. | Monolito (49 nós) | Obsoleto / Histórico | `c2100af1f59562f221c6c24b0d6e7762a4ee2407491ec73929855dcacbe05114` |
| V7 | Abr/2026 | Última versão monolítica preservada. Fluxo completo de dedup e aprovação fiscal. | Monolito (66 nós) | Obsoleto / Histórico | `5c09a280d9b796a3ec3285c2ee35c286c944adda9c77398a4d93c450938ecd66` |
| V8 | Mai-Jul/2026 | Separação de responsabilidades. Fluxo dividido em Orquestrador, Triagem e Fiscal. | Workflows Divididos (WF01, WF02, WF03) | Obsoleto / Histórico | WF01: `6c09ee5885d4d1f24383c6a0e384e82835d3162f1fd95c94101423c6e53d080b`<br>WF02: `36f47a651d84d042d3f562dd627226ae84ef60860c8740c8ee45559b3ce7c7a5`<br>WF03: `3e4b949e63d9e042e73db13bfc79063b73b8cdb04f7b85fb8da5391b7d43196f` |
| V9 | Ago/2026 | Arquitetura atual com fila de IA assíncrona, retry e métricas separadas, suportando múltiplos modelos. | Workflows divididos (6 publicados no ambiente local) | Candidata operacional local | Consulte os snapshots da release V9 |
