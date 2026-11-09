# Início rápido — ambiente local V9

**Estado:** protótipo operacional; não é implantação produtiva certificada.

## 1. Configure segredos locais

Crie `n8n/.env`, `n8n/.env.local` e `glpi/.env` a partir dos exemplos e troque
todos os `CHANGE_ME`. Não use senhas descritas em documentação e não versione
os arquivos reais.

## 2. Suba os serviços

Na raiz do projeto:

```powershell
$env:COMPOSE_CONVERT_WINDOWS_PATHS=1; docker compose -f glpi/docker-compose.yml up -d
docker compose -f n8n/docker-compose.yml up -d
./local_ai/scripts/start-local-ai.ps1 -CpuThreads 2 -MaxEmbedBatch 1
```

Interfaces locais (as portas vêm do `.env`):

- GLPI: `http://localhost:9080` por padrão; neste host Windows, use `9180`
  porque o intervalo que contém 9080 está reservado pelo sistema;
- n8n: `http://localhost:5678`;
- Mailpit: `http://localhost:18025`;
- IA local: `http://127.0.0.1:8090/health`.

Para criar uma homologação sintética totalmente separada, sem copiar chamados:

```powershell
./avaliacao/operacional/initialize_homolog_env.ps1
docker compose --env-file glpi/.env.homolog `
  -f glpi/docker-compose.yml -f glpi/docker-compose.homolog.yml up -d
docker compose --env-file n8n/.env.homolog `
  -f n8n/docker-compose.yml -f n8n/docker-compose.homolog.yml up -d
python avaliacao/operacional/validate_homolog.py
```

## 3. Valide e publique V9

```powershell
python n8n/workflows/Versão9/validate_v9_static.py
python -m pytest -q n8n/workflows/Versão9/test_v9_hard.py
python n8n/workflows/Versão9/deploy.py
```

O deploy altera o n8n local e deve confirmar seis workflows ativos com
paridade. O WF06 é o ingresso público do plugin GLPI; não use os fluxos V8.

## 4. Testes seguros

```powershell
python -m pytest -q -p no:cacheprovider `
  local_ai/tests `
  avaliacao/tests `
  --ignore=avaliacao/tests/test_runtime_integration_live.py `
  n8n/workflows/Versão9/test_v9_hard.py `
  n8n/history/tests

python n8n/history/validate_history.py --check-sources
```

O smoke live exige `RUN_LIVE_INTEGRATION_TESTS=1`; o E2E mutante exige frase de
confirmação e cleanup. Consulte o guia completo antes de executá-los.

## 5. Limites

Não use `docker system prune -a` como passo de troubleshooting: pode remover
imagens e caches de outros projetos. Não execute seeds, calibração ou E2E em
ambiente produtivo. `scientific_ready=false` é o estado correto até gabarito
independente e holdout institucional. Como esse projeto excluiu revisão humana
e em pares, os resultados permitidos são técnicos/de desenvolvimento por proxy.

Guia completo: `docs/tutorial_reproducao_e_implantacao.md`.
