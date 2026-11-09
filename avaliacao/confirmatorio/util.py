from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PLACEHOLDER_TOKENS = (
    "PREENCHER",
    "SUBSTITUIR",
    "CHANGEME",
    "PLACEHOLDER",
    "TODO",
    "A_DEFINIR",
)


def contains_placeholder(value: str) -> bool:
    normalized = value.upper().replace("-", "_").replace(" ", "_")
    return any(
        normalized == token
        or normalized.startswith(token + "_")
        or normalized.endswith("_" + token)
        or ("_" + token + "_") in normalized
        for token in PLACEHOLDER_TOKENS
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def family_ids_sha256(family_ids: Iterable[str]) -> str:
    values = sorted(str(value) for value in family_ids)
    return sha256_bytes(canonical_json_bytes(values))


def require_mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} deve ser um objeto JSON")
    return value


def require_list(value: Any, context: str, *, nonempty: bool = True) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        suffix = " não vazia" if nonempty else ""
        raise ValueError(f"{context} deve ser uma lista{suffix}")
    return value


def require_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} deve ser texto não vazio")
    text = value.strip()
    if contains_placeholder(text):
        raise ValueError(f"{context} contém placeholder: {text!r}")
    return text


def require_sha256(value: Any, context: str) -> str:
    text = require_string(value, context).lower()
    if not SHA256_RE.fullmatch(text):
        raise ValueError(f"{context} deve ser SHA-256 hexadecimal com 64 caracteres")
    return text


def require_probability(value: Any, context: str, *, inclusive: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} deve ser numérico")
    number = float(value)
    valid = 0 <= number <= 1 if inclusive else 0 < number < 1
    if not math.isfinite(number) or not valid:
        bounds = "[0, 1]" if inclusive else "]0, 1["
        raise ValueError(f"{context} deve pertencer a {bounds}")
    return number


def require_positive_int(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{context} deve ser inteiro positivo")
    return value


def parse_aware_datetime(value: Any, context: str) -> datetime:
    text = require_string(value, context)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{context} deve estar em ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{context} deve incluir fuso horário")
    return parsed


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"arquivo obrigatório ausente: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON inválido em {path}: {exc}") from exc
    return require_mapping(value, str(path))


def load_json_bytes(payload: bytes, context: str) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON UTF-8 inválido em {context}: {exc}") from exc
    return require_mapping(value, context)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        payload = path.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError(f"arquivo obrigatório ausente: {path}") from exc
    return load_jsonl_bytes(payload, str(path))


def load_jsonl_bytes(payload: bytes, context: str) -> list[dict[str, Any]]:
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError(f"JSONL não está em UTF-8 em {context}: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSONL inválido em {context}:{line_number}: {exc}") from exc
        rows.append(require_mapping(value, f"{context}:{line_number}"))
    if not rows:
        raise ValueError(f"dataset JSONL vazio: {context}")
    return rows


def _fsync_directory(path: Path) -> None:
    """Best effort de persistência do diretório após criação/substituição.

    Windows não oferece a mesma semântica de ``fsync`` de diretório que POSIX;
    nesse sistema o ``os.replace`` continua atômico no mesmo volume e a falha
    deste reforço não deve apagar um artefato já persistido.
    """

    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def exclusive_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise FileExistsError(f"arquivo imutável já existe: {path}") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(path.parent)
    except Exception:
        try:
            path.unlink(missing_ok=True)
        finally:
            raise


def exclusive_write_json(path: Path, value: Any) -> None:
    payload = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    exclusive_write_bytes(path, payload)


def atomic_replace_json(path: Path, value: Any) -> None:
    """Substitui JSON no mesmo diretório sem expor conteúdo parcialmente escrito."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        exclusive_write_bytes(temporary, payload)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def resolve_artifact(base_dir: Path, value: Any, context: str) -> Path:
    text = require_string(value, context)
    candidate = Path(text)
    resolved = candidate.resolve() if candidate.is_absolute() else (base_dir / candidate).resolve()
    if not resolved.is_file():
        raise ValueError(f"{context} não existe ou não é arquivo: {resolved}")
    return resolved
