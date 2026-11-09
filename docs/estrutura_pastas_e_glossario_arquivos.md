# Estrutura de pastas e fontes principais

**Revisão:** 01/09/2026

```text
projeto-ic/
├─ avaliacao/       protocolo, datasets, scripts, testes e resultados
├─ database/        schema/migrações auxiliares
├─ docs/            documentação corrente e histórica
├─ glpi/            compose, plugin de webhook e seed
├─ local_ai/        serviço, contratos, treinamento, modelos e testes
├─ n8n/             compose, histórico V1–V8 e workflows V9
├─ outputs/         saídas operacionais auxiliares
├─ scripts/         verificações transversais
├─ README.md        estado executivo corrente
└─ requirements.txt dependências Python congeladas
```

O [inventário arquivo por arquivo](inventario_arquivos_versionados_2026-09-01.md)
complementa este mapa com tamanho, SHA-256, prioridade e destinação mecânica de
cada arquivo rastreado ou não ignorado no snapshot.

## Avaliação

- `avaliacao/config/selecao_modelos_supervisionados_v2.json`: protocolo V2.1
  integral, somente desenvolvimento; atualmente inviável para deduplicação.
- `avaliacao/config/selecao_classificacao_supervisionada_v2_1.json`: escopo
  classificatório reproduzível e viável.
- `avaliacao/datasets/desenvolvimento_local_v2.jsonl`: corpus sintético V2.1
  agrupado pela dependência-fonte.
- `avaliacao/scripts/gerar_corpus_desenvolvimento_local_v2.py`: gerador
  determinístico do corpus.
- `avaliacao/scripts/selecionar_modelos_supervisionados.py`: seleção aninhada,
  calibração, bootstrap, SHAP e benchmark.
- `avaliacao/scripts/validar_resultados_selecao.py`: recálculo independente.
- `avaliacao/scripts/validar_viabilidade_protocolo_selecao.py`: preflight de
  grupos/divisões antes de embeddings e treino.
- `avaliacao/scripts/validar_pipeline_fila_e2e.py`: E2E sintético isolado,
  mutante somente com confirmação explícita.
- `avaliacao/resultados/selecao-supervisionada-v2/`: rodada histórica
  invalidada; não reutilizar.
- `avaliacao/resultados/selecao-supervisionada-v2.1-20260826/`: classificação
  validada apenas no escopo parcial; deduplicação falhou e não possui ranking.
- `avaliacao/confirmatorio/`: gates confirmatórios e cálculo mínimo de
  exposições; bloqueado sem gabarito independente.
- `avaliacao/operacional/`: carga limitada, falhas isoladas, restore, menor
  privilégio, SLO e drift; não certifica produção.
- `avaliacao/piloto_sombra/`: implementação preservada, mas piloto humano fora
  do escopo por decisão de 01/09.

## n8n

- `n8n/history/`: dez snapshots sanitizados/inativos que cobrem V1–V8,
  manifesto, gerador, validador e testes.
- `n8n/workflows/Versão9/`: builders, seis JSONs canônicos, deploy, validação e
  testes da release atual.
- `n8n/credentials/`: exemplos locais sem segredos; credenciais reais ficam na
  instância/ambiente.
- `n8n/.env.example` e `.env.local.example`: contratos de configuração; `.env`
  reais são ignorados.

## IA local

- `local_ai/app.py`: API estruturada;
- `local_ai/training/`: treinamento/calibração dos cabeçalhos supervisionados;
- `local_ai/artifacts/` e resultados operacionais: manifests/bundles
  congelados, sem implicar aprovação científica;
- `local_ai/models/`: pesos locais, ignorados salvo manifesto;
- `local_ai/runtime/`: binários/caches regeneráveis, ignorados;
- `local_ai/tests/`: contratos herméticos.

## GLPI e banco

- `glpi/docker-compose.yml`: GLPI/MariaDB;
- `glpi/plugins/n8nwebhook/`: ingresso de chamados no WF06;
- `glpi/seed/`: dados locais de demonstração;
- `database/init_v9.sql`: schema idempotente de fila, decisões, tentativas,
  eventos e views.

## Documentação canônica

1. `docs/SOURCE_OF_TRUTH.md`;
2. `avaliacao/metodologia_avaliacao_v2_1.md`;
3. `docs/auditoria_critica_completa_2026-09-01.md`;
4. `docs/auditoria_critica_completa_2026-08-26.md` (snapshot histórico);
5. `docs/resposta_professor_2026-08-26.md`;
6. `docs/tutorial_reproducao_e_implantacao.md`;
7. `docs/TEST_REPORT.md`;
8. `README.md`.

Documentos com banner de snapshot/invalidado não são estado corrente.

## O que não deve ser versionado

- `.env`, `.env.local`, tokens, export de credenciais;
- dumps de banco e backups integrais;
- executáveis/DLLs e pesos baixados;
- caches de embedding e resultados intermediários regeneráveis;
- PIDs, `__pycache__` e caches de testes.

Backups locais ignorados não são automaticamente descartáveis: exclusão física
exige política de retenção e verificação separada. O histórico público de
workflows deve ser feito pelo sanitizador de `n8n/history/`, não por cópia de
exports runtime.
