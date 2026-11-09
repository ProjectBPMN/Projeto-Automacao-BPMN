"""Smoke tests somente leitura/negação segura contra os serviços locais.

O E2E mutante pertence a ``validar_pipeline_fila_e2e.py``, que isola a rodada,
congela o modelo, restaura o perfil e executa cleanup. Esta suíte nunca cria
chamados nem contém credenciais versionadas.
"""

from __future__ import annotations

import os
import sys
import urllib.request
import urllib.error
import psycopg2
from pathlib import Path
import pytest
import requests


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "avaliacao" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from project_env import configured_value, load_project_env  # noqa: E402


load_project_env()

pytestmark = [
    pytest.mark.live_integration,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE_INTEGRATION_TESTS") != "1",
        reason=(
            "smokes contra serviços reais exigem "
            "RUN_LIVE_INTEGRATION_TESTS=1"
        ),
    ),
]

N8N_WEBHOOK_URL = "http://localhost:5678/webhook/glpi-ticket-fila-ia-v9"
LOCAL_AI_HEALTH_URL = "http://127.0.0.1:8090/health"
LOCAL_AI_TOKEN = configured_value("IA_LOCAL_API_TOKEN")

DB_CONFIG = {
    "host": configured_value("PGHOST") or "localhost",
    "port": int(configured_value("PGPORT") or "5432"),
    "dbname": configured_value("PGDATABASE", "POSTGRES_DB"),
    "user": configured_value("PGUSER", "POSTGRES_USER"),
    "password": configured_value("PGPASSWORD", "POSTGRES_PASSWORD"),
}


def test_local_ai_health_real():
    """Verifica se o servidor local_ai está ativo e saudável."""
    headers = {
        "Authorization": f"Bearer {LOCAL_AI_TOKEN}",
        "Connection": "close",
    }
    res = requests.get(LOCAL_AI_HEALTH_URL, headers=headers, timeout=15)
    assert res.status_code == 200
    data = res.json()
    assert data.get("status") == "ok"
    assert data.get("alive") is True
    assert data.get("decision_ready") is True


def test_postgresql_connection_real():
    """Verifica se o banco de dados PostgreSQL de triagem está acessível."""
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            result = cur.fetchone()
            assert result == (1,)
    finally:
        conn.close()


def test_webhook_rejects_invalid_key_without_persisting() -> None:
    """Exercita a rota real com 401 e comprova que não houve mutação."""
    probe_id = 2_147_483_000
    payload = b'{"id":2147483000,"event":"security-probe"}'
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM tickets_processados WHERE id = %s",
                (probe_id,),
            )
            before = int(cur.fetchone()[0])
    finally:
        conn.close()
    req = urllib.request.Request(
        N8N_WEBHOOK_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-webhook-key": "invalid-runtime-smoke-key",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as exc:
        assert exc.code == 401
    else:
        raise AssertionError("Webhook aceitou chave inválida")
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM tickets_processados WHERE id = %s",
                (probe_id,),
            )
            after = int(cur.fetchone()[0])
    finally:
        conn.close()
    assert before == after == 0
