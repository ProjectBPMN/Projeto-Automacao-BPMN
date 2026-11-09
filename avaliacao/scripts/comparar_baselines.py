from __future__ import annotations

import argparse
import csv
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

from estatistica import (
    bootstrap_binary,
    bootstrap_multiclass,
    bootstrap_paired_difference,
    mcnemar_exact,
)

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.pipeline import FeatureUnion
    from sklearn.linear_model import LogisticRegression
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Instale as dependências fixadas em requirements.txt para os baselines TF-IDF."
    ) from exc


CLASS_LABELS = [
    "OBRA",
    "DEMO",
    "SOB_DEMANDA",
    "TRIAGEM_MANUAL",
]
DEDUP_LABELS = ["DUPLICADO", "NAO_DUPLICADO"]
DEDUP_CANDIDATE_LIMIT = 20


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def normalize(value: str) -> str:
    text = "".join(
        char
        for char in unicodedata.normalize("NFD", str(value or "").lower())
        if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def tokens(value: str) -> set[str]:
    return {token for token in normalize(value).split() if len(token) >= 4}


def rule_classification(case: dict) -> str:
    text = normalize(f"{case.get('title','')} {case.get('content','')}")
    if any(word in text for word in (
        "nao sei", "sem informar", "onde exatamente", "sistema academico",
        "senha", "problemas", "construir ou consertar",
    )):
        return "TRIAGEM_MANUAL"
    if any(word in text for word in (
        "ar condicionado", "elevador", "portao eletronico", "autoclave",
        "cftv", "camera", "caldeira", "exaustor industrial",
    )):
        return "SOB_DEMANDA"
    if any(word in text for word in (
        "fundacao", "estrutural", "ampliar", "construcao do zero",
        "troca completa", "telhado do predio central",
    )):
        return "OBRA"
    return "DEMO"


def jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def rule_dedup_predictions(cases: list[dict]) -> dict[str, str]:
    predictions: dict[str, str] = {}
    history: list[dict] = []
    for case in cases:
        current_tokens = tokens(f"{case['title']} {case['content']}")
        current_location = normalize(case.get("location", ""))
        candidates = history[-DEDUP_CANDIDATE_LIMIT:]
        duplicate = any(
            current_location
            and current_location == normalize(previous.get("location", ""))
            and jaccard(
                current_tokens,
                tokens(f"{previous['title']} {previous['content']}"),
            ) >= 0.48
            for previous in candidates
        )
        predictions[case["case_id"]] = (
            "DUPLICADO" if duplicate else "NAO_DUPLICADO"
        )
        history.append(case)
    return predictions


def case_text(case: dict) -> str:
    return " ".join(
        str(case.get(field, "") or "")
        for field in ("title", "content", "location", "service_type")
    )


def tfidf_logreg_predictions(
    pilot: list[dict], test: list[dict], seed: int
) -> dict[tuple[str, str], str]:
    train = [case for case in pilot if case.get("expected_classification")]
    target = [case for case in test if case.get("expected_classification")]
    if len({case["expected_classification"] for case in train}) < 2:
        raise ValueError("TF-IDF + LogReg requer ao menos duas classes no piloto.")
    features = FeatureUnion(
        [
            (
                "word",
                TfidfVectorizer(
                    ngram_range=(1, 2),
                    min_df=1,
                    sublinear_tf=True,
                    strip_accents="unicode",
                ),
            ),
            (
                "char",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(3, 5),
                    min_df=1,
                    sublinear_tf=True,
                ),
            ),
        ]
    )
    train_matrix = features.fit_transform([case_text(case) for case in train])
    model = LogisticRegression(
        class_weight="balanced",
        max_iter=3000,
        random_state=seed,
        solver="lbfgs",
    )
    model.fit(
        train_matrix,
        [case["expected_classification"] for case in train],
    )
    predicted = model.predict(
        features.transform([case_text(case) for case in target])
    )
    return {
        (case["case_id"], "CLASSIFICACAO"): str(label)
        for case, label in zip(target, predicted)
    }


def tfidf_similarity_scores(
    train: list[dict], cases: list[dict]
) -> dict[str, float]:
    vectorizer = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(3, 5),
        min_df=1,
        sublinear_tf=True,
    )
    vectorizer.fit([case_text(case) for case in train])
    matrix = vectorizer.transform([case_text(case) for case in cases])
    scores: dict[str, float] = {}
    previous: list[int] = []
    for index, case in enumerate(cases):
        best = 0.0
        for candidate in previous[-DEDUP_CANDIDATE_LIMIT:]:
            similarity = float(matrix[index].multiply(matrix[candidate]).sum())
            location_a = normalize(case.get("location", ""))
            location_b = normalize(cases[candidate].get("location", ""))
            if not location_a or location_a != location_b:
                similarity *= 0.35
            best = max(best, similarity)
        scores[case["case_id"]] = best
        previous.append(index)
    return scores


def is_dedup_challenge(case: dict) -> bool:
    order = case.get("order_in_episode", case.get("order_in_group", 0))
    return (
        str(case.get("dimension", "")).upper() == "DEDUPLICACAO"
        and int(order or 0) > 1
        and case.get("expected_dedup") is not None
    )


def tfidf_dedup_predictions(
    pilot: list[dict], test: list[dict]
) -> tuple[dict[tuple[str, str], str], float]:
    pilot_scores = tfidf_similarity_scores(pilot, pilot)
    best_threshold = 0.5
    best_f1 = -1.0
    for threshold_int in range(10, 91, 2):
        threshold = threshold_int / 100
        pilot_challenge = [case for case in pilot if is_dedup_challenge(case)]
        gold = [
            "DUPLICADO" if case["expected_dedup"] else "NAO_DUPLICADO"
            for case in pilot_challenge
        ]
        predicted = [
            "DUPLICADO"
            if pilot_scores[case["case_id"]] >= threshold
            else "NAO_DUPLICADO"
            for case in pilot_challenge
        ]
        f1 = binary_metrics(gold, predicted)["f1"] or 0.0
        if f1 > best_f1:
            best_f1 = f1
            best_threshold = threshold
    test_scores = tfidf_similarity_scores(pilot, test)
    predictions = {
        (case["case_id"], "DEDUPLICACAO"): (
            "DUPLICADO"
            if test_scores[case["case_id"]] >= best_threshold
            else "NAO_DUPLICADO"
        )
        for case in test
        if case.get("expected_dedup") is not None
    }
    return predictions, best_threshold


def classification_metrics(gold: list[str], predicted: list[str]) -> dict:
    total = len(gold)
    per_class: dict[str, dict] = {}
    f1_values: list[float] = []
    for label in CLASS_LABELS:
        tp = sum(g == label and p == label for g, p in zip(gold, predicted))
        fp = sum(g != label and p == label for g, p in zip(gold, predicted))
        fn = sum(g == label and p != label for g, p in zip(gold, predicted))
        support = tp + fn
        precision = tp / (tp + fp) if tp + fp else (0.0 if support else None)
        recall = tp / support if support else None
        f1 = 2 * tp / ((2 * tp) + fp + fn) if support else None
        if f1 is not None:
            f1_values.append(f1)
        per_class[label] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    return {
        "total": total,
        "accuracy": sum(g == p for g, p in zip(gold, predicted)) / total if total else None,
        "macro_f1": sum(f1_values) / len(f1_values) if f1_values else None,
        "per_class": per_class,
    }


def binary_metrics(gold: list[str], predicted: list[str]) -> dict:
    tp = sum(g == "DUPLICADO" and p == "DUPLICADO" for g, p in zip(gold, predicted))
    fp = sum(g != "DUPLICADO" and p == "DUPLICADO" for g, p in zip(gold, predicted))
    fn = sum(g == "DUPLICADO" and p != "DUPLICADO" for g, p in zip(gold, predicted))
    tn = sum(g != "DUPLICADO" and p != "DUPLICADO" for g, p in zip(gold, predicted))
    positive_support = tp + fn
    precision = tp / (tp + fp) if tp + fp else (0.0 if positive_support else None)
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / ((2 * tp) + fp + fn) if positive_support else None
    return {
        "total": len(gold),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "accuracy": (tp + tn) / len(gold) if gold else None,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def paired_vectors(
    cases: list[dict],
    predictions: dict[tuple[str, str], str],
    stage: str,
    *,
    challenge_only: bool = False,
) -> tuple[list[str], list[str], list[str]]:
    if stage == "CLASSIFICACAO":
        selected = [
            case for case in cases if case.get("expected_classification")
        ]
        gold = [case["expected_classification"] for case in selected]
    else:
        selected = [
            case
            for case in cases
            if case.get("expected_dedup") is not None
            and (not challenge_only or is_dedup_challenge(case))
        ]
        gold = [
            "DUPLICADO" if case["expected_dedup"] else "NAO_DUPLICADO"
            for case in selected
        ]
    predicted = [
        predictions.get((case["case_id"], stage), "SEM_DECISAO")
        for case in selected
    ]
    groups = [case["episode_id"] for case in selected]
    return gold, predicted, groups


def evaluate_predictions(
    cases: list[dict],
    predictions: dict[tuple[str, str], str],
    bootstrap_replications: int,
    seed: int,
) -> dict:
    class_cases = [case for case in cases if case.get("expected_classification")]
    class_gold = [case["expected_classification"] for case in class_cases]
    class_pred = [
        predictions.get((case["case_id"], "CLASSIFICACAO"), "SEM_DECISAO")
        for case in class_cases
    ]
    dedup_cases = [
        case for case in cases if case.get("expected_dedup") is not None
    ]
    challenge_cases = [case for case in dedup_cases if is_dedup_challenge(case)]
    dedup_gold = [
        "DUPLICADO" if case["expected_dedup"] else "NAO_DUPLICADO"
        for case in dedup_cases
    ]
    dedup_pred = [
        predictions.get((case["case_id"], "DEDUPLICACAO"), "SEM_DECISAO")
        for case in dedup_cases
    ]
    challenge_gold = [
        "DUPLICADO" if case["expected_dedup"] else "NAO_DUPLICADO"
        for case in challenge_cases
    ]
    challenge_pred = [
        predictions.get((case["case_id"], "DEDUPLICACAO"), "SEM_DECISAO")
        for case in challenge_cases
    ]
    class_groups = [
        case["episode_id"]
        for case in class_cases
    ]
    dedup_groups = [case["episode_id"] for case in dedup_cases]
    challenge_groups = [case["episode_id"] for case in challenge_cases]
    return {
        "classification": {
            **classification_metrics(class_gold, class_pred),
            "bootstrap_95": bootstrap_multiclass(
                class_gold,
                class_pred,
                class_groups,
                CLASS_LABELS,
                replications=bootstrap_replications,
                seed=seed,
            ),
        },
        "deduplication_challenge_primary": {
            **binary_metrics(challenge_gold, challenge_pred),
            "bootstrap_95": bootstrap_binary(
                challenge_gold,
                challenge_pred,
                challenge_groups,
                replications=bootstrap_replications,
                seed=seed + 1,
            ),
            "selection": "dimension=DEDUPLICACAO and order_in_episode>1",
        },
        "deduplication_global_secondary": {
            **binary_metrics(dedup_gold, dedup_pred),
            "bootstrap_95": bootstrap_binary(
                dedup_gold,
                dedup_pred,
                dedup_groups,
                replications=bootstrap_replications,
                seed=seed + 2,
            ),
        },
    }


def imported_predictions(path: Path) -> dict[tuple[str, str], str]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        return {
            (row["case_id"], row["etapa"].upper()): row["predicao"].upper()
            for row in rows
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compara regras, maioria e modelos alternativos no mesmo teste congelado."
    )
    parser.add_argument("--piloto", type=Path, required=True)
    parser.add_argument("--teste", type=Path, required=True)
    parser.add_argument(
        "--predicoes",
        action="append",
        default=[],
        help="NOME=arquivo.csv com case_id,etapa,predicao.",
    )
    parser.add_argument("--saida", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260702)
    parser.add_argument("--bootstrap", type=int, default=2000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.piloto.read_bytes() == args.teste.read_bytes():
        raise SystemExit("Piloto e teste devem ser arquivos distintos.")
    pilot = load_jsonl(args.piloto)
    test = load_jsonl(args.teste)
    majority_class = Counter(
        case["expected_classification"]
        for case in pilot
        if case.get("expected_classification")
    ).most_common(1)[0][0]
    rule_dedup = rule_dedup_predictions(test)
    rule_predictions = {
        (case["case_id"], "CLASSIFICACAO"): rule_classification(case)
        for case in test
        if case.get("expected_classification")
    }
    rule_predictions.update(
        {
            (case_id, "DEDUPLICACAO"): prediction
            for case_id, prediction in rule_dedup.items()
        }
    )
    majority_predictions = {
        (case["case_id"], "CLASSIFICACAO"): majority_class
        for case in test
        if case.get("expected_classification")
    }
    majority_predictions.update(
        {
            (case["case_id"], "DEDUPLICACAO"): "NAO_DUPLICADO"
            for case in test
            if case.get("expected_dedup") is not None
        }
    )
    tfidf_predictions = tfidf_logreg_predictions(pilot, test, args.seed)
    tfidf_dedup, dedup_threshold = tfidf_dedup_predictions(pilot, test)
    tfidf_predictions.update(tfidf_dedup)
    all_predictions = {
        "regra_deterministica": rule_predictions,
        "maioria_do_piloto": majority_predictions,
        "tfidf_logreg_cosine": tfidf_predictions,
    }
    for spec in args.predicoes:
        if "=" not in spec:
            raise SystemExit("--predicoes deve usar NOME=arquivo.csv")
        name, path = spec.split("=", 1)
        all_predictions[name] = imported_predictions(Path(path))
    results = {
        name: evaluate_predictions(
            test,
            predictions,
            args.bootstrap,
            args.seed + index * 10,
        )
        for index, (name, predictions) in enumerate(all_predictions.items())
    }
    results["tfidf_logreg_cosine"]["configuracao"] = {
        "classificacao": "TF-IDF palavras+caracteres e LogisticRegression balanceada",
        "deduplicacao": "TF-IDF char cosine; limiar calibrado somente no piloto",
        "limiar_deduplicacao": dedup_threshold,
        "seed": args.seed,
    }
    comparisons: dict[str, dict] = {}
    reference_name = (
        next(
            (
                name
                for name in all_predictions
                if name.lower() in {"gemini", "gemini_3_5_flash"}
            ),
            "tfidf_logreg_cosine",
        )
    )
    for name, predictions in all_predictions.items():
        if name == reference_name:
            continue
        comparisons[name] = {}
        comparison_specs = [
            ("CLASSIFICACAO", False, "classificacao"),
            ("DEDUPLICACAO", True, "deduplicacao_desafio_primaria"),
            ("DEDUPLICACAO", False, "deduplicacao_global_secundaria"),
        ]
        for stage, challenge_only, output_key in comparison_specs:
            gold, reference_predicted, groups = paired_vectors(
                test,
                all_predictions[reference_name],
                stage,
                challenge_only=challenge_only,
            )
            _, compared_predicted, _ = paired_vectors(
                test,
                predictions,
                stage,
                challenge_only=challenge_only,
            )
            comparisons[name][output_key] = {
                "bootstrap_pareado_episodico": bootstrap_paired_difference(
                    gold,
                    reference_predicted,
                    compared_predicted,
                    groups,
                    labels=CLASS_LABELS if stage == "CLASSIFICACAO" else DEDUP_LABELS,
                    task=stage,
                    replications=args.bootstrap,
                    seed=(
                        args.seed
                        + len(comparisons) * 100
                        + (0 if stage == "CLASSIFICACAO" else (1 if challenge_only else 2))
                    ),
                ),
                "mcnemar_secundario": mcnemar_exact(
                    gold, reference_predicted, compared_predicted
                ),
            }
    payload = {
        "status_evidencia": "PRELIMINAR_SINTETICO_NAO_CONFIRMATORIO",
        "alerta_validade": (
            "Os splits V2 reutilizam famílias narrativas e não substituem o benchmark V3 "
            "congelado; não usar estes números como resultado final do artigo."
        ),
        "referencia_comparacoes": reference_name,
        "resultados": results,
        "comparacoes_pareadas": comparisons,
        "criterio_significancia": "p < 0.05",
    }
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] Comparação: {args.saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
