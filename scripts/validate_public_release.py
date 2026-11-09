#!/usr/bin/env python3
"""Fail-closed validator for the files intended for the public repository.

The Git ignore file is deliberately not a security boundary.  This program uses
an explicit positive list and applies content checks after path checks.  It does
not modify the worktree, the Git index, or any candidate bundle.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_MANIFEST = SCRIPT_DIR / "public_release_manifest.json"


@dataclass(frozen=True, order=True)
class Issue:
    path: str
    code: str
    detail: str
    line: int | None = None

    def render(self) -> str:
        location = f"{self.path}:{self.line}" if self.line else self.path
        return f"{location}: [{self.code}] {self.detail}"


SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("SECRET_GOOGLE_API_KEY", re.compile(r"AIza[0-9A-Za-z_-]{30,}")),
    ("SECRET_PROVIDER_API_KEY", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("SECRET_GITHUB_TOKEN", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}")),
    ("SECRET_AWS_ACCESS_KEY", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    (
        "SECRET_JWT",
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."
            r"[A-Za-z0-9_-]{10,}"
        ),
    ),
    (
        "SECRET_PRIVATE_KEY",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "SECRET_URL_CREDENTIAL",
        re.compile(r"(?i)https?://[^\s:/]+:[^\s/@]+@"),
    ),
    (
        "SECRET_LITERAL_BEARER",
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    ),
)

SENSITIVE_ASSIGNMENT = re.compile(
    r"(?ix)"
    r"\b(?:api[_-]?key|access[_-]?token|app[_-]?token|user[_-]?token|"
    r"session[_-]?token|webhook[_-]?key|secret|password|authorization)\b"
    r"\s*[:=]\s*[\"']([^\"'\r\n]{8,})[\"']"
)

ENV_ASSIGNMENT = re.compile(
    r"^[ \t]*(?:export[ \t]+)?([A-Z][A-Z0-9_]*)[ \t]*=[ \t]*([^\r\n]*)[ \t]*$",
    re.MULTILINE,
)

SENSITIVE_ENV_NAME = re.compile(
    r"(?:API_KEY(?:_[A-Z0-9]+)*|PASSWORD|PASS|SECRET|AUTH|"
    r"(?:ACCESS|APP|USER|SESSION|FISCAL|REVIEW|LOCAL_API)_TOKEN|WEBHOOK_KEY)$"
)

SENSITIVE_JSON_KEYS = {
    "apikey",
    "accesstoken",
    "apptoken",
    "authorization",
    "password",
    "secret",
    "sessiontoken",
    "usertoken",
    "webhookkey",
}

SENSITIVE_HEADER_NAMES = {
    "app-token",
    "authorization",
    "proxy-authorization",
    "session-token",
    "x-api-key",
}

SAFE_LITERAL_MARKERS = (
    "change_me",
    "changeme",
    "placeholder",
    "example",
    "dummy",
    "fake",
    "redacted",
    "replace_me",
    "sua_chave",
    "sua-chave",
    "cole_sua",
    "not_configured",
    "not-configured",
    "[redacted]",
)


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("release manifest root must be an object")
    return document


def normalize_relative_path(value: str | Path) -> str:
    raw = str(value).replace("\\", "/")
    if not raw or "\x00" in raw:
        raise ValueError("empty or NUL-containing path")
    path = PurePosixPath(raw)
    if path.is_absolute() or path.anchor or ":" in path.parts[0]:
        raise ValueError("absolute paths are not accepted")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("path traversal is not accepted")
    return path.as_posix()


def _matches(path: str, pattern: str) -> bool:
    normalized = pattern.replace("\\", "/")
    if fnmatch.fnmatchcase(path, normalized):
        return True
    return normalized.startswith("**/") and fnmatch.fnmatchcase(path, normalized[3:])


def _allowed(path: str, manifest: dict[str, Any]) -> bool:
    rules = manifest.get("allowed_paths", {})
    if path in set(rules.get("exact", [])):
        return True
    return any(_matches(path, pattern) for pattern in rules.get("globs", []))


def validate_manifest_policy(manifest: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    if manifest.get("schema_version") != 1:
        issues.append(Issue("<manifest>", "MANIFEST_SCHEMA", "schema_version must be 1"))

    allowed = manifest.get("allowed_paths")
    if not isinstance(allowed, dict):
        return [Issue("<manifest>", "MANIFEST_ALLOWED", "allowed_paths must be an object")]

    exact = allowed.get("exact", [])
    globs = allowed.get("globs", [])
    required = manifest.get("required_files", [])
    canonical = manifest.get("canonical_n8n_workflows", [])
    for label, values in (
        ("allowed_paths.exact", exact),
        ("allowed_paths.globs", globs),
        ("required_files", required),
        ("canonical_n8n_workflows", canonical),
    ):
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            issues.append(Issue("<manifest>", "MANIFEST_TYPE", f"{label} must be a string list"))

    if issues:
        return issues

    if len(exact) != len(set(exact)):
        issues.append(Issue("<manifest>", "MANIFEST_DUPLICATE", "duplicate exact allowlist path"))
    if len(globs) != len(set(globs)):
        issues.append(Issue("<manifest>", "MANIFEST_DUPLICATE", "duplicate allowlist glob"))

    for value in [*exact, *required, *canonical]:
        try:
            normalized = normalize_relative_path(value)
        except ValueError as error:
            issues.append(Issue("<manifest>", "MANIFEST_PATH", f"invalid path: {error}"))
            continue
        if normalized != value:
            issues.append(Issue(value, "MANIFEST_PATH", "path is not normalized"))

    for path in required:
        if not _allowed(path, manifest):
            issues.append(Issue(path, "MANIFEST_REQUIRED_NOT_ALLOWED", "required path is not allowed"))
    for path in canonical:
        if path not in required:
            issues.append(Issue(path, "MANIFEST_CANONICAL_NOT_REQUIRED", "canonical V9 file is not required"))

    for path in exact:
        reason = forbidden_path_reason(path, manifest)
        if reason:
            issues.append(Issue(path, "MANIFEST_ALLOW_FORBIDDEN", reason))
    return sorted(set(issues))


def forbidden_path_reason(path: str, manifest: dict[str, Any]) -> str | None:
    basename = PurePosixPath(path).name.lower()
    forbidden_basenames = {item.lower() for item in manifest.get("forbidden_basenames", [])}
    if basename in forbidden_basenames or basename == ".gitignore":
        return f"forbidden basename {basename}"
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in {item.lower() for item in manifest.get("forbidden_extensions", [])}:
        return f"forbidden extension {suffix}"
    for pattern in manifest.get("forbidden_paths", []):
        if _matches(path, pattern):
            return f"forbidden path policy {pattern}"
    return None


def discover_manifest_candidates(root: Path, manifest: dict[str, Any]) -> list[str]:
    candidates: set[str] = set()
    rules = manifest.get("allowed_paths", {})
    for item in rules.get("exact", []):
        if (root / Path(item)).is_file():
            candidates.add(item)
    for pattern in rules.get("globs", []):
        for path in root.glob(pattern):
            if path.is_file():
                candidates.add(path.relative_to(root).as_posix())
    return sorted(candidates)


def discover_tree_candidates(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


def discover_git_candidates(root: Path, staged: bool = False) -> list[str]:
    command = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"]
    if not staged:
        command = ["git", "ls-files", "-z"]
    process = subprocess.run(command, cwd=root, capture_output=True, check=False)
    if process.returncode != 0:
        raise RuntimeError("Git could not enumerate candidate paths")
    return sorted(
        normalize_relative_path(item.decode("utf-8", errors="strict"))
        for item in process.stdout.split(b"\0")
        if item
    )


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _looks_safe_literal(value: str, path: str = "") -> bool:
    stripped = value.strip().strip("\"'")
    if not stripped:
        return True
    lower = stripped.lower()
    if any(marker in lower for marker in SAFE_LITERAL_MARKERS):
        return True
    if any(marker in stripped for marker in ("${", "$env", "process.env", "os.environ", "getenv(")):
        return True
    if re.search(r"\$[A-Za-z_][A-Za-z0-9_]*", stripped):
        return True
    if stripped.startswith("="):
        return True
    if "/tests/" in f"/{path}" and lower in {
        "local-secret",
        "test-secret",
        "segredo-endpoint-que-nao-deve-ir-ao-banco",
    }:
        return True
    return False


def _is_explicit_test_fixture(value: str, path: str) -> bool:
    if "/tests/" not in f"/{path}":
        return False
    lower = value.lower()
    return any(
        marker in lower
        for marker in (
            "must-never-be-public",
            "synthetic-secret-fixture",
            "dummy-secret",
        )
    )


def _iter_json(value: Any, json_path: str = "$") -> Iterable[tuple[str, str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{json_path}.{key}"
            yield child_path, str(key), child
            yield from _iter_json(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_json(child, f"{json_path}[{index}]")


def _iter_json_objects(value: Any, json_path: str = "$") -> Iterable[tuple[str, dict[str, Any]]]:
    if isinstance(value, dict):
        yield json_path, value
        for key, child in value.items():
            yield from _iter_json_objects(child, f"{json_path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_json_objects(child, f"{json_path}[{index}]")


def _validate_json_secrets(path: str, value: Any) -> list[Issue]:
    issues: list[Issue] = []
    for json_path, object_value in _iter_json_objects(value):
        header_name = str(object_value.get("name", "")).strip().lower().replace("_", "-")
        header_value = object_value.get("value")
        if (
            header_name in SENSITIVE_HEADER_NAMES
            and isinstance(header_value, str)
            and header_value.strip()
            and not _looks_safe_literal(header_value, path)
        ):
            issues.append(
                Issue(
                    path,
                    "SECRET_HEADER_LITERAL",
                    f"literal sensitive header at {json_path}",
                )
            )
    for json_path, key, child in _iter_json(value):
        normalized = re.sub(r"[^a-z0-9]", "", key.lower())
        if normalized not in SENSITIVE_JSON_KEYS or not isinstance(child, str):
            continue
        if len(child.strip()) >= 8 and not _looks_safe_literal(child, path):
            issues.append(
                Issue(path, "SECRET_JSON_LITERAL", f"literal sensitive value at {json_path}")
            )
    return issues


def _validate_n8n_json(
    path: str,
    value: Any,
    manifest: dict[str, Any],
) -> list[Issue]:
    issues: list[Issue] = []
    if not isinstance(value, dict) or not isinstance(value.get("nodes"), list):
        if isinstance(value, dict) and {"name", "type", "data"}.issubset(value):
            issues.append(Issue(path, "N8N_CREDENTIAL_EXPORT", "n8n credential export detected"))
        return issues

    policy = manifest.get("n8n_policy", {})
    canonical = set(manifest.get("canonical_n8n_workflows", []))
    symbolic_pattern = re.compile(policy.get("symbolic_credential_id_pattern", r"(?!)"))

    if policy.get("reject_nonempty_pin_data") and value.get("pinData") not in (None, {}, []):
        issues.append(Issue(path, "N8N_PIN_DATA", "non-empty pinData is forbidden"))

    for json_path, key, child in _iter_json(value):
        normalized = re.sub(r"[^a-z0-9]", "", key.lower())
        if normalized == "staticdata" and policy.get("reject_static_data"):
            issues.append(Issue(path, "N8N_STATIC_DATA", f"staticData is forbidden at {json_path}"))
        if normalized != "credentials":
            continue
        if not child:
            continue
        if path not in canonical or not policy.get("allow_symbolic_credential_references_only_in_canonical_v9"):
            issues.append(
                Issue(path, "N8N_CREDENTIAL_REFERENCE", f"credential reference is forbidden at {json_path}")
            )
            continue
        if not isinstance(child, dict):
            issues.append(Issue(path, "N8N_CREDENTIAL_SHAPE", f"invalid reference at {json_path}"))
            continue
        for credential_type, reference in child.items():
            if not isinstance(credential_type, str) or not isinstance(reference, dict):
                issues.append(Issue(path, "N8N_CREDENTIAL_SHAPE", f"invalid reference at {json_path}"))
                continue
            if set(reference) != {"id", "name"}:
                issues.append(
                    Issue(path, "N8N_CREDENTIAL_DATA", f"credential data is forbidden at {json_path}")
                )
                continue
            identifier = reference.get("id")
            name = reference.get("name")
            if not isinstance(identifier, str) or not symbolic_pattern.fullmatch(identifier):
                issues.append(
                    Issue(path, "N8N_CREDENTIAL_ID", f"credential id is not a symbolic placeholder at {json_path}")
                )
            if not isinstance(name, str) or not name.strip() or len(name) > 100:
                issues.append(Issue(path, "N8N_CREDENTIAL_NAME", f"invalid reference name at {json_path}"))
    return issues


def _validate_text(path: str, raw: bytes, manifest: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    if b"\0" in raw:
        return [Issue(path, "BINARY_CONTENT", "NUL byte detected")]
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [Issue(path, "TEXT_ENCODING", "file is not valid UTF-8")]

    for code, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            if _is_explicit_test_fixture(match.group(0), path):
                continue
            issues.append(Issue(path, code, "secret-shaped literal detected", _line_number(text, match.start())))

    for match in SENSITIVE_ASSIGNMENT.finditer(text):
        if not _looks_safe_literal(match.group(1), path):
            issues.append(
                Issue(
                    path,
                    "SECRET_LITERAL_ASSIGNMENT",
                    "hard-coded sensitive assignment detected",
                    _line_number(text, match.start()),
                )
            )

    if PurePosixPath(path).name.startswith(".env"):
        for match in ENV_ASSIGNMENT.finditer(text):
            key, value = match.groups()
            if SENSITIVE_ENV_NAME.search(key) and not _looks_safe_literal(value, path):
                issues.append(
                    Issue(
                        path,
                        "SECRET_ENV_LITERAL",
                        f"non-placeholder value assigned to {key}",
                        _line_number(text, match.start()),
                    )
                )

    if PurePosixPath(path).suffix.lower() == ".json":
        try:
            document = json.loads(text)
        except json.JSONDecodeError as error:
            issues.append(Issue(path, "JSON_INVALID", "invalid JSON", error.lineno))
        else:
            issues.extend(_validate_json_secrets(path, document))
            issues.extend(_validate_n8n_json(path, document, manifest))
    return issues


def validate_release(
    root: Path,
    candidates: Sequence[str | Path],
    manifest: dict[str, Any],
    *,
    require_required: bool = True,
) -> list[Issue]:
    issues = validate_manifest_policy(manifest)
    normalized_candidates: set[str] = set()
    root_resolved = root.resolve()

    for candidate in candidates:
        try:
            path = normalize_relative_path(candidate)
        except ValueError as error:
            issues.append(Issue(str(candidate), "PATH_INVALID", str(error)))
            continue
        normalized_candidates.add(path)

        forbidden = forbidden_path_reason(path, manifest)
        if forbidden:
            issues.append(Issue(path, "PATH_FORBIDDEN", forbidden))
            continue
        if not _allowed(path, manifest):
            issues.append(Issue(path, "PATH_NOT_ALLOWED", "path is outside the public allowlist"))
            continue

        file_path = root / Path(path)
        try:
            resolved = file_path.resolve(strict=True)
        except (OSError, RuntimeError):
            issues.append(Issue(path, "FILE_MISSING", "candidate file is missing"))
            continue
        try:
            resolved.relative_to(root_resolved)
        except ValueError:
            issues.append(Issue(path, "PATH_ESCAPE", "candidate resolves outside the release root"))
            continue
        if file_path.is_symlink():
            issues.append(Issue(path, "SYMLINK_FORBIDDEN", "symbolic links are not published"))
            continue
        if not resolved.is_file():
            issues.append(Issue(path, "FILE_TYPE", "candidate is not a regular file"))
            continue

        maximum = int(manifest.get("max_file_bytes", 0))
        size = resolved.stat().st_size
        if maximum > 0 and size > maximum:
            issues.append(Issue(path, "FILE_TOO_LARGE", f"file exceeds {maximum} bytes"))
            continue
        try:
            raw = resolved.read_bytes()
        except OSError:
            issues.append(Issue(path, "FILE_READ", "candidate could not be read"))
            continue
        issues.extend(_validate_text(path, raw, manifest))

    if require_required:
        for required in manifest.get("required_files", []):
            if required not in normalized_candidates:
                issues.append(Issue(required, "REQUIRED_MISSING", "required public file is absent"))
    return sorted(set(issues))


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--source",
        choices=("git-index", "staged", "manifest", "tree"),
        default="git-index",
        help="candidate set to validate; git-index is the authoritative publication gate",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=PROJECT_ROOT,
        help="project root, or export bundle root when --source tree is used",
    )
    parser.add_argument("--json", action="store_true", help="emit a machine-readable report")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        manifest = load_manifest(args.manifest.resolve())
        root = args.root.resolve()
        if args.source == "git-index":
            candidates = discover_git_candidates(root)
            require_required = True
        elif args.source == "staged":
            candidates = discover_git_candidates(root, staged=True)
            require_required = False
            if not candidates:
                raise RuntimeError("Git has no staged candidate files")
        elif args.source == "manifest":
            candidates = discover_manifest_candidates(root, manifest)
            require_required = True
        else:
            candidates = discover_tree_candidates(root)
            require_required = True
        issues = validate_release(root, candidates, manifest, require_required=require_required)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, RuntimeError) as error:
        if args.json:
            print(json.dumps({"status": "ERROR", "error": str(error)}, ensure_ascii=False))
        else:
            print(f"ERROR: {error}", file=sys.stderr)
        return 2

    status = "PASS" if not issues else "FAIL"
    if args.json:
        print(
            json.dumps(
                {
                    "status": status,
                    "policy_id": manifest.get("policy_id"),
                    "source": args.source,
                    "candidate_count": len(candidates),
                    "issue_count": len(issues),
                    "issues": [
                        {
                            "path": issue.path,
                            "line": issue.line,
                            "code": issue.code,
                            "detail": issue.detail,
                        }
                        for issue in issues
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for issue in issues:
            print(issue.render())
        print(
            f"{status}: policy={manifest.get('policy_id')} source={args.source} "
            f"files={len(candidates)} issues={len(issues)}"
        )
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
