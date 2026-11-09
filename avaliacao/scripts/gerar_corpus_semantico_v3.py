from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import treinar_modelo_local as pipeline


ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = ROOT / "avaliacao" / "catalogos" / "corpus_semantico_v3"
CLASS_CATALOG = CATALOG_DIR / "catalogo_classificacao_v3_1.json"
DEDUP_CATALOG = CATALOG_DIR / "catalogo_deduplicacao_v3_1.json"
OUTPUT_DIR = ROOT / "avaliacao" / "datasets" / "semantico_v3"
DEV_OUTPUT = OUTPUT_DIR / "desenvolvimento_semantico_v3_1.jsonl"
DEV_MANIFEST = OUTPUT_DIR / "desenvolvimento_semantico_v3_1_manifest.json"
LOCKED_OUTPUT = OUTPUT_DIR / "desafio_semantico_bloqueado_v3_1.jsonl"
LOCKED_MANIFEST = OUTPUT_DIR / "desafio_semantico_bloqueado_v3_1_manifest.json"

VERSION = "3.1.0"
SEED = 20260914
GENERATED_AT = "2026-09-14T00:00:00Z"
CLASSES = ("OBRA", "DEMO", "SOB_DEMANDA", "TRIAGEM_MANUAL")
DEV_CLASS_TARGET = 100
LOCKED_CLASS_TARGET = 25
DEV_DEDUP_TARGETS = {"positive": 186, "complete_negative": 97, "critical_negative": 75}
LOCKED_DEDUP_TARGETS = {"positive": 47, "complete_negative": 24, "critical_negative": 19}
LOCATIONS = (
    "Núcleo de zootecnia", "Laboratório de materiais", "Arquivo institucional",
    "Unidade de processamento", "Centro de línguas", "Estação experimental",
    "Pavilhão de pós-graduação", "Setor de coleções", "Anexo administrativo",
    "Área técnica leste", "Complexo esportivo", "Casa de vegetação",
)
REQUESTERS = ("fiscal", "docente", "técnico de laboratório", "assistente administrativo", "estudante bolsista")


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def artifact_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(resolved).replace("\\", "/")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalized_visible(row: dict[str, Any]) -> str:
    return " ".join(" ".join(str(row.get(key) or "").casefold().split()) for key in ("title", "content", "category", "location"))


def base_record(*, case_id: str, scenario_id: str, episode_id: str, dimension: str,
                order: int, title: str, content: str, category: str, location: str,
                split: str, semantic_key: dict[str, Any], source_key: dict[str, Any],
                grammar_key: dict[str, Any], occurrence: datetime) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "scenario_id": scenario_id,
        "group_id": scenario_id,
        "episode_id": episode_id,
        "dimension": dimension,
        "order_in_episode": order,
        "title": title,
        "content": content,
        "category": category,
        "location": location,
        "requester": REQUESTERS[int(canonical_sha256(source_key)[:4], 16) % len(REQUESTERS)],
        "expected_classification": None,
        "expected_dedup": None,
        "pair_role": "",
        "reference_case_id": "",
        "contrast_anchor_case_id": "",
        # Nenhuma chave abaixo contém split, seed, scenario_set ou realização superficial.
        "semantic_family_sha256": canonical_sha256(semantic_key),
        "source_dependency_group_sha256": canonical_sha256(source_key),
        "grammar_family_sha256": canonical_sha256(grammar_key),
        "split": split,
        "rationale": "",
        "label_source": "synthetic_proxy",
        "dataset_version": VERSION,
        "synthetic": True,
        "confirmatory_eligible": False,
        "urgency": 3,
        "impact": 3,
        "status": 1,
        "occurrence_at": occurrence.isoformat(),
    }


def classification_groups(catalog: dict[str, Any], *, locked: bool) -> list[list[dict[str, Any]]]:
    split = "TESTE_BLOQUEADO" if locked else "DESENVOLVIMENTO"
    mechanism_key = "locked_mechanisms" if locked else "mechanisms"
    prefix = "LOCK" if locked else "DEV"
    groups: list[list[dict[str, Any]]] = []
    serial = 0
    for label in CLASSES:
        assets = [item for item in catalog["assets"][label] if (len(item) == 3) == locked]
        mechanisms = catalog[mechanism_key][label]
        for asset_index, item in enumerate(assets):
            asset, category = item[:2]
            for mechanism_index, (mechanism, request, evidence) in enumerate(mechanisms):
                serial += 1
                semantic = {"task": "classification", "class": label, "asset": asset, "mechanism": mechanism}
                source = {"task": "classification", "class": label, "authored_asset_source": asset}
                grammar = {"task": "classification", "class": label, "authored_grammar": mechanism}
                scenario_id = f"{prefix}-SEM31-C-{label}-{asset_index + 1:02d}-{mechanism_index + 1:02d}"
                variants = 1 if locked else 2
                group: list[dict[str, Any]] = []
                for variant in range(variants):
                    wording = request.format(asset=asset)
                    proof = evidence.format(asset=asset)
                    if variant:
                        wording = f"Após vistoria, solicita-se {wording}"
                        proof = f"O escopo confirmado registra que {proof[0].lower() + proof[1:]}"
                    row = base_record(
                        case_id=f"{prefix}-SEM31-C-{serial:04d}-R{variant + 1}",
                        scenario_id=scenario_id,
                        episode_id=scenario_id,
                        dimension="CLASSIFICACAO",
                        order=variant + 1,
                        title=f"{mechanism.replace('_', ' ').title()}: {asset}",
                        content=f"{wording}. {proof}.",
                        category=category,
                        location="" if label in {"OBRA", "SOB_DEMANDA"} else LOCATIONS[(serial + variant) % len(LOCATIONS)],
                        split=split,
                        semantic_key=semantic,
                        source_key=source,
                        grammar_key=grammar,
                        occurrence=datetime(2025, 5 if locked else 1, 1, tzinfo=timezone.utc) + timedelta(hours=serial * 7 + variant),
                    )
                    row.update({
                        "expected_classification": label,
                        "pair_role": "CLASSIFICATION",
                        "rationale": f"Hipótese proxy: o fato decisório corresponde a {mechanism}; exige adjudicação institucional.",
                    })
                    group.append(row)
                groups.append(group)
    return groups


def pair_text(asset: str, fault: str, relation: str, location: str, other: str, index: int) -> tuple[str, str, str]:
    tag = f"EQ-{index + 4100}"
    order = f"OS-{index + 8100}"
    anchor = f"O {asset}, identificação {tag}, apresenta {fault} em {location}; foi aberto o atendimento {order}."
    positive = {
        "referencia_explicita": f"Complemento do {order}: o {asset} {tag} continua com {fault}.",
        "mesmo_patrimonio_outro_solicitante": f"Outro usuário confirmou {fault} no mesmo {asset}, identificação {tag}.",
        "complemento_mesma_falha": f"No {asset} {tag}, a falha de {fault} também ocorre depois de aquecer; anexar ao relato existente.",
        "parafrase_mesmo_ativo": f"O equipamento {tag} segue apresentando a anomalia já descrita: {fault}.",
        "continuidade_nao_resolvida": f"O atendimento não eliminou a falha; o {asset} {tag} permanece com {fault}.",
        "descricao_curta_com_id": f"{tag}: ainda {fault}; mesma ocorrência.",
        "numero_de_os_compartilhado": f"Registrar na ordem {order}: persiste {fault} no {asset}.",
        "etiqueta_e_instante_coincidem": f"Relato simultâneo confirma no ativo {tag} a mesma condição: {fault}.",
        "retorno_do_mesmo_atendimento": f"Durante o retorno do serviço {order}, constatou-se que o {asset} ainda {fault}.",
    }
    complete = {
        "ativo_distinto_mesmo_local": f"Outro {asset}, identificação EQ-{index + 9100}, apresenta {fault} no mesmo local.",
        "mesmo_ativo_falha_distinta": f"O {asset} {tag} opera quanto a '{fault}', mas agora apresenta ruptura física diferente.",
        "mesmo_sintoma_outro_local": f"Um {asset} identificado como EQ-{index + 9200}, em {other}, apresenta {fault}.",
        "incidente_novo_apos_resolucao": f"A {order} foi encerrada com teste aprovado; um mês depois o {asset} {tag} voltou a {fault} em novo evento.",
        "identificador_distinto": f"Título semelhante, porém o ativo atual é EQ-{index + 9300}, não {tag}; ele {fault}.",
        "componente_distinto": f"No mesmo conjunto, um componente identificado EQ-{index + 9400} apresenta {fault}; {tag} está normal.",
        "serial_explicitamente_distinto": f"A ocorrência atual é do serial EQ-{index + 9500}; o registro {tag} foi conferido e funciona.",
        "predio_e_unidade_distintos": f"Em {other}, a unidade EQ-{index + 9600} de {asset} apresenta {fault}; não é a unidade de {location}.",
        "falha_posterior_documentada": f"O termo de aceite encerrou {order}; após quarenta dias iniciou-se outra falha em {asset} {tag}: {fault}.",
    }
    critical = {
        "sem_identificador": f"Há notícia de {asset} com {fault}, sem local, identificação ou referência verificável.",
        "identificadores_conflitantes": f"A mensagem associa {fault} tanto a {tag} quanto a EQ-{index + 9700}, sem indicar o ativo correto.",
        "multiplas_ancoras": f"Vários registros de {asset} mencionam {fault}; o relato atual não identifica qual deles continua aberto.",
        "estado_de_resolucao_incerto": f"O {asset} talvez ainda apresente {fault}, mas não se sabe se {order} foi executada ou encerrada.",
        "objeto_generico": f"Foi informado apenas que algo semelhante apresenta {fault}, sem objeto ou vínculo observável.",
        "candidato_nao_identificado": f"O setor relata {fault}, porém existem várias unidades de {asset} e nenhuma foi apontada.",
        "duas_os_possiveis": f"O texto cita duas ordens possíveis, {order} e OS-{index + 9800}, sem escolher a ocorrência relacionada.",
        "historico_indeterminado_operacional": f"Há menção anterior a {asset} com {fault}, mas o histórico visível não permite saber se é continuidade ou novo evento.",
    }
    current = positive.get(relation) or complete.get(relation) or critical.get(relation)
    if current is None:
        raise ValueError(f"Relação desconhecida: {relation}")
    return anchor, current, tag


def dedup_groups(catalog: dict[str, Any], *, locked: bool) -> list[list[dict[str, Any]]]:
    split = "TESTE_BLOQUEADO" if locked else "DESENVOLVIMENTO"
    prefix = "LOCK" if locked else "DEV"
    assets = catalog["locked_assets" if locked else "development_assets"]
    relations = catalog["locked_relations" if locked else "relations"]
    targets = LOCKED_DEDUP_TARGETS if locked else DEV_DEDUP_TARGETS
    recipes: list[tuple[str, list[str], str]] = []
    for stratum in ("positive", "complete_negative", "critical_negative"):
        candidates = [(stratum, asset, relation) for asset in assets for relation in relations[stratum]]
        recipes.extend(candidates[:targets[stratum]])
    groups: list[list[dict[str, Any]]] = []
    for index, (stratum, asset_row, relation) in enumerate(recipes):
        asset, fault, category = asset_row
        location = LOCATIONS[(index * 3 + (5 if locked else 0)) % len(LOCATIONS)]
        other = LOCATIONS[(index * 3 + 7) % len(LOCATIONS)]
        semantic = {"task": "deduplication", "asset": asset, "fault": fault, "relation": relation, "stratum": stratum}
        source = {"task": "deduplication", "authored_incident_source": [asset, fault]}
        grammar = {"task": "deduplication", "authored_relation": relation}
        scenario = f"{prefix}-SEM31-D-{index + 1:04d}"
        anchor_text, current_text, tag = pair_text(asset, fault, relation, location, other, index)
        base_time = datetime(2025, 6 if locked else 3, 1, tzinfo=timezone.utc) + timedelta(hours=index * 11)
        anchor_id = f"{scenario}-A"
        anchor = base_record(case_id=anchor_id, scenario_id=scenario, episode_id=scenario,
                             dimension="DEDUPLICACAO", order=1, title=f"Ocorrência em {asset}",
                             content=anchor_text, category=category, location=location, split=split,
                             semantic_key=semantic, source_key=source, grammar_key=grammar, occurrence=base_time)
        anchor.update({"pair_role": "ANCHOR", "dedup_stratum": stratum, "asset_tag": tag,
                       "rationale": "Âncora sintética sem rótulo de deduplicação próprio."})
        expected = stratum == "positive"
        current_location = other if relation in {"mesmo_sintoma_outro_local", "predio_e_unidade_distintos"} else location
        if stratum == "critical_negative":
            current_location = ""
        current = base_record(case_id=f"{scenario}-C", scenario_id=scenario, episode_id=scenario,
                              dimension="DEDUPLICACAO", order=2, title=f"Reavaliação de {asset}",
                              content=current_text, category=category,
                              location=current_location, split=split,
                              semantic_key=semantic, source_key=source, grammar_key=grammar,
                              occurrence=base_time + timedelta(minutes=53))
        if stratum == "critical_negative":
            rationale = "Decisão operacional proxy: não fundir automaticamente sem evidência; não afirma que os eventos sejam semanticamente distintos."
        else:
            rationale = "Vínculo visível suficiente com a âncora." if expected else "Evidência visível identifica evento, ativo ou componente distinto."
        current.update({"expected_dedup": expected, "pair_role": "CHALLENGE",
                        "reference_case_id": anchor_id, "contrast_anchor_case_id": anchor_id,
                        "dedup_stratum": stratum, "asset_tag": tag, "rationale": rationale,
                        "requires_human_review": stratum == "critical_negative"})
        groups.append([anchor, current])
    return groups


def flatten(groups: list[list[dict[str, Any]]], seed: int) -> list[dict[str, Any]]:
    shuffled = list(groups)
    random.Random(seed).shuffle(shuffled)
    rows = [row for group in shuffled for row in group]
    for row in rows:
        row["visible_text_sha256"] = canonical_sha256(normalized_visible(row))
    return rows


def validate(rows: list[dict[str, Any]], *, locked: bool) -> dict[str, Any]:
    classes: dict[str, set[str]] = defaultdict(set)
    strata: Counter[str] = Counter()
    for row in rows:
        if row["pair_role"] == "CLASSIFICATION":
            classes[row["expected_classification"]].add(row["semantic_family_sha256"])
        elif row["pair_role"] == "CHALLENGE":
            strata[row["dedup_stratum"]] += 1
            anchor = next((candidate for candidate in rows if candidate["case_id"] == row["reference_case_id"]), None)
            if not anchor or anchor["episode_id"] != row["episode_id"] or anchor["order_in_episode"] != 1:
                raise ValueError(f"Relação dedup inválida: {row['case_id']}")
    target_class = LOCKED_CLASS_TARGET if locked else DEV_CLASS_TARGET
    target_dedup = LOCKED_DEDUP_TARGETS if locked else DEV_DEDUP_TARGETS
    if {label: len(classes[label]) for label in CLASSES} != {label: target_class for label in CLASSES}:
        raise ValueError("Cobertura classificatória inválida")
    if dict(strata) != target_dedup:
        raise ValueError(f"Cobertura dedup inválida: {dict(strata)}")
    visible = [row["visible_text_sha256"] for row in rows]
    if len(visible) != len(set(visible)):
        raise ValueError("Há texto visível duplicado")
    routed = pipeline.classification_model_rows(rows)
    routed_records = Counter(row["expected_classification"] for row in routed)
    routed_families = {
        label: len({row["semantic_family_sha256"] for row in routed if row["expected_classification"] == label})
        for label in CLASSES
    }
    return {
        "status": "PASS",
        "records": len(rows),
        "semantic_classification_families_by_class": {label: len(classes[label]) for label in CLASSES},
        "dedup_challenges_by_stratum": dict(strata),
        "source_dependency_groups": len({row["source_dependency_group_sha256"] for row in rows}),
        "grammar_families": len({row["grammar_family_sha256"] for row in rows}),
        "unique_visible_texts": len(visible),
        "post_fixed_router_records_by_class": {label: routed_records[label] for label in CLASSES},
        "post_fixed_router_semantic_families_by_class": routed_families,
    }


def overlap(left: list[dict[str, Any]], right: list[dict[str, Any]], field: str) -> int:
    return len({row[field] for row in left} & {row[field] for row in right})


def jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows).encode("utf-8")


def guarded_write(path: Path, payload: bytes, *, immutable: bool, replace_locked_confirmed: bool) -> None:
    if path.exists():
        current = path.read_bytes()
        if current == payload:
            return
        if immutable and not replace_locked_confirmed:
            raise FileExistsError(f"Artefato bloqueado diverge e não será sobrescrito sem confirmação explícita: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def manifest(path: Path, rows: list[dict[str, Any]], validation: dict[str, Any], *, locked: bool,
             cross: dict[str, int], dataset_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": VERSION,
        "dataset_version": VERSION,
        "generated_at": GENERATED_AT,
        "split": "TESTE_BLOQUEADO" if locked else "DESENVOLVIMENTO",
        "selection_access": "FORBIDDEN_UNTIL_MODEL_SELECTION_FROZEN" if locked else "ALLOWED_FOR_GROUPED_DEVELOPMENT",
        "status": "FROZEN_LOCKED_SYNTHETIC_CHALLENGE" if locked else "SYNTHETIC_DEVELOPMENT_ONLY",
        "label_source": "synthetic_proxy",
        "synthetic": True,
        "proxy_labels_only": True,
        "confirmatory_eligible": False,
        "scientific_result": False,
        "inference_method": "known_grammar_conditional",
        "validation": validation,
        "cross_partition_overlap": cross,
        "files": {
            "jsonl": {"path": artifact_path(path), "sha256": dataset_sha256},
            "classification_catalog": {"path": str(CLASS_CATALOG.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256_file(CLASS_CATALOG)},
            "dedup_catalog": {"path": str(DEDUP_CATALOG.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256_file(DEDUP_CATALOG)},
            "generator": {"path": str(Path(__file__).resolve().relative_to(ROOT)).replace("\\", "/"), "sha256": sha256_file(Path(__file__).resolve())},
            "fixed_router": {"path": str(Path(pipeline.__file__).resolve().relative_to(ROOT)).replace("\\", "/"), "sha256": sha256_file(Path(pipeline.__file__).resolve())},
        },
        "grouping": {
            "semantic_coverage_field": "semantic_family_sha256",
            "primary_dependency_field": "source_dependency_group_sha256",
            "grammar_sensitivity_field": "grammar_family_sha256",
            "hashes_exclude_split_seed_scenario_set_and_surface_realization": True,
            "coverage_is_not_effective_sample_size": True,
            "effective_sample_size": "UNKNOWN",
            "unit_count_rule": "Somente semantic_family_sha256 com conteúdo visível factual distinto conta para cobertura; variações superficiais não contam.",
        },
        "limitations": [
            "Cobertura semântica sintética não é tamanho amostral efetivo nem amostra da distribuição institucional.",
            "As cinco regras por ativo compartilham uma fonte autorada e devem permanecer agrupadas.",
            "Resultados são exploratórios e condicionais às gramáticas conhecidas; relatar sensibilidade por grammar_family_sha256.",
            "Cobertura bruta não equivale ao estrato pós-roteador; comparar o classificador condicional ao roteador fixo e o desafio no pipeline completo.",
            "O desafio é pequeno e sintético; seu n não demonstra risco de erro menor ou igual a 2%.",
            "Negativo crítico representa decisão operacional de não fusão automática, não certeza de eventos semanticamente distintos.",
        ],
    }


def generate(dev_output: Path = DEV_OUTPUT, dev_manifest: Path = DEV_MANIFEST,
             locked_output: Path = LOCKED_OUTPUT, locked_manifest: Path = LOCKED_MANIFEST,
             *, replace_locked_confirmed: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    class_catalog = load_json(CLASS_CATALOG)
    dedup_catalog = load_json(DEDUP_CATALOG)
    dev = flatten([*classification_groups(class_catalog, locked=False), *dedup_groups(dedup_catalog, locked=False)], SEED)
    locked = flatten([*classification_groups(class_catalog, locked=True), *dedup_groups(dedup_catalog, locked=True)], SEED + 1)
    dev_validation = validate(dev, locked=False)
    locked_validation = validate(locked, locked=True)
    fields = ("semantic_family_sha256", "source_dependency_group_sha256", "grammar_family_sha256", "visible_text_sha256")
    cross = {field: overlap(dev, locked, field) for field in fields}
    if cross["semantic_family_sha256"] or cross["source_dependency_group_sha256"] or cross["visible_text_sha256"]:
        raise ValueError(f"Partições reutilizam família, fonte ou texto: {cross}")
    # Gramáticas bloqueadas também são autoradas independentemente; overlap zero é verificado, não fabricado pelo split.
    if cross["grammar_family_sha256"]:
        raise ValueError(f"Partições reutilizam gramática: {cross}")
    dev_bytes = jsonl_bytes(dev)
    locked_bytes = jsonl_bytes(locked)
    dev_payload = manifest(dev_output, dev, dev_validation, locked=False, cross=cross,
                           dataset_sha256=sha256_bytes(dev_bytes))
    locked_payload = manifest(locked_output, locked, locked_validation, locked=True, cross=cross,
                              dataset_sha256=sha256_bytes(locked_bytes))
    dev_manifest_bytes = (json.dumps(dev_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    locked_manifest_bytes = (json.dumps(locked_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    # Valida os dois componentes do selo antes de escrever qualquer um deles.
    for path, payload in ((locked_output, locked_bytes), (locked_manifest, locked_manifest_bytes)):
        if path.exists() and path.read_bytes() != payload and not replace_locked_confirmed:
            raise FileExistsError(f"Artefato bloqueado diverge e não será sobrescrito sem confirmação explícita: {path}")
    guarded_write(dev_output, dev_bytes, immutable=False, replace_locked_confirmed=replace_locked_confirmed)
    guarded_write(locked_output, locked_bytes, immutable=True, replace_locked_confirmed=replace_locked_confirmed)
    guarded_write(dev_manifest, dev_manifest_bytes, immutable=False, replace_locked_confirmed=replace_locked_confirmed)
    guarded_write(locked_manifest, locked_manifest_bytes, immutable=True, replace_locked_confirmed=replace_locked_confirmed)
    return dev_payload, locked_payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera corpus semântico prospectivo v3.1, offline e determinístico.")
    parser.add_argument("--dev", type=Path, default=DEV_OUTPUT)
    parser.add_argument("--dev-manifest", type=Path, default=DEV_MANIFEST)
    parser.add_argument("--locked", type=Path, default=LOCKED_OUTPUT)
    parser.add_argument("--locked-manifest", type=Path, default=LOCKED_MANIFEST)
    parser.add_argument("--replace-locked-confirmed", action="store_true", help="Confirma substituição deliberada de artefato bloqueado divergente.")
    args = parser.parse_args()
    dev, locked = generate(args.dev, args.dev_manifest, args.locked, args.locked_manifest,
                           replace_locked_confirmed=args.replace_locked_confirmed)
    print(json.dumps({"development": dev["validation"], "locked": locked["validation"], "overlap": dev["cross_partition_overlap"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
