from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "avaliacao" / "scripts" / "validar_pipeline_fila_e2e.py"
SPEC = importlib.util.spec_from_file_location("validar_pipeline_fila_e2e", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class PipelineE2ETests(unittest.TestCase):
    def test_every_queue_side_effect_depends_on_shared_lock(self):
        workflow = json.loads((ROOT / 'n8n/workflows/Versão9/V9-WF06-Fila-IA.json').read_text(encoding='utf-8'))
        query = next(n for n in workflow['nodes'] if n['name'] == 'PG: Reservar Fila IA')['parameters']['query']
        for name in ('reservas_expiradas', 'experimentos_encerrados', 'avanco', 'metricas'):
            body = query.split(name + ' AS (', 1)[1].split('RETURNING', 1)[0]
            with self.subTest(cte=name):
                self.assertIn('FROM bloqueio', body)

    def test_main_health_does_not_replace_runner_probe_and_recovery_is_bounded(self):
        context = mock.Mock(
            returncode=0,
            stdout=module.LOCAL_DOCKER_ENDPOINT_WINDOWS + "\n",
            stderr="",
        )
        success = mock.Mock(returncode=0, stdout="", stderr="")
        with (
            mock.patch.object(
                module.subprocess,
                'run',
                side_effect=[context, success, success],
            ) as run,
            mock.patch.object(module, 'require_config', return_value={}),
            mock.patch.object(module.requests, 'get', return_value=mock.Mock(status_code=200)),
            mock.patch.object(module, 'probe_runner_ready', side_effect=[False, True]) as probe,
            mock.patch.object(module.time, 'monotonic', side_effect=[0, 0, 31, 31, 32]),
            mock.patch.object(module.time, 'sleep'),
        ):
            module.recreate_n8n({})
        self.assertEqual(probe.call_count, 2)
        self.assertEqual(run.call_count, 3)
        self.assertEqual(
            run.call_args.args[0],
            ['docker', '--context', 'desktop-linux', 'restart', 'n8n-task-runners'],
        )

    def test_docker_commands_are_pinned_local_and_remote_endpoint_is_rejected(self):
        self.assertEqual(
            module._docker_command('inspect', 'n8n-task-runners'),
            [
                'docker',
                '--context',
                'desktop-linux',
                'inspect',
                'n8n-task-runners',
            ],
        )
        remote = mock.Mock(returncode=0, stdout='ssh://example.invalid\n', stderr='')
        with mock.patch.object(module.subprocess, 'run', return_value=remote):
            with self.assertRaisesRegex(RuntimeError, 'Docker Desktop local|endpoint Docker remoto'):
                module.assert_local_docker_context()

    def test_runner_probe_requires_code_node_rejection(self) -> None:
        config = {"n8n_url": "http://127.0.0.1:5678", "webhook_key": "fixture"}
        response = mock.Mock(status_code=422, text="ticket_id inválido")
        with mock.patch.object(module.requests, "post", return_value=response) as post:
            self.assertTrue(module.probe_runner_ready(config))
            self.assertEqual(post.call_args.kwargs["json"], {"ticket_id": 0})
            response.status_code = 200
            self.assertFalse(module.probe_runner_ready(config))
            response.status_code, response.text = 422, "proxy error"
            self.assertFalse(module.probe_runner_ready(config))

    def test_cleanup_accepts_owned_case_before_ticket_materialization(self) -> None:
        connection = mock.MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"registered_ticket_id": None}

        def execute(sql, parameters):
            cursor.rowcount = 1 if any(
                f"DELETE FROM {table}" in sql
                for table in ("dataset_controle", "experimentos_avaliacao")
            ) else 0

        cursor.execute.side_effect = execute
        result = module.cleanup_database(connection, module.make_run_id(), 325)
        self.assertEqual(result["ticket"], 0)
        self.assertEqual(result["dataset"], 1)
        connection.commit.assert_called_once()

    def test_cleanup_still_rejects_unowned_case(self) -> None:
        connection = mock.MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = None
        with self.assertRaisesRegex(RuntimeError, "propriedade sintética"):
            module.cleanup_database(connection, module.make_run_id(), 325)
        self.assertEqual(cursor.execute.call_count, 1)
        connection.commit.assert_not_called()

    def test_cleanup_cardinality_failure_rolls_back_before_commit(self) -> None:
        connection = mock.MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"registered_ticket_id": 325}
        cursor.rowcount = 0
        with self.assertRaisesRegex(RuntimeError, "cardinalidade"):
            module.cleanup_database(connection, module.make_run_id(), 325)
        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()

    def test_run_id_is_deterministic_namespace(self) -> None:
        value = module.make_run_id(datetime(2026, 8, 17, 12, 34, 56, 123456, tzinfo=timezone.utc))
        self.assertEqual(value, "VALIDACAO-WF06-E2E-20260817T123456123456Z")
        self.assertEqual(module.validate_run_id(value), value)
        with self.assertRaises(ValueError):
            module.validate_run_id("CALQ-OUTRO")

    def test_scoped_profile_disables_every_remote_path(self) -> None:
        snapshot = {key: "original" for key in module.PROFILE_KEYS}
        run_id = module.make_run_id(datetime(2026, 8, 17, tzinfo=timezone.utc))
        scoped = module.scoped_runtime_profile(snapshot, run_id)
        self.assertEqual(scoped["FILA_IA_RUN_SCOPE"], run_id)
        self.assertEqual(scoped["IA_MODEL_LOCAL"], module.EXPECTED_MODEL)
        self.assertEqual(scoped["IA_OPERATIONAL_SEQUENCE"], "LOCAL")
        self.assertEqual(scoped["IA_FAILOVER_ENABLED"], "false")
        self.assertEqual(scoped["FILA_IA_LOTE_TAMANHO"], "1")

    def test_generation_config_is_local_and_non_confirmatory(self) -> None:
        provenance = {
            "manifest_sha256": "a" * 64,
            "manifest_payload_sha256": "b" * 64,
            "bundle_sha256": "c" * 64,
            "embedding": {"model_revision": "rev", "model_tree_sha256": "d" * 64},
        }
        config = module.generation_config(provenance)
        self.assertEqual(config["ia_fixed_model_role"], "LOCAL")
        self.assertEqual(config["ia_expected_model"], module.EXPECTED_MODEL)
        self.assertFalse(config["failover_enabled"])
        self.assertFalse(config["confirmatory_eligible"])

    def _snapshot(self) -> dict:
        provenance = self._provenance()
        policy = {"fixed_role": "LOCAL", "failover_allowed": False, "policy_violation": False}
        metadata = {
            "pipeline_evaluation_eligible": True,
            "artifact": {
                "bundle_sha256": provenance["bundle_sha256"],
                "manifest_payload_sha256": provenance["manifest_payload_sha256"],
            },
        }
        attempts = []
        decisions = []
        events = []
        for stage, prediction in (("DEDUPLICACAO", "NAO_DUPLICADO"), ("CLASSIFICACAO", "TRIAGEM_MANUAL")):
            decisions.append({"etapa": stage, "predicao": prediction, "erro_ia": False})
            attempts.append(
                {
                    "etapa": stage,
                    "ordem_tentativa": 1,
                    "papel_modelo": "LOCAL",
                    "provedor_ia": "local-native",
                    "versao_modelo": module.EXPECTED_MODEL,
                    "status_tentativa": "VALID",
                    "transporte_ok": True,
                    "schema_ok": True,
                    "fallback_utilizado": False,
                    "retryable": False,
                    "metadata_cientifica": metadata,
                    "politica_execucao": policy,
                }
            )
            events.append({"fase": stage, "erro": False})
        return {
            "ticket": {
                "triagem_status": "TRIAGEM_MANUAL",
                "log_workflow": [{"acao": "RESERVAR_FILA"}, {"acao": "RESERVAR_FILA"}],
            },
            "decisions": decisions,
            "attempts": attempts,
            "events": events,
            "dlq": [],
        }

    @staticmethod
    def _provenance() -> dict:
        return {"bundle_sha256": "c" * 64, "manifest_payload_sha256": "b" * 64}

    def test_complete_snapshot_requires_two_clean_stages(self) -> None:
        summary = module.validate_complete_snapshot(self._snapshot(), self._provenance())
        self.assertEqual(summary["reservations"], 2)
        self.assertEqual(summary["terminal"], "TRIAGEM_MANUAL")
        self.assertEqual(summary["attempts"], 2)

    def test_complete_snapshot_rejects_fallback_retry_and_dlq(self) -> None:
        for mutation in ("fallback", "retry", "dlq"):
            snapshot = self._snapshot()
            if mutation == "fallback":
                snapshot["attempts"][0]["fallback_utilizado"] = True
            elif mutation == "retry":
                snapshot["attempts"][0]["ordem_tentativa"] = 2
            else:
                snapshot["dlq"] = [{"id": 1}]
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                module.validate_complete_snapshot(snapshot, self._provenance())

    def test_complete_snapshot_rejects_obra_and_missing_cycle(self) -> None:
        for classification, terminal in (
            ("OBRA", "FECHADO_OBRA"),
            ("DEMO", "ATRIBUIDO_DEMO"),
            ("SOB_DEMANDA", "ENCAMINHADO_PLANEJADO"),
        ):
            snapshot = self._snapshot()
            snapshot["decisions"][1]["predicao"] = classification
            snapshot["ticket"]["triagem_status"] = terminal
            with self.subTest(classification=classification), self.assertRaises(RuntimeError):
                module.validate_complete_snapshot(snapshot, self._provenance())
        snapshot = self._snapshot()
        snapshot["ticket"]["log_workflow"].pop()
        with self.assertRaises(RuntimeError):
            module.validate_complete_snapshot(snapshot, self._provenance())

    def test_existing_output_blocks_before_preflight_or_mutation(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output = Path(temporary) / "existing.json"
            output.write_text("{}\n", encoding="utf-8")
            args = SimpleNamespace(output=str(output))
            with mock.patch.object(module, "preflight") as preflight:
                with self.assertRaisesRegex(RuntimeError, "já existe"):
                    module.execute.__wrapped__(args)
            preflight.assert_not_called()

    def test_partial_runtime_transition_never_restores_without_queue_lock(self) -> None:
        run_id = module.make_run_id(datetime(2026, 8, 17, tzinfo=timezone.utc))
        profile = {key: "original" for key in module.PROFILE_KEYS}
        profile["IA_MODEL_LOCAL"] = module.EXPECTED_MODEL
        profile["IA_MODEL_VERSION"] = module.EXPECTED_MODEL
        controller = {
            "id": 1,
            "proxima_liberacao_em": datetime(2026, 8, 17, tzinfo=timezone.utc),
            "intervalo_segundos": 45,
            "lote_tamanho": 3,
            "atualizado_em": datetime(2026, 8, 17, tzinfo=timezone.utc),
        }
        base = {
            "runtime_profile": profile,
            "controller": module.scalar(controller),
            "model_provenance": self._provenance(),
            "runtime_provenance": {},
            "safe_probes": {},
            "workflow_artifacts": {},
            "config": {
                "n8n_url": "http://127.0.0.1:5678",
                "n8n_user": "fixture",
                "n8n_password": "fixture",
                "glpi_url": "http://127.0.0.1:9080/apirest.php",
                "glpi_app_token": "fixture",
                "glpi_auth_basic": "fixture",
                "webhook_key": "fixture",
                "local_token": "fixture",
            },
        }
        first_lock = mock.MagicMock()
        first_lock.__enter__.return_value = mock.MagicMock()
        second_lock = mock.MagicMock()
        second_lock.__enter__.side_effect = RuntimeError("queue busy")
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output = Path(temporary) / "evidence.json"
            args = SimpleNamespace(
                output=str(output),
                run_id=run_id,
                lock_timeout=1.0,
                http_timeout=1.0,
                timeout=1.0,
                poll=0.01,
            )
            with (
                mock.patch.object(module, "preflight", return_value=base),
                mock.patch.object(module, "assert_no_eligible_foreign_queue"),
                mock.patch.object(module, "assert_no_active_n8n_executions"),
                mock.patch.object(module, "wait_no_active_n8n_executions"),
                mock.patch.object(
                    module,
                    "queue_reservation_lock",
                    side_effect=[first_lock, second_lock],
                ),
                mock.patch.object(module, "controller_snapshot", return_value=controller),
                mock.patch.object(
                    module,
                    "recreate_n8n",
                    side_effect=RuntimeError("partial compose failure"),
                ) as recreate,
            ):
                with self.assertRaisesRegex(RuntimeError, "partial compose failure"):
                    module.execute.__wrapped__(args)

            self.assertEqual(recreate.call_count, 1)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(payload["cleanup"]["complete"])
            self.assertFalse(payload["cleanup"]["runtime_profile_restored"])

    def test_snapshot_rejects_wrong_attempt_stage_and_decision_error(self) -> None:
        snapshot = self._snapshot()
        snapshot["attempts"][1]["etapa"] = "DEDUPLICACAO"
        with self.assertRaisesRegex(RuntimeError, "uma tentativa por etapa"):
            module.validate_complete_snapshot(snapshot, self._provenance())

        snapshot = self._snapshot()
        snapshot["decisions"][0]["erro_ia"] = True
        with self.assertRaisesRegex(RuntimeError, "Decisão ou evento com erro"):
            module.validate_complete_snapshot(snapshot, self._provenance())

    def test_local_url_parser_rejects_substring_and_userinfo_attacks(self) -> None:
        accepted = (
            "http://127.0.0.1:5678",
            "http://localhost:5678",
            "http://[::1]:8090",
        )
        for value in accepted:
            with self.subTest(value=value):
                self.assertEqual(module.validate_local_url(value, "url"), value)

        rejected = (
            "http://127.0.0.1.evil.example:5678",
            "http://localhost.evil.example:5678",
            "http://localhost@evil.example:5678",
            "http://" + "user" + ":" + "password" + "@localhost:5678",
        )
        for value in rejected:
            with self.subTest(value=value):
                with self.assertRaises(RuntimeError):
                    module.validate_local_url(value, "url")

    def test_safe_probes_are_fail_closed(self) -> None:
        provenance = self._provenance()
        responses = [
            {
                "result": {"eh_duplicado": False},
                "metadata": {
                    "decision_path": "deterministic_empty_history",
                    "pipeline_evaluation_eligible": True,
                    "fallback_used": False,
                    "artifact": {
                        "bundle_sha256": provenance["bundle_sha256"],
                        "manifest_payload_sha256": provenance["manifest_payload_sha256"],
                    },
                },
            },
            {
                "result": {"tipo": "TRIAGEM_MANUAL", "executor": "FISCAL"},
                "metadata": {
                    "decision_path": "deterministic_out_of_scope",
                    "pipeline_evaluation_eligible": True,
                    "fallback_used": False,
                    "artifact": {
                        "bundle_sha256": provenance["bundle_sha256"],
                        "manifest_payload_sha256": provenance["manifest_payload_sha256"],
                    },
                },
            },
        ]
        with mock.patch.object(module.calibration, "_request_json", side_effect=responses):
            result = module.validate_safe_local_probes("http://127.0.0.1:8090", "token", provenance, 1)
        self.assertEqual(set(result), {"deduplicacao", "classificacao"})
        responses[0]["metadata"]["fallback_used"] = True
        with mock.patch.object(module.calibration, "_request_json", side_effect=responses), self.assertRaises(RuntimeError):
            module.validate_safe_local_probes("http://127.0.0.1:8090", "token", provenance, 1)

    def test_local_health_is_bound_to_manifest_without_forcing_hybrid_probe(self) -> None:
        provenance = {
            **self._provenance(),
            "bundle_version": "local-hybrid-bundle-v1.8.0",
            "embedding": {
                "model_revision": "revision",
                "model_tree_sha256": "d" * 64,
            },
        }
        health = {
            "alive": True,
            "decision_ready": True,
            "candidate_evaluation_eligible": True,
            "pipeline_evaluation_eligible": True,
            "mode": "production",
            "artifacts": {
                "hybrid_bundle": {
                    "loaded": True,
                    "version": provenance["bundle_version"],
                }
            },
            "embedding": {
                "backend": "granite_embedding_pytorch_fp32",
                "dimension": 384,
                "model_revision": "revision",
                "model_tree_sha256": "d" * 64,
                "fallback_used": False,
            },
        }
        with mock.patch.object(
            module.calibration,
            "_request_json",
            return_value=health,
        ):
            result = module.validate_local_runtime_health(
                "http://127.0.0.1:8090",
                "token",
                provenance,
                1,
            )

        self.assertTrue(all(result["health_gates"].values()))

    def test_default_cli_is_dry_run_and_manifest_is_required(self) -> None:
        parser = module.build_parser()
        args = parser.parse_args(["--model-manifest", "manifest.json"])
        self.assertFalse(args.executar)
        self.assertEqual(args.confirmacao, "")

    def test_workflow_manifest_covers_worker_chain_and_builders(self) -> None:
        manifest = module.workflow_artifacts()
        for name in (*module.WORKFLOW_FILES, "ai_gateway_builder.py", "build_wf02.py", "build_wf03.py", "build_wf06.py"):
            self.assertRegex(manifest[name]["sha256"], r"^[a-f0-9]{64}$")

    def test_deployed_workflow_parity_uses_logic_hash_not_layout(self) -> None:
        directory = ROOT / "n8n" / "workflows" / "Versão9"
        responses = []
        for filename in module.WORKFLOW_FILES:
            payload = json.loads(
                (directory / filename).read_text(encoding="utf-8-sig")
            )
            for index, node in enumerate(payload["nodes"]):
                node["position"] = [index * 17, index * -11]
            response = mock.MagicMock()
            response.json.return_value = {"data": payload}
            responses.append(response)
        session = mock.MagicMock()
        session.get.side_effect = responses
        with mock.patch.object(module, "n8n_login_session", return_value=session):
            evidence = module.verify_deployed_workflows(
                "http://127.0.0.1:5678",
                "fixture",
                "fixture",
            )

        self.assertEqual(set(evidence), set(module.WORKFLOW_FILES))
        self.assertTrue(all(item["parity"] for item in evidence.values()))
        session.close.assert_called_once_with()

    def test_active_execution_guard_uses_supported_n8n_endpoint(self) -> None:
        response = mock.MagicMock()
        response.json.return_value = {
            "data": {
                "concurrentExecutionsCount": 1,
                "results": [{"id": "1", "status": "running"}],
            }
        }
        session = mock.MagicMock()
        session.get.return_value = response
        with mock.patch.object(module, "n8n_login_session", return_value=session):
            with self.assertRaisesRegex(RuntimeError, "1 execução"):
                module.assert_no_active_n8n_executions(
                    "http://127.0.0.1:5678",
                    "fixture",
                    "fixture",
                )

        session.get.assert_called_once_with(
            "http://127.0.0.1:5678/rest/executions",
            timeout=20,
        )
        session.close.assert_called_once_with()

    def test_ingress_accepts_documented_empty_202_response(self) -> None:
        response = mock.MagicMock()
        response.status_code = 202
        response.text = ""
        with mock.patch.object(module.requests, "post", return_value=response):
            result = module.ingress_ticket(
                "http://127.0.0.1:5678",
                "fixture-key",
                123,
                1,
            )

        self.assertEqual(
            result,
            {"status_code": 202, "response_body": "EMPTY"},
        )
        response.json.assert_not_called()

    def test_ingress_records_non_json_202_without_persisting_body(self) -> None:
        response = mock.MagicMock()
        response.status_code = 202
        response.text = "Workflow was started"
        response.json.side_effect = ValueError("not json")
        with mock.patch.object(module.requests, "post", return_value=response):
            result = module.ingress_ticket(
                "http://127.0.0.1:5678",
                "fixture-key",
                123,
                1,
            )

        self.assertEqual(result["status_code"], 202)
        self.assertEqual(result["response_body"], "TEXT")
        self.assertEqual(result["body_length"], len(response.text.encode("utf-8")))
        self.assertNotIn(response.text, json.dumps(result))


if __name__ == "__main__":
    unittest.main()
