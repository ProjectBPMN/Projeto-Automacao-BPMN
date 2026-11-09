"""Validação técnica sintética e isolada do caminho WF06 -> WF02 -> WF03.

O modo padrão é somente leitura. A execução mutante exige ``--executar`` e uma
frase de confirmação exata. O resultado é evidência técnica, não uma estimativa
confirmatória de eficácia do modelo.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Iterator
from urllib.parse import urlsplit

import requests


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import calibrar_vazao as calibration  # noqa: E402
import conferir_gabarito as database  # noqa: E402
from isolamento_experimentos import serialized_experiment  # noqa: E402
from project_env import configured_value, load_project_env  # noqa: E402


load_project_env()

PROTOCOL_VERSION = "e2e-pipeline-local-v1"
EXPECTED_MODEL = "local-hybrid-v1.8.0"
TEST_PREFIX = "[TESTE_AUTOMATIZADO_E2E_WF06_LOCAL_V18]"
RUN_RE = re.compile(r"^VALIDACAO-WF06-E2E-[0-9]{8}T[0-9]{12}Z$")
MUTATION_CONFIRMATION = "EXECUTAR_E2E_SINTETICO_WF06_LOCAL_V18"
QUEUE_LOCK_KEY = 9062026
WF06_WORKFLOW_ID = "ZpQ0H9uV9Fila06"
LOCAL_DOCKER_CONTEXT = "desktop-linux"
LOCAL_DOCKER_ENDPOINT_WINDOWS = "npipe:////./pipe/dockerDesktopLinuxEngine"
EXPECTED_CLASSIFICATION = "TRIAGEM_MANUAL"
EXPECTED_TERMINAL = "TRIAGEM_MANUAL"
ACTIVE_QUEUE_STATES = (
    "PENDENTE_FILA_IA",
    "FILA_IA_LIBERADA",
    "CLASSIFICANDO_DUP",
    "CLASSIFICANDO",
    "AGUARDANDO_FILA_CLASSIFICACAO",
)
PROFILE_KEYS = (
    "FILA_IA_RUN_SCOPE",
    "FILA_IA_LOTE_TAMANHO",
    "FILA_IA_INTERVALO_SEGUNDOS",
    "FILA_IA_INGRESS_GRACE_SEGUNDOS",
    "FILA_IA_LEASE_SEGUNDOS",
    "IA_MODEL_LOCAL",
    "IA_MODEL_VERSION",
    "IA_FIXED_MODEL_ROLE",
    "IA_OPERATIONAL_SEQUENCE",
    "IA_FAILOVER_ENABLED",
    "IA_EXECUTION_MODE",
    "IA_GENERATION_PROFILE",
    "TEST_MODE",
    "TEST_AUTO_HUMAN_CONFIRMATION",
)
WORKFLOW_FILES = (
    "V9-WF02-Triagem.json",
    "V9-WF03-Classificacao.json",
    "V9-WF06-Fila-IA.json",
)
SAFE_TITLE = f"{TEST_PREFIX} Falha de senha no sistema acadêmico"
SAFE_CONTENT = (
    f"{TEST_PREFIX} Caso exclusivamente sintético; não atender. "
    "O usuário não consegue fazer login por erro de senha no sistema acadêmico. "
    "Não existe defeito físico, obra ou manutenção predial neste chamado."
)


def scalar(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): scalar(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [scalar(item) for item in value]
    return value


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def make_run_id(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    return "VALIDACAO-WF06-E2E-" + current.astimezone(timezone.utc).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )


def validate_run_id(run_id: str) -> str:
    value = str(run_id or "").strip()
    if not RUN_RE.fullmatch(value):
        raise ValueError("run_id não pertence ao namespace sintético WF06 E2E")
    return value


def workflow_artifacts() -> dict[str, dict[str, Any]]:
    directory = ROOT / "n8n" / "workflows" / "Versão9"
    result: dict[str, dict[str, Any]] = {}
    for filename in WORKFLOW_FILES:
        path = directory / filename
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"))
        if not payload.get("id") or not payload.get("name") or not payload.get("active"):
            raise RuntimeError(f"Workflow canônico inativo ou inválido: {filename}")
        result[filename] = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "workflow_id": str(payload["id"]),
            "workflow_name": str(payload["name"]),
            "node_count": len(payload.get("nodes") or []),
        }
    for filename in ("ai_gateway_builder.py", "build_wf02.py", "build_wf03.py", "build_wf06.py"):
        path = directory / filename
        result[filename] = {"sha256": file_sha256(path)}
    return result


def workflow_logic(payload: dict[str, Any]) -> dict[str, Any]:
    nodes = []
    for raw in payload.get("nodes") or []:
        node = {key: value for key, value in raw.items() if key != "position"}
        nodes.append(node)
    nodes.sort(key=lambda node: (str(node.get("id") or ""), str(node.get("name") or "")))
    settings_source = payload.get("settings") or {}
    setting_keys = {
        "executionOrder",
        "timezone",
        "saveExecutionProgress",
        "saveManualExecutions",
        "callerPolicy",
        "errorWorkflow",
    }
    settings = {
        key: value for key, value in settings_source.items() if key in setting_keys
    }
    return {
        "id": payload.get("id"),
        "name": payload.get("name"),
        "active": payload.get("active") is True,
        "nodes": nodes,
        "connections": payload.get("connections") or {},
        "settings": settings,
    }


def n8n_login_session(base_url: str, user: str, password: str) -> requests.Session:
    session = requests.Session()
    try:
        response = session.post(
            f"{base_url.rstrip('/')}/rest/login",
            json={"emailOrLdapLoginId": user, "password": password},
            timeout=20,
        )
        response.raise_for_status()
        return session
    except Exception:
        session.close()
        raise


def verify_deployed_workflows(
    base_url: str,
    user: str,
    password: str,
) -> dict[str, dict[str, Any]]:
    directory = ROOT / "n8n" / "workflows" / "Versão9"
    session = n8n_login_session(base_url, user, password)
    evidence: dict[str, dict[str, Any]] = {}
    try:
        for filename in WORKFLOW_FILES:
            local_path = directory / filename
            local = json.loads(local_path.read_text(encoding="utf-8-sig"))
            response = session.get(
                f"{base_url.rstrip('/')}/rest/workflows/{local['id']}",
                timeout=20,
            )
            response.raise_for_status()
            raw = response.json()
            live = raw.get("data", raw) if isinstance(raw, dict) else None
            if not isinstance(live, dict):
                raise RuntimeError(f"n8n não retornou workflow vivo: {filename}")
            local_logic = workflow_logic(local)
            live_logic = workflow_logic(live)
            local_hash = canonical_sha256(local_logic)
            live_hash = canonical_sha256(live_logic)
            if (
                not hmac.compare_digest(local_hash, live_hash)
                or live.get("isArchived") is True
                or live.get("active") is not True
            ):
                raise RuntimeError(
                    f"Workflow implantado diverge do canônico: {filename}"
                )
            evidence[filename] = {
                "workflow_id": str(local["id"]),
                "workflow_name": str(local["name"]),
                "node_count": len(local_logic["nodes"]),
                "canonical_logic_sha256": local_hash,
                "deployed_logic_sha256": live_hash,
                "active": True,
                "archived": False,
                "parity": True,
            }
    finally:
        session.close()
    return evidence


def _docker_command(*arguments: str) -> list[str]:
    return ["docker", "--context", LOCAL_DOCKER_CONTEXT, *arguments]


def assert_local_docker_context() -> str:
    process = subprocess.run(
        [
            "docker",
            "context",
            "inspect",
            LOCAL_DOCKER_CONTEXT,
            "--format",
            "{{.Endpoints.docker.Host}}",
        ],
        capture_output=True,
        text=True,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        timeout=30,
    )
    endpoint = process.stdout.strip()
    if process.returncode:
        raise RuntimeError(
            process.stderr.strip() or "Contexto Docker local não está disponível"
        )
    if os.name == "nt" and endpoint.lower() != LOCAL_DOCKER_ENDPOINT_WINDOWS.lower():
        raise RuntimeError(
            f"Contexto {LOCAL_DOCKER_CONTEXT} não aponta para o Docker Desktop local"
        )
    if endpoint.lower().startswith(("ssh://", "tcp://", "http://", "https://")):
        raise RuntimeError("E2E recusou endpoint Docker remoto")
    return endpoint


def _docker_environment() -> dict[str, str]:
    assert_local_docker_context()
    process = subprocess.run(
        _docker_command(
            "inspect",
            "--format",
            "{{range .Config.Env}}{{println .}}{{end}}",
            "n8n-task-runners",
        ),
        capture_output=True,
        text=True,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        timeout=30,
    )
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or "Não foi possível inspecionar o runner externo")
    values: dict[str, str] = {}
    for line in process.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def snapshot_runtime_profile() -> dict[str, str]:
    environment = _docker_environment()
    missing = [key for key in PROFILE_KEYS if key not in environment]
    if missing:
        raise RuntimeError("Perfil do runner externo incompleto: " + ", ".join(missing))
    return {key: environment[key] for key in PROFILE_KEYS}


def validate_local_url(
    value: str,
    label: str,
    *,
    allow_host_docker_internal: bool = False,
) -> str:
    parsed = urlsplit(str(value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError(f"{label} deve ser uma URL HTTP local válida")
    if parsed.username is not None or parsed.password is not None:
        raise RuntimeError(f"{label} não pode conter credenciais na URL")
    hostname = parsed.hostname.lower().rstrip(".")
    allowed = hostname == "localhost"
    if allow_host_docker_internal and hostname == "host.docker.internal":
        allowed = True
    try:
        allowed = allowed or ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        pass
    if not allowed:
        raise RuntimeError(f"{label} deve apontar para loopback local")
    return parsed.geturl()


def scoped_runtime_profile(snapshot: dict[str, str], run_id: str) -> dict[str, str]:
    validate_run_id(run_id)
    profile = dict(snapshot)
    profile.update(
        {
            "FILA_IA_RUN_SCOPE": run_id,
            "FILA_IA_LOTE_TAMANHO": "1",
            "FILA_IA_INTERVALO_SEGUNDOS": "0",
            "FILA_IA_INGRESS_GRACE_SEGUNDOS": "0",
            "IA_MODEL_LOCAL": EXPECTED_MODEL,
            "IA_MODEL_VERSION": EXPECTED_MODEL,
            "IA_FIXED_MODEL_ROLE": "LOCAL",
            "IA_OPERATIONAL_SEQUENCE": "LOCAL",
            "IA_FAILOVER_ENABLED": "false",
            "IA_EXECUTION_MODE": "VALIDACAO",
            "IA_GENERATION_PROFILE": "local-hybrid-v1.8.0_e2e-technical",
            "TEST_MODE": "true",
            "TEST_AUTO_HUMAN_CONFIRMATION": "false",
        }
    )
    return profile


def validate_scoped_profile(profile: dict[str, str], run_id: str) -> None:
    expected = scoped_runtime_profile(profile, run_id)
    actual = {key: profile.get(key) for key in expected}
    if actual != expected:
        raise RuntimeError("O perfil n8n não comprova LOCAL v1.8 isolado")


def recreate_n8n(profile: dict[str, str], timeout_seconds: float = 120.0) -> None:
    assert_local_docker_context()
    environment = os.environ.copy()
    environment.update(profile)
    process = subprocess.run(
        _docker_command(
            "compose",
            "-f",
            str(ROOT / "n8n" / "docker-compose.yml"),
            "up",
            "-d",
            "--force-recreate",
            "--no-deps",
            "n8n-task-runners",
        ),
        cwd=ROOT / "n8n",
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        timeout=timeout_seconds,
    )
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or "Falha ao recriar o runner externo")
    deadline = time.monotonic() + timeout_seconds
    config = require_config()
    restart_attempted = False
    while time.monotonic() < deadline:
        try:
            response = requests.get("http://127.0.0.1:5678/healthz", timeout=5)
            # healthz do processo principal não comprova registro/execução do
            # runner. A entrada inválida percorre Code -> IF -> resposta 422,
            # sem criar ticket GLPI ou alcançar nós PostgreSQL.
            if response.status_code == 200 and probe_runner_ready(config):
                return
        except requests.RequestException:
            pass
        # Uma conexão de runner recusada durante startup pode permanecer presa
        # apesar de o launcher estar vivo. Uma única reinicialização preserva
        # perfil/volume e exige a mesma prova funcional, sem relaxar autenticação.
        if not restart_attempted and time.monotonic() >= deadline - timeout_seconds + 30:
            restart_attempted = True
            restart = subprocess.run(
                _docker_command("restart", "n8n-task-runners"),
                capture_output=True, text=True, check=False,
                timeout=min(30, max(1, deadline - time.monotonic())),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if restart.returncode:
                raise RuntimeError("Falha na recuperação limitada do runner externo")
        time.sleep(2)
    raise TimeoutError("n8n/runner não comprovou execução da rota segura 422 no prazo")


def probe_runner_ready(config: dict[str, str]) -> bool:
    response = requests.post(
        f"{config['n8n_url'].rstrip('/')}/webhook/glpi-ticket-fila-ia-v9",
        headers={"X-Webhook-Key": config["webhook_key"]},
        json={"ticket_id": 0},
        timeout=15,
    )
    return response.status_code == 422 and response.text.strip() == "ticket_id inválido"


def assert_profile_exact(expected: dict[str, str]) -> dict[str, str]:
    observed = snapshot_runtime_profile()
    if observed != expected:
        differing = sorted(key for key in expected if observed.get(key) != expected[key])
        raise RuntimeError("Perfil n8n divergiu após recriação: " + ", ".join(differing))
    return observed


def controller_snapshot(connection: Any | None = None) -> dict[str, Any]:
    sql = """
        SELECT id,proxima_liberacao_em,intervalo_segundos,lote_tamanho,atualizado_em
        FROM fila_ia_controle WHERE id=1
    """
    if connection is None:
        rows = database.query(sql)
        if len(rows) != 1:
            raise RuntimeError("Controlador da fila ausente ou duplicado")
        return dict(rows[0])
    with connection.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Controlador da fila ausente")
    return dict(row)


def restore_controller(connection: Any, snapshot: dict[str, Any]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE fila_ia_controle
            SET proxima_liberacao_em=%s,intervalo_segundos=%s,lote_tamanho=%s,
                atualizado_em=%s
            WHERE id=%s
            """,
            (
                snapshot["proxima_liberacao_em"],
                snapshot["intervalo_segundos"],
                snapshot["lote_tamanho"],
                snapshot["atualizado_em"],
                snapshot["id"],
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("Restauração do controlador não atingiu uma linha")
    connection.commit()


def _first_value(row: Any) -> Any:
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


@contextmanager
def queue_reservation_lock(timeout_seconds: float = 30.0) -> Iterator[Any]:
    connection = database.connect_pg()
    acquired = False
    deadline = time.monotonic() + timeout_seconds
    try:
        while time.monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", (QUEUE_LOCK_KEY,))
                acquired = bool(_first_value(cursor.fetchone()))
            connection.commit()
            if acquired:
                break
            time.sleep(0.25)
        if not acquired:
            raise RuntimeError("WF06 mantém a reserva ocupada; E2E abortado")
        yield connection
    finally:
        if acquired:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", (QUEUE_LOCK_KEY,))
                connection.commit()
            except Exception:
                pass
        connection.close()


def assert_no_eligible_foreign_queue() -> None:
    rows = database.query(
        """
        SELECT COALESCE(array_agg(t.id ORDER BY t.id),ARRAY[]::bigint[]) AS ids
        FROM tickets_processados t
        WHERE t.triagem_status=ANY(%s)
          AND COALESCE(t.em_aprovacao_fiscal,FALSE)=FALSE
          AND (
            NOT EXISTS (
              SELECT 1 FROM dataset_controle dc
              WHERE dc.ticket_id=t.id AND dc.run_id IS NOT NULL
            )
            OR EXISTS (
              SELECT 1 FROM dataset_controle dc
              JOIN experimentos_avaliacao e ON e.run_id=dc.run_id
              WHERE dc.ticket_id=t.id AND e.status IN ('EXECUTANDO','CALIBRANDO')
            )
          )
        """,
        (list(ACTIVE_QUEUE_STATES),),
    )
    ids = list((rows[0] if rows else {}).get("ids") or [])
    if ids:
        raise RuntimeError(f"Fila elegível contém tickets externos: {ids}")


def assert_no_active_n8n_executions(base_url: str, user: str, password: str) -> None:
    session = n8n_login_session(base_url, user, password)
    try:
        current = session.get(
            f"{base_url.rstrip('/')}/rest/executions",
            timeout=20,
        )
        current.raise_for_status()
        payload = current.json()
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        rows = data.get("results", []) if isinstance(data, dict) else []
        concurrent = int(data.get("concurrentExecutionsCount") or 0) if isinstance(data, dict) else 0
        terminal = {"success", "error", "canceled", "crashed"}
        active = [row for row in rows if str(row.get("status") or "").lower() not in terminal]
        # O WF06 dispara a cada minuto. Quando a pré-condição separada confirma
        # ausência de fila externa, esse polling vazio não é interferência e a
        # recriação do perfil o encerra de forma controlada. Qualquer outra
        # execução continua bloqueando o ensaio.
        ignored_wf06 = sum(
            1 for row in active if str(row.get("workflowId") or "") == WF06_WORKFLOW_ID
        )
        active = [row for row in active if str(row.get("workflowId") or "") != WF06_WORKFLOW_ID]
        active_count = (
            max(max(0, concurrent - ignored_wf06), len(active))
            if concurrent >= 0 else len(active)
        )
        if active_count:
            raise RuntimeError(f"Há {active_count} execução(ões) n8n em andamento")
    finally:
        session.close()


def wait_no_active_n8n_executions(
    base_url: str,
    user: str,
    password: str,
    timeout: float,
    poll: float,
) -> None:
    deadline = time.monotonic() + timeout
    last_error: RuntimeError | None = None
    while time.monotonic() < deadline:
        try:
            assert_no_active_n8n_executions(base_url, user, password)
            return
        except RuntimeError as exc:
            if not str(exc).startswith("Há "):
                raise
            last_error = exc
        time.sleep(poll)
    raise TimeoutError(
        "O n8n não ficou ocioso antes do cleanup"
        + (f": {last_error}" if last_error is not None else "")
    )


def generation_config(provenance: dict[str, Any]) -> dict[str, Any]:
    return {
        "test_mode": True,
        "auto_human_confirmation": False,
        "synthetic_only": True,
        "evidence_nature": "VALIDACAO_TECNICA_NAO_CONFIRMATORIA",
        "scientific_result": False,
        "confirmatory_eligible": False,
        "ia_fixed_model_role": "LOCAL",
        "ia_expected_model": EXPECTED_MODEL,
        "ia_execution_mode": "VALIDACAO",
        "failover_enabled": False,
        "fallback_enabled": False,
        "model_manifest_sha256": provenance["manifest_sha256"],
        "model_manifest_payload_sha256": provenance["manifest_payload_sha256"],
        "model_bundle_sha256": provenance["bundle_sha256"],
        "embedding_model_revision": provenance["embedding"]["model_revision"],
        "embedding_model_tree_sha256": provenance["embedding"]["model_tree_sha256"],
    }


def validate_local_runtime_health(
    base_url: str,
    token: str,
    provenance: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    health = calibration._request_json(
        f"{base_url.rstrip('/')}/health",
        token,
        timeout_seconds=timeout,
    )
    hybrid = ((health.get("artifacts") or {}).get("hybrid_bundle") or {})
    embedding = health.get("embedding") or {}
    gates = {
        "alive": health.get("alive") is True,
        "decision_ready": health.get("decision_ready") is True,
        "candidate_evaluation_eligible": (
            health.get("candidate_evaluation_eligible") is True
        ),
        "pipeline_evaluation_eligible": (
            health.get("pipeline_evaluation_eligible") is True
        ),
        "production_mode": health.get("mode") == "production",
        "hybrid_loaded": hybrid.get("loaded") is True,
        "bundle_version": (
            str(hybrid.get("version") or "") == provenance["bundle_version"]
        ),
        "embedding_backend": (
            embedding.get("backend") == "granite_embedding_pytorch_fp32"
        ),
        "embedding_dimension": embedding.get("dimension") == 384,
        "embedding_revision": (
            str(embedding.get("model_revision") or "")
            == provenance["embedding"]["model_revision"]
        ),
        "embedding_tree_hash": hmac.compare_digest(
            str(embedding.get("model_tree_sha256") or "").lower(),
            provenance["embedding"]["model_tree_sha256"],
        ),
        "no_embedding_fallback": embedding.get("fallback_used") is False,
    }
    if not all(gates.values()):
        raise RuntimeError(f"Serviço LOCAL v1.8 diverge do manifesto: {gates}")
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "service_version": health.get("service_version"),
        "mode": health.get("mode"),
        "health_gates": gates,
        "bundle_version": hybrid.get("version"),
        "embedding_backend": embedding.get("backend"),
    }


def validate_safe_local_probes(
    base_url: str, token: str, provenance: dict[str, Any], timeout: float
) -> dict[str, Any]:
    current = {
        "id": 1,
        "titulo": SAFE_TITLE,
        "descricao": SAFE_CONTENT,
        "tipo_servico": "",
        "localizacao": "",
        "solicitante": "teste.e2e",
    }
    calls = {
        "deduplicacao": ("/v1/deduplicate?include_metadata=1", {"chamado_atual": current, "historico": []}),
        "classificacao": ("/v1/classify?include_metadata=1", current),
    }
    result: dict[str, Any] = {}
    for stage, (path, payload) in calls.items():
        response = calibration._request_json(
            f"{base_url.rstrip('/')}{path}", token, payload=payload, timeout_seconds=timeout
        )
        decision = response.get("result") or {}
        metadata = response.get("metadata") or {}
        artifact = metadata.get("artifact") or {}
        expected_path = (
            "deterministic_empty_history"
            if stage == "deduplicacao"
            else "deterministic_out_of_scope"
        )
        gates = {
            "decision_path": metadata.get("decision_path") == expected_path,
            "pipeline_eligible": metadata.get("pipeline_evaluation_eligible") is True,
            "no_fallback": metadata.get("fallback_used") is False,
            "bundle_hash": hmac.compare_digest(
                str(artifact.get("bundle_sha256") or "").lower(), provenance["bundle_sha256"]
            ),
            "manifest_hash": hmac.compare_digest(
                str(artifact.get("manifest_payload_sha256") or "").lower(),
                provenance["manifest_payload_sha256"],
            ),
            "safe_decision": (
                decision.get("eh_duplicado") is False
                if stage == "deduplicacao"
                else decision.get("tipo") == "TRIAGEM_MANUAL"
                and decision.get("executor") == "FISCAL"
            ),
        }
        if not all(gates.values()):
            raise RuntimeError(f"Probe LOCAL seguro falhou em {stage}: {gates}")
        result[stage] = {"gates": gates, "decision_path": expected_path}
    return result


class GlpiSession:
    def __init__(self, base_url: str, app_token: str, auth_basic: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/").replace("host.docker.internal", "127.0.0.1")
        self.app_token = app_token
        self.auth_basic = auth_basic
        self.timeout = timeout
        self.session_token = ""

    def __enter__(self) -> "GlpiSession":
        response = requests.get(
            f"{self.base_url}/initSession",
            headers={"App-Token": self.app_token, "Authorization": self.auth_basic},
            timeout=self.timeout,
        )
        response.raise_for_status()
        self.session_token = str(response.json().get("session_token") or "")
        if not self.session_token:
            raise RuntimeError("GLPI não retornou session_token")
        return self

    def __exit__(self, *_: Any) -> None:
        if self.session_token:
            try:
                requests.get(f"{self.base_url}/killSession", headers=self.headers, timeout=10)
            except requests.RequestException:
                pass

    @property
    def headers(self) -> dict[str, str]:
        return {
            "App-Token": self.app_token,
            "Session-Token": self.session_token,
            "Content-Type": "application/json",
        }

    def create_ticket(self) -> int:
        response = requests.post(
            f"{self.base_url}/Ticket",
            headers=self.headers,
            json={
                "input": {
                    "name": SAFE_TITLE,
                    "content": SAFE_CONTENT,
                    "type": 1,
                    "status": 1,
                    "urgency": 1,
                    "impact": 1,
                }
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            payload = payload[0] if payload else {}
        ticket_id = int(payload.get("id") or 0)
        if ticket_id <= 0 or not self.get_ticket(ticket_id)["name"].startswith(TEST_PREFIX):
            raise RuntimeError("GLPI não confirmou o ticket sintético")
        return ticket_id

    def get_ticket(self, ticket_id: int) -> dict[str, Any]:
        response = requests.get(
            f"{self.base_url}/Ticket/{int(ticket_id)}", headers=self.headers, timeout=self.timeout
        )
        response.raise_for_status()
        return dict(response.json())

    def purge_ticket(self, ticket_id: int) -> None:
        ticket = self.get_ticket(ticket_id)
        if not str(ticket.get("name") or "").startswith(TEST_PREFIX):
            raise RuntimeError("Purge bloqueado para ticket não sintético")
        response = requests.delete(
            f"{self.base_url}/Ticket/{int(ticket_id)}",
            headers=self.headers,
            params={"force_purge": "true"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        check = requests.get(
            f"{self.base_url}/Ticket/{int(ticket_id)}", headers=self.headers, timeout=self.timeout
        )
        if check.status_code not in {404, 410}:
            raise RuntimeError("GLPI não comprovou o purge do ticket sintético")


def register_case(connection: Any, run_id: str, ticket_id: int, provenance: dict[str, Any]) -> None:
    case_payload = {"title": SAFE_TITLE, "content": SAFE_CONTENT, "expected": "TRIAGEM_MANUAL"}
    config = generation_config(provenance)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO experimentos_avaliacao(
              run_id,origem,dataset_version,dataset_sha256,seed,split,modelo_ia,
              prompt_dedup_version,prompt_classif_version,generation_profile,
              generation_config,protocolo_version,status,rotulos_validados,
              protocolo_rotulagem_validado,auditoria_humana_concluida,iniciado_em
            ) VALUES(
              %s,%s,'e2e-pipeline-v1',%s,20260817,'VALIDACAO',%s,
              'deduplicacao_v9.1-episodica','classificacao_v9.1-episodica',
              'local-v1.8-deterministic-safe',%s::jsonb,%s,'EXECUTANDO',
              FALSE,FALSE,FALSE,NOW()
            )
            """,
            (
                run_id,
                f"VALIDACAO_E2E_PIPELINE_{run_id}",
                canonical_sha256(case_payload),
                EXPECTED_MODEL,
                json.dumps(config, ensure_ascii=False),
                PROTOCOL_VERSION,
            ),
        )
        cursor.execute(
            """
            INSERT INTO dataset_controle(
              ticket_id,origem,cenario_controle,duplicado_esperado,
              classificacao_esperada,executor_esperado,status_final_esperado,
              nivel_dificuldade,run_id,case_id,episode_id,scenario_id,dimension,
              order_in_episode,requires_human_review,risk,rationale,label_source,
              template_family,dataset_version,split,observacao
            ) VALUES(
              %s,'VALIDACAO_E2E_PIPELINE','E2E_WF06_LOCAL_V18',FALSE,
              'TRIAGEM_MANUAL','FISCAL','PENDENTE','CONTROLADO',%s,
              'E2E-WF06-001','E2E-WF06-EP-001','E2EWF06','PIPELINE',1,TRUE,
              'BAIXO','Rota segura de software fora do escopo físico',
              'REGRA_SINTETICA_TECNICA','E2E_WF06_LOCAL_V18','e2e-pipeline-v1',
              'VALIDACAO',%s
            )
            """,
            (ticket_id, run_id, f"{TEST_PREFIX} run_id={run_id}"),
        )
    connection.commit()


def ingress_ticket(n8n_url: str, webhook_key: str, ticket_id: int, timeout: float) -> dict[str, Any]:
    response = requests.post(
        f"{n8n_url.rstrip('/')}/webhook/glpi-ticket-fila-ia-v9",
        headers={"X-Webhook-Key": webhook_key},
        json={
            "ticket_id": ticket_id,
            "name": SAFE_TITLE,
            "descricao": SAFE_CONTENT,
            "status": 1,
            "status_nome": "Novo",
            "source": "e2e-wf06-local-v1.8",
            "event": "ticket.add",
        },
        timeout=timeout,
    )
    if response.status_code != 202:
        raise RuntimeError(f"Ingresso WF06 deveria retornar 202; recebeu {response.status_code}")
    if not response.text.strip():
        return {"status_code": 202, "response_body": "EMPTY"}
    try:
        payload = response.json()
    except (ValueError, TypeError):
        raw = response.text.encode("utf-8")
        return {
            "status_code": 202,
            "response_body": "TEXT",
            "body_length": len(raw),
            "body_sha256": hashlib.sha256(raw).hexdigest(),
        }
    if not isinstance(payload, dict):
        raise RuntimeError("Ingresso WF06 retornou JSON que não é objeto")
    return {"status_code": 202, "response_body": "JSON", "payload": payload}


def snapshot_run(run_id: str, ticket_id: int) -> dict[str, Any]:
    rows = database.query(
        """
        SELECT jsonb_build_object(
          'ticket',(SELECT to_jsonb(tp) FROM tickets_processados tp WHERE tp.id=%s),
          'decisions',COALESCE((SELECT jsonb_agg(to_jsonb(d) ORDER BY d.id)
            FROM ia_decisoes d WHERE d.run_id=%s AND d.ticket_id=%s),'[]'::jsonb),
          'attempts',COALESCE((SELECT jsonb_agg(to_jsonb(a) ORDER BY a.id)
            FROM ia_tentativas_modelo a WHERE a.run_id=%s AND a.ticket_id=%s),'[]'::jsonb),
          'events',COALESCE((SELECT jsonb_agg(to_jsonb(w) ORDER BY w.id)
            FROM workflow_eventos w WHERE w.ticket_id=%s),'[]'::jsonb),
          'dlq',COALESCE((SELECT jsonb_agg(to_jsonb(q) ORDER BY q.id)
            FROM fila_ia_dead_letter q WHERE q.run_id=%s AND q.ticket_id=%s),'[]'::jsonb)
        ) AS payload
        """,
        (ticket_id, run_id, ticket_id, run_id, ticket_id, ticket_id, run_id, ticket_id),
    )
    if len(rows) != 1:
        raise RuntimeError("Snapshot E2E ausente")
    return scalar(rows[0]["payload"])


def validate_complete_snapshot(
    snapshot: dict[str, Any], provenance: dict[str, Any]
) -> dict[str, Any]:
    ticket = snapshot.get("ticket") or {}
    decisions = list(snapshot.get("decisions") or [])
    attempts = list(snapshot.get("attempts") or [])
    events = list(snapshot.get("events") or [])
    dlq = list(snapshot.get("dlq") or [])
    by_stage = {str(row.get("etapa")): row for row in decisions}
    if len(decisions) != 2 or set(by_stage) != {"DEDUPLICACAO", "CLASSIFICACAO"}:
        raise RuntimeError("E2E exige exatamente uma decisão por etapa")
    if by_stage["DEDUPLICACAO"].get("predicao") != "NAO_DUPLICADO":
        raise RuntimeError("WF02 não produziu NAO_DUPLICADO")
    classification = str(by_stage["CLASSIFICACAO"].get("predicao") or "")
    terminal = str(ticket.get("triagem_status") or "")
    if classification != EXPECTED_CLASSIFICATION or terminal != EXPECTED_TERMINAL:
        raise RuntimeError(
            "O caso sintético não terminou na abstenção segura esperada: "
            f"{classification}/{terminal}"
        )
    if len(attempts) != 2 or dlq:
        raise RuntimeError("E2E contém tentativas extras ou DLQ")
    attempt_stages = {str(row.get("etapa") or "") for row in attempts}
    if attempt_stages != {"DEDUPLICACAO", "CLASSIFICACAO"}:
        raise RuntimeError("E2E não contém exatamente uma tentativa por etapa")
    for attempt in attempts:
        metadata = attempt.get("metadata_cientifica") or {}
        artifact = metadata.get("artifact") or {}
        policy = attempt.get("politica_execucao") or {}
        checks = {
            "order": int(attempt.get("ordem_tentativa") or 0) == 1,
            "role": attempt.get("papel_modelo") == "LOCAL",
            "provider": attempt.get("provedor_ia") == "local-native",
            "model": attempt.get("versao_modelo") == EXPECTED_MODEL,
            "valid": attempt.get("status_tentativa") == "VALID",
            "transport": attempt.get("transporte_ok") is True,
            "schema": attempt.get("schema_ok") is True,
            "fallback": attempt.get("fallback_utilizado") is False,
            "retry": attempt.get("retryable") is not True,
            "pipeline": metadata.get("pipeline_evaluation_eligible") is True,
            "artifact": artifact.get("bundle_sha256") == provenance["bundle_sha256"],
            "manifest": artifact.get("manifest_payload_sha256")
            == provenance["manifest_payload_sha256"],
            "policy": policy.get("fixed_role") == "LOCAL"
            and policy.get("failover_allowed") is False
            and policy.get("policy_violation") is False,
        }
        if not all(checks.values()):
            raise RuntimeError(f"Tentativa LOCAL inválida: {checks}")
    reservation_count = sum(
        1
        for entry in (ticket.get("log_workflow") or [])
        if str((entry or {}).get("acao") or "").upper() == "RESERVAR_FILA"
    )
    stages_in_events = {
        str(row.get("fase") or row.get("etapa") or "")
        for row in events
        if row.get("erro") is not True
    }
    if reservation_count != 2 or not {"DEDUPLICACAO", "CLASSIFICACAO"}.issubset(stages_in_events):
        raise RuntimeError("Não há prova dos dois ciclos WF06/WF02/WF03")
    if any(row.get("erro_ia") is True for row in decisions) or any(
        row.get("erro") is True for row in events
    ):
        raise RuntimeError("Decisão ou evento com erro no E2E")
    return {
        "classification": classification,
        "terminal": terminal,
        "reservations": reservation_count,
        "decisions": len(decisions),
        "attempts": len(attempts),
        "dlq": len(dlq),
    }


def wait_complete(
    run_id: str, ticket_id: int, provenance: dict[str, Any], timeout: float, poll: float
) -> tuple[dict[str, Any], dict[str, Any]]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = snapshot_run(run_id, ticket_id)
        try:
            summary = validate_complete_snapshot(last, provenance)
            return last, summary
        except RuntimeError:
            terminal = str((last.get("ticket") or {}).get("triagem_status") or "")
            if terminal in {"ERRO_IA", "DUPLICADO_FECHADO", "FECHADO_OBRA"}:
                raise
        time.sleep(poll)
    raise TimeoutError(f"E2E não completou no prazo; último estado={last.get('ticket')}")


def cleanup_database(connection: Any, run_id: str, ticket_id: int) -> dict[str, int]:
    validate_run_id(run_id)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT tp.id AS registered_ticket_id FROM dataset_controle dc
            JOIN experimentos_avaliacao e ON e.run_id=dc.run_id
            LEFT JOIN tickets_processados tp ON tp.id=dc.ticket_id
            WHERE dc.run_id=%s AND dc.ticket_id=%s
              AND (tp.id IS NULL OR tp.titulo LIKE %s)
              AND dc.origem='VALIDACAO_E2E_PIPELINE'
              AND dc.observacao LIKE %s
              AND e.origem LIKE 'VALIDACAO_E2E_PIPELINE_%%'
            """,
            (run_id, ticket_id, f"{TEST_PREFIX}%", f"{TEST_PREFIX} run_id={run_id}"),
        )
        ownership = cursor.fetchone()
        if ownership is None:
            raise RuntimeError("Cleanup bloqueado: propriedade sintética não comprovada")
        # O ingresso pode falhar antes de materializar tickets_processados.
        # A propriedade continua comprovada pelo caso e experimento sintéticos.
        expected_ticket_count = int(_first_value(ownership) is not None)
        statements = (
            ("auto_confirmations", "DELETE FROM avaliacao_auto_confirmacoes WHERE run_id=%s", (run_id,)),
            ("human_reviews", "DELETE FROM avaliacoes_humanas WHERE run_id=%s", (run_id,)),
            ("model_attempts", "DELETE FROM ia_tentativas_modelo WHERE run_id=%s", (run_id,)),
            ("ai_decisions", "DELETE FROM ia_decisoes WHERE run_id=%s", (run_id,)),
            ("dlq", "DELETE FROM fila_ia_dead_letter WHERE run_id=%s", (run_id,)),
            ("queue_metrics", "DELETE FROM fila_ia_metricas WHERE run_id=%s", (run_id,)),
            ("workflow_events", "DELETE FROM workflow_eventos WHERE ticket_id=%s", (ticket_id,)),
            ("dataset", "DELETE FROM dataset_controle WHERE run_id=%s AND ticket_id=%s", (run_id, ticket_id)),
            ("ticket", "DELETE FROM tickets_processados WHERE id=%s AND titulo LIKE %s", (ticket_id, f"{TEST_PREFIX}%")),
            ("experiment", "DELETE FROM experimentos_avaliacao WHERE run_id=%s", (run_id,)),
        )
        counts: dict[str, int] = {}
        for label, sql, parameters in statements:
            cursor.execute(sql, parameters)
            counts[label] = int(cursor.rowcount)
    if counts["dataset"] != 1 or counts["ticket"] != expected_ticket_count or counts["experiment"] != 1:
        connection.rollback()
        raise RuntimeError(f"Cleanup cardinalidade inválida: {counts}")
    connection.commit()
    return counts


def write_report(path: Path, payload: dict[str, Any]) -> None:
    resolved = validate_output_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    result = scalar(payload)
    result["evidence_payload_sha256"] = None
    result["evidence_payload_sha256"] = canonical_sha256(result)
    resolved.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_output_path(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise RuntimeError("Saída deve permanecer dentro do projeto") from exc
    if resolved.exists():
        raise RuntimeError(f"Evidência já existe: {resolved}")
    return resolved


def require_config() -> dict[str, str]:
    values = {
        "n8n_url": configured_value("N8N_BASE_URL", "N8N_PUBLIC_BASE_URL", "N8N_URL"),
        "n8n_user": configured_value("N8N_BASIC_AUTH_USER"),
        "n8n_password": configured_value("N8N_BASIC_AUTH_PASSWORD"),
        "glpi_url": configured_value("GLPI_API_URL", "GLPI_URL"),
        "glpi_app_token": configured_value("GLPI_APP_TOKEN"),
        "glpi_auth_basic": configured_value("GLPI_AUTH_BASIC"),
        "webhook_key": configured_value("GLPI_WEBHOOK_KEY"),
        "local_token": configured_value("IA_LOCAL_API_TOKEN"),
    }
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise RuntimeError("Configuração ausente: " + ", ".join(missing))
    values["n8n_url"] = validate_local_url(values["n8n_url"], "n8n_url")
    values["glpi_url"] = validate_local_url(
        values["glpi_url"],
        "glpi_url",
        allow_host_docker_internal=True,
    )
    return values


def preflight(args: argparse.Namespace) -> dict[str, Any]:
    local_ai_url = validate_local_url(args.local_ai_url, "local_ai_url")
    provenance = calibration.validate_model_manifest(Path(args.model_manifest))
    if provenance["model_version"] != EXPECTED_MODEL:
        raise RuntimeError(f"Este runner exige {EXPECTED_MODEL}")
    config = require_config()
    runtime = snapshot_runtime_profile()
    if runtime["IA_MODEL_LOCAL"] != EXPECTED_MODEL or runtime["IA_MODEL_VERSION"] != EXPECTED_MODEL:
        raise RuntimeError("n8n ativo não declara LOCAL v1.8")
    assert_no_eligible_foreign_queue()
    assert_no_active_n8n_executions(
        config["n8n_url"], config["n8n_user"], config["n8n_password"]
    )
    deployed_workflows = verify_deployed_workflows(
        config["n8n_url"],
        config["n8n_user"],
        config["n8n_password"],
    )
    runtime_provenance = validate_local_runtime_health(
        local_ai_url,
        config["local_token"],
        provenance,
        args.http_timeout,
    )
    safe_probes = validate_safe_local_probes(
        local_ai_url, config["local_token"], provenance, args.http_timeout
    )
    return {
        "model_provenance": provenance,
        "runtime_provenance": runtime_provenance,
        "safe_probes": safe_probes,
        "runtime_profile": runtime,
        "controller": scalar(controller_snapshot()),
        "workflow_artifacts": workflow_artifacts(),
        "deployed_workflows": deployed_workflows,
        "config": config,
    }


@serialized_experiment(database.connect_pg, "VALIDACAO_E2E_PIPELINE_WF06")
def execute(args: argparse.Namespace) -> dict[str, Any]:
    output_path = validate_output_path(Path(args.output))
    run_id = validate_run_id(args.run_id or make_run_id())
    base = preflight(args)
    original_profile = dict(base["runtime_profile"])
    original_controller: dict[str, Any] | None = None
    scoped_profile = scoped_runtime_profile(original_profile, run_id)
    config = base.pop("config")
    ticket_id: int | None = None
    scoped_started = False
    cleanup: dict[str, Any] = {}
    result: dict[str, Any] = {
        "schema_version": PROTOCOL_VERSION,
        "run_id": run_id,
        "natureza_evidencia": "VALIDACAO_TECNICA_NAO_CONFIRMATORIA",
        "synthetic_only": True,
        "started_at": datetime.now(timezone.utc).isoformat(),
        **base,
    }
    primary_error: Exception | None = None
    try:
        with queue_reservation_lock(args.lock_timeout) as locked:
            assert_no_eligible_foreign_queue()
            assert_no_active_n8n_executions(
                config["n8n_url"],
                config["n8n_user"],
                config["n8n_password"],
            )
            original_controller = dict(controller_snapshot(locked))
            result["controller"] = scalar(original_controller)
            # Uma falha parcial da recriação também precisa disparar a
            # restauração; por isso o marcador vem antes da mutação do Docker.
            scoped_started = True
            recreate_n8n(scoped_profile)
            assert_profile_exact(scoped_profile)
        window_started = calibration.database_now()
        with queue_reservation_lock(args.lock_timeout) as locked:
            with GlpiSession(
                config["glpi_url"], config["glpi_app_token"],
                config["glpi_auth_basic"], args.http_timeout,
            ) as glpi:
                ticket_id = glpi.create_ticket()
            result["ticket_id"] = ticket_id
            register_case(locked, run_id, ticket_id, base["model_provenance"])
            ingress = ingress_ticket(
                config["n8n_url"], config["webhook_key"], ticket_id, args.http_timeout
            )
            result["ingress"] = ingress
        complete, validation = wait_complete(
            run_id, ticket_id, base["model_provenance"], args.timeout, args.poll
        )
        window_finished = calibration.database_now()
        interference = calibration.audit_foreign_interference(
            run_id, window_started, window_finished
        )
        if interference.get("interferencia_estranha_detectada") is not False:
            raise RuntimeError(f"Interferência externa detectada: {interference}")
        result.update(
            {
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "validation": validation,
                "complete_snapshot": complete,
                "foreign_interference": interference,
                "passed": True,
            }
        )
    except Exception as exc:
        primary_error = exc
        result["passed"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        cleanup_errors: list[str] = []
        if ticket_id is not None or scoped_started or original_controller is not None:
            try:
                wait_no_active_n8n_executions(
                    config["n8n_url"],
                    config["n8n_user"],
                    config["n8n_password"],
                    timeout=args.timeout,
                    poll=args.poll,
                )
                with queue_reservation_lock(args.lock_timeout) as locked:
                    assert_no_active_n8n_executions(
                        config["n8n_url"],
                        config["n8n_user"],
                        config["n8n_password"],
                    )
                    if ticket_id is not None:
                        try:
                            with GlpiSession(
                                config["glpi_url"], config["glpi_app_token"],
                                config["glpi_auth_basic"], args.http_timeout,
                            ) as glpi:
                                glpi.purge_ticket(ticket_id)
                            cleanup["glpi_purged"] = True
                        except Exception as exc:
                            cleanup_errors.append(f"GLPI: {exc}")
                        if cleanup.get("glpi_purged") is True:
                            cleanup["database_deleted"] = cleanup_database(
                                locked, run_id, ticket_id
                            )
                    if original_controller is None:
                        raise RuntimeError("Snapshot original do controlador ausente")
                    restore_controller(locked, original_controller)
                    cleanup["controller_restored"] = (
                        scalar(controller_snapshot(locked)) == scalar(original_controller)
                    )
                    if not cleanup["controller_restored"]:
                        raise RuntimeError("Snapshot restaurado do controlador divergiu")
                    if scoped_started:
                        recreate_n8n(original_profile)
                        assert_profile_exact(original_profile)
                        scoped_started = False
                    cleanup["runtime_profile_restored"] = True
                    cleanup["controller_restored"] = (
                        scalar(controller_snapshot(locked)) == scalar(original_controller)
                    )
                    if not cleanup["controller_restored"]:
                        raise RuntimeError(
                            "Controlador divergiu após restaurar o perfil operacional"
                        )
            except Exception as exc:
                cleanup_errors.append(f"restauração isolada: {exc}")
        if not scoped_started:
            try:
                cleanup["runtime_profile_restored"] = (
                    assert_profile_exact(original_profile) == original_profile
                )
            except Exception as exc:
                cleanup_errors.append(f"n8n: {exc}")
        else:
            cleanup.setdefault("runtime_profile_restored", False)
        cleanup.setdefault("controller_restored", original_controller is None)
        cleanup["errors"] = cleanup_errors
        cleanup["complete"] = (
            not cleanup_errors
            and cleanup.get("runtime_profile_restored") is True
            and cleanup.get("controller_restored") is True
            and (
                ticket_id is None
                or (
                    cleanup.get("glpi_purged") is True
                    and bool(cleanup.get("database_deleted"))
                )
            )
        )
        result["cleanup"] = cleanup
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        if not cleanup["complete"]:
            result["passed"] = False
            if primary_error is None:
                primary_error = RuntimeError("Cleanup/restauração incompletos")
        write_report(output_path, result)
    if primary_error is not None:
        raise primary_error
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executar", action="store_true", help="habilita a mutação sintética")
    parser.add_argument("--confirmacao", default="")
    parser.add_argument("--run-id")
    parser.add_argument(
        "--model-manifest",
        required=True,
        help="manifesto LOCAL v1.8 congelado; não existe valor implícito",
    )
    parser.add_argument("--local-ai-url", default="http://127.0.0.1:8090")
    parser.add_argument("--output", default="avaliacao/resultados/e2e-pipeline-local-v1.json")
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--poll", type=float, default=2.0)
    parser.add_argument("--http-timeout", type=float, default=30.0)
    parser.add_argument("--lock-timeout", type=float, default=30.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if min(args.timeout, args.poll, args.http_timeout, args.lock_timeout) <= 0:
        raise SystemExit("Todos os timeouts devem ser positivos")
    if args.executar:
        if args.confirmacao != MUTATION_CONFIRMATION:
            raise SystemExit(
                "Execução bloqueada: informe --confirmacao " + MUTATION_CONFIRMATION
            )
        execute(args)
        print(f"[OK] E2E sintético concluído; evidência: {args.output}")
        return 0
    result = preflight(args)
    public = {key: value for key, value in result.items() if key != "config"}
    print(json.dumps(scalar(public), ensure_ascii=False, indent=2))
    print("[OK] Preflight somente leitura; nenhuma mutação foi executada")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
