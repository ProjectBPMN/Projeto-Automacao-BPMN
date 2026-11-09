"""Reconstrói, valida e implanta os workflows V9 no n8n.

Com ``N8N_API_KEY`` configurada, usa a API REST pública. Sem a chave, prefere
a sessão REST autenticada da própria interface; o CLI do container permanece
como último recurso. Falhas interrompem o deploy para evitar uma implantação
parcial apresentada como sucesso.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

DIR = Path(__file__).resolve().parent
N8N_DIR = DIR.parents[1]
PROJECT_DIR = DIR.parents[2]
N8N_URL = "http://localhost:5678"
LOCAL_DOCKER_CONTEXT = os.getenv("DOCKER_CONTEXT", "desktop-linux")
os.environ["DOCKER_CONTEXT"] = LOCAL_DOCKER_CONTEXT

SMTP_CRED = {
    "name": "SMTP Mailpit Local", "type": "smtp",
    "data": {"host": "mailpit", "port": 1025, "secure": False,
             "user": "", "password": "", "hostName": "n8n"}
}


def parse_env_file(path):
    """Read a dotenv file without overwriting explicit process variables."""
    values = {}
    path = Path(path)
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_project_env(paths=None):
    """Load n8n/.env and n8n/.env.local; local values take precedence."""
    paths = paths or (N8N_DIR / ".env", N8N_DIR / ".env.local")
    merged = {}
    for path in paths:
        merged.update(parse_env_file(path))
    for key, value in merged.items():
        if key not in os.environ and value and value.upper() != "CHANGE_ME":
            os.environ[key] = value
    return merged


def required_env(name):
    value = os.getenv(name, "").strip()
    if not value or value.upper() == "CHANGE_ME":
        raise RuntimeError(f"Variável obrigatória ausente: {name}")
    return value


def postgres_credential():
    """Build the n8n PostgreSQL credential without embedded passwords."""
    try:
        port = int(os.getenv("POSTGRES_PORT", "5432"))
    except ValueError as exc:
        raise RuntimeError("POSTGRES_PORT deve ser um inteiro.") from exc
    return {
        "name": "Postgres Triagem",
        "type": "postgres",
        "data": {
            "host": os.getenv("POSTGRES_HOST", "glpi-dedup-db"),
            "port": port,
            "database": required_env("POSTGRES_DB"),
            "user": required_env("POSTGRES_RUNTIME_USER"),
            "password": required_env("POSTGRES_RUNTIME_PASSWORD"),
            "ssl": "disable",
        },
    }


def load_api_key():
    value = os.getenv("N8N_API_KEY", "").strip()
    return "" if value.upper() == "CHANGE_ME" else value

WORKFLOW_FILES = [
    "V9-WF03-Classificacao.json",
    "V9-WF04-Decisao-Fiscal.json",
    "V9-WF02-Triagem.json",
    "V9-WF01-Sincronizador.json",
    "V9-WF05-Metricas.json",
    "V9-WF06-Fila-IA.json",
]
WORKFLOW_ID_DEFAULTS = {
    "V9-WF03-Classificacao.json": ("WF03_ID", "reVggSpJiaPhnfIo"),
    "V9-WF04-Decisao-Fiscal.json": ("WF04_ID", "ZpQ0H9uV9Fiscal04"),
    "V9-WF02-Triagem.json": ("WF02_ID", "nmNEsgC8kXmCVOsX"),
    "V9-WF01-Sincronizador.json": ("WF01_ID", "BCrENoTzdW20owz4"),
    "V9-WF05-Metricas.json": ("WF05_ID", "ZpQ0H9uV9Metric05"),
    "V9-WF06-Fila-IA.json": ("WF06_ID", "ZpQ0H9uV9Fila06"),
}


def workflow_ids():
    return {
        filename: os.getenv(variable, default)
        for filename, (variable, default) in WORKFLOW_ID_DEFAULTS.items()
    }


def obsolete_workflow_ids():
    return [
        workflow_id.strip()
        for workflow_id in os.getenv(
            "V9_OBSOLETE_WORKFLOW_IDS",
            "IyFBT5BVpzQkoe5R,2x95WAiouiiLMVqD",
        ).split(",")
        if workflow_id.strip()
    ]

def build_workflows():
    """Regenerate workflow JSON files from the embedded Python snapshots."""
    for script in ["build_wf01.py", "build_wf02.py", "build_wf03.py", "build_wf04.py", "build_wf05.py", "build_wf06.py"]:
        print(f"[BUILD] {script}")
        subprocess.run([sys.executable, str(DIR / script)], check=True)

def validate_workflows():
    """Run the static gate against the freshly generated workflow bundle."""
    run([sys.executable, str(DIR / "validate_v9_static.py")], cwd=PROJECT_DIR)


def get_session(api_key):
    """Get n8n API session with API key."""
    s = requests.Session()
    if not api_key:
        raise RuntimeError("N8N_API_KEY ausente.")
    s.headers.update({"X-N8N-API-KEY": api_key})
    r = s.get(f"{N8N_URL}/api/v1/workflows")
    if r.status_code != 200:
        raise RuntimeError(
            f"Falha de autenticação/conexão com n8n: {r.status_code} {r.text[:200]}"
        )
    print("[OK] Conectado ao n8n (API key)")
    return s

def list_workflows(s):
    r = s.get(f"{N8N_URL}/api/v1/workflows")
    if r.status_code != 200:
        raise RuntimeError(
            f"Falha ao listar workflows: {r.status_code} {r.text[:200]}"
        )
    return r.json().get("data", [])

def ensure_credential(s, cred_template):
    """Create or find credential."""
    r = s.get(f"{N8N_URL}/api/v1/credentials")
    if r.status_code != 200:
        raise RuntimeError(
            f"Falha ao listar credenciais: {r.status_code} {r.text[:200]}"
        )
    for credential in r.json().get("data", []):
        if (
            credential["name"] == cred_template["name"]
            and credential["type"] == cred_template["type"]
        ):
            print(
                f"[OK] Credencial existe: {credential['name']} "
                f"(id={credential['id']})"
            )
            return credential["id"]
    # Create
    r = s.post(f"{N8N_URL}/api/v1/credentials", json=cred_template)
    if r.status_code in (200, 201):
        cid = r.json().get("id", r.json().get("data", {}).get("id"))
        if not cid:
            raise RuntimeError(
                f"n8n criou {cred_template['name']} sem retornar o ID da credencial."
            )
        print(f"[OK] Credencial criada: {cred_template['name']} (id={cid})")
        return cid
    raise RuntimeError(
        f"Falha ao criar credencial {cred_template['name']}: "
        f"{r.status_code} {r.text[:200]}"
    )

def patch_credential_ids(wf, pg_id, smtp_id):
    """Replace credential IDs in workflow nodes."""
    for node in wf.get("nodes", []):
        creds = node.get("credentials", {})
        if "postgres" in creds:
            creds["postgres"]["id"] = pg_id
        if "smtp" in creds:
            creds["smtp"]["id"] = smtp_id

def patch_execute_workflow_ids(wf, overrides):
    """Replace executeWorkflow node IDs by node name."""
    if not overrides:
        return
    for node in wf.get("nodes", []):
        node_name = node.get("name")
        if node_name not in overrides:
            continue
        params = node.setdefault("parameters", {})
        wf_id = params.get("workflowId")
        if isinstance(wf_id, dict):
            wf_id["value"] = str(overrides[node_name])
        else:
            params["workflowId"] = {"__rl": True, "mode": "id", "value": str(overrides[node_name])}

def deploy_workflow(s, filepath, pg_id, smtp_id, exec_overrides=None):
    """Import or update a workflow."""
    with open(filepath, "r", encoding="utf-8-sig") as f:
        wf = json.load(f)
    name = wf["name"]
    patch_credential_ids(wf, pg_id, smtp_id)
    patch_execute_workflow_ids(wf, exec_overrides)
    # Remove fields that shouldn't be sent
    for key in ["id", "versionId", "meta", "tags", "pinData", "active"]:
        wf.pop(key, None)
    # Remove node IDs (n8n generates its own)
    for node in wf.get("nodes", []):
        node.pop("id", None)
        node.pop("webhookId", None)
    # Check if exists
    r = s.get(f"{N8N_URL}/api/v1/workflows")
    if r.status_code != 200:
        raise RuntimeError(
            f"Falha ao consultar workflow {name}: {r.status_code} {r.text[:300]}"
        )
    existing_id = None
    for workflow in r.json().get("data", []):
        if workflow["name"] == name:
            existing_id = workflow["id"]
            break
    if existing_id:
        r = s.put(f"{N8N_URL}/api/v1/workflows/{existing_id}", json=wf)
        if r.status_code == 200:
            print(f"[OK] Atualizado: {name} (id={existing_id})")
            return existing_id
        raise RuntimeError(
            f"Falha ao atualizar {name}: {r.status_code} {r.text[:300]}"
        )
    else:
        r = s.post(f"{N8N_URL}/api/v1/workflows", json=wf)
        if r.status_code in (200, 201):
            wid = r.json().get("id", r.json().get("data",{}).get("id","?"))
            print(f"[OK] Criado: {name} (id={wid})")
            return wid
        raise RuntimeError(
            f"Falha ao criar {name}: {r.status_code} {r.text[:300]}"
        )

def activate_workflow(s, wid):
    """Activate a workflow."""
    r = s.post(f"{N8N_URL}/api/v1/workflows/{wid}/activate")
    if r.status_code in (200, 201):
        print(f"[OK] Ativado: {wid}")
        return
    r = s.patch(f"{N8N_URL}/api/v1/workflows/{wid}", json={"active": True})
    if r.status_code in (200, 201):
        print(f"[OK] Ativado: {wid}")
        return
    raise RuntimeError(f"Falha ao ativar {wid}: {r.status_code} {r.text[:200]}")

def deactivate_workflow(s, wid, name=""):
    r = s.post(f"{N8N_URL}/api/v1/workflows/{wid}/deactivate")
    if r.status_code in (200, 201):
        print(f"[OK] Desativado conflito: {name or wid} ({wid})")
        return True
    r = s.patch(f"{N8N_URL}/api/v1/workflows/{wid}", json={"active": False})
    if r.status_code in (200, 201):
        print(f"[OK] Desativado conflito: {name or wid} ({wid})")
        return True
    raise RuntimeError(
        f"Falha ao desativar {name or wid}: {r.status_code} {r.text[:200]}"
    )

def workflow_has_webhook_path(wf, path):
    for node in wf.get("nodes", []):
        if node.get("type") == "n8n-nodes-base.webhook" and node.get("parameters", {}).get("path") == path:
            return True
    return False

def deactivate_duplicate_webhooks(s, path, keep_id):
    for wf_meta in list_workflows(s):
        wid = wf_meta.get("id")
        if str(wid) == str(keep_id) or not wf_meta.get("active"):
            continue
        r = s.get(f"{N8N_URL}/api/v1/workflows/{wid}")
        if r.status_code != 200:
            raise RuntimeError(
                f"Falha ao inspecionar workflow ativo {wid}: "
                f"{r.status_code} {r.text[:200]}"
            )
        wf = r.json()
        if workflow_has_webhook_path(wf, path):
            deactivate_workflow(s, wid, wf.get("name", ""))

def run(cmd, cwd=None):
    cmd_list = list(cmd)
    if cmd_list and cmd_list[0] == "docker" and (len(cmd_list) < 2 or cmd_list[1] != "--context"):
        cmd_list = ["docker", "--context", LOCAL_DOCKER_CONTEXT, *cmd_list[1:]]
    print("[CMD] " + " ".join(cmd_list))
    subprocess.run(cmd_list, cwd=cwd, check=True)

def sh_quote(value):
    return "'" + str(value).replace("'", "'\"'\"'") + "'"

def copy_file_to_container(src, dest):
    """Copy a local file into the n8n container without docker cp.

    Docker Desktop on Windows can deny docker cp from sandboxed sessions. The
    stdin path keeps the copy client-side and also lets us overwrite files that
    were previously created as root.
    """
    with open(src, "rb") as f:
        data = f.read()
    dest_q = sh_quote(dest)
    cmd = [
        "docker", "--context", LOCAL_DOCKER_CONTEXT, "exec", "-i", "-u", "root", "n8n", "sh", "-lc",
        f"cat > {dest_q} && chown node:node {dest_q} && chmod 0644 {dest_q}",
    ]
    print("[CMD] docker --context " + LOCAL_DOCKER_CONTEXT + " exec -i -u root n8n sh -lc cat > " + dest)
    subprocess.run(cmd, input=data, check=True)

def deploy_via_docker_cli():
    """Fallback when the n8n public API key is not configured."""
    compose_dir = N8N_DIR
    configured_workflow_ids = workflow_ids()
    print("[INFO] N8N_API_KEY ausente; usando fallback via Docker CLI.")
    print("[INFO] O fallback atualiza workflows existentes por ID e exige credenciais ja existentes no n8n.")
    run(["docker", "exec", "-u", "root", "n8n", "sh", "-lc", "mkdir -p /home/node/.n8n/v9 && chown node:node /home/node/.n8n/v9"])
    for filename in WORKFLOW_FILES:
        copy_file_to_container(DIR / filename, f"/home/node/.n8n/v9/{filename}")
    run(["docker", "compose", "stop", "n8n"], cwd=compose_dir)
    try:
        for filename in WORKFLOW_FILES:
            run(["docker", "compose", "run", "--rm", "--no-deps", "n8n", "import:workflow", f"--input=/home/node/.n8n/v9/{filename}"], cwd=compose_dir)
        for filename in WORKFLOW_FILES:
            wid = configured_workflow_ids[filename]
            run(["docker", "compose", "run", "--rm", "--no-deps", "n8n", "publish:workflow", f"--id={wid}"], cwd=compose_dir)
        for wid in obsolete_workflow_ids():
            run(["docker", "compose", "run", "--rm", "--no-deps", "n8n", "update:workflow", f"--id={wid}", "--active=false"], cwd=compose_dir)
    finally:
        run(["docker", "compose", "up", "-d", "n8n"], cwd=compose_dir)
    print("[OK] Deploy via Docker CLI concluido.")


def rest_session_configured() -> bool:
    values = (
        os.getenv("N8N_BASIC_AUTH_USER", "").strip(),
        os.getenv("N8N_BASIC_AUTH_PASSWORD", "").strip(),
    )
    return all(value and value.upper() != "CHANGE_ME" for value in values)


def deploy_via_rest_session() -> None:
    print("[INFO] N8N_API_KEY ausente; usando sessão REST autenticada do n8n.")
    run([sys.executable, str(DIR / "deploy_rest_session.py")])

def main():
    global N8N_URL

    print("=== Deploy V9 ===")
    load_project_env()
    N8N_URL = os.getenv("N8N_URL", "http://localhost:5678").rstrip("/")
    build_workflows()
    validate_workflows()
    api_key = load_api_key()
    if not api_key:
        if rest_session_configured():
            deploy_via_rest_session()
        else:
            deploy_via_docker_cli()
        return
    s = get_session(api_key)
    # Credentials
    pg_id = ensure_credential(s, postgres_credential())
    smtp_id = ensure_credential(s, SMTP_CRED)
    fiscal_webhook_key = required_env("FISCAL_WEBHOOK_KEY")
    glpi_webhook_key = required_env("GLPI_WEBHOOK_KEY")
    # Deploy workflows. WF01 e independente; WF02 chama WF03; WF04 escuta o fiscal.
    wf3_id = deploy_workflow(s, os.path.join(DIR, "V9-WF03-Classificacao.json"), pg_id, smtp_id)
    time.sleep(1)
    if wf3_id:
        activate_workflow(s, wf3_id)
    wf4_id = deploy_workflow(
        s,
        os.path.join(DIR, "V9-WF04-Decisao-Fiscal.json"),
        pg_id,
        smtp_id,
        exec_overrides=None,
    )
    time.sleep(1)
    if wf4_id:
        deactivate_duplicate_webhooks(
            s, f"fiscal-decisao-{fiscal_webhook_key}", wf4_id
        )
        activate_workflow(s, wf4_id)
    wf2_id = deploy_workflow(
        s,
        os.path.join(DIR, "V9-WF02-Triagem.json"),
        pg_id,
        smtp_id,
        exec_overrides={"Chamar WF03": wf3_id} if wf3_id else None,
    )
    time.sleep(1)
    if wf2_id:
        deactivate_duplicate_webhooks(
            s, f"glpi-ticket-novo-{glpi_webhook_key}", wf2_id
        )
        activate_workflow(s, wf2_id)
    wf1_id = deploy_workflow(
        s,
        os.path.join(DIR, "V9-WF01-Sincronizador.json"),
        pg_id,
        smtp_id,
        exec_overrides=None,
    )
    time.sleep(1)
    if wf1_id:
        activate_workflow(s, wf1_id)
    wf5_id = deploy_workflow(
        s,
        os.path.join(DIR, "V9-WF05-Metricas.json"),
        pg_id,
        smtp_id,
        exec_overrides=None,
    )
    time.sleep(1)
    if wf5_id:
        activate_workflow(s, wf5_id)
    wf6_id = deploy_workflow(
        s,
        os.path.join(DIR, "V9-WF06-Fila-IA.json"),
        pg_id,
        smtp_id,
        exec_overrides={
            "Chamar WF02 da Fila": wf2_id,
            "Chamar WF03 da Fila": wf3_id,
        } if wf2_id and wf3_id else None,
    )
    time.sleep(1)
    if wf6_id:
        activate_workflow(s, wf6_id)
    print("\n=== Deploy V9 concluído ===")
    print(f"WF01 Sincronizador: {wf1_id}")
    print(f"WF02 Triagem:       {wf2_id}")
    print(f"WF03 Classificação: {wf3_id}")
    print(f"WF04 Fiscal:        {wf4_id}")
    print(f"WF05 Métricas:      {wf5_id}")
    print(f"WF06 Fila IA:       {wf6_id}")

if __name__ == "__main__":
    argparse.ArgumentParser(
        description="Reconstrói e implanta os seis workflows V9 no n8n."
    ).parse_args()
    main()
