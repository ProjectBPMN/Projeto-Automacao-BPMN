#!/usr/bin/env python3
"""Build the deterministic, sanitized V1-V8 public workflow archive.

The historical sources remain in their original locations.  This builder only
reads them and writes importable, inactive n8n workflow JSON files under
``n8n/history/workflows``.  It intentionally removes deployment/runtime
metadata and credential references while preserving nodes, connections and
settings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ARCHIVE_SCHEMA = "n8n-history-public-v1"
ARCHIVE_DATE = "2026-08-12"
HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
WORKFLOW_DIR = HERE / "workflows"
MANIFEST_PATH = HERE / "manifest.json"


@dataclass(frozen=True)
class Source:
    version: str
    artifact: str
    source: str
    selector: str | None = None
    role: str = "historical workflow"


SOURCES = (
    Source("V1", "v1_triagem.json", "n8n/workflows/Teste01_v1.json"),
    Source("V2", "v2_triagem.json", "n8n/workflows/Teste01_v2.json"),
    Source("V3", "v3_triagem.json", "n8n/workflows/Teste01_v3.json"),
    Source("V4", "v4_triagem.json", "n8n/workflows/Teste01_v4.json"),
    Source("V5", "v5_triagem.json", "n8n/workflows/Teste01_v5.json"),
    Source(
        "V6",
        "v6_triagem_postgres.json",
        "n8n/workflows/all_workflows_after_v7.json",
        "AutoFinal20260422A",
    ),
    Source("V7", "v7_triagem_postgres.json", "n8n/workflows/v7_current.json"),
    Source(
        "V8",
        "v8_wf01_orquestrador.json",
        "n8n/workflows/Versão8/WF01_Orquestrador.json",
        role="orchestrator",
    ),
    Source(
        "V8",
        "v8_wf02_triagem.json",
        "n8n/workflows/Versão8/WF02_Triagem.json",
        role="triage and classification",
    ),
    Source(
        "V8",
        "v8_wf03_fiscal.json",
        "n8n/workflows/Versão8/WF03_Fiscal.json",
        role="human decision",
    ),
)


VARIANTS = (
    Source(
        "V6",
        "excluded-v6-initial-postgres",
        "n8n/workflows/all_workflows_after_v7.json",
        "wfTeste01v6Pg001",
        role="excluded earlier V6 candidate",
    ),
    Source(
        "V7",
        "excluded-v7-63-initial",
        "n8n/workflows/Teste01_v7.json",
        role="excluded 63-node snapshot",
    ),
    Source(
        "V7",
        "excluded-v7-63-final",
        "n8n/workflows/Teste01_v7final.json",
        role="excluded 63-node snapshot",
    ),
    Source(
        "V7",
        "excluded-v7-63-manutencao",
        "n8n/workflows/Teste01_v7_MANUTENCAO.json",
        role="excluded duplicate 63-node snapshot",
    ),
    Source(
        "V7",
        "excluded-v7-63-triagem",
        "n8n/workflows/Teste01_v7_TRIAGEM.json",
        role="excluded duplicate 63-node snapshot",
    ),
    Source(
        "V7",
        "excluded-v7-65-runtime",
        "n8n/workflows/all_workflows_after_v7.json",
        "TriagemV7Pg20260429",
        role="excluded 65-node runtime snapshot",
    ),
    Source(
        "V7",
        "excluded-v7-66-runtime-export",
        "n8n/workflows/v7_runtime_export2.json",
        role="excluded duplicate of selected 66-node snapshot",
    ),
    Source(
        "V8",
        "excluded-v8-wf01-export",
        "n8n/workflows/Versão8/wf01_export.json",
        role="excluded runtime export",
    ),
    Source(
        "V8",
        "excluded-v8-wf01-reimport",
        "n8n/workflows/Versão8/wf01_reimport.json",
        role="excluded reimport snapshot",
    ),
    Source(
        "V8",
        "excluded-v8-wf02-export",
        "n8n/workflows/Versão8/wf02_export.json",
        role="excluded runtime export",
    ),
    Source(
        "V8",
        "excluded-v8-wf02-reimport",
        "n8n/workflows/Versão8/wf02_reimport.json",
        role="excluded reimport snapshot",
    ),
)


RUNTIME_KEYS = {
    "activeversion",
    "activeversionid",
    "binarydata",
    "executiondata",
    "pindata",
    "resultdata",
    "rundata",
    "shared",
    "staticdata",
}
SENSITIVE_DIRECT_KEYS = re.compile(
    r"^(?:api[_-]?key|app[_-]?token|authorization|password|passwd|"
    r"refresh[_-]?token|access[_-]?token|session[_-]?token|x-api-key)$",
    re.IGNORECASE,
)
SENSITIVE_HEADER_NAMES = {
    "app-token",
    "authorization",
    "proxy-authorization",
    "session-token",
    "x-api-key",
}
SECRET_PATTERNS = (
    (re.compile(r"AIza[0-9A-Za-z_-]{20,}"), "<REDACTED_GOOGLE_API_KEY>"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "<REDACTED_API_KEY>"),
    (
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."
            r"[A-Za-z0-9_-]{10,}"
        ),
        "<REDACTED_JWT>",
    ),
    (
        re.compile(r"(?i)\b(?:bearer|user_token)\s+[A-Za-z0-9._~+/=-]{8,}"),
        "<REDACTED_AUTHORIZATION>",
    ),
    (
        re.compile(r"(?i)(https?://[^\s:/]+:)[^\s/@]+(@)"),
        r"\1<REDACTED_PASSWORD>\2",
    ),
)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def pretty_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def load_source(spec: Source) -> tuple[Path, bytes, dict[str, Any]]:
    path = PROJECT_ROOT / spec.source
    raw = path.read_bytes()
    document = json.loads(raw.decode("utf-8-sig"))
    candidates = document if isinstance(document, list) else [document]

    if spec.selector is None:
        if len(candidates) != 1:
            raise ValueError(
                f"{spec.source}: expected one workflow, found {len(candidates)}"
            )
        workflow = candidates[0]
    else:
        selected = [item for item in candidates if item.get("id") == spec.selector]
        if len(selected) != 1:
            raise ValueError(
                f"{spec.source}: selector {spec.selector!r} matched {len(selected)}"
            )
        workflow = selected[0]

    if not isinstance(workflow, dict):
        raise TypeError(f"{spec.source}: selected value is not a workflow object")
    if not isinstance(workflow.get("nodes"), list):
        raise ValueError(f"{spec.source}: selected workflow has no node list")
    return path, raw, workflow


def _header_name(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def collect_literal_secrets(value: Any) -> set[str]:
    """Collect source literals so repeated occurrences can also be redacted."""

    found: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            header = item.get("name")
            header_value = item.get("value")
            if (
                isinstance(header, str)
                and _header_name(header) in SENSITIVE_HEADER_NAMES
                and isinstance(header_value, str)
                and not header_value.lstrip().startswith("=")
                and len(header_value.strip()) >= 8
            ):
                found.add(header_value)
            for key, child in item.items():
                if (
                    SENSITIVE_DIRECT_KEYS.fullmatch(str(key))
                    and isinstance(child, str)
                    and not child.lstrip().startswith("=")
                    and len(child.strip()) >= 8
                ):
                    found.add(child)
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return found


def env_expression_for_header(name: str) -> str:
    normalized = _header_name(name)
    if normalized == "app-token":
        return "={{ $env.GLPI_APP_TOKEN }}"
    if normalized == "authorization":
        return "={{ 'user_token ' + $env.GLPI_USER_TOKEN }}"
    if normalized == "proxy-authorization":
        return "={{ $env.PROXY_AUTHORIZATION }}"
    if normalized == "session-token":
        return "={{ $env.GLPI_SESSION_TOKEN }}"
    return "={{ $env.API_KEY }}"


def env_expression_for_key(name: str) -> str:
    normalized = _header_name(name)
    if normalized in {"password", "passwd"}:
        return "={{ $env.HISTORICAL_PASSWORD }}"
    if normalized == "authorization":
        return "={{ $env.AUTHORIZATION }}"
    if normalized == "app-token":
        return "={{ $env.GLPI_APP_TOKEN }}"
    if normalized == "session-token":
        return "={{ $env.GLPI_SESSION_TOKEN }}"
    return "={{ $env.API_KEY }}"


def sanitize_workflow(workflow: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    secrets = sorted(collect_literal_secrets(workflow), key=len, reverse=True)
    stats = {
        "credential_references_removed": 0,
        "runtime_fields_removed": 0,
        "sensitive_values_replaced": 0,
        "top_level_fields_omitted": 0,
    }

    def scrub_string(value: str) -> str:
        result = value
        for secret in secrets:
            if secret in result:
                result = result.replace(secret, "<REDACTED_HISTORICAL_SECRET>")
                stats["sensitive_values_replaced"] += 1
        for pattern, replacement in SECRET_PATTERNS:
            result, count = pattern.subn(replacement, result)
            stats["sensitive_values_replaced"] += count
        return result

    def visit(item: Any) -> Any:
        if isinstance(item, list):
            return [visit(child) for child in item]
        if not isinstance(item, dict):
            return scrub_string(item) if isinstance(item, str) else item

        header = item.get("name")
        is_sensitive_header = (
            isinstance(header, str)
            and _header_name(header) in SENSITIVE_HEADER_NAMES
            and "value" in item
        )
        sanitized: dict[str, Any] = {}
        for key, child in item.items():
            normalized_key = str(key).lower().replace("_", "")
            if normalized_key in RUNTIME_KEYS:
                stats["runtime_fields_removed"] += 1
                continue
            if str(key).lower() == "credentials":
                stats["credential_references_removed"] += 1
                continue
            if is_sensitive_header and key == "value":
                if isinstance(child, str) and child.lstrip().startswith("="):
                    sanitized[key] = scrub_string(child)
                else:
                    sanitized[key] = env_expression_for_header(header)
                    stats["sensitive_values_replaced"] += 1
                continue
            if SENSITIVE_DIRECT_KEYS.fullmatch(str(key)):
                if isinstance(child, str) and child.lstrip().startswith("="):
                    sanitized[key] = scrub_string(child)
                else:
                    sanitized[key] = env_expression_for_key(str(key))
                    stats["sensitive_values_replaced"] += 1
                continue
            sanitized[key] = visit(child)
        return sanitized

    preserved = {"name", "nodes", "connections", "settings"}
    omitted = set(workflow) - preserved - {"active"}
    runtime_omitted = {
        key for key in omitted
        if key.lower().replace("_", "") in RUNTIME_KEYS
    }
    stats["runtime_fields_removed"] += len(runtime_omitted)
    stats["top_level_fields_omitted"] = len(omitted - runtime_omitted)
    public = {
        "active": False,
        "connections": visit(workflow.get("connections", {})),
        "name": scrub_string(str(workflow.get("name") or "Historical workflow")),
        "nodes": visit(workflow.get("nodes", [])),
        "settings": visit(workflow.get("settings", {})),
    }
    return public, stats


def source_manifest_entry(
    spec: Source,
    raw: bytes,
    workflow: dict[str, Any],
    sanitized: dict[str, Any],
) -> dict[str, Any]:
    source_entry: dict[str, Any] = {
        "path": spec.source.replace("\\", "/"),
        "source_file_sha256": sha256_bytes(raw),
        "selected_workflow_sha256": sha256_bytes(canonical_bytes(workflow)),
    }
    if spec.selector is not None:
        source_entry["selector_id"] = spec.selector
    return {
        "artifact": f"workflows/{spec.artifact}",
        "node_count": len(sanitized["nodes"]),
        "role": spec.role,
        "sanitized_sha256": sha256_bytes(pretty_bytes(sanitized)),
        "source": source_entry,
        "source_name": workflow.get("name"),
        "source_workflow_id": workflow.get("id"),
        "version": spec.version,
    }


def build_in_memory() -> tuple[dict[Path, bytes], dict[str, Any]]:
    outputs: dict[Path, bytes] = {}
    artifacts: list[dict[str, Any]] = []
    transformations: dict[str, dict[str, int]] = {}

    for spec in SOURCES:
        _, raw, workflow = load_source(spec)
        sanitized, stats = sanitize_workflow(workflow)
        output = WORKFLOW_DIR / spec.artifact
        outputs[output] = pretty_bytes(sanitized)
        artifacts.append(source_manifest_entry(spec, raw, workflow, sanitized))
        transformations[f"workflows/{spec.artifact}"] = stats

    variants: list[dict[str, Any]] = []
    for spec in VARIANTS:
        _, raw, workflow = load_source(spec)
        sanitized, _ = sanitize_workflow(workflow)
        entry = source_manifest_entry(spec, raw, workflow, sanitized)
        entry.pop("artifact")
        entry["label"] = spec.artifact
        entry["selection_status"] = "excluded"
        entry["exclusion_reason"] = (
            "Not the selected canonical snapshot; retained in the manifest for "
            "provenance and variant comparison only."
        )
        variants.append(entry)

    manifest = {
        "archive_date": ARCHIVE_DATE,
        "archive_schema": ARCHIVE_SCHEMA,
        "artifacts": artifacts,
        "canonical_selection": {
            "V1-V5": "named version files preserved in the private workspace",
            "V6": "workflow id AutoFinal20260422A selected from aggregate export",
            "V7": "latest audited 66-node snapshot v7_current.json",
            "V8": "three named design exports: WF01, WF02 and WF03",
        },
        "determinism": {
            "json_encoding": "UTF-8 without BOM",
            "json_format": "sorted keys, two-space indentation, LF newline",
            "source_object_hash": "SHA-256 of canonical compact JSON with sorted keys",
        },
        "publication_scope": "historical, sanitized, inactive and non-production",
        "transformations": transformations,
        "variants": variants,
    }
    outputs[MANIFEST_PATH] = pretty_bytes(manifest)
    return outputs, manifest


def write_outputs(outputs: dict[Path, bytes]) -> None:
    WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)
    expected = {path.resolve() for path in outputs}
    for existing in WORKFLOW_DIR.glob("*.json"):
        if existing.resolve() not in expected:
            raise RuntimeError(
                f"unexpected JSON in public workflow directory: {existing.name}"
            )
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def check_outputs(outputs: dict[Path, bytes]) -> list[str]:
    problems: list[str] = []
    for path, expected in outputs.items():
        if not path.is_file():
            problems.append(f"missing: {path.relative_to(PROJECT_ROOT)}")
        elif path.read_bytes() != expected:
            problems.append(f"not deterministic/current: {path.relative_to(PROJECT_ROOT)}")
    expected_workflows = {
        path.resolve() for path in outputs if path.parent == WORKFLOW_DIR
    }
    for existing in WORKFLOW_DIR.glob("*.json"):
        if existing.resolve() not in expected_workflows:
            problems.append(f"unexpected: {existing.relative_to(PROJECT_ROOT)}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare committed artifacts with a fresh in-memory build",
    )
    args = parser.parse_args()
    outputs, _ = build_in_memory()
    if args.check:
        problems = check_outputs(outputs)
        if problems:
            for problem in problems:
                print(f"FAIL: {problem}")
            return 1
        print(f"PASS: {len(SOURCES)} sanitized workflows and manifest are deterministic")
        return 0
    write_outputs(outputs)
    print(f"WROTE: {len(SOURCES)} sanitized workflows and manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
