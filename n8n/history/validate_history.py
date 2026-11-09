#!/usr/bin/env python3
"""Validate the safety, integrity and deterministic build of n8n/history."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
MANIFEST_PATH = HERE / "manifest.json"
WORKFLOW_DIR = HERE / "workflows"
EXPECTED_TOP_LEVEL = {"active", "connections", "name", "nodes", "settings"}
FORBIDDEN_KEYS = {
    "activeversion",
    "activeversionid",
    "binarydata",
    "credentials",
    "executiondata",
    "pindata",
    "resultdata",
    "rundata",
    "shared",
    "staticdata",
}
SENSITIVE_HEADERS = {
    "app-token",
    "authorization",
    "proxy-authorization",
    "session-token",
    "x-api-key",
}
SECRET_PATTERNS = {
    "Google API key": re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    "provider API key": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    "JWT": re.compile(
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."
        r"[A-Za-z0-9_-]{10,}"
    ),
    "literal authorization": re.compile(
        r"(?i)\b(?:bearer|user_token)\s+[A-Za-z0-9._~+/=-]{8,}"
    ),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "URL password": re.compile(r"(?i)https?://[^\s:/]+:[^\s/@]+@"),
    "embedded data URI": re.compile(r"(?i)data:[^;,\s]+;base64,[A-Za-z0-9+/=]{16,}"),
    "large embedded base64": re.compile(
        r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{256,}={0,2}(?![A-Za-z0-9+/=])"
    ),
}
ALLOWED_EXTENSIONS = {".json", ".md", ".py", ".txt"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    content = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def walk(value: Any, path: str = "$") -> Iterable[tuple[str, str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            yield child_path, str(key), child
            yield from walk(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]")


def validate_workflow(path: Path) -> list[str]:
    failures: list[str] = []
    try:
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            failures.append(f"{path.name}: UTF-8 BOM is not allowed")
        workflow = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return [f"{path.name}: invalid UTF-8 JSON: {error}"]

    if not isinstance(workflow, dict):
        return [f"{path.name}: root must be a workflow object"]
    if set(workflow) != EXPECTED_TOP_LEVEL:
        failures.append(
            f"{path.name}: top-level keys are {sorted(workflow)}, expected "
            f"{sorted(EXPECTED_TOP_LEVEL)}"
        )
    if workflow.get("active") is not False:
        failures.append(f"{path.name}: workflow must be inactive")
    if not isinstance(workflow.get("nodes"), list) or not workflow.get("nodes"):
        failures.append(f"{path.name}: node list is missing or empty")
    if not isinstance(workflow.get("connections"), dict):
        failures.append(f"{path.name}: connections must be an object")

    serialized = raw.decode("utf-8")
    for label, pattern in SECRET_PATTERNS.items():
        if pattern.search(serialized):
            failures.append(f"{path.name}: detected {label}")

    for json_path, key, child in walk(workflow):
        normalized = key.lower().replace("_", "")
        if normalized in FORBIDDEN_KEYS:
            failures.append(f"{path.name}: forbidden field {json_path}")
        if isinstance(child, str) and "\x00" in child:
            failures.append(f"{path.name}: NUL byte at {json_path}")
        if key == "name" and isinstance(child, str):
            header_name = child.strip().lower().replace("_", "-")
            if header_name in SENSITIVE_HEADERS:
                parent = _value_at_parent(workflow, json_path)
                header_value = parent.get("value") if isinstance(parent, dict) else None
                if not (
                    isinstance(header_value, str)
                    and header_value.lstrip().startswith("=")
                ):
                    failures.append(
                        f"{path.name}: sensitive header at {json_path} is not an expression"
                    )
    return failures


def _value_at_parent(root: Any, json_path: str) -> Any:
    """Resolve the small JSONPath subset emitted by ``walk``."""

    parent_path = json_path.rsplit(".", 1)[0]
    current = root
    for key, index in re.findall(r"(?:^|\.)([^.\[]+)|\[(\d+)\]", parent_path[1:]):
        current = current[int(index)] if index else current[key]
    return current


def validate_manifest() -> tuple[list[str], dict[str, Any] | None]:
    failures: list[str] = []
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return [f"manifest.json: invalid or missing: {error}"], None

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 10:
        failures.append("manifest.json: exactly 10 canonical workflow artifacts are required")
        return failures, manifest

    referenced: set[Path] = set()
    versions: set[str] = set()
    for entry in artifacts:
        artifact = HERE / entry.get("artifact", "")
        referenced.add(artifact.resolve())
        versions.add(str(entry.get("version")))
        if not artifact.is_file():
            failures.append(f"manifest.json: missing artifact {entry.get('artifact')}")
            continue
        actual = sha256_file(artifact)
        if actual != entry.get("sanitized_sha256"):
            failures.append(f"manifest.json: sanitized hash mismatch for {artifact.name}")
        workflow = json.loads(artifact.read_text(encoding="utf-8"))
        if len(workflow.get("nodes", [])) != entry.get("node_count"):
            failures.append(f"manifest.json: node count mismatch for {artifact.name}")
        source = entry.get("source", {})
        for field in ("source_file_sha256", "selected_workflow_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", str(source.get(field, ""))):
                failures.append(f"manifest.json: invalid {field} for {artifact.name}")

    if versions != {f"V{number}" for number in range(1, 9)}:
        failures.append(f"manifest.json: version coverage is {sorted(versions)}")
    actual_files = {path.resolve() for path in WORKFLOW_DIR.glob("*.json")}
    if actual_files != referenced:
        failures.append("manifest.json: artifact list and workflow directory differ")

    variants = manifest.get("variants")
    if not isinstance(variants, list) or not variants:
        failures.append("manifest.json: excluded variants are not documented")
    else:
        for variant in variants:
            if variant.get("selection_status") != "excluded":
                failures.append("manifest.json: variant without excluded status")
            for field in ("sanitized_sha256",):
                if not re.fullmatch(r"[0-9a-f]{64}", str(variant.get(field, ""))):
                    failures.append(f"manifest.json: invalid variant {field}")
    return failures, manifest


def validate_filesystem() -> list[str]:
    failures: list[str] = []
    for path in HERE.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            failures.append(f"binary/unexpected extension: {path.relative_to(HERE)}")
        if path.stat().st_size > 5 * 1024 * 1024:
            failures.append(f"unexpected file over 5 MiB: {path.relative_to(HERE)}")
    return failures


def validate_sources(manifest: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for entry in [*manifest.get("artifacts", []), *manifest.get("variants", [])]:
        source = entry.get("source", {})
        source_path = PROJECT_ROOT / source.get("path", "")
        if not source_path.is_file():
            failures.append(f"private source missing: {source.get('path')}")
            continue
        if sha256_file(source_path) != source.get("source_file_sha256"):
            failures.append(f"private source hash mismatch: {source.get('path')}")
            continue
        try:
            document = json.loads(source_path.read_text(encoding="utf-8-sig"))
            candidates = document if isinstance(document, list) else [document]
            selector = source.get("selector_id")
            if selector is None:
                selected = candidates
            else:
                selected = [item for item in candidates if item.get("id") == selector]
            if len(selected) != 1:
                failures.append(
                    f"private source selection is ambiguous: {source.get('path')}"
                )
            elif canonical_sha256(selected[0]) != source.get("selected_workflow_sha256"):
                failures.append(
                    f"private selected-workflow hash mismatch: {source.get('path')}"
                )
        except (OSError, UnicodeError, json.JSONDecodeError, AttributeError) as error:
            failures.append(f"private source cannot be inspected: {source.get('path')}: {error}")
    return failures


def validate_determinism() -> list[str]:
    process = subprocess.run(
        [sys.executable, str(HERE / "build_history.py"), "--check"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode == 0:
        return []
    details = (process.stdout + process.stderr).strip()
    return [f"deterministic rebuild failed: {details}"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-sources",
        action="store_true",
        help="also verify the private source files recorded in the manifest",
    )
    parser.add_argument(
        "--skip-determinism",
        action="store_true",
        help="skip rebuilding from private sources (for source-free distributions)",
    )
    args = parser.parse_args()

    failures: list[str] = []
    failures.extend(validate_filesystem())
    manifest_failures, manifest = validate_manifest()
    failures.extend(manifest_failures)
    for path in sorted(WORKFLOW_DIR.glob("*.json")):
        failures.extend(validate_workflow(path))
    if args.check_sources and manifest is not None:
        failures.extend(validate_sources(manifest))
    if not args.skip_determinism:
        failures.extend(validate_determinism())

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        print(f"SUMMARY: {len(failures)} failure(s)")
        return 1
    print("PASS: public V1-V8 archive is inactive, deterministic and free of detected secrets/runtime data")
    print("PASS: 10 workflow artifacts cover V1 through V8; manifest hashes match")
    return 0


if __name__ == "__main__":
    sys.exit(main())
