"""Deploy V9 workflows through the n8n authenticated REST session.

This is a local fallback for environments where the public API key is absent
and Docker exec is blocked by the host session.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import requests


DIR = Path(__file__).resolve().parent
PROJECT_DIR = DIR.parents[2]
BACKUP_ROOT = PROJECT_DIR / "backups" / "n8n" / "workflows-v9"


def load_local_env(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


load_local_env(PROJECT_DIR / "n8n" / ".env")
load_local_env(PROJECT_DIR / "n8n" / ".env.local")
BASE_URL = os.getenv("N8N_URL", "http://localhost:5678").rstrip("/")
EMAIL = os.getenv("N8N_BASIC_AUTH_USER", "").strip()
PASSWORD = os.getenv("N8N_BASIC_AUTH_PASSWORD", "")

WORKFLOW_FILES = [
    "V9-WF03-Classificacao.json",
    "V9-WF04-Decisao-Fiscal.json",
    "V9-WF02-Triagem.json",
    "V9-WF01-Sincronizador.json",
    "V9-WF05-Metricas.json",
    "V9-WF06-Fila-IA.json",
]

EXEC_OVERRIDES = {
    "V9 - WF02 Triagem": {"Chamar WF03": "V9 - WF03 Classificação"},
    "V9 - WF06 Fila IA": {
        "Chamar WF02 da Fila": "V9 - WF02 Triagem",
        "Chamar WF03 da Fila": "V9 - WF03 Classificação",
    },
}


def load_workflow(filename: str) -> dict:
    with (DIR / filename).open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def clean_for_rest(workflow: dict) -> dict:
    wf = json.loads(json.dumps(workflow, ensure_ascii=False))
    wf.pop("versionId", None)
    wf.pop("meta", None)
    wf.pop("tags", None)
    wf.pop("pinData", None)
    wf.pop("staticData", None)
    wf.pop("activeVersionId", None)
    wf.pop("triggerCount", None)
    wf.pop("shared", None)
    wf.pop("scopes", None)
    wf.pop("checksum", None)
    wf.pop("versionCounter", None)
    wf.pop("createdAt", None)
    wf.pop("updatedAt", None)
    wf.setdefault("settings", {})
    wf.setdefault("connections", {})
    wf.setdefault("nodes", [])
    return wf


def patch_execute_workflow_ids(workflow: dict, ids_by_name: dict[str, str]) -> None:
    overrides = EXEC_OVERRIDES.get(workflow["name"], {})
    if not overrides:
        return
    for node in workflow.get("nodes", []):
        target_name = overrides.get(node.get("name"))
        if not target_name:
            continue
        target_id = ids_by_name.get(target_name)
        if not target_id:
            continue
        params = node.setdefault("parameters", {})
        wf_id = params.get("workflowId")
        if isinstance(wf_id, dict):
            wf_id["value"] = target_id
        else:
            params["workflowId"] = {"__rl": True, "mode": "id", "value": target_id}


def logic_surface(workflow: dict) -> dict:
    """Retém somente a lógica que deve permanecer idêntica após o deploy."""
    return {
        "name": workflow.get("name"),
        "nodes": workflow.get("nodes", []),
        "connections": workflow.get("connections", {}),
        "settings": workflow.get("settings", {}),
    }


def logic_sha256(workflow: dict) -> str:
    payload = json.dumps(
        logic_surface(workflow),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_deployed_logic(
    s: requests.Session,
    filename: str,
    workflow_id: str,
    ids_by_name: dict[str, str],
) -> None:
    expected = clean_for_rest(load_workflow(filename))
    patch_execute_workflow_ids(expected, ids_by_name)
    expected.pop("active", None)
    expected.pop("id", None)
    deployed = get_workflow(s, workflow_id)
    expected_hash = logic_sha256(expected)
    deployed_hash = logic_sha256(deployed)
    if deployed_hash != expected_hash:
        raise RuntimeError(
            f"Paridade de lógica falhou para {expected['name']}: "
            f"esperado={expected_hash} implantado={deployed_hash}"
        )
    if deployed.get("active") is not True:
        raise RuntimeError(f"Paridade falhou: {expected['name']} não está ativo")
    print(f"[OK] Paridade lógica: {expected['name']} sha256={expected_hash}")


def session() -> requests.Session:
    if not EMAIL or not PASSWORD or "CHANGE_ME" in {EMAIL, PASSWORD}:
        raise RuntimeError(
            "Defina N8N_BASIC_AUTH_USER e N8N_BASIC_AUTH_PASSWORD em n8n/.env."
        )
    s = requests.Session()
    r = s.post(
        f"{BASE_URL}/rest/login",
        json={"emailOrLdapLoginId": EMAIL, "password": PASSWORD},
        timeout=30,
    )
    r.raise_for_status()
    print("[OK] Login REST n8n")
    return s


def list_workflows(s: requests.Session) -> list[dict]:
    r = s.get(f"{BASE_URL}/rest/workflows", timeout=30)
    r.raise_for_status()
    return r.json().get("data", [])


def resolve_workflow_ids(workflows: list[dict]) -> dict[str, str]:
    """Prefere o ID canônico do JSON e nunca uma cópia homônima antiga."""
    by_id = {str(item.get("id")): item for item in workflows if item.get("id")}
    resolved: dict[str, str] = {}
    for filename in WORKFLOW_FILES:
        desired = load_workflow(filename)
        name = desired["name"]
        canonical_id = str(desired.get("id") or "").strip()
        if canonical_id and canonical_id in by_id:
            resolved[name] = canonical_id
            continue
        candidates = [
            item
            for item in workflows
            if item.get("name") == name and not item.get("isArchived")
        ]
        if candidates:
            candidates.sort(key=lambda item: item.get("active") is True, reverse=True)
            resolved[name] = str(candidates[0]["id"])
    return resolved


def get_workflow(s: requests.Session, workflow_id: str) -> dict:
    r = s.get(f"{BASE_URL}/rest/workflows/{workflow_id}", timeout=30)
    r.raise_for_status()
    return r.json()["data"]


def save_backups(s: requests.Session, ids_by_name: dict[str, str]) -> None:
    backup_dir = BACKUP_ROOT / ("rest-session-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    backup_dir.mkdir(parents=True, exist_ok=True)
    (backup_dir / "LEIA-ME.txt").write_text(
        "BACKUP DE WORKFLOWS V9\n"
        "======================\n\n"
        "Esta pasta foi criada automaticamente antes de um deploy por sessao REST.\n"
        "Os arquivos JSON sao snapshots dos workflows que estavam publicados no n8n.\n"
        "Use-os somente para auditoria ou recuperacao; os builders da pasta Versao9\n"
        "continuam sendo a fonte editavel dos workflows atuais.\n",
        encoding="utf-8",
    )
    for name, workflow_id in ids_by_name.items():
        if name not in {load_workflow(f)["name"] for f in WORKFLOW_FILES}:
            continue
        current = get_workflow(s, workflow_id)
        safe_name = "".join(ch if ch.isalnum() else "_" for ch in name)
        (backup_dir / f"{safe_name}.json").write_text(
            json.dumps(current, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(f"[OK] Backup salvo em {backup_dir}")


def update_or_create(s: requests.Session, workflow: dict, ids_by_name: dict[str, str]) -> str:
    name = workflow["name"]
    workflow_id = ids_by_name.get(name)
    payload = clean_for_rest(workflow)
    patch_execute_workflow_ids(payload, ids_by_name)
    active = bool(payload.pop("active", True))
    if workflow_id:
        current = get_workflow(s, workflow_id)
        if current.get("isArchived") is True:
            unarchive = s.post(
                f"{BASE_URL}/rest/workflows/{workflow_id}/unarchive",
                json={},
                timeout=30,
            )
            if unarchive.status_code >= 400:
                raise RuntimeError(
                    f"Falha ao desarquivar {name}: "
                    f"{unarchive.status_code} {unarchive.text[:500]}"
                )
            print(f"[OK] Desarquivado: {name} ({workflow_id})")
        payload["id"] = workflow_id
        r = s.put(f"{BASE_URL}/rest/workflows/{workflow_id}", json=payload, timeout=60)
        if r.status_code == 404:
            r = s.patch(f"{BASE_URL}/rest/workflows/{workflow_id}", json=payload, timeout=60)
        if r.status_code >= 400:
            raise RuntimeError(f"Falha ao atualizar {name}: {r.status_code} {r.text[:500]}")
        print(f"[OK] Atualizado: {name} ({workflow_id})")
        result_id = workflow_id
    else:
        payload.pop("id", None)
        r = s.post(f"{BASE_URL}/rest/workflows", json=payload, timeout=60)
        if r.status_code >= 400:
            raise RuntimeError(f"Falha ao criar {name}: {r.status_code} {r.text[:500]}")
        result = r.json().get("data", r.json())
        result_id = result.get("id")
        if not result_id:
            raise RuntimeError(f"n8n nao retornou ID ao criar {name}: {r.text[:500]}")
        ids_by_name[name] = result_id
        print(f"[OK] Criado: {name} ({result_id})")
    if active:
        activate(s, result_id, name)
    return result_id


def activate(s: requests.Session, workflow_id: str, name: str) -> None:
    detail = get_workflow(s, workflow_id)
    version_id = detail.get("versionId")
    r = s.post(
        f"{BASE_URL}/rest/workflows/{workflow_id}/activate",
        json={"versionId": version_id},
        timeout=30,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Falha ao ativar {name}: {r.status_code} {r.text[:500]}")
    detail = get_workflow(s, workflow_id)
    if detail.get("active") is not True:
        raise RuntimeError(f"n8n aceitou ativacao, mas {name} continua inativo")
    print(f"[OK] Ativado: {name}")


def deactivate_legacy_wf06(s: requests.Session, workflows: list[dict]) -> None:
    canonical_id = load_workflow("V9-WF06-Fila-IA.json").get("id")
    for item in workflows:
        if item.get("name") not in {"V9 - WF06 Fila", "V9 - WF06 Fila IA"}:
            continue
        if item.get("active") is not True or item.get("id") == canonical_id:
            continue
        workflow_id = item["id"]
        response = s.post(
            f"{BASE_URL}/rest/workflows/{workflow_id}/deactivate",
            json={},
            timeout=30,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                "Falha ao desativar WF06 legado: "
                f"{response.status_code} {response.text[:500]}"
            )
        print(f"[OK] WF06 legado desativado: {workflow_id}")


def main() -> None:
    s = session()
    workflows = list_workflows(s)
    deactivate_legacy_wf06(s, workflows)
    workflows = list_workflows(s)
    ids_by_name = resolve_workflow_ids(workflows)
    save_backups(s, ids_by_name)
    deployed_ids: dict[str, str] = {}
    for filename in WORKFLOW_FILES:
        wf = load_workflow(filename)
        deployed_ids[filename] = update_or_create(s, wf, ids_by_name)
    for filename in WORKFLOW_FILES:
        verify_deployed_logic(s, filename, deployed_ids[filename], ids_by_name)
    print("[OK] Deploy REST session concluido.")


if __name__ == "__main__":
    argparse.ArgumentParser(
        description="Implanta os seis workflows V9 usando uma sessão REST autenticada do n8n."
    ).parse_args()
    main()
