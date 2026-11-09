from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "avaliacao" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import conferir_gabarito as oracle  # noqa: E402
from isolamento_experimentos import serialized_experiment  # noqa: E402


TEST_PREFIX = "[TESTE_AUTOMATIZADO_E2E_WF04_WF05]"
RUN_RE = re.compile(r"^VALIDACAO-POSTS-E2E-[0-9]{8}T[0-9]{6}Z$")
CANONICAL_V9_WORKFLOWS = (
    "V9-WF01-Sincronizador.json",
    "V9-WF02-Triagem.json",
    "V9-WF03-Classificacao.json",
    "V9-WF04-Decisao-Fiscal.json",
    "V9-WF05-Metricas.json",
    "V9-WF06-Fila-IA.json",
)


def scalar(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: scalar(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [scalar(item) for item in value]
    return value


def workflow_artifact_manifest() -> dict[str, dict[str, Any]]:
    """Congela os seis exports canônicos associados à evidência E2E."""
    workflow_dir = ROOT / "n8n" / "workflows" / "Versão9"
    manifest: dict[str, dict[str, Any]] = {}
    for filename in CANONICAL_V9_WORKFLOWS:
        path = workflow_dir / filename
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
        workflow_id = str(payload.get("id") or "")
        workflow_name = str(payload.get("name") or "")
        node_count = len(payload.get("nodes") or [])
        if not workflow_id or not workflow_name or node_count <= 0:
            raise RuntimeError(f"Workflow canônico inválido para E2E: {filename}")
        manifest[filename] = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "node_count": node_count,
        }
    return manifest


def require_test_environment() -> dict[str, str]:
    env = {key: str(value) for key, value in os.environ.items()}
    checks = {
        "TEST_MODE": env.get("TEST_MODE", "").lower() == "true",
        "TEST_AUTO_HUMAN_CONFIRMATION": (
            env.get("TEST_AUTO_HUMAN_CONFIRMATION", "").lower() == "true"
        ),
        "TEST_AUTO_REVIEW_TOKEN": bool(
            re.fullmatch(r"[A-Za-z0-9_-]{32,128}", env.get("TEST_AUTO_REVIEW_TOKEN", ""))
        ),
        "GLPI_APP_TOKEN": bool(env.get("GLPI_APP_TOKEN")),
        "GLPI_AUTH_BASIC": env.get("GLPI_AUTH_BASIC", "").startswith("Basic "),
    }
    missing = [name for name, ok in checks.items() if not ok]
    if missing:
        raise RuntimeError("Ambiente de teste incompleto: " + ", ".join(missing))
    return env


def assert_no_active_calibration() -> None:
    rows = oracle.query(
        """
        SELECT run_id
        FROM experimentos_avaliacao
        WHERE status='CALIBRANDO'
        ORDER BY criado_em DESC
        LIMIT 1
        """
    )
    if rows:
        raise RuntimeError(
            "Validação E2E bloqueada enquanto há calibração de fila ativa: "
            + str(rows[0]["run_id"])
        )


def host_glpi_url(value: str) -> str:
    url = str(value or "").rstrip("/")
    if not url.endswith("/apirest.php"):
        raise RuntimeError("GLPI_API_URL deve terminar em /apirest.php")
    return url.replace("host.docker.internal", "127.0.0.1")


class GlpiSession:
    def __init__(self, base_url: str, app_token: str, auth_basic: str) -> None:
        self.base_url = base_url
        self.app_token = app_token
        self.auth_basic = auth_basic
        self.session_token = ""

    def __enter__(self) -> "GlpiSession":
        response = requests.get(
            f"{self.base_url}/initSession",
            headers={"App-Token": self.app_token, "Authorization": self.auth_basic},
            timeout=20,
        )
        response.raise_for_status()
        self.session_token = str(response.json().get("session_token") or "")
        if not self.session_token:
            raise RuntimeError("GLPI não retornou session_token")
        return self

    def __exit__(self, *_: Any) -> None:
        if self.session_token:
            try:
                requests.get(
                    f"{self.base_url}/killSession",
                    headers=self.headers,
                    timeout=10,
                )
            except requests.RequestException:
                pass

    @property
    def headers(self) -> dict[str, str]:
        return {
            "App-Token": self.app_token,
            "Session-Token": self.session_token,
            "Content-Type": "application/json",
        }

    def create_ticket(self, title: str) -> int:
        if not title.startswith(TEST_PREFIX):
            raise RuntimeError("Criação de chamado não sintético bloqueada")
        response = requests.post(
            f"{self.base_url}/Ticket",
            headers=self.headers,
            json={
                "input": {
                    "name": title,
                    "content": (
                        f"{TEST_PREFIX} Registro exclusivamente sintético para validar "
                        "GET preview, POST e idempotência dos webhooks. Não atender."
                    ),
                    "type": 1,
                    "status": 4,
                    "urgency": 1,
                    "impact": 1,
                }
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            payload = payload[0] if payload else {}
        ticket_id = int(payload.get("id") or 0)
        if ticket_id <= 0:
            raise RuntimeError("GLPI não retornou o ID do chamado sintético")
        ticket = self.get_ticket(ticket_id)
        if not str(ticket.get("name") or "").startswith(TEST_PREFIX):
            raise RuntimeError("GLPI não confirmou a marca sintética do chamado")
        if int(ticket.get("status") or 0) != 4:
            response = requests.put(
                f"{self.base_url}/Ticket/{ticket_id}",
                headers=self.headers,
                json={"input": {"id": ticket_id, "status": 4}},
                timeout=20,
            )
            response.raise_for_status()
        return ticket_id

    def get_ticket(self, ticket_id: int) -> dict[str, Any]:
        response = requests.get(
            f"{self.base_url}/Ticket/{int(ticket_id)}",
            headers=self.headers,
            timeout=20,
        )
        response.raise_for_status()
        return dict(response.json())

    def close_synthetic_ticket(self, ticket_id: int) -> None:
        ticket = self.get_ticket(ticket_id)
        if not str(ticket.get("name") or "").startswith(TEST_PREFIX):
            raise RuntimeError(f"Encerramento bloqueado para chamado não sintético #{ticket_id}")
        response = requests.put(
            f"{self.base_url}/Ticket/{int(ticket_id)}",
            headers=self.headers,
            json={"input": {"id": int(ticket_id), "status": 6}},
            timeout=20,
        )
        response.raise_for_status()


def prepare_database(
    run_id: str,
    target_id: int,
    reference_id: int,
    fiscal_token: str,
    review_token: str,
    decision: str,
) -> None:
    expected_duplicate = decision == "confirmar"
    with oracle.connect_pg() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO experimentos_avaliacao(
                  run_id,origem,dataset_version,dataset_sha256,seed,split,modelo_ia,
                  prompt_dedup_version,prompt_classif_version,generation_profile,
                  generation_config,protocolo_version,status,rotulos_validados,
                  protocolo_rotulagem_validado,auditoria_humana_concluida,iniciado_em
                ) VALUES(
                  %s,%s,'e2e-webhooks-v1',%s,20260722,'VALIDACAO','local-hybrid-v1.8.0',
                  'e2e-dedup','nao-aplicavel','deterministico-test-only',
                  %s::jsonb,'e2e-webhooks-v1','EXECUTANDO',FALSE,FALSE,FALSE,NOW()
                )
                """,
                (
                    run_id,
                    f"VALIDACAO_E2E_POST_{run_id}",
                    hashlib.sha256(run_id.encode("utf-8")).hexdigest(),
                    json.dumps(
                        {
                            "test_mode": True,
                            "auto_human_confirmation": True,
                            "evidence_nature": "VALIDACAO_TECNICA_NAO_CONFIRMATORIA",
                            "synthetic_only": True,
                            "fiscal_decision_under_test": decision,
                        }
                    ),
                ),
            )
            common_ticket = (
                "status_num,status_nome,tipo_servico,descricao,localizacao,"
                "data_abertura,data_ultima_mudanca,solicitante,email_solicitante,"
                "origem_ingestao,wf_version"
            )
            cursor.execute(
                f"""
                INSERT INTO tickets_processados(id,titulo,{common_ticket})
                VALUES(
                  %s,%s,4,'Pendente','Validação sintética',%s,'AMBIENTE SINTETICO E2E',
                  NOW(),NOW(),'oraculo_teste','teste-e2e@example.invalid',
                  'VALIDACAO_E2E','v9-e2e'
                )
                ON CONFLICT(id) DO UPDATE SET
                  titulo=EXCLUDED.titulo,status_num=EXCLUDED.status_num,
                  status_nome=EXCLUDED.status_nome,tipo_servico=EXCLUDED.tipo_servico,
                  descricao=EXCLUDED.descricao,localizacao=EXCLUDED.localizacao,
                  data_abertura=EXCLUDED.data_abertura,
                  data_ultima_mudanca=EXCLUDED.data_ultima_mudanca,
                  solicitante=EXCLUDED.solicitante,
                  email_solicitante=EXCLUDED.email_solicitante,
                  origem_ingestao=EXCLUDED.origem_ingestao,wf_version=EXCLUDED.wf_version
                WHERE tickets_processados.titulo LIKE %s
                """,
                (
                    reference_id,
                    f"{TEST_PREFIX} REFERENCIA {run_id}",
                    f"{TEST_PREFIX} Chamado de referência; não atender.",
                    f"{TEST_PREFIX}%",
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Conflito com registro PostgreSQL não sintético na referência")
            cursor.execute(
                f"""
                INSERT INTO tickets_processados(
                  id,titulo,{common_ticket},triagem_status,classificacao,
                  classificacao_final,duplicado_de_id,motivo_classificacao,
                  em_aprovacao_fiscal,aprovacao_iniciada_em,decisao_fiscal,
                  fiscal_decision_token,fiscal_token_expira_em,ultima_acao_workflow
                ) VALUES(
                  %s,%s,4,'Pendente','Validação sintética',%s,'AMBIENTE SINTETICO E2E',
                  NOW(),NOW(),'oraculo_teste','teste-e2e@example.invalid',
                  'VALIDACAO_E2E','v9-e2e','AGUARDANDO_APROVACAO_FISCAL','DUPLICADO',
                  'DUPLICADO',%s,'Contexto sintético exclusivo para teste E2E',
                  TRUE,NOW(),NULL,%s,NOW()+INTERVAL '30 minutes','E2E_PREPARADO'
                )
                ON CONFLICT(id) DO UPDATE SET
                  titulo=EXCLUDED.titulo,status_num=EXCLUDED.status_num,
                  status_nome=EXCLUDED.status_nome,tipo_servico=EXCLUDED.tipo_servico,
                  descricao=EXCLUDED.descricao,localizacao=EXCLUDED.localizacao,
                  data_abertura=EXCLUDED.data_abertura,
                  data_ultima_mudanca=EXCLUDED.data_ultima_mudanca,
                  solicitante=EXCLUDED.solicitante,
                  email_solicitante=EXCLUDED.email_solicitante,
                  origem_ingestao=EXCLUDED.origem_ingestao,wf_version=EXCLUDED.wf_version,
                  triagem_status=EXCLUDED.triagem_status,
                  classificacao=EXCLUDED.classificacao,
                  classificacao_final=EXCLUDED.classificacao_final,
                  duplicado_de_id=EXCLUDED.duplicado_de_id,
                  motivo_classificacao=EXCLUDED.motivo_classificacao,
                  em_aprovacao_fiscal=EXCLUDED.em_aprovacao_fiscal,
                  aprovacao_iniciada_em=EXCLUDED.aprovacao_iniciada_em,
                  aprovacao_decidida_em=NULL,decisao_fiscal=NULL,
                  fiscal_decision_token=EXCLUDED.fiscal_decision_token,
                  fiscal_token_expira_em=EXCLUDED.fiscal_token_expira_em,
                  ultima_acao_workflow=EXCLUDED.ultima_acao_workflow
                WHERE tickets_processados.titulo LIKE %s
                """,
                (
                    target_id,
                    f"{TEST_PREFIX} ALVO {run_id}",
                    f"{TEST_PREFIX} Chamado alvo; não atender.",
                    reference_id,
                    fiscal_token,
                    f"{TEST_PREFIX}%",
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Conflito com registro PostgreSQL não sintético no alvo")
            cursor.execute(
                """
                UPDATE tickets_processados
                SET triagem_status=CASE
                      WHEN id=%s THEN 'VALIDACAO_E2E_REFERENCIA'
                      ELSE 'AGUARDANDO_APROVACAO_FISCAL'
                    END,
                    fila_enfileirada_em=NULL,fila_disponivel_em=NULL,
                    fila_liberar_em=NULL,fila_reservada_em=NULL,
                    fila_ultimo_erro=NULL,atualizado_em=NOW()
                WHERE id IN (%s,%s)
                  AND titulo LIKE %s
                """,
                (reference_id, reference_id, target_id, f"{TEST_PREFIX}%"),
            )
            if cursor.rowcount != 2:
                raise RuntimeError("Isolamento inicial não alcançou os dois tickets sintéticos")
            cursor.execute(
                """
                INSERT INTO dataset_controle(
                  ticket_id,origem,cenario_controle,duplicado_esperado,
                  referencia_duplicado_esperada,observacao,run_id,case_id,episode_id,
                  scenario_id,dimension,order_in_episode,reference_case_id,
                  requires_human_review,risk,rationale,label_source,template_family,
                  dataset_version,split
                ) VALUES(
                  %s,'VALIDACAO_E2E_POST','E2E_POST_WEBHOOK',%s,%s,
                  %s,%s,'E2E-REALIZATION-001','E2E-EPISODE-001','E2E01',
                  'DEDUPLICACAO',2,'E2E-REFERENCE-001',TRUE,'ALTO',
                  'Validação técnica isolada dos webhooks','REGRA_SINTETICA',
                  'E2E_WEBHOOK','e2e-webhooks-v1','VALIDACAO'
                )
                """,
                (
                    target_id,
                    expected_duplicate,
                    reference_id if expected_duplicate else None,
                    f"{TEST_PREFIX} Contexto sintético; run_id={run_id}",
                    run_id,
                ),
            )
            cursor.execute(
                """
                INSERT INTO ia_decisoes(
                  ticket_id,workflow_origem,etapa,modelo_ia,versao_modelo,
                  prompt_version,predicao,classe_referencia_id,confianca,
                  justificativa,tentativa_numero,erro_ia,run_id,case_id,episode_id,
                  generation_profile,provedor_ia,papel_modelo,fallback_utilizado,
                  ciclo_tentativa,total_modelos_tentados,modo_execucao,
                  elegivel_eficacia_confirmatoria,criado_em
                ) VALUES(
                  %s,'E2E','DEDUPLICACAO','Local','local-hybrid-v1.8.0',
                  'e2e-dedup','DUPLICADO',%s,1.0,
                  'Decisão sintética determinística para validar confirmação',1,FALSE,
                  %s,'E2E-REALIZATION-001','E2E-EPISODE-001','deterministico-test-only',
                  'LOCAL','LOCAL',FALSE,%s,1,'VALIDACAO',FALSE,NOW()-INTERVAL '1 minute'
                )
                RETURNING id
                """,
                (target_id, reference_id, run_id, f"{run_id}:E2E-REALIZATION-001"),
            )
            decision_id = int(cursor.fetchone()["id"])
            cursor.execute(
                """
                INSERT INTO avaliacoes_humanas(
                  ticket_id,etapa,avaliador,decisao_ia,observacao,avaliacao_token,
                  avaliacao_token_expira_em,status_avaliacao,origem_amostra,
                  solicitado_em,run_id,case_id,episode_id,fonte_gabarito
                ) VALUES(
                  %s,'DEDUPLICACAO',NULL,'DUPLICADO',%s,%s,
                  NOW()+INTERVAL '30 minutes','PENDENTE','WF05_AMOSTRA_E2E',NOW(),
                  %s,'E2E-REALIZATION-001','E2E-EPISODE-001',NULL
                ) RETURNING id
                """,
                (
                    target_id,
                    f"{TEST_PREFIX} Avaliação sintética; ia_decisao_id={decision_id}",
                    review_token,
                    run_id,
                ),
            )
        connection.commit()


def snapshot(run_id: str, target_id: int) -> dict[str, Any]:
    rows = oracle.query(
        """
        SELECT jsonb_build_object(
          'ticket',(
            SELECT jsonb_build_object(
              'id',id,'status_num',status_num,'status_nome',status_nome,
              'triagem_status',triagem_status,'classificacao',classificacao,
              'classificacao_final',classificacao_final,'duplicado_de_id',duplicado_de_id,
              'em_aprovacao_fiscal',em_aprovacao_fiscal,'decisao_fiscal',decisao_fiscal,
              'token_presente',fiscal_decision_token IS NOT NULL,
              'fiscal_token_expira_em',fiscal_token_expira_em,
              'fiscal_token_expirado',(
                fiscal_token_expira_em IS NOT NULL AND fiscal_token_expira_em<=NOW()
              ),
              'motivo_classificacao',motivo_classificacao,
              'fila_etapa',fila_etapa,
              'fila_enfileirada_em',fila_enfileirada_em,
              'fila_reservada_em',fila_reservada_em,
              'ultima_acao_workflow',ultima_acao_workflow
            ) FROM tickets_processados WHERE id=%s
          ),
          'avaliacao',(
            SELECT jsonb_build_object(
              'id',id,'status_avaliacao',status_avaliacao,
              'ia_estava_correta',ia_estava_correta,'decisao_ia',decisao_ia,
              'decisao_humana',decisao_humana,'classe_correta',classe_correta,
              'fonte_gabarito',fonte_gabarito
            ) FROM avaliacoes_humanas
            WHERE ticket_id=%s AND run_id=%s ORDER BY id DESC LIMIT 1
          ),
          'auto_confirmacoes',(
            SELECT COALESCE(jsonb_agg(jsonb_build_object(
              'id',id,'tipo',tipo_confirmacao,'status',status,'tentativas',tentativas,
              'decisao_webhook',decisao_webhook
            ) ORDER BY tipo_confirmacao),'[]'::jsonb)
            FROM avaliacao_auto_confirmacoes WHERE run_id=%s
          ),
          'eventos_wf04',(SELECT COUNT(*) FROM workflow_eventos WHERE ticket_id=%s AND workflow='WF04'),
          'eventos_wf04_rejeitado',(
            SELECT COUNT(*) FROM workflow_eventos
            WHERE ticket_id=%s AND workflow='WF04' AND acao='DUPLICIDADE_REJEITADA'
          ),
          'eventos_wf04_confirmado',(
            SELECT COUNT(*) FROM workflow_eventos
            WHERE ticket_id=%s AND workflow='WF04' AND acao='DUPLICIDADE_CONFIRMADA'
          ),
          'eventos_wf05',(SELECT COUNT(*) FROM workflow_eventos WHERE ticket_id=%s AND workflow='WF05')
        ) AS estado
        """,
        (
            target_id,
            target_id,
            run_id,
            run_id,
            target_id,
            target_id,
            target_id,
            target_id,
        ),
    )
    return scalar(rows[0]["estado"])


def set_fiscal_token_expiry(target_id: int, expired: bool) -> None:
    with oracle.connect_pg() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE tickets_processados
                SET fiscal_token_expira_em = CASE WHEN %s
                      THEN NOW()-INTERVAL '1 minute'
                      ELSE NOW()+INTERVAL '30 minutes'
                    END,
                    atualizado_em=NOW()
                WHERE id=%s AND titulo LIKE %s
                """,
                (expired, target_id, f"{TEST_PREFIX}%"),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Token fiscal não pertence ao ticket sintético esperado")
        connection.commit()


def assert_rejected_ticket_immutable(
    label: str,
    response: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
) -> None:
    if response.get("http_status") != 409:
        raise AssertionError(
            f"{label} deveria responder HTTP 409; recebeu "
            f"{response.get('http_status')}"
        )
    if before.get("ticket") != after.get("ticket"):
        raise AssertionError(f"{label} alterou o ticket")


def probe_expired_fiscal_token(
    action: dict[str, Any],
    env: dict[str, str],
    run_id: str,
    target_id: int,
) -> dict[str, Any]:
    """Exercise the real expired-token path and always restore validity."""
    set_fiscal_token_expiry(target_id, True)
    try:
        before = snapshot(run_id, target_id)
        if before["ticket"].get("fiscal_token_expirado") is not True:
            raise AssertionError("Preparação não tornou o token fiscal expirado")
        response = oracle_request(action, env)
        after = snapshot(run_id, target_id)
        assert_rejected_ticket_immutable(
            "POST com token fiscal expirado",
            response,
            before,
            after,
        )
    finally:
        set_fiscal_token_expiry(target_id, False)

    restored = snapshot(run_id, target_id)
    if restored["ticket"].get("fiscal_token_expirado") is not False:
        raise AssertionError("Validade do token fiscal não foi restaurada")
    if restored["ticket"].get("token_presente") is not True:
        raise AssertionError("Restauração removeu o token fiscal")
    return {
        "post": response,
        "state_before": before["ticket"],
        "state_after": after["ticket"],
        "ticket_immutable": before["ticket"] == after["ticket"],
        "validity_restored": True,
        "state_after_restore": restored["ticket"],
    }


def probe_invalid_fiscal_token(
    action: dict[str, Any],
    env: dict[str, str],
    run_id: str,
    target_id: int,
) -> dict[str, Any]:
    token = str(action.get("token_endpoint") or "")
    wrong_token = "0" * len(token)
    if wrong_token == token:
        wrong_token = "f" * len(token)
    if not re.fullmatch(r"[a-f0-9]{32,128}", wrong_token, re.IGNORECASE):
        raise AssertionError("Não foi possível construir token fiscal inválido seguro")
    invalid_action = {**action, "token_endpoint": wrong_token}
    before = snapshot(run_id, target_id)
    response = oracle_request(invalid_action, env)
    after = snapshot(run_id, target_id)
    assert_rejected_ticket_immutable(
        "POST com token fiscal inválido",
        response,
        before,
        after,
    )
    return {
        "post": response,
        "state_before": before["ticket"],
        "state_after": after["ticket"],
        "ticket_immutable": before["ticket"] == after["ticket"],
    }


def validate_concurrent_fiscal_responses(
    responses: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if len(responses) != 2:
        raise AssertionError("A corrida fiscal exige exatamente dois POSTs")
    accepted = [item for item in responses if item.get("http_status") == 202]
    competing = [item for item in responses if item.get("http_status") != 202]
    if len(accepted) != 1 or len(competing) != 1:
        raise AssertionError(
            "Dois POSTs concorrentes devem produzir exatamente um HTTP 202; "
            f"obtido {[item.get('http_status') for item in responses]}"
        )
    if competing[0].get("http_status") not in {200, 409}:
        raise AssertionError(
            "POST concorrente não vencedor deve responder somente 200 ou 409; "
            f"recebeu {competing[0].get('http_status')}"
        )
    return accepted[0], competing[0]


def request(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    started = time.perf_counter()
    response = requests.request(method, url, timeout=30, allow_redirects=False, **kwargs)
    summary = str(response.text or "")[:240]
    summary = re.sub(r"\b[a-fA-F0-9]{32,128}\b", "<redacted>", summary)
    return {
        "http_status": int(response.status_code),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "content_type": str(response.headers.get("Content-Type") or ""),
        "contains_form": "<form" in str(response.text or "").lower(),
        "body_summary": summary,
    }


def oracle_request(action: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    common = {
        "fonte": "ORACULO_GABARITO",
        "run_id": action["run_id"],
        "scenario_id": action["scenario_id"],
        "realization_id": action["realization_id"],
    }
    if action["tipo_confirmacao"] == "FISCAL_DUPLICIDADE":
        url = env["FISCAL_WEBHOOK_URL"]
        params = {
            **common,
            "decisao": action["decisao_webhook"],
            "chamado_id": action["ticket_id"],
            "token": action["token_endpoint"],
        }
    else:
        url = env["AVALIACAO_HUMANA_WEBHOOK_URL"]
        params = {
            **common,
            "token": action["token_endpoint"],
            "resultado": action["decisao_webhook"],
            "avaliador": "oraculo_gabarito",
        }
        if action.get("classe_correta_webhook"):
            params["classe_correta"] = action["classe_correta_webhook"]
    headers = {
        "X-Test-Mode": "true",
        "X-Test-Auto-Review-Token": env["TEST_AUTO_REVIEW_TOKEN"],
        "X-Test-Auto-Review-Nonce": action["assessor_nonce"],
        "X-Test-Run-Id": action["run_id"],
        "X-Test-Scenario-Id": action["scenario_id"],
        "X-Test-Realization-Id": action["realization_id"],
    }
    return request("POST", url, params=params, headers=headers, data=b"")


def reconcile(run_id: str) -> None:
    with oracle.connect_pg() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (9062027,))
            oracle._reconcile_oracle_actions(cursor, run_id)
        connection.commit()


def acquire_wf06_reservation_lock():
    """Impede o scheduler de consumir o handoff enquanto ele é auditado."""
    connection = oracle.connect_pg()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (9062026,))
        return connection
    except Exception:
        connection.close()
        raise


def assert_fiscal_outcome(state: dict[str, Any], decision: str) -> None:
    ticket = state["ticket"]
    if decision == "confirmar":
        if ticket["triagem_status"] != "DUPLICADO_FECHADO":
            raise AssertionError("WF04 não concluiu DUPLICADO_FECHADO")
        if ticket["decisao_fiscal"] != "CONFIRMOU_DUP":
            raise AssertionError("WF04 não registrou CONFIRMOU_DUP")
        if int(state.get("eventos_wf04_confirmado") or 0) != 1:
            raise AssertionError("WF04 não registrou uma única DUPLICIDADE_CONFIRMADA")
        return

    expected_null = (
        "classificacao",
        "classificacao_final",
        "duplicado_de_id",
        "motivo_classificacao",
    )
    failures: list[str] = []
    if ticket["decisao_fiscal"] != "REJEITOU_DUP":
        failures.append("decisao_fiscal")
    if ticket["triagem_status"] != "PENDENTE_FILA_IA":
        failures.append("triagem_status")
    if ticket["fila_etapa"] != "CLASSIFICACAO":
        failures.append("fila_etapa")
    if ticket["em_aprovacao_fiscal"] is not False:
        failures.append("em_aprovacao_fiscal")
    if ticket["token_presente"] is not False:
        failures.append("fiscal_decision_token")
    if ticket["fila_enfileirada_em"] is None:
        failures.append("fila_enfileirada_em")
    if ticket["fila_reservada_em"] is not None:
        failures.append("fila_reservada_em")
    failures.extend(name for name in expected_null if ticket[name] is not None)
    if int(state.get("eventos_wf04_rejeitado") or 0) != 1:
        failures.append("evento_DUPLICIDADE_REJEITADA")
    if ticket["ultima_acao_workflow"] != "WF04_ENFILEIROU_CLASSIFICACAO":
        failures.append("ultima_acao_workflow")
    if failures:
        raise AssertionError(
            "WF04 não concluiu o handoff negativo esperado: " + ", ".join(failures)
        )


def wait_fiscal_state(
    run_id: str,
    target_id: int,
    decision: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error: AssertionError | None = None
    while True:
        state = snapshot(run_id, target_id)
        try:
            assert_fiscal_outcome(state, decision)
            return state
        except AssertionError as exc:
            last_error = exc
        if time.monotonic() >= deadline:
            raise TimeoutError(
                "WF04 não concluiu a decisão fiscal dentro da janela: "
                + str(last_error or "estado inesperado")
            ) from last_error
        time.sleep(0.5)


def wait_event_audit(
    run_id: str,
    target_id: int,
    workflow: str,
    previous_count: int,
    timeout: float = 10.0,
) -> dict[str, Any]:
    key = f"eventos_{workflow.lower()}"
    deadline = time.monotonic() + timeout
    while True:
        state = snapshot(run_id, target_id)
        if int(state[key]) > int(previous_count):
            return state
        if time.monotonic() >= deadline:
            return state
        time.sleep(0.25)


def mark_experiment(run_id: str, status: str, note: str | None = None) -> None:
    oracle.execute(
        """
        UPDATE experimentos_avaliacao
        SET status=%s,concluido_em=NOW(),
            generation_config=COALESCE(generation_config,'{}'::jsonb)
              || jsonb_build_object('resultado_e2e',%s)
        WHERE run_id=%s
        """,
        (status, note or status, run_id),
    )


def cleanup_database(
    run_id: str,
    ticket_ids: list[int],
    reference_id: int | None = None,
) -> list[dict[str, Any]]:
    ids = sorted({int(ticket_id) for ticket_id in ticket_ids if int(ticket_id) > 0})
    if not ids:
        return []
    with oracle.connect_pg() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO workflow_eventos(
                  ticket_id,workflow,node_name,fase,acao,status_evento,
                  status_anterior,status_novo,erro,mensagem_erro,inicio_em,fim_em
                )
                SELECT id,'E2E_VALIDACAO','Cleanup fila sintética','ISOLAMENTO_TESTE',
                       'REMOVER_TICKET_SINTETICO_DA_FILA','OK',
                       COALESCE(triagem_status,''),
                       CASE WHEN id=%s THEN 'VALIDACAO_E2E_REFERENCIA_ENCERRADA'
                            WHEN triagem_status='DUPLICADO_FECHADO' THEN triagem_status
                            ELSE 'VALIDACAO_E2E_ENCERRADO' END,
                       FALSE,'Cleanup limitado ao run sintético ' || %s,NOW(),NOW()
                FROM tickets_processados
                WHERE id=ANY(%s) AND titulo LIKE %s
                """,
                (
                    reference_id or -1,
                    run_id,
                    ids,
                    f"{TEST_PREFIX}%",
                ),
            )
            cursor.execute(
                """
                UPDATE tickets_processados
                SET status_num=6,status_nome='Fechado',
                    triagem_status=CASE
                      WHEN id=%s THEN 'VALIDACAO_E2E_REFERENCIA_ENCERRADA'
                      WHEN triagem_status='DUPLICADO_FECHADO' THEN triagem_status
                      ELSE 'VALIDACAO_E2E_ENCERRADO'
                    END,
                    em_aprovacao_fiscal=FALSE,
                    fiscal_decision_token=NULL,fiscal_token_expira_em=NULL,
                    fila_enfileirada_em=NULL,fila_disponivel_em=NULL,
                    fila_liberar_em=NULL,fila_reservada_em=NULL,
                    fila_ultimo_erro=NULL,
                    ultima_acao_workflow='E2E_CLEANUP_FILA_ISOLADA',
                    log_workflow=COALESCE(log_workflow,'[]'::jsonb)
                      || jsonb_build_object(
                           'wf','E2E_VALIDACAO','acao','CLEANUP_FILA_SINTETICA',
                           'run_id',%s,'ts',NOW()
                         ),
                    atualizado_em=NOW()
                WHERE id=ANY(%s) AND titulo LIKE %s
                RETURNING id,triagem_status,status_num,status_nome,
                          fila_enfileirada_em,fila_disponivel_em,
                          fila_liberar_em,fila_reservada_em
                """,
                (
                    reference_id or -1,
                    run_id,
                    ids,
                    f"{TEST_PREFIX}%",
                ),
            )
            rows = [scalar(dict(row)) for row in cursor.fetchall()]
        connection.commit()
    return rows


@serialized_experiment(oracle.connect_pg, "VALIDACAO_E2E_WEBHOOKS")
def validate(run_id: str, output_dir: Path, decision: str = "confirmar") -> dict[str, Any]:
    if decision not in {"confirmar", "nao_duplicado"}:
        raise ValueError("decision deve ser confirmar ou nao_duplicado")
    env = require_test_environment()
    env["FISCAL_WEBHOOK_URL"] = "http://127.0.0.1:5678/webhook/fiscal-decisao-fiscal-ic-2026"
    env["AVALIACAO_HUMANA_WEBHOOK_URL"] = "http://127.0.0.1:5678/webhook/avaliacao-humana-v9"
    fiscal_token = hashlib.sha256(f"fiscal:{run_id}".encode()).hexdigest()
    review_token = hashlib.sha256(f"review:{run_id}".encode()).hexdigest()
    created_ids: list[int] = []
    result: dict[str, Any] = {
        "schema_version": "e2e-webhooks-v3",
        "run_id": run_id,
        "fiscal_decision_under_test": decision,
        "natureza_evidencia": "VALIDACAO_TECNICA_NAO_CONFIRMATORIA",
        "synthetic_only": True,
        "workflow_artifacts": workflow_artifact_manifest(),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    database_prepared = False
    queue_lock_connection = None
    passed = False
    error_message: str | None = None
    glpi = GlpiSession(
        host_glpi_url(env.get("GLPI_API_URL", "")),
        env["GLPI_APP_TOKEN"],
        env["GLPI_AUTH_BASIC"],
    )
    try:
        assert_no_active_calibration()
        with glpi:
            reference_id = glpi.create_ticket(f"{TEST_PREFIX} REFERENCIA {run_id}")
            created_ids.append(reference_id)
            target_id = glpi.create_ticket(f"{TEST_PREFIX} ALVO {run_id}")
            created_ids.append(target_id)
            result["ids"] = {
                "glpi_reference_ticket_id": reference_id,
                "glpi_target_ticket_id": target_id,
            }
            prepare_database(
                run_id,
                target_id,
                reference_id,
                fiscal_token,
                review_token,
                decision,
            )
            database_prepared = True
            if decision == "nao_duplicado":
                queue_lock_connection = acquire_wf06_reservation_lock()
                result["wf06_reservation_lock_held_during_assertions"] = True
            guard_env = oracle._oracle_guard(run_id)
            actions = oracle._reserve_oracle_actions(run_id, 10)
            by_type = {action["tipo_confirmacao"]: action for action in actions}
            if set(by_type) != {"FISCAL_DUPLICIDADE", "AVALIACAO_METRICA"}:
                raise AssertionError(f"Reservas inesperadas: {sorted(by_type)}")
            if by_type["FISCAL_DUPLICIDADE"]["decisao_webhook"] != decision:
                raise AssertionError("Ação fiscal reservada diverge da decisão solicitada")
            result["ids"].update(
                {
                    "wf04_auto_confirmation_id": by_type["FISCAL_DUPLICIDADE"]["auto_confirmacao_id"],
                    "wf05_auto_confirmation_id": by_type["AVALIACAO_METRICA"]["auto_confirmacao_id"],
                }
            )

            before_get = snapshot(run_id, target_id)
            get_wf04 = request(
                "GET",
                "http://127.0.0.1:5678/webhook/fiscal-confirmacao-v9",
                params={
                    "decisao": decision,
                    "chamado_id": target_id,
                    "ref_id": reference_id,
                    "token": fiscal_token,
                },
            )
            after_get_wf04 = snapshot(run_id, target_id)
            if before_get != after_get_wf04:
                raise AssertionError("GET de WF04 alterou o estado persistido")
            get_wf05 = request(
                "GET",
                "http://127.0.0.1:5678/webhook/avaliacao-humana-confirmacao-v9",
                params={
                    "token": review_token,
                    "resultado": "correta" if decision == "confirmar" else "incorreta",
                },
            )
            after_get_wf05 = snapshot(run_id, target_id)
            if before_get != after_get_wf05:
                raise AssertionError("GET de WF05 alterou o estado persistido")
            for label, response in (("WF04", get_wf04), ("WF05", get_wf05)):
                if response["http_status"] != 200 or not response["contains_form"]:
                    raise AssertionError(f"GET preview {label} inválido: HTTP {response['http_status']}")

            wf05_action = by_type["AVALIACAO_METRICA"]
            wf05_first = oracle_request(wf05_action, guard_env)
            if wf05_first["http_status"] != 200:
                raise AssertionError(f"Primeiro POST WF05: HTTP {wf05_first['http_status']}")
            oracle._finish_oracle_action(wf05_action, True, wf05_first["http_status"], None)
            reconcile(run_id)
            after_wf05 = snapshot(run_id, target_id)
            if after_wf05["avaliacao"]["status_avaliacao"] != "CONCLUIDA":
                raise AssertionError("WF05 não concluiu a avaliação")
            if after_wf05["avaliacao"]["fonte_gabarito"] != "ORACULO_GABARITO":
                raise AssertionError("WF05 não registrou a proveniência do oráculo")
            expected_correct = decision == "confirmar"
            if after_wf05["avaliacao"]["ia_estava_correta"] is not expected_correct:
                raise AssertionError("WF05 registrou concordância divergente do gabarito")
            if (
                decision == "nao_duplicado"
                and after_wf05["avaliacao"]["classe_correta"] != "NAO_DUPLICADO"
            ):
                raise AssertionError("WF05 não registrou NAO_DUPLICADO como classe correta")
            wf05_replay = oracle_request(wf05_action, guard_env)
            after_wf05_replay = snapshot(run_id, target_id)
            if (
                wf05_replay["http_status"] != 403
                or after_wf05_replay["avaliacao"] != after_wf05["avaliacao"]
            ):
                raise AssertionError("Replay de WF05 não falhou fechado de forma idempotente")

            wf04_action = by_type["FISCAL_DUPLICIDADE"]
            expired_token_evidence = probe_expired_fiscal_token(
                wf04_action,
                guard_env,
                run_id,
                target_id,
            )
            invalid_token_evidence = probe_invalid_fiscal_token(
                wf04_action,
                guard_env,
                run_id,
                target_id,
            )
            before_concurrent_posts = snapshot(run_id, target_id)
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(oracle_request, wf04_action, guard_env)
                    for _ in range(2)
                ]
                concurrent_responses = [future.result() for future in futures]
            wf04_first, wf04_competing = validate_concurrent_fiscal_responses(
                concurrent_responses
            )
            after_wf04 = wait_fiscal_state(run_id, target_id, decision)
            transition_event_key = (
                "eventos_wf04_confirmado"
                if decision == "confirmar"
                else "eventos_wf04_rejeitado"
            )
            transition_event_delta = int(after_wf04[transition_event_key]) - int(
                before_concurrent_posts[transition_event_key]
            )
            if transition_event_delta != 1:
                raise AssertionError(
                    "A corrida fiscal produziu número inesperado de transições: "
                    f"{transition_event_delta}"
                )
            oracle._finish_oracle_action(wf04_action, True, wf04_first["http_status"], None)
            reconcile(run_id)
            after_wf04 = snapshot(run_id, target_id)
            assert_fiscal_outcome(after_wf04, decision)
            wf04_replay = oracle_request(wf04_action, guard_env)
            after_wf04_replay = wait_event_audit(
                run_id,
                target_id,
                "WF04",
                int(after_wf04["eventos_wf04"]),
            )
            if (
                wf04_replay["http_status"] != 409
                or after_wf04_replay["ticket"] != after_wf04["ticket"]
            ):
                raise AssertionError("Replay de WF04 não falhou fechado de forma idempotente")

            result["wf04"] = {
                "get_preview": get_wf04,
                "expired_token_before_valid_decision": expired_token_evidence,
                "invalid_token_after_oracle_reservation": invalid_token_evidence,
                "concurrent_posts": {
                    "responses": concurrent_responses,
                    "status_codes": [
                        item["http_status"] for item in concurrent_responses
                    ],
                    "accepted_http_202_count": 1,
                    "competing_response": wf04_competing,
                    "single_transition_event": transition_event_delta == 1,
                    "transition_event_delta": transition_event_delta,
                },
                "post_first": wf04_first,
                "post_competing": wf04_competing,
                "post_replay": wf04_replay,
                "state_before": before_get["ticket"],
                "state_before_concurrent_posts": before_concurrent_posts["ticket"],
                "state_after": after_wf04["ticket"],
                "state_after_replay": after_wf04_replay["ticket"],
                "workflow_event_count_delta_concurrent_posts": (
                    after_wf04["eventos_wf04"]
                    - before_concurrent_posts["eventos_wf04"]
                ),
                "workflow_event_count_delta_replay": (
                    after_wf04_replay["eventos_wf04"] - after_wf04["eventos_wf04"]
                ),
                "state_transition_once": True,
                "idempotent": after_wf04_replay["ticket"] == after_wf04["ticket"],
            }
            result["wf05"] = {
                "get_preview": get_wf05,
                "post_first": wf05_first,
                "post_replay": wf05_replay,
                "state_before": before_get["avaliacao"],
                "state_after": after_wf05["avaliacao"],
                "state_after_replay": after_wf05_replay["avaliacao"],
                "workflow_event_count_delta_first_post": (
                    after_wf05["eventos_wf05"] - before_get["eventos_wf05"]
                ),
                "workflow_event_count_delta_replay": (
                    after_wf05_replay["eventos_wf05"] - after_wf05["eventos_wf05"]
                ),
                "state_transition_once": True,
                "idempotent": (
                    after_wf05_replay["avaliacao"] == after_wf05["avaliacao"]
                ),
            }
            result["get_preview_no_mutation"] = (
                before_get == after_get_wf04 == after_get_wf05
            )
            passed = True
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        result["error"] = error_message
        raise
    finally:
        closed_ids: list[int] = []
        try:
            if created_ids:
                with GlpiSession(
                    glpi.base_url, glpi.app_token, glpi.auth_basic
                ) as cleanup_glpi:
                    for ticket_id in created_ids:
                        cleanup_glpi.close_synthetic_ticket(ticket_id)
                        if int(cleanup_glpi.get_ticket(ticket_id).get("status") or 0) == 6:
                            closed_ids.append(ticket_id)
                if set(closed_ids) != set(created_ids):
                    raise RuntimeError("Nem todos os chamados sintéticos foram encerrados")
        except Exception as cleanup_exc:
            result["cleanup_warning"] = f"{type(cleanup_exc).__name__}: {cleanup_exc}"
            passed = False
            if error_message is None:
                error_message = result["cleanup_warning"]
        if created_ids:
            try:
                result["database_queue_cleanup"] = cleanup_database(
                    run_id,
                    created_ids,
                    int(result.get("ids", {}).get("glpi_reference_ticket_id") or -1),
                )
                cleanup_rows = result["database_queue_cleanup"]
                if len(cleanup_rows) != len(set(created_ids)):
                    raise RuntimeError("Cleanup não alcançou todos os tickets sintéticos")
                queue_fields = (
                    "fila_enfileirada_em",
                    "fila_disponivel_em",
                    "fila_liberar_em",
                    "fila_reservada_em",
                )
                if any(
                    row.get(field) is not None
                    for row in cleanup_rows
                    for field in queue_fields
                ):
                    raise RuntimeError("Cleanup deixou estado residual na fila")
            except Exception as cleanup_exc:
                result["database_cleanup_warning"] = (
                    f"{type(cleanup_exc).__name__}: {cleanup_exc}"
                )
                passed = False
                if error_message is None:
                    error_message = result["database_cleanup_warning"]
        if queue_lock_connection is not None:
            try:
                queue_lock_connection.rollback()
            finally:
                queue_lock_connection.close()
                result["wf06_reservation_lock_released_after_cleanup"] = True
        if database_prepared:
            mark_experiment(run_id, "CONCLUIDO" if passed else "FALHOU", error_message)
        result["glpi_synthetic_tickets_closed"] = bool(created_ids) and (
            set(closed_ids) == set(created_ids)
        )
        result["passed"] = passed
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        output_dir.mkdir(parents=True, exist_ok=False)
        (output_dir / "resultado.json").write_text(
            json.dumps(scalar(result), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        lines = [
            "# Validação E2E dos webhooks WF04 e WF05",
            "",
            f"- run_id: `{run_id}`",
            f"- decisão fiscal testada: `{decision}`",
            "- natureza: validação técnica automatizada, sintética e não confirmatória",
            f"- resultado: **{'APROVADO' if passed else 'FALHOU'}**",
            f"- chamados GLPI sintéticos: `{', '.join(map(str, created_ids))}`",
            f"- chamados sintéticos encerrados ao final: `{bool(created_ids)}`",
            "",
            "Tokens, nonces e segredos não são persistidos neste artefato.",
        ]
        if passed:
            lines += [
                "",
                "## Evidências",
                "",
                f"- WF04 GET preview: HTTP {result['wf04']['get_preview']['http_status']}, sem mutação.",
                "- WF04 token expirado antes da decisão válida: HTTP "
                f"{result['wf04']['expired_token_before_valid_decision']['post']['http_status']}, "
                "ticket imutável e validade restaurada.",
                "- WF04 token inválido após a reserva do oráculo: HTTP "
                f"{result['wf04']['invalid_token_after_oracle_reservation']['post']['http_status']}, "
                "ticket imutável.",
                "- WF04 corrida com dois POSTs reais: códigos "
                f"`{result['wf04']['concurrent_posts']['status_codes']}`, exatamente "
                "um HTTP 202 e uma única transição persistida.",
                f"- WF04 replay após conclusão: HTTP {result['wf04']['post_replay']['http_status']} e sem nova transição.",
                f"- WF05 GET preview: HTTP {result['wf05']['get_preview']['http_status']}, sem mutação.",
                f"- WF05 POST válido: HTTP {result['wf05']['post_first']['http_status']}; replay: HTTP {result['wf05']['post_replay']['http_status']} e sem nova transição.",
            ]
        else:
            lines += ["", "## Falha", "", error_message or "Falha não especificada."]
        (output_dir / "RELATORIO.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Valida GET/POST/idempotência de WF04 e WF05 somente com chamados sintéticos."
    )
    parser.add_argument("--run-id")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--decision",
        choices=("confirmar", "nao_duplicado"),
        default="confirmar",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = args.run_id or datetime.now(timezone.utc).strftime(
        "VALIDACAO-POSTS-E2E-%Y%m%dT%H%M%SZ"
    )
    if not RUN_RE.fullmatch(run_id):
        raise SystemExit("run_id inválido ou sem a marca sintética obrigatória")
    output_dir = (args.output_dir or (
        ROOT / "avaliacao" / "resultados" / run_id.lower()
    )).resolve()
    results_root = (ROOT / "avaliacao" / "resultados").resolve()
    try:
        output_dir.relative_to(results_root)
    except ValueError as exc:
        raise SystemExit("output-dir deve ficar dentro de avaliacao/resultados") from exc
    result = validate(run_id, output_dir, args.decision)
    print(
        json.dumps(
            {
                "run_id": run_id,
                "decision": args.decision,
                "passed": result["passed"],
                "output_dir": str(output_dir.resolve()),
                "ticket_ids": result.get("ids", {}),
                "wf04_http": {
                    "get": result.get("wf04", {}).get("get_preview", {}).get("http_status"),
                    "post": result.get("wf04", {}).get("post_first", {}).get("http_status"),
                    "replay": result.get("wf04", {}).get("post_replay", {}).get("http_status"),
                },
                "wf05_http": {
                    "get": result.get("wf05", {}).get("get_preview", {}).get("http_status"),
                    "post": result.get("wf05", {}).get("post_first", {}).get("http_status"),
                    "replay": result.get("wf05", {}).get("post_replay", {}).get("http_status"),
                },
            },
            ensure_ascii=False,
        )
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
