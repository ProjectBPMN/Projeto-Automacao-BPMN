from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "avaliacao" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import calibrar_vazao  # noqa: E402


def sample_model_provenance() -> dict:
    return {
        "model_version": "local-hybrid-v1.9.0",
        "bundle_version": "local-hybrid-bundle-v1.9.0",
        "manifest_sha256": "a" * 64,
        "manifest_payload_sha256": "b" * 64,
        "bundle_sha256": "c" * 64,
        "embedding": {
            "model_id": "ibm-granite/granite-embedding-97m-multilingual-r2",
            "dimension": 384,
            "model_revision": "revision-frozen",
            "model_tree_sha256": "d" * 64,
        },
    }


class CalibracaoVazaoTests(unittest.TestCase):
    def test_cli_requires_explicit_model_manifest(self) -> None:
        with patch.object(sys, "argv", ["calibrar_vazao.py"]):
            with self.assertRaises(SystemExit):
                calibrar_vazao.parse_args()

    def test_help_does_not_require_database_connection(self) -> None:
        with patch.object(sys, "argv", ["calibrar_vazao.py", "--help"]):
            with redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as stopped:
                    calibrar_vazao.main()

        self.assertEqual(stopped.exception.code, 0)

    def test_requested_sample_size_is_exact_and_deterministic(self) -> None:
        first = calibrar_vazao.calibration_cases(12, 2026062502)
        second = calibrar_vazao.calibration_cases(12, 2026062502)

        self.assertEqual(len(first), 12)
        self.assertEqual(
            [case.case_id for case in first],
            [case.case_id for case in second],
        )
        self.assertTrue(all(case.dimension == "CLASSIFICACAO" for case in first))

    def test_non_positive_sample_size_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "maior que zero"):
            calibrar_vazao.calibration_cases(0, 2026062502)

    def test_calibration_contract_forces_local_model_without_failover(self) -> None:
        config = calibrar_vazao.calibration_generation_config(
            {"id": "Q1", "batch": 3, "interval_seconds": 45},
            sample_model_provenance(),
        )

        self.assertEqual(config["ia_fixed_model_role"], "LOCAL")
        self.assertEqual(config["ia_expected_model"], "local-hybrid-v1.9.0")
        self.assertEqual(config["ia_execution_mode"], "CALIBRACAO")
        self.assertFalse(config["failover_enabled"])
        self.assertFalse(config["fallback_enabled"])
        self.assertFalse(config["scientific_result"])
        self.assertFalse(config["confirmatory_eligible"])

    def test_register_experiment_persists_the_gateway_contract(self) -> None:
        with patch.object(calibrar_vazao.checker, "execute") as execute:
            calibrar_vazao.register_experiment(
                "CALQ-TEST-Q1-R1",
                2026062502,
                {"id": "Q1", "batch": 3, "interval_seconds": 45},
                sample_model_provenance(),
            )

        _, parameters = execute.call_args.args
        generation_config = json.loads(parameters[-2])
        self.assertEqual(parameters[-3], "local-hybrid-v1.9.0")
        self.assertEqual(
            parameters[-1], calibrar_vazao.CALIBRATION_PROTOCOL_VERSION
        )
        self.assertEqual(generation_config["ia_fixed_model_role"], "LOCAL")
        self.assertEqual(
            generation_config["ia_expected_model"], "local-hybrid-v1.9.0"
        )
        self.assertEqual(generation_config["ia_execution_mode"], "CALIBRACAO")
        self.assertFalse(generation_config["failover_enabled"])
        self.assertEqual(generation_config["model_manifest_sha256"], "a" * 64)
        self.assertEqual(generation_config["model_bundle_sha256"], "c" * 64)

    def test_configuration_aggregation_applies_p95_sla_and_confidence_interval(self) -> None:
        config = {
            "id": "Q1",
            "base_configuration_id": "Q1",
            "batch": 3,
            "interval_seconds": 45,
            "ingress_profile": "deterministic",
            "tickets_per_repetition": 3,
            "burst_size": None,
        }
        runs = []
        for repetition, latencies in enumerate(([10.0, 12.0], [11.0, 13.0]), start=1):
            runs.append(
                {
                    **config,
                    "repetition": repetition,
                    "metrics": {
                        "success": True,
                        "total": 3,
                        "vazao_observada_terminalizacoes_por_minuto": 6.0
                        + repetition,
                        "observations": [
                            {
                                "warmup": False,
                                "espera_ingresso_banco_ate_primeira_decisao_ia_s": latency
                                / 2,
                                "duracao_ingresso_banco_ate_ultimo_update_terminal_s": latency,
                            }
                            for latency in latencies
                        ],
                    },
                }
            )

        aggregate = calibrar_vazao.aggregate_configurations(
            runs, [config], repetitions=2, p95_sla_seconds=20.0
        )[0]

        self.assertTrue(aggregate["all_runs_successful"])
        self.assertTrue(aggregate["p95_sla_met"])
        self.assertTrue(aggregate["eligible_for_selection"])
        self.assertEqual(aggregate["latency_observations_after_warmup"], 4)
        self.assertAlmostEqual(
            aggregate[
                "duracao_ingresso_banco_ate_ultimo_update_terminal_s"
            ]["p95"],
            12.85,
        )
        self.assertAlmostEqual(
            aggregate[
                "vazao_observada_terminalizacoes_por_minuto"
            ]["mean_between_runs"],
            7.5,
        )
        self.assertLess(
            aggregate["run_success_wilson_95"]["lower"], 1.0
        )
        self.assertEqual(aggregate["run_success_wilson_95"]["upper"], 1.0)

    def test_configuration_outside_p95_sla_is_not_selected(self) -> None:
        config = {
            "id": "Q1",
            "base_configuration_id": "Q1",
            "batch": 3,
            "interval_seconds": 45,
            "ingress_profile": "deterministic",
            "tickets_per_repetition": 1,
            "burst_size": None,
        }
        runs = [
            {
                **config,
                "repetition": 1,
                "metrics": {
                    "success": True,
                    "total": 1,
                    "vazao_observada_terminalizacoes_por_minuto": 1.0,
                    "observations": [
                        {
                            "warmup": False,
                            "espera_ingresso_banco_ate_primeira_decisao_ia_s": 5.0,
                            "duracao_ingresso_banco_ate_ultimo_update_terminal_s": 30.0,
                        }
                    ],
                },
            }
        ]
        aggregate = calibrar_vazao.aggregate_configurations(
            runs, [config], repetitions=1, p95_sla_seconds=20.0
        )[0]

        self.assertFalse(aggregate["p95_sla_met"])
        self.assertFalse(aggregate["eligible_for_selection"])

    def test_temporal_audit_rejects_real_stage_mixing_pattern(self) -> None:
        observation = {
            "ticket_id": 279,
            "ingresso_banco_em": "2026-07-21T16:39:01.534547-03:00",
            "primeira_reserva_wf06_em": "2026-07-21T16:39:00.000000-03:00",
            "primeira_decisao_ia_em": "2026-07-21T16:39:01.460293-03:00",
            "ultimo_update_terminal_em": "2026-07-21T16:40:02.184993-03:00",
        }

        audit = calibrar_vazao.audit_temporal_observations([observation])

        self.assertEqual(audit["latencias_negativas"], 1)
        self.assertEqual(audit["tickets_com_latencia_negativa"], [279])

    def test_temporal_audit_rejects_missing_timestamp_and_fifo_inversion(self) -> None:
        base = datetime(2026, 7, 21, 19, 0, tzinfo=timezone.utc)
        observations = [
            {
                "ticket_id": 1,
                "ordem_fifo_esperada": 1,
                "ingresso_banco_em": base,
                "primeira_reserva_wf06_em": base + timedelta(seconds=20),
                "primeira_decisao_ia_em": base + timedelta(seconds=30),
                "ultimo_update_terminal_em": base + timedelta(seconds=40),
            },
            {
                "ticket_id": 2,
                "ordem_fifo_esperada": 2,
                "ingresso_banco_em": base + timedelta(seconds=1),
                "primeira_reserva_wf06_em": base + timedelta(seconds=10),
                "primeira_decisao_ia_em": base + timedelta(seconds=31),
                "ultimo_update_terminal_em": base + timedelta(seconds=41),
            },
            {
                "ticket_id": 3,
                "ordem_fifo_esperada": 3,
                "ingresso_banco_em": base + timedelta(seconds=2),
                "primeira_reserva_wf06_em": None,
                "primeira_decisao_ia_em": base + timedelta(seconds=32),
                "ultimo_update_terminal_em": base + timedelta(seconds=42),
            },
        ]

        audit = calibrar_vazao.audit_temporal_observations(observations)

        self.assertEqual(audit["timestamps_ausentes"], 1)
        self.assertEqual(audit["violacoes_fifo_primeira_reserva"], 1)
        self.assertEqual(audit["tickets_com_timestamp_ausente"], [3])
        self.assertEqual(audit["tickets_com_violacao_fifo"], [2])

    def test_collect_result_uses_stable_clock_and_fails_closed(self) -> None:
        base = datetime(2026, 7, 21, 19, 0, tzinfo=timezone.utc)
        summary = {
            "total": 1,
            "total_medido": 1,
            "latencias_validas": 0,
            "warmup_descartado": 0,
            "terminal": 1,
        }
        quality = {
            "decisoes_total": 1,
            "erros_ia": 0,
            "probabilidades_invalidas": 0,
            "rate_limits_decisoes": 0,
            "tentativas_modelo_total": 1,
            "tentativas_modelo_falhas": 0,
            "retentativas_modelo": 0,
            "rate_limits_429": 0,
            "falhas_retentaveis": 0,
            "timeouts_modelo": 0,
            "fallbacks_utilizados": 0,
            "tentativas_modelo_inesperado": 0,
            "tentativas_proveniencia_invalida": 0,
            "retentativas_workflow": 0,
            "entradas_dlq": 0,
            "entradas_dlq_abertas": 0,
            "ciclos_wf06_metrificados": 1,
            "pico_pendentes": 1,
            "pico_reservados": 1,
            "liberacoes_wf06": 1,
            "reingressos_fila": 0,
        }
        observations = [
            {
                "ticket_id": 279,
                "ordem_ingresso": 1,
                "triagem_status": "TRIAGEM_MANUAL",
                "ingresso_banco_em": base + timedelta(seconds=2),
                "primeira_reserva_wf06_em": base + timedelta(seconds=1),
                "primeira_decisao_ia_em": base + timedelta(seconds=3),
                "ultimo_update_terminal_em": base + timedelta(seconds=4),
                "warmup": False,
                "espera_ingresso_banco_ate_primeira_decisao_ia_s": 1.0,
                "duracao_ingresso_banco_ate_ultimo_update_terminal_s": 2.0,
            }
        ]
        with patch.object(
            calibrar_vazao.checker,
            "query",
            side_effect=[[summary], [quality], observations],
        ) as query:
            metrics = calibrar_vazao.collect_result(
                "CALQ-REGRESSION",
                0,
                sample_model_provenance(),
            )

        metric_sql = query.call_args_list[0].args[0]
        observation_sql = query.call_args_list[2].args[0]
        quality_sql = query.call_args_list[1].args[0]
        self.assertIn("tp.criado_em AS ingresso_banco_em", metric_sql)
        self.assertIn(
            "COALESCE(tp.data_abertura,tp.criado_em) AS chave_fifo_em",
            metric_sql,
        )
        self.assertIn("i.run_id=%s", metric_sql)
        self.assertIn("RESERVAR_FILA", observation_sql)
        self.assertNotIn("primeira_decisao-fila_enfileirada_em", metric_sql)
        self.assertIn("FROM ia_tentativas_modelo", quality_sql)
        self.assertIn("FROM fila_ia_dead_letter", quality_sql)
        self.assertIn("FROM fila_ia_metricas", quality_sql)
        self.assertIn("WHERE t.run_id=p.run_id", quality_sql)
        self.assertIn("WHERE d.run_id=p.run_id", quality_sql)
        self.assertIn("WHERE m.run_id=p.run_id", quality_sql)
        self.assertIn("HTTP_429", quality_sql)
        self.assertFalse(metrics["success"])
        self.assertEqual(metrics["latencias_negativas"], 1)
        self.assertIn("não inclui o tempo anterior", metrics["definicao_latencia"])

        observations[0]["primeira_reserva_wf06_em"] = base + timedelta(
            seconds=2.5
        )
        stable_summary = {**summary, "latencias_validas": 1}
        with patch.object(
            calibrar_vazao.checker,
            "query",
            side_effect=[[stable_summary], [quality], observations],
        ):
            stable = calibrar_vazao.collect_result(
                "CALQ-STABLE",
                0,
                sample_model_provenance(),
            )
        self.assertTrue(stable["success"])

        retry_quality = {
            **quality,
            "tentativas_modelo_total": 2,
            "retentativas_modelo": 1,
        }
        with patch.object(
            calibrar_vazao.checker,
            "query",
            side_effect=[[stable_summary], [retry_quality], observations],
        ):
            retried = calibrar_vazao.collect_result(
                "CALQ-RETRY",
                0,
                sample_model_provenance(),
            )
        self.assertFalse(retried["success"])

    def test_compose_applies_scope_only_to_calibration_recreation(self) -> None:
        response = MagicMock()
        response.status = 200
        context = MagicMock()
        context.__enter__.return_value = response
        completed = SimpleNamespace(returncode=0, stderr="")
        with (
            patch.dict(
                os.environ,
                {
                    "FILA_IA_RUN_SCOPE": "STALE-SCOPE",
                    "IA_MODEL_LOCAL": "stale-model",
                },
            ),
            patch.object(
                calibrar_vazao.subprocess, "run", return_value=completed
            ) as run,
            patch.object(
                calibrar_vazao.urllib.request, "urlopen", return_value=context
            ),
        ):
            calibrar_vazao.compose_n8n(
                3,
                45,
                "CALQ-TEST-Q1-R1",
                "local-hybrid-v1.9.0",
            )
            scoped_env = run.call_args.kwargs["env"]
            calibrar_vazao.compose_n8n(3, 45, None)
            operational_env = run.call_args.kwargs["env"]

        self.assertEqual(scoped_env["FILA_IA_RUN_SCOPE"], "CALQ-TEST-Q1-R1")
        self.assertEqual(scoped_env["IA_MODEL_LOCAL"], "local-hybrid-v1.9.0")
        self.assertEqual(operational_env["FILA_IA_RUN_SCOPE"], "")
        self.assertNotIn("IA_MODEL_LOCAL", operational_env)

    def test_invalid_queue_scope_is_rejected_before_recreation(self) -> None:
        with patch.object(calibrar_vazao.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "run_scope inválido"):
                calibrar_vazao.compose_n8n(3, 45, "scope com espaço")
        run.assert_not_called()

    def test_live_queue_profile_capture_filters_secrets_and_preserves_values(self) -> None:
        completed = SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps(
                [
                    "FILA_IA_LOTE_TAMANHO=7",
                    "FILA_IA_INTERVALO_SEGUNDOS=13",
                    "FILA_IA_RUN_SCOPE=RUN-ANTERIOR",
                    "IA_MODEL_LOCAL=local-hybrid-v1.8.0",
                    "PGPASSWORD=nao-deve-sair",
                ]
            ),
        )
        with patch.object(
            calibrar_vazao.subprocess, "run", return_value=completed
        ):
            profile = calibrar_vazao.capture_n8n_queue_profile()

        self.assertEqual(
            profile,
            {
                "batch": 7,
                "interval_seconds": 13,
                "run_scope": "RUN-ANTERIOR",
                "model_version": "local-hybrid-v1.8.0",
            },
        )
        self.assertNotIn("PGPASSWORD", profile)

    def test_live_queue_profile_capture_rejects_failed_or_incomplete_inspect(
        self,
    ) -> None:
        failures = [
            SimpleNamespace(returncode=1, stderr="inspect failed", stdout=""),
            SimpleNamespace(returncode=0, stderr="", stdout="{}"),
            SimpleNamespace(
                returncode=0,
                stderr="",
                stdout=json.dumps(
                    [
                        "FILA_IA_LOTE_TAMANHO=3",
                        "FILA_IA_INTERVALO_SEGUNDOS=45",
                    ]
                ),
            ),
        ]
        for completed in failures:
            with self.subTest(completed=completed):
                with patch.object(
                    calibrar_vazao.subprocess,
                    "run",
                    return_value=completed,
                ):
                    with self.assertRaises(RuntimeError):
                        calibrar_vazao.capture_n8n_queue_profile()

    def test_queue_scheduler_lock_refuses_busy_wf06_and_closes_connection(
        self,
    ) -> None:
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"acquired": False}
        with patch.object(
            calibrar_vazao.checker,
            "connect_pg",
            return_value=connection,
        ):
            with self.assertRaisesRegex(RuntimeError, "não iniciou"):
                with calibrar_vazao.queue_scheduler_lock():
                    self.fail("a janela ocupada não pode ser adquirida")

        connection.close.assert_called_once_with()

    def test_queue_controller_restore_uses_exact_snapshot_under_lock(self) -> None:
        next_release = datetime(2026, 8, 18, tzinfo=timezone.utc)
        snapshot = {
            "proxima_liberacao_em": next_release,
            "intervalo_segundos": 17,
            "lote_tamanho": 2,
        }
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.rowcount = 1

        calibrar_vazao.restore_queue_controller(snapshot, connection=connection)

        sql, parameters = cursor.execute.call_args.args
        self.assertIn("UPDATE fila_ia_controle", sql)
        self.assertEqual(
            parameters,
            (next_release, 17, 2),
        )

    def test_queue_controller_capture_rejects_invalid_snapshot_before_mutation(
        self,
    ) -> None:
        valid_time = datetime(2026, 8, 18, tzinfo=timezone.utc)
        invalid_rows = [
            [],
            [{"proxima_liberacao_em": None, "intervalo_segundos": 17, "lote_tamanho": 2}],
            [{"proxima_liberacao_em": valid_time, "intervalo_segundos": None, "lote_tamanho": 2}],
            [{"proxima_liberacao_em": valid_time, "intervalo_segundos": 17, "lote_tamanho": 0}],
            [{"proxima_liberacao_em": valid_time, "intervalo_segundos": 601, "lote_tamanho": 2}],
        ]
        for rows in invalid_rows:
            with self.subTest(rows=rows):
                with patch.object(calibrar_vazao.checker, "query", return_value=rows):
                    with self.assertRaises(RuntimeError):
                        calibrar_vazao.capture_queue_controller()

    def test_queue_controller_restore_rejects_missing_row(self) -> None:
        snapshot = {
            "proxima_liberacao_em": datetime(2026, 8, 18, tzinfo=timezone.utc),
            "intervalo_segundos": 17,
            "lote_tamanho": 2,
        }
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.rowcount = 0

        with self.assertRaisesRegex(RuntimeError, "não foi restaurado"):
            calibrar_vazao.restore_queue_controller(snapshot, connection=connection)

    def test_restore_state_orders_controller_before_operational_profile(self) -> None:
        runtime_profile = {
            "batch": 3,
            "interval_seconds": 45,
            "run_scope": None,
            "model_version": "local-hybrid-v1.8.0",
        }
        queue_controller = {
            "proxima_liberacao_em": datetime(2026, 8, 18, tzinfo=timezone.utc),
            "intervalo_segundos": 45,
            "lote_tamanho": 3,
        }
        events: list[str] = []
        connection = MagicMock()
        lock = MagicMock()
        lock.__enter__.return_value = connection
        with (
            patch.object(calibrar_vazao, "queue_scheduler_lock", return_value=lock),
            patch.object(
                calibrar_vazao,
                "restore_queue_controller",
                side_effect=lambda *args, **kwargs: events.append("controller_restore"),
            ),
            patch.object(
                calibrar_vazao,
                "assert_queue_controller",
                side_effect=lambda *args, **kwargs: events.append("controller_verify"),
            ),
            patch.object(
                calibrar_vazao,
                "compose_n8n",
                side_effect=lambda *args, **kwargs: events.append("runtime_restore"),
            ),
            patch.object(
                calibrar_vazao,
                "assert_runtime_profile",
                side_effect=lambda *args, **kwargs: events.append("runtime_verify"),
            ),
        ):
            calibrar_vazao.restore_calibration_state(
                runtime_profile,
                queue_controller,
            )

        self.assertEqual(
            events,
            [
                "controller_restore",
                "controller_verify",
                "runtime_restore",
                "runtime_verify",
            ],
        )

    def test_foreign_interference_audit_ignores_historical_closed_rows(self) -> None:
        base = datetime(2026, 7, 22, 4, 0, tzinfo=timezone.utc)
        database_row = {
            "entradas_fila_estranhas": 0,
            "reservas_wf06_estranhas": 0,
            "tickets_fila_estranhos_ativos": 0,
            "decisoes_ia_estranhas": 0,
            "tickets_estranhos": [],
        }
        with patch.object(
            calibrar_vazao.checker, "query", return_value=[database_row]
        ) as query:
            audit = calibrar_vazao.audit_foreign_interference(
                "CALQ-TEST-Q1-R1", base, base + timedelta(minutes=5)
            )

        sql = query.call_args.args[0]
        self.assertIn("proprios AS MATERIALIZED", sql)
        self.assertIn("dc.run_id=p.run_id", sql)
        self.assertIn("FROM proprios o WHERE o.ticket_id=tp.id", sql)
        self.assertIn("relogio.evento_em BETWEEN p.inicio AND p.fim", sql)
        self.assertIn("tp.triagem_status IN", sql)
        self.assertNotIn("triagem_status NOT IN", sql)
        self.assertFalse(audit["interferencia_estranha_detectada"])

    def test_foreign_interference_fails_repetition_and_registration_precedes_create(
        self,
    ) -> None:
        base = datetime(2026, 7, 22, 4, 0, tzinfo=timezone.utc)
        events: list[str] = []
        args = SimpleNamespace(
            warmup=0,
            concorrencia_ingresso=1,
            ingress_interval=0.0,
            ingress_profile="deterministic",
            timeout=60,
            poll=1,
        )
        item = {"id": "Q1", "batch": 3, "interval_seconds": 45, "repetition": 1}
        interference = {
            "interferencia_estranha_detectada": True,
            "tickets_estranhos": [999],
        }
        with (
            patch.object(
                calibrar_vazao,
                "register_experiment",
                side_effect=lambda *unused: events.append("register"),
            ),
            patch.object(
                calibrar_vazao,
                "database_now",
                side_effect=[base, base + timedelta(minutes=1)],
            ),
            patch.object(
                calibrar_vazao,
                "compose_n8n",
                side_effect=lambda *unused, **kwargs: events.append(
                    "compose:" + str(kwargs.get("run_scope"))
                ),
            ),
            patch.object(
                calibrar_vazao,
                "reset_queue_controller",
                side_effect=lambda *unused: events.append("reset"),
            ),
            patch.object(
                calibrar_vazao,
                "create_cases",
                side_effect=lambda *unused: events.append("create") or [],
            ),
            patch.object(
                calibrar_vazao.checker,
                "wait_processing",
                side_effect=lambda *unused, **kwargs: events.append("wait"),
            ),
            patch.object(
                calibrar_vazao, "collect_result", return_value={"success": True}
            ),
            patch.object(
                calibrar_vazao,
                "audit_foreign_interference",
                return_value=interference,
            ),
            patch.object(
                calibrar_vazao,
                "audit_queue_drain",
                return_value={"fila_vazia_ao_final": True},
            ),
        ):
            _, metrics = calibrar_vazao.execute_repetition(
                item,
                "CALQ-TEST-Q1-R1",
                2026062502,
                [],
                args,
                sample_model_provenance(),
            )

        self.assertEqual(
            events,
            [
                "register",
                "compose:CALQ-TEST-Q1-R1",
                "reset",
                "create",
                "wait",
            ],
        )
        self.assertFalse(metrics["success"])
        self.assertEqual(metrics["auditoria_interferencia"], interference)

    def test_ingress_schedules_are_reproducible_and_distinct(self) -> None:
        deterministic = calibrar_vazao.build_ingress_offsets(
            4, 0.5, "deterministic", 123
        )
        poisson_first = calibrar_vazao.build_ingress_offsets(
            5, 0.5, "poisson", 123
        )
        poisson_second = calibrar_vazao.build_ingress_offsets(
            5, 0.5, "poisson", 123
        )
        poisson_other_seed = calibrar_vazao.build_ingress_offsets(
            5, 0.5, "poisson", 124
        )
        burst = calibrar_vazao.build_ingress_offsets(4, 99, "burst", 123)

        self.assertEqual(deterministic, [0.0, 0.5, 1.0, 1.5])
        self.assertEqual(poisson_first, poisson_second)
        self.assertNotEqual(poisson_first, poisson_other_seed)
        self.assertEqual(poisson_first, sorted(poisson_first))
        self.assertEqual(burst, [0.0, 0.0, 0.0, 0.0])

    def test_pacing_waits_before_submission_even_with_concurrency(self) -> None:
        with (
            patch.object(
                calibrar_vazao.time,
                "monotonic",
                side_effect=[10.25, 11.0],
            ),
            patch.object(calibrar_vazao.time, "sleep") as sleep,
        ):
            observed = calibrar_vazao.pace_submission(10.0, 1.0)

        sleep.assert_called_once_with(0.75)
        self.assertEqual(observed, 1.0)

    def test_ingress_timing_audit_detects_early_submission(self) -> None:
        audit = calibrar_vazao.audit_ingress_timing(
            [
                {
                    "case_id": "A",
                    "ingress_sequence": 1,
                    "scheduled_offset_s": 0.0,
                    "submitted_offset_s": 0.0,
                    "request_started_offset_s": 0.002,
                },
                {
                    "case_id": "B",
                    "ingress_sequence": 2,
                    "scheduled_offset_s": 1.0,
                    "submitted_offset_s": 0.98,
                    "request_started_offset_s": 0.981,
                },
            ],
            tolerance_seconds=0.005,
        )

        self.assertFalse(audit["cronograma_respeitado"])
        self.assertEqual(audit["submissoes_antecipadas"], 1)
        self.assertEqual(audit["tickets_antecipados"], ["B"])
        self.assertAlmostEqual(audit["duracao_planejada_ingresso_s"], 1.0)
        self.assertAlmostEqual(
            audit["duracao_observada_inicio_requisicoes_s"], 0.979
        )

    def test_burst_treatments_expand_protocol_sizes_25_50_100(self) -> None:
        treatments = calibrar_vazao.build_treatments(
            [{"id": "Q1", "batch": 3, "interval_seconds": 30}],
            ingress_profile="burst",
            tickets_per_repetition=12,
            burst_sizes=[25, 50, 100],
        )

        self.assertEqual(
            [item["id"] for item in treatments],
            ["Q1-B25", "Q1-B50", "Q1-B100"],
        )
        self.assertEqual(
            [item["tickets_per_repetition"] for item in treatments],
            [25, 50, 100],
        )
        self.assertTrue(all(item["ingress_profile"] == "burst" for item in treatments))

    def test_confirmation_phase_enforces_five_repetitions(self) -> None:
        args = SimpleNamespace(
            url="http://localhost",
            app_token="app",
            user="user",
            password=os.getenv("PROJECT_IC_TEST_PASSWORD", "fixture-not-a-secret"),
            fase="confirmacao",
            repeticoes=4,
        )

        with self.assertRaisesRegex(SystemExit, "pelo menos 5"):
            calibrar_vazao._run_calibration.__wrapped__(args)

    def test_queue_drain_is_scoped_and_fails_on_residual_ticket(self) -> None:
        row = {
            "ativos_do_run": 1,
            "ativos_estranhos": 0,
            "tickets_ativos_do_run": [42],
            "tickets_ativos_estranhos": [],
        }
        with patch.object(
            calibrar_vazao.checker, "query", return_value=[row]
        ) as query:
            audit = calibrar_vazao.audit_queue_drain("CALQ-TEST-Q1-R1")

        sql, parameters = query.call_args.args
        self.assertIn("WHERE run_id=%s", sql)
        self.assertEqual(parameters, ("CALQ-TEST-Q1-R1",))
        self.assertFalse(audit["fila_vazia_ao_final"])
        self.assertEqual(audit["tickets_ativos_do_run"], [42])

    def test_model_manifest_is_verified_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "bundle.joblib"
            bundle.write_bytes(b"frozen-bundle")
            manifest_path = root / "manifest.json"
            manifest = {
                "model_version": "local-hybrid-v1.9.0",
                "bundle_version": "local-hybrid-bundle-v1.9.0",
                "status": "DEVELOPMENT_CANDIDATE",
                "candidate_frozen": True,
                "evaluation_eligible": True,
                "test_data_used": False,
                "primary33_used": False,
                "scientifically_validated": False,
                "scientific_result": False,
                "thresholds": {"approved": True},
                "embedding": {
                    "model_id": "ibm-granite/granite-embedding-97m-multilingual-r2",
                    "dimension": 384,
                    "model_revision": "revision-frozen",
                    "model_tree_sha256": "d" * 64,
                },
                "bundle": {
                    "path": bundle.name,
                    "sha256": calibrar_vazao.file_sha256(bundle),
                },
                "manifest_payload_sha256": None,
            }
            manifest["manifest_payload_sha256"] = (
                calibrar_vazao.canonical_sha256(manifest)
            )
            manifest_path.write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )

            provenance = calibrar_vazao.validate_model_manifest(manifest_path)
            self.assertEqual(provenance["model_version"], "local-hybrid-v1.9.0")
            self.assertEqual(
                provenance["bundle_sha256"], calibrar_vazao.file_sha256(bundle)
            )

            manifest["model_version"] = "tampered"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "Auto-hash"):
                calibrar_vazao.validate_model_manifest(manifest_path)

    def test_local_runtime_preflight_matches_manifest_hashes(self) -> None:
        provenance = sample_model_provenance()
        health = {
            "alive": True,
            "decision_ready": True,
            "candidate_evaluation_eligible": True,
            "mode": "production",
            "service_version": "0.8.0",
            "artifacts": {
                "hybrid_bundle": {
                    "loaded": True,
                    "version": provenance["bundle_version"],
                }
            },
            "embedding": {
                "backend": "granite_embedding_pytorch_fp32",
                "dimension": 384,
                "model_revision": provenance["embedding"]["model_revision"],
                "model_tree_sha256": provenance["embedding"][
                    "model_tree_sha256"
                ],
                "fallback_used": False,
            },
        }
        probe = {
            "result": {"tipo": "MANUTENCAO"},
            "metadata": {
                "decision_path": "hybrid_model",
                "candidate_evaluation_eligible": True,
                "pipeline_evaluation_eligible": True,
                "fallback_used": False,
                "artifact": {
                    "version": provenance["bundle_version"],
                    "bundle_sha256": provenance["bundle_sha256"],
                    "manifest_payload_sha256": provenance[
                        "manifest_payload_sha256"
                    ],
                },
                "embedding": {
                    "backend": "granite_embedding_pytorch_fp32",
                    "runtime_backend": "pytorch_fp32",
                    "precision": "fp32",
                    "dimension": 384,
                    "model_revision": provenance["embedding"][
                        "model_revision"
                    ],
                    "model_tree_sha256": provenance["embedding"][
                        "model_tree_sha256"
                    ],
                },
            },
        }
        with patch.object(
            calibrar_vazao,
            "_request_json",
            side_effect=[health, probe],
        ) as request:
            result = calibrar_vazao.preflight_local_ai(
                "http://127.0.0.1:8090",
                "secret-token",
                provenance,
            )

        self.assertEqual(request.call_count, 2)
        self.assertTrue(all(result["health_gates"].values()))
        self.assertTrue(all(result["probe_gates"].values()))
        self.assertNotIn("secret-token", json.dumps(result))

    def test_local_runtime_preflight_rejects_other_bundle(self) -> None:
        provenance = sample_model_provenance()
        health = {
            "alive": True,
            "decision_ready": True,
            "candidate_evaluation_eligible": True,
            "mode": "production",
            "artifacts": {
                "hybrid_bundle": {
                    "loaded": True,
                    "version": "different-bundle",
                }
            },
            "embedding": {
                "backend": "granite_embedding_pytorch_fp32",
                "dimension": 384,
                "model_revision": provenance["embedding"]["model_revision"],
                "model_tree_sha256": provenance["embedding"][
                    "model_tree_sha256"
                ],
                "fallback_used": False,
            },
        }
        with patch.object(calibrar_vazao, "_request_json", return_value=health):
            with self.assertRaisesRegex(RuntimeError, "candidato congelado"):
                calibrar_vazao.preflight_local_ai(
                    "http://127.0.0.1:8090",
                    "secret-token",
                    provenance,
                )

    def test_nonempty_output_directory_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidencias"
            output.mkdir()
            (output / "calibracao_aprovada.json").write_text(
                "{}\n", encoding="utf-8"
            )

            with self.assertRaisesRegex(RuntimeError, "já contém evidências"):
                calibrar_vazao.prepare_output_dir(output)


if __name__ == "__main__":
    unittest.main()
