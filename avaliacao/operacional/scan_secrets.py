from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "avaliacao" / "resultados" / "operacional" / "varredura-segredos-20260902.json"
MAX_BYTES = 2 * 1024 * 1024
PLACEHOLDERS = {
    "",
    "change_me",
    "changeme",
    "example",
    "placeholder",
    "seu_token",
    "sua_senha",
    "your_token",
    "your_password",
    "dummy",
    "test",
    "false",
    "true",
}
PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    "openai_key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
}
KNOWN_SAFE_EXAMPLE_FINGERPRINTS = {
    ("n8n/.env.example", "V9_E2E_FISCAL_TOKEN", "60f1b1e4c652a2c9"),
    ("n8n/.env.example", "GEMINI_API_KEY_PRIMARY", "574c79ff1ec3ef58"),
    ("n8n/.env.local.example", "GEMINI_API_KEY", "d55223319c4679e1"),
}
ASSIGNMENT = re.compile(
    r"(?m)^\s*(?:export\s+)?([A-Z][A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|API_KEY|AUTH_BASIC|TOKEN)[A-Z0-9_]*)\s*[:=]\s*['\"]?([^\s'\"#]{12,})"
)
DIRECT_STRUCTURED_CREDENTIAL = re.compile(
    r"(?i)[\"']?(APP[-_]?TOKEN|X[-_]?WEBHOOK[-_]?KEY|AUTHORIZATION)[\"']?\s*[:=]\s*[\"']([^\"']{12,})[\"']"
)
NAMED_HEADER_CREDENTIAL = re.compile(
    r"(?is)[\"']name[\"']\s*:\s*[\"'](APP[-_]?TOKEN|X[-_]?WEBHOOK[-_]?KEY|AUTHORIZATION)[\"']"
    r".{0,160}?[\"']value[\"']\s*:\s*[\"']([^\"']{12,})[\"']"
)


def _run(command: list[str], *, binary: bool = False, input_data: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=ROOT,
        input=input_data,
        capture_output=True,
        text=not binary,
        timeout=300,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _is_placeholder(value: str) -> bool:
    lowered = value.strip().strip("'\"").lower()
    return (
        lowered in PLACEHOLDERS
        or "change_me" in lowered
        or "example" in lowered
        or "placeholder" in lowered
        or lowered.startswith("${")
        or lowered.startswith("={{")
        or lowered.startswith("{{")
        or lowered.startswith("$")
        or lowered.startswith("%")
        or lowered.startswith("process.env")
        or lowered.startswith("os.getenv")
        or "getenv(" in lowered
        or "$env." in lowered
        or lowered.startswith("test")
        or lowered.startswith("dummy")
        or lowered.startswith("validacao")
        or lowered.startswith("nao_")
        or lowered.startswith("nunca_")
        or lowered.startswith("inativo")
    )


def _scan_text(text: str, path: str, scope: str, blob: str | None = None) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for rule, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            value = match.group(0)
            findings.append(
                {
                    "scope": scope,
                    "path": path,
                    "rule": rule,
                    "line": text.count("\n", 0, match.start()) + 1,
                    "fingerprint": _fingerprint(value),
                    "blob": blob,
                }
            )
    for match in ASSIGNMENT.finditer(text):
        name, value = match.groups()
        normalized_path = path.replace("\\", "/").lower()
        fingerprint = _fingerprint(value)
        if (
            _is_placeholder(value)
            or name.endswith(("_RE", "_EXPR", "_PATTERN", "_PATTERNS"))
            or "/tests/" in f"/{normalized_path}"
            or (normalized_path, name, fingerprint) in KNOWN_SAFE_EXAMPLE_FINGERPRINTS
        ):
            continue
        findings.append(
            {
                "scope": scope,
                "path": path,
                "rule": "credential_assignment",
                "variable": name,
                "line": text.count("\n", 0, match.start()) + 1,
                "fingerprint": fingerprint,
                "blob": blob,
            }
        )
    for pattern in (DIRECT_STRUCTURED_CREDENTIAL, NAMED_HEADER_CREDENTIAL):
        for match in pattern.finditer(text):
            name, value = match.groups()
            normalized_path = path.replace("\\", "/").lower()
            if _is_placeholder(value) or "/tests/" in f"/{normalized_path}" or normalized_path.startswith("tests/"):
                continue
            if Path(normalized_path).name.startswith("test_"):
                continue
            findings.append(
                {
                    "scope": scope,
                    "path": path,
                    "rule": "structured_credential_literal",
                    "variable": name.upper().replace("_", "-"),
                    "line": text.count("\n", 0, match.start()) + 1,
                    "fingerprint": _fingerprint(value),
                    "blob": blob,
                }
            )
    return findings


def _candidate_files() -> list[str]:
    completed = _run(["git", "ls-files", "-co", "--exclude-standard", "-z"], binary=True)
    if completed.returncode != 0:
        raise RuntimeError("git ls-files falhou")
    return sorted(value.decode("utf-8", errors="surrogateescape") for value in completed.stdout.split(b"\0") if value)


def _is_release_surface(relative: str) -> bool:
    normalized = relative.replace("\\", "/")
    exact = {
        "README.md",
        "requirements.txt",
        "n8n/docker-compose.yml",
        "glpi/docker-compose.yml",
    }
    prefixes = (
        ".github/workflows/",
        "avaliacao/config/",
        "avaliacao/operacional/",
        "avaliacao/scripts/",
        "docs/",
        "glpi/plugins/n8nwebhook/",
        "local_ai/app/",
        "n8n/proxies/",
        "n8n/workflows/Versão9/",
        "scripts/",
    )
    excluded = (
        "avaliacao/operacional/tests/",
        "avaliacao/resultados/",
        "avaliacao/runtime/",
        "scripts/tests/",
    )
    return normalized in exact or (
        normalized.startswith(prefixes) and not normalized.startswith(excluded)
    )


def _scan_candidate(*, release_only: bool = False) -> tuple[list[dict[str, object]], list[str]]:
    findings: list[dict[str, object]] = []
    skipped: list[str] = []
    for relative in _candidate_files():
        if release_only and not _is_release_surface(relative):
            continue
        path = ROOT / relative
        try:
            is_file = path.is_file()
            size = path.stat().st_size if is_file else 0
        except OSError:
            skipped.append(relative)
            continue
        if not is_file:
            continue
        if size > MAX_BYTES:
            try:
                with path.open("r", encoding="utf-8", errors="ignore") as source:
                    for line_number, line in enumerate(source, start=1):
                        line_findings = _scan_text(line, relative, "candidate_tree")
                        for finding in line_findings:
                            finding["line"] = line_number
                        findings.extend(line_findings)
            except OSError:
                skipped.append(relative)
            continue
        try:
            content = path.read_bytes()
        except OSError:
            skipped.append(relative)
            continue
        if b"\0" in content[:8192]:
            continue
        findings.extend(_scan_text(content.decode("utf-8", errors="ignore"), relative, "candidate_tree"))
    return findings, skipped


def _history_objects() -> tuple[list[str], dict[str, str]]:
    completed = _run(["git", "rev-list", "--objects", "--all"], binary=True)
    if completed.returncode != 0:
        raise RuntimeError("git rev-list falhou")
    shas: list[str] = []
    seen: set[str] = set()
    paths: dict[str, str] = {}
    for raw in completed.stdout.decode("utf-8", errors="surrogateescape").splitlines():
        sha, _, path = raw.partition(" ")
        if sha not in seen:
            shas.append(sha)
            seen.add(sha)
        if path and sha not in paths:
            paths[sha] = path
    return shas, paths


def _blob_metadata(shas: Iterable[str]) -> list[tuple[str, int]]:
    payload = ("\n".join(shas) + "\n").encode("ascii")
    completed = _run(
        ["git", "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)"],
        binary=True,
        input_data=payload,
    )
    if completed.returncode != 0:
        raise RuntimeError("git cat-file --batch-check falhou")
    result: list[tuple[str, int]] = []
    for line in completed.stdout.decode("ascii", errors="ignore").splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1] == "blob" and int(parts[2]) <= MAX_BYTES:
            result.append((parts[0], int(parts[2])))
    return result


def _scan_history() -> tuple[list[dict[str, object]], int]:
    shas, paths = _history_objects()
    blobs = _blob_metadata(shas)
    findings: list[dict[str, object]] = []
    with tempfile.TemporaryFile() as requests:
        requests.write(("\n".join(sha for sha, _ in blobs) + "\n").encode("ascii"))
        requests.seek(0)
        process = subprocess.Popen(
            ["git", "cat-file", "--batch"],
            cwd=ROOT,
            stdin=requests,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        assert process.stdout is not None
        for requested_sha, _ in blobs:
            header = process.stdout.readline().decode("ascii", errors="ignore").split()
            if len(header) != 3:
                process.kill()
                raise RuntimeError("Resposta inválida de git cat-file --batch")
            size = int(header[2])
            content = process.stdout.read(size)
            process.stdout.read(1)
            if b"\0" in content[:8192]:
                continue
            findings.extend(
                _scan_text(
                    content.decode("utf-8", errors="ignore"),
                    paths.get(requested_sha, "<historical-blob>"),
                    "reachable_git_history",
                    requested_sha,
                )
            )
        process.wait(timeout=300)
        if process.returncode != 0:
            raise RuntimeError("git cat-file --batch falhou")
    unique = {
        (row["scope"], row["path"], row["rule"], row["fingerprint"], row.get("blob")): row
        for row in findings
    }
    return list(unique.values()), len(blobs)


def main() -> int:
    parser = argparse.ArgumentParser(description="Varredura local de segredos sem imprimir os valores.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--scope", choices=("release", "candidate", "all"), default="all")
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(ROOT.resolve())
    if output.exists():
        raise RuntimeError(f"Evidência já existe: {output}")
    candidate, skipped = _scan_candidate(release_only=args.scope == "release")
    history, history_blobs = _scan_history() if args.scope == "all" else ([], 0)
    result = {
        "schema_version": "1.1.0",
        "candidate_tree": {
            "status": "PASS" if not candidate else "FAIL",
            "finding_count": len(candidate),
            "findings": candidate,
            "large_text_files_not_content_scanned": skipped,
        },
        "reachable_git_history": {
            "status": "NOT_RUN" if args.scope != "all" else ("PASS" if not history else "FAIL"),
            "blob_count_scanned": history_blobs,
            "finding_count": len(history),
            "findings": history,
        },
        "secrets_printed": False,
        "scientific_result": False,
        "requires_rotation_or_history_remediation": (
            bool(history or candidate) if args.scope == "all" else None
        ),
        "interpretation_limit": (
            "Varredura por padrões reduz risco, mas não prova ausência absoluta de segredos. "
            "Arquivos binários e textos acima de 2 MiB não foram lidos como conteúdo."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "candidate_status": result["candidate_tree"]["status"],
                "candidate_findings": len(candidate),
                "history_status": result["reachable_git_history"]["status"],
                "history_findings": len(history),
                "output": str(output),
            },
            ensure_ascii=False,
        )
    )
    return 0 if not candidate else 1


if __name__ == "__main__":
    raise SystemExit(main())
