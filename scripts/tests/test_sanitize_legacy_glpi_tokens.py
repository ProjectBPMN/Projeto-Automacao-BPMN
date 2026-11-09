from __future__ import annotations

import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import sanitize_legacy_glpi_tokens as sanitizer


def test_sanitize_direct_and_named_app_token() -> None:
    secret = "literal-token-value-123456"
    source = (
        "headers: {'App-Token': '" + secret + "'}\n"
        + '{"name":"App-Token","value":"' + secret + '"}'
    )
    sanitized, count = sanitizer.sanitize(source)
    assert count == 2
    assert secret not in sanitized
    assert sanitized.count(sanitizer.PLACEHOLDER) == 2


def test_sanitize_is_idempotent_for_placeholder() -> None:
    sanitized, count = sanitizer.sanitize("{'App-Token': '${GLPI_APP_TOKEN}'}")
    assert count == 0
    assert sanitized == "{'App-Token': '${GLPI_APP_TOKEN}'}"
