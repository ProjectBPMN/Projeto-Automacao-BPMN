from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from statistics import NormalDist


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def proportion_sample_size(
    margin: float, confidence: float, expected: float = 0.5
) -> int:
    alpha = 1 - confidence
    z = NormalDist().inv_cdf(1 - alpha / 2)
    return math.ceil(z * z * expected * (1 - expected) / (margin * margin))


def mcnemar_sample_size(
    discordant_rate: float,
    discordant_difference: float,
    alpha: float,
    power: float,
) -> int:
    if not 0 < discordant_difference < discordant_rate < 1:
        raise ValueError(
            "Use 0 < diferença discordante < taxa discordante < 1."
        )
    z_alpha = NormalDist().inv_cdf(1 - alpha / 2)
    z_power = NormalDist().inv_cdf(power)
    numerator = (
        z_alpha * math.sqrt(discordant_rate)
        + z_power
        * math.sqrt(
            discordant_rate - discordant_difference**2
        )
    ) ** 2
    return math.ceil(numerator / (discordant_difference**2))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Planeja suporte por classe e pares para o benchmark."
    )
    parser.add_argument("piloto", type=Path)
    parser.add_argument("--margem", type=float, default=0.10)
    parser.add_argument("--confianca", type=float, default=0.95)
    parser.add_argument("--poder", type=float, default=0.80)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--taxa-discordante", type=float, default=0.20)
    parser.add_argument("--diferenca-discordante", type=float, default=0.10)
    parser.add_argument("--saida", type=Path)
    args = parser.parse_args()

    cases = load_jsonl(args.piloto)
    class_counts = Counter(
        case["expected_classification"]
        for case in cases
        if case.get("expected_classification")
    )
    per_class_target = proportion_sample_size(
        args.margem, args.confianca
    )
    variations_by_class = {
        label: math.ceil(per_class_target / count)
        for label, count in class_counts.items()
        if count
    }
    mcnemar_target = mcnemar_sample_size(
        args.taxa_discordante,
        args.diferenca_discordante,
        args.alpha,
        args.poder,
    )
    payload = {
        "method": {
            "support_per_class": (
                "aproximação conservadora binomial de pior caso p=0.5; "
                "a precisão final deve ser verificada por bootstrap episódico"
            ),
            "paired_comparison": "aproximação normal para McNemar pareado",
        },
        "parameters": {
            "margin": args.margem,
            "confidence": args.confianca,
            "power": args.poder,
            "alpha": args.alpha,
            "discordant_rate": args.taxa_discordante,
            "discordant_difference": args.diferenca_discordante,
        },
        "pilot_support_per_variation": dict(sorted(class_counts.items())),
        "minimum_support_per_class": per_class_target,
        "variations_required_by_class": variations_by_class,
        "recommended_variations": max(variations_by_class.values()),
        "minimum_paired_cases_mcnemar": mcnemar_target,
        "decision_rule": (
            "usar o maior requisito entre suporte por classe e pares; "
            "não concluir equivalência quando o IC permanecer amplo"
        ),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.saida:
        args.saida.parent.mkdir(parents=True, exist_ok=True)
        args.saida.write_text(text, encoding="utf-8")
        print(f"[OK] Planejamento: {args.saida}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
