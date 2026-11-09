#!/usr/bin/env python3
"""Validador de Consistência Científica e Não-Contradição da Documentação.

Garante que nenhuma afirmação em README ou docs entre em conflito com os manifests
congelados, com a hierarquia de fontes de verdade (SOURCE_OF_TRUTH.md) ou com os
limites estatísticos comprovados.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = ROOT / "docs"
README_FILE = ROOT / "README.md"

# Padrões rigorosamente proibidos por configurarem overclaim científico
PROHIBITED_PATTERNS = [
    (
        re.compile(r"validação científica (?:está )?(?:100% )?concluída", re.IGNORECASE),
        "Afirmação indevida de validação científica 100% concluída. O holdout confirmatório ainda é pendente."
    ),
    (
        re.compile(r"UCB(?:95)?\s*[:=]?\s*0(?:\.0+)?%", re.IGNORECASE),
        "Afirmação indevida de UCB95 = 0% para eventos com zero falhas. Deve reportar UCB95 <= 2.30% via Regra de Três."
    ),
    (
        re.compile(r"SHAP comprovou causalidade", re.IGNORECASE),
        "Uso indevido de SHAP como prova causal. SHAP é método de atribuição de atributos, não inferência causal."
    ),
    (
        re.compile(r"proteção total contra (?:prompt )?injection", re.IGNORECASE),
        "Overclaim de proteção universal contra prompt injection. Deve reportar 100% no benchmark controlado avaliado."
    ),
    (
        re.compile(r"status.*produção & pesquisa", re.IGNORECASE),
        "Status do projeto no README não pode ser 'Produção & Pesquisa' enquanto a validação confirmatória for pendente."
    )
]

FILES_TO_CHECK = [
    README_FILE,
    DOCS_DIR / "diagnostico_validacao_cientifica.md",
    DOCS_DIR / "resultados_estatisticos_e_comparativo_gemini.md",
    DOCS_DIR / "SOURCE_OF_TRUTH.md",
    DOCS_DIR / "justificativa_override_deduplicacao.md",
]


def check_file(file_path: Path) -> list[str]:
    if not file_path.exists():
        return [f"Arquivo não encontrado: {file_path}"]
    
    content = file_path.read_text(encoding="utf-8")
    errors = []
    
    for pattern, msg in PROHIBITED_PATTERNS:
        for match in pattern.finditer(content):
            start = max(0, match.start() - 100)
            end = min(len(content), match.end() + 100)
            snippet = content[start:end].replace('\n', ' ').lower()
            # Pular se o trecho estiver citando a proibição ou em SOURCE_OF_TRUTH
            if any(term in snippet for term in ["nenhum documento", "não afirme", "não pode", "proibid", "incorret", "prevalecem"]):
                continue
            errors.append(f"[{file_path.name}] {msg} (Trecho: '{match.group(0)}')")
            
    return errors


def main() -> int:
    all_errors = []
    for f in FILES_TO_CHECK:
        all_errors.extend(check_file(f))
        
    if all_errors:
        print("=" * 80)
        print("FALHA NA CONSISTENCIA CIENTIFICA DOCUMENTAL:")
        for err in all_errors:
            print(f"  [ERRO] {err}")
        print("=" * 80)
        return 1
        
    print("=" * 80)
    print("[APROVADO] Consistencia cientifica documental aprovada: zero overclaims detectados.")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
