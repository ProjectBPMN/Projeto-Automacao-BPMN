from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    compose = (ROOT / "deploy" / "tls" / "docker-compose.yml").read_text(encoding="utf-8")
    nginx = (ROOT / "deploy" / "tls" / "nginx.conf.template").read_text(encoding="utf-8")
    checks = {
        "loopback_default": "${TLS_BIND_ADDRESS:-127.0.0.1}" in compose,
        "certificate_read_only": "/run/tls/tls.crt:ro" in compose and "/run/tls/tls.key:ro" in compose,
        "no_certificate_in_repository": "BEGIN CERTIFICATE" not in compose + nginx,
        "tls_12_and_13": nginx.count("ssl_protocols TLSv1.2 TLSv1.3;") == 2,
        "hsts_both_hosts": nginx.count("Strict-Transport-Security") == 2,
        "forwarded_https": nginx.count("proxy_set_header X-Forwarded-Proto https;") >= 3,
        "webhook_guard": "GLPI_WEBHOOK_KEY" in nginx,
        "n8n_and_glpi_routes": "http://n8n:5678" in nginx and "http://glpi:80" in nginx,
    }
    failed = [name for name, passed in checks.items() if not passed]
    print({"status": "PASS" if not failed else "FAIL", "checks": checks})
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
