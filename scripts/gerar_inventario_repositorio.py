"""Gera inventário mecânico e reproduzível dos arquivos publicáveis do projeto.

O inventário enumera arquivos rastreados e arquivos não ignorados. Ele não
substitui revisão semântica: a prioridade e a destinação são classificações
conservadoras para orientar a auditoria humana.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import subprocess
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path


CANONICAL = {
    "README.md",
    "docs/SOURCE_OF_TRUTH.md",
    "docs/auditoria_continuacao_2026-09-10.md",
    "docs/politica_organizacao_retencao.md",
    "docs/auditoria_critica_completa_2026-09-01.md",
    "docs/auditoria_critica_completa_2026-08-26.md",
    "docs/resposta_professor_2026-08-26.md",
    "docs/tutorial_reproducao_e_implantacao.md",
    "docs/TEST_REPORT.md",
    "avaliacao/config/selecao_modelos_supervisionados_v2.json",
    "avaliacao/config/selecao_classificacao_supervisionada_v2_1.json",
    "avaliacao/metodologia_avaliacao_v2_1.md",
    "avaliacao/PRE_REGISTRO_PENDENTE.md",
    "avaliacao/confirmatorio/README.md",
    "avaliacao/operacional/README.md",
    "avaliacao/piloto_sombra/README.md",
}

CODE_EXTENSIONS = {
    ".py",
    ".ps1",
    ".js",
    ".php",
    ".sql",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
}


def git_paths(root: Path, *args: str) -> set[str]:
    completed = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files", "-z", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return {
        item.decode("utf-8").replace("\\", "/")
        for item in completed.stdout.split(b"\0")
        if item
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classify(path: str, tracked: bool) -> tuple[str, str, str]:
    lower = path.lower()
    suffix = Path(path).suffix.lower()

    if path in CANONICAL:
        return "documentacao_canonica", "P0", "KEEP_CANONICAL"
    if lower.startswith("n8n/workflows/versão9/"):
        return "workflow_v9", "P0", "KEEP_CANONICAL"
    if lower.startswith("n8n/history/"):
        return "historico_workflows", "P1", "KEEP_HISTORICAL"
    if "/tests/" in lower or Path(path).name.lower().startswith("test_"):
        return "teste", "P1", "KEEP_CODE"
    if lower.startswith("avaliacao/datasets/"):
        return "dataset", "P1", "KEEP_EVIDENCE"
    if lower.startswith("avaliacao/resultados/"):
        if "selecao-supervisionada-v2.1-20260826" in lower:
            return "resultado_corrente", "P0", "KEEP_EVIDENCE"
        if "selecao-supervisionada-v2/" in lower:
            return "resultado_invalidado", "P1", "KEEP_HISTORICAL"
        return "resultado_historico", "P2", "REVIEW_RETENTION"
    if suffix in CODE_EXTENSIONS:
        return "codigo_configuracao", "P1", "KEEP_CODE"
    if suffix in {".md", ".txt"}:
        return "documentacao_historica_ou_auxiliar", "P2", "KEEP_HISTORICAL"
    if suffix in {".joblib", ".png", ".csv", ".json", ".jsonl"}:
        return "artefato_ou_evidencia", "P2", "REVIEW_RETENTION"
    if not tracked:
        return "nao_rastreado_publicavel", "P1", "REVIEW_BEFORE_COMMIT"
    return "outro", "P2", "REVIEW_RETENTION"


def main() -> int:
    parser = argparse.ArgumentParser()
    today = date.today().isoformat()
    parser.add_argument(
        "--csv",
        default=f"docs/inventario_arquivos_versionados_{today}.csv",
    )
    parser.add_argument(
        "--summary",
        default=f"docs/inventario_arquivos_versionados_{today}.md",
    )
    parser.add_argument("--as-of", default=today, help="data do snapshot, AAAA-MM-DD")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    tracked = git_paths(root, "--cached")
    untracked = git_paths(root, "--others", "--exclude-standard")
    output_paths = {
        Path(args.csv).as_posix(),
        Path(args.summary).as_posix(),
    }
    publishable = sorted((tracked | untracked) - output_paths)

    rows: list[dict[str, object]] = []
    for relative in publishable:
        absolute = root / relative
        if not absolute.is_file():
            continue
        role, priority, disposition = classify(relative, relative in tracked)
        rows.append(
            {
                "path": relative,
                "tracked": str(relative in tracked).lower(),
                "bytes": absolute.stat().st_size,
                "sha256": sha256(absolute),
                "area": relative.split("/", 1)[0],
                "extension": absolute.suffix.lower() or "(none)",
                "audit_role": role,
                "audit_priority": priority,
                "recommended_disposition": disposition,
            }
        )

    csv_path = root / args.csv
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    role_counts = Counter(str(row["audit_role"]) for row in rows)
    role_bytes: dict[str, int] = defaultdict(int)
    for row in rows:
        role_bytes[str(row["audit_role"])] += int(row["bytes"])

    summary_path = root / args.summary
    lines = [
        f"# Inventário arquivo por arquivo — {args.as_of}",
        "",
        "> Inventário mecânico dos arquivos rastreados e não ignorados no momento",
        "> da geração. SHA-256 comprova identidade; não comprova correção nem",
        "> validade científica. A classificação de prioridade orienta, mas não",
        "> substitui, a revisão semântica baseada em risco.",
        "",
        f"- arquivos enumerados: **{len(rows)}**;",
        f"- bytes enumerados: **{sum(int(row['bytes']) for row in rows):,}**;",
        f"- rastreados no índice: **{sum(row['tracked'] == 'true' for row in rows)}**;",
        f"- não rastreados e não ignorados: **{sum(row['tracked'] == 'false' for row in rows)}**;",
        f"- inventário detalhado: `{Path(args.csv).name}`.",
        "",
        "| Papel mecânico | Arquivos | Bytes |",
        "|---|---:|---:|",
    ]
    for role in sorted(role_counts):
        lines.append(f"| `{role}` | {role_counts[role]} | {role_bytes[role]:,} |")
    lines.extend(
        [
            "",
            "## Interpretação",
            "",
            "A auditoria aprofundou código, dados e documentos de maior risco. Arquivos",
            "gerados/binários foram validados por identidade, estrutura, proveniência e",
            "reprodutibilidade quando havia gerador; não é correto alegar leitura manual",
            "linha a linha de cada binário. Itens `REVIEW_RETENTION` são preservados por",
            "rastreabilidade, mas devem entrar em uma política futura de retenção.",
            "",
            "Regere após mudanças relevantes:",
            "",
            "```powershell",
            "python scripts/gerar_inventario_repositorio.py",
            "```",
        ]
    )
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Inventário gerado: {len(rows)} arquivos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
