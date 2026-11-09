#!/usr/bin/env python3
"""Gera o arquivo ZIP do projeto contendo a base operacional, datasets de teste,
corpora de treino, scripts de testes, drills de homologação, testes de regressão
e testes unitários, preservando os chamados do GLPI e excluindo arquivos temporários e caches.

Exclui:
- Ambientes virtuais (.venv, venv) e caches (.pytest_cache, __pycache__, *.pyc)
- Repositório Git e histórico interno (.git)
- Saídas de logs e runs históricos pesados (avaliacao/resultados/, outputs/)
- Segredos vivos de ambiente local (glpi/.env, n8n/.env)
- Binários pesados de pesos de modelos locais (local_ai/models/*.gguf, pesos > 100MB)
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ZIP_NAME = "projeto-base-limpo.zip"

ROOT_FILES = (
    ".gitattributes",
    ".gitignore",
    "CITATION.cff",
    "DEPLOYMENT_AND_VALIDATION_V9.md",
    "LICENSE",
    "NOTICE",
    "QUICK_START.md",
    "README.md",
    "SECURITY.md",
    "requirements.txt",
    "pytest.ini",
    "verify.py",
)

FORBIDDEN_SUBSTRINGS = (
    "__pycache__",
    ".pyc",
    ".pyo",
    ".venv",
    ".pytest_cache",
    ".git/",
    "avaliacao/resultados",
    "outputs/",
    "backups/n8n",
)


def collect_project_files(root: Path = PROJECT_ROOT) -> list[str]:
    files_to_pack: set[str] = set()

    # 1. Raiz
    for rf in ROOT_FILES:
        p = root / rf
        if p.is_file():
            files_to_pack.add(rf)

    # 2. Database
    for p in (root / "database").rglob("*"):
        if p.is_file():
            files_to_pack.add(p.relative_to(root).as_posix())

    # 3. GLPI (incluindo seed scripts, sql de chamados e o dump com os chamados injetados)
    for p in (root / "glpi").rglob("*"):
        rel = p.relative_to(root).as_posix()
        if p.is_file():
            if "__pycache__" in rel or rel.endswith((".pyc", ".pyo")):
                continue
            if rel in {"glpi/.env", "glpi/.env.homolog"}:
                continue
            if "glpi/backups" in rel:
                # Inclui o dump do GLPI contendo as tabelas e chamados injetados
                if rel == "glpi/backups/glpi_backup_20260309_141817.sql":
                    files_to_pack.add(rel)
                continue
            files_to_pack.add(rel)

    # 4. Local AI (código, testes unitários, scripts de benchmark, artefatos do modelo, manifestos)
    for p in (root / "local_ai").rglob("*"):
        rel = p.relative_to(root).as_posix()
        if p.is_file():
            if "__pycache__" in rel or rel.endswith((".pyc", ".pyo")):
                continue
            if "runtime" in rel or "artifacts/candidates" in rel:
                continue
            if rel.startswith("local_ai/models/"):
                if rel not in {"local_ai/models/manifest.json", "local_ai/models/.gitkeep"}:
                    continue
            files_to_pack.add(rel)

    # 5. n8n (workflows V9, construtores, testes de regressão V9, histórico V1-V8 e testes do histórico)
    for p in (root / "n8n").rglob("*"):
        rel = p.relative_to(root).as_posix()
        if p.is_file():
            if "__pycache__" in rel or rel.endswith((".pyc", ".pyo")):
                continue
            if rel.startswith("n8n/.env") and not rel.endswith(".example"):
                continue
            if "workflows/Teste01_" in rel or "workflows/Versão8" in rel:
                continue
            if rel.startswith("n8n/workflows/all_workflows") or rel.startswith("n8n/workflows/v7_"):
                continue
            if rel == "n8n/credentials/SMTP_Mailpit_Local.json":
                continue
            files_to_pack.add(rel)

    # 6. Scripts e seus testes unitários
    for p in (root / "scripts").rglob("*"):
        rel = p.relative_to(root).as_posix()
        if p.is_file():
            if "__pycache__" in rel or rel.endswith((".pyc", ".pyo")):
                continue
            files_to_pack.add(rel)

    # 7. Documentação
    for p in (root / "docs").rglob("*"):
        rel = p.relative_to(root).as_posix()
        if p.is_file():
            if rel.startswith("docs/inventario_") and rel.endswith(".csv"):
                continue
            files_to_pack.add(rel)

    # 8. Avaliação completa: Datasets de teste, corpora de treino, scripts, testes, drills operacionais
    for p in (root / "avaliacao").rglob("*"):
        rel = p.relative_to(root).as_posix()
        if p.is_file():
            if "__pycache__" in rel or rel.endswith((".pyc", ".pyo")):
                continue
            # Exclui apenas resultados/logs de execuções passadas e runtime efêmero
            if rel.startswith("avaliacao/resultados") or "runtime" in rel:
                continue
            files_to_pack.add(rel)

    sorted_files = sorted(files_to_pack)

    # Validação de segurança
    violations: list[tuple[str, str]] = []
    for path in sorted_files:
        for marker in FORBIDDEN_SUBSTRINGS:
            if marker in path:
                violations.append((path, marker))

    if violations:
        print("Erro: violações detectadas na seleção do pacote limpo:", file=sys.stderr)
        for path, marker in violations:
            print(f"  - {path} (regra: {marker})", file=sys.stderr)
        raise RuntimeError(f"{len(violations)} arquivos proibidos na lista")

    return sorted_files


def generate_zip(output_zip: Path = PROJECT_ROOT / DEFAULT_ZIP_NAME, root: Path = PROJECT_ROOT) -> Path:
    files = collect_project_files(root)
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel in files:
            full_path = root / rel
            zf.write(full_path, arcname=rel)

    return output_zip


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera zip com projeto base, testes e datasets")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=PROJECT_ROOT / DEFAULT_ZIP_NAME,
        help="Caminho do arquivo zip de saída",
    )
    args = parser.parse_args()

    out = generate_zip(args.output)
    stat = out.stat()
    print(f"Zip gerado com sucesso em: {out}")
    print(f"Tamanho comprimido: {stat.st_size / 1024:.1f} KB ({stat.st_size / (1024*1024):.2f} MB)")


if __name__ == "__main__":
    main()
