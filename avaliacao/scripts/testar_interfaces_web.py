from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, Page, async_playwright


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "avaliacao" / "resultados" / "browser_2026-07-15"
EXPECTED_WORKFLOWS = {
    "V9 - WF01 Sincronizador",
    "V9 - WF02 Triagem",
    "V9 - WF03 Classificação",
    "V9 - WF04 Decisão Fiscal",
    "V9 - WF05 Métricas",
    "V9 - WF06 Fila IA",
}


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def local_environment() -> dict[str, str]:
    values = read_env(ROOT / "n8n" / ".env")
    values.update(read_env(ROOT / "n8n" / ".env.local"))
    values.update({key: value for key, value in os.environ.items() if value})
    return values


def decode_basic_auth(value: str) -> tuple[str, str] | None:
    token = str(value or "").strip()
    if token.lower().startswith("basic "):
        token = token.split(None, 1)[1]
    try:
        decoded = base64.b64decode(token, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    if ":" not in decoded:
        return None
    user, password = decoded.split(":", 1)
    return (user, password) if user and password else None


def add_check(
    report: dict[str, Any],
    service: str,
    check: str,
    passed: bool,
    detail: str,
    duration_ms: int | None = None,
) -> None:
    report["checks"].append(
        {
            "service": service,
            "check": check,
            "passed": passed,
            "detail": detail,
            "duration_ms": duration_ms,
        }
    )


async def timed_goto(page: Page, url: str) -> tuple[Any, int]:
    started = time.perf_counter()
    response = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    duration = round((time.perf_counter() - started) * 1000)
    return response, duration


async def test_n8n(browser: Browser, env: dict[str, str], output: Path, report: dict[str, Any]) -> None:
    context = await browser.new_context(viewport={"width": 1440, "height": 1000})
    page = await context.new_page()
    try:
        response, duration = await timed_goto(page, "http://127.0.0.1:5678/")
        status = response.status if response else 0
        add_check(report, "n8n", "public_page", status == 200, f"HTTP {status}", duration)
        try:
            await page.locator('input[type="email"]').wait_for(state="visible", timeout=15_000)
        except Exception:
            pass
        sign_in = (
            await page.locator('input[type="email"]').count() == 1
            and await page.locator('input[type="password"]').count() == 1
        )
        add_check(report, "n8n", "login_form", sign_in, "formulário de login renderizado")
        await page.screenshot(path=output / "n8n-login.png", full_page=True)

        health = await context.request.get("http://127.0.0.1:5678/healthz", timeout=15_000)
        add_check(report, "n8n", "healthz", health.status == 200, f"HTTP {health.status}")

        user = env.get("N8N_BASIC_AUTH_USER", "")
        password = env.get("N8N_BASIC_AUTH_PASSWORD", "")
        if not user or not password:
            add_check(report, "n8n", "authenticated_read", False, "credenciais locais ausentes")
            return
        await page.locator('input[type="email"]').fill(user)
        await page.locator('input[type="password"]').fill(password)
        async with page.expect_response(
            lambda item: "/rest/login" in item.url and item.request.method == "POST",
            timeout=20_000,
        ) as login_info:
            await page.get_by_role("button", name="Sign in", exact=True).click(timeout=15_000)
        login_response = await login_info.value
        authenticated = login_response.status == 200
        add_check(
            report,
            "n8n",
            "authenticated_read",
            authenticated,
            f"HTTP {login_response.status}",
        )
        if not authenticated:
            await page.screenshot(path=output / "n8n-login-failed.png", full_page=True)
            return
        await page.wait_for_timeout(1_000)
        workflow_fetch = await page.evaluate(
            """async () => {
              const response = await fetch('/rest/workflows', {credentials: 'same-origin'});
              let payload = {};
              try { payload = await response.json(); } catch (_) {}
              return {status: response.status, payload};
            }"""
        )
        if workflow_fetch.get("status") == 401:
            session_response = await context.request.post(
                "http://127.0.0.1:5678/rest/login",
                data={"emailOrLdapLoginId": user, "password": password},
                timeout=20_000,
            )
            workflows_response = await context.request.get(
                "http://127.0.0.1:5678/rest/workflows", timeout=20_000
            )
            try:
                refreshed_payload = await workflows_response.json()
            except Exception:
                refreshed_payload = {}
            workflow_fetch = {
                "status": workflows_response.status,
                "payload": refreshed_payload,
                "session_refresh_status": session_response.status,
            }
        payload = workflow_fetch.get("payload", {})
        workflows = payload.get("data", []) if isinstance(payload, dict) else []
        active_names = {
            str(item.get("name"))
            for item in workflows
            if isinstance(item, dict) and item.get("active") is True
        }
        missing = sorted(EXPECTED_WORKFLOWS - active_names)
        add_check(
            report,
            "n8n",
            "six_active_v9_workflows",
            workflow_fetch.get("status") == 200 and not missing,
            (
                "6 workflows V9 ativos em sessão autenticada somente leitura"
                if not missing
                else f"HTTP {workflow_fetch.get('status')}; ausentes: " + ", ".join(missing)
            ),
        )
        await page.goto("http://127.0.0.1:5678/home/workflows", wait_until="domcontentloaded")
        await page.screenshot(path=output / "n8n-workflows.png", full_page=True)
    finally:
        await context.close()


async def test_glpi(browser: Browser, env: dict[str, str], output: Path, report: dict[str, Any]) -> None:
    context = await browser.new_context(viewport={"width": 1440, "height": 1000})
    page = await context.new_page()
    try:
        response, duration = await timed_goto(page, "http://127.0.0.1:9080/")
        status = response.status if response else 0
        add_check(report, "GLPI", "public_page", status == 200, f"HTTP {status}", duration)
        has_form = await page.locator('input[name="login_name"]').count() == 1
        add_check(report, "GLPI", "login_form", has_form, "formulário de login renderizado")
        await page.screenshot(path=output / "glpi-login.png", full_page=True)

        credentials = decode_basic_auth(env.get("GLPI_AUTH_BASIC", ""))
        if credentials is None:
            add_check(report, "GLPI", "authenticated_read", False, "credencial Basic local ausente/inválida")
            return
        user, password = credentials
        await page.locator('input[name="login_name"]').fill(user)
        await page.locator('input[name="login_password"]').fill(password)
        await page.get_by_role("button", name="Entrar", exact=True).click(timeout=15_000)
        await page.wait_for_load_state("domcontentloaded")
        authenticated = await page.locator('input[name="login_name"]').count() == 0
        add_check(report, "GLPI", "authenticated_read", authenticated, "sessão somente leitura iniciada")
        if authenticated:
            response = await page.goto(
                "http://127.0.0.1:9080/front/ticket.php",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            add_check(
                report,
                "GLPI",
                "tickets_page_read_only",
                bool(response and response.status == 200),
                f"HTTP {response.status if response else 0}",
            )
            await page.screenshot(path=output / "glpi-tickets.png", full_page=True)
    finally:
        await context.close()


async def test_mailpit(browser: Browser, output: Path, report: dict[str, Any]) -> None:
    context = await browser.new_context(viewport={"width": 1440, "height": 1000})
    page = await context.new_page()
    try:
        response, duration = await timed_goto(page, "http://127.0.0.1:18025/")
        status = response.status if response else 0
        add_check(report, "Mailpit", "public_page", status == 200, f"HTTP {status}", duration)
        title_ok = "Mailpit" in await page.title()
        add_check(report, "Mailpit", "ui_title", title_ok, await page.title())
        info = await context.request.get("http://127.0.0.1:18025/api/v1/info", timeout=15_000)
        add_check(report, "Mailpit", "api_info", info.status == 200, f"HTTP {info.status}")
        await page.screenshot(path=output / "mailpit.png", full_page=True)
    finally:
        await context.close()


async def run_browser(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "READ_ONLY_BROWSER_VALIDATION",
        "created_tickets": 0,
        "workflow_mutations": 0,
        "checks": [],
    }
    env = local_environment()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            channel="msedge",
            headless=True,
            args=["--disable-gpu", "--no-first-run", "--disable-extensions"],
        )
        try:
            for service, test in (
                ("n8n", lambda: test_n8n(browser, env, output, report)),
                ("GLPI", lambda: test_glpi(browser, env, output, report)),
                ("Mailpit", lambda: test_mailpit(browser, output, report)),
            ):
                try:
                    await test()
                except Exception as exc:
                    add_check(
                        report,
                        service,
                        "browser_execution",
                        False,
                        f"{type(exc).__name__}: {str(exc)[:300]}",
                    )
        finally:
            await browser.close()
    report["passed"] = all(item["passed"] for item in report["checks"])
    return report


def write_report(output: Path, report: dict[str, Any]) -> None:
    (output / "resultado.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Teste de navegador somente leitura",
        "",
        f"Resultado geral: `{'PASSOU' if report['passed'] else 'FALHOU'}`.",
        "",
        "| Serviço | Verificação | Resultado | Detalhe |",
        "|---|---|---:|---|",
    ]
    for item in report["checks"]:
        detail = str(item["detail"]).replace("|", "\\|")
        lines.append(
            f"| {item['service']} | {item['check']} | "
            f"{'PASSOU' if item['passed'] else 'FALHOU'} | {detail} |"
        )
    lines.extend(
        [
            "",
            "A suíte não cria chamados, não executa workflows e não altera mensagens.",
            "As credenciais são lidas somente de variáveis/arquivos locais e nunca entram nos artefatos.",
        ]
    )
    (output / "relatorio.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Valida n8n, GLPI e Mailpit pelo navegador sem mutações.")
    parser.add_argument("--saida", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = asyncio.run(run_browser(args.saida.resolve()))
    write_report(args.saida.resolve(), report)
    print(f"[{'OK' if report['passed'] else 'FALHOU'}] {len(report['checks'])} verificações browser")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
