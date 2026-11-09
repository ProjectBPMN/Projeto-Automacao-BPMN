"""Carregamento mínimo e previsível das configurações locais do projeto."""

from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLACEHOLDERS = {"", "CHANGE_ME", "CHANGEME"}


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_project_env(paths: tuple[Path, ...] | None = None) -> dict[str, str]:
    """Load project dotenv files while preserving explicit process values."""
    paths = paths or (
        ROOT / "glpi" / ".env",
        ROOT / "n8n" / ".env",
        ROOT / "n8n" / ".env.local",
    )
    merged: dict[str, str] = {}
    for path in paths:
        merged.update(parse_env_file(path))
    for key, value in merged.items():
        if key not in os.environ and value:
            os.environ[key] = value
    return merged


def configured_value(name: str, *aliases: str) -> str:
    for candidate in (name, *aliases):
        value = os.getenv(candidate, "").strip()
        if value.upper() not in PLACEHOLDERS:
            return value
    return ""


def require_env(name: str, *aliases: str) -> str:
    value = configured_value(name, *aliases)
    if not value:
        candidates = ", ".join((name, *aliases))
        raise RuntimeError(f"Configuração obrigatória ausente: {candidates}")
    return value


def postgres_connection_kwargs() -> dict[str, object]:
    """Resolve host-side PostgreSQL settings without credential defaults."""
    port_raw = require_env("PGPORT", "POSTGRES_PORT")
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise RuntimeError("PGPORT/POSTGRES_PORT deve ser um inteiro.") from exc
    return {
        "host": require_env("PGHOST"),
        "port": port,
        "dbname": require_env("PGDATABASE", "POSTGRES_DB"),
        "user": require_env("PGUSER", "POSTGRES_USER"),
        "password": require_env("PGPASSWORD", "POSTGRES_PASSWORD"),
    }
