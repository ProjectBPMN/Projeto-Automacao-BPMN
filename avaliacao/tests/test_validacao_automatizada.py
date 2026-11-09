from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "avaliacao" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import auditar_suficiencia_amostral as amostra  # noqa: E402
import conferir_gabarito as checker  # noqa: E402
import executar_avaliacao as runner  # noqa: E402
import gerar_dataset_avaliacao as generator  # noqa: E402
import testar_interfaces_web as browser_test  # noqa: E402


class TestSuficienciaAmostral(unittest.TestCase):
    def test_corpus_v3_counts_independent_narrative_cores(self) -> None:
        cases = amostra.load_jsonl(amostra.DEFAULT_DATASET)
        result = amostra.audit(
            cases,
            amostra.load_json(amostra.DEFAULT_MANIFEST),
            amostra.load_json(amostra.DEFAULT_PLAN),
        )

        units = result["independent_units"]
        self.assertEqual(result["nominal"]["tickets"], 1200)
        self.assertEqual(units["dedup_challenge_cores"], 100)
        self.assertEqual(units["dedup_duplicate_cores"], 40)
        self.assertEqual(units["dedup_nonduplicate_complete_cores"], 48)
        self.assertEqual(units["dedup_nonduplicate_critical_cores"], 12)
        self.assertEqual(units["classification_cores_by_class"], {
            "DEMO": 10,
            "OBRA": 10,
            "SOB_DEMANDA": 10,
            "TRIAGEM_MANUAL": 10,
        })
        self.assertEqual(
            result["precision_reference"]["required_independent_n_margin_10pp_worst_case"],
            97,
        )
        self.assertEqual(
            result["precision_reference"]["required_zero_false_positive_n_for_wilson_upper_5pct"],
            73,
        )
        self.assertEqual(
            result["precision_reference"]["required_zero_false_negative_n_for_wilson_upper_2pct"],
            189,
        )
        self.assertEqual(
            result["recommended_v4"]["gaps"]["dedup_duplicate_new_episodes"],
            149,
        )
        self.assertEqual(result["recommended_v4"]["additional_tickets"], 878)
        self.assertEqual(result["recommended_v4"]["recommended_total_tickets"], 2078)
        self.assertFalse(
            result["decision"]["sufficient_for_precise_per_class_scientific_estimates"]
        )


class TestSeparacaoDaEvidencia(unittest.TestCase):
    def test_status_helper_never_overwrites_invalidated_or_aborted_run(self) -> None:
        with patch.object(checker, "execute") as execute:
            checker.set_experiment_status("CALQ-INVALIDADO", "FALHOU")

        statement = execute.call_args.args[0]
        self.assertIn("status NOT LIKE 'INVALIDADO%%'", statement)
        self.assertIn("status NOT LIKE 'EXECUTION_ABORTED%%'", statement)

    def test_automated_validation_never_becomes_confirmatory(self) -> None:
        exp = {
            "split": "VALIDACAO",
            "rotulos_validados": True,
            "protocolo_rotulagem_validado": True,
            "auditoria_humana_concluida": True,
        }
        nature, scientific = checker.result_nature(exp)
        self.assertEqual(nature, "VALIDACAO AUTOMATIZADA NAO CONFIRMATORIA")
        self.assertFalse(scientific)

    def test_confirmatory_nature_requires_all_gates_and_model_integrity(self) -> None:
        exp = {"split": "TESTE"}
        nature, scientific = checker.result_nature(
            exp,
            {
                "rotulos_validados": True,
                "protocolo_rotulagem_validado": True,
                "auditoria_humana_concluida": True,
            },
            [],
        )
        self.assertEqual(nature, "BENCHMARK CONFIRMATORIO")
        self.assertTrue(scientific)

        nature, scientific = checker.result_nature(
            exp,
            {
                "rotulos_validados": True,
                "protocolo_rotulagem_validado": True,
                "auditoria_humana_concluida": True,
            },
            ["fallback detectado"],
        )
        self.assertEqual(nature, "BENCHMARK INCOMPLETO")
        self.assertFalse(scientific)

    def test_synthetic_gold_is_refused_for_confirmatory_split(self) -> None:
        with patch.object(checker, "experiment", return_value={"split": "TESTE"}):
            with self.assertRaisesRegex(RuntimeError, "Gabarito sintético"):
                checker.materialize_synthetic_gold("BENCH-TESTE")

    def test_generated_summary_names_review_requirement_unambiguously(self) -> None:
        source = (SCRIPTS / "gerar_dataset_avaliacao.py").read_text(encoding="utf-8")
        self.assertIn("## Requer revisão humana", source)
        self.assertNotIn("## Revisao Humana", source)

    def test_validation_experiment_freezes_primary_model_and_no_fallback(self) -> None:
        args = SimpleNamespace(
            perfil_operacional="COM_DEMO",
            confidence_threshold=0.65,
            split="VALIDACAO",
            run_id="VALIDACAO-TESTE",
            origem="VALIDACAO_AUTOMATIZADA_NAO_CONFIRMATORIA",
            dataset_version="dataset-v2-test",
            seed=123,
        )
        sql = generator.experiment_sql(args, "a" * 64)
        for marker in (
            "AUTOMATED_VALIDATION",
            "gemini-3.5-flash",
            "SYNTHETIC_GENERATOR",
            '"ia_failover_enabled": false',
            '"scientific_result": false',
            '"human_workflow_confirmations_preserved": true',
        ):
            self.assertIn(marker, sql)

    def test_validation_can_freeze_each_configured_model_without_fallback(self) -> None:
        configured = json.loads(
            generator.MODEL_CONFIG_PATH.read_text(encoding="utf-8")
        )["models"]
        for role in generator.MODEL_ROLES:
            with self.subTest(role=role):
                args = SimpleNamespace(
                    perfil_operacional="PADRAO",
                    confidence_threshold=0.65,
                    split="VALIDACAO",
                    run_id=f"VALIDACAO-{role}",
                    origem="VALIDACAO_AUTOMATIZADA_NAO_CONFIRMATORIA",
                    dataset_version="dataset-v2-test",
                    seed=123,
                    model_role=role,
                    scenario_set="stress2",
                )
                sql = generator.experiment_sql(args, "b" * 64)
                self.assertIn(f'"ia_fixed_model_role": "{role}"', sql)
                self.assertIn(
                    f'"ia_expected_model": "{configured[role]["model"]}"', sql
                )
                self.assertIn(
                    f'"ia_expected_provider": "{configured[role]["provider"]}"',
                    sql,
                )
                self.assertIn('"ia_failover_enabled": false', sql)
                self.assertIn("AUTOMATED_VALIDATION", sql)

    def test_executor_propagates_fixed_model_role_to_generator_and_manifest(self) -> None:
        self.assertEqual(runner.MODEL_ROLES, ("LOCAL", "SECONDARY"))
        for role in runner.MODEL_ROLES:
            with self.subTest(role=role):
                args = SimpleNamespace(
                    fase="validacao",
                    seed=20260715,
                    scenario_set="stress2",
                    model_role=role,
                )
                command = runner.build_generator_command(
                    args,
                    per_scenario=1,
                    run_id=f"VALIDACAO-{role}",
                    dataset_prefix=ROOT / "avaliacao" / "resultados" / "dummy",
                    threshold=0.65,
                )
                role_index = command.index("--model-role")
                self.assertEqual(command[role_index + 1], role)
                self.assertEqual(
                    command[command.index("--split") + 1], "VALIDACAO"
                )
                manifest = runner.code_manifest("validacao", role)
                expected = json.loads(
                    runner.MODEL_CONFIG.read_text(encoding="utf-8")
                )["models"][role]
                self.assertEqual(manifest["model_role"], role)
                self.assertEqual(manifest["model"], expected["model"])
                self.assertEqual(manifest["provider"], expected["provider"])
                frozen_files = set(manifest["files"])
                self.assertIn(
                    "local_ai\\artifacts\\local_hybrid_bundle.joblib",
                    frozen_files,
                )
                self.assertIn("local_ai\\inference.py", frozen_files)
                self.assertIn(
                    "n8n\\workflows\\Versão9\\ai_gateway_builder.py",
                    frozen_files,
                )
                self.assertIn(
                    "n8n\\workflows\\Versão9\\V9-WF02-Triagem.json",
                    frozen_files,
                )
                self.assertEqual(
                    manifest["evidence_nature"],
                    "AUTOMATED_TECHNICAL_NON_CONFIRMATORY",
                )
                self.assertFalse(manifest["oracle_is_human_review"])
                self.assertFalse(manifest["confirmatory_eligible"])

    def test_executor_blocks_confirmatory_benchmark_before_side_effects(self) -> None:
        args = SimpleNamespace(fase="benchmark", model_role="LOCAL")
        with patch.object(runner, "parse_args", return_value=args), patch.object(
            runner, "run"
        ) as run, patch.object(
            runner, "require_quiescent_queue"
        ) as queue:
            with self.assertRaisesRegex(
                SystemExit, "BENCHMARK_CONFIRMATORIO_BLOQUEADO"
            ):
                runner.main()
        run.assert_not_called()
        queue.assert_not_called()

    def test_executor_rejects_historical_primary_role(self) -> None:
        with self.assertRaisesRegex(SystemExit, "Papel não executável"):
            runner.require_supported_route("validacao", "PRIMARY")

    def test_executor_does_not_request_synthetic_gold_twice(self) -> None:
        source = (SCRIPTS / "executar_avaliacao.py").read_text(encoding="utf-8")
        self.assertNotIn('"--registrar-gabarito"', source)

    def test_benchmark_also_records_one_fixed_model_and_disables_fallback(self) -> None:
        args = SimpleNamespace(
            perfil_operacional="PADRAO",
            confidence_threshold=0.65,
            split="TESTE",
            run_id="BENCHMARK-SECONDARY",
            origem="AVALIACAO_V2_EPISODICA",
            dataset_version="dataset-v2-test",
            seed=123,
            model_role="SECONDARY",
            scenario_set="primary33",
        )
        sql = generator.experiment_sql(args, "c" * 64)
        self.assertIn('"ia_execution_mode": "BENCHMARK"', sql)
        self.assertIn('"ia_fixed_model_role": "SECONDARY"', sql)
        self.assertIn('"ia_failover_enabled": false', sql)
        self.assertIn('"ia_expected_model": "gemini-3.5-flash"', sql)

    def test_automated_completion_keeps_human_audit_false(self) -> None:
        with patch.object(
            checker, "pending_summary", return_value={"pendentes": 0}
        ), patch.object(checker, "execute") as execute:
            runner.finalize_automated_validation("VALIDACAO-TESTE")
        statement = execute.call_args.args[0]
        self.assertIn("CONCLUIDO_AUTOMATIZADO", statement)
        self.assertIn("auditoria_humana_concluida=FALSE", statement)
        self.assertIn('"scientific_result":false', statement)

    def test_automated_failure_is_closed_without_scientific_promotion(self) -> None:
        with patch.object(checker, "execute") as execute:
            runner.fail_automated_validation(
                "VALIDACAO-TESTE", "TimeoutError: fila nao drenou"
            )
        statement, params = execute.call_args.args
        self.assertIn("FALHOU_AUTOMATIZADO", statement)
        self.assertIn("auditoria_humana_concluida=FALSE", statement)
        self.assertIn("'scientific_result',FALSE", statement)
        self.assertIn("AUTOMATED_VALIDATION_FAILURE", statement)
        self.assertIn("model_attempt',FALSE", statement)
        self.assertEqual(params[0], "VALIDACAO-TESTE")
        self.assertEqual(params[-1], "VALIDACAO-TESTE")


class TestBrowserHelpers(unittest.TestCase):
    def test_basic_auth_decoder_never_needs_plaintext_artifact(self) -> None:
        import base64

        token = base64.b64encode(b"usuario:senha-segura").decode("ascii")
        self.assertEqual(
            browser_test.decode_basic_auth("Basic " + token),
            ("usuario", "senha-segura"),
        )
        self.assertIsNone(browser_test.decode_basic_auth("invalido"))

    def test_expected_workflow_inventory_has_all_six_v9_flows(self) -> None:
        self.assertEqual(len(browser_test.EXPECTED_WORKFLOWS), 6)
        self.assertIn("V9 - WF06 Fila IA", browser_test.EXPECTED_WORKFLOWS)


class TestWorkflowRetryTypes(unittest.TestCase):
    def test_retry_conditions_use_native_boolean_without_string_right_value(
        self,
    ) -> None:
        workflow_dir = ROOT / "n8n" / "workflows" / "Versão9"
        checks = (
            ("V9-WF02-Triagem.json", "Retry Dedup?"),
            ("V9-WF03-Classificacao.json", "Retry Classificação?"),
        )
        for filename, node_name in checks:
            workflow = json.loads(
                (workflow_dir / filename).read_text(encoding="utf-8")
            )
            node = next(
                item for item in workflow["nodes"] if item["name"] == node_name
            )
            condition = node["parameters"]["conditions"]["conditions"][0]
            self.assertEqual(
                condition["operator"],
                {"type": "boolean", "operation": "true"},
            )
            self.assertIn("=== 'PENDENTE_FILA_IA'", condition["leftValue"])
            self.assertNotIn("rightValue", condition)


class TestRegistroDatasetControle(unittest.TestCase):
    def test_psql_registration_stops_on_first_sql_error(self) -> None:
        source = (SCRIPTS / "gerar_dataset_avaliacao.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"ON_ERROR_STOP=1"', source)
        self.assertIn("verify_dataset_registration(args, len(dataset_rows))", source)
        self.assertIn('run_dataset_sql("BEGIN;\\n" + sql + "COMMIT;\\n"', source)

    def test_psql_registration_sends_utf8_bytes_on_windows(self) -> None:
        args = SimpleNamespace(
            postgres_container="glpi-dedup-db",
            postgres_user="triagem_user",
            postgres_db="triagem",
        )
        completed = SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        sql = "SELECT 'rampa de acessibilidade e divisória';"
        with patch.object(generator.subprocess, "run", return_value=completed) as mocked:
            generator.run_dataset_sql(sql, args, quiet=True)
        kwargs = mocked.call_args.kwargs
        self.assertEqual(kwargs["input"], sql.encode("utf-8"))
        self.assertNotIn("text", kwargs)

    def test_primary_33_distinguishes_units_from_glpi_tickets(self) -> None:
        cases = generator.generate_cases(
            30,
            20260715,
            split="VALIDACAO",
            scenario_set="primary33",
        )
        self.assertEqual(len(generator.PRIMARY_33_SCENARIO_IDS), 33)
        self.assertEqual(33 * 30, 990)
        self.assertEqual(len(cases), 1410)
        self.assertNotIn("D15", {case.scenario_id for case in cases})
        self.assertNotIn("C20", {case.scenario_id for case in cases})

    def test_primary33_varia_urgencia_de_forma_reprodutivel(self) -> None:
        first = generator.generate_cases(
            30,
            20260715,
            split="TESTE",
            scenario_set="primary33",
        )
        second = generator.generate_cases(
            30,
            20260715,
            split="TESTE",
            scenario_set="primary33",
        )
        first_urgencies = [case.urgency for case in first]
        self.assertEqual(first_urgencies, [case.urgency for case in second])
        self.assertGreaterEqual(len(set(first_urgencies)), 4)
        scenario_ids = {case.scenario_id for case in first}
        for scenario_id in scenario_ids - {"C19"}:
            scenario_urgencies = {
                case.urgency for case in first if case.scenario_id == scenario_id
            }
            self.assertGreaterEqual(len(scenario_urgencies), 2, scenario_id)
        self.assertEqual(
            {case.urgency for case in first if case.scenario_id == "C19"},
            {5},
        )

    def test_supplementary_stress_set_is_preserved(self) -> None:
        cases = generator.generate_cases(
            1,
            20260715,
            split="VALIDACAO",
            scenario_set="stress2",
        )
        self.assertEqual({case.scenario_id for case in cases}, {"D15", "C20"})
        self.assertEqual(len(cases), 3)


if __name__ == "__main__":
    unittest.main()
