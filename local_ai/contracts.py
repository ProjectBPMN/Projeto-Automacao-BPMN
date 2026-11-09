from __future__ import annotations

import math
from typing import Any


DEDUP_KEYS = {
    "eh_duplicado",
    "chamado_referencia_id",
    "justificativa",
    "caracteristicas_match",
    "confianca",
    "probabilidades",
}
CLASSIFICATION_KEYS = {
    "tipo",
    "executor",
    "categoria",
    "justificativa",
    "mensagem_solicitante",
    "confianca",
    "probabilidades",
}
CLASS_LABELS = ("OBRA", "DEMO", "SOB_DEMANDA", "TRIAGEM_MANUAL")


def clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def rounded_probabilities(values: dict[str, float], labels: tuple[str, ...], digits: int = 6) -> dict[str, float]:
    safe = {label: max(0.0, float(values.get(label, 0.0))) for label in labels}
    total = sum(safe.values())
    if total <= 0:
        safe = {label: 1.0 / len(labels) for label in labels}
    else:
        safe = {label: value / total for label, value in safe.items()}
    result = {label: round(safe[label], digits) for label in labels}
    correction = round(1.0 - sum(result.values()), digits)
    winner = max(labels, key=lambda label: result[label])
    result[winner] = round(result[winner] + correction, digits)
    return result


def validate_dedup_v9(value: dict[str, Any]) -> None:
    if set(value) != DEDUP_KEYS:
        raise ValueError("Saída de deduplicação não corresponde ao contrato V9")
    if not isinstance(value["eh_duplicado"], bool):
        raise ValueError("eh_duplicado deve ser booleano")
    reference = value["chamado_referencia_id"]
    if reference is not None and (not isinstance(reference, int) or isinstance(reference, bool)):
        raise ValueError("chamado_referencia_id deve ser inteiro ou null")
    if value["eh_duplicado"] and reference is None:
        raise ValueError("Duplicidade exige chamado_referencia_id")
    if not isinstance(value["justificativa"], str):
        raise ValueError("justificativa deve ser texto")
    matches = value["caracteristicas_match"]
    if not isinstance(matches, list) or len(matches) > 10 or not all(isinstance(x, str) for x in matches):
        raise ValueError("caracteristicas_match inválido")
    confidence = value["confianca"]
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise ValueError("confianca inválida")
    probabilities = value["probabilidades"]
    if set(probabilities) != {"duplicado", "nao_duplicado"}:
        raise ValueError("probabilidades de deduplicação inválidas")
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v <= 1 for v in probabilities.values()):
        raise ValueError("probabilidade fora do intervalo")
    if not math.isclose(sum(probabilities.values()), 1.0, abs_tol=0.001):
        raise ValueError("probabilidades não somam 1")
    declared = probabilities["duplicado"] > probabilities["nao_duplicado"]
    if probabilities["duplicado"] != probabilities["nao_duplicado"] and declared != value["eh_duplicado"]:
        raise ValueError("decisão diverge da maior probabilidade")


def validate_classification_v9(value: dict[str, Any]) -> None:
    if set(value) != CLASSIFICATION_KEYS:
        raise ValueError("Saída de classificação não corresponde ao contrato V9")
    pair = (value["tipo"], value["executor"])
    if pair not in {
        ("OBRA", "DDI_DG"),
        ("MANUTENCAO", "DEMO"),
        ("MANUTENCAO", "SOB_DEMANDA"),
        ("TRIAGEM_MANUAL", "FISCAL"),
    }:
        raise ValueError("Par tipo/executor inválido")
    for field in ("categoria", "justificativa", "mensagem_solicitante"):
        if not isinstance(value[field], str):
            raise ValueError(f"{field} deve ser texto")
    confidence = value["confianca"]
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise ValueError("confianca inválida")
    probabilities = value["probabilidades"]
    if set(probabilities) != set(CLASS_LABELS):
        raise ValueError("Vetor de probabilidades inválido")
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v <= 1 for v in probabilities.values()):
        raise ValueError("probabilidade fora do intervalo")
    if not math.isclose(sum(probabilities.values()), 1.0, abs_tol=0.001):
        raise ValueError("probabilidades não somam 1")
    declared = (
        "OBRA"
        if pair == ("OBRA", "DDI_DG")
        else "DEMO"
        if pair == ("MANUTENCAO", "DEMO")
        else "SOB_DEMANDA"
        if pair == ("MANUTENCAO", "SOB_DEMANDA")
        else "TRIAGEM_MANUAL"
    )
    if declared != max(CLASS_LABELS, key=lambda label: probabilities[label]):
        raise ValueError("Classe declarada diverge da maior probabilidade")

