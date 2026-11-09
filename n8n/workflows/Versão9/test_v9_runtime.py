"""Preflight e teste E2E controlado dos webhooks da V9.

O modo padrao, ``--preflight``, nao altera tickets nem o banco: ele verifica a
saude do n8n, a rejeicao de uma chave invalida pelo WF06 e a pagina de preview
invalida do WF04. O modo ``--fiscal-preparado`` e opt-in e somente aceita um
ticket sintetico ja colocado em aprovacao fiscal por um roteiro de teste.

Nenhuma credencial possui valor padrao. Segredos sao lidos exclusivamente de
variaveis de ambiente e nunca sao escritos na saida.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import ipaddress
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

import requests


WF06_INGRESS_PATH = "/webhook/glpi-ticket-fila-ia-v9"
WF04_PREVIEW_PATH = "/webhook/fiscal-confirmacao-v9"
WF04_DECISION_PATH = "/webhook/fiscal-decisao-fiscal-ic-2026"
DEFAULT_SYNTHETIC_PREFIX = "[TESTE_AUTOMATIZADO_E2E_"
HEX_TOKEN_RE = re.compile(r"^[a-f0-9]{32,128}$", re.IGNORECASE)


class HttpClient(Protocol):
    def get(self, url: str, **kwargs: Any) -> requests.Response: ...

    def post(self, url: str, **kwargs: Any) -> requests.Response: ...


def _env(name: str, *, required: bool = False, default: str = "") -> str:
    value = str(os.environ.get(name, default)).strip()
    if required and (not value or value.upper() in {"CHANGE_ME", "CHANGEME"}):
        raise RuntimeError(f"Variavel de ambiente obrigatoria ausente: {name}")
    return value


def _true(name: str) -> bool:
    return _env(name).lower() == "true"


def _clean_base_url(value: str, name: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError(f"{name} deve ser uma URL HTTP(S) valida")
    return value.rstrip("/")


def _is_loopback_url(value: str) -> bool:
    host = urlparse(value).hostname or ""
    if host.lower() in {"localhost", "host.docker.internal"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _assert_safe_target(*urls: str) -> None:
    if _true("V9_E2E_ALLOW_REMOTE"):
        return
    remote = [url for url in urls if not _is_loopback_url(url)]
    if remote:
        raise RuntimeError(
            "Teste remoto bloqueado. Use somente localhost ou defina "
            "V9_E2E_ALLOW_REMOTE=true de forma consciente."
        )


@dataclass(frozen=True)
class RuntimeConfig:
    n8n_base_url: str
    request_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        raw_timeout = _env("V9_E2E_HTTP_TIMEOUT_SECONDS", default="20")
        try:
            timeout = float(raw_timeout)
        except ValueError as exc:
            raise RuntimeError("V9_E2E_HTTP_TIMEOUT_SECONDS deve ser numerico") from exc
        if not 1 <= timeout <= 180:
            raise RuntimeError("V9_E2E_HTTP_TIMEOUT_SECONDS deve ficar entre 1 e 180")
        n8n_raw = _env("N8N_BASE_URL") or _env("N8N_PUBLIC_BASE_URL")
        if not n8n_raw:
            raise RuntimeError(
                "Variavel de ambiente obrigatoria ausente: "
                "N8N_BASE_URL ou N8N_PUBLIC_BASE_URL"
            )
        n8n = _clean_base_url(n8n_raw, "N8N_BASE_URL")
        _assert_safe_target(n8n)
        return cls(n8n_base_url=n8n, request_timeout_seconds=timeout)

    def endpoint(self, path: str) -> str:
        return f"{self.n8n_base_url}{path}"


@dataclass(frozen=True)
class PreparedFiscalCase:
    ticket_id: int
    token: str
    decision: str
    reference_id: int | None
    synthetic_prefix: str

    @classmethod
    def from_env(cls) -> "PreparedFiscalCase":
        if not (_true("TEST_MODE") and _true("V9_E2E_MUTATION_TESTS")):
            raise RuntimeError(
                "POST fiscal bloqueado: TEST_MODE=true e "
                "V9_E2E_MUTATION_TESTS=true sao obrigatorios."
            )
        try:
            ticket_id = int(_env("V9_E2E_FISCAL_TICKET_ID", required=True))
        except ValueError as exc:
            raise RuntimeError("V9_E2E_FISCAL_TICKET_ID deve ser inteiro") from exc
        if ticket_id <= 0:
            raise RuntimeError("V9_E2E_FISCAL_TICKET_ID deve ser positivo")
        token = _env("V9_E2E_FISCAL_TOKEN", required=True)
        if not HEX_TOKEN_RE.fullmatch(token):
            raise RuntimeError("V9_E2E_FISCAL_TOKEN possui formato invalido")
        decision = _env("V9_E2E_FISCAL_DECISION", required=True).lower()
        if decision not in {"confirmar", "nao_duplicado"}:
            raise RuntimeError(
                "V9_E2E_FISCAL_DECISION deve ser confirmar ou nao_duplicado"
            )
        reference_raw = _env("V9_E2E_FISCAL_REF_ID")
        try:
            reference_id = int(reference_raw) if reference_raw else None
        except ValueError as exc:
            raise RuntimeError("V9_E2E_FISCAL_REF_ID deve ser inteiro") from exc
        if reference_id is not None and reference_id <= 0:
            raise RuntimeError("V9_E2E_FISCAL_REF_ID deve ser positivo")
        prefix = _env(
            "V9_E2E_SYNTHETIC_PREFIX", default=DEFAULT_SYNTHETIC_PREFIX
        )
        if not prefix.startswith("[TESTE_") or len(prefix) < 12:
            raise RuntimeError(
                "V9_E2E_SYNTHETIC_PREFIX deve identificar inequivocamente um teste"
            )
        return cls(ticket_id, token, decision, reference_id, prefix)

    @property
    def parameters(self) -> dict[str, str | int]:
        values: dict[str, str | int] = {
            "decisao": self.decision,
            "chamado_id": self.ticket_id,
            "token": self.token,
        }
        if self.reference_id is not None:
            values["ref_id"] = self.reference_id
        return values


@dataclass(frozen=True)
class GlpiConfig:
    api_url: str
    app_token: str
    auth_basic: str

    @classmethod
    def from_env(cls) -> "GlpiConfig":
        api_url = _clean_base_url(
            _env("GLPI_API_URL", required=True), "GLPI_API_URL"
        )
        if not api_url.endswith("/apirest.php"):
            raise RuntimeError("GLPI_API_URL deve terminar em /apirest.php")
        _assert_safe_target(api_url)
        app_token = _env("GLPI_APP_TOKEN", required=True)
        auth_basic = _env("GLPI_AUTH_BASIC", required=True)
        if not auth_basic.startswith("Basic "):
            raise RuntimeError("GLPI_AUTH_BASIC deve iniciar com 'Basic '")
        encoded = auth_basic.removeprefix("Basic ").strip()
        try:
            if not base64.b64decode(encoded, validate=True):
                raise ValueError
        except (binascii.Error, ValueError, TypeError) as exc:
            raise RuntimeError("GLPI_AUTH_BASIC possui Base64 invalido") from exc
        return cls(api_url, app_token, auth_basic)


class GlpiReadOnlySession:
    """Sessao usada apenas para confirmar que o alvo e sintetico."""

    def __init__(self, config: GlpiConfig, timeout: float) -> None:
        self.config = config
        self.timeout = timeout
        self.session_token = ""

    def __enter__(self) -> "GlpiReadOnlySession":
        response = requests.get(
            f"{self.config.api_url}/initSession",
            headers={
                "App-Token": self.config.app_token,
                "Authorization": self.config.auth_basic,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        self.session_token = str(response.json().get("session_token") or "")
        if not self.session_token:
            raise RuntimeError("GLPI nao retornou session_token")
        return self

    def __exit__(self, *_: Any) -> None:
        if not self.session_token:
            return
        try:
            requests.get(
                f"{self.config.api_url}/killSession",
                headers=self.headers,
                timeout=self.timeout,
            )
        except requests.RequestException:
            pass

    @property
    def headers(self) -> dict[str, str]:
        return {
            "App-Token": self.config.app_token,
            "Session-Token": self.session_token,
        }

    def snapshot(self, ticket_id: int) -> tuple[str, int]:
        response = requests.get(
            f"{self.config.api_url}/Ticket/{int(ticket_id)}",
            headers=self.headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        ticket = response.json()
        return str(ticket.get("name") or ""), int(ticket.get("status") or 0)


def wf06_ingress(
    client: HttpClient,
    config: RuntimeConfig,
    payload: dict[str, Any],
    webhook_key: str,
) -> requests.Response:
    return client.post(
        config.endpoint(WF06_INGRESS_PATH),
        headers={"X-Webhook-Key": webhook_key},
        json=payload,
        timeout=config.request_timeout_seconds,
    )


def fiscal_preview(
    client: HttpClient, config: RuntimeConfig, case: PreparedFiscalCase
) -> requests.Response:
    return client.get(
        config.endpoint(WF04_PREVIEW_PATH),
        params=case.parameters,
        timeout=config.request_timeout_seconds,
    )


def fiscal_decision(
    client: HttpClient, config: RuntimeConfig, case: PreparedFiscalCase
) -> requests.Response:
    return client.post(
        config.endpoint(WF04_DECISION_PATH),
        data=case.parameters,
        timeout=config.request_timeout_seconds,
    )


def run_preflight(config: RuntimeConfig) -> None:
    health = requests.get(
        config.endpoint("/healthz"), timeout=config.request_timeout_seconds
    )
    health.raise_for_status()

    unauthorized = wf06_ingress(
        requests,
        config,
        {"ticket_id": 1, "source": "v9-safe-preflight"},
        "__invalid_preflight_key__",
    )
    if unauthorized.status_code != 401:
        raise AssertionError(
            f"WF06 deveria rejeitar chave invalida com 401; recebeu "
            f"{unauthorized.status_code}"
        )

    invalid_preview = requests.get(
        config.endpoint(WF04_PREVIEW_PATH),
        params={"decisao": "confirmar", "chamado_id": 1, "token": "invalido"},
        timeout=config.request_timeout_seconds,
    )
    if invalid_preview.status_code != 400:
        raise AssertionError(
            f"Preview WF04 invalido deveria responder 400; recebeu "
            f"{invalid_preview.status_code}"
        )
    if "<form" in invalid_preview.text.lower():
        raise AssertionError("Preview invalido nao pode renderizar formulario de POST")
    print("[OK] Preflight V9 sem mutacao: health, auth WF06 e preview WF04")


def run_prepared_fiscal_case(
    config: RuntimeConfig, case: PreparedFiscalCase
) -> None:
    glpi_config = GlpiConfig.from_env()
    with GlpiReadOnlySession(
        glpi_config, config.request_timeout_seconds
    ) as glpi:
        before = glpi.snapshot(case.ticket_id)
        if not before[0].startswith(case.synthetic_prefix):
            raise RuntimeError(
                "POST fiscal bloqueado: o ticket alvo nao possui o prefixo sintetico"
            )

        preview = fiscal_preview(requests, config, case)
        if preview.status_code != 200:
            raise AssertionError(f"Preview WF04 retornou HTTP {preview.status_code}")
        html = preview.text.lower()
        if "method=\"post\"" not in html or WF04_DECISION_PATH not in html:
            raise AssertionError("Preview WF04 nao aponta para o POST de decisao")
        if glpi.snapshot(case.ticket_id) != before:
            raise AssertionError("GET preview alterou nome/status do ticket")

        wrong_token = "0" * len(case.token)
        if wrong_token == case.token:
            wrong_token = "f" * len(case.token)
        invalid_case = PreparedFiscalCase(
            case.ticket_id,
            wrong_token,
            case.decision,
            case.reference_id,
            case.synthetic_prefix,
        )
        invalid = fiscal_decision(requests, config, invalid_case)
        if invalid.status_code != 409:
            raise AssertionError(
                f"Token fiscal incorreto deveria responder 409; recebeu "
                f"{invalid.status_code}"
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(
                pool.map(
                    lambda _: fiscal_decision(requests, config, case),
                    range(2),
                )
            )
        statuses = sorted(response.status_code for response in responses)
        if statuses.count(202) != 1 or any(
            status not in {200, 202, 409} for status in statuses
        ):
            raise AssertionError(
                "Dois POSTs concorrentes devem produzir exatamente uma reserva "
                f"(202) e nenhuma segunda reserva; obtido {statuses}"
            )
        replay = fiscal_decision(requests, config, case)
        if replay.status_code != 409:
            raise AssertionError(
                "Replay apos a corrida deveria falhar fechado (409); recebeu "
                f"{replay.status_code}"
            )
        print(
            "[OK] WF04 sintetico: GET sem mutacao, token invalido fechado, "
            f"POST {case.decision} atomico e replay idempotente"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("preflight", "fiscal-preparado"),
        default="preflight",
        help="preflight e seguro; fiscal-preparado exige opt-in e ticket sintetico",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = RuntimeConfig.from_env()
    if args.mode == "preflight":
        run_preflight(config)
        return
    run_prepared_fiscal_case(config, PreparedFiscalCase.from_env())


if __name__ == "__main__":
    main()
