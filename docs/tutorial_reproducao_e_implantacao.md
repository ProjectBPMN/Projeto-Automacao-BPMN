# Reprodução, validação e implantação segura

**Revisão:** 01/09/2026
**Estado:** V9 operacional; eficácia confirmatória bloqueada sem gabarito independente

Este guia separa quatro atividades que não devem ser confundidas:

1. subir a infraestrutura;
2. validar código sem mutar serviços;
3. provar tecnicamente um caminho E2E sintético;
4. executar pesquisa de desempenho, que é mais lenta e não produz evidência
   institucional por usar desenvolvimento sintético.

Nenhum comando abaixo justifica dizer que o sistema está “100% correto”.

## 1. Requisitos

- Windows/PowerShell, Python 3.11 ou 3.12 e Git;
- Docker Desktop com Compose;
- 8 GB de RAM no mínimo; 16 GB é mais confortável para a seleção comparativa;
- modelos locais presentes nos caminhos congelados do config;
- arquivos `.env` locais derivados dos `.env.example`, nunca versionados.

Em uma máquina de 8 GB, suspenda temporariamente GLPI, n8n e a API de IA antes
da seleção longa para evitar paginação/encerramento por memória. Registre a
parada e, ao terminar, religue os serviços e repita health, flags e smoke live.

Instale as dependências em ambiente virtual:

```powershell
python -m venv .venv
./.venv/Scripts/Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -r local_ai/requirements-hybrid.txt
```

Copie os exemplos de ambiente e preencha os segredos fora do Git. Não use
credenciais de demonstração em produção e não cole tokens em documentação.

## 2. Infraestrutura local

```powershell
docker compose -f glpi/docker-compose.yml up -d
docker compose -f n8n/docker-compose.yml up -d
docker ps
```

Serviços locais esperados:

- GLPI: `http://localhost:9080`;
- n8n: `http://localhost:5678`;
- Mailpit: `http://localhost:18025`;
- serviço de IA: `http://127.0.0.1:8090`.

Autentique-se com contas locais configuradas pelo responsável. Senhas não são
parte deste guia.

## 3. Serviço local operacional congelado

O runtime atual deve apontar para:

```text
avaliacao/resultados/treino-local-pytorch-fp32-v1.8.0-20260716/local_hybrid_manifest.json
```

Em máquina de 8 GB, a configuração conservadora observada é:

```powershell
./local_ai/scripts/start-local-ai.ps1 -CpuThreads 2 -MaxEmbedBatch 1
```

No `/health`, verifique pelo menos:

- `alive=true` e `decision_ready=true`;
- bundle `local-hybrid-bundle-v1.8.0`;
- backend `granite_embedding_pytorch_fp32`, dimensão 384;
- revisão/tree hash iguais ao manifesto;
- nenhum fallback de embedding;
- `scientific_ready=false` enquanto o holdout não for concluído.

## 4. Build e validação V9

Primeiro valide localmente:

```powershell
python n8n/workflows/Versão9/validate_v9_static.py
python -m pytest -q n8n/workflows/Versão9/test_v9_hard.py
```

Publicar altera a instância n8n. Faça isso somente no ambiente explicitamente
em escopo:

```powershell
python n8n/workflows/Versão9/deploy.py
```

O deploy deve confirmar seis workflows ativos e paridade da lógica canônica.
Depois, rode o preflight live indicado pelo script de runtime do V9; não use os
modos mutantes fora de um caso sintético controlado.

## 5. Testes herméticos

O conjunto rotineiro não acessa serviços reais nem cria chamados:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'

python -m pytest -q -p no:cacheprovider `
  local_ai/tests `
  avaliacao/tests `
  --ignore=avaliacao/tests/test_runtime_integration_live.py `
  n8n/workflows/Versão9/test_v9_hard.py `
  n8n/history/tests

python n8n/workflows/Versão9/validate_v9_static.py
python n8n/history/validate_history.py --check-sources
python avaliacao/scripts/validar_consistencia_cientifica_docs.py
git diff --check
git diff --cached --check
```

O validador documental é apenas um gate mínimo por padrões; ele não substitui
revisão científica de todos os relatórios.

## 6. Smokes contra serviços reais

Esses testes fazem leitura de serviços e enviam um POST deliberadamente
inválido para comprovar rejeição sem persistência. Exigem opt-in:

```powershell
$env:RUN_LIVE_INTEGRATION_TESTS = '1'
python -m pytest -q -p no:cacheprovider `
  avaliacao/tests/test_runtime_integration_live.py
Remove-Item Env:RUN_LIVE_INTEGRATION_TESTS
```

O teste verifica health da IA, `SELECT 1` no PostgreSQL e HTTP 401 para chave
inválida, comparando a ausência do ticket-sentinela antes/depois.

## 7. E2E sintético WF06 → WF02 → WF03

O modo padrão é preflight somente leitura:

```powershell
python avaliacao/scripts/validar_pipeline_fila_e2e.py `
  --model-manifest avaliacao/resultados/treino-local-pytorch-fp32-v1.8.0-20260716/local_hybrid_manifest.json
```

A execução mutante cria um chamado sintético isolado, restringe o WF06 ao
`run_id`, acompanha o terminal e desfaz os dados. Não rode junto de calibração,
piloto ou outra experiência:

```powershell
python avaliacao/scripts/validar_pipeline_fila_e2e.py `
  --executar `
  --confirmacao EXECUTAR_E2E_SINTETICO_WF06_LOCAL_V18 `
  --model-manifest avaliacao/resultados/treino-local-pytorch-fp32-v1.8.0-20260716/local_hybrid_manifest.json `
  --output avaliacao/resultados/e2e-pipeline-local-v1-AAAA-MM-DD.json
```

Aceite a rodada somente se o artefato mostrar:

- `passed=true` e `cleanup.complete=true`;
- modelo/revisão/hash esperados e ausência de fallback;
- paridade dos workflows publicados;
- terminal seguro, contagens esperadas e DLQ zero;
- nenhuma interferência estranha;
- controlador e perfil operacional restaurados.

Essa é evidência técnica sintética, não estimativa de acurácia.

## 8. Histórico V1–V8

```powershell
python n8n/history/build_history.py --check
python n8n/history/validate_history.py --check-sources
python -m pytest -q n8n/history/tests
```

Os dez JSONs são sanitizados, inativos e históricos. Não reconecte credenciais
ou ative versões antigas sem revisão completa.

## 9. Corpus de desenvolvimento V2.1

Regere e confirme o SHA congelado:

```powershell
python avaliacao/scripts/gerar_corpus_desenvolvimento_local_v2.py
python -m pytest -q avaliacao/tests/test_selecao_modelos_supervisionados.py
```

O config corrente exige SHA-256
`305e84164d663a19a2e224b2dc8bf08e8d3173bf50bc15c7675f9de553d2de9a`
e grupos `source_dependency_group_sha256`. Se o hash divergir, pare; não ajuste
o config depois de observar resultados.

## 10. Seleção comparativa reproduzível 2.1

Nunca reutilize `avaliacao/resultados/selecao-supervisionada-v2/`: ele é um
resultado histórico invalidado. Antes de treinar, execute o preflight:

```powershell
python avaliacao/scripts/validar_viabilidade_protocolo_selecao.py `
  --config avaliacao/config/selecao_modelos_supervisionados_v2.json
```

No corpus atual, o resultado esperado é `INFEASIBLE` para deduplicação: seis
grupos por classe não comportam cinco grupos de ajuste mais quatro de
calibração dentro do treino externo. Não reduza esses mínimos após observar a
falha. Para reproduzir somente a classificação viável, use um diretório novo e
o escopo congelado específico:

```powershell
powershell -ExecutionPolicy Bypass `
  -File avaliacao/scripts/executar_selecao_modelos.ps1 `
  -Config avaliacao/config/selecao_classificacao_supervisionada_v2_1.json `
  -Saida avaliacao/resultados/selecao-classificacao-v2.1.1-AAAA-MM-DD
```

Não use `-SkipXai` na rodada destinada ao relatório final. O protocolo compara:

- Granite 97M, multilingual-e5-small e multilingual MiniLM-L12-v2;
- TF-IDF, embedding e híbrido, com metadados nas variantes de deduplicação;
- regressão logística, árvore, SVM linear, MLP e XGBoost;
- CV externo/interno agrupado, calibração, bootstrap, comparações pareadas,
  SHAP e desempenho computacional.

Valide independentemente a saída:

```powershell
python avaliacao/scripts/validar_resultados_selecao.py `
  --saida avaliacao/resultados/selecao-classificacao-v2.1.1-AAAA-MM-DD `
  --config avaliacao/config/selecao_classificacao_supervisionada_v2_1.json
```

Só interprete métricas se o validador terminar sem erro, os hashes coincidirem,
as dobras não compartilharem grupos-fonte e os intervalos forem relatados. O
status ainda será de desenvolvimento e não confirmatório.

A rodada integral de 26/08 está preservada em
`avaliacao/resultados/selecao-supervisionada-v2.1-20260826/`. Sua classificação
tem auditoria `VALID_PARTIAL_TASK_SCOPE`; as 55 configurações de deduplicação
falharam e não podem ser ranqueadas.

## 11. Materialização de candidato

Não materialize bundle a partir do diretório invalidado nem da rodada parcial.
Após uma futura rodada integral válida, a promoção exige revisão humana do relatório, dos erros críticos,
dos intervalos, da calibração, da cobertura e da latência. Um ranking de ponto
ou SHAP não autoriza promoção automática.

Antes de trocar o v1.8, congele novo nome de versão, manifesto, bundle, hashes,
limiares e plano de rollback; execute regressão e E2E novamente.

## 12. Etapa confirmatória

Uma conclusão científica requer, fora deste tutorial operacional:

1. chamados reais autorizados e representativos;
2. rótulos de dois revisores independentes, cegos às predições e aos rótulos um
   do outro, com adjudicação;
3. holdout intocado e protocolo pré-registrado;
4. execução única do candidato congelado;
5. intervalos, calibração, risco-cobertura, subgrupos e análise de erro;
6. piloto prospectivo em sombra.

Consulte `docs/auditoria_critica_completa_2026-08-26.md` para o parecer e os
bloqueadores completos.
