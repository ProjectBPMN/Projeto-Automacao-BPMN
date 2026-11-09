from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable


_SPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_PROMPT_INJECTION_COMMANDS = (
    re.compile(
        r"(?i)\b(?:ignore|ignorar)\s+(?:todas?\s+)?(?:as?\s+)?"
        r"(?:instru[cç][oõ]es|regras|orienta[cç][oõ]es)"
        r"(?:\s+(?:anteriores|acima|do\s+sistema))?"
        r"(?:\s+e\s+(?:"
        r"(?:classifique|marque|retorne|escolha)\s+"
        r"(?:o\s+chamado\s+)?(?:como\s+)?"
        r"(?:obra|demo|sob[ _-]?demanda|triagem(?:\s+manual)?|"
        r"duplicad[oa]|n[aã]o\s+duplicad[oa])"
        r"|escolher\s+a\s+classe\s+mais\s+cara))?"
    ),
    re.compile(
        r"(?i)\b(?:classifique|marque|retorne|responda|escolha)\s+"
        r"(?:o\s+chamado\s+)?(?:como\s+)?"
        r"(?:obra|demo|sob[ _-]?demanda|triagem(?:\s+manual)?|"
        r"duplicad[oa]|n[aã]o\s+duplicad[oa])\b"
    ),
    re.compile(r"(?i)\b(?:system\s+prompt|voc[eê]\s+agora\s+[eé])\b[^.;,\n]*"),
)


def strip_accents(value: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch)
    )


def normalize_text(value: Any) -> str:
    text = strip_accents(str(value or "")).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return _SPACE_RE.sub(" ", text).strip()


def tokens(value: Any) -> list[str]:
    return _TOKEN_RE.findall(normalize_text(value))


def ticket_text(ticket: dict[str, Any], max_chars: int) -> str:
    field_groups = (
        ("title", "titulo", "name"),
        ("content", "descricao"),
        ("location", "localizacao"),
        ("category", "categoria", "tipo_servico"),
    )
    parts: list[str] = []
    seen: set[str] = set()
    for aliases in field_groups:
        value = next(
            (
                ticket.get(field)
                for field in aliases
                if ticket.get(field) is not None and str(ticket.get(field)).strip()
            ),
            None,
        )
        if value is None:
            continue
        value_text = str(value).strip()
        if value_text and value_text not in seen:
            parts.append(value_text)
            seen.add(value_text)
    return " ".join(parts)[:max_chars]


def ticket_narrative_parts(ticket: dict[str, Any], max_chars: int) -> list[str]:
    """Campos narrativos separados, limitados sem perder fronteiras de campo."""
    field_groups = (
        ("title", "titulo", "name"),
        ("content", "descricao"),
        ("location", "localizacao"),
    )
    parts: list[str] = []
    seen: set[str] = set()
    used = 0
    for aliases in field_groups:
        value = next(
            (
                ticket.get(field)
                for field in aliases
                if ticket.get(field) is not None
                and str(ticket.get(field)).strip()
            ),
            None,
        )
        if value is None:
            continue
        value_text = str(value).strip()
        if not value_text or value_text in seen:
            continue
        separator_size = 1 if parts else 0
        available = max_chars - used - separator_size
        if available <= 0:
            break
        part = value_text[:available]
        if part:
            parts.append(part)
            seen.add(value_text)
            used += separator_size + len(part)
    return parts


def ticket_narrative_text(ticket: dict[str, Any], max_chars: int) -> str:
    """Texto observável do relato, sem usar a categoria GLPI como evidência.

    A categoria é preenchida pelo usuário e pode estar errada. Ela permanece no
    payload original para auditoria e para comparações estruturadas fracas, mas
    não participa da extração do ativo nem do classificador semântico.
    """
    return " ".join(ticket_narrative_parts(ticket, max_chars))


def sanitize_untrusted_text(value: Any) -> str:
    """Remove somente comandos típicos de prompt injection do texto do modelo.

    O relato original continua disponível para auditoria e extração determinística.
    Esta função não tenta "corrigir" o conteúdo técnico: preserva ativo, defeito,
    local e contexto, removendo apenas diretivas dirigidas ao classificador.
    """
    text = str(value or "")
    for pattern in _PROMPT_INJECTION_COMMANDS:
        text = pattern.sub(" ", text)
    text = re.sub(r"(?i)\bo\s+texto\s+diz\s*['\"]\s*['\"]\s*,?", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = _SPACE_RE.sub(" ", text).strip(" \t\r\n,.;:'\"")
    return text


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def cosine(left: Iterable[float], right: Iterable[float]) -> float:
    a = list(left)
    b = list(right)
    if len(a) != len(b) or not a:
        return 0.0
    denom_a = math.sqrt(sum(value * value for value in a))
    denom_b = math.sqrt(sum(value * value for value in b))
    if denom_a == 0 or denom_b == 0:
        return 0.0
    value = sum(x * y for x, y in zip(a, b)) / (denom_a * denom_b)
    return max(-1.0, min(1.0, value))


def tfidf_cosine(left: str, right: str, idf: dict[str, float]) -> float:
    counts_left = Counter(tokens(left))
    counts_right = Counter(tokens(right))
    if not counts_left or not counts_right:
        return 0.0

    def weighted(counts: Counter[str]) -> dict[str, float]:
        result: dict[str, float] = {}
        for token, count in counts.items():
            weight = float(idf.get(token, idf.get("__default__", 1.0)))
            result[token] = (1.0 + math.log(count)) * weight
        return result

    a = weighted(counts_left)
    b = weighted(counts_right)
    common = set(a).intersection(b)
    numerator = sum(a[token] * b[token] for token in common)
    denominator = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(
        sum(v * v for v in b.values())
    )
    return numerator / denominator if denominator else 0.0


def parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        try:
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    raw = str(value).strip().replace("Z", "+00:00")
    for candidate in (raw, raw.replace(" ", "T", 1)):
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None
