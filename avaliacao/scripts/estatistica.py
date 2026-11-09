from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Callable, Sequence

# Os limiares são calibrados no piloto/validação e congelados antes do teste.


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _interval(values: list[float], point: float | None) -> dict:
    return {
        "estimate": point,
        "lower": _percentile(values, 0.025),
        "upper": _percentile(values, 0.975),
        "method": "bootstrap_percentil_episodico_95",
        "replicacoes_validas": len(values),
    }


def _class_metrics(
    gold: Sequence[str], predicted: Sequence[str], label: str
) -> tuple[float | None, float | None, float | None]:
    tp = sum(g == label and p == label for g, p in zip(gold, predicted))
    fp = sum(g != label and p == label for g, p in zip(gold, predicted))
    fn = sum(g == label and p != label for g, p in zip(gold, predicted))
    support = tp + fn
    if support == 0:
        return None, None, None
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / support
    f1 = 2 * tp / ((2 * tp) + fp + fn)
    return precision, recall, f1


def _macro_f1(
    gold: Sequence[str], predicted: Sequence[str], labels: Sequence[str]
) -> float | None:
    values = [
        metrics[2]
        for label in labels
        if (metrics := _class_metrics(gold, predicted, label))[2] is not None
    ]
    return sum(values) / len(values) if values else None


def _accuracy(gold: Sequence[str], predicted: Sequence[str]) -> float | None:
    return (
        sum(g == p for g, p in zip(gold, predicted)) / len(gold)
        if gold
        else None
    )


def _false_positive_rate(
    gold: Sequence[str], predicted: Sequence[str], positive: str
) -> float | None:
    fp = sum(g != positive and p == positive for g, p in zip(gold, predicted))
    tn = sum(g != positive and p != positive for g, p in zip(gold, predicted))
    return fp / (fp + tn) if fp + tn else None


def bootstrap_multiclass(
    gold: Sequence[str],
    predicted: Sequence[str],
    groups: Sequence[str],
    labels: Sequence[str],
    *,
    replications: int = 2000,
    seed: int = 20260702,
) -> dict:
    if not (len(gold) == len(predicted) == len(groups)):
        raise ValueError("gold, predicted e groups devem ter o mesmo tamanho")
    if not gold:
        return {}
    indices_by_group: dict[str, list[int]] = defaultdict(list)
    for index, group in enumerate(groups):
        indices_by_group[str(group)].append(index)
    unique_groups = sorted(indices_by_group)
    rng = random.Random(seed)
    samples: dict[str, dict[str, list[float]]] = {
        label: {"precision": [], "recall": [], "f1": []} for label in labels
    }
    samples["__macro__"] = {"f1": []}
    for _ in range(replications):
        selected_groups = [
            rng.choice(unique_groups) for _ in range(len(unique_groups))
        ]
        indices = [
            index
            for group in selected_groups
            for index in indices_by_group[group]
        ]
        sampled_gold = [gold[index] for index in indices]
        sampled_predicted = [predicted[index] for index in indices]
        for label in labels:
            precision, recall, f1 = _class_metrics(
                sampled_gold, sampled_predicted, label
            )
            for name, value in (
                ("precision", precision),
                ("recall", recall),
                ("f1", f1),
            ):
                if value is not None:
                    samples[label][name].append(value)
        macro_f1 = _macro_f1(sampled_gold, sampled_predicted, labels)
        if macro_f1 is not None:
            samples["__macro__"]["f1"].append(macro_f1)
    output: dict[str, dict] = {"per_class": {}}
    for label in labels:
        precision, recall, f1 = _class_metrics(gold, predicted, label)
        output["per_class"][label] = {
            "precision": _interval(samples[label]["precision"], precision),
            "recall": _interval(samples[label]["recall"], recall),
            "f1": _interval(samples[label]["f1"], f1),
        }
    point_macro = _macro_f1(gold, predicted, labels)
    output["macro_f1"] = _interval(samples["__macro__"]["f1"], point_macro)
    output["seed"] = seed
    output["replicacoes_solicitadas"] = replications
    output["unidade_reamostragem"] = "episode_id"
    return output


def bootstrap_binary(
    gold: Sequence[str],
    predicted: Sequence[str],
    groups: Sequence[str],
    *,
    positive: str = "DUPLICADO",
    replications: int = 2000,
    seed: int = 20260702,
) -> dict:
    base = bootstrap_multiclass(
        gold,
        predicted,
        groups,
        [positive],
        replications=replications,
        seed=seed,
    )
    return {
        **base["per_class"].get(positive, {}),
        "seed": seed,
        "replicacoes_solicitadas": replications,
        "unidade_reamostragem": "episode_id",
    }


def bootstrap_paired_difference(
    gold: Sequence[str],
    predicted_a: Sequence[str],
    predicted_b: Sequence[str],
    groups: Sequence[str],
    *,
    labels: Sequence[str],
    task: str,
    replications: int = 2000,
    seed: int = 20260702,
) -> dict:
    """Intervalos pareados por episódio; diferenças positivas favorecem A."""
    if not (
        len(gold) == len(predicted_a) == len(predicted_b) == len(groups)
    ):
        raise ValueError("As listas pareadas devem ter o mesmo tamanho")
    if not gold:
        return {}

    indices_by_group: dict[str, list[int]] = defaultdict(list)
    for index, group in enumerate(groups):
        indices_by_group[str(group)].append(index)
    unique_groups = sorted(indices_by_group)
    rng = random.Random(seed)

    if task == "CLASSIFICACAO":
        metrics: dict[str, Callable[[Sequence[str], Sequence[str]], float | None]] = {
            "accuracy": _accuracy,
            "macro_f1": lambda g, p: _macro_f1(g, p, labels),
        }
    elif task == "DEDUPLICACAO":
        positive = labels[0]
        metrics = {
            "accuracy": _accuracy,
            "f1_positivo": lambda g, p: _class_metrics(g, p, positive)[2],
            "recall_positivo": lambda g, p: _class_metrics(g, p, positive)[1],
            "taxa_falso_positivo": lambda g, p: _false_positive_rate(
                g, p, positive
            ),
        }
    else:
        raise ValueError("task deve ser CLASSIFICACAO ou DEDUPLICACAO")

    samples: dict[str, list[float]] = {name: [] for name in metrics}
    for _ in range(replications):
        selected_groups = [
            rng.choice(unique_groups) for _ in range(len(unique_groups))
        ]
        indices = [
            index
            for group in selected_groups
            for index in indices_by_group[group]
        ]
        sampled_gold = [gold[index] for index in indices]
        sampled_a = [predicted_a[index] for index in indices]
        sampled_b = [predicted_b[index] for index in indices]
        for name, metric in metrics.items():
            value_a = metric(sampled_gold, sampled_a)
            value_b = metric(sampled_gold, sampled_b)
            if value_a is not None and value_b is not None:
                samples[name].append(value_a - value_b)

    output: dict[str, dict] = {}
    for name, metric in metrics.items():
        value_a = metric(gold, predicted_a)
        value_b = metric(gold, predicted_b)
        difference = (
            value_a - value_b
            if value_a is not None and value_b is not None
            else None
        )
        output[name] = {
            **_interval(samples[name], difference),
            "modelo_a": value_a,
            "modelo_b": value_b,
        }
    return {
        "diferenca_a_menos_b": output,
        "interpretacao": "intervalo acima de zero favorece A; abaixo de zero favorece B",
        "unidade_reamostragem": "episode_id",
        "replicacoes_solicitadas": replications,
        "seed": seed,
    }


def mcnemar_exact(
    gold: Sequence[str],
    predicted_a: Sequence[str],
    predicted_b: Sequence[str],
) -> dict:
    if not (len(gold) == len(predicted_a) == len(predicted_b)):
        raise ValueError("As listas pareadas devem ter o mesmo tamanho")
    a_certo_b_errado = sum(
        a == g and b != g for g, a, b in zip(gold, predicted_a, predicted_b)
    )
    a_errado_b_certo = sum(
        a != g and b == g for g, a, b in zip(gold, predicted_a, predicted_b)
    )
    discordantes = a_certo_b_errado + a_errado_b_certo
    if discordantes == 0:
        p_value = 1.0
    else:
        extremo = min(a_certo_b_errado, a_errado_b_certo)
        tail = sum(
            math.comb(discordantes, k)
            for k in range(extremo + 1)
        ) / (2 ** discordantes)
        p_value = min(1.0, 2 * tail)
    return {
        "a_certo_b_errado": a_certo_b_errado,
        "a_errado_b_certo": a_errado_b_certo,
        "discordantes": discordantes,
        "p_value": p_value,
        "alpha": 0.05,
        "significativo": p_value < 0.05,
        "method": "McNemar exato bicaudal",
        "uso_recomendado": "análise secundária de acurácia por decisão",
    }
