from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def normalize_text(case: dict) -> str:
    raw = " ".join(
        str(case.get(field, "") or "")
        for field in ("title", "content", "location")
    )
    plain = "".join(
        char
        for char in unicodedata.normalize("NFD", raw.lower())
        if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", " ", plain).strip()


def validate(
    cases: list[dict],
    comparison: list[dict] | None = None,
    target_distribution: dict[str, float] | None = None,
    tolerance: float = 0.10,
) -> list[str]:
    errors: list[str] = []
    case_ids = [case["case_id"] for case in cases]
    if len(case_ids) != len(set(case_ids)):
        errors.append("case_id duplicado")
    episodes: dict[str, list[dict]] = defaultdict(list)
    normalized_cases: dict[str, list[str]] = defaultdict(list)
    for case in cases:
        episodes[case["episode_id"]].append(case)
        visible = f"{case.get('title','')} {case.get('content','')}"
        if case["case_id"] in visible or "[AVAL-" in visible:
            errors.append(f"{case['case_id']}: identificador experimental visível")
        if case.get("group_id") != case.get("episode_id"):
            errors.append(f"{case['case_id']}: group_id e episode_id divergentes")
        if case.get("label_source") != "REGRA_SINTETICA_PENDENTE_ESPECIALISTA":
            errors.append(f"{case['case_id']}: label_source inválido")
        normalized_cases[normalize_text(case)].append(case["case_id"])
    for normalized, ids in normalized_cases.items():
        if normalized and len(ids) > 1:
            errors.append(
                "texto normalizado duplicado internamente: " + ",".join(ids)
            )
    by_id = {case["case_id"]: case for case in cases}
    for episode_id, episode in episodes.items():
        episode.sort(key=lambda item: int(item["order_in_group"]))
        orders = [int(item["order_in_group"]) for item in episode]
        if orders != list(range(1, len(episode) + 1)):
            errors.append(f"{episode_id}: ordem não contígua")
        for case in episode:
            reference = case.get("reference_case_id")
            if case.get("expected_dedup") is True and not reference:
                errors.append(f"{case['case_id']}: duplicado sem referência")
            if not reference:
                continue
            target = by_id.get(reference)
            if not target:
                errors.append(f"{case['case_id']}: referência inexistente")
            elif target["episode_id"] != episode_id:
                errors.append(f"{case['case_id']}: referência fora do episódio")
            elif int(target["order_in_group"]) >= int(case["order_in_group"]):
                errors.append(f"{case['case_id']}: referência não antecede o caso")
    if comparison:
        comparison_ids = {case["case_id"] for case in comparison}
        reused_ids = sorted(set(case_ids) & comparison_ids)
        if reused_ids:
            errors.append(
                "case_id reutilizado entre splits: " + ",".join(reused_ids[:10])
            )
        comparison_episodes = {case["episode_id"] for case in comparison}
        reused_episodes = sorted(set(episodes) & comparison_episodes)
        if reused_episodes:
            errors.append(
                "episode_id reutilizado entre splits: "
                + ",".join(reused_episodes[:10])
            )
        comparison_texts = {
            normalize_text(case) for case in comparison if normalize_text(case)
        }
        leaked = [
            case["case_id"]
            for case in cases
            if normalize_text(case) in comparison_texts
        ]
        if leaked:
            errors.append(
                "texto idêntico vazou entre splits: " + ",".join(leaked[:10])
            )
    if target_distribution:
        classified = [
            case["expected_classification"]
            for case in cases
            if case.get("expected_classification")
        ]
        counts = Counter(classified)
        total = len(classified)
        if not total:
            errors.append("distribuição-alvo informada sem casos de classificação")
        else:
            for label, expected in target_distribution.items():
                observed = counts[label] / total
                if abs(observed - float(expected)) > tolerance:
                    errors.append(
                        f"distribuição {label}: observada={observed:.4f}, "
                        f"alvo={float(expected):.4f}, tolerância={tolerance:.4f}"
                    )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument(
        "--comparar-com",
        type=Path,
        help="Outro split usado para detectar reutilização de IDs/textos.",
    )
    parser.add_argument(
        "--distribuicao-alvo",
        type=Path,
        help="JSON no formato {classe: proporcao}; só use se houver estimativa real.",
    )
    parser.add_argument("--tolerancia-distribuicao", type=float, default=0.10)
    args = parser.parse_args()
    cases = load(args.dataset)
    comparison = load(args.comparar_com) if args.comparar_com else None
    target_distribution = (
        json.loads(args.distribuicao_alvo.read_text(encoding="utf-8"))
        if args.distribuicao_alvo
        else None
    )
    errors = validate(
        cases,
        comparison=comparison,
        target_distribution=target_distribution,
        tolerance=args.tolerancia_distribuicao,
    )
    if errors:
        for error in errors:
            print(f"ERRO: {error}")
        return 1
    print(f"OK: {len(cases)} casos em {len({c['episode_id'] for c in cases})} episódios")
    print(f"SHA256: {hashlib.sha256(args.dataset.read_bytes()).hexdigest()}")
    print(
        "Classes: "
        + json.dumps(
            Counter(
                case.get("expected_classification") or "SEM_CLASSIFICACAO"
                for case in cases
            ),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if not args.distribuicao_alvo:
        print(
            "AVISO: distribuição sintética não deve ser descrita como representativa; "
            "use --distribuicao-alvo apenas após estimá-la em chamados reais anonimizados."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
