from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .amostra import tamanho_minimo_zero_eventos
from .familias import LABELS, load_exclusions, validate_registry
from .util import (
    canonical_json_bytes,
    contains_placeholder,
    exclusive_write_json,
    load_json,
    load_jsonl,
    parse_aware_datetime,
    require_list,
    require_mapping,
    require_positive_int,
    require_probability,
    require_sha256,
    require_string,
    sha256_bytes,
    sha256_file,
    utc_now,
)


CONFIG_SCHEMA_VERSION = "confirmatory-evaluation-config-v1"
PREREGISTRATION_SCHEMA_VERSION = "confirmatory-preregistration-v1"
FROZEN_STATUS = "FROZEN_BEFORE_HOLDOUT"


def _nonnegative_int(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} deve ser inteiro não negativo")
    return value


def _reject_placeholders(value: Any, context: str = "documento") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_placeholders(item, f"{context}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_placeholders(item, f"{context}[{index}]")
    elif isinstance(value, str):
        if contains_placeholder(value):
            raise ValueError(f"{context} contém placeholder e não pode ser congelado")


def _contract_seal(document: dict[str, Any]) -> str:
    unsealed = copy.deepcopy(document)
    unsealed.pop("contract_sha256", None)
    return sha256_bytes(canonical_json_bytes(unsealed))


def _validate_hypotheses(raw: Any) -> list[dict[str, Any]]:
    hypotheses = require_list(raw, "config.hypotheses")
    ids: set[str] = set()
    primary = 0
    for index, raw_hypothesis in enumerate(hypotheses):
        hypothesis = require_mapping(raw_hypothesis, f"config.hypotheses[{index}]")
        hypothesis_id = require_string(
            hypothesis.get("id"), f"config.hypotheses[{index}].id"
        )
        if hypothesis_id in ids:
            raise ValueError(f"hipótese repetida: {hypothesis_id}")
        ids.add(hypothesis_id)
        for field in ("statement", "endpoint", "null_hypothesis", "decision_rule"):
            require_string(
                hypothesis.get(field), f"config.hypotheses[{index}].{field}"
            )
        if not isinstance(hypothesis.get("primary"), bool):
            raise ValueError(f"config.hypotheses[{index}].primary deve ser booleano")
        if hypothesis["primary"]:
            if hypothesis.get("endpoint") != "ALL_PRE_REGISTERED_GATES":
                raise ValueError(
                    "hipótese primária deve usar endpoint estruturado "
                    "ALL_PRE_REGISTERED_GATES"
                )
            if hypothesis.get("decision_rule") != "ALL_GATES_PASS":
                raise ValueError(
                    "hipótese primária deve usar decision_rule estruturada ALL_GATES_PASS"
                )
        primary += int(hypothesis["primary"])
    if primary != 1:
        raise ValueError("deve existir exatamente uma hipótese primária")
    return hypotheses


def validate_evaluation_config(config: dict[str, Any]) -> dict[str, Any]:
    """Valida decisões científicas que precisam existir antes do holdout."""

    if config.get("schema_version") != CONFIG_SCHEMA_VERSION:
        raise ValueError(
            f"config.schema_version deve ser {CONFIG_SCHEMA_VERSION!r}"
        )
    require_string(config.get("protocol_id"), "config.protocol_id")
    _validate_hypotheses(config.get("hypotheses"))

    candidate = require_mapping(config.get("candidate"), "config.candidate")
    for field in ("id", "task", "selection_evidence_ref"):
        require_string(candidate.get(field), f"config.candidate.{field}")
    if candidate.get("task") != "deduplication":
        raise ValueError("o módulo confirmatório atual aceita somente deduplication")
    if candidate.get("frozen_no_retraining") is not True:
        raise ValueError("config.candidate.frozen_no_retraining deve ser true")
    if candidate.get("trained_without_holdout") is not True:
        raise ValueError("config.candidate.trained_without_holdout deve ser true")

    metrics = require_list(config.get("metrics"), "config.metrics")
    metric_names = {
        require_string(value, "config.metrics[]").lower() for value in metrics
    }
    required_metrics = {
        "brier",
        "log_loss",
        "ece",
        "risk_coverage",
        "subgroups",
        "critical_errors",
    }
    missing_metrics = sorted(required_metrics - metric_names)
    if missing_metrics:
        raise ValueError(f"métricas confirmatórias ausentes: {missing_metrics}")

    policy = require_mapping(config.get("decision_policy"), "config.decision_policy")
    positive = require_probability(
        policy.get("automatic_duplicate_min_probability"),
        "config.decision_policy.automatic_duplicate_min_probability",
    )
    negative = require_probability(
        policy.get("automatic_nonduplicate_max_probability"),
        "config.decision_policy.automatic_nonduplicate_max_probability",
    )
    if negative >= positive:
        raise ValueError("threshold negativo deve ser menor que o positivo")
    if policy.get("abstain_between_thresholds") is not True:
        raise ValueError("config.decision_policy.abstain_between_thresholds deve ser true")

    analysis = require_mapping(config.get("analysis"), "config.analysis")
    require_probability(analysis.get("confidence"), "config.analysis.confidence", inclusive=False)
    ece_bins = require_positive_int(analysis.get("ece_bins"), "config.analysis.ece_bins")
    if ece_bins < 2 or ece_bins > 100:
        raise ValueError("config.analysis.ece_bins deve estar entre 2 e 100")
    if analysis.get("missing_prediction_policy") != "FAIL_CLOSED":
        raise ValueError("config.analysis.missing_prediction_policy deve ser FAIL_CLOSED")
    if analysis.get("single_confirmatory_execution") is not True:
        raise ValueError("config.analysis.single_confirmatory_execution deve ser true")
    if analysis.get("count_abstention_as_correct") is not False:
        raise ValueError("abstenção não pode ser contada como acerto")

    gates = require_mapping(config.get("gates"), "config.gates")
    require_positive_int(
        gates.get("minimum_independent_families"),
        "config.gates.minimum_independent_families",
    )
    _nonnegative_int(
        gates.get("maximum_technical_failures"),
        "config.gates.maximum_technical_failures",
    )
    require_probability(
        gates.get("minimum_automatic_coverage"),
        "config.gates.minimum_automatic_coverage",
    )
    require_probability(
        gates.get("maximum_selective_risk"),
        "config.gates.maximum_selective_risk",
    )
    require_probability(gates.get("maximum_ece"), "config.gates.maximum_ece")
    require_probability(gates.get("maximum_brier"), "config.gates.maximum_brier")

    subgroup_fields = require_list(config.get("subgroups"), "config.subgroups")
    subgroup_names = {
        require_string(field, "config.subgroups[]") for field in subgroup_fields
    }
    if len(subgroup_names) != len(subgroup_fields):
        raise ValueError("config.subgroups contém campo repetido")

    critical_rules = require_list(
        config.get("critical_errors"), "config.critical_errors"
    )
    rule_ids: set[str] = set()
    for index, raw_rule in enumerate(critical_rules):
        rule = require_mapping(raw_rule, f"config.critical_errors[{index}]")
        rule_id = require_string(rule.get("id"), f"config.critical_errors[{index}].id")
        if rule_id in rule_ids:
            raise ValueError(f"regra crítica repetida: {rule_id}")
        rule_ids.add(rule_id)
        true_label = require_string(
            rule.get("true_label"), f"config.critical_errors[{index}].true_label"
        ).upper()
        predicted_label = require_string(
            rule.get("automatic_predicted_label"),
            f"config.critical_errors[{index}].automatic_predicted_label",
        ).upper()
        if {true_label, predicted_label} - LABELS or true_label == predicted_label:
            raise ValueError(f"regra crítica {rule_id} deve descrever erro binário real")
        maximum_events = _nonnegative_int(
            rule.get("maximum_events"),
            f"config.critical_errors[{index}].maximum_events",
        )
        if maximum_events != 0:
            raise ValueError(
                f"regra crítica {rule_id}: somente gate conservador de zero eventos é aceito"
            )
        confidence = require_probability(
            rule.get("confidence"),
            f"config.critical_errors[{index}].confidence",
            inclusive=False,
        )
        maximum_upper = require_probability(
            rule.get("maximum_upper_exclusive"),
            f"config.critical_errors[{index}].maximum_upper_exclusive",
            inclusive=False,
        )
        minimum = require_positive_int(
            rule.get("minimum_independent_exposures"),
            f"config.critical_errors[{index}].minimum_independent_exposures",
        )
        exact_minimum = tamanho_minimo_zero_eventos(maximum_upper, confidence)
        if minimum < exact_minimum:
            raise ValueError(
                f"regra crítica {rule_id} exige ao menos {exact_minimum} exposições "
                "independentes para o limite estrito pré-especificado"
            )

    approvals = require_mapping(config.get("approvals"), "config.approvals")
    responsible = require_string(
        approvals.get("institutional_responsible_id"),
        "config.approvals.institutional_responsible_id",
    )
    scientific = require_string(
        approvals.get("scientific_reviewer_id"),
        "config.approvals.scientific_reviewer_id",
    )
    if responsible == scientific:
        raise ValueError("aprovação institucional e revisão científica exigem pessoas distintas")
    parse_aware_datetime(approvals.get("approved_at"), "config.approvals.approved_at")
    require_string(approvals.get("approval_ref"), "config.approvals.approval_ref")
    _reject_placeholders(config, "config")
    return config


def _artifact(path: Path, role: str) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"artefato {role} ausente: {resolved}")
    size = resolved.stat().st_size
    if size <= 0:
        raise ValueError(f"artefato {role} vazio: {resolved}")
    return {
        "role": role,
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "bytes": size,
    }


def _validate_dataset_manifest(
    dataset_path: Path,
    manifest_path: Path,
    config: dict[str, Any],
    *,
    exclusions_path: Path | None,
) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    if manifest.get("validation_status") != "PASS":
        raise ValueError("manifesto do registro de famílias não está validado")
    if manifest.get("content_validation_eligible_for_preregistration") is not True:
        raise ValueError("registro não é elegível para pré-registro")
    if manifest.get("confirmatory_evaluation_completed") is not False:
        raise ValueError("manifesto indica avaliação confirmatória já executada")
    manifest_exclusions_sha = manifest.get("exclusions_sha256")
    if manifest_exclusions_sha is not None:
        expected_exclusions_sha = require_sha256(
            manifest_exclusions_sha, "manifest.exclusions_sha256"
        )
        if exclusions_path is None:
            raise ValueError(
                "manifesto foi importado com exclusões; o mesmo arquivo é obrigatório"
            )
        if sha256_file(exclusions_path.resolve()) != expected_exclusions_sha:
            raise ValueError("arquivo de exclusões diverge do usado na importação")
    expected_dataset_sha = require_sha256(
        manifest.get("dataset_sha256"), "manifest.dataset_sha256"
    )
    actual_dataset_sha = sha256_file(dataset_path)
    if expected_dataset_sha != actual_dataset_sha:
        raise ValueError("hash do dataset diverge do manifesto")

    exclusions = load_exclusions(exclusions_path.resolve() if exclusions_path else None)
    summary = validate_registry(load_jsonl(dataset_path), exclusions=exclusions)
    for field in (
        "independent_families",
        "independent_dependency_groups",
        "family_ids_sha256",
    ):
        if manifest.get(field) != summary[field]:
            raise ValueError(f"manifesto diverge do dataset em {field}")

    gates = config["gates"]
    if summary["independent_families"] < gates["minimum_independent_families"]:
        raise ValueError("dataset não alcança o total mínimo pré-especificado")
    for rule in config["critical_errors"]:
        label = str(rule["true_label"]).upper()
        count = int(summary["label_counts"].get(label, 0))
        if count < int(rule["minimum_independent_exposures"]):
            raise ValueError(
                f"regra crítica {rule['id']} possui {count} exposições elegíveis; "
                f"mínimo pré-especificado={rule['minimum_independent_exposures']}"
            )
    return summary


def criar_rascunho(
    *,
    evaluation_config_path: Path,
    dataset_path: Path,
    dataset_manifest_path: Path,
    candidate_artifact_path: Path,
    output_path: Path,
    exclusions_path: Path | None = None,
) -> dict[str, Any]:
    """Materializa rascunho auditável sem abrir nem executar o holdout."""

    paths = [
        evaluation_config_path.resolve(),
        dataset_path.resolve(),
        dataset_manifest_path.resolve(),
        candidate_artifact_path.resolve(),
    ]
    if len(set(paths)) != len(paths):
        raise ValueError("config, dataset, manifesto e candidato devem ser arquivos distintos")
    if output_path.resolve() in set(paths):
        raise ValueError("rascunho deve ser distinto dos artefatos de entrada")
    config = validate_evaluation_config(load_json(evaluation_config_path.resolve()))
    summary = _validate_dataset_manifest(
        dataset_path.resolve(),
        dataset_manifest_path.resolve(),
        config,
        exclusions_path=exclusions_path,
    )
    artifacts = {
        "dataset": _artifact(dataset_path, "holdout_dataset"),
        "dataset_manifest": _artifact(dataset_manifest_path, "holdout_dataset_manifest"),
        "candidate": _artifact(candidate_artifact_path, "frozen_candidate"),
        "evaluation_config": _artifact(evaluation_config_path, "evaluation_config"),
    }
    if exclusions_path:
        artifacts["development_exclusions"] = _artifact(
            exclusions_path, "development_exclusions"
        )
    # Falha se qualquer entrada mudar durante a criação do rascunho.
    if load_json(evaluation_config_path.resolve()) != config:
        raise ValueError("configuração mudou durante a criação do rascunho")
    if sha256_file(dataset_path.resolve()) != artifacts["dataset"]["sha256"]:
        raise ValueError("dataset mudou durante a criação do rascunho")
    if sha256_file(dataset_manifest_path.resolve()) != artifacts["dataset_manifest"]["sha256"]:
        raise ValueError("manifesto mudou durante a criação do rascunho")
    draft: dict[str, Any] = {
        "schema_version": PREREGISTRATION_SCHEMA_VERSION,
        "status": "DRAFT_NOT_FROZEN",
        "created_at": utc_now(),
        "protocol_id": config["protocol_id"],
        "artifacts": artifacts,
        "dataset_summary": summary,
        "candidate": copy.deepcopy(config["candidate"]),
        "hypotheses": copy.deepcopy(config["hypotheses"]),
        "metrics": copy.deepcopy(config["metrics"]),
        "decision_policy": copy.deepcopy(config["decision_policy"]),
        "analysis": copy.deepcopy(config["analysis"]),
        "gates": copy.deepcopy(config["gates"]),
        "subgroups": copy.deepcopy(config["subgroups"]),
        "critical_errors": copy.deepcopy(config["critical_errors"]),
        "approvals": copy.deepcopy(config["approvals"]),
        "holdout_policy": {
            "open_at_most_once": True,
            "execute_at_most_once": True,
            "ledger_reservation_precedes_dataset_read_during_evaluation": True,
            "failed_or_interrupted_attempt_consumes_the_only_execution": True,
            "candidate_change_after_freeze_forbidden": True,
        },
        "scientific_result": False,
    }
    draft["contract_sha256"] = _contract_seal(draft)
    exclusive_write_json(output_path.resolve(), draft)
    return draft


def _verify_contract_and_artifacts(
    document: dict[str, Any], *, frozen: bool, verify_artifacts: bool = True
) -> None:
    expected = require_sha256(document.get("contract_sha256"), "contract_sha256")
    if expected != _contract_seal(document):
        raise ValueError("pré-registro adulterado: selo do contrato não confere")
    expected_status = FROZEN_STATUS if frozen else "DRAFT_NOT_FROZEN"
    if document.get("status") != expected_status:
        raise ValueError(f"status esperado={expected_status!r}")
    if document.get("schema_version") != PREREGISTRATION_SCHEMA_VERSION:
        raise ValueError("versão de schema do pré-registro inválida")
    _reject_placeholders(document, "preregistration")
    if not verify_artifacts:
        return
    artifacts = require_mapping(document.get("artifacts"), "artifacts")
    required_roles = {"dataset", "dataset_manifest", "candidate", "evaluation_config"}
    if required_roles - set(artifacts):
        raise ValueError("pré-registro não contém todos os artefatos obrigatórios")
    for name, raw_artifact in artifacts.items():
        artifact = require_mapping(raw_artifact, f"artifacts.{name}")
        path = Path(require_string(artifact.get("path"), f"artifacts.{name}.path"))
        expected_sha = require_sha256(
            artifact.get("sha256"), f"artifacts.{name}.sha256"
        )
        if not path.is_file() or sha256_file(path) != expected_sha:
            raise ValueError(f"artefato adulterado ou ausente: {name}")
        if path.stat().st_size != artifact.get("bytes"):
            raise ValueError(f"tamanho do artefato diverge: {name}")


def congelar_preregistro(*, draft_path: Path, output_path: Path) -> dict[str, Any]:
    """Congela o contrato uma única vez; o arquivo de saída nunca é sobrescrito."""

    draft_path = draft_path.resolve()
    output_path = output_path.resolve()
    if draft_path == output_path:
        raise ValueError("rascunho e pré-registro congelado devem ser distintos")
    draft = load_json(draft_path)
    _verify_contract_and_artifacts(draft, frozen=False)
    approved_at = parse_aware_datetime(
        draft["approvals"]["approved_at"], "approvals.approved_at"
    )
    frozen_at_text = utc_now()
    frozen_at = parse_aware_datetime(frozen_at_text, "frozen_at")
    if approved_at > frozen_at:
        raise ValueError("aprovação não pode estar no futuro em relação ao congelamento")
    frozen = copy.deepcopy(draft)
    frozen["status"] = FROZEN_STATUS
    frozen["frozen_at"] = frozen_at_text
    frozen["source_draft_sha256"] = sha256_file(draft_path)
    dataset_path = Path(frozen["artifacts"]["dataset"]["path"])
    dataset_prefix = frozen["artifacts"]["dataset"]["sha256"][:16]
    frozen["execution_control"] = {
        "dataset_bound": True,
        "ledger_path": str(
            dataset_path.with_name(
                f".{dataset_path.name}.{dataset_prefix}.confirmatory-ledger.json"
            )
        ),
        "result_path": str(
            dataset_path.with_name(
                f".{dataset_path.name}.{dataset_prefix}.confirmatory-result.json"
            )
        ),
        "prediction_claim_path": str(
            dataset_path.with_name(
                f".{dataset_path.name}.{dataset_prefix}.confirmatory-prediction-claim.json"
            )
        ),
        "registered_predictions_path": str(
            dataset_path.with_name(
                f".{dataset_path.name}.{dataset_prefix}.confirmatory-registered-predictions.json"
            )
        ),
        "any_started_attempt_consumes_holdout": True,
    }
    frozen["scientific_result"] = False
    frozen["contract_sha256"] = _contract_seal(frozen)
    exclusive_write_json(output_path, frozen)
    return frozen


def verificar_preregistro_congelado(path: Path) -> dict[str, Any]:
    document = load_json(path.resolve())
    _verify_contract_and_artifacts(document, frozen=True)
    config = validate_evaluation_config(
        load_json(Path(document["artifacts"]["evaluation_config"]["path"]))
    )
    if config["protocol_id"] != document["protocol_id"]:
        raise ValueError("protocol_id diverge entre config e pré-registro")
    for field in (
        "candidate",
        "hypotheses",
        "metrics",
        "decision_policy",
        "analysis",
        "gates",
        "subgroups",
        "critical_errors",
        "approvals",
    ):
        if config[field] != document[field]:
            raise ValueError(f"configuração congelada diverge em {field}")
    dataset_manifest = load_json(Path(document["artifacts"]["dataset_manifest"]["path"]))
    if dataset_manifest.get("dataset_sha256") != document["artifacts"]["dataset"]["sha256"]:
        raise ValueError("manifesto e hash congelado do dataset divergem")
    return document


def carregar_preregistro_selado_sem_abrir_artefatos(path: Path) -> dict[str, Any]:
    """Verifica apenas o contrato para permitir reservar antes de ler o holdout."""

    document = load_json(path.resolve())
    _verify_contract_and_artifacts(document, frozen=True, verify_artifacts=False)
    return document


# Aliases em inglês para integração por biblioteca sem duplicar a implementação.
create_draft = criar_rascunho
freeze_preregistration = congelar_preregistro
verify_frozen_preregistration = verificar_preregistro_congelado
