from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from avaliacao.piloto_sombra.core import (
    RELEASE_ACKNOWLEDGEMENT,
    AuditIntegrityError,
    IdempotencyConflict,
    InvalidTransition,
    KillSwitchEngaged,
    ShadowPilot,
    ValidationError,
)


ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / "avaliacao" / "piloto_sombra"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ShadowPilotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = Path(self.temp_dir.name) / "piloto.sqlite3"
        self.pilot = ShadowPilot.initialize(
            self.database,
            actor_id="responsavel-piloto",
        )

    def capture(
        self,
        *,
        key: str = "capture-case-0001",
        ticket: str = "GLPI-1001",
        trace: str = "trace-1001",
        actor: str = "shadow-ingest",
        confidence: float = 0.82,
        critical_risk: bool = False,
    ) -> dict:
        return self.pilot.capture_prediction(
            source_ticket_ref=ticket,
            task="classification",
            prediction_label="OBRA",
            prediction_confidence=confidence,
            model_id="candidate-frozen",
            model_version="bundle-sha256",
            inference_trace_id=trace,
            input_sha256=digest(f"input:{ticket}"),
            prediction_sha256=digest(f"prediction:{trace}"),
            subgroup="campus-a",
            critical_risk=critical_risk,
            actor_id=actor,
            idempotency_key=key,
        )

    def release(self, *, key: str = "release-pilot-0001") -> dict:
        return self.pilot.release_kill_switch(
            actor_id="responsavel-piloto",
            reason="revisão local autorizada",
            acknowledgement=RELEASE_ACKNOWLEDGEMENT,
            idempotency_key=key,
        )

    def review(
        self,
        case_id: str,
        *,
        reviewer: str,
        key: str,
        decision: str = "LABEL",
        label: str | None = "OBRA",
    ) -> dict:
        return self.pilot.record_review(
            case_id=case_id,
            reviewer_id=reviewer,
            decision=decision,
            proposed_label=label,
            rationale="parecer humano independente",
            idempotency_key=key,
        )

    def test_initialization_is_fail_closed_and_capture_never_mutates_externally(self) -> None:
        status = self.pilot.status()
        self.assertTrue(status["kill_switch_enabled"])
        self.assertFalse(status["external_mutation_capability"])
        self.assertFalse(status["external_application_allowed"])

        captured = self.capture()
        self.assertEqual(captured["state"], "HELD_KILL_SWITCH")
        self.assertFalse(captured["external_application_allowed"])
        self.assertEqual(self.pilot.queue(), [])
        with self.assertRaises(KillSwitchEngaged):
            self.review(
                captured["case_id"],
                reviewer="especialista-1",
                key="review-held-0001",
            )

    def test_release_requires_explicit_shadow_only_acknowledgement(self) -> None:
        with self.assertRaises(ValidationError):
            self.pilot.release_kill_switch(
                actor_id="responsavel-piloto",
                reason="tentativa insegura",
                acknowledgement="ALLOW_GLPI_MUTATION",
                idempotency_key="release-invalid-0001",
            )
        self.assertTrue(self.pilot.status()["kill_switch_enabled"])
        released = self.release()
        self.assertFalse(released["kill_switch_enabled"])
        self.assertFalse(released["external_application_allowed"])

    def test_review_queue_is_blind_and_two_independent_labels_are_required(self) -> None:
        self.release()
        captured = self.capture()
        queued = self.pilot.queue()[0]
        for secret_field in (
            "prediction_label",
            "prediction_confidence",
            "prediction_sha256",
            "model_id",
            "model_version",
            "final_label",
        ):
            self.assertNotIn(secret_field, queued)
        self.assertTrue(queued["prediction_blinded"])
        self.assertTrue(queued["prior_reviews_blinded"])

        first = self.review(
            captured["case_id"],
            reviewer="especialista-1",
            key="review-one-0001",
        )
        self.assertEqual(first["state"], "PENDING_CONFIRMATION")
        self.assertNotIn("prediction_label", first)
        with self.assertRaises(ValidationError):
            self.review(
                captured["case_id"],
                reviewer="especialista-1",
                key="review-repeated-person-0001",
            )

        second = self.review(
            captured["case_id"],
            reviewer="especialista-2",
            key="review-two-0001",
        )
        self.assertEqual(second["state"], "CONFIRMED")
        self.assertNotIn("prediction_label", second)

    def test_reject_or_disagreement_still_requires_second_review_and_third_adjudicator(self) -> None:
        self.release()
        captured = self.capture()
        first = self.review(
            captured["case_id"],
            reviewer="especialista-1",
            decision="REJECT",
            label=None,
            key="review-reject-0001",
        )
        self.assertEqual(first["state"], "PENDING_CONFIRMATION")
        with self.assertRaises(InvalidTransition):
            self.pilot.adjudicate(
                case_id=captured["case_id"],
                adjudicator_id="especialista-3",
                outcome="CONFIRM",
                final_label="DEMO",
                rationale="adjudicação prematura",
                idempotency_key="adjudicate-premature-0001",
            )

        second = self.review(
            captured["case_id"],
            reviewer="especialista-2",
            decision="LABEL",
            label="DEMO",
            key="review-disagreement-0001",
        )
        self.assertEqual(second["state"], "PENDING_ADJUDICATION")
        with self.assertRaises(ValidationError):
            self.pilot.adjudicate(
                case_id=captured["case_id"],
                adjudicator_id="especialista-1",
                outcome="CONFIRM",
                final_label="DEMO",
                rationale="mesma pessoa não pode adjudicar",
                idempotency_key="adjudicate-not-independent-0001",
            )

        adjudicated = self.pilot.adjudicate(
            case_id=captured["case_id"],
            adjudicator_id="especialista-3",
            outcome="CONFIRM",
            final_label="DEMO",
            rationale="terceiro parecer independente",
            idempotency_key="adjudicate-independent-0001",
        )
        self.assertEqual(adjudicated["state"], "CONFIRMED")
        self.assertEqual(adjudicated["adjudicated_label"], "DEMO")
        self.assertFalse(adjudicated["external_application_allowed"])

    def test_idempotency_replays_same_result_and_rejects_changed_payload(self) -> None:
        original = self.capture()
        event_count = self.pilot.verify_audit()["event_count"]
        replay = self.capture()
        self.assertEqual(replay["case_id"], original["case_id"])
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(self.pilot.verify_audit()["event_count"], event_count)

        with self.assertRaises(IdempotencyConflict):
            self.capture(confidence=0.71)

        duplicate_transport = self.capture(
            key="capture-case-0002",
            actor="shadow-ingest-retry",
        )
        self.assertEqual(duplicate_transport["case_id"], original["case_id"])
        self.assertTrue(duplicate_transport["deduplicated_prediction"])
        with self.assertRaises(IdempotencyConflict):
            self.capture(
                key="capture-case-0003",
                confidence=0.71,
            )

    def test_audit_chain_detects_tampering(self) -> None:
        self.capture()
        self.assertTrue(self.pilot.verify_audit()["valid"])
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                "UPDATE audit_events SET details_json = ? WHERE sequence = 1",
                (json.dumps({"tampered": True}),),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(AuditIntegrityError):
            self.pilot.verify_audit()

    def test_kill_switch_is_safe_shutdown_and_rollback_is_local_only(self) -> None:
        self.release()
        captured = self.capture()
        shutdown = self.pilot.engage_kill_switch(
            actor_id="responsavel-piloto",
            reason="encerramento seguro",
            idempotency_key="shutdown-pilot-0001",
        )
        self.assertTrue(shutdown["kill_switch_enabled"])
        self.assertEqual(shutdown["held_cases"], 1)
        self.assertFalse(shutdown["external_application_allowed"])

        rolled_back = self.pilot.rollback_case(
            case_id=captured["case_id"],
            actor_id="responsavel-piloto",
            reason="caso retirado da pesquisa",
            idempotency_key="rollback-case-0001",
        )
        self.assertEqual(rolled_back["state"], "ROLLED_BACK")
        self.assertFalse(rolled_back["external_application_allowed"])
        self.assertTrue(self.pilot.verify_audit()["valid"])

    def test_export_is_an_explicit_research_only_envelope(self) -> None:
        empty = self.pilot.export_research_labels()
        self.assertEqual(empty["purpose"], "research_evaluation_only")
        self.assertFalse(empty["external_application_allowed"])
        self.assertEqual(empty["record_count"], 0)
        self.assertEqual(empty["records"], [])
        self.assertEqual(len(empty["export_sha256"]), 64)

        self.release()
        case_id = self.capture()["case_id"]
        self.review(case_id, reviewer="especialista-1", key="export-review-0001")
        self.review(case_id, reviewer="especialista-2", key="export-review-0002")
        exported = self.pilot.export_research_labels()
        self.assertEqual(exported["record_count"], 1)
        self.assertEqual(exported["records"][0]["purpose"], "research_evaluation_only")
        self.assertFalse(exported["records"][0]["external_application_allowed"])

    def test_invalid_types_fail_closed(self) -> None:
        with self.assertRaises(ValidationError):
            self.capture(critical_risk=1)  # type: ignore[arg-type]
        with self.assertRaises(ValidationError):
            self.capture(confidence=float("nan"))
        self.release()
        case_id = self.capture()["case_id"]
        with self.assertRaises(ValidationError):
            self.pilot.record_review(
                case_id=case_id,
                reviewer_id="especialista-1",
                decision="CONFIRM",
                proposed_label=None,
                rationale="tentativa não cegada",
                idempotency_key="legacy-review-0001",
            )

    def test_module_has_no_external_service_or_network_imports(self) -> None:
        forbidden_roots = {
            "aiohttp",
            "httpx",
            "psycopg",
            "psycopg2",
            "requests",
            "urllib",
        }
        imported: set[str] = set()
        for path in (MODULE_DIR / "core.py", MODULE_DIR / "cli.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
        self.assertTrue(forbidden_roots.isdisjoint(imported))


if __name__ == "__main__":
    unittest.main()
