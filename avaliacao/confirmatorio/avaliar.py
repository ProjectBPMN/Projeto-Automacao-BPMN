from __future__ import annotations

import copy
import math
import uuid
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .amostra import clopper_pearson_upper_unilateral
from .familias import LABELS, validate_registry
from .preregistro import (
    carregar_preregistro_selado_sem_abrir_artefatos,
    verificar_preregistro_congelado,
)
from .util import (
    atomic_replace_json,
    canonical_json_bytes,
    exclusive_write_bytes,
    exclusive_write_json,
    load_json,
    load_json_bytes,
    load_jsonl_bytes,
    parse_aware_datetime,
    require_list,
    require_mapping,
    require_probability,
    require_sha256,
    require_string,
    sha256_bytes,
    sha256_file,
    utc_now,
)


PREDICTIONS_SCHEMA_VERSION = "confirmatory-predictions-v1"
LEDGER_SCHEMA_VERSION = "confirmatory-one-shot-ledger-v1"
RESULT_SCHEMA_VERSION = "confirmatory-evaluation-result-v1"


def _seal(document: dict[str, Any]) -> str:
    value = copy.deepcopy(document)
    value.pop("contract_sha256", None)
    return sha256_bytes(canonical_json_bytes(value))


def _sealed(document: dict[str, Any]) -> dict[str, Any]:
    output = copy.deepcopy(document)
    output["contract_sha256"] = _seal(output)
    return output


def _verify_seal(document: dict[str, Any], context: str) -> None:
    expected = require_sha256(document.get("contract_sha256"), f"{context}.contract_sha256")
    if expected != _seal(document):
        raise ValueError(f"{context} adulterado: selo não confere")


def _load_prediction_bundle(
    bundle: dict[str, Any],
    *,
    preregistration: dict[str, Any],
    preregistration_sha256: str,
    reservation: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if bundle.get("schema_version") != PREDICTIONS_SCHEMA_VERSION:
        raise ValueError(f"predictions.schema_version deve ser {PREDICTIONS_SCHEMA_VERSION!r}")
    bindings = {
        "protocol_id": preregistration["protocol_id"],
        "preregistration_sha256": preregistration_sha256,
        "dataset_sha256": preregistration["artifacts"]["dataset"]["sha256"],
        "candidate_sha256": preregistration["artifacts"]["candidate"]["sha256"],
        "attempt_id": reservation["attempt_id"],
        "reservation_contract_sha256": reservation["contract_sha256"],
    }
    for field, expected in bindings.items():
        if bundle.get(field) != expected:
            raise ValueError(f"predictions.{field} não corresponde ao pré-registro congelado")
    generated_at = parse_aware_datetime(bundle.get("generated_at"), "predictions.generated_at")
    ready_at = parse_aware_datetime(reservation.get("ready_at"), "ledger.ready_at")
    if generated_at < ready_at:
        raise ValueError("predições são anteriores à reserva one-shot do holdout")
    require_string(bundle.get("candidate_execution_id"), "predictions.candidate_execution_id")
    rows = require_list(bundle.get("predictions"), "predictions.predictions")
    output: dict[str, dict[str, Any]] = {}
    for index, raw_row in enumerate(rows):
        row = require_mapping(raw_row, f"predictions.predictions[{index}]")
        family_id = require_string(row.get("family_id"), f"predictions[{index}].family_id")
        if family_id in output:
            raise ValueError(f"predição duplicada para family_id={family_id}")
        status = require_string(row.get("status"), f"predictions[{index}].status").upper()
        if status == "OK":
            probability = require_probability(
                row.get("duplicate_probability"),
                f"predictions[{index}].duplicate_probability",
            )
            output[family_id] = {
                "family_id": family_id,
                "status": status,
                "duplicate_probability": probability,
            }
        elif status == "TECHNICAL_FAILURE":
            if row.get("duplicate_probability") is not None:
                raise ValueError("falha técnica não pode transportar probabilidade aproveitável")
            output[family_id] = {
                "family_id": family_id,
                "status": status,
                "duplicate_probability": None,
                "error_code": require_string(
                    row.get("error_code"), f"predictions[{index}].error_code"
                ),
            }
        else:
            raise ValueError(f"status de predição inválido: {status}")
    return output


def _decision(probability: float, policy: dict[str, Any]) -> str:
    if probability >= float(policy["automatic_duplicate_min_probability"]):
        return "DUPLICADO"
    if probability <= float(policy["automatic_nonduplicate_max_probability"]):
        return "NAO_DUPLICADO"
    return "ABSTAIN"


def _calibration(scored: list[dict[str, Any]], bins: int) -> dict[str, Any]:
    if not scored:
        return {
            "denominator": 0,
            "brier": None,
            "log_loss": None,
            "ece": None,
            "bins": [],
        }
    epsilon = 1e-15
    brier_sum = 0.0
    loss_sum = 0.0
    bucket_rows: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    for row in scored:
        probability = float(row["probability"])
        truth = int(row["truth"] == "DUPLICADO")
        brier_sum += (probability - truth) ** 2
        clipped = min(1.0 - epsilon, max(epsilon, probability))
        loss_sum += -(truth * math.log(clipped) + (1 - truth) * math.log(1 - clipped))
        bin_index = min(bins - 1, int(probability * bins))
        bucket_rows[bin_index].append((probability, truth))
    n = len(scored)
    ece = 0.0
    details: list[dict[str, Any]] = []
    for index, bucket in enumerate(bucket_rows):
        count = len(bucket)
        mean_probability = sum(item[0] for item in bucket) / count if count else None
        event_rate = sum(item[1] for item in bucket) / count if count else None
        absolute_gap = (
            abs(float(mean_probability) - float(event_rate)) if count else None
        )
        if count:
            ece += count / n * float(absolute_gap)
        details.append(
            {
                "index": index,
                "lower_inclusive": index / bins,
                "upper_inclusive_if_last": (index + 1) / bins,
                "count": count,
                "mean_probability": mean_probability,
                "event_rate": event_rate,
                "absolute_gap": absolute_gap,
            }
        )
    return {
        "denominator": n,
        "brier": brier_sum / n,
        "log_loss": loss_sum / n,
        "ece": ece,
        "bins": details,
    }


def _selective_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    automatic = [row for row in rows if row["decision"] in LABELS]
    errors = [row for row in automatic if row["decision"] != row["truth"]]
    abstentions = sum(row["decision"] == "ABSTAIN" for row in rows)
    technical = sum(row["decision"] == "TECHNICAL_FAILURE" for row in rows)
    return {
        "total_independent_families": total,
        "automatic_decisions": len(automatic),
        "automatic_errors": len(errors),
        "abstentions": abstentions,
        "technical_failures": technical,
        "automatic_coverage": len(automatic) / total if total else None,
        "selective_risk": len(errors) / len(automatic) if automatic else None,
        "overall_correct_fraction_abstention_and_failure_incorrect": (
            (len(automatic) - len(errors)) / total if total else None
        ),
    }


def _risk_coverage_curve(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = [row for row in rows if row["probability"] is not None]
    total = len(rows)
    curve: list[dict[str, Any]] = []
    # Grade fixa, independente dos resultados, para evitar escolha pós-hoc do limiar.
    for step in range(50, 101, 5):
        threshold = step / 100
        covered = [
            row
            for row in scored
            if max(float(row["probability"]), 1.0 - float(row["probability"])) >= threshold
        ]
        errors = sum(
            ("DUPLICADO" if float(row["probability"]) >= 0.5 else "NAO_DUPLICADO")
            != row["truth"]
            for row in covered
        )
        curve.append(
            {
                "confidence_threshold": threshold,
                "coverage": len(covered) / total if total else None,
                "risk": errors / len(covered) if covered else None,
                "covered": len(covered),
                "errors": errors,
            }
        )
    return curve


def _subgroup_metrics(
    rows: list[dict[str, Any]], subgroup_fields: list[str], bins: int
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for field in subgroup_fields:
        partitions: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            value = row["subgroups"].get(field)
            if value is None:
                raise ValueError(f"subgrupo pré-especificado ausente no dataset: {field}")
            partitions[str(value)].append(row)
        output[field] = {}
        for value, subset in sorted(partitions.items()):
            scored = [row for row in subset if row["probability"] is not None]
            output[field][value] = {
                **_selective_metrics(subset),
                "calibration": _calibration(scored, bins),
                "descriptive_only": True,
            }
    return output


def _critical_errors(
    rows: list[dict[str, Any]], rules: list[dict[str, Any]]
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for rule in rules:
        true_label = str(rule["true_label"]).upper()
        target = str(rule["automatic_predicted_label"]).upper()
        exposures = [
            row for row in rows if row["truth"] == true_label and row["decision"] in LABELS
        ]
        events = sum(row["decision"] == target for row in exposures)
        upper = (
            clopper_pearson_upper_unilateral(
                events, len(exposures), float(rule["confidence"])
            )
            if exposures
            else None
        )
        output[str(rule["id"])] = {
            "true_label": true_label,
            "automatic_predicted_label": target,
            "independent_exposures": len(exposures),
            "events": events,
            "rate": events / len(exposures) if exposures else None,
            "clopper_pearson_upper_unilateral": upper,
            "confidence": rule["confidence"],
            "minimum_independent_exposures": rule["minimum_independent_exposures"],
            "maximum_events": rule["maximum_events"],
            "maximum_upper_exclusive": rule["maximum_upper_exclusive"],
        }
    return output


def _evaluate_gates(
    preregistration: dict[str, Any],
    selective: dict[str, Any],
    calibration: dict[str, Any],
    critical: dict[str, Any],
) -> list[dict[str, Any]]:
    gates = preregistration["gates"]
    checks = [
        ("minimum_independent_families", selective["total_independent_families"] >= gates["minimum_independent_families"], selective["total_independent_families"], f">={gates['minimum_independent_families']}"),
        ("maximum_technical_failures", selective["technical_failures"] <= gates["maximum_technical_failures"], selective["technical_failures"], f"<={gates['maximum_technical_failures']}"),
        ("minimum_automatic_coverage", selective["automatic_coverage"] is not None and selective["automatic_coverage"] >= gates["minimum_automatic_coverage"], selective["automatic_coverage"], f">={gates['minimum_automatic_coverage']}"),
        ("maximum_selective_risk", selective["selective_risk"] is not None and selective["selective_risk"] <= gates["maximum_selective_risk"], selective["selective_risk"], f"<={gates['maximum_selective_risk']}"),
        ("maximum_ece", calibration["ece"] is not None and calibration["ece"] <= gates["maximum_ece"], calibration["ece"], f"<={gates['maximum_ece']}"),
        ("maximum_brier", calibration["brier"] is not None and calibration["brier"] <= gates["maximum_brier"], calibration["brier"], f"<={gates['maximum_brier']}"),
    ]
    output = [
        {"id": gate_id, "passed": bool(passed), "observed": observed, "rule": rule}
        for gate_id, passed, observed, rule in checks
    ]
    for rule in preregistration["critical_errors"]:
        metric = critical[str(rule["id"])]
        upper = metric["clopper_pearson_upper_unilateral"]
        critical_pass = (
            metric["events"] <= rule["maximum_events"]
            and metric["independent_exposures"] >= rule["minimum_independent_exposures"]
            and upper is not None
            and upper < rule["maximum_upper_exclusive"]
        )
        output.append(
            {
                "id": f"critical::{rule['id']}",
                "passed": bool(critical_pass),
                "observed": metric,
                "rule": "events<=maximum, exposures>=minimum e upper unilateral estritamente menor que o gate",
            }
        )
    return output


def _execution_paths(
    preregistration: dict[str, Any]
) -> tuple[Path, Path, Path, Path]:
    control = require_mapping(preregistration.get("execution_control"), "execution_control")
    if control.get("dataset_bound") is not True or control.get("any_started_attempt_consumes_holdout") is not True:
        raise ValueError("controle one-shot do pré-registro é inválido")
    return (
        Path(require_string(control.get("ledger_path"), "execution_control.ledger_path")),
        Path(require_string(control.get("result_path"), "execution_control.result_path")),
        Path(
            require_string(
                control.get("prediction_claim_path"),
                "execution_control.prediction_claim_path",
            )
        ),
        Path(
            require_string(
                control.get("registered_predictions_path"),
                "execution_control.registered_predictions_path",
            )
        ),
    )


def status_execucao(preregistration_path: Path) -> dict[str, Any]:
    preregistration = carregar_preregistro_selado_sem_abrir_artefatos(
        preregistration_path
    )
    ledger_path, result_path, claim_path, registered_path = _execution_paths(
        preregistration
    )
    if not ledger_path.exists():
        if result_path.exists() or claim_path.exists() or registered_path.exists():
            raise ValueError("estado fail-closed: artefato de execução existe sem ledger")
        return {
            "status": "NOT_RESERVED",
            "ledger_path": str(ledger_path),
            "result_path": str(result_path),
            "prediction_claim_path": str(claim_path),
            "registered_predictions_path": str(registered_path),
        }
    ledger = load_json(ledger_path)
    _verify_seal(ledger, "ledger")
    if ledger.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise ValueError("schema do ledger inválido")
    if ledger.get("dataset_sha256") != preregistration["artifacts"]["dataset"]["sha256"]:
        raise ValueError("ledger pertence a outro dataset")
    state = require_string(ledger.get("state"), "ledger.state")
    if state == "COMPLETED":
        if not result_path.is_file() or sha256_file(result_path) != ledger.get("result_sha256"):
            raise ValueError("resultado final ausente ou adulterado")
        if (
            not registered_path.is_file()
            or sha256_file(registered_path) != ledger.get("predictions_sha256")
        ):
            raise ValueError("bundle registrado ausente ou adulterado")
    elif result_path.exists():
        raise ValueError("resultado existe para ledger não concluído")
    if claim_path.exists():
        claim = load_json(claim_path)
        _verify_seal(claim, "prediction_claim")
        if claim.get("attempt_id") != ledger.get("attempt_id"):
            raise ValueError("claim de predições pertence a outra reserva")
    return ledger


def reservar_abertura_confirmatoria(
    *, preregistration_path: Path, confirm_irreversible_open: bool
) -> dict[str, Any]:
    """Reserva atomicamente antes de validar/ler qualquer artefato do holdout."""

    if confirm_irreversible_open is not True:
        raise PermissionError("confirmação explícita da abertura irreversível é obrigatória")
    preregistration_path = preregistration_path.resolve()
    # Esta leitura verifica somente o contrato; dataset/candidato ainda não são lidos.
    sealed = carregar_preregistro_selado_sem_abrir_artefatos(preregistration_path)
    ledger_path, result_path, claim_path, registered_path = _execution_paths(sealed)
    if (
        ledger_path.exists()
        or result_path.exists()
        or claim_path.exists()
        or registered_path.exists()
    ):
        status_execucao(preregistration_path)
        raise RuntimeError("holdout já foi reservado; nova abertura bloqueada")
    preregistration_sha = sha256_file(preregistration_path)
    started = _sealed(
        {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "state": "RESERVATION_STARTED",
            "attempt_id": uuid.uuid4().hex,
            "started_at": utc_now(),
            "preregistration_path": str(preregistration_path),
            "preregistration_sha256": preregistration_sha,
            "dataset_sha256": sealed["artifacts"]["dataset"]["sha256"],
            "candidate_sha256": sealed["artifacts"]["candidate"]["sha256"],
            "holdout_open_consumed": True,
        }
    )
    # O_EXCL ocorre antes da primeira leitura/hash do dataset ou candidato.
    exclusive_write_json(ledger_path, started)
    try:
        verified = verificar_preregistro_congelado(preregistration_path)
        if verified["contract_sha256"] != sealed["contract_sha256"]:
            raise ValueError("pré-registro mudou durante a reserva")
        ready = _sealed(
            {
                **{key: value for key, value in started.items() if key != "contract_sha256"},
                "state": "RESERVED_READY_FOR_BLINDED_INFERENCE",
                "ready_at": utc_now(),
                "artifact_integrity_verified": True,
            }
        )
        atomic_replace_json(ledger_path, ready)
        return ready
    except Exception as exc:
        failed = _sealed(
            {
                **{key: value for key, value in started.items() if key != "contract_sha256"},
                "state": "FAILED_RESERVATION_CONSUMED",
                "failed_at": utc_now(),
                "failure_type": type(exc).__name__,
                "failure_message": str(exc),
            }
        )
        try:
            atomic_replace_json(ledger_path, failed)
        finally:
            raise


def executar_avaliacao_confirmatoria(
    *,
    preregistration_path: Path,
    predictions_path: Path,
    confirm_predictions_registration_once: bool,
) -> dict[str, Any]:
    """Registra predições da reserva e avalia uma única vez.

    ``reservar_abertura_confirmatoria`` deve ter sido chamada antes de qualquer
    inferência. O claim exclusivo é criado antes de ler o bundle; erro ou
    interrupção consome a única tentativa de registro/avaliação.
    """

    if confirm_predictions_registration_once is not True:
        raise PermissionError("confirmação explícita do registro one-shot é obrigatória")
    preregistration_path = preregistration_path.resolve()
    predictions_path = predictions_path.resolve()
    preregistration = carregar_preregistro_selado_sem_abrir_artefatos(
        preregistration_path
    )
    ledger_path, result_path, claim_path, registered_path = _execution_paths(
        preregistration
    )
    if not ledger_path.is_file():
        raise RuntimeError("holdout ainda não foi reservado; inferência não autorizada")
    reservation = load_json(ledger_path)
    _verify_seal(reservation, "ledger")
    if reservation.get("state") != "RESERVED_READY_FOR_BLINDED_INFERENCE":
        raise RuntimeError("reserva não está disponível para registrar predições")
    if result_path.exists() or claim_path.exists() or registered_path.exists():
        status_execucao(preregistration_path)
        raise RuntimeError("predições já foram registradas; repetição bloqueada")
    attempt_id = str(reservation["attempt_id"])
    preregistration_sha = sha256_file(preregistration_path)
    claim = _sealed(
        {
            "schema_version": "confirmatory-prediction-claim-v1",
            "attempt_id": attempt_id,
            "claimed_at": utc_now(),
            "preregistration_sha256": preregistration_sha,
            "predictions_path": str(predictions_path),
            "registration_consumed": True,
        }
    )
    # O_EXCL impede duas avaliações concorrentes e ocorre antes de ler o bundle.
    exclusive_write_json(claim_path, claim)
    try:
        if reservation.get("preregistration_sha256") != preregistration_sha:
            raise ValueError("pré-registro foi substituído após a reserva")
        if reservation.get("dataset_sha256") != preregistration["artifacts"]["dataset"]["sha256"]:
            raise ValueError("dataset congelado diverge da reserva")
        if reservation.get("candidate_sha256") != preregistration["artifacts"]["candidate"]["sha256"]:
            raise ValueError("candidato congelado diverge da reserva")
        if not predictions_path.is_file():
            raise ValueError(f"bundle de predições ausente: {predictions_path}")
        preregistration = verificar_preregistro_congelado(preregistration_path)
        dataset_path = Path(preregistration["artifacts"]["dataset"]["path"])
        dataset_payload = dataset_path.read_bytes()
        if sha256_bytes(dataset_payload) != preregistration["artifacts"]["dataset"]["sha256"]:
            raise ValueError("dataset mudou durante a avaliação")
        families = load_jsonl_bytes(dataset_payload, str(dataset_path))
        validate_registry(families)
        prediction_payload = predictions_path.read_bytes()
        predictions_sha = sha256_bytes(prediction_payload)
        # Preserva exatamente a primeira tentativa, antes de analisar seu conteúdo.
        exclusive_write_bytes(registered_path, prediction_payload)
        prediction_bundle = load_json_bytes(prediction_payload, str(predictions_path))
        predictions = _load_prediction_bundle(
            prediction_bundle,
            preregistration=preregistration,
            preregistration_sha256=preregistration_sha,
            reservation=reservation,
        )
        family_by_id = {str(row["family_id"]): row for row in families}
        missing = sorted(set(family_by_id) - set(predictions))
        unexpected = sorted(set(predictions) - set(family_by_id))
        if missing or unexpected:
            raise ValueError(
                f"predições não correspondem 1:1 ao holdout; missing={missing[:5]}, "
                f"unexpected={unexpected[:5]}"
            )

        evaluation_rows: list[dict[str, Any]] = []
        policy = preregistration["decision_policy"]
        for family_id in sorted(family_by_id):
            family = family_by_id[family_id]
            prediction = predictions[family_id]
            probability = prediction["duplicate_probability"]
            decision = (
                _decision(float(probability), policy)
                if probability is not None
                else "TECHNICAL_FAILURE"
            )
            evaluation_rows.append(
                {
                    "family_id": family_id,
                    "truth": str(family["adjudication"]["final_label"]).upper(),
                    "probability": probability,
                    "decision": decision,
                    "status": prediction["status"],
                    "subgroups": copy.deepcopy(family["subgroups"]),
                }
            )

        bins = int(preregistration["analysis"]["ece_bins"])
        scored = [row for row in evaluation_rows if row["probability"] is not None]
        calibration = _calibration(scored, bins)
        selective = _selective_metrics(evaluation_rows)
        critical = _critical_errors(evaluation_rows, preregistration["critical_errors"])
        subgroups = _subgroup_metrics(evaluation_rows, preregistration["subgroups"], bins)
        gate_results = _evaluate_gates(preregistration, selective, calibration, critical)
        gates_passed = all(item["passed"] for item in gate_results)
        technical_failures = Counter(
            predictions[row["family_id"]].get("error_code", "NONE")
            for row in evaluation_rows
            if row["status"] == "TECHNICAL_FAILURE"
        )
        result = _sealed(
            {
                "schema_version": RESULT_SCHEMA_VERSION,
                "completed_at": utc_now(),
                "protocol_id": preregistration["protocol_id"],
                "attempt_id": attempt_id,
                "reservation_contract_sha256": reservation["contract_sha256"],
                "prediction_claim_sha256": sha256_file(claim_path),
                "preregistration_sha256": preregistration_sha,
                "dataset_sha256": preregistration["artifacts"]["dataset"]["sha256"],
                "candidate_sha256": preregistration["artifacts"]["candidate"]["sha256"],
                "predictions_sha256": predictions_sha,
                "confirmatory_status": "PASS" if gates_passed else "FAIL",
                "pre_registered_gates_passed": gates_passed,
                "confirmatory_claim_supported": gates_passed,
                "single_execution_consumed": True,
                "calibration": calibration,
                "selective_operation": selective,
                "risk_coverage_curve": _risk_coverage_curve(evaluation_rows),
                "subgroups": subgroups,
                "critical_errors": critical,
                "technical_failure_codes": dict(sorted(technical_failures.items())),
                "gate_results": gate_results,
                "limitations": [
                    "Subgrupos são descritivos salvo hipótese inferencial explicitamente pré-registrada.",
                    "Um PASS sustenta somente os endpoints, gates, candidato e população congelados.",
                    "Hashes detectam alteração acidental; prova contra agente malicioso exige registro externo assinado.",
                ],
            }
        )
        exclusive_write_json(result_path, result)
        completed = _sealed(
            {
                **{
                    key: value
                    for key, value in reservation.items()
                    if key != "contract_sha256"
                },
                "state": "COMPLETED",
                "completed_at": utc_now(),
                "result_path": str(result_path),
                "result_sha256": sha256_file(result_path),
                "registered_predictions_path": str(registered_path),
                "predictions_sha256": predictions_sha,
                "confirmatory_status": result["confirmatory_status"],
            }
        )
        atomic_replace_json(ledger_path, completed)
        return result
    except Exception as exc:
        failed = _sealed(
            {
                **{
                    key: value
                    for key, value in reservation.items()
                    if key != "contract_sha256"
                },
                "state": "FAILED_PREDICTIONS_CONSUMED",
                "failed_at": utc_now(),
                "failure_type": type(exc).__name__,
                "failure_message": str(exc),
            }
        )
        try:
            atomic_replace_json(ledger_path, failed)
        finally:
            raise


execute_confirmatory_evaluation = executar_avaliacao_confirmatoria
reserve_confirmatory_opening = reservar_abertura_confirmatoria
execution_status = status_execucao
