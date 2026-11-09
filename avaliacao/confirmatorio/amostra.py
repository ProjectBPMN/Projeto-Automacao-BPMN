from __future__ import annotations

import math
from typing import Any

from .util import require_probability


def clopper_pearson_upper_unilateral(
    events: int,
    exposures: int,
    confidence: float = 0.95,
) -> float:
    """Limite superior exato unilateral para uma proporção binomial.

    Para zero eventos usa a solução fechada ``1 - alpha**(1/n)``. Para os
    demais casos usa o quantil beta do intervalo de Clopper--Pearson.
    """

    if isinstance(events, bool) or isinstance(exposures, bool):
        raise ValueError("events/exposures devem ser inteiros")
    if not isinstance(events, int) or not isinstance(exposures, int):
        raise ValueError("events/exposures devem ser inteiros")
    if exposures <= 0 or not 0 <= events <= exposures:
        raise ValueError("contagem binomial inválida")
    confidence = require_probability(confidence, "confidence", inclusive=False)
    alpha = 1.0 - confidence
    if events == 0:
        return 1.0 - alpha ** (1.0 / exposures)
    if events == exposures:
        return 1.0
    try:
        from scipy.stats import beta
    except ImportError as exc:  # pragma: no cover - dependência fixada no projeto
        raise RuntimeError("scipy é necessário para Clopper-Pearson com eventos > 0") from exc
    return float(beta.ppf(confidence, events + 1, exposures - events))


def tamanho_minimo_zero_eventos(
    maximum_upper: float = 0.02,
    confidence: float = 0.95,
) -> int:
    """Menor n cujo limite exato unilateral é *estritamente* menor que o gate."""

    maximum_upper = require_probability(
        maximum_upper, "maximum_upper", inclusive=False
    )
    confidence = require_probability(confidence, "confidence", inclusive=False)
    alpha = 1.0 - confidence
    ratio = math.log(alpha) / math.log(1.0 - maximum_upper)
    candidate = max(1, math.floor(ratio) + 1)
    while clopper_pearson_upper_unilateral(0, candidate, confidence) >= maximum_upper:
        candidate += 1
    while candidate > 1 and clopper_pearson_upper_unilateral(
        0, candidate - 1, confidence
    ) < maximum_upper:
        candidate -= 1
    return candidate


def planejar_zero_eventos(
    *,
    maximum_upper: float = 0.02,
    confidence: float = 0.95,
    expected_exposure_fraction: float,
    attrition_fraction: float = 0.0,
    design_effect: float = 1.0,
) -> dict[str, Any]:
    """Planeja famílias a recrutar sem confundir famílias com exposições.

    ``expected_exposure_fraction`` é a fração pré-especificada de famílias que
    pertence ao denominador do erro crítico (por exemplo, negativos reais para
    falso positivo). ``design_effect`` deve ser informado se ainda houver
    correlação residual; não é estimado do holdout.
    """

    expected_exposure_fraction = require_probability(
        expected_exposure_fraction,
        "expected_exposure_fraction",
        inclusive=True,
    )
    if expected_exposure_fraction == 0:
        raise ValueError("expected_exposure_fraction deve ser maior que 0")
    attrition_fraction = require_probability(
        attrition_fraction, "attrition_fraction", inclusive=True
    )
    if attrition_fraction >= 1:
        raise ValueError("attrition_fraction deve ser menor que 1")
    if isinstance(design_effect, bool) or not isinstance(design_effect, (int, float)):
        raise ValueError("design_effect deve ser numérico")
    design_effect = float(design_effect)
    if not math.isfinite(design_effect) or design_effect < 1:
        raise ValueError("design_effect deve ser finito e >= 1")

    effective_exposures = tamanho_minimo_zero_eventos(maximum_upper, confidence)
    raw_without_attrition = math.ceil(
        effective_exposures * design_effect / expected_exposure_fraction
    )
    recruitment_target = math.ceil(raw_without_attrition / (1.0 - attrition_fraction))
    return {
        "method": "Clopper-Pearson exato unilateral, zero eventos",
        "strict_gate": True,
        "confidence": confidence,
        "maximum_upper": maximum_upper,
        "minimum_effective_independent_exposures": effective_exposures,
        "expected_exposure_fraction": expected_exposure_fraction,
        "design_effect": design_effect,
        "attrition_fraction": attrition_fraction,
        "minimum_recruited_independent_families": recruitment_target,
        "interpretation": (
            "O n=149 vale para exposições efetivamente independentes quando o gate é "
            "limite unilateral exato de 95% <2%; prevalência do denominador, perdas e "
            "correlação residual podem elevar o total de famílias recrutadas."
        ),
    }
