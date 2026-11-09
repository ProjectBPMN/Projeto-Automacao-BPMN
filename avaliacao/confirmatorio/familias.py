from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .util import (
    canonical_json_bytes,
    exclusive_write_bytes,
    exclusive_write_json,
    family_ids_sha256,
    load_json,
    load_jsonl_bytes,
    parse_aware_datetime,
    require_list,
    require_mapping,
    require_sha256,
    require_string,
    sha256_bytes,
    sha256_file,
    utc_now,
)


SCHEMA_VERSION = "dedup-independent-family-v1"
LABELS = {"DUPLICADO", "NAO_DUPLICADO"}
REAL_EVIDENCE_TIER = "REAL_INSTITUTIONAL"


def _review(review: Any, context: str) -> tuple[str, str, Any]:
    value = require_mapping(review, context)
    reviewer_id = require_string(value.get("reviewer_id"), f"{context}.reviewer_id")
    label = require_string(value.get("label"), f"{context}.label").upper()
    if label not in LABELS:
        raise ValueError(f"{context}.label inválido: {label}")
    reviewed_at = parse_aware_datetime(value.get("reviewed_at"), f"{context}.reviewed_at")
    if value.get("blind_to_model") is not True:
        raise ValueError(f"{context}.blind_to_model deve ser true")
    if value.get("blind_to_other_reviewer") is not True:
        raise ValueError(f"{context}.blind_to_other_reviewer deve ser true")
    return reviewer_id, label, reviewed_at


def validate_family(row: dict[str, Any], *, index: int | None = None) -> None:
    prefix = f"familia[{index}]" if index is not None else "familia"
    if row.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{prefix}.schema_version deve ser {SCHEMA_VERSION!r}")
    require_string(row.get("family_id"), f"{prefix}.family_id")
    if row.get("evidence_tier") != REAL_EVIDENCE_TIER:
        raise ValueError(
            f"{prefix}.evidence_tier deve ser {REAL_EVIDENCE_TIER!r}; "
            "dados sintéticos/piloto não são elegíveis"
        )
    require_sha256(
        row.get("source_dependency_group_sha256"),
        f"{prefix}.source_dependency_group_sha256",
    )

    provenance = require_mapping(row.get("provenance"), f"{prefix}.provenance")
    for field in (
        "source_system",
        "source_instance_id",
        "extraction_id",
        "query_or_export_ref",
        "collector_id",
        "chain_of_custody_ref",
    ):
        require_string(provenance.get(field), f"{prefix}.provenance.{field}")
    collected_at = parse_aware_datetime(
        provenance.get("collected_at"), f"{prefix}.provenance.collected_at"
    )
    require_sha256(
        provenance.get("raw_export_sha256"), f"{prefix}.provenance.raw_export_sha256"
    )

    independence = require_mapping(row.get("independence"), f"{prefix}.independence")
    if independence.get("attested_independent") is not True:
        raise ValueError(f"{prefix}.independence.attested_independent deve ser true")
    if independence.get("development_overlap_checked") is not True:
        raise ValueError(
            f"{prefix}.independence.development_overlap_checked deve ser true"
        )
    if independence.get("other_holdout_overlap_checked") is not True:
        raise ValueError(
            f"{prefix}.independence.other_holdout_overlap_checked deve ser true"
        )
    for field in ("auditor_id", "method", "attestation_ref"):
        require_string(independence.get(field), f"{prefix}.independence.{field}")
    independence_at = parse_aware_datetime(
        independence.get("reviewed_at"), f"{prefix}.independence.reviewed_at"
    )
    related = require_list(
        independence.get("known_related_family_ids", []),
        f"{prefix}.independence.known_related_family_ids",
        nonempty=False,
    )
    if related:
        raise ValueError(
            f"{prefix} declara famílias relacionadas e não pode contar como unidade independente"
        )

    records = require_list(row.get("records"), f"{prefix}.records")
    if len(records) < 2:
        raise ValueError(f"{prefix}.records deve conter ao menos âncora e desafio")
    record_ids: set[str] = set()
    for record_index, raw_record in enumerate(records):
        record = require_mapping(raw_record, f"{prefix}.records[{record_index}]")
        record_id = require_string(
            record.get("source_record_id"),
            f"{prefix}.records[{record_index}].source_record_id",
        )
        if record_id in record_ids:
            raise ValueError(f"{prefix} repete source_record_id {record_id!r}")
        record_ids.add(record_id)
        occurred_at = parse_aware_datetime(
            record.get("occurred_at"), f"{prefix}.records[{record_index}].occurred_at"
        )
        if occurred_at > collected_at:
            raise ValueError(f"{prefix} contém registro posterior à coleta")
        require_sha256(
            record.get("content_sha256"),
            f"{prefix}.records[{record_index}].content_sha256",
        )
        require_string(
            record.get("protected_payload_ref"),
            f"{prefix}.records[{record_index}].protected_payload_ref",
        )

    anchor_id = require_string(row.get("primary_anchor_id"), f"{prefix}.primary_anchor_id")
    challenge_id = require_string(
        row.get("primary_challenge_id"), f"{prefix}.primary_challenge_id"
    )
    if anchor_id == challenge_id or {anchor_id, challenge_id} - record_ids:
        raise ValueError(f"{prefix} deve apontar para âncora e desafio distintos existentes")

    adjudication = require_mapping(row.get("adjudication"), f"{prefix}.adjudication")
    require_string(
        adjudication.get("protocol_version"), f"{prefix}.adjudication.protocol_version"
    )
    first_id, first_label, first_at = _review(
        adjudication.get("reviewer_1"), f"{prefix}.adjudication.reviewer_1"
    )
    second_id, second_label, second_at = _review(
        adjudication.get("reviewer_2"), f"{prefix}.adjudication.reviewer_2"
    )
    if first_id == second_id:
        raise ValueError(f"{prefix} exige dois revisores distintos")
    if min(first_at, second_at) < collected_at:
        raise ValueError(f"{prefix} contém revisão anterior à coleta institucional")
    final_label = require_string(
        adjudication.get("final_label"), f"{prefix}.adjudication.final_label"
    ).upper()
    if final_label not in LABELS:
        raise ValueError(f"{prefix}.adjudication.final_label inválido")
    finalized_at = parse_aware_datetime(
        adjudication.get("finalized_at"), f"{prefix}.adjudication.finalized_at"
    )
    if finalized_at < max(first_at, second_at):
        raise ValueError(f"{prefix}.adjudication.finalized_at antecede as revisões")
    if first_label == second_label:
        if final_label != first_label:
            raise ValueError(f"{prefix} altera consenso dos revisores sem justificativa")
    else:
        adjudicator = require_mapping(
            adjudication.get("adjudicator"), f"{prefix}.adjudication.adjudicator"
        )
        adjudicator_id = require_string(
            adjudicator.get("reviewer_id"),
            f"{prefix}.adjudication.adjudicator.reviewer_id",
        )
        if adjudicator_id in {first_id, second_id}:
            raise ValueError(f"{prefix} exige terceiro adjudicador independente")
        adjudicated_label = require_string(
            adjudicator.get("label"), f"{prefix}.adjudication.adjudicator.label"
        ).upper()
        if adjudicated_label not in LABELS or adjudicated_label != final_label:
            raise ValueError(f"{prefix} possui adjudicação final inconsistente")
        adjudicator_at = parse_aware_datetime(
            adjudicator.get("reviewed_at"),
            f"{prefix}.adjudication.adjudicator.reviewed_at",
        )
        if adjudicator_at < max(first_at, second_at) or finalized_at < adjudicator_at:
            raise ValueError(f"{prefix} possui ordem temporal de adjudicação inválida")
        if adjudicator.get("blind_to_model") is not True:
            raise ValueError(f"{prefix} exige adjudicador cego à saída do modelo")

    if independence_at < collected_at:
        raise ValueError(f"{prefix}.independence.reviewed_at antecede a coleta")
    subgroups = require_mapping(row.get("subgroups"), f"{prefix}.subgroups")
    if not subgroups:
        raise ValueError(f"{prefix}.subgroups não pode ser vazio")
    for key, value in subgroups.items():
        require_string(key, f"{prefix}.subgroups.chave")
        require_string(value, f"{prefix}.subgroups.{key}")


def load_exclusions(path: Path | None) -> dict[str, set[str]]:
    empty = {
        "source_dependency_group_sha256": set(),
        "content_sha256": set(),
        "source_record_keys": set(),
    }
    if path is None:
        return empty
    payload = load_json(path)
    output: dict[str, set[str]] = {}
    for field in empty:
        raw = require_list(payload.get(field, []), f"exclusions.{field}", nonempty=False)
        values = {require_string(value, f"exclusions.{field}[]") for value in raw}
        if field != "source_record_keys":
            for value in values:
                require_sha256(value, f"exclusions.{field}[]")
        output[field] = values
    return output


def validate_registry(
    rows: list[dict[str, Any]],
    *,
    exclusions: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    if not rows:
        raise ValueError("registro de famílias vazio")
    exclusions = exclusions or load_exclusions(None)
    family_ids: set[str] = set()
    group_hashes: set[str] = set()
    record_keys: set[str] = set()
    content_hashes: set[str] = set()
    labels: Counter[str] = Counter()
    subgroup_counts: dict[str, Counter[str]] = defaultdict(Counter)

    for index, row in enumerate(rows):
        validate_family(row, index=index)
        family_id = str(row["family_id"])
        group_hash = str(row["source_dependency_group_sha256"]).lower()
        if family_id in family_ids:
            raise ValueError(f"family_id repetido: {family_id}")
        if group_hash in group_hashes:
            raise ValueError(
                "duas famílias compartilham source_dependency_group_sha256; "
                "não são unidades independentes"
            )
        if group_hash in exclusions["source_dependency_group_sha256"]:
            raise ValueError(f"grupo presente no registro de exclusão: {group_hash}")
        family_ids.add(family_id)
        group_hashes.add(group_hash)

        provenance = row["provenance"]
        instance = str(provenance["source_instance_id"])
        for record in row["records"]:
            record_key = f"{instance}\x1f{record['source_record_id']}"
            content_hash = str(record["content_sha256"]).lower()
            if record_key in record_keys or record_key in exclusions["source_record_keys"]:
                raise ValueError(f"registro-fonte reutilizado ou proibido: {record_key}")
            if content_hash in content_hashes or content_hash in exclusions["content_sha256"]:
                raise ValueError(
                    f"conteúdo exato reutilizado ou proibido entre famílias: {content_hash}"
                )
            record_keys.add(record_key)
            content_hashes.add(content_hash)
        labels[str(row["adjudication"]["final_label"]).upper()] += 1
        for field, value in row["subgroups"].items():
            subgroup_counts[str(field)][str(value)] += 1

    return {
        "validation_status": "PASS",
        "scientific_result": False,
        "automatic_independence_proof": False,
        "independent_families": len(family_ids),
        "independent_dependency_groups": len(group_hashes),
        "label_counts": dict(sorted(labels.items())),
        "subgroup_counts": {
            field: dict(sorted(counts.items()))
            for field, counts in sorted(subgroup_counts.items())
        },
        "family_ids_sha256": family_ids_sha256(family_ids),
        "limitations": [
            "Hashes detectam sobreposição exata, não equivalência semântica aproximada.",
            "A independência semântica depende da atestação humana e da trilha institucional.",
            "Validação estrutural não transforma o registro em evidência confirmatória.",
        ],
    }


def import_registry(
    source: Path,
    output_dataset: Path,
    output_manifest: Path,
    *,
    exclusions_path: Path | None = None,
) -> dict[str, Any]:
    source = source.resolve()
    output_dataset = output_dataset.resolve()
    output_manifest = output_manifest.resolve()
    if source in {output_dataset, output_manifest}:
        raise ValueError("a origem deve ser distinta dos artefatos imutáveis de saída")
    if output_dataset.exists() or output_manifest.exists():
        raise FileExistsError("dataset/manifesto de saída já existe; importação é imutável")
    try:
        source_payload = source.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError(f"arquivo obrigatório ausente: {source}") from exc
    rows = load_jsonl_bytes(source_payload, str(source))
    exclusions = load_exclusions(exclusions_path.resolve() if exclusions_path else None)
    summary = validate_registry(rows, exclusions=exclusions)
    canonical_dataset = b"".join(
        canonical_json_bytes(row) + b"\n"
        for row in sorted(rows, key=lambda item: str(item["family_id"]))
    )
    dataset_sha = sha256_bytes(canonical_dataset)
    manifest = {
        "schema_version": "dedup-independent-registry-manifest-v1",
        "created_at": utc_now(),
        "source_import_sha256": sha256_bytes(source_payload),
        "dataset_sha256": dataset_sha,
        "dataset_file_name": output_dataset.name,
        "exclusions_sha256": sha256_file(exclusions_path.resolve())
        if exclusions_path
        else None,
        **summary,
        "content_validation_eligible_for_preregistration": True,
        "confirmatory_evaluation_completed": False,
    }
    exclusive_write_bytes(output_dataset, canonical_dataset)
    try:
        exclusive_write_json(output_manifest, manifest)
    except Exception:
        output_dataset.unlink(missing_ok=True)
        raise
    return manifest
