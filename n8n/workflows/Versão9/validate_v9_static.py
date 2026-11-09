"""Static checks for the V9 n8n + GLPI workflow bundle.

This script intentionally avoids Docker and external services. It validates the
editable Python builders, generated n8n JSON files, docker-compose definitions,
and the initial PostgreSQL schema.
"""

from __future__ import annotations

import json
import hashlib
import py_compile
import subprocess
import sys
from pathlib import Path

from helpers import normalize_n8n_env_access


BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parents[2]

WORKFLOW_FILES = {
    "WF01": "V9-WF01-Sincronizador.json",
    "WF02": "V9-WF02-Triagem.json",
    "WF03": "V9-WF03-Classificacao.json",
    "WF04": "V9-WF04-Decisao-Fiscal.json",
    "WF05": "V9-WF05-Metricas.json",
    "WF06": "V9-WF06-Fila-IA.json",
}

PYTHON_FILES = [
    BASE_DIR / "helpers.py",
    BASE_DIR / "deploy.py",
    BASE_DIR / "deploy_rest_session.py",
    BASE_DIR / "build_wf01.py",
    BASE_DIR / "build_wf02.py",
    BASE_DIR / "build_wf03.py",
    BASE_DIR / "build_wf04.py",
    BASE_DIR / "build_wf05.py",
    BASE_DIR / "build_wf06.py",
    BASE_DIR / "ai_gateway_builder.py",
    BASE_DIR / "retry_queue_builder.py",
    PROJECT_DIR / "local_ai" / "run_server.py",
    PROJECT_DIR / "glpi" / "seed" / "seed_glpi.py",
    PROJECT_DIR / "avaliacao" / "scripts" / "gerar_dataset_avaliacao.py",
    PROJECT_DIR / "avaliacao" / "scripts" / "conferir_gabarito.py",
    PROJECT_DIR / "avaliacao" / "scripts" / "calibrar_vazao.py",
    PROJECT_DIR / "avaliacao" / "scripts" / "calibrar_limiar.py",
    PROJECT_DIR / "avaliacao" / "scripts" / "executar_avaliacao.py",
    PROJECT_DIR / "avaliacao" / "scripts" / "executar_demo_off.py",
    PROJECT_DIR / "avaliacao" / "scripts" / "comparar_baselines.py",
    PROJECT_DIR / "avaliacao" / "scripts" / "validar_dataset.py",
    PROJECT_DIR / "avaliacao" / "scripts" / "sincronizar_manifesto.py",
    PROJECT_DIR / "avaliacao" / "scripts" / "validar_rotulos_especialistas.py",
    PROJECT_DIR / "avaliacao" / "scripts" / "estatistica.py",
    PROJECT_DIR / "avaliacao" / "scripts" / "planejar_amostra.py",
    PROJECT_DIR / "avaliacao" / "scripts" / "gerar_diagnostico_operacional.py",
    PROJECT_DIR / "avaliacao" / "scripts" / "auditar_suficiencia_amostral.py",
    PROJECT_DIR / "avaliacao" / "scripts" / "testar_interfaces_web.py",
    PROJECT_DIR / "avaliacao" / "scripts" / "project_env.py",
]

FORBIDDEN_CREDENTIAL_LITERALS = (
    "Seed" + "Token2024CampusRP",
    "Basic " + "Z2xwaTphZG1pbg==",
    "Triagem" + "Pass2026!",
)

PUBLIC_CREDENTIAL_SCAN_FILES = (
    PYTHON_FILES
    + [BASE_DIR / filename for filename in WORKFLOW_FILES.values()]
    + [PROJECT_DIR / "glpi" / "seed" / "setup_api_token.php"]
)

REQUIRED_ENV_VARS = [
    "GLPI_WEBHOOK_KEY",
    "FISCAL_WEBHOOK_KEY",
    "TEST_MODE",
    "TEST_AUTO_HUMAN_CONFIRMATION",
    "TEST_AUTO_REVIEW_TOKEN",
    "TEST_AUTO_REVIEW_BATCH_SIZE",
    "FISCAL_TOKEN_TTL_MINUTOS",
    "DEDUP_CANDIDATE_LIMIT",
    "DEDUP_LOCAL_TOP_K",
    "DEDUP_POSITIVE_THRESHOLD",
    "DEDUP_NEGATIVE_THRESHOLD",
    "AVALIACAO_HUMANA_BASE_URL",
    "AVALIACAO_HUMANA_AMOSTRA_PERCENT",
    "AVALIACAO_HUMANA_AMOSTRA_MIN",
    "AVALIACAO_HUMANA_AMOSTRA_LIMIT",
    "AVALIACAO_HUMANA_TOKEN_TTL_DIAS",
    "IA_CONFIANCA_MINIMA",
    "IA_OBRA_CONFIANCA_MINIMA",
    "FILA_IA_ATIVA",
    "FILA_IA_LOTE_TAMANHO",
    "FILA_IA_INTERVALO_SEGUNDOS",
    "FILA_IA_LEASE_SEGUNDOS",
    "FILA_IA_INGRESS_GRACE_SEGUNDOS",
    "IA_RETRY_BASE_SEGUNDOS",
    "IA_RETRY_MAX_SEGUNDOS",
    "IA_RETRY_HARD_MAX_SEGUNDOS",
    "IA_MODEL_NAME",
    "IA_MODEL_VERSION",
    "IA_EXECUTION_MODE",
    "IA_FAILOVER_ENABLED",
    "IA_FIXED_MODEL_ROLE",
    "IA_OPERATIONAL_SEQUENCE",
    "IA_MODEL_SECONDARY",
    "IA_MODEL_LOCAL",
    "IA_LOCAL_BASE_URL",
    "IA_LOCAL_API_TOKEN",
    "IA_LOCAL_TIMEOUT_MS",
    "LOCAL_AI_EMBED_BACKEND",
    "LOCAL_AI_EMBED_MODEL_REVISION",
    "IA_GENERATION_SEED",
    "IA_GENERATION_PROFILE",
    "DEMO_EQUIPE_DISPONIVEL",
    "AVALIACAO_DATASET_VERSION",
    "PROMPT_DEDUP_VERSION",
    "PROMPT_CLASSIF_VERSION",
]

REMOTE_SECRET_KEYS = (
    "GEMINI_API_KEY",
    "GEMINI_API_KEY_PRIMARY",
    "GEMINI_API_KEY_SECONDARY",
    "DEEPSEEK_API_KEY",
)

SECRET_PLACEHOLDERS = {
    "",
    "CHANGE_ME",
    "CHANGEME",
    "YOUR_API_KEY",
    "SEU_TOKEN",
}


def parse_env_values(text: str) -> dict[str, str]:
    """Parse the small KEY=VALUE subset used by the project env files."""
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def invalid_configured_remote_secrets(values: dict[str, str]) -> list[str]:
    """Return remote credentials that are present but clearly unusable.

    Remote providers are optional in a local-only clone. Empty values and
    documented placeholders therefore mean "not configured". Once a value is
    supplied, however, it must have a plausible credential length.
    """
    invalid: list[str] = []
    for key in REMOTE_SECRET_KEYS:
        value = values.get(key, "").strip()
        if not value or value.upper() in SECRET_PLACEHOLDERS:
            continue
        if len(value) < 16:
            invalid.append(key)
    return invalid

ANALYTIC_TABLES = [
    "ia_decisoes",
    "ia_tentativas_modelo",
    "workflow_eventos",
    "avaliacoes_humanas",
    "avaliacao_auto_confirmacoes",
    "dataset_controle",
    "experimentos_avaliacao",
    "fila_ia_controle",
]

OPERATIONAL_TABLES = ["fila_ia_metricas", "fila_ia_dead_letter"]

ANALYTIC_STAT_VIEWS = [
    "vw_matriz_confusao_classificacao",
    "vw_kpi_classificacao",
    "vw_scores_classificacao",
    "vw_metricas_assertividade_classificacao",
    "vw_roc_classificacao",
    "vw_auc_classificacao",
    "vw_pr_classificacao",
    "vw_average_precision_classificacao",
    "vw_log_loss_classificacao",
    "vw_brier_classificacao",
    "vw_risco_cobertura_classificacao",
    "vw_metricas_deduplicacao",
    "vw_metricas_deduplicacao_desafio",
    "vw_recall_candidatos_deduplicacao",
    "vw_roc_deduplicacao",
    "vw_auc_deduplicacao",
    "vw_pr_deduplicacao",
    "vw_average_precision_deduplicacao",
    "vw_log_loss_deduplicacao",
    "vw_proveniencia_gateway_ia",
    "vw_decisoes_confirmatorias_elegiveis",
    "vw_erros_ia_sem_dead_letter",
]


failures: list[str] = []


def ok(message: str) -> None:
    print(f"PASS: {message}")


def check(condition: bool, message: str) -> None:
    if condition:
        ok(message)
    else:
        failures.append(message)
        print(f"FAIL: {message}")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def forbidden_credential_occurrences(paths) -> list[str]:
    hits: list[str] = []
    for path in paths:
        path = Path(path)
        if not path.exists() or not path.is_file():
            continue
        text = read_text(path)
        if any(literal in text for literal in FORBIDDEN_CREDENTIAL_LITERALS):
            try:
                hits.append(str(path.relative_to(PROJECT_DIR)))
            except ValueError:
                hits.append(str(path))
    return hits


def compact(text: str) -> str:
    return " ".join(text.lower().split())


def load_workflows() -> dict[str, dict]:
    workflows: dict[str, dict] = {}
    for key, filename in WORKFLOW_FILES.items():
        path = BASE_DIR / filename
        check(path.exists(), f"{filename} exists")
        workflows[key] = json.loads(read_text(path))
        ok(f"{filename} is valid JSON")
    return workflows


def node_names(workflow: dict) -> set[str]:
    return {str(node.get("name")) for node in workflow.get("nodes", [])}


def nodes_by_name(workflow: dict) -> dict[str, dict]:
    return {str(node.get("name")): node for node in workflow.get("nodes", [])}


def iter_strings(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_strings(item)
    elif isinstance(value, str):
        yield value


def workflow_text(workflow: dict) -> str:
    return json.dumps(workflow, ensure_ascii=False, sort_keys=True)


def connection_targets(workflow: dict, source: str) -> set[str]:
    targets: set[str] = set()
    outputs = workflow.get("connections", {}).get(source, {})
    for output_group in outputs.values():
        if not isinstance(output_group, list):
            continue
        for branch in output_group:
            if isinstance(branch, dict):
                target = branch.get("node")
                if target:
                    targets.add(str(target))
                continue
            if not isinstance(branch, list):
                continue
            for edge in branch:
                if isinstance(edge, dict) and edge.get("node"):
                    targets.add(str(edge["node"]))
    return targets


def connection_targets_by_branch(workflow: dict, source: str) -> list[set[str]]:
    """Return the ordered main-output targets (for example, true/false of an IF node)."""
    branches = workflow.get("connections", {}).get(source, {}).get("main", [])
    result: list[set[str]] = []
    if not isinstance(branches, list):
        return result
    for branch in branches:
        edges = branch if isinstance(branch, list) else [branch]
        result.append(
            {
                str(edge["node"])
                for edge in edges
                if isinstance(edge, dict) and edge.get("node")
            }
        )
    return result


def validate_python() -> None:
    for path in PYTHON_FILES:
        check(path.exists(), f"{path.relative_to(PROJECT_DIR)} exists")
        py_compile.compile(str(path), doraise=True)
        ok(f"{path.relative_to(PROJECT_DIR)} compiles")
    checker_text = read_text(
        PROJECT_DIR / "avaliacao" / "scripts" / "conferir_gabarito.py"
    )
    check(
        "require_completion_gates(experiment(args.run_id))" in checker_text,
        "experimental completion enforces label and human-audit gates",
    )
    check(
        "VALIDACAO AUTOMATIZADA NAO CONFIRMATORIA" in checker_text
        and "Gabarito sintético não pode ser materializado" in checker_text,
        "automated validation cannot be promoted to confirmatory benchmark",
    )
    automated_runner = read_text(
        PROJECT_DIR / "avaliacao" / "scripts" / "executar_avaliacao.py"
    )
    check(
        'choices=["piloto", "validacao", "benchmark"]' in automated_runner
        and "CONCLUIDO_AUTOMATIZADO" in automated_runner,
        "runner exposes a separate non-confirmatory automated validation phase",
    )
    for number in range(1, 7):
        builder = BASE_DIR / f"build_wf{number:02d}.py"
        check(
            "SNAPSHOT_SHA256" in read_text(builder),
            f"WF{number:02d} builder protects the approved JSON with a snapshot hash",
        )


def validate_json_structure(workflows: dict[str, dict]) -> None:
    expected_names = {
        "WF01": "V9 - WF01 Sincronizador",
        "WF02": "V9 - WF02 Triagem",
        "WF03": "V9 - WF03 Classificação",
        "WF04": "V9 - WF04 Decisão Fiscal",
        "WF05": "V9 - WF05 Métricas",
        "WF06": "V9 - WF06 Fila IA",
    }
    for key, workflow in workflows.items():
        names = [str(node.get("name")) for node in workflow.get("nodes", [])]
        node_set = set(names)
        check(workflow.get("name") == expected_names[key], f"{key} has the expected workflow name")
        check(bool(names), f"{key} has nodes")
        check(len(names) == len(node_set), f"{key} has unique node names")
        if key == "WF06":
            check(
                any(node.get("type") == "n8n-nodes-base.wait" for node in workflow.get("nodes", [])),
                "WF06 has a controlled Wait node for paced IA release",
            )
        else:
            check(
                all(node.get("type") != "n8n-nodes-base.wait" for node in workflow.get("nodes", [])),
                f"{key} has no Wait node",
            )
        check(
            all("mock" not in name.lower() and "determin" not in name.lower() for name in names),
            f"{key} has no mock/deterministic node names",
        )
        for source, outputs in workflow.get("connections", {}).items():
            check(source in node_set, f"{key} connection source exists: {source}")
            for target in connection_targets(workflow, source):
                check(target in node_set, f"{key} connection target exists: {target}")
        for node in workflow.get("nodes", []):
            for parameter in iter_strings(node.get("parameters", {})):
                if "process.env" not in parameter:
                    continue
                prompt_literal = "{{ Number($env.IA_CONFIANCA_MINIMA || 0.65) }}"
                without_prompt_literal = parameter.replace(prompt_literal, "")
                check(
                    "$env" not in without_prompt_literal,
                    f"{key}/{node.get('name')} has no executable $env access",
                )


def validate_v9_rules(workflows: dict[str, dict]) -> None:
    wf01 = workflows["WF01"]
    wf02 = workflows["WF02"]
    wf03 = workflows["WF03"]
    wf04 = workflows["WF04"]
    wf05 = workflows["WF05"]
    wf06 = workflows["WF06"]

    wf01_text = workflow_text(wf01)
    check("Validar Sessão GLPI" in node_names(wf01), "WF01 validates GLPI initSession output")
    check(
        "GLPI: Buscar Chamados" in connection_targets(wf01, "Validar Sessão GLPI"),
        "WF01 only searches tickets after GLPI session validation",
    )
    check("fetchAllSearchTickets" not in wf01_text, "WF01 no longer duplicates the GLPI search inside code")
    check(
        "PG: Enfileirar Pendentes WF06" in connection_targets(wf01, "LOG: Resumo Sync"),
        "WF01 recovers synchronized tickets into the shared WF06 queue",
    )
    check("Chamar WF02 Sync" not in node_names(wf01), "WF01 never bypasses WF06")
    check("CREATE TABLE IF NOT EXISTS ia_decisoes" in wf01_text, "WF01 guarantees ia_decisoes before operational use")

    wf02_nodes = nodes_by_name(wf02)
    wf03_nodes = nodes_by_name(wf03)
    wf04_nodes = nodes_by_name(wf04)
    wf05_nodes = nodes_by_name(wf05)
    wf02_text = workflow_text(wf02)

    for key in ("WF01", "WF02", "WF03", "WF04", "WF05", "WF06"):
        current_workflow = workflows[key]
        text = workflow_text(current_workflow)
        if "GLPI_APP_TOKEN" in text:
            check(
                "GLPI_APP_TOKEN ausente" in text,
                f"{key} fails closed when GLPI_APP_TOKEN is absent",
            )
        if "GLPI_AUTH_BASIC" in text:
            check(
                "GLPI_AUTH_BASIC ausente" in text,
                f"{key} fails closed when GLPI_AUTH_BASIC is absent",
            )
        check(
            "={{ $env.GLPI_APP_TOKEN || '' }}" not in text
            and "={{ $env.GLPI_AUTH_BASIC || 'Basic ' }}" not in text,
            f"{key} has no weak empty GLPI credential header fallback",
        )
        check(
            all(
                "$env" not in str((node.get("parameters") or {}).get("jsCode") or "")
                and "process.env" not in str((node.get("parameters") or {}).get("jsCode") or "")
                for node in current_workflow.get("nodes", [])
                if node.get("type") == "n8n-nodes-base.code"
            ),
            f"{key} Code nodes have no environment-variable access",
        )

        for node in current_workflow.get("nodes", []):
            parameters = node.get("parameters", {})
            header_entries = (
                parameters.get("headerParameters", {}).get("parameters", [])
            )
            for header in header_entries:
                header_name = header.get("name")
                header_value = str(header.get("value", ""))
                if header_name == "App-Token":
                    check(
                        "$env.GLPI_APP_TOKEN" in header_value
                        and "GLPI_APP_TOKEN ausente" in header_value
                        and "CHANGE_ME" in header_value,
                        f"{key}/{node.get('name')} App-Token header fails closed",
                    )
                if header_name == "Authorization" and "GLPI_AUTH_BASIC" in header_value:
                    check(
                        "$env.GLPI_AUTH_BASIC" in header_value
                        and "GLPI_AUTH_BASIC ausente" in header_value
                        and "CHANGE_ME" in header_value,
                        f"{key}/{node.get('name')} GLPI Authorization header fails closed",
                    )

            js_code = str(parameters.get("jsCode", ""))
            if "helpers.httpRequest" in js_code and "'App-Token'" in js_code:
                check(
                    "GLPI_APP_TOKEN ausente" in js_code
                    and "GLPI session_token ausente" in js_code,
                    f"{key}/{node.get('name')} requires GLPI app and session tokens before direct HTTP",
                )

    gateway_compose = read_text(PROJECT_DIR / "n8n" / "docker-compose.yml")
    gateway_template = read_text(PROJECT_DIR / "n8n" / "proxies" / "n8n-gateway.conf.template")
    check(
        "glpi-n8n-ic-2026" not in wf02_text
        and "glpi-n8n-ic-2026" not in workflow_text(wf06)
        and "n8n-gateway:" in gateway_compose
        and "GLPI_WEBHOOK_KEY=${GLPI_WEBHOOK_KEY:?" in gateway_compose
        and "location = /webhook/glpi-ticket-fila-ia-v9" in gateway_template
        and '$http_x_webhook_key != "${GLPI_WEBHOOK_KEY}"' in gateway_template
        and "Webhook GLPI" not in wf02_nodes
        and "wf06-fila-ia" in wf02_text,
        "gateway authenticates public GLPI ingress; WF02 accepts only internal workflow sources",
    )

    check("Webhook GLPI" not in wf02_nodes, "WF02 has no public webhook ingress")
    check(
        "Início Subworkflow/Teste" in wf02_nodes,
        "WF02 is an internal subworkflow worker",
    )
    persistence_branches = connection_targets_by_branch(wf02, "Decisão IA Persistida?")
    check(
        connection_targets(wf02, "Normalizar Dedup") == {"PG: Registrar IA Dedup"}
        and connection_targets(wf02, "PG: Registrar IA Dedup") == {"Decisão IA Persistida?"}
        and len(persistence_branches) >= 2
        and persistence_branches[0] == {"Duplicado?"}
        and persistence_branches[1] == {"Preparar Erro Persistência IA"}
        and connection_targets(wf02, "Preparar Erro Persistência IA") == {"PG: Erro IA Dedup"},
        "WF02 persists the scientific dedup decision before any operational action",
    )
    check(
        wf02_nodes["PG: Registrar IA Dedup"].get("onError") == "continueRegularOutput",
        "WF02 routes decision-persistence errors to its fail-closed gate",
    )
    wf02_text = workflow_text(wf02)
    check(
        "let candidateLimit = 20" in wf02_text
        and "candidateLimit = Math.min(20" in wf02_text,
        "WF02 freezes the remote candidate limit at 20",
    )
    check(
        "DEDUP_LOCAL_TOP_K" in wf02_text
        and "historico_local" in wf02_text
        and "local_candidate_limit" in wf02_text,
        "WF02 keeps an auditable configurable local top-k candidate view",
    )
    check("LIMIT 80" in wf02_text, "WF02 keeps the 80-row dedup retrieval pool")
    check("fiscal_token_expira_em" in wf02_text, "WF02 writes fiscal_token_expira_em")
    check(
        "fiscal_token_expira_em" in wf02_text and "ttl=10080" in wf02_text,
        "WF02 uses the frozen seven-day fiscal token TTL",
    )
    check(
        "0.78" in wf02_text
        and "0.22" in wf02_text
        and "abstencao_operacional_dedup" in wf02_text,
        "WF02 applies the frozen asymmetric dedup thresholds with operational abstention",
    )
    check("probabilidades" in wf02_text, "WF02 records dedup probabilities for ROC/AUC and Log Loss")
    check("INSERT INTO ia_decisoes" in wf02_text, "WF02 inserts into ia_decisoes")
    check("INSERT INTO workflow_eventos" in wf02_text, "WF02 inserts into workflow_eventos")
    check("deduplicacao_v9.1-episodica" in wf02_text, "WF02 records the frozen dedup prompt version")
    check("Validar Sessão GLPI" in node_names(wf02), "WF02 validates GLPI initSession output")
    check("PG: Enfileirar Webhook" not in node_names(wf02), "WF02 does not own the ingress queue")
    check("PENDENTE_FILA_IA" in wf02_text, "WF02 writes the IA queue status")
    check("FILA_IA_LIBERADA" in wf02_text, "WF02 accepts tickets released by WF06")
    check(
        "SELECT id AS dataset_row_id,run_id" in wf02_text
        and "c.run_id=dc.run_id" in wf02_text
        and "dc.id < c.dataset_row_id" in wf02_text,
        "WF02 uses prior distractors from the same experimental run",
    )
    check(
        "c.episode_id=dc.episode_id" not in wf02_text,
        "WF02 does not create a closed-world episode-only candidate set",
    )
    check(
        wf02_nodes["IA: Verificar Duplicidade"].get("type") == "n8n-nodes-base.code",
        "WF02 uses the in-n8n multi-model gateway",
    )
    check(
        all(marker in wf02_text for marker in (
            "IA_MODEL_SECONDARY", "IA_MODEL_LOCAL", "gemini-3.5-flash",
            "local-ai-credential-proxy:8080",
        )),
        "WF02 embeds the explicit LOCAL role and isolated remote benchmark role",
    )
    check("INSERT INTO ia_tentativas_modelo" in wf02_text, "WF02 persists every provider attempt")
    check(
        all(marker in wf02_text for marker in (
            "endpoint,perfil_entrada,prompt_chars,input_chars,total_candidatos,http_status",
            "retry_after_seconds,retryable,tipo_erro,metadata_cientifica",
            "a.value->'scientific_metadata'",
        )),
        "WF02 persists transport, input profile and scientific metadata for every attempt",
    )
    check(
        all(marker in wf02_text for marker in (
            "ia_http_status", "ia_retry_after_seconds", "ia_retryable", "ia_error_type",
            "parseRetryAfter", "retry-after",
        )),
        "WF02 preserves HTTP status and provider retry metadata",
    )
    check("EXPERIMENT_MODEL_MISMATCH" in wf02_text, "WF02 fails closed on experimental model mismatch")
    check("fila_ia_dead_letter" in wf02_text, "WF02 sends exhausted retries to the DLQ")
    check("fila_disponivel_em" in wf02_text, "WF02 schedules exponential retry backoff")
    wf02_retry_query = wf02_nodes["PG: Erro IA Dedup"]["parameters"]["query"]
    check(
        all(marker in wf02_retry_query for marker in (
            "pg_advisory_xact_lock(9062026)", "fila_ia_controle",
            "proxima_liberacao_em", "PERMANENT_HTTP", "RATE_LIMIT",
            "SERVICE_UNAVAILABLE", "TIMEOUT", "IA_RETRY_HARD_MAX_SEGUNDOS",
        )),
        "WF02 uses status-aware retry, permanent failure handling and global cooldown",
    )
    check(
        wf02_retry_query.index("pg_advisory_xact_lock(9062026)")
        < wf02_retry_query.index("FROM fila_ia_controle")
        < wf02_retry_query.index("UPDATE tickets_processados"),
        "WF02 locks queue control before updating a retry ticket",
    )
    check("api_response_raw" in wf02_text, "WF02 preserves the raw provider response")
    check(
        "Math.abs((pd + pn)-1) <= 0.001" in wf02_text
        and "Vetor de probabilidades inválido ou soma diferente de 1" in wf02_text,
        "WF02 rejects malformed probability vectors instead of renormalizing them",
    )
    check(
        "Decisão de duplicidade diverge da maior probabilidade" in wf02_text,
        "WF02 rejects a dedup label inconsistent with its probability vector",
    )
    check(
        "confianca_declarada" in wf02_text
        and "confianca:confiancaSemantica" in wf02_text
        and "confianca_operacional:confianca" in wf02_text
        and "probabilidades_semanticas" in wf02_text,
        "WF02 preserves semantic candidate scores separately from operational abstention",
    )
    check(
        "GLPI: Pendente Revisão Dedup" in wf02_nodes
        and "GLPI: Pendente Revisão Dedup" in connection_targets(wf02, "Duplicado?"),
        "WF02 routes every low-confidence dedup decision to human review",
    )
    check(
        "const inputModelo={chamado_atual:p.chamado_atual,historico:hist};" in wf02_text,
        "WF02 hashes and records the exact dedup model input",
    )
    check(
        "candidate_profile:benchmarkPaired ? 'BENCHMARK_PAIRED_FROZEN'" in wf02_text
        and "candidate_order_ids:hist.map(item=>Number(item.id))" in wf02_text
        and "referencia_presente_candidatos" in wf02_text,
        "WF02 records which candidate view reached the selected model for recall auditing",
    )
    check(
        "const validacao=$('Validar Categoria Técnica').first().json || {}" in wf02_text
        and "validacao.chamado || $json.chamado" in wf02_text,
        "WF02 preserves the ticket payload after GLPI category-correction HTTP responses",
    )
    check(
        "Reprocessar WF02" not in connection_targets(wf02, "Preparar Retry Dedup"),
        "WF02 retry after dedup IA error returns to queue instead of immediate reprocessing",
    )
    check(
        "WF02_REENFILEIRADO_ERRO_IA_DEDUP" in wf02_text,
        "WF02 records dedup IA retry requeue events",
    )
    check(
        {"Preparar WF03", "Chamar WF03"}.isdisjoint(node_names(wf02))
        and connection_targets(wf02, "GLPI: Marcar Pendente") == {"GLPI: Encerrar Sessão"},
        "WF02 returns classification to WF06 instead of invoking WF03 directly",
    )
    check(
        all(marker in wf02_nodes["PG: Marcar Não Duplicado"]["parameters"]["query"] for marker in (
            "triagem_status='PENDENTE_FILA_IA'", "fila_etapa='CLASSIFICACAO'",
            "fila_enfileirada_em=NOW()", "fila_disponivel_em=NOW()",
            "fila_liberar_em=NULL", "fila_reservada_em=NULL",
        )),
        "WF02 enqueues the classification stage with a clean queue lease",
    )

    wf03_text = workflow_text(wf03)
    classification_persistence_branches = connection_targets_by_branch(
        wf03, "Decisão IA Classificação Persistida?"
    )
    check(
        connection_targets(wf03, "Normalizar Classificação")
        == {"PG: Registrar IA Classificação"}
        and connection_targets(wf03, "PG: Registrar IA Classificação")
        == {"Decisão IA Classificação Persistida?"}
        and len(classification_persistence_branches) >= 2
        and classification_persistence_branches[0] == {"Switch Classificação"}
        and classification_persistence_branches[1]
        == {"Preparar Erro Persistência IA Classif"}
        and connection_targets(wf03, "Preparar Erro Persistência IA Classif")
        == {"PG: Erro IA Classif"},
        "WF03 persists the scientific classification decision before any operational action",
    )
    check(
        wf03_nodes["PG: Registrar IA Classificação"].get("onError")
        == "continueRegularOutput",
        "WF03 routes decision-persistence errors to its fail-closed gate",
    )
    check("INSERT INTO ia_decisoes" in wf03_text, "WF03 inserts into ia_decisoes")
    check("INSERT INTO workflow_eventos" in wf03_text, "WF03 inserts into workflow_eventos")
    check("TRIAGEM_MANUAL" in wf03_text, "WF03 handles TRIAGEM_MANUAL")
    check(
        "rota_operacional:classeFinal" in wf03_text
        and "classe_semantica:classeSemantica" in wf03_text
        and "semantic_class_prediction" in wf03_text
        and "operational_information_sufficient" in wf03_text,
        "WF03 separates semantic IA class from DEMO availability routing",
    )
    check("probabilidades" in wf03_text, "WF03 records class probabilities for ROC/AUC and Log Loss")
    check("classificacao_v9.1-episodica" in wf03_text, "WF03 records the frozen classification prompt version")
    check("Validar Sessão GLPI" in node_names(wf03), "WF03 validates GLPI initSession output")
    check(
        wf03_nodes["IA: Classificar"].get("type") == "n8n-nodes-base.code",
        "WF03 uses the in-n8n multi-model gateway",
    )
    check(
        all(marker in wf03_text for marker in (
            "IA_MODEL_SECONDARY", "IA_MODEL_LOCAL", "gemini-3.5-flash",
            "local-ai-credential-proxy:8080",
        )),
        "WF03 embeds the explicit LOCAL role and isolated remote benchmark role",
    )
    check("INSERT INTO ia_tentativas_modelo" in wf03_text, "WF03 persists every provider attempt")
    check(
        all(marker in wf03_text for marker in (
            "endpoint,perfil_entrada,prompt_chars,input_chars,total_candidatos,http_status",
            "retry_after_seconds,retryable,tipo_erro,metadata_cientifica",
            "a.value->'scientific_metadata'",
        )),
        "WF03 persists transport, input profile and scientific metadata for every attempt",
    )
    check(
        all(marker in wf03_text for marker in (
            "ia_http_status", "ia_retry_after_seconds", "ia_retryable", "ia_error_type",
            "parseRetryAfter", "retry-after",
        )),
        "WF03 preserves HTTP status and provider retry metadata",
    )
    check("EXPERIMENT_MODEL_MISMATCH" in wf03_text, "WF03 fails closed on experimental model mismatch")
    check("fila_ia_dead_letter" in wf03_text, "WF03 sends exhausted retries to the DLQ")
    check("fila_disponivel_em" in wf03_text, "WF03 schedules exponential retry backoff")
    wf03_retry_query = wf03_nodes["PG: Erro IA Classif"]["parameters"]["query"]
    check(
        all(marker in wf03_retry_query for marker in (
            "pg_advisory_xact_lock(9062026)", "fila_ia_controle",
            "proxima_liberacao_em", "PERMANENT_HTTP", "RATE_LIMIT",
            "SERVICE_UNAVAILABLE", "TIMEOUT", "IA_RETRY_HARD_MAX_SEGUNDOS",
        )),
        "WF03 uses status-aware retry, permanent failure handling and global cooldown",
    )
    check(
        wf03_retry_query.index("pg_advisory_xact_lock(9062026)")
        < wf03_retry_query.index("FROM fila_ia_controle")
        < wf03_retry_query.index("UPDATE tickets_processados"),
        "WF03 locks queue control before updating a retry ticket",
    )
    check("api_response_raw" in wf03_text, "WF03 preserves the raw provider response")
    check("operational_config" in wf03_text, "WF03 records DEMO operational state")
    check(
        "Math.abs(soma-1) > 0.001" in wf03_text
        and "Vetor de probabilidades inválido ou soma diferente de 1" in wf03_text,
        "WF03 rejects malformed probability vectors instead of renormalizing them",
    )
    check(
        "Classe declarada diverge da maior probabilidade" in wf03_text,
        "WF03 rejects a semantic class inconsistent with its probability vector",
    )
    check(
        "confianca_declarada" in wf03_text
        and "confianca:confiancaSemantica" in wf03_text
        and "confianca_operacional:confianca" in wf03_text
        and "probabilidades_semanticas" in wf03_text,
        "WF03 preserves semantic candidate scores separately from operational abstention",
    )
    check(
        "const inputModelo=c;" in wf03_text,
        "WF03 hashes and records the exact classification model input",
    )
    wf03_payload = wf03_nodes["Montar Payload Classificação"]["parameters"]["jsCode"]
    check(
        "chamado_modelo" in wf03_payload
        and "log_workflow" not in wf03_payload
        and "fiscal_decision_token" not in wf03_payload,
        "WF03 sends only compact essential ticket fields to the model",
    )
    check(
        "Disponibilidade da equipe DEMO é uma variável operacional externa" in wf03_text,
        "WF03 does not ask the LLM to infer DEMO availability",
    )
    check(
        "Reprocessar WF03" not in connection_targets(wf03, "Preparar Retry Classificação"),
        "WF03 retries return to WF06 instead of bypassing queue pacing",
    )
    for name in [
        "GLPI: Pendente Triagem Manual",
        "GLPI: Atribuir DEMO",
        "GLPI: Planejado SOB_DEMANDA",
        "GLPI: Planejar DEMO sem equipe",
        "GLPI: Fechar OBRA",
    ]:
        check(
            wf03_nodes.get(name, {}).get("onError") == "continueRegularOutput",
            f"WF03 continues after GLPI status failure at {name}",
        )

    webhook_fiscal = wf04_nodes.get("Webhook Fiscal", {})
    check(
        webhook_fiscal.get("parameters", {}).get("path") == "fiscal-decisao-fiscal-ic-2026",
        "WF04 fiscal webhook path is stable",
    )
    check(
        webhook_fiscal.get("parameters", {}).get("httpMethod") == "POST",
        "WF04 mutates fiscal decisions only through POST",
    )
    check(
        wf04_nodes.get("Webhook Fiscal Confirmação", {}).get("parameters", {}).get("httpMethod") == "GET",
        "WF04 GET link only renders a confirmation page",
    )
    check(
        {"Link Válido?", "PG: Registrar Link Fiscal"}.issubset(connection_targets(wf04, "Extrair Decisão")),
        "WF04 records every fiscal link hit",
    )
    check(
        {"Switch Ação Fiscal", "PG: Registrar Decisão Fiscal"}.issubset(connection_targets(wf04, "Validar Fiscal")),
        "WF04 records every fiscal validation result",
    )
    check(
        "PG: Evento Fiscal Confirmado" in connection_targets(wf04, "PG: Duplicado Fechado"),
        "WF04 records confirmed duplicate final result",
    )
    check(
        "PG: Evento Fiscal Rejeitado" in connection_targets(wf04, "PG: Limpar Duplicidade"),
        "WF04 records rejected duplicate final result",
    )
    check("Chamar WF03" not in node_names(wf04), "WF04 never bypasses WF06 after fiscal rejection")
    check(
        "PG: Enfileirar Classificação"
        in connection_targets(wf04, "GLPI: Encerrar Sessão Fiscal Rejeição"),
        "WF04 returns rejected duplicates to the paced classification queue",
    )
    wf04_text = workflow_text(wf04)
    wf04_text_lower = wf04_text.lower()
    check("fiscal_token_expira_em > NOW()" in wf04_text, "WF04 validates fiscal token expiry")
    check("fiscal_token_expirado" in wf04_text, "WF04 distinguishes expired fiscal tokens")
    check("clique_duplo" in wf04_text_lower, "WF04 records double clicks")
    check("token_invalido" in wf04_text_lower, "WF04 records invalid tokens")
    check("token_expirado" in wf04_text_lower, "WF04 records expired tokens")

    wf05_text = compact(workflow_text(wf05))
    for relation in (
        "ia_decisoes",
        "ia_tentativas_modelo",
        "workflow_eventos",
        "metricas_diarias_automacao",
        "vw_kpi_geral_automacao",
        "vw_kpi_duplicidade",
        "vw_kpi_classificacao",
    ):
        check(relation in wf05_text, f"WF05 verifies or reads runtime relation {relation}")
    check(
        all(token not in wf05_text for token in ("create table", "alter table", "create or replace view")),
        "WF05 runtime JSON contains no schema DDL",
    )
    check("webhook avaliação humana" in wf05_text, "WF05 exposes the human evaluation webhook")
    check("avaliacao-humana-v9" in wf05_text, "WF05 uses the stable human evaluation webhook path")
    check(
        wf05_nodes.get("Webhook Avaliação Humana", {}).get("parameters", {}).get("httpMethod") == "POST",
        "WF05 mutates human evaluations only through POST",
    )
    check(
        wf05_nodes.get("Webhook Confirmação Avaliação", {}).get("parameters", {}).get("httpMethod") == "GET",
        "WF05 GET link only renders a confirmation page",
    )
    check(
        "pg: selecionar avaliações humanas"
        not in compact(str(connection_targets(wf05, "PG: Consolidar Métricas"))),
        "WF05 does not create a competing random research sample",
    )
    check("pg: registrar avaliação humana" in wf05_text, "WF05 records human review responses")

    wf06_text = workflow_text(wf06)
    wf06_names = node_names(wf06)
    check("Agendador Fila IA" in wf06_names, "WF06 has a scheduled queue drain")
    check("PG: Reservar Fila IA" in wf06_names, "WF06 reserves pending IA queue tickets")
    check("Aguardar Janela" in wf06_names, "WF06 waits between IA releases")
    check("Chamar WF02 da Fila" in wf06_names, "WF06 dispatches released tickets to WF02")
    check("Chamar WF03 da Fila" in wf06_names, "WF06 paces classification retries and fiscal rejections")
    check("PENDENTE_FILA_IA" in wf06_text, "WF06 reads the pending IA queue status")
    check("FILA_IA_LIBERADA" in wf06_text, "WF06 marks tickets released for IA")
    check("FILA_IA_LOTE_TAMANHO" in wf06_text, "WF06 uses FILA_IA_LOTE_TAMANHO")
    check("FILA_IA_INTERVALO_SEGUNDOS" in wf06_text, "WF06 uses FILA_IA_INTERVALO_SEGUNDOS")
    check("FILA_IA_LEASE_SEGUNDOS" in wf06_text, "WF06 recovers expired queue reservations")
    check(
        "FILA_IA_RUN_SCOPE" in wf06_text
        and "dc.run_id=(SELECT run_scope FROM parametros)" in wf06_text
        and "OR d.run_id=(SELECT run_scope FROM parametros)" in wf06_text,
        "WF06 can isolate reservations and experiment context to one calibration run",
    )
    check("pg_advisory_xact_lock" in wf06_text, "WF06 serializes concurrent schedulers")
    check(
        "bloqueio AS MATERIALIZED" in wf06_text
        and "CROSS JOIN bloqueio" in wf06_text,
        "WF06 advisory lock is part of the single reservation statement",
    )
    check(
        "$input.all().map" in wf06_text
        and "hasOwnProperty.call(candidate, 'tickets')" in wf06_text,
        "WF06 selects the SQL result containing the ticket array",
    )
    check(
        "source:'wf06-fila-ia'" in wf06_text
        and "chamado:{...chamado,source:'wf06-fila-ia'}" in wf06_text,
        "WF06 carries authenticated internal source in the dispatched item",
    )
    check(
        "GLPI_WEBHOOK_KEY" not in wf06_text
        and "O gateway n8n-gateway valida X-Webhook-Key" in wf06_text,
        "WF06 Code nodes do not receive or read the GLPI webhook secret",
    )
    for worker_name in ("Chamar WF02 da Fila", "Chamar WF03 da Fila"):
        check(
            nodes_by_name(wf06)
            .get(worker_name, {})
            .get("parameters", {})
            .get("options", {})
            .get("waitForSubWorkflow")
            is True,
            f"WF06 waits for {worker_name} completion",
        )
    tem_chamados = nodes_by_name(wf06).get("Tem Chamados?", {})
    tem_chamados_condition = (
        tem_chamados.get("parameters", {})
        .get("conditions", {})
        .get("conditions", [{}])[0]
    )
    check(
        tem_chamados_condition.get("leftValue")
        == "={{ Number($json.total_lote || 0) > 0 }}"
        and tem_chamados_condition.get("operator")
        == {"type": "boolean", "operation": "true"},
        "WF06 tests total_lote with an explicit boolean condition",
    )
    check("fila_disponivel_em" in wf06_text, "WF06 honors retry backoff availability")
    check(
        "t.fila_etapa='CLASSIFICACAO'" in wf06_text
        and "COALESCE(t.status_num,4)=4" in wf06_text
        and "COALESCE(t.fila_etapa,'DEDUPLICACAO')='DEDUPLICACAO'" in wf06_text,
        "WF06 reserves pending classification retries as well as new dedup tickets",
    )
    check("fila_ia_metricas" in wf06_text, "WF06 persists queue telemetry")
    check("Webhook GLPI Fila" in wf06_names, "WF06 is the public GLPI ingress")
    check(
        nodes_by_name(wf06).get("Webhook GLPI Fila", {}).get("parameters", {}).get("path")
        == "glpi-ticket-fila-ia-v9",
        "WF06 exposes the stable GLPI queue webhook path",
    )
    check(
        nodes_by_name(wf06)
        .get("Resp: Rejeitado", {})
        .get("parameters", {})
        .get("options", {})
        .get("responseCode")
        == "={{ Number($json.codigo_http || 401) }}",
        "WF06 preserves 401 versus 422 ingress rejection semantics",
    )
    check(
        "Aguardar Janela" in connection_targets(wf06, "Tem Chamados?"),
        "WF06 only waits and dispatches when there are queued tickets",
    )
    check(
        {"Chamar WF02 da Fila", "Chamar WF03 da Fila"}.issubset(
            connection_targets(wf06, "É Classificação?")
        ),
        "WF06 routes each reserved item to the requested IA stage",
    )


def validate_schema_and_config() -> None:
    init_sql_raw = read_text(PROJECT_DIR / "database" / "init_v9.sql")
    init_sql = compact(init_sql_raw)
    for table in ANALYTIC_TABLES + OPERATIONAL_TABLES:
        check(
            f"create table if not exists {table}" in init_sql,
            f"init_v9.sql creates {table} idempotently",
        )
    for view in ANALYTIC_STAT_VIEWS:
        check(
            f"create or replace view {view}" in init_sql
            or f"create view {view}" in init_sql,
            f"init_v9.sql creates analytic statistic view {view}",
        )
    final_score_view = init_sql_raw[init_sql_raw.rfind(
        "CREATE OR REPLACE VIEW vw_scores_classificacao"
    ):init_sql_raw.find(
        "CREATE OR REPLACE VIEW vw_roc_classificacao",
        init_sql_raw.rfind("CREATE OR REPLACE VIEW vw_scores_classificacao"),
    )]
    check(
        "ia_estava_correta" not in final_score_view,
        "final probabilistic score view has no label-derived imputation",
    )
    check(
        "probabilidades_semanticas" in final_score_view
        and "hybrid_model_abstention" in final_score_view,
        "classification probability metrics retain pre-abstention local candidate scores",
    )
    final_dedup_score_view = init_sql_raw[init_sql_raw.rfind(
        "CREATE OR REPLACE VIEW vw_scores_deduplicacao"
    ):init_sql_raw.find(
        "CREATE OR REPLACE VIEW vw_roc_deduplicacao",
        init_sql_raw.rfind("CREATE OR REPLACE VIEW vw_scores_deduplicacao"),
    )]
    check(
        "probabilidades_semanticas" in final_dedup_score_view
        and "hybrid_model_abstention" in final_dedup_score_view,
        "dedup probability metrics retain pre-abstention local candidate scores",
    )
    check(
        "AS gabarito_humano" in init_sql_raw
        and "AS gabarito_sintetico" in init_sql_raw
        and "a.fonte_gabarito IN ('ADJUDICADO','REVISAO_HUMANA')" in init_sql_raw,
        "confirmatory metrics require normative human gold provenance",
    )
    check(
        "Metricas experimentais V2" in init_sql_raw,
        "init_v9.sql contains the run-isolated experimental metric layer",
    )
    for column in (
        "api_response_raw", "operational_config", "fila_disponivel_em",
        "perfil_entrada", "http_status", "retry_after_seconds", "retryable",
        "metadata_cientifica",
    ):
        check(column in init_sql, f"init_v9.sql includes {column}")
    check(
        "idx_ia_decisoes_run_etapa_criado" in init_sql,
        "init_v9.sql includes partial research index",
    )

    n8n_compose = read_text(PROJECT_DIR / "n8n" / "docker-compose.yml")
    n8n_env_path = PROJECT_DIR / "n8n" / ".env"
    n8n_env_example_path = PROJECT_DIR / "n8n" / ".env.example"
    check(n8n_env_example_path.exists(), "n8n .env.example exists")
    env_definition_path = (
        n8n_env_path if n8n_env_path.exists() else n8n_env_example_path
    )
    n8n_env = read_text(env_definition_path)
    for var in REQUIRED_ENV_VARS:
        check(var in n8n_env, f"{env_definition_path.name} defines {var}")
    n8n_service_block = n8n_compose.split("\n  n8n:\n", 1)[1].split(
        "\n  n8n-gateway:\n", 1
    )[0]
    check("env_file:" not in n8n_service_block, "n8n main process does not import .env files")
    check(
        all(
            secret not in n8n_service_block
            for secret in (
                "GLPI_APP_TOKEN",
                "GLPI_AUTH_BASIC",
                "GLPI_WEBHOOK_KEY",
                "FISCAL_WEBHOOK_KEY",
                "IA_LOCAL_API_TOKEN",
                "TEST_AUTO_REVIEW_TOKEN",
                "GEMINI_API_KEY",
            )
        ),
        "integration secrets are absent from the n8n main process",
    )
    check("N8N_BLOCK_ENV_ACCESS_IN_NODE" in n8n_service_block, "n8n blocks node environment access")
    check("N8N_RUNNERS_MODE=${N8N_RUNNERS_MODE:-external}" in n8n_service_block, "n8n uses external task runners")
    check("FILA_IA_RUN_SCOPE" in n8n_env, "environment template defines calibration queue scope")
    check(":latest" not in n8n_compose, "n8n compose has no mutable latest images")
    check("healthcheck:" in n8n_compose, "PostgreSQL compose has a healthcheck")
    check("condition: service_healthy" in n8n_compose, "n8n waits for healthy PostgreSQL")
    check("research_backend:" in n8n_compose, "compose declares isolated research network")
    check("internal: true" in n8n_compose, "research database network is internal")

    glpi_compose = read_text(PROJECT_DIR / "glpi" / "docker-compose.yml")
    check(":latest" not in glpi_compose, "GLPI compose has no mutable latest images")
    check("healthcheck:" in glpi_compose, "MariaDB compose has a healthcheck")
    check("condition: service_healthy" in glpi_compose, "GLPI waits for healthy MariaDB")
    check("N8N_GLPI_WEBHOOK_URL" in glpi_compose, "GLPI compose declares the n8n webhook URL")
    check("N8N_GLPI_WEBHOOK_KEY" in glpi_compose, "GLPI compose declares the n8n webhook key")
    check("N8N_GLPI_WEBHOOK_RETRIES" in glpi_compose, "GLPI compose declares webhook retry attempts")
    check("N8N_GLPI_WEBHOOK_RETRY_SLEEP_MS" in glpi_compose, "GLPI compose declares webhook retry delay")
    check("glpi-ticket-fila-ia-v9" in glpi_compose, "GLPI sends new tickets to WF06")

    setup_api_token = read_text(PROJECT_DIR / "glpi" / "seed" / "setup_api_token.php")
    check(
        "require_env_value('GLPI_APP_TOKEN')" in setup_api_token
        and "require_env_value('GLPI_DB_PASSWORD')" in setup_api_token,
        "GLPI API setup requires token and database password from environment",
    )
    check(
        "Token plain" not in setup_api_token,
        "GLPI API setup never prints the application token",
    )

    for script_name in (
        "calibrar_vazao.py",
        "gerar_dataset_avaliacao.py",
        "conferir_gabarito.py",
        "gerar_diagnostico_operacional.py",
    ):
        script_text = read_text(PROJECT_DIR / "avaliacao" / "scripts" / script_name)
        check(
            "project_env" in script_text,
            f"{script_name} loads project environment configuration",
        )

    env_local = PROJECT_DIR / "n8n" / ".env.local"
    if env_local.exists():
        ok("n8n .env.local found; configured remote secrets will be validated")
    else:
        ok("n8n .env.local is optional for a local-only installation")
    public_env_values = parse_env_values(n8n_env)
    check(
        all(
            not public_env_values.get(key, "").strip()
            or public_env_values.get(key, "").strip().upper() in SECRET_PLACEHOLDERS
            for key in REMOTE_SECRET_KEYS
        ),
        f"{env_definition_path.name} contains no remote AI credential value",
    )
    check(".env.local" not in n8n_service_block, "n8n main process does not load .env.local")
    if env_local.exists():
        local_values = parse_env_values(read_text(env_local))
        invalid_secrets = invalid_configured_remote_secrets(local_values)
        check(
            not invalid_secrets,
            "configured remote AI credentials have plausible values"
            + (f" (invalid: {', '.join(invalid_secrets)})" if invalid_secrets else ""),
        )
        public_bundle = "\n".join(
            [n8n_env, n8n_compose]
            + [read_text(BASE_DIR / filename) for filename in WORKFLOW_FILES.values()]
            + [read_text(path) for path in PYTHON_FILES]
        )
        leaked = any(
            value
            and len(value) >= 16
            and value.upper() not in SECRET_PLACEHOLDERS
            and value in public_bundle
            for key, value in local_values.items()
            if key in REMOTE_SECRET_KEYS
        )
        check(not leaked, "AI credential values do not appear in builders, workflows or compose")

    credential_hits = forbidden_credential_occurrences(PUBLIC_CREDENTIAL_SCAN_FILES)
    check(
        not credential_hits,
        "public builders, workflows and scripts contain no predictable credential fallback"
        + (f" (files: {', '.join(credential_hits)})" if credential_hits else ""),
    )
    local_ai_runner = read_text(PROJECT_DIR / "local_ai" / "run_server.py")
    check(
        'os.environ["LOCAL_AI_API_TOKEN"] =' not in local_ai_runner
        and "LOCAL_AI_API_TOKEN" in local_ai_runner,
        "local_ai direct runner requires an external token and embeds no token value",
    )

    model_config_path = PROJECT_DIR / "avaliacao" / "config" / "modelos_ia_v1.json"
    check(model_config_path.exists(), "multi-model policy manifest exists")
    if model_config_path.exists():
        model_config = json.loads(read_text(model_config_path))
        models = model_config.get("models", {})
        check(
            models.get("LOCAL", {}).get("model") == "local-hybrid-v1.8.0"
            and models.get("SECONDARY", {}).get("model") == "gemini-3.5-flash",
            "multi-model policy freezes operational model roles",
        )
        check(
            model_config.get("operational_policy", {}).get("sequence")
            == ["LOCAL"]
            and model_config.get("operational_policy", {}).get("failover_enabled") is False
            and models.get("SECONDARY", {}).get("active_operational_role") is False,
            "multi-model policy freezes the LOCAL-only operational order",
        )
        check(
            models.get("LOCAL", {}).get("provider") == "local-native"
            and models.get("LOCAL", {}).get("runtime_backend") == "pytorch_fp32"
            and models.get("LOCAL", {}).get("precision") == "fp32"
            and models.get("LOCAL", {}).get("embedding_dimension") == 384
            and models.get("LOCAL", {}).get("operational_failover_member") is True,
            "multi-model policy freezes the native local PyTorch FP32 role",
        )
        check(
            model_config.get("confirmatory_policy", {}).get("one_model_per_run") is True
            and model_config.get("confirmatory_policy", {}).get("failover_enabled") is False,
            "confirmatory policy forbids model mixing and failover",
        )

    sample_plan_path = (
        PROJECT_DIR / "avaliacao" / "config" / "plano_amostral_automatizado_v4.json"
    )
    check(sample_plan_path.exists(), "automated V4 sample-size plan exists")
    if sample_plan_path.exists():
        sample_plan = json.loads(read_text(sample_plan_path))
        targets = sample_plan.get("targets", {})
        check(
            targets.get("classification_independent_cores_per_class") == 100
            and targets.get("dedup_duplicate_independent_cores") == 189
            and targets.get("dedup_hard_nonduplicate_complete_independent_cores") == 97
            and targets.get("dedup_hard_nonduplicate_critical_independent_cores") == 73,
            "automated V4 plan sizes independent semantic cores, not raw paraphrases",
        )
        check(
            sample_plan.get("scientific_result") is False
            and sample_plan.get("confirmatory_eligible") is False,
            "automated V4 plan is explicitly non-confirmatory",
        )

    prompt_manifest_path = PROJECT_DIR / "avaliacao" / "manifesto_modelo_prompts.json"
    check(prompt_manifest_path.exists(), "model/prompt manifest exists")
    if prompt_manifest_path.exists():
        prompt_manifest = json.loads(read_text(prompt_manifest_path))
        check(
            prompt_manifest.get("model") == "gemini-3.5-flash",
            "model/prompt manifest freezes Gemini 3.5 Flash",
        )
        for workflow_key, node_name, prompt_name, manifest_key in (
            ("WF02", "IA: Verificar Duplicidade", "prompt_deduplicacao_v9.1.txt", "deduplicacao"),
            ("WF03", "IA: Classificar", "prompt_classificacao_v9.1.txt", "classificacao"),
        ):
            workflow = json.loads(
                read_text(BASE_DIR / WORKFLOW_FILES[workflow_key])
            )
            node = nodes_by_name(workflow)[node_name]
            schema_name = (
                "deduplicacao_v9.1.schema.json"
                if manifest_key == "deduplicacao"
                else "classificacao_v9.1.schema.json"
            )
            parameters = node["parameters"]
            gateway_js = parameters.get("jsCode", "")
            canonical_prompt = read_text(
                PROJECT_DIR / "avaliacao" / "prompts" / prompt_name
            ).rstrip("\r\n")
            check(
                f"const PROMPT_TEMPLATE = {json.dumps(canonical_prompt, ensure_ascii=False)};" in gateway_js,
                f"{workflow_key} gateway embeds the exact canonical prompt",
            )
            digest = hashlib.sha256(canonical_prompt.encode("utf-8")).hexdigest()
            check(
                prompt_manifest.get("prompt_sha256", {}).get(manifest_key) == digest,
                f"{workflow_key} canonical prompt hash matches manifest",
            )
            canonical_schema = json.loads(
                read_text(PROJECT_DIR / "avaliacao" / "schemas" / schema_name)
            )
            check(
                node.get("type") == "n8n-nodes-base.code",
                f"{workflow_key} calls providers inside a controlled n8n Code gateway",
            )
            check(
                "generativelanguage.googleapis.com/v1beta/models/" in gateway_js,
                f"{workflow_key} gateway contains official provider endpoint",
            )
            check(
                "$env" not in gateway_js
                and "process.env" not in gateway_js
                and "local-ai-credential-proxy:8080" in gateway_js,
                f"{workflow_key} keeps secrets outside Code and uses the credential proxy",
            )
            check(
                "const roles = ['LOCAL','SECONDARY'];" in gateway_js,
                f"{workflow_key} freezes the operational failover sequence",
            )
            check(
                "const supportedRoles = [...roles];" in gateway_js
                and "role:'LOCAL', provider:'local-native'" in gateway_js
                and "requires_key:false" in gateway_js
                and "IA_LOCAL_BASE_URL" in gateway_js
                and "IA_LOCAL_TIMEOUT_MS" in gateway_js,
                f"{workflow_key} exposes an explicit native local role with optional bearer authentication",
            )
            check(
                "/v1/deduplicate" in gateway_js
                and "/v1/classify" in gateway_js
                and "?include_metadata=1" in gateway_js
                and "body:nativeLocalBody" in gateway_js,
                f"{workflow_key} calls the native structured local endpoints with scientific metadata",
            )
            check(
                "IA_OPERATIONAL_SEQUENCE" in gateway_js
                and "IA_OPERATIONAL_SEQUENCE:'LOCAL'" in gateway_js
                and "operational_sequence:operationalChain(fixedRole)" in gateway_js,
                f"{workflow_key} uses a frozen and audited LOCAL-only operational sequence",
            )
            check(
                "if (role === 'LOCAL') return ['LOCAL'];" in gateway_js
                and "['LOCAL',...roles]" not in gateway_js,
                f"{workflow_key} operational chain does not add a remote fallback",
            )
            check(
                "attempt_input_profiles" in gateway_js
                and "endpoint:item.endpoint" in gateway_js,
                f"{workflow_key} audits local endpoint and per-attempt input profile",
            )
            check(
                "result_v9" in gateway_js
                and "scientific_metadata" in gateway_js
                and "? selected.result_v9" in gateway_js,
                f"{workflow_key} separates canonical V9 output from local scientific metadata",
            )
            check(
                all(marker in gateway_js for marker in (
                    "validateLocalRuntime",
                    "LOCAL_AI_EMBED_BACKEND",
                    "pytorch_fp32",
                    "granite_embedding_pytorch_fp32",
                    "LOCAL_AI_EMBED_MODEL_REVISION",
                    "Number(embedding.dimension) !== 384",
                    "LOCAL_RUNTIME_MISMATCH",
                    "LOCAL_DEVELOPMENT_FALLBACK",
                )),
                f"{workflow_key} accepts local decisions only from frozen PyTorch FP32 Granite runtime",
            )
            check(
                "application/json" in gateway_js
                and "responseJsonSchema" in gateway_js,
                f"{workflow_key} requests structured JSON from providers",
            )
            check(
                (
                    "const RESPONSE_SCHEMA = "
                    + json.dumps(canonical_schema, ensure_ascii=False, separators=(",", ":"))
                    + ";"
                ) in gateway_js,
                f"{workflow_key} gateway embeds exact canonical JSON Schema",
            )
            check(
                "IA_GENERATION_SEED" in gateway_js,
                f"{workflow_key} freezes generation seed through environment",
            )
            check(
                "candidateCount" not in gateway_js
                and "thinkingConfig = {thinkingLevel:'MEDIUM'}" in gateway_js,
                f"{workflow_key} follows Gemini 3.5 generation parameter contract",
            )
            check(
                "failoverAllowed = failoverRequested && !experimental && !benchmark" in gateway_js,
                f"{workflow_key} disables fallback for every experimental/benchmark run",
            )
            check(
                "const requestedRoleValid = supportedRoles.includes(requestedRole)" in gateway_js
                and "const frozenModelDeclared = Boolean(expectedModel)" in gateway_js
                and "EXPERIMENT_ROLE_INVALID" in gateway_js
                and "EXPERIMENT_MODEL_NOT_FROZEN" in gateway_js,
                f"{workflow_key} fails closed when a research run omits its frozen role/model",
            )
            check(
                all(marker in gateway_js for marker in (
                    "parseRetryAfter", "retry-after", "http_status",
                    "retry_after_seconds", "retryable", "error_type",
                )),
                f"{workflow_key} gateway exposes transport retry metadata",
            )
            schema_digest = hashlib.sha256(
                json.dumps(
                    canonical_schema, ensure_ascii=False, sort_keys=True
                ).encode("utf-8")
            ).hexdigest()
            check(
                prompt_manifest.get("schema_sha256", {}).get(manifest_key)
                == schema_digest,
                f"{workflow_key} canonical schema hash matches manifest",
            )

    requirements = PROJECT_DIR / "requirements.txt"
    check(requirements.exists(), "requirements.txt exists")
    if requirements.exists():
        lines = [
            line.strip() for line in read_text(requirements).splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        check(
            all("==" in line for line in lines),
            "all Python dependencies are exactly pinned",
        )

    hook_php = read_text(PROJECT_DIR / "glpi" / "plugins" / "n8nwebhook" / "hook.php")
    check("N8N_GLPI_WEBHOOK_RETRIES" in hook_php, "GLPI webhook plugin reads retry attempts")
    check("usleep" in hook_php, "GLPI webhook plugin waits between retry attempts")


def validate_prompt_manifest_sync() -> None:
    """Fail closed when generated gateways and the frozen manifest drift apart."""
    synchronizer = PROJECT_DIR / "avaliacao" / "scripts" / "sincronizar_manifesto.py"
    result = subprocess.run(
        [sys.executable, str(synchronizer), "--check"],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    detail = (result.stdout or result.stderr).strip()
    check(
        result.returncode == 0,
        "model, prompt, schema, gateway and workflow hashes match the frozen manifest"
        + (f" ({detail})" if result.returncode else ""),
    )


def main() -> int:
    validate_python()
    workflows = load_workflows()
    validate_json_structure(workflows)
    validate_v9_rules(workflows)
    validate_prompt_manifest_sync()
    validate_schema_and_config()

    if failures:
        print()
        print(f"Static validation failed with {len(failures)} issue(s).")
        return 1
    print()
    print("Static validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
