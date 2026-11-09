"""Núcleo do piloto em sombra.

Este módulo deliberadamente só conhece SQLite. Ele não importa clientes HTTP,
GLPI, n8n ou PostgreSQL e não contém uma interface para aplicar recomendações.
Uma confirmação humana representa apenas um rótulo de pesquisa confirmado.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 1
ZERO_HASH = "0" * 64
RELEASE_ACKNOWLEDGEMENT = "SHADOW_ONLY_NO_GLPI_MUTATION"
NO_EXTERNAL_MUTATION_CAPABILITY = True
RESEARCH_EXPORT_PURPOSE = "research_evaluation_only"

CLASSIFICATION_LABELS = frozenset({"OBRA", "DEMO", "SOB_DEMANDA", "TRIAGEM_MANUAL"})
DEDUPLICATION_LABELS = frozenset({"DUPLICADO", "NAO_DUPLICADO"})
OPEN_STATES = frozenset({"PENDING_REVIEW", "PENDING_CONFIRMATION", "PENDING_ADJUDICATION"})
TERMINAL_STATES = frozenset({"CONFIRMED", "REJECTED", "ROLLED_BACK"})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ShadowPilotError(RuntimeError):
    """Erro base do piloto em sombra."""


class ValidationError(ShadowPilotError):
    """Entrada não atende ao contrato local."""


class InvalidTransition(ShadowPilotError):
    """Transição de estado proibida."""


class KillSwitchEngaged(ShadowPilotError):
    """Operação de revisão bloqueada pelo kill switch."""


class IdempotencyConflict(ShadowPilotError):
    """A mesma chave foi reapresentada com outro conteúdo."""


class AuditIntegrityError(ShadowPilotError):
    """A cadeia de auditoria não pôde ser validada."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError("Valor não pode ser serializado de forma canônica") from exc


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_text(name: str, value: str, *, minimum: int = 1, maximum: int = 4000) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{name} deve ser texto")
    clean = value.strip()
    if len(clean) < minimum or len(clean) > maximum:
        raise ValidationError(f"{name} deve ter entre {minimum} e {maximum} caracteres")
    if any(ord(char) < 32 and char not in "\t\n\r" for char in clean):
        raise ValidationError(f"{name} contém caracteres de controle")
    return clean


def _require_sha256(name: str, value: str) -> str:
    clean = _require_text(name, value, minimum=64, maximum=64).lower()
    if not SHA256_RE.fullmatch(clean):
        raise ValidationError(f"{name} deve ser um SHA-256 hexadecimal de 64 caracteres")
    return clean


def _require_confidence(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError("prediction_confidence deve ser numérica")
    confidence = float(value)
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise ValidationError("prediction_confidence deve estar entre 0 e 1")
    return confidence


def _labels_for_task(task: str) -> frozenset[str]:
    if task == "classification":
        return CLASSIFICATION_LABELS
    if task == "deduplication":
        return DEDUPLICATION_LABELS
    raise ValidationError("task deve ser classification ou deduplication")


def _require_label(task: str, label: str) -> str:
    clean = _require_text("label", label, maximum=64).upper()
    if clean not in _labels_for_task(task):
        allowed = ", ".join(sorted(_labels_for_task(task)))
        raise ValidationError(f"Rótulo inválido para {task}; permitidos: {allowed}")
    return clean


class ShadowPilot:
    """Fila transacional de sombra com dupla revisão e auditoria encadeada."""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database).resolve()
        if not self.database.is_file():
            raise ShadowPilotError(
                "Banco do piloto não inicializado; execute o comando init explicitamente"
            )
        with self._connection() as connection:
            self._validate_schema(connection)
            self._verify_audit(connection)

    @classmethod
    def initialize(
        cls,
        database: str | Path,
        *,
        actor_id: str,
        reason: str = "Inicialização segura: kill switch ligado",
    ) -> "ShadowPilot":
        path = Path(database).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        actor = _require_text("actor_id", actor_id, maximum=128)
        clean_reason = _require_text("reason", reason, minimum=3)
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        connection = sqlite3.connect(path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            connection.executescript(schema)
            row = connection.execute(
                "SELECT schema_version FROM schema_meta WHERE singleton_id = 1"
            ).fetchone()
            if row is None:
                now = _now()
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute(
                        "INSERT INTO schema_meta(singleton_id, schema_version, created_at) VALUES(1, ?, ?)",
                        (SCHEMA_VERSION, now),
                    )
                    connection.execute(
                        """
                        INSERT INTO controls(
                            singleton_id, kill_switch_enabled, reason, actor_id, updated_at,
                            audit_head_hash, audit_event_count
                        ) VALUES(1, 1, ?, ?, ?, ?, 0)
                        """,
                        (clean_reason, actor, now, ZERO_HASH),
                    )
                    cls._append_audit_static(
                        connection,
                        case_id=None,
                        actor_id=actor,
                        event_type="PILOT_INITIALIZED_FAIL_CLOSED",
                        details={
                            "kill_switch_enabled": True,
                            "schema_version": SCHEMA_VERSION,
                            "external_mutation_capability": False,
                        },
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
            elif int(row["schema_version"]) != SCHEMA_VERSION:
                raise ShadowPilotError("Versão de schema incompatível")
        finally:
            connection.close()
        if os.name != "nt":
            path.chmod(0o600)
        return cls(path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Fecha explicitamente a conexão; o context manager do sqlite não fecha."""

        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._validate_schema(connection)
            self._verify_audit(connection)
            yield connection
            # Nenhuma operação é confirmada se tiver quebrado o ledger.
            self._verify_audit(connection)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        row = connection.execute(
            "SELECT schema_version FROM schema_meta WHERE singleton_id = 1"
        ).fetchone()
        if row is None or int(row["schema_version"]) != SCHEMA_VERSION:
            raise ShadowPilotError("Schema ausente ou incompatível")
        control = connection.execute(
            "SELECT kill_switch_enabled, audit_head_hash, audit_event_count FROM controls WHERE singleton_id = 1"
        ).fetchone()
        if control is None:
            raise AuditIntegrityError("Controle de segurança ausente")
        if int(control["kill_switch_enabled"]) not in {0, 1}:
            raise AuditIntegrityError("Estado inválido do kill switch")

    @staticmethod
    def _audit_material(
        *,
        event_id: str,
        event_time: str,
        case_id: str | None,
        actor_id: str,
        event_type: str,
        details_json: str,
        previous_hash: str,
    ) -> dict[str, Any]:
        return {
            "actor_id": actor_id,
            "case_id": case_id,
            "details_json": details_json,
            "event_id": event_id,
            "event_time": event_time,
            "event_type": event_type,
            "previous_hash": previous_hash,
        }

    @classmethod
    def _append_audit_static(
        cls,
        connection: sqlite3.Connection,
        *,
        case_id: str | None,
        actor_id: str,
        event_type: str,
        details: dict[str, Any],
    ) -> str:
        control = connection.execute(
            "SELECT audit_head_hash, audit_event_count FROM controls WHERE singleton_id = 1"
        ).fetchone()
        if control is None:
            raise AuditIntegrityError("Controle de auditoria ausente")
        previous_hash = str(control["audit_head_hash"])
        event_id = str(uuid.uuid4())
        event_time = _now()
        details_json = _canonical_json(details)
        material = cls._audit_material(
            event_id=event_id,
            event_time=event_time,
            case_id=case_id,
            actor_id=actor_id,
            event_type=event_type,
            details_json=details_json,
            previous_hash=previous_hash,
        )
        event_hash = _sha256_json(material)
        connection.execute(
            """
            INSERT INTO audit_events(
                event_id, event_time, case_id, actor_id, event_type,
                details_json, previous_hash, event_hash
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                event_time,
                case_id,
                actor_id,
                event_type,
                details_json,
                previous_hash,
                event_hash,
            ),
        )
        connection.execute(
            """
            UPDATE controls
            SET audit_head_hash = ?, audit_event_count = audit_event_count + 1
            WHERE singleton_id = 1
            """,
            (event_hash,),
        )
        return event_hash

    def _append_audit(self, connection: sqlite3.Connection, **kwargs: Any) -> str:
        return self._append_audit_static(connection, **kwargs)

    @classmethod
    def _verify_audit(cls, connection: sqlite3.Connection) -> dict[str, Any]:
        previous = ZERO_HASH
        count = 0
        for row in connection.execute("SELECT * FROM audit_events ORDER BY sequence"):
            if row["previous_hash"] != previous:
                raise AuditIntegrityError(f"Encadeamento inválido no evento {row['sequence']}")
            material = cls._audit_material(
                event_id=row["event_id"],
                event_time=row["event_time"],
                case_id=row["case_id"],
                actor_id=row["actor_id"],
                event_type=row["event_type"],
                details_json=row["details_json"],
                previous_hash=row["previous_hash"],
            )
            calculated = _sha256_json(material)
            if calculated != row["event_hash"]:
                raise AuditIntegrityError(f"Hash inválido no evento {row['sequence']}")
            previous = calculated
            count += 1
        control = connection.execute(
            "SELECT audit_head_hash, audit_event_count FROM controls WHERE singleton_id = 1"
        ).fetchone()
        if control is None:
            raise AuditIntegrityError("Controle de auditoria ausente")
        if control["audit_head_hash"] != previous or int(control["audit_event_count"]) != count:
            raise AuditIntegrityError("Cabeçalho de auditoria diverge da cadeia")
        return {"valid": True, "event_count": count, "head_hash": previous}

    @staticmethod
    def _validate_idempotency_key(value: str) -> str:
        return _require_text("idempotency_key", value, minimum=8, maximum=200)

    @staticmethod
    def _receipt(
        connection: sqlite3.Connection,
        command_name: str,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        payload_hash = _sha256_json(payload)
        row = connection.execute(
            """
            SELECT payload_sha256, result_json FROM command_receipts
            WHERE command_name = ? AND idempotency_key = ?
            """,
            (command_name, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        if row["payload_sha256"] != payload_hash:
            raise IdempotencyConflict(
                f"Chave já usada com outro conteúdo no comando {command_name}"
            )
        result = json.loads(row["result_json"])
        result["idempotent_replay"] = True
        return result

    @staticmethod
    def _save_receipt(
        connection: sqlite3.Connection,
        command_name: str,
        idempotency_key: str,
        payload: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO command_receipts(
                command_name, idempotency_key, payload_sha256, result_json, created_at
            ) VALUES(?, ?, ?, ?, ?)
            """,
            (
                command_name,
                idempotency_key,
                _sha256_json(payload),
                _canonical_json(result),
                _now(),
            ),
        )

    @staticmethod
    def _case_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "case_id": row["case_id"],
            "source_system": row["source_system"],
            "source_ticket_ref": row["source_ticket_ref"],
            "task": row["task"],
            "prediction_label": row["prediction_label"],
            "prediction_confidence": row["prediction_confidence"],
            "model_id": row["model_id"],
            "model_version": row["model_version"],
            "inference_trace_id": row["inference_trace_id"],
            "input_sha256": row["input_sha256"],
            "prediction_sha256": row["prediction_sha256"],
            "subgroup": row["subgroup"],
            "critical_risk": bool(row["critical_risk"]),
            "state": row["state"],
            "final_label": row["final_label"],
            "received_at": row["received_at"],
            "updated_at": row["updated_at"],
            "external_application_allowed": False,
        }

    @staticmethod
    def _blind_review_case_dict(row: sqlite3.Row) -> dict[str, Any]:
        """Visão de fila que não revela a previsão nem pareceres anteriores."""

        return {
            "case_id": row["case_id"],
            "source_system": row["source_system"],
            "source_ticket_ref": row["source_ticket_ref"],
            "task": row["task"],
            "input_sha256": row["input_sha256"],
            "subgroup": row["subgroup"],
            "critical_risk": bool(row["critical_risk"]),
            "state": row["state"],
            "received_at": row["received_at"],
            "prediction_blinded": True,
            "prior_reviews_blinded": True,
            "external_application_allowed": False,
        }

    @staticmethod
    def _get_case(connection: sqlite3.Connection, case_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        if row is None:
            raise ValidationError("case_id não encontrado")
        return row

    @staticmethod
    def _kill_switch_enabled(connection: sqlite3.Connection) -> bool:
        row = connection.execute(
            "SELECT kill_switch_enabled FROM controls WHERE singleton_id = 1"
        ).fetchone()
        if row is None:
            # Falha fechada mesmo diante de corrupção parcial.
            return True
        return bool(row["kill_switch_enabled"])

    def capture_prediction(
        self,
        *,
        source_ticket_ref: str,
        task: str,
        prediction_label: str,
        prediction_confidence: float,
        model_id: str,
        model_version: str,
        inference_trace_id: str,
        input_sha256: str,
        prediction_sha256: str,
        subgroup: str,
        critical_risk: bool,
        idempotency_key: str,
        actor_id: str = "shadow-ingest",
    ) -> dict[str, Any]:
        clean_task = _require_text("task", task, maximum=32).lower()
        if not isinstance(critical_risk, bool):
            raise ValidationError("critical_risk deve ser booleano")
        payload = {
            "actor_id": _require_text("actor_id", actor_id, maximum=128),
            "critical_risk": critical_risk,
            "inference_trace_id": _require_text(
                "inference_trace_id", inference_trace_id, maximum=256
            ),
            "input_sha256": _require_sha256("input_sha256", input_sha256),
            "model_id": _require_text("model_id", model_id, maximum=256),
            "model_version": _require_text("model_version", model_version, maximum=128),
            "prediction_confidence": _require_confidence(prediction_confidence),
            "prediction_label": _require_label(clean_task, prediction_label),
            "prediction_sha256": _require_sha256("prediction_sha256", prediction_sha256),
            "source_system": "GLPI",
            "source_ticket_ref": _require_text(
                "source_ticket_ref", source_ticket_ref, maximum=128
            ),
            "subgroup": _require_text("subgroup", subgroup, maximum=128),
            "task": clean_task,
        }
        key = self._validate_idempotency_key(idempotency_key)
        # O ator que transportou o registro não altera a identidade da previsão.
        identity = _sha256_json(
            {
                key_name: value
                for key_name, value in payload.items()
                if key_name != "actor_id"
            }
        )
        with self._transaction() as connection:
            replay = self._receipt(connection, "capture_prediction", key, payload)
            if replay is not None:
                return replay
            existing = connection.execute(
                "SELECT * FROM cases WHERE prediction_identity = ?", (identity,)
            ).fetchone()
            if existing is not None:
                result = self._case_dict(existing)
                result["deduplicated_prediction"] = True
                self._save_receipt(connection, "capture_prediction", key, payload, result)
                return result
            trace_conflict = connection.execute(
                "SELECT case_id FROM cases WHERE inference_trace_id = ?",
                (payload["inference_trace_id"],),
            ).fetchone()
            if trace_conflict is not None:
                raise IdempotencyConflict(
                    "inference_trace_id já registrado com outro conteúdo"
                )
            case_id = str(uuid.uuid4())
            now = _now()
            held = self._kill_switch_enabled(connection)
            state = "HELD_KILL_SWITCH" if held else "PENDING_REVIEW"
            held_from_state = "PENDING_REVIEW" if held else None
            connection.execute(
                """
                INSERT INTO cases(
                    case_id, prediction_identity, source_system, source_ticket_ref, task,
                    prediction_label, prediction_confidence, model_id, model_version,
                    inference_trace_id, input_sha256, prediction_sha256, subgroup,
                    critical_risk, state, held_from_state, final_label, received_at, updated_at
                ) VALUES(?, ?, 'GLPI', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    case_id,
                    identity,
                    payload["source_ticket_ref"],
                    payload["task"],
                    payload["prediction_label"],
                    payload["prediction_confidence"],
                    payload["model_id"],
                    payload["model_version"],
                    payload["inference_trace_id"],
                    payload["input_sha256"],
                    payload["prediction_sha256"],
                    payload["subgroup"],
                    int(payload["critical_risk"]),
                    state,
                    held_from_state,
                    now,
                    now,
                ),
            )
            self._append_audit(
                connection,
                case_id=case_id,
                actor_id=payload["actor_id"],
                event_type="PREDICTION_CAPTURED_SHADOW_ONLY",
                details={
                    "model_id": payload["model_id"],
                    "model_version": payload["model_version"],
                    "state": state,
                    "task": payload["task"],
                    "external_application_allowed": False,
                },
            )
            result = self._case_dict(self._get_case(connection, case_id))
            self._save_receipt(connection, "capture_prediction", key, payload, result)
            return result

    def engage_kill_switch(
        self, *, actor_id: str, reason: str, idempotency_key: str
    ) -> dict[str, Any]:
        payload = {
            "actor_id": _require_text("actor_id", actor_id, maximum=128),
            "reason": _require_text("reason", reason, minimum=3),
        }
        key = self._validate_idempotency_key(idempotency_key)
        with self._transaction() as connection:
            replay = self._receipt(connection, "engage_kill_switch", key, payload)
            if replay is not None:
                return replay
            if self._kill_switch_enabled(connection):
                result = {
                    "kill_switch_enabled": True,
                    "held_cases": 0,
                    "already_enabled": True,
                    "external_application_allowed": False,
                }
                self._save_receipt(connection, "engage_kill_switch", key, payload, result)
                return result
            rows = list(
                connection.execute(
                    "SELECT case_id, state FROM cases WHERE state IN (?, ?, ?)",
                    tuple(sorted(OPEN_STATES)),
                )
            )
            now = _now()
            connection.execute(
                """
                UPDATE controls SET kill_switch_enabled = 1, reason = ?, actor_id = ?, updated_at = ?
                WHERE singleton_id = 1
                """,
                (payload["reason"], payload["actor_id"], now),
            )
            for row in rows:
                connection.execute(
                    "UPDATE cases SET held_from_state = state, state = 'HELD_KILL_SWITCH', updated_at = ? WHERE case_id = ?",
                    (now, row["case_id"]),
                )
                self._append_audit(
                    connection,
                    case_id=row["case_id"],
                    actor_id=payload["actor_id"],
                    event_type="CASE_HELD_BY_KILL_SWITCH",
                    details={"previous_state": row["state"], "reason": payload["reason"]},
                )
            self._append_audit(
                connection,
                case_id=None,
                actor_id=payload["actor_id"],
                event_type="KILL_SWITCH_ENGAGED",
                details={"held_cases": len(rows), "reason": payload["reason"]},
            )
            result = {
                "kill_switch_enabled": True,
                "held_cases": len(rows),
                "external_application_allowed": False,
            }
            self._save_receipt(connection, "engage_kill_switch", key, payload, result)
            return result

    def release_kill_switch(
        self,
        *,
        actor_id: str,
        reason: str,
        acknowledgement: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if acknowledgement != RELEASE_ACKNOWLEDGEMENT:
            raise ValidationError(
                f"Liberação exige acknowledgement={RELEASE_ACKNOWLEDGEMENT}"
            )
        payload = {
            "acknowledgement": acknowledgement,
            "actor_id": _require_text("actor_id", actor_id, maximum=128),
            "reason": _require_text("reason", reason, minimum=3),
        }
        key = self._validate_idempotency_key(idempotency_key)
        with self._transaction() as connection:
            replay = self._receipt(connection, "release_kill_switch", key, payload)
            if replay is not None:
                return replay
            if not self._kill_switch_enabled(connection):
                result = {
                    "kill_switch_enabled": False,
                    "resumed_cases": 0,
                    "already_released": True,
                    "external_application_allowed": False,
                }
                self._save_receipt(connection, "release_kill_switch", key, payload, result)
                return result
            held_rows = list(
                connection.execute(
                    "SELECT case_id, held_from_state FROM cases WHERE state = 'HELD_KILL_SWITCH'"
                )
            )
            now = _now()
            connection.execute(
                """
                UPDATE controls SET kill_switch_enabled = 0, reason = ?, actor_id = ?, updated_at = ?
                WHERE singleton_id = 1
                """,
                (payload["reason"], payload["actor_id"], now),
            )
            self._append_audit(
                connection,
                case_id=None,
                actor_id=payload["actor_id"],
                event_type="KILL_SWITCH_RELEASED_SHADOW_ONLY",
                details={
                    "reason": payload["reason"],
                    "resumed_cases": len(held_rows),
                    "external_application_allowed": False,
                },
            )
            for row in held_rows:
                target = row["held_from_state"] or "PENDING_REVIEW"
                if target not in OPEN_STATES:
                    target = "PENDING_REVIEW"
                connection.execute(
                    "UPDATE cases SET state = ?, held_from_state = NULL, updated_at = ? WHERE case_id = ?",
                    (target, now, row["case_id"]),
                )
                self._append_audit(
                    connection,
                    case_id=row["case_id"],
                    actor_id=payload["actor_id"],
                    event_type="CASE_RESUMED_FOR_HUMAN_REVIEW",
                    details={"state": target, "external_application_allowed": False},
                )
            result = {
                "kill_switch_enabled": False,
                "resumed_cases": len(held_rows),
                "external_application_allowed": False,
            }
            self._save_receipt(connection, "release_kill_switch", key, payload, result)
            return result

    def record_review(
        self,
        *,
        case_id: str,
        reviewer_id: str,
        decision: str,
        rationale: str,
        idempotency_key: str,
        proposed_label: str | None = None,
    ) -> dict[str, Any]:
        clean_case_id = _require_text("case_id", case_id, maximum=64)
        clean_decision = _require_text("decision", decision, maximum=16).upper()
        if clean_decision not in {"LABEL", "REJECT", "ABSTAIN"}:
            raise ValidationError("decision deve ser LABEL, REJECT ou ABSTAIN")
        clean_proposed_label: str | None
        if proposed_label is None:
            clean_proposed_label = None
        else:
            clean_proposed_label = _require_text(
                "proposed_label", proposed_label, maximum=64
            ).upper()
        payload = {
            "case_id": clean_case_id,
            "decision": clean_decision,
            "proposed_label": clean_proposed_label,
            "rationale": _require_text("rationale", rationale, minimum=3),
            "reviewer_id": _require_text("reviewer_id", reviewer_id, maximum=128),
        }
        key = self._validate_idempotency_key(idempotency_key)
        with self._transaction() as connection:
            replay = self._receipt(connection, "record_review", key, payload)
            if replay is not None:
                return replay
            if self._kill_switch_enabled(connection):
                raise KillSwitchEngaged("Kill switch ligado; revisão bloqueada de forma segura")
            case = self._get_case(connection, clean_case_id)
            if case["state"] not in {"PENDING_REVIEW", "PENDING_CONFIRMATION"}:
                raise InvalidTransition(f"Caso em {case['state']} não aceita revisão")
            count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM reviews WHERE case_id = ?", (clean_case_id,)
                ).fetchone()[0]
            )
            expected = 0 if case["state"] == "PENDING_REVIEW" else 1
            if count != expected:
                raise AuditIntegrityError("Quantidade de revisões diverge do estado")
            if connection.execute(
                "SELECT 1 FROM reviews WHERE case_id = ? AND reviewer_id = ?",
                (clean_case_id, payload["reviewer_id"]),
            ).fetchone():
                raise ValidationError("O mesmo revisor não pode ocupar as duas rodadas")

            if clean_decision == "LABEL":
                if payload["proposed_label"] is None:
                    raise ValidationError("LABEL exige proposed_label")
                final_proposal = _require_label(case["task"], payload["proposed_label"])
            else:
                if payload["proposed_label"] is not None:
                    raise ValidationError("REJECT/ABSTAIN não aceitam proposed_label")
                final_proposal = None

            review_round = count + 1
            now = _now()
            connection.execute(
                """
                INSERT INTO reviews(
                    review_id, case_id, review_round, reviewer_id, decision,
                    proposed_label, rationale, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    clean_case_id,
                    review_round,
                    payload["reviewer_id"],
                    clean_decision,
                    final_proposal,
                    payload["rationale"],
                    now,
                ),
            )
            final_label: str | None = None
            if review_round == 1:
                # Nenhum parecer isolado pode finalizar ou pular a segunda revisão.
                next_state = "PENDING_CONFIRMATION"
            else:
                reviews = list(
                    connection.execute(
                        "SELECT decision, proposed_label FROM reviews WHERE case_id = ? ORDER BY review_round",
                        (clean_case_id,),
                    )
                )
                proposals = [review["proposed_label"] for review in reviews]
                if all(proposal is not None for proposal in proposals) and len(set(proposals)) == 1:
                    next_state = "CONFIRMED"
                    final_label = proposals[0]
                else:
                    next_state = "PENDING_ADJUDICATION"
            connection.execute(
                "UPDATE cases SET state = ?, final_label = ?, updated_at = ? WHERE case_id = ?",
                (next_state, final_label, now, clean_case_id),
            )
            self._append_audit(
                connection,
                case_id=clean_case_id,
                actor_id=payload["reviewer_id"],
                event_type="HUMAN_REVIEW_RECORDED",
                details={
                    "decision": clean_decision,
                    "proposed_label": final_proposal,
                    "review_round": review_round,
                    "resulting_state": next_state,
                    "external_application_allowed": False,
                },
            )
            result = self._blind_review_case_dict(
                self._get_case(connection, clean_case_id)
            )
            result["review_round"] = review_round
            self._save_receipt(connection, "record_review", key, payload, result)
            return result

    def adjudicate(
        self,
        *,
        case_id: str,
        adjudicator_id: str,
        outcome: str,
        rationale: str,
        idempotency_key: str,
        final_label: str | None = None,
    ) -> dict[str, Any]:
        clean_outcome = _require_text("outcome", outcome, maximum=16).upper()
        if clean_outcome not in {"CONFIRM", "REJECT"}:
            raise ValidationError("outcome deve ser CONFIRM ou REJECT")
        payload = {
            "adjudicator_id": _require_text("adjudicator_id", adjudicator_id, maximum=128),
            "case_id": _require_text("case_id", case_id, maximum=64),
            "final_label": (
                _require_text("final_label", final_label, maximum=64).upper()
                if final_label is not None
                else None
            ),
            "outcome": clean_outcome,
            "rationale": _require_text("rationale", rationale, minimum=3),
        }
        key = self._validate_idempotency_key(idempotency_key)
        with self._transaction() as connection:
            replay = self._receipt(connection, "adjudicate", key, payload)
            if replay is not None:
                return replay
            if self._kill_switch_enabled(connection):
                raise KillSwitchEngaged("Kill switch ligado; adjudicação bloqueada")
            case = self._get_case(connection, payload["case_id"])
            if case["state"] != "PENDING_ADJUDICATION":
                raise InvalidTransition(f"Caso em {case['state']} não aceita adjudicação")
            review_rows = list(
                connection.execute(
                    "SELECT reviewer_id FROM reviews WHERE case_id = ? ORDER BY review_round",
                    (payload["case_id"],),
                )
            )
            if len(review_rows) != 2:
                raise AuditIntegrityError(
                    "Adjudicação exige exatamente duas revisões independentes"
                )
            reviewer_ids = {row["reviewer_id"] for row in review_rows}
            if payload["adjudicator_id"] in reviewer_ids:
                raise ValidationError("Adjudicador deve ser independente dos revisores")
            if clean_outcome == "CONFIRM":
                if payload["final_label"] is None:
                    raise ValidationError("CONFIRM exige final_label")
                resolved_label = _require_label(case["task"], payload["final_label"])
                next_state = "CONFIRMED"
            else:
                if payload["final_label"] is not None:
                    raise ValidationError("REJECT não aceita final_label")
                resolved_label = None
                next_state = "REJECTED"
            now = _now()
            connection.execute(
                """
                INSERT INTO adjudications(
                    adjudication_id, case_id, adjudicator_id, outcome,
                    final_label, rationale, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    payload["case_id"],
                    payload["adjudicator_id"],
                    clean_outcome,
                    resolved_label,
                    payload["rationale"],
                    now,
                ),
            )
            connection.execute(
                "UPDATE cases SET state = ?, final_label = ?, updated_at = ? WHERE case_id = ?",
                (next_state, resolved_label, now, payload["case_id"]),
            )
            self._append_audit(
                connection,
                case_id=payload["case_id"],
                actor_id=payload["adjudicator_id"],
                event_type="HUMAN_ADJUDICATION_RECORDED",
                details={
                    "final_label": resolved_label,
                    "outcome": clean_outcome,
                    "resulting_state": next_state,
                    "external_application_allowed": False,
                },
            )
            result = self._blind_review_case_dict(
                self._get_case(connection, payload["case_id"])
            )
            result["adjudication_outcome"] = clean_outcome
            result["adjudicated_label"] = resolved_label
            self._save_receipt(connection, "adjudicate", key, payload, result)
            return result

    def rollback_case(
        self,
        *,
        case_id: str,
        actor_id: str,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        payload = {
            "actor_id": _require_text("actor_id", actor_id, maximum=128),
            "case_id": _require_text("case_id", case_id, maximum=64),
            "reason": _require_text("reason", reason, minimum=3),
        }
        key = self._validate_idempotency_key(idempotency_key)
        with self._transaction() as connection:
            replay = self._receipt(connection, "rollback_case", key, payload)
            if replay is not None:
                return replay
            case = self._get_case(connection, payload["case_id"])
            if case["state"] == "ROLLED_BACK":
                result = self._case_dict(case)
                result["already_rolled_back"] = True
                self._save_receipt(connection, "rollback_case", key, payload, result)
                return result
            previous_state = case["state"]
            connection.execute(
                """
                UPDATE cases SET state = 'ROLLED_BACK', held_from_state = NULL, updated_at = ?
                WHERE case_id = ?
                """,
                (_now(), payload["case_id"]),
            )
            self._append_audit(
                connection,
                case_id=payload["case_id"],
                actor_id=payload["actor_id"],
                event_type="LOCAL_CASE_ROLLED_BACK",
                details={
                    "previous_state": previous_state,
                    "reason": payload["reason"],
                    "external_rollback_required": False,
                    "external_application_allowed": False,
                },
            )
            result = self._case_dict(self._get_case(connection, payload["case_id"]))
            self._save_receipt(connection, "rollback_case", key, payload, result)
            return result

    def queue(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValidationError("limit deve ser inteiro entre 1 e 1000")
        with self._connection() as connection:
            self._validate_schema(connection)
            self._verify_audit(connection)
            rows = connection.execute(
                """
                SELECT * FROM cases
                WHERE state IN ('PENDING_REVIEW', 'PENDING_CONFIRMATION', 'PENDING_ADJUDICATION')
                ORDER BY critical_risk DESC, received_at ASC, case_id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [self._blind_review_case_dict(row) for row in rows]

    def status(self) -> dict[str, Any]:
        with self._connection() as connection:
            self._validate_schema(connection)
            audit = self._verify_audit(connection)
            control = connection.execute("SELECT * FROM controls WHERE singleton_id = 1").fetchone()
            states = {
                row["state"]: int(row["total"])
                for row in connection.execute(
                    "SELECT state, COUNT(*) AS total FROM cases GROUP BY state ORDER BY state"
                )
            }
            return {
                "audit": audit,
                "evidence_scope": "shadow_pilot_local_only",
                "external_mutation_capability": False,
                "external_application_allowed": False,
                "kill_switch_enabled": bool(control["kill_switch_enabled"]),
                "kill_switch_reason": control["reason"],
                "last_control_actor": control["actor_id"],
                "schema_version": SCHEMA_VERSION,
                "states": states,
            }

    def verify_audit(self) -> dict[str, Any]:
        with self._connection() as connection:
            self._validate_schema(connection)
            return self._verify_audit(connection)

    def metrics(self) -> dict[str, Any]:
        with self._connection() as connection:
            self._validate_schema(connection)
            audit = self._verify_audit(connection)
            cases = list(connection.execute("SELECT * FROM cases"))
            reviews_by_case: dict[str, list[sqlite3.Row]] = {}
            for review in connection.execute("SELECT * FROM reviews ORDER BY case_id, review_round"):
                reviews_by_case.setdefault(review["case_id"], []).append(review)

        total = len(cases)
        active = [case for case in cases if case["state"] != "ROLLED_BACK"]
        reviewed = [case for case in active if reviews_by_case.get(case["case_id"])]
        double_reviewed = [
            case for case in active if len(reviews_by_case.get(case["case_id"], [])) >= 2
        ]
        review_agreements = 0
        for case in double_reviewed:
            proposals = [row["proposed_label"] for row in reviews_by_case[case["case_id"]]][:2]
            if all(proposal is not None for proposal in proposals) and len(set(proposals)) == 1:
                review_agreements += 1
        finalized = [case for case in active if case["state"] in {"CONFIRMED", "REJECTED"}]
        confirmed = [case for case in active if case["state"] == "CONFIRMED"]
        comparable = [case for case in confirmed if case["final_label"]]
        agreements = [case for case in comparable if case["prediction_label"] == case["final_label"]]
        critical_comparable = [case for case in comparable if bool(case["critical_risk"])]
        critical_errors = [
            case
            for case in critical_comparable
            if case["prediction_label"] != case["final_label"]
        ]

        def ratio(numerator: int, denominator: int) -> float | None:
            return numerator / denominator if denominator else None

        state_counts: dict[str, int] = {}
        for case in cases:
            state_counts[case["state"]] = state_counts.get(case["state"], 0) + 1
        subgroup_metrics: dict[str, dict[str, Any]] = {}
        for case in active:
            key = f"{case['task']}::{case['subgroup']}"
            item = subgroup_metrics.setdefault(
                key,
                {"cases": 0, "confirmed": 0, "ai_human_agreements": 0, "critical_errors": 0},
            )
            item["cases"] += 1
            if case["state"] == "CONFIRMED":
                item["confirmed"] += 1
                if case["prediction_label"] == case["final_label"]:
                    item["ai_human_agreements"] += 1
                if bool(case["critical_risk"]) and case["prediction_label"] != case["final_label"]:
                    item["critical_errors"] += 1
        for item in subgroup_metrics.values():
            item["ai_human_agreement_rate"] = ratio(
                item["ai_human_agreements"], item["confirmed"]
            )

        return {
            "audit": audit,
            "evidence_scope": "shadow_pilot_local_only",
            "external_mutations": 0,
            "external_mutation_capability": False,
            "external_application_allowed": False,
            "cases_total": total,
            "cases_active": len(active),
            "states": state_counts,
            "human_review_coverage": ratio(len(reviewed), len(active)),
            "double_review_coverage": ratio(len(double_reviewed), len(active)),
            "reviewer_agreement_rate": ratio(review_agreements, len(double_reviewed)),
            "finalization_rate": ratio(len(finalized), len(active)),
            "ai_human_agreement_rate": ratio(len(agreements), len(comparable)),
            "critical_error_count": len(critical_errors),
            "critical_error_rate": ratio(len(critical_errors), len(critical_comparable)),
            "critical_error_denominator": len(critical_comparable),
            "subgroups": dict(sorted(subgroup_metrics.items())),
        }

    def export_research_labels(self) -> dict[str, Any]:
        with self._connection() as connection:
            self._validate_schema(connection)
            audit = self._verify_audit(connection)
            rows = connection.execute(
                "SELECT * FROM cases WHERE state = 'CONFIRMED' ORDER BY received_at, case_id"
            ).fetchall()
        records = [
            {
                "case_id": row["case_id"],
                "source_ticket_ref": row["source_ticket_ref"],
                "task": row["task"],
                "prediction_label": row["prediction_label"],
                "final_human_label": row["final_label"],
                "model_id": row["model_id"],
                "model_version": row["model_version"],
                "subgroup": row["subgroup"],
                "purpose": RESEARCH_EXPORT_PURPOSE,
                "external_application_allowed": False,
            }
            for row in rows
        ]
        material = {
            "audit_head_hash": audit["head_hash"],
            "external_application_allowed": False,
            "purpose": RESEARCH_EXPORT_PURPOSE,
            "records": records,
        }
        return {
            **material,
            "record_count": len(records),
            "export_sha256": _sha256_json(material),
        }
