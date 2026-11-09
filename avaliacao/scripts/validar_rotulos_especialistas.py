from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


CLASS_LABELS = {
    "OBRA",
    "DEMO",
    "SOB_DEMANDA",
    "TRIAGEM_MANUAL",
}
DEDUP_LABELS = {"DUPLICADO", "NAO_DUPLICADO"}
REVIEW_FIELDS = [
    "review_id",
    "etapa",
    "titulo",
    "descricao",
    "localizacao",
    "contexto_anterior_episodio",
    "revisor_1",
    "rotulo_revisor_1",
    "revisor_2",
    "rotulo_revisor_2",
    "adjudicador",
    "rotulo_adjudicado",
    "observacao",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_label(value: str) -> str:
    return value.strip().upper().replace(" ", "_").replace("-", "_")


def load_dataset(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        cases = [json.loads(line) for line in handle if line.strip()]
    if not cases:
        raise ValueError("O dataset está vazio.")
    required = {
        "case_id",
        "episode_id",
        "scenario_id",
        "order_in_group",
        "title",
        "content",
        "location",
        "expected_dedup",
    }
    for index, case in enumerate(cases, start=1):
        missing = required - set(case)
        if missing:
            raise ValueError(f"Caso {index}: campos ausentes: {sorted(missing)}")
    return cases


def rows_for_review(cases: list[dict]) -> tuple[list[dict], list[dict]]:
    episodes: dict[str, list[dict]] = defaultdict(list)
    for case in cases:
        episodes[str(case["episode_id"])].append(case)

    blind: list[dict] = []
    manifest: list[dict] = []
    index = 0
    for case in cases:
        stages = [
            (
                "DEDUPLICACAO",
                "DUPLICADO" if bool(case["expected_dedup"]) else "NAO_DUPLICADO",
            )
        ]
        if str(case.get("expected_classification") or "").strip():
            stages.append(("CLASSIFICACAO", str(case["expected_classification"])))

        current_order = int(case["order_in_group"])
        prior_context = sorted(
            (
                item
                for item in episodes[str(case["episode_id"])]
                if int(item["order_in_group"]) < current_order
            ),
            key=lambda item: (int(item["order_in_group"]), str(item["case_id"])),
        )
        context_json = json.dumps(
            [
                {
                    "ordem": item["order_in_group"],
                    "titulo": item["title"],
                    "descricao": item["content"],
                    "localizacao": item["location"],
                }
                for item in prior_context
            ],
            ensure_ascii=False,
        )

        for stage, gold in stages:
            index += 1
            review_id = f"ROTULO-{index:04d}"
            blind.append(
                {
                    "review_id": review_id,
                    "etapa": stage,
                    "titulo": case["title"],
                    "descricao": case["content"],
                    "localizacao": case["location"],
                    "contexto_anterior_episodio": context_json,
                    "revisor_1": "",
                    "rotulo_revisor_1": "",
                    "revisor_2": "",
                    "rotulo_revisor_2": "",
                    "adjudicador": "",
                    "rotulo_adjudicado": "",
                    "observacao": "",
                }
            )
            manifest.append(
                {
                    "review_id": review_id,
                    "case_id": case["case_id"],
                    "episode_id": case["episode_id"],
                    "scenario_id": case["scenario_id"],
                    "etapa": stage,
                    "gabarito_sintetico": normalize_label(gold),
                }
            )
    return blind, manifest


def export(dataset: Path, output: Path) -> None:
    blind, decisions = rows_for_review(load_dataset(dataset))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(blind)
    manifest = {
        "schema_version": "rotulagem-cega-v2.1.0",
        "dataset": str(dataset),
        "dataset_sha256": sha256(dataset),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_decisoes": len(decisions),
        "decisoes": decisions,
    }
    output.with_name(output.stem + "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] Planilha cega: {output} ({len(blind)} decisões)")


def load_reviewer_profile(path: Path) -> dict:
    profile = json.loads(path.read_text(encoding="utf-8"))
    reviewers = profile.get("avaliadores", [])
    if len(reviewers) < 3:
        raise ValueError("O perfil deve registrar ao menos três avaliadores.")
    required = {
        "id_anonimo",
        "area_atuacao",
        "anos_experiencia",
        "treinamento_protocolo",
    }
    ids: list[str] = []
    for reviewer in reviewers:
        missing = required - set(reviewer)
        if missing:
            raise ValueError(
                f"Perfil de avaliador incompleto; faltam: {sorted(missing)}"
            )
        reviewer_id = str(reviewer["id_anonimo"]).strip()
        area = str(reviewer["area_atuacao"]).strip()
        training = str(reviewer["treinamento_protocolo"]).strip()
        if not reviewer_id or not area or not training:
            raise ValueError("O perfil contém campos obrigatórios vazios.")
        if "PREENCHER" in {area.upper(), training.upper()}:
            raise ValueError("Substitua todos os placeholders do perfil.")
        if float(reviewer["anos_experiencia"]) <= 0:
            raise ValueError("anos_experiencia deve ser maior que zero.")
        ids.append(reviewer_id)
    if len(ids) != len(set(ids)):
        raise ValueError("Os identificadores dos avaliadores devem ser distintos.")
    if not str(profile.get("versao_instrucoes") or "").strip():
        raise ValueError("O perfil deve registrar versao_instrucoes.")
    return profile


def cohen_kappa(pairs: list[tuple[str, str]]) -> dict:
    total = len(pairs)
    if total == 0:
        return {"n": 0, "concordancia": None, "cohen_kappa": None}
    observed = sum(left == right for left, right in pairs) / total
    left_counts = Counter(left for left, _ in pairs)
    right_counts = Counter(right for _, right in pairs)
    expected = sum(
        (left_counts[label] / total) * (right_counts[label] / total)
        for label in set(left_counts) | set(right_counts)
    )
    value = (observed - expected) / (1 - expected) if expected < 1 else 1.0
    return {"n": total, "concordancia": observed, "cohen_kappa": value}


def load_manifest(path: Path, dataset: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw
    if raw.get("dataset_sha256") != sha256(dataset):
        raise ValueError("O hash do dataset diverge do manifesto da planilha.")
    decisions = raw.get("decisoes")
    if not isinstance(decisions, list):
        raise ValueError("Manifesto de rotulagem inválido.")
    return decisions


def incorporate(
    dataset: Path,
    sheet: Path,
    output: Path,
    reviewer_profile_path: Path,
) -> None:
    manifest_path = sheet.with_name(sheet.stem + "_manifest.json")
    manifest_rows = load_manifest(manifest_path, dataset)
    manifest = {str(item["review_id"]): item for item in manifest_rows}
    if len(manifest) != len(manifest_rows):
        raise ValueError("O manifesto contém review_id duplicado.")

    with sheet.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    row_ids = [str(row.get("review_id") or "") for row in rows]
    if len(row_ids) != len(set(row_ids)):
        raise ValueError("A planilha contém review_id duplicado.")
    missing = set(manifest) - set(row_ids)
    extra = set(row_ids) - set(manifest)
    if missing or extra:
        raise ValueError(
            f"Planilha incompleta ou divergente; ausentes={sorted(missing)}, extras={sorted(extra)}"
        )

    reviewer_profile = load_reviewer_profile(reviewer_profile_path)
    reviewer_ids = {
        str(item["id_anonimo"]).strip()
        for item in reviewer_profile["avaliadores"]
    }
    pairs: dict[str, list[tuple[str, str]]] = defaultdict(list)
    changes: list[dict] = []
    adjudicated: list[dict] = []

    for row in rows:
        meta = manifest[row["review_id"]]
        stage = str(meta["etapa"])
        allowed = DEDUP_LABELS if stage == "DEDUPLICACAO" else CLASS_LABELS
        reviewer_1 = row.get("revisor_1", "").strip()
        reviewer_2 = row.get("revisor_2", "").strip()
        if reviewer_1 not in reviewer_ids or reviewer_2 not in reviewer_ids:
            raise ValueError(
                f"{row['review_id']}: revisores não constam no perfil."
            )
        if reviewer_1 == reviewer_2:
            raise ValueError(f"{row['review_id']}: os dois revisores devem ser distintos.")

        left = normalize_label(row.get("rotulo_revisor_1", ""))
        right = normalize_label(row.get("rotulo_revisor_2", ""))
        if left not in allowed or right not in allowed:
            raise ValueError(f"{row['review_id']}: rótulo inválido ou ausente.")
        pairs[stage].append((left, right))

        adjudicator = row.get("adjudicador", "").strip()
        if left == right:
            final = left
            if adjudicator or normalize_label(row.get("rotulo_adjudicado", "")):
                raise ValueError(
                    f"{row['review_id']}: não preencha adjudicação quando há concordância."
                )
        else:
            final = normalize_label(row.get("rotulo_adjudicado", ""))
            if final not in allowed:
                raise ValueError(f"{row['review_id']}: divergência exige rótulo adjudicado.")
            if adjudicator not in reviewer_ids:
                raise ValueError(f"{row['review_id']}: adjudicador não consta no perfil.")
            if adjudicator in {reviewer_1, reviewer_2}:
                raise ValueError(
                    f"{row['review_id']}: o adjudicador deve ser um terceiro avaliador."
                )

        result_row = {
            **meta,
            "revisor_1": reviewer_1,
            "rotulo_revisor_1": left,
            "revisor_2": reviewer_2,
            "rotulo_revisor_2": right,
            "adjudicador": adjudicator or None,
            "rotulo_final": final,
        }
        adjudicated.append(result_row)
        if final != normalize_label(str(meta["gabarito_sintetico"])):
            changes.append(result_row)

    result = {
        "schema_version": "resultado-rotulagem-v2.1.0",
        "dataset": str(dataset),
        "dataset_sha256": sha256(dataset),
        "planilha_sha256": sha256(sheet),
        "perfil_avaliadores_sha256": sha256(reviewer_profile_path),
        "versao_instrucoes": reviewer_profile["versao_instrucoes"],
        "total_decisoes": len(rows),
        "confiabilidade": {
            stage: cohen_kappa(stage_pairs) for stage, stage_pairs in pairs.items()
        },
        "alteracoes_necessarias": changes,
        "rotulos_adjudicados": adjudicated,
        "approved": not changes,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] Validação: {output}; approved={result['approved']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exporta e valida rotulagem cega do dataset sintético."
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--planilha", type=Path, required=True)
    parser.add_argument("--incorporar", action="store_true")
    parser.add_argument("--saida-validacao", type=Path)
    parser.add_argument("--perfil-avaliadores", type=Path)
    args = parser.parse_args()
    if args.incorporar:
        if not args.saida_validacao or not args.perfil_avaliadores:
            raise SystemExit(
                "--incorporar exige --saida-validacao e --perfil-avaliadores"
            )
        incorporate(
            args.dataset,
            args.planilha,
            args.saida_validacao,
            args.perfil_avaliadores,
        )
    else:
        export(args.dataset, args.planilha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
