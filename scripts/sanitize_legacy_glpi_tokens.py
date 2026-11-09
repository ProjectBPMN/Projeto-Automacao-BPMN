from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGETS = (
    ROOT / "scripts" / "build_v7_workflow.js",
    ROOT / "n8n" / "workflows" / "Teste01_v7final.json",
)
PLACEHOLDER = "${GLPI_APP_TOKEN}"
DIRECT = re.compile(
    r"(?i)([\"']?APP[-_]?TOKEN[\"']?\s*[:=]\s*[\"'])([^\"']{12,})([\"'])"
)
NAMED = re.compile(
    r"(?is)([\"']name[\"']\s*:\s*[\"']APP[-_]?TOKEN[\"'].{0,160}?[\"']value[\"']\s*:\s*[\"'])([^\"']{12,})([\"'])"
)


def sanitize(text: str) -> tuple[str, int]:
    total = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal total
        value = match.group(2)
        if value.startswith(("${", "{{")) or "placeholder" in value.lower():
            return match.group(0)
        total += 1
        return f"{match.group(1)}{PLACEHOLDER}{match.group(3)}"

    text = DIRECT.sub(replace, text)
    text = NAMED.sub(replace, text)
    return text, total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sanitiza App-Token literal somente nos dois artefatos V7 legados.")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    results = []
    for path in TARGETS:
        original = path.read_text(encoding="utf-8")
        sanitized, replacements = sanitize(original)
        if args.apply and replacements:
            path.write_text(sanitized, encoding="utf-8", newline="\n")
        results.append({"path": str(path.relative_to(ROOT)), "replacements": replacements})
    print(json.dumps({"mode": "APPLY" if args.apply else "DRY_RUN", "results": results}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
