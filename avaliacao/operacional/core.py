from __future__ import annotations

import concurrent.futures
import contextlib
import hashlib
import http.server
import json
import math
import os
import socket
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_PATH = Path(__file__).with_name("politica_operacional_v1.json")
ALLOWED_LOAD_PATHS = {"/health", "/healthz", "/v1/classify", "/v1/deduplicate", "/v1/embed"}
LOCAL_DOCKER_CONTEXT = "desktop-linux"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} deve conter um objeto JSON")
    return value


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    policy = load_json(path)
    required = {
        "schema_version",
        "status",
        "safe_defaults",
        "slo",
        "drift",
        "monitoring",
        "failure_policy",
        "required_backup_tables",
        "evidence_labels",
    }
    missing = sorted(required - set(policy))
    if missing:
        raise ValueError(f"Política operacional incompleta: {', '.join(missing)}")
    if policy["status"] != "PROPOSTA_NAO_APROVADA":
        raise ValueError("A política operacional v1 deve permanecer identificada como proposta não aprovada")
    for section in ("slo", "drift", "monitoring"):
        if policy[section].get("approval_status") != "PROPOSTO_NAO_APROVADO":
            raise ValueError(f"{section} deve permanecer explicitamente marcado como proposto e não aprovado")
    if policy["monitoring"].get("automatic_retraining_allowed") is not False:
        raise ValueError("Monitoramento não pode autorizar retreinamento automático")
    safe = policy["safe_defaults"]
    if not bool(safe.get("loopback_only")):
        raise ValueError("A política operacional deve restringir carga técnica ao loopback")
    for field in ("max_load_requests", "max_concurrency", "max_duration_seconds"):
        if float(safe.get(field, 0)) <= 0:
            raise ValueError(f"Limite de segurança inválido: {field}")
    drift = policy["drift"]
    if not 0 <= float(drift["jensen_shannon_warning"]) < float(drift["jensen_shannon_stop"]):
        raise ValueError("Limiares Jensen-Shannon devem obedecer warning < stop")
    if not 0 <= float(drift["psi_warning"]) < float(drift["psi_stop"]):
        raise ValueError("Limiares PSI devem obedecer warning < stop")
    for dependency in ("glpi", "local_ai", "postgresql"):
        configured = policy["failure_policy"].get(f"{dependency}_unavailable")
        if not isinstance(configured, dict) or configured.get("automatic_decision_allowed") is not False:
            raise ValueError(f"Política fail-closed ausente ou insegura para {dependency}")
    return policy


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"").strip("'")
    return values


def project_env(root: Path = ROOT) -> dict[str, str]:
    merged: dict[str, str] = {}
    for path in (root / "glpi" / ".env", root / "n8n" / ".env", root / "n8n" / ".env.local"):
        merged.update(parse_env_file(path))
    merged.update({key: value for key, value in os.environ.items() if value})
    return merged


def check(identifier: str, status: str, summary: str, **evidence: Any) -> dict[str, Any]:
    if status not in {"PASS", "FAIL", "WARN", "INDETERMINATE", "NOT_RUN"}:
        raise ValueError(f"Status inválido: {status}")
    return {
        "id": identifier,
        "status": status,
        "summary": summary,
        "evidence": evidence,
    }


def validate_loopback_url(url: str, *, allowed_paths: set[str] | None = None) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Somente URLs HTTP(S) são aceitas")
    host = (parsed.hostname or "").lower()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("O alvo deve ser loopback; hosts remotos são bloqueados")
    if parsed.username or parsed.password:
        raise ValueError("Credenciais não podem ser incluídas na URL")
    if parsed.query or parsed.fragment:
        raise ValueError("Query string e fragmento são bloqueados no probe de carga")
    if allowed_paths is not None and parsed.path not in allowed_paths:
        raise ValueError(f"Endpoint não permitido para carga segura: {parsed.path}")
    return url


def percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _http_request(
    url: str,
    *,
    timeout_seconds: float,
    token: str = "",
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    data = None
    method = "GET"
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        method = "POST"
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    started = time.perf_counter()
    status = 0
    error = None
    body: dict[str, Any] | None = None
    try:
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = int(response.status)
            raw = response.read(1024 * 1024)
            if raw and "json" in response.headers.get("Content-Type", "").lower():
                value = json.loads(raw.decode("utf-8"))
                body = value if isinstance(value, dict) else None
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        error = f"HTTP_{status}"
    except (TimeoutError, socket.timeout):
        error = "TIMEOUT"
    except urllib.error.URLError as exc:
        reason = exc.reason
        error = "TIMEOUT" if isinstance(reason, (TimeoutError, socket.timeout)) else "UNREACHABLE"
    except (OSError, ValueError, json.JSONDecodeError):
        error = "INVALID_OR_UNREACHABLE"
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {"status": status, "latency_ms": elapsed_ms, "error": error, "body": body}


def bounded_load_probe(
    *,
    url: str,
    requests_count: int,
    concurrency: int,
    timeout_seconds: float,
    token: str = "",
    payload: Mapping[str, Any] | None = None,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    policy = dict(policy or load_policy())
    limits = policy["safe_defaults"]
    validate_loopback_url(url, allowed_paths=ALLOWED_LOAD_PATHS)
    maximum_requests = int(limits["max_load_requests"])
    maximum_concurrency = int(limits["max_concurrency"])
    maximum_duration = float(limits["max_duration_seconds"])
    if not 1 <= requests_count <= maximum_requests:
        raise ValueError(f"requests_count deve estar entre 1 e {maximum_requests}")
    if not 1 <= concurrency <= maximum_concurrency:
        raise ValueError(f"concurrency deve estar entre 1 e {maximum_concurrency}")
    if timeout_seconds <= 0 or timeout_seconds * math.ceil(requests_count / concurrency) > maximum_duration:
        raise ValueError("Plano excede a duração máxima de segurança")

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                _http_request,
                url,
                timeout_seconds=timeout_seconds,
                token=token,
                payload=payload,
            )
            for _ in range(requests_count)
        ]
        rows = [future.result() for future in futures]
    elapsed = time.perf_counter() - started
    latencies = [float(row["latency_ms"]) for row in rows]
    statuses = Counter(str(row["status"]) for row in rows)
    errors = Counter(str(row["error"]) for row in rows if row["error"])
    successes = sum(1 for row in rows if 200 <= int(row["status"]) < 300)
    saturation = sum(1 for row in rows if int(row["status"]) == 429)
    server_errors = sum(1 for row in rows if int(row["status"]) >= 500)
    return {
        "evidence_status": policy["evidence_labels"]["load_probe"],
        "scientific_result": False,
        "collected_at": utc_now(),
        "target": url,
        "requests": requests_count,
        "concurrency": concurrency,
        "duration_seconds": elapsed,
        "throughput_requests_second": requests_count / elapsed if elapsed else None,
        "success_rate": successes / requests_count,
        "saturation_rate": saturation / requests_count,
        "server_error_rate": server_errors / requests_count,
        "status_counts": dict(statuses),
        "error_counts": dict(errors),
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
            "maximum": max(latencies),
        },
        "interpretation_limit": (
            "Cenário técnico limitado no loopback; não estima disponibilidade mensal, "
            "desempenho multiusuário institucional nem eficácia científica."
        ),
    }


def _normalise_distribution(values: Mapping[str, int | float], epsilon: float) -> dict[str, float]:
    clean = {str(key): max(0.0, float(value)) for key, value in values.items()}
    if not clean:
        raise ValueError("Distribuição vazia")
    adjusted = {key: value + epsilon for key, value in clean.items()}
    total = sum(adjusted.values())
    return {key: value / total for key, value in adjusted.items()}


def jensen_shannon_divergence(
    reference: Mapping[str, int | float],
    current: Mapping[str, int | float],
    *,
    epsilon: float = 1e-6,
) -> float:
    keys = sorted(set(reference) | set(current))
    p = _normalise_distribution({key: reference.get(key, 0.0) for key in keys}, epsilon)
    q = _normalise_distribution({key: current.get(key, 0.0) for key in keys}, epsilon)
    midpoint = {key: (p[key] + q[key]) / 2.0 for key in keys}

    def kl(left: Mapping[str, float], right: Mapping[str, float]) -> float:
        return sum(left[key] * math.log(left[key] / right[key], 2) for key in keys)

    return 0.5 * kl(p, midpoint) + 0.5 * kl(q, midpoint)


def population_stability_index(
    reference_bins: Sequence[int | float],
    current_bins: Sequence[int | float],
    *,
    epsilon: float = 1e-6,
) -> float:
    if len(reference_bins) != len(current_bins) or not reference_bins:
        raise ValueError("Histogramas PSI devem ter o mesmo número de bins")
    ref_total = sum(max(0.0, float(value)) for value in reference_bins)
    cur_total = sum(max(0.0, float(value)) for value in current_bins)
    if ref_total <= 0 or cur_total <= 0:
        raise ValueError("Histogramas PSI precisam de observações")
    value = 0.0
    for reference, current in zip(reference_bins, current_bins, strict=True):
        p = max(float(reference) / ref_total, epsilon)
        q = max(float(current) / cur_total, epsilon)
        value += (q - p) * math.log(q / p)
    return value


def evaluate_drift(
    reference: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    policy = dict(policy or load_policy())
    thresholds = policy["drift"]
    ref_n = int(reference.get("sample_size", 0))
    cur_n = int(current.get("sample_size", 0))
    if ref_n < int(thresholds["minimum_reference_sample_size"]) or cur_n < int(
        thresholds["minimum_current_sample_size"]
    ):
        return {
            "status": "INSUFFICIENT_DATA",
            "sample_size": {"reference": ref_n, "current": cur_n},
            "scientific_result": False,
            "automatic_stop_enforced": False,
            "enforcement_scope": "READ_ONLY_DIAGNOSTIC_NO_RUNTIME_ACTUATION",
            "checks": [],
        }

    checks: list[dict[str, Any]] = []
    epsilon = float(thresholds["zero_probability_epsilon"])
    categorical_reference = reference.get("categorical", {})
    categorical_current = current.get("categorical", {})
    for name in sorted(set(categorical_reference) & set(categorical_current)):
        value = jensen_shannon_divergence(
            categorical_reference[name], categorical_current[name], epsilon=epsilon
        )
        status = (
            "STOP"
            if value >= float(thresholds["jensen_shannon_stop"])
            else "WARN"
            if value >= float(thresholds["jensen_shannon_warning"])
            else "PASS"
        )
        checks.append({"feature": name, "metric": "jensen_shannon", "value": value, "status": status})

    numeric_reference = reference.get("numeric_histograms", {})
    numeric_current = current.get("numeric_histograms", {})
    for name in sorted(set(numeric_reference) & set(numeric_current)):
        ref_bins, cur_bins = numeric_reference[name], numeric_current[name]
        if not ref_bins or not cur_bins or sum(ref_bins) <= 0 or sum(cur_bins) <= 0:
            checks.append({"feature": name, "metric": "psi", "value": None, "status": "INSUFFICIENT_DATA"})
            continue
        value = population_stability_index(
            numeric_reference[name], numeric_current[name], epsilon=epsilon
        )
        status = (
            "STOP"
            if value >= float(thresholds["psi_stop"])
            else "WARN"
            if value >= float(thresholds["psi_warning"])
            else "PASS"
        )
        checks.append({"feature": name, "metric": "psi", "value": value, "status": status})

    if not checks:
        return {
            "status": "INCOMPATIBLE_SNAPSHOTS",
            "sample_size": {"reference": ref_n, "current": cur_n},
            "scientific_result": False,
            "automatic_stop_enforced": False,
            "enforcement_scope": "READ_ONLY_DIAGNOSTIC_NO_RUNTIME_ACTUATION",
            "checks": [],
            "interpretation_limit": (
                "Os snapshots não possuem variáveis comparáveis em comum; não é permitido "
                "interpretar a ausência de checks como ausência de drift."
            ),
        }
    final = "STOP" if any(row["status"] == "STOP" for row in checks) else "WARN" if any(
        row["status"] == "WARN" for row in checks
    ) else "INSUFFICIENT_DATA" if any(row["status"] == "INSUFFICIENT_DATA" for row in checks) else "PASS"
    return {
        "status": final,
        "sample_size": {"reference": ref_n, "current": cur_n},
        "scientific_result": False,
        "stop_requested": final == "STOP",
        "automatic_stop_enforced": False,
        "enforcement_scope": "READ_ONLY_DIAGNOSTIC_NO_RUNTIME_ACTUATION",
        "checks": checks,
        "interpretation_limit": (
            "Drift detecta mudança de distribuição; não demonstra queda de acurácia. "
            "STOP indica que o limite de parada foi atingido; esta avaliação e o coletor "
            "somente leem dados e não aplicam bloqueio automático no runtime. "
            "Não há autorização para retreinamento automático."
        ),
    }


def evaluate_slo(metrics: Mapping[str, Any], policy: Mapping[str, Any] | None = None) -> dict[str, Any]:
    policy = dict(policy or load_policy())
    thresholds = policy["slo"]
    checks: list[dict[str, Any]] = []

    def lower(name: str, actual: Any, target: float) -> None:
        if actual is None:
            checks.append({"metric": name, "status": "INSUFFICIENT_DATA", "target": target})
        else:
            value = float(actual)
            checks.append({"metric": name, "status": "PASS" if value >= target else "FAIL", "value": value, "target": target})

    def upper(name: str, actual: Any, target: float) -> None:
        if actual is None:
            checks.append({"metric": name, "status": "INSUFFICIENT_DATA", "target": target})
        else:
            value = float(actual)
            checks.append({"metric": name, "status": "PASS" if value <= target else "FAIL", "value": value, "target": target})

    for component, target in thresholds["component_availability_minimum"].items():
        lower(f"availability.{component}", metrics.get("availability", {}).get(component), float(target))
    upper("local_ai.inference_p95_ms", metrics.get("local_ai_inference_p95_ms"), float(thresholds["local_ai_inference_p95_ms_maximum"]))
    upper("queue.wait_p95_seconds", metrics.get("queue_wait_p95_seconds"), float(thresholds["queue_wait_p95_seconds_maximum"]))
    upper("dlq.open", metrics.get("open_dead_letters"), float(thresholds["open_dead_letters_maximum"]))
    upper("technical_error_rate", metrics.get("technical_error_rate"), float(thresholds["technical_error_rate_maximum"]))
    upper("critical_automatic_errors", metrics.get("critical_automatic_error_count"), float(thresholds["critical_automatic_error_count_maximum"]))
    upper("rollback.recovery_minutes", metrics.get("rollback_recovery_minutes"), float(thresholds["rollback_recovery_minutes_maximum"]))
    upper("backup.restore_age_hours", metrics.get("backup_restore_age_hours"), float(thresholds["backup_restore_age_hours_maximum"]))
    if any(row["status"] == "FAIL" for row in checks):
        status = "FAIL"
    elif any(row["status"] == "INSUFFICIENT_DATA" for row in checks):
        status = "INSUFFICIENT_DATA"
    else:
        status = "PASS"
    return {
        "status": status,
        "policy_status": policy["status"],
        "institutionally_approved": False,
        "checks": checks,
        "scientific_result": False,
        "interpretation_limit": (
            "Os limiares são uma proposta técnica pré-registrada. PASS não equivale a aceite "
            "institucional, certificação de produção ou disponibilidade mensal comprovada."
        ),
    }


def collect_static_audit(root: Path = ROOT) -> dict[str, Any]:
    n8n_compose = (root / "n8n" / "docker-compose.yml").read_text(encoding="utf-8")
    n8n_env_example = (root / "n8n" / ".env.example").read_text(encoding="utf-8")
    glpi_compose = (root / "glpi" / "docker-compose.yml").read_text(encoding="utf-8")
    workflow_dir = root / "n8n" / "workflows" / "Versão9"
    wf05 = load_json(workflow_dir / "V9-WF05-Metricas.json")
    wf05_queries = [
        str(node.get("parameters", {}).get("query", ""))
        for node in wf05.get("nodes", [])
        if isinstance(node, dict)
    ]
    runtime_ddl_tokens = sorted(
        {
            token
            for token in ("CREATE TABLE", "ALTER TABLE", "CREATE OR REPLACE VIEW", "DROP TABLE", "TRUNCATE ")
            if any(token in query.upper() for query in wf05_queries)
        }
    )
    workflow_payloads = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(workflow_dir.glob("V9-WF*.json"))
    )
    prompt_literal = "{{ Number($env.IA_CONFIANCA_MINIMA || 0.65) }}"
    executable_env_payloads = workflow_payloads.replace(prompt_literal, "")
    executable_dollar_env_count = executable_env_payloads.count("$env")
    runner_config = load_json(root / "n8n" / "task-runners" / "n8n-task-runners.json")
    runner_allowed = {
        str(name)
        for runner in runner_config.get("task-runners", [])
        for name in runner.get("allowed-env", [])
    }
    application_secret_names = {
        "GEMINI_API_KEY",
        "GEMINI_API_KEY_SECONDARY",
        "GLPI_APP_TOKEN",
        "GLPI_AUTH_BASIC",
        "GLPI_WEBHOOK_KEY",
        "IA_LOCAL_API_TOKEN",
        "TEST_AUTO_REVIEW_TOKEN",
    }
    allowed_secret_overlap = sorted(runner_allowed & application_secret_names)
    direct_secret_access = sorted(
        name for name in application_secret_names if f"process.env.{name}" in workflow_payloads
    )
    all_compose = n8n_compose + "\n" + glpi_compose
    checks = [
        check(
            "network.loopback_ports",
            "PASS" if "127.0.0.1:${N8N_PORT" in n8n_compose and "127.0.0.1:${GLPI_HTTP_PORT" in glpi_compose else "FAIL",
            "Portas HTTP canônicas devem permanecer vinculadas ao loopback.",
        ),
        check(
            "supply_chain.image_digests",
            "PASS" if all("@sha256:" in line for line in all_compose.splitlines() if line.strip().startswith("image:")) else "FAIL",
            "Todas as imagens declaradas devem estar congeladas por digest.",
        ),
        check(
            "postgres.healthcheck",
            "PASS" if "pg_isready" in n8n_compose else "FAIL",
            "PostgreSQL possui healthcheck explícito.",
        ),
        check(
            "n8n.healthcheck",
            "PASS" if "healthcheck:" in n8n_compose[n8n_compose.find("  n8n:"):n8n_compose.find("  mailpit:")] else "FAIL",
            "O container n8n deve possuir healthcheck próprio no Compose.",
        ),
        check(
            "glpi.healthcheck",
            "PASS" if "curl -fsS -o /dev/null --max-time 5 http://127.0.0.1/" in glpi_compose else "FAIL",
            "O container GLPI deve possuir healthcheck HTTP próprio.",
        ),
        check(
            "n8n.code_node_sandbox",
            "PASS" if "N8N_DISABLE_SANDBOX=${N8N_DISABLE_SANDBOX:-false}" in n8n_compose else "FAIL",
            "Sandbox de Code nodes deve ter default seguro no Compose.",
        ),
        check(
            "n8n.environment_access",
            "PASS" if "N8N_BLOCK_ENV_ACCESS_IN_NODE=${N8N_BLOCK_ENV_ACCESS_IN_NODE:-true}" in n8n_compose else "FAIL",
            "Acesso a variáveis de ambiente por nodes deve ter default bloqueado.",
        ),
        check(
            "n8n.workflow_env_migration",
            "PASS"
            if not executable_dollar_env_count
            and not direct_secret_access
            and not allowed_secret_overlap
            and "N8N_RUNNERS_MODE=${N8N_RUNNERS_MODE:-external}" in n8n_compose
            and "read_only: true" in n8n_compose
            else "FAIL",
            "Code nodes usam runner externo com allowlist sem segredos; $env executável é proibido.",
            executable_dollar_env_references=executable_dollar_env_count,
            direct_secret_access=direct_secret_access,
            runner_secret_allowlist_overlap=allowed_secret_overlap,
        ),
        check(
            "postgres.runtime_not_bootstrap_role",
            "PASS" if "POSTGRES_USER=${POSTGRES_BOOTSTRAP_USER:?" in n8n_compose else "FAIL",
            "O usuário de bootstrap/migração deve ser distinto da credencial runtime do n8n.",
        ),
        check(
            "workflow.runtime_ddl_separation",
            "FAIL" if runtime_ddl_tokens else "PASS",
            "O JSON executável do WF05 deve conter somente readiness e DML; DDL fica em database/init_v9.sql.",
            runtime_ddl_tokens=runtime_ddl_tokens,
        ),
        check(
            "test_flags.safe_defaults",
            "PASS" if "TEST_MODE=false" in n8n_env_example and "TEST_AUTO_HUMAN_CONFIRMATION=false" in n8n_env_example else "FAIL",
            "Flags de teste devem iniciar desligadas no template, sem serem injetadas no processo principal.",
        ),
    ]
    final = "FAIL" if any(item["status"] == "FAIL" for item in checks) else "WARN" if any(
        item["status"] in {"WARN", "INDETERMINATE"} for item in checks
    ) else "PASS"
    return {
        "status": final,
        "evidence_status": "STATIC_CONFIGURATION_AUDIT",
        "scientific_result": False,
        "collected_at": utc_now(),
        "checks": checks,
    }


def run_command_read_only(command: Sequence[str], timeout_seconds: float = 15.0) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"returncode": None, "stdout": "", "stderr": type(exc).__name__}


def collect_live_point_in_time(root: Path = ROOT) -> dict[str, Any]:
    env = project_env(root)
    token = env.get("IA_LOCAL_API_TOKEN", "")
    glpi_configured = urlparse(
        env.get("GLPI_API_URL", "http://host.docker.internal:9080/apirest.php")
    )
    glpi_port = glpi_configured.port or (443 if glpi_configured.scheme == "https" else 80)
    n8n_configured = urlparse(
        env.get("N8N_PUBLIC_BASE_URL", env.get("N8N_BASE_URL", "http://127.0.0.1:5678"))
    )
    n8n_port = n8n_configured.port or (443 if n8n_configured.scheme == "https" else 80)
    local_configured = urlparse(
        env.get("IA_LOCAL_BASE_URL", "http://host.docker.internal:8090")
    )
    local_port = local_configured.port or (443 if local_configured.scheme == "https" else 80)
    endpoints = {
        "local_ai": (f"http://127.0.0.1:{local_port}/health", token),
        "n8n": (f"http://127.0.0.1:{n8n_port}/healthz", ""),
        "glpi": (f"http://127.0.0.1:{glpi_port}/", ""),
    }
    probes: dict[str, Any] = {}
    for name, (url, endpoint_token) in endpoints.items():
        probes[name] = _http_request(url, timeout_seconds=3.0, token=endpoint_token)
        probes[name].pop("body", None)

    docker = run_command_read_only(
        [
            "docker",
            "--context",
            LOCAL_DOCKER_CONTEXT,
            "inspect",
            "--format",
            "{{.Name}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
            "glpi",
            "glpi-db",
            "glpi-dedup-db",
            "n8n",
        ]
    )
    container_rows = [row for row in docker["stdout"].splitlines() if row]
    expected_containers = {"glpi", "glpi-db", "glpi-dedup-db", "n8n"}
    container_states: dict[str, tuple[str, str]] = {}
    for row in container_rows:
        parts = row.lstrip("/").split("|", 2)
        if len(parts) == 3:
            container_states[parts[0]] = (parts[1], parts[2])
    docker_ok = (
        docker["returncode"] == 0
        and set(container_states) == expected_containers
        and all(
            status == "running" and health in {"healthy", "none"}
            for status, health in container_states.values()
        )
    )
    http_ok = all(200 <= int(row["status"]) < 300 for row in probes.values())
    return {
        "status": "PASS" if http_ok and docker_ok else "FAIL",
        "evidence_status": "POINT_IN_TIME_TECHNICAL_EVIDENCE",
        "scientific_result": False,
        "collected_at": utc_now(),
        "http_probes": probes,
        "containers": container_rows,
        "docker_healthy": docker_ok,
        "docker_probe_error": docker["stderr"] or None,
        "interpretation_limit": "Uma coleta pontual não mede disponibilidade na janela do SLO.",
    }


def snapshot_from_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    predictions: Counter[str] = Counter()
    stages: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    confidence_bins = [0] * 10
    for row in rows:
        predictions[str(row.get("predicao") or "SEM_PREDICAO")] += 1
        stages[str(row.get("etapa") or "SEM_ETAPA")] += 1
        outcomes["ERRO" if row.get("erro_ia") else "VALIDA"] += 1
        confidence = row.get("confianca")
        if confidence is not None:
            value = min(0.999999, max(0.0, float(confidence)))
            confidence_bins[int(value * 10)] += 1
    return {
        "sample_size": len(rows),
        "categorical": {
            "predicao": dict(predictions),
            "etapa": dict(stages),
            "resultado_tecnico": dict(outcomes),
        },
        "numeric_histograms": {"confianca_10_bins": confidence_bins},
    }


def failure_action(policy: Mapping[str, Any], dependency: str, detected_failure: str) -> dict[str, Any]:
    key = f"{dependency}_unavailable"
    configured = policy["failure_policy"].get(key)
    if configured is None:
        raise ValueError(f"Dependência sem política de falha: {dependency}")
    return {
        "dependency": dependency,
        "detected_failure": detected_failure,
        "required_action": configured["required_action"],
        "automatic_decision_allowed": bool(configured["automatic_decision_allowed"]),
        "status": "PASS" if not configured["automatic_decision_allowed"] else "FAIL",
    }


def failure_harness(policy: Mapping[str, Any] | None = None) -> dict[str, Any]:
    policy = dict(policy or load_policy())
    scenarios = [
        failure_action(policy, "glpi", "HTTP_503"),
        failure_action(policy, "local_ai", "TIMEOUT"),
        failure_action(policy, "postgresql", "CONNECTION_REFUSED"),
    ]
    return {
        "status": "PASS" if all(row["status"] == "PASS" for row in scenarios) else "FAIL",
        "evidence_status": policy["evidence_labels"]["isolated_harness"],
        "scientific_result": False,
        "collected_at": utc_now(),
        "scenarios": scenarios,
        "interpretation_limit": (
            "Valida a política fail-closed em memória. Não prova que o workflow vivo "
            "executa o rollback; isso exige drill E2E em stack Docker isolada."
        ),
    }


class _QuietHandler(http.server.BaseHTTPRequestHandler):
    response_status = 503
    response_delay_seconds = 0.0

    def do_GET(self) -> None:  # noqa: N802 - assinatura exigida pela biblioteca padrão
        if self.response_delay_seconds:
            time.sleep(self.response_delay_seconds)
        with contextlib.suppress(BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.send_response(self.response_status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"simulated_failure"}')

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


@contextlib.contextmanager
def _isolated_http_server(*, status: int, delay_seconds: float = 0.0) -> Iterable[str]:
    handler = type(
        "IsolatedFailureHandler",
        (_QuietHandler,),
        {"response_status": status, "response_delay_seconds": delay_seconds},
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}/health"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def isolated_failure_simulation(policy: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Exercita falhas somente em endpoints efêmeros no loopback.

    Nenhuma chamada é enviada ao GLPI, à IA ou ao PostgreSQL vivos. O objetivo é
    verificar detecção técnica e o mapeamento fail-closed, não a reação E2E dos
    workflows publicados.
    """

    policy = dict(policy or load_policy())
    with _isolated_http_server(status=503) as glpi_url:
        glpi_probe = _http_request(glpi_url, timeout_seconds=0.5)
    with _isolated_http_server(status=200, delay_seconds=0.15) as ai_url:
        ai_probe = _http_request(ai_url, timeout_seconds=0.03)

    refused_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    refused_socket.bind(("127.0.0.1", 0))
    _, refused_port = refused_socket.getsockname()
    refused_socket.close()
    postgresql_started = time.perf_counter()
    postgresql_code = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    postgresql_code.settimeout(0.2)
    try:
        connect_code = postgresql_code.connect_ex(("127.0.0.1", refused_port))
    finally:
        postgresql_code.close()
    postgresql_latency_ms = (time.perf_counter() - postgresql_started) * 1000.0

    observed = {
        "glpi": "HTTP_503" if int(glpi_probe["status"]) == 503 else "UNEXPECTED",
        "local_ai": "TIMEOUT" if ai_probe["error"] == "TIMEOUT" else "UNEXPECTED",
        "postgresql": "CONNECTION_REFUSED" if connect_code != 0 else "UNEXPECTED",
    }
    scenarios = [
        {
            **failure_action(policy, dependency, detected),
            "isolated_observation": (
                glpi_probe
                if dependency == "glpi"
                else ai_probe
                if dependency == "local_ai"
                else {"connect_ex": connect_code, "latency_ms": postgresql_latency_ms}
            ),
            "isolated_target_only": True,
        }
        for dependency, detected in observed.items()
    ]
    observed_as_expected = all(row["detected_failure"] != "UNEXPECTED" for row in scenarios)
    return {
        "status": "PASS" if observed_as_expected and all(row["status"] == "PASS" for row in scenarios) else "FAIL",
        "evidence_status": policy["evidence_labels"]["isolated_harness"],
        "scientific_result": False,
        "collected_at": utc_now(),
        "live_services_touched": False,
        "scenarios": scenarios,
        "interpretation_limit": (
            "Simulação técnica em loopback efêmero. Não comprova failover ou rollback do "
            "workflow vivo e não autoriza indisponibilizar dependências reais."
        ),
    }


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
