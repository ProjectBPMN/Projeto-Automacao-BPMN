from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "avaliacao" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import benchmark_pareado_local_gemini as paired  # noqa: E402


class PairedBenchmarkPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = paired.load_jsonl(paired.DEFAULT_DATASET)
        cls.audit = paired.validate_reserved_dataset(
            paired.DEFAULT_DATASET,
            paired.DEFAULT_DATASET_MANIFEST,
            cls.rows,
            require_confirmatory_eligible=False,
        )
        cls.local_candidate = paired.validate_local_candidate(
            paired.DEFAULT_LOCAL_MODEL_MANIFEST
        )
        cls.units = paired.build_units(cls.rows)

    def test_exposed_historical_test_corpus_is_not_confirmatory_holdout(self) -> None:
        with self.assertRaisesRegex(
            paired.BenchmarkGuardError, "não está elegível como holdout confirmatório"
        ):
            paired.validate_reserved_dataset(
                paired.DEFAULT_DATASET,
                paired.DEFAULT_DATASET_MANIFEST,
                self.rows,
            )

    def test_remote_registry_keeps_paid_deepseek_candidate_blocked(self) -> None:
        registry = json.loads(
            (ROOT / "avaliacao" / "config" / "modelos_ia_v1.json").read_text(
                encoding="utf-8"
            )
        )
        candidate = registry["remote_benchmark_candidates"]["DEEPSEEK_V4_FLASH"]
        self.assertEqual(candidate["model"], "deepseek-v4-flash")
        self.assertFalse(candidate["guaranteed_free_api_tier"])
        self.assertFalse(candidate["active_operational_role"])
        self.assertTrue(candidate["benchmark_role"].startswith("blocked_"))

    def test_sample_is_deterministic_independent_core_and_balanced(self) -> None:
        repeated = paired.build_units(self.rows)
        self.assertEqual(
            paired.canonical_sha256(self.units), paired.canonical_sha256(repeated)
        )
        self.assertEqual(len(self.units), 140)
        self.assertEqual(len({unit["narrative_core_sha256"] for unit in self.units}), 140)
        tasks = Counter(unit["task"] for unit in self.units)
        labels = Counter((unit["task"], unit["gold"]["decision"]) for unit in self.units)
        self.assertEqual(tasks, {"classification": 40, "deduplication": 100})
        self.assertEqual(labels[("classification", "OBRA")], 10)
        self.assertEqual(labels[("classification", "DEMO")], 10)
        self.assertEqual(labels[("classification", "SOB_DEMANDA")], 10)
        self.assertEqual(labels[("classification", "TRIAGEM_MANUAL")], 10)
        self.assertEqual(labels[("deduplication", "DUPLICADO")], 40)
        self.assertEqual(labels[("deduplication", "NAO_DUPLICADO")], 60)

    def test_shared_input_has_no_gold_and_dedup_candidates_are_fixed(self) -> None:
        id_map = {
            str(row["case_id"]): index for index, row in enumerate(self.rows, start=1)
        }
        by_id = {str(row["case_id"]): row for row in self.rows}
        for unit in self.units:
            rendered = paired.canonical_json(unit["shared_input"])
            self.assertNotIn("expected_", rendered)
            self.assertNotIn("rationale", rendered)
            self.assertEqual(
                unit["shared_input_sha256"],
                paired.canonical_sha256(unit["shared_input"]),
            )
            self.assertIn(rendered, unit["gemini_prompt"])
            if unit["task"] != "deduplication":
                continue
            candidates = unit["shared_input"]["candidates"]
            self.assertEqual(len(candidates), 20)
            self.assertEqual(len({item["id"] for item in candidates}), 20)
            source = by_id[unit["case_id"]]
            anchor_numeric = id_map[str(source["contrast_anchor_case_id"])]
            self.assertIn(anchor_numeric, {item["id"] for item in candidates})

    def test_smaller_budget_sample_remains_stratified_and_deterministic(self) -> None:
        units = paired.build_units(
            self.rows, classification_core_limit=20, dedup_core_limit=10
        )
        labels = Counter((unit["task"], unit["gold"]["decision"]) for unit in units)
        self.assertEqual(len(units), 30)
        self.assertEqual(labels[("classification", "OBRA")], 5)
        self.assertEqual(labels[("classification", "DEMO")], 5)
        self.assertEqual(labels[("classification", "SOB_DEMANDA")], 5)
        self.assertEqual(labels[("classification", "TRIAGEM_MANUAL")], 5)
        self.assertEqual(labels[("deduplication", "DUPLICADO")], 4)
        self.assertEqual(labels[("deduplication", "NAO_DUPLICADO")], 6)

    def test_budget_is_conservative_and_insufficient_budget_fails(self) -> None:
        requirements = paired.budget_requirements(self.units)
        self.assertEqual(requirements["remote_calls"], 140)
        self.assertGreater(requirements["remote_tokens_conservative"], 140 * 768)
        self.assertGreater(requirements["max_remote_tokens_per_call_conservative"], 768)
        with self.assertRaisesRegex(paired.BenchmarkGuardError, "Orçamento remoto insuficiente"):
            paired.preflight_budget(
                requirements,
                max_remote_calls=139,
                max_remote_tokens=requirements["remote_tokens_conservative"],
                max_rpm=10,
                max_tpm=1000000,
                max_remote_rpd=140,
            )

    def test_preflight_applies_explicit_quota_headroom(self) -> None:
        requirements = {
            "remote_calls": 2,
            "remote_tokens_conservative": 1200,
            "max_remote_tokens_per_call_conservative": 700,
        }
        budget = paired.preflight_budget(
            requirements,
            max_remote_calls=2,
            max_remote_tokens=2000,
            max_rpm=15,
            max_tpm=1000,
            max_remote_rpd=10,
            quota_utilization=0.80,
        )
        self.assertEqual(
            budget["effective_limits"],
            {"rpm": 12, "tpm": 800, "rpd_conservative_rolling_24h": 8},
        )

    def test_single_call_larger_than_effective_tpm_fails_before_execution(self) -> None:
        with self.assertRaisesRegex(paired.BenchmarkGuardError, "TPM efetivo"):
            paired.preflight_budget(
                {
                    "remote_calls": 1,
                    "remote_tokens_conservative": 900,
                    "max_remote_tokens_per_call_conservative": 900,
                },
                max_remote_calls=1,
                max_remote_tokens=1000,
                max_rpm=15,
                max_tpm=1000,
                max_remote_rpd=10,
                quota_utilization=0.80,
            )

    def test_plan_is_frozen_idempotently_and_never_overwritten(self) -> None:
        requirements = paired.budget_requirements(self.units)
        budget = paired.preflight_budget(
            requirements,
            max_remote_calls=140,
            max_remote_tokens=requirements["remote_tokens_conservative"],
            max_rpm=10,
            max_tpm=1000000,
            max_remote_rpd=140,
        )
        plan, units_bytes = paired.build_plan(
            dataset=paired.DEFAULT_DATASET,
            dataset_manifest=paired.DEFAULT_DATASET_MANIFEST,
            rows=self.rows,
            dataset_audit=self.audit,
            local_candidate=self.local_candidate,
            units=self.units,
            seed=paired.DEFAULT_SEED,
            realizations_per_core=1,
            classification_core_limit=40,
            dedup_core_limit=100,
            candidate_limit=20,
            gemini_model=paired.DEFAULT_MODEL,
            max_output_tokens_per_call=768,
            budget=budget,
            noninferiority_margin=None,
        )
        self.assertFalse(plan["scientific_status"]["scientific_result"])
        self.assertFalse(plan["scientific_status"]["confirmatory_claim_allowed"])
        self.assertFalse(plan["remote"]["fallback_enabled"])
        self.assertFalse(plan["remote"]["retry_enabled"])
        self.assertFalse(plan["noninferiority"]["pre_registered"])
        self.assertIsNone(plan["noninferiority"]["margin_local_minus_gemini"])
        critical = plan["critical_risk_comparison"]
        self.assertEqual(critical["analysis_type"], "PAIRED_DESCRIPTIVE_ONLY")
        self.assertFalse(critical["noninferiority_evaluated"])
        self.assertIsNone(critical["noninferiority_margin"])
        self.assertFalse(critical["confirmatory_claim_allowed"])
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "plan"
            _, _, reused = paired.freeze_plan(output, plan, units_bytes, execute=False)
            self.assertFalse(reused)
            _, _, reused = paired.freeze_plan(output, plan, units_bytes, execute=False)
            self.assertTrue(reused)
            changed = copy.deepcopy(plan)
            changed["paired_design"]["seed"] += 1
            with self.assertRaisesRegex(paired.BenchmarkGuardError, "diverge"):
                paired.freeze_plan(output, changed, units_bytes, execute=False)
            with self.assertRaisesRegex(paired.BenchmarkGuardError, "previamente congelado"):
                paired.freeze_plan(
                    Path(temporary) / "missing", plan, units_bytes, execute=True
                )

    def test_cli_requires_all_five_remote_limits(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                paired.parse_args([])

    def test_execute_requires_live_quota_billing_and_exclusive_window_gates(self) -> None:
        base = [
            "--development-paired",
            "--max-remote-calls",
            "140",
            "--max-remote-tokens",
            "2000000",
            "--max-rpm",
            "15",
            "--max-tpm",
            "1000000",
            "--max-remote-rpd",
            "1500",
            "--execute",
            "--confirm-remote-execution",
        ]
        with self.assertRaisesRegex(SystemExit, "active-quota-checked"):
            paired.main(base)
        with self.assertRaisesRegex(SystemExit, "billing-status-checked"):
            paired.main([*base, "--confirm-active-quota-checked"])
        with self.assertRaisesRegex(SystemExit, "exclusive-quota-window"):
            paired.main(
                [
                    *base,
                    "--confirm-active-quota-checked",
                    "--confirm-billing-status-checked",
                ]
            )



    def test_default_main_rejects_exposed_historical_test_corpus(self) -> None:
        requirements = paired.budget_requirements(self.units)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "frozen"
            with self.assertRaisesRegex(
                paired.BenchmarkGuardError,
                "não está elegível como holdout confirmatório",
            ):
                paired.main(
                    [
                        "--output-dir",
                        str(output),
                        "--max-remote-calls",
                        str(requirements["remote_calls"]),
                        "--max-remote-tokens",
                        str(requirements["remote_tokens_conservative"]),
                        "--max-rpm",
                        "10",
                        "--max-tpm",
                        "1000000",
                        "--max-remote-rpd",
                        str(requirements["remote_calls"]),
                    ]
                )
            self.assertFalse((output / paired.PLAN_FILENAME).exists())
            self.assertFalse((output / paired.UNITS_FILENAME).exists())
            self.assertFalse((output / paired.RESULTS_FILENAME).exists())


class PairedBenchmarkExecutionGuardsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        rows = paired.load_jsonl(paired.DEFAULT_DATASET)
        all_units = paired.build_units(rows)
        cls.units = [
            next(unit for unit in all_units if unit["task"] == "classification"),
            next(unit for unit in all_units if unit["task"] == "deduplication"),
        ]

    def test_sliding_limiter_enforces_rpm_and_reserved_tpm(self) -> None:
        now = [0.0]
        sleeps: list[float] = []

        def clock() -> float:
            return now[0]

        def sleeper(seconds: float) -> None:
            sleeps.append(seconds)
            now[0] += seconds

        limiter = paired.SlidingMinuteQuotaLimiter(
            max_rpm=2,
            max_tpm=100,
            clock=clock,
            sleeper=sleeper,
        )
        self.assertEqual(limiter.acquire(40), 0.0)
        self.assertEqual(limiter.acquire(40), 0.0)
        waited = limiter.acquire(30)
        self.assertGreaterEqual(waited, 60.0)
        self.assertEqual(len(sleeps), 1)
        self.assertEqual(len(limiter.events), 1)

    def test_sliding_limiter_rejects_one_call_above_tpm(self) -> None:
        limiter = paired.SlidingMinuteQuotaLimiter(max_rpm=12, max_tpm=100)
        with self.assertRaisesRegex(paired.BenchmarkGuardError, "excede o TPM"):
            limiter.acquire(101)

    def test_preflight_refuses_before_any_transport_call(self) -> None:
        calls: list[str] = []

        def transport(url: str, headers: dict, payload: dict, timeout: float) -> tuple[int, dict]:
            calls.append(url)
            return 500, {}

        requirements = paired.budget_requirements(self.units)
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(paired.BenchmarkGuardError, "Orçamento remoto insuficiente"):
                paired.run_execution(
                    self.units,
                    gemini_model=paired.DEFAULT_MODEL,
                    local_model="local-hybrid-v1.1.0",
                    gemini_key="dummy-secret",
                    local_base_url="http://127.0.0.1:8090",
                    local_token="",
                    max_remote_calls=1,
                    max_remote_tokens=requirements["remote_tokens_conservative"],
                    max_rpm=100,
                    max_tpm=1000000,
                    max_remote_rpd=2,
                    remote_attempt_ledger=Path(temporary) / "ledger.json",
                    plan_sha256="a" * 64,
                    max_output_tokens_per_call=768,
                    seed=paired.DEFAULT_SEED,
                    timeout_seconds=1,
                    post_json=transport,
                    sleeper=lambda _: None,
                )
        self.assertEqual(calls, [])

    def test_exactly_one_gemini_call_per_unit_and_no_fallback(self) -> None:
        calls: list[tuple[str, dict[str, str], dict]] = []
        remote_index = 0

        def transport(url: str, headers: dict, payload: dict, timeout: float) -> tuple[int, dict]:
            nonlocal remote_index
            calls.append((url, headers, payload))
            if "127.0.0.1" in url and "/classify" in url:
                return 200, {
                    "result": {
                        "tipo": "MANUTENCAO",
                        "executor": "DEMO",
                        "confianca": 0.8,
                    },
                    "metadata": {
                        "gates": [],
                        "candidate_evaluation_eligible": True,
                    },
                }
            if "127.0.0.1" in url and "/deduplicate" in url:
                return 200, {
                    "result": {
                        "eh_duplicado": False,
                        "chamado_referencia_id": None,
                        "confianca": 0.8,
                    },
                    "metadata": {
                        "gates": [],
                        "candidate_evaluation_eligible": True,
                    },
                }
            unit = self.units[remote_index]
            remote_index += 1
            decision = unit["gold"]["decision"]
            value = {
                "decision": decision,
                "confidence": 0.9,
                "rationale": "fixture",
            }
            if unit["task"] == "deduplication":
                value["reference_id"] = unit["gold"].get("reference_id")
                if decision == "NAO_DUPLICADO":
                    value["reference_id"] = None
            return 200, {
                "candidates": [
                    {"content": {"parts": [{"text": json.dumps(value)}]}}
                ],
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 5,
                    "totalTokenCount": 15,
                },
            }

        requirements = paired.budget_requirements(self.units)
        with tempfile.TemporaryDirectory() as temporary:
            ledger = Path(temporary) / "ledger.json"
            records = paired.run_execution(
                self.units,
                gemini_model=paired.DEFAULT_MODEL,
                local_model="local-hybrid-v1.1.0",
                gemini_key="dummy-secret-not-logged",
                local_base_url="http://127.0.0.1:8090",
                local_token="local-secret",
                max_remote_calls=2,
                max_remote_tokens=requirements["remote_tokens_conservative"],
                max_rpm=100000,
                max_tpm=1000000,
                max_remote_rpd=2,
                remote_attempt_ledger=ledger,
                plan_sha256="b" * 64,
                max_output_tokens_per_call=768,
                seed=paired.DEFAULT_SEED,
                timeout_seconds=1,
                post_json=transport,
                sleeper=lambda _: None,
            )
            ledger_payload = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(len(ledger_payload["attempts"]), 2)
            self.assertTrue(
                all(item["status"] == "COMPLETED" for item in ledger_payload["attempts"])
            )
        remote_calls = [item for item in calls if "googleapis.com" in item[0]]
        self.assertEqual(len(remote_calls), 2)
        self.assertTrue(
            all(
                item[0].endswith("gemini-3.5-flash:generateContent")
                for item in remote_calls
            )
        )
        self.assertEqual(len(records), 4)
        remote_records = [
            row for row in records if row["provider"] == paired.REMOTE_PROVIDER
        ]
        self.assertTrue(
            all(row.get("remote_quota_control", {}).get("effective_tpm") == 1000000 for row in remote_records)
        )
        serialized = json.dumps(records)
        self.assertNotIn("dummy-secret-not-logged", serialized)
        self.assertNotIn("local-secret", serialized)

    def test_invalid_local_preflight_blocks_every_gemini_call(self) -> None:
        calls: list[str] = []

        def transport(url: str, headers: dict, payload: dict, timeout: float) -> tuple[int, dict]:
            calls.append(url)
            if "127.0.0.1" in url:
                return 401, {"error": {"message": "token local inválido"}}
            return 200, {}

        requirements = paired.budget_requirements(self.units)
        with tempfile.TemporaryDirectory() as temporary:
            ledger = Path(temporary) / "ledger.json"
            with self.assertRaisesRegex(
                paired.BenchmarkExecutionAborted, "Pré-flight LOCAL falhou"
            ) as captured:
                paired.run_execution(
                    self.units,
                    gemini_model=paired.DEFAULT_MODEL,
                    local_model="local-hybrid-v1.8.0",
                    gemini_key="dummy-secret",
                    local_base_url="http://127.0.0.1:8090",
                    local_token="wrong-local-token",
                    max_remote_calls=2,
                    max_remote_tokens=requirements["remote_tokens_conservative"],
                    max_rpm=4,
                    max_tpm=1000000,
                    max_remote_rpd=2,
                    remote_attempt_ledger=ledger,
                    plan_sha256="c" * 64,
                    max_output_tokens_per_call=768,
                    seed=paired.DEFAULT_SEED,
                    timeout_seconds=1,
                    post_json=transport,
                    sleeper=lambda _: None,
                )
            self.assertEqual(captured.exception.phase, "LOCAL_PREFLIGHT")
            self.assertEqual(len(captured.exception.records), len(self.units))
            self.assertFalse(any("googleapis.com" in url for url in calls))
            self.assertFalse(ledger.exists())

    def test_remote_ledger_counts_started_attempts_and_enforces_rolling_cap(self) -> None:
        now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            ledger = Path(temporary) / "ledger.json"
            first = paired.reserve_remote_attempt(
                ledger,
                max_remote_rpd=2,
                model=paired.DEFAULT_MODEL,
                unit_id="PAIR-1",
                plan_sha256="d" * 64,
                now=now,
            )
            paired.complete_remote_attempt(
                ledger,
                first,
                http_status=200,
                error_code=None,
                now=now + timedelta(seconds=1),
            )
            paired.reserve_remote_attempt(
                ledger,
                max_remote_rpd=2,
                model=paired.DEFAULT_MODEL,
                unit_id="PAIR-2",
                plan_sha256="d" * 64,
                now=now + timedelta(seconds=2),
            )
            with self.assertRaisesRegex(
                paired.BenchmarkGuardError, "(?i)limite conservador"
            ):
                paired.reserve_remote_attempt(
                    ledger,
                    max_remote_rpd=2,
                    model=paired.DEFAULT_MODEL,
                    unit_id="PAIR-3",
                    plan_sha256="d" * 64,
                    now=now + timedelta(seconds=3),
                )
            payload = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["attempts"]), 2)
            self.assertEqual(payload["attempts"][0]["status"], "COMPLETED")
            self.assertEqual(
                payload["attempts"][1]["status"], "STARTED_CONSERVATIVE_COUNT"
            )

    def test_first_429_aborts_without_attempting_remaining_units(self) -> None:
        calls: list[str] = []

        def transport(url: str, headers: dict, payload: dict, timeout: float) -> tuple[int, dict]:
            calls.append(url)
            if "127.0.0.1" in url and "/classify" in url:
                return 200, {
                    "result": {
                        "tipo": "MANUTENCAO",
                        "executor": "DEMO",
                        "confianca": 0.99,
                    },
                    "metadata": {"pipeline_evaluation_eligible": True},
                }
            if "127.0.0.1" in url and "/deduplicate" in url:
                return 200, {
                    "result": {
                        "eh_duplicado": False,
                        "chamado_referencia_id": None,
                        "confianca": 0.99,
                        "probabilidades": {"duplicado": 0.01, "nao_duplicado": 0.99},
                    },
                    "metadata": {"pipeline_evaluation_eligible": True},
                }
            return 429, {
                "error": {
                    "status": "RESOURCE_EXHAUSTED",
                    "message": "quota exceeded",
                }
            }

        requirements = paired.budget_requirements(self.units)
        with tempfile.TemporaryDirectory() as temporary:
            ledger = Path(temporary) / "ledger.json"
            with self.assertRaisesRegex(
                paired.BenchmarkExecutionAborted, "HTTP 429"
            ) as captured:
                paired.run_execution(
                    self.units,
                    gemini_model=paired.DEFAULT_MODEL,
                    local_model="local-hybrid-v1.8.0",
                    gemini_key="dummy-secret",
                    local_base_url="http://127.0.0.1:8090",
                    local_token="local-token",
                    max_remote_calls=2,
                    max_remote_tokens=requirements["remote_tokens_conservative"],
                    max_rpm=4,
                    max_tpm=1000000,
                    max_remote_rpd=2,
                    remote_attempt_ledger=ledger,
                    plan_sha256="e" * 64,
                    max_output_tokens_per_call=768,
                    seed=paired.DEFAULT_SEED,
                    timeout_seconds=1,
                    post_json=transport,
                    sleeper=lambda _: None,
                )
            self.assertEqual(captured.exception.phase, "REMOTE_HTTP_429")
            self.assertEqual(len(captured.exception.records), len(self.units) + 1)
            remote_calls = [url for url in calls if "googleapis.com" in url]
            self.assertEqual(len(remote_calls), 1)
            payload = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["attempts"]), 1)
            self.assertEqual(payload["attempts"][0]["http_status"], 429)

    def test_first_transport_error_aborts_without_waiting_for_remaining_units(self) -> None:
        calls: list[str] = []

        def transport(url: str, headers: dict, payload: dict, timeout: float) -> tuple[int, dict]:
            calls.append(url)
            if "127.0.0.1" in url and "/classify" in url:
                return 200, {
                    "result": {
                        "tipo": "MANUTENCAO",
                        "executor": "DEMO",
                        "confianca": 0.99,
                    },
                    "metadata": {"pipeline_evaluation_eligible": True},
                }
            if "127.0.0.1" in url and "/deduplicate" in url:
                return 200, {
                    "result": {
                        "eh_duplicado": False,
                        "chamado_referencia_id": None,
                        "confianca": 0.99,
                        "probabilidades": {"duplicado": 0.01, "nao_duplicado": 0.99},
                    },
                    "metadata": {"pipeline_evaluation_eligible": True},
                }
            return 0, {
                "error": {
                    "status": "TRANSPORT_ERROR",
                    "message": "socket blocked",
                }
            }

        requirements = paired.budget_requirements(self.units)
        with tempfile.TemporaryDirectory() as temporary:
            ledger = Path(temporary) / "ledger.json"
            with self.assertRaisesRegex(
                paired.BenchmarkExecutionAborted, "Falha de transporte"
            ) as captured:
                paired.run_execution(
                    self.units,
                    gemini_model=paired.DEFAULT_MODEL,
                    local_model="local-hybrid-v1.8.0",
                    gemini_key="dummy-secret",
                    local_base_url="http://127.0.0.1:8090",
                    local_token="local-token",
                    max_remote_calls=2,
                    max_remote_tokens=requirements["remote_tokens_conservative"],
                    max_rpm=4,
                    max_tpm=1000000,
                    max_remote_rpd=2,
                    remote_attempt_ledger=ledger,
                    plan_sha256="f" * 64,
                    max_output_tokens_per_call=768,
                    seed=paired.DEFAULT_SEED,
                    timeout_seconds=1,
                    post_json=transport,
                    sleeper=lambda _: None,
                )
            self.assertEqual(captured.exception.phase, "REMOTE_TRANSPORT_ERROR")
            self.assertEqual(len(captured.exception.records), len(self.units) + 1)
            self.assertEqual(
                len([url for url in calls if "googleapis.com" in url]), 1
            )
            payload = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["attempts"]), 1)
            self.assertEqual(payload["attempts"][0]["http_status"], 0)

    def test_first_non_429_http_or_contract_error_aborts_without_retry(self) -> None:
        scenarios = (
            (
                401,
                {"error": {"status": "UNAUTHENTICATED", "message": "invalid"}},
                "REMOTE_HTTP_ERROR",
            ),
            (
                200,
                {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]},
                "REMOTE_CONTRACT_ERROR",
            ),
        )
        requirements = paired.budget_requirements(self.units)
        for remote_status, remote_body, expected_phase in scenarios:
            with self.subTest(expected_phase=expected_phase):
                calls: list[str] = []

                def transport(
                    url: str, headers: dict, payload: dict, timeout: float
                ) -> tuple[int, dict]:
                    calls.append(url)
                    if "127.0.0.1" in url and "/classify" in url:
                        return 200, {
                            "result": {
                                "tipo": "MANUTENCAO",
                                "executor": "DEMO",
                                "confianca": 0.99,
                            },
                            "metadata": {"pipeline_evaluation_eligible": True},
                        }
                    if "127.0.0.1" in url and "/deduplicate" in url:
                        return 200, {
                            "result": {
                                "eh_duplicado": False,
                                "chamado_referencia_id": None,
                                "confianca": 0.99,
                                "probabilidades": {
                                    "duplicado": 0.01,
                                    "nao_duplicado": 0.99,
                                },
                            },
                            "metadata": {"pipeline_evaluation_eligible": True},
                        }
                    return remote_status, remote_body

                with tempfile.TemporaryDirectory() as temporary:
                    with self.assertRaises(paired.BenchmarkExecutionAborted) as captured:
                        paired.run_execution(
                            self.units,
                            gemini_model=paired.DEFAULT_MODEL,
                            local_model="local-hybrid-v1.8.0",
                            gemini_key="dummy-secret",
                            local_base_url="http://127.0.0.1:8090",
                            local_token="local-token",
                            max_remote_calls=2,
                            max_remote_tokens=requirements[
                                "remote_tokens_conservative"
                            ],
                            max_rpm=100000,
                            max_tpm=1000000,
                            max_remote_rpd=2,
                            remote_attempt_ledger=Path(temporary) / "ledger.json",
                            plan_sha256="1" * 64,
                            max_output_tokens_per_call=768,
                            seed=paired.DEFAULT_SEED,
                            timeout_seconds=1,
                            post_json=transport,
                            sleeper=lambda _: None,
                        )
                    self.assertEqual(captured.exception.phase, expected_phase)
                    self.assertEqual(
                        len([url for url in calls if "googleapis.com" in url]), 1
                    )

    def test_secret_redaction_covers_google_key_shape(self) -> None:
        key = "AIza" + "A" * 32
        value = paired.redact(f"falha key={key}", [key])
        self.assertNotIn(key, value)
        self.assertIn("REDACTED", value)

    def test_secret_redaction_covers_openai_compatible_key_shape(self) -> None:
        key = "sk-" + "a" * 32
        value = paired.redact(f"falha key={key}", [])
        self.assertNotIn(key, value)
        self.assertIn("REDACTED_API_KEY", value)

    def test_duplicate_with_wrong_candidate_is_not_scored_correct(self) -> None:
        rows = paired.load_jsonl(paired.DEFAULT_DATASET)
        unit = next(
            item
            for item in paired.build_units(rows)
            if item["task"] == "deduplication"
            and item["gold"]["decision"] == "DUPLICADO"
        )
        wrong_reference = next(
            candidate["id"]
            for candidate in unit["shared_input"]["candidates"]
            if candidate["id"] != unit["gold"]["reference_id"]
        )
        record = paired._prediction_record(
            unit=unit,
            provider=paired.REMOTE_PROVIDER,
            model=paired.DEFAULT_MODEL,
            status=200,
            latency_ms=1.0,
            normalized=(True, "DUPLICADO", 0.9, False, wrong_reference, None),
            usage=None,
            raw_body={},
            secrets=[],
        )
        self.assertFalse(record["correct"])

    def test_intermediate_dedup_confidence_is_abstention_for_both_providers(self) -> None:
        unit = next(item for item in self.units if item["task"] == "deduplication")
        local = paired.normalize_local(
            unit,
            200,
            {
                "result": {
                    "eh_duplicado": False,
                    "chamado_referencia_id": None,
                    "confianca": 0.80,
                    "probabilidades": {"duplicado": 0.20, "nao_duplicado": 0.80},
                },
                "metadata": {
                    "gates": [],
                    "candidate_evaluation_eligible": True,
                },
            },
        )
        self.assertTrue(local[0])
        self.assertEqual(local[1], "TRIAGEM_MANUAL")
        self.assertTrue(local[3])

        remote_body = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    {
                                        "decision": "NAO_DUPLICADO",
                                        "reference_id": None,
                                        "confidence": 0.80,
                                        "rationale": "incerto",
                                    }
                                )
                            }
                        ]
                    }
                }
            ]
        }
        remote = paired.normalize_gemini(unit, 200, remote_body)
        self.assertTrue(remote[0])
        self.assertEqual(remote[1], "TRIAGEM_MANUAL")
        self.assertTrue(remote[3])

    def test_classification_triagem_is_semantic_class_not_abstention(self) -> None:
        all_units = paired.build_units(paired.load_jsonl(paired.DEFAULT_DATASET))
        unit = next(
            item
            for item in all_units
            if item["task"] == "classification"
            and item["gold"]["decision"] == "TRIAGEM_MANUAL"
        )
        local_body = {
            "result": {
                "tipo": "TRIAGEM_MANUAL",
                "executor": "FISCAL",
                "confianca": 0.94,
            },
            "metadata": {
                "candidate_evaluation_eligible": True,
                "pipeline_evaluation_eligible": True,
                "decision_path": "hybrid_model",
                "features": {
                    "semantic_class_prediction": "TRIAGEM_MANUAL",
                    "operational_abstention": False,
                },
            },
        }
        normalized_local = paired.normalize_local(unit, 200, local_body)
        self.assertTrue(normalized_local[0])
        self.assertEqual(normalized_local[1], "TRIAGEM_MANUAL")
        self.assertFalse(normalized_local[3])
        record = paired._prediction_record(
            unit=unit,
            provider=paired.LOCAL_PROVIDER,
            model="local-hybrid-v1.8.0",
            status=200,
            latency_ms=1.0,
            normalized=normalized_local,
            usage=None,
            raw_body=local_body,
            secrets=[],
        )
        self.assertEqual(record["predicted_class"], "TRIAGEM_MANUAL")
        self.assertFalse(record["operational_abstention"])
        self.assertTrue(record["routed_to_human"])
        self.assertTrue(record["correct"])

        remote_body = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    {
                                        "decision": "TRIAGEM_MANUAL",
                                        "confidence": 0.94,
                                        "rationale": "requer análise fiscal",
                                    }
                                )
                            }
                        ]
                    }
                }
            ]
        }
        normalized_remote = paired.normalize_gemini(unit, 200, remote_body)
        self.assertTrue(normalized_remote[0])
        self.assertEqual(normalized_remote[1], "TRIAGEM_MANUAL")
        self.assertFalse(normalized_remote[3])

    def test_metrics_separate_abstention_semantic_triage_and_human_route(self) -> None:
        records = [
            {
                "task": "classification",
                "ok": True,
                "decision": "TRIAGEM_MANUAL",
                "predicted_class": "TRIAGEM_MANUAL",
                "operational_abstention": False,
                "routed_to_human": True,
                "gold": {"decision": "TRIAGEM_MANUAL"},
                "reference_id": None,
                "latency_ms": 1.0,
            },
            {
                "task": "classification",
                "ok": True,
                "decision": "TRIAGEM_MANUAL",
                "predicted_class": "OBRA",
                "operational_abstention": True,
                "routed_to_human": True,
                "gold": {"decision": "OBRA"},
                "reference_id": None,
                "latency_ms": 1.0,
            },
            {
                "task": "classification",
                "ok": True,
                "decision": "DEMO",
                "predicted_class": "DEMO",
                "operational_abstention": False,
                "routed_to_human": False,
                "gold": {"decision": "DEMO"},
                "reference_id": None,
                "latency_ms": 1.0,
            },
        ]
        metrics = paired._provider_metrics(records)
        self.assertEqual(metrics["abstention_count"], 1)
        self.assertEqual(metrics["predicted_class_triagem_manual"], 1)
        self.assertEqual(metrics["routed_to_human_total"], 2)
        self.assertAlmostEqual(metrics["semantic_coverage"], 2 / 3)
        self.assertAlmostEqual(metrics["straight_through_automation_coverage"], 1 / 3)
        self.assertEqual(metrics["selective_accuracy"], 1.0)
        self.assertEqual(
            metrics["confusion"],
            {
                "DEMO->DEMO": 1,
                "OBRA->ABSTENCAO": 1,
                "TRIAGEM_MANUAL->TRIAGEM_MANUAL": 1,
            },
        )

    def test_abstention_does_not_increment_automatic_false_negative(self) -> None:
        unit = next(
            item
            for item in self.units
            if item["task"] == "deduplication"
        )
        positive_unit = copy.deepcopy(unit)
        positive_unit["gold"] = {"decision": "DUPLICADO", "reference_id": None}
        record = paired._prediction_record(
            unit=positive_unit,
            provider=paired.LOCAL_PROVIDER,
            model="local-hybrid-v1.1.0",
            status=200,
            latency_ms=1.0,
            normalized=(True, "TRIAGEM_MANUAL", 0.5, True, None, None),
            usage=None,
            raw_body={},
            secrets=[],
        )
        metrics = paired._provider_metrics([record])
        self.assertEqual(metrics["dedup_false_negatives"], 0)
        self.assertEqual(metrics["abstentions"], 1)
        self.assertEqual(metrics["automation_coverage"], 0.0)

    def test_paired_summary_rejects_pairs_when_either_arm_is_invalid(self) -> None:
        plan = {
            "manifest_payload_sha256": "a" * 64,
            "remote": {"budget": {}},
        }
        base = {
            "unit_id": "PAIR-INVALID",
            "task": "classification",
            "decision": None,
            "gold": {"decision": "DEMO"},
            "reference_id": None,
            "abstained": False,
            "latency_ms": 1.0,
            "usage": None,
        }
        summary = paired.summarize(
            [
                {**base, "provider": paired.LOCAL_PROVIDER, "ok": False},
                {**base, "provider": paired.REMOTE_PROVIDER, "ok": False},
            ],
            plan,
            expected_unit_ids=["PAIR-INVALID"],
        )
        pair = summary["paired"]
        self.assertEqual(pair["attempted_pairs"], 1)
        self.assertEqual(pair["jointly_valid_pairs"], 0)
        self.assertEqual(pair["complete_pairs"], 0)
        self.assertEqual(pair["invalid_pairs"], 1)
        self.assertIsNone(pair["mcnemar_exact_two_sided_p"])
        self.assertFalse(pair["mcnemar_evaluable"])
        self.assertEqual(summary["status"], "REJECTED_NO_JOINTLY_VALID_PAIRS")

    def test_partial_pairs_are_descriptive_and_block_inference(self) -> None:
        plan = {
            "manifest_payload_sha256": "b" * 64,
            "remote": {"budget": {}},
        }

        def record(unit_id: str, provider: str, ok: bool) -> dict:
            return {
                "unit_id": unit_id,
                "provider": provider,
                "task": "classification",
                "ok": ok,
                "decision": "DEMO" if ok else None,
                "predicted_class": "DEMO" if ok else None,
                "operational_abstention": False,
                "routed_to_human": False,
                "gold": {"decision": "DEMO"},
                "reference_id": None,
                "latency_ms": 1.0,
                "usage": None,
            }

        summary = paired.summarize(
            [
                record("PAIR-VALID", paired.LOCAL_PROVIDER, True),
                record("PAIR-VALID", paired.REMOTE_PROVIDER, True),
                record("PAIR-PARTIAL", paired.LOCAL_PROVIDER, True),
                record("PAIR-PARTIAL", paired.REMOTE_PROVIDER, False),
            ],
            plan,
            expected_unit_ids=["PAIR-VALID", "PAIR-PARTIAL"],
        )
        pair = summary["paired"]
        self.assertEqual(pair["attempted_pairs"], 2)
        self.assertEqual(pair["jointly_valid_pairs"], 1)
        self.assertEqual(pair["complete_pairs"], 1)
        self.assertEqual(pair["both_correct"], 1)
        self.assertEqual(pair["both_not_correct"], 0)
        self.assertIsNone(pair["mcnemar_exact_two_sided_p"])
        self.assertFalse(pair["mcnemar_evaluable"])
        self.assertEqual(
            pair["complete_case_point_estimate"]["estimate"], 0.0
        )
        self.assertTrue(pair["complete_case_point_estimate"]["descriptive_only"])
        self.assertEqual(
            summary["status"], "REJECTED_INCOMPLETE_OR_INVALID_PAIRS"
        )
        self.assertFalse(summary["noninferiority"]["evaluated"])
        self.assertEqual(
            summary["noninferiority"]["reason"], "PAIR_VALIDITY_GATE_FAILED"
        )
        composite = summary["conservative_availability_accuracy_composite"]
        self.assertEqual(composite["local_accuracy"], 1.0)
        self.assertEqual(composite["gemini_accuracy"], 0.5)
        self.assertEqual(composite["difference_local_minus_gemini"], 0.5)
        self.assertFalse(composite["noninferiority_decision_allowed"])

    def test_complete_verified_pairs_allow_paired_test_but_not_critical_h2(self) -> None:
        plan = {
            "manifest_payload_sha256": "c" * 64,
            "sample": {"units": 1},
            "paired_design": {"seed": paired.DEFAULT_SEED},
            "remote": {"budget": {}},
            "noninferiority": {
                "margin_local_minus_gemini": 0.05,
                "confidence": 0.95,
            },
        }
        base = {
            "unit_id": "PAIR-COMPLETE",
            "task": "classification",
            "ok": True,
            "decision": "DEMO",
            "predicted_class": "DEMO",
            "operational_abstention": False,
            "routed_to_human": False,
            "gold": {"decision": "DEMO"},
            "reference_id": None,
            "latency_ms": 1.0,
            "usage": None,
        }
        summary = paired.summarize(
            [
                {**base, "provider": paired.LOCAL_PROVIDER},
                {**base, "provider": paired.REMOTE_PROVIDER},
            ],
            plan,
            expected_unit_ids=["PAIR-COMPLETE"],
        )
        self.assertTrue(summary["stability"]["all_planned_pairs_present_and_valid"])
        self.assertTrue(summary["paired"]["mcnemar_evaluable"])
        self.assertTrue(summary["noninferiority"]["evaluated"])
        self.assertEqual(
            summary["noninferiority"]["estimand"],
            "overall_accuracy_local_minus_accuracy_gemini",
        )
        self.assertFalse(summary["noninferiority"]["critical_risk_h2_evaluated"])

    def test_missing_remote_record_blocks_noninferiority(self) -> None:
        plan = {
            "manifest_payload_sha256": "d" * 64,
            "sample": {"units": 1},
            "paired_design": {"seed": paired.DEFAULT_SEED},
            "remote": {"budget": {}},
            "noninferiority": {
                "margin_local_minus_gemini": 0.10,
                "confidence": 0.95,
            },
        }
        local = {
            "unit_id": "PAIR-MISSING-REMOTE",
            "provider": paired.LOCAL_PROVIDER,
            "task": "classification",
            "ok": True,
            "decision": "DEMO",
            "predicted_class": "DEMO",
            "operational_abstention": False,
            "routed_to_human": False,
            "gold": {"decision": "DEMO"},
            "reference_id": None,
            "latency_ms": 1.0,
            "usage": None,
        }
        summary = paired.summarize(
            [local],
            plan,
            expected_unit_ids=["PAIR-MISSING-REMOTE"],
        )
        self.assertEqual(summary["stability"]["remote"]["missing_records"], 1)
        self.assertFalse(summary["noninferiority"]["evaluated"])
        self.assertIsNone(summary["noninferiority"]["noninferior"])

    def test_development_pilot_never_evaluates_noninferiority(self) -> None:
        result = paired.paired_noninferiority(
            [0] * 40,
            {"margin_local_minus_gemini": 0.05, "confidence": 0.95},
            seed=paired.DEFAULT_SEED,
            descriptive_pilot=True,
        )
        self.assertFalse(result["evaluated"])
        self.assertEqual(result["reason"], "DESCRIPTIVE_DEVELOPMENT_PILOT_ONLY")
        self.assertIsNone(result["noninferior"])

    def test_complete_development_pilot_suppresses_inferential_tests(self) -> None:
        plan = {
            "manifest_payload_sha256": "e" * 64,
            "sample": {"units": 1},
            "paired_design": {
                "seed": paired.DEFAULT_SEED,
                "analysis_intent": "DESCRIPTIVE_DEVELOPMENT_PILOT",
            },
            "dataset": {"split": "DESENVOLVIMENTO"},
            "remote": {"budget": {}},
            "noninferiority": {
                "margin_local_minus_gemini": None,
                "confidence": 0.95,
            },
        }
        base = {
            "unit_id": "PILOT-1",
            "task": "classification",
            "ok": True,
            "decision": "DEMO",
            "predicted_class": "DEMO",
            "operational_abstention": False,
            "routed_to_human": False,
            "gold": {"decision": "DEMO"},
            "reference_id": None,
            "latency_ms": 1.0,
            "usage": None,
        }
        summary = paired.summarize(
            [
                {**base, "provider": paired.LOCAL_PROVIDER},
                {**base, "provider": paired.REMOTE_PROVIDER},
            ],
            plan,
            expected_unit_ids=["PILOT-1"],
        )
        self.assertEqual(summary["status"], "DESCRIPTIVE_PILOT_COMPLETE")
        self.assertIsNone(summary["paired"]["mcnemar_exact_two_sided_p"])
        self.assertTrue(
            summary["paired"]["mcnemar_suppressed_for_descriptive_pilot"]
        )
        self.assertFalse(summary["noninferiority"]["evaluated"])
        self.assertEqual(
            summary["noninferiority"]["reason"],
            "DESCRIPTIVE_DEVELOPMENT_PILOT_ONLY",
        )

    def test_development_cli_rejects_noninferiority_margin(self) -> None:
        with self.assertRaisesRegex(SystemExit, "exclusivamente descritivo"):
            paired.main(
                [
                    "--development-paired",
                    "--max-remote-calls",
                    "40",
                    "--max-remote-tokens",
                    "500000",
                    "--max-rpm",
                    "4",
                    "--max-tpm",
                    "250000",
                    "--max-remote-rpd",
                    "40",
                    "--noninferiority-margin",
                    "0.05",
                ]
            )

    def test_noninferiority_is_not_evaluated_without_explicit_margin(self) -> None:
        result = paired.paired_noninferiority(
            [0, 0, 1], None, seed=paired.DEFAULT_SEED
        )
        self.assertFalse(result["evaluated"])
        self.assertEqual(result["reason"], "MARGIN_NOT_PRE_REGISTERED")

    def test_noninferiority_uses_non_degenerate_paired_bound_when_margin_is_frozen(self) -> None:
        result = paired.paired_noninferiority(
            [0] * 40,
            {
                "margin_local_minus_gemini": 0.05,
                "confidence": 0.95,
            },
            seed=paired.DEFAULT_SEED,
        )
        self.assertTrue(result["evaluated"])
        self.assertEqual(result["estimate"], 0.0)
        self.assertLess(result["confidence_lower_bound_95_one_sided"], 0.0)
        self.assertFalse(result["noninferior"])

    def test_critical_risks_are_paired_and_descriptive_only(self) -> None:
        plan = {
            "manifest_payload_sha256": "f" * 64,
            "sample": {
                "units": 4,
                "label_counts": {
                    "deduplication:DUPLICADO": 2,
                    "classification:DEMO": 1,
                    "classification:SOB_DEMANDA": 1,
                },
            },
            "paired_design": {
                "seed": paired.DEFAULT_SEED,
                "analysis_intent": "DESCRIPTIVE_DEVELOPMENT_PILOT",
            },
            "dataset": {"split": "DESENVOLVIMENTO"},
            "remote": {"budget": {}},
            "noninferiority": {"margin_local_minus_gemini": None},
        }

        def record(
            unit_id: str,
            provider: str,
            *,
            task: str,
            gold: str,
            decision: str,
            routed_to_human: bool,
            predicted_class: str | None = None,
            abstained: bool = False,
            reference_id: int | None = None,
            gold_reference_id: int | None = None,
        ) -> dict[str, object]:
            return {
                "unit_id": unit_id,
                "provider": provider,
                "task": task,
                "ok": True,
                "decision": decision,
                "predicted_class": predicted_class,
                "operational_abstention": abstained,
                "abstained": abstained,
                "routed_to_human": routed_to_human,
                "gold": {
                    "decision": gold,
                    **(
                        {"reference_id": gold_reference_id}
                        if task == "deduplication"
                        else {}
                    ),
                },
                "reference_id": reference_id,
                "shared_input_sha256": unit_id.lower().ljust(64, "0")[:64],
                "latency_ms": 1.0,
                "usage": None,
            }

        records = [
            record(
                "D1",
                paired.LOCAL_PROVIDER,
                task="deduplication",
                gold="DUPLICADO",
                decision="NAO_DUPLICADO",
                routed_to_human=False,
                gold_reference_id=7,
            ),
            record(
                "D1",
                paired.REMOTE_PROVIDER,
                task="deduplication",
                gold="DUPLICADO",
                decision="DUPLICADO",
                routed_to_human=True,
                reference_id=7,
                gold_reference_id=7,
            ),
            record(
                "D2",
                paired.LOCAL_PROVIDER,
                task="deduplication",
                gold="DUPLICADO",
                decision="TRIAGEM_MANUAL",
                routed_to_human=True,
                abstained=True,
                gold_reference_id=8,
            ),
            record(
                "D2",
                paired.REMOTE_PROVIDER,
                task="deduplication",
                gold="DUPLICADO",
                decision="NAO_DUPLICADO",
                routed_to_human=False,
                gold_reference_id=8,
            ),
            record(
                "C1",
                paired.LOCAL_PROVIDER,
                task="classification",
                gold="DEMO",
                decision="OBRA",
                predicted_class="OBRA",
                routed_to_human=False,
            ),
            record(
                "C1",
                paired.REMOTE_PROVIDER,
                task="classification",
                gold="DEMO",
                decision="DEMO",
                predicted_class="DEMO",
                routed_to_human=False,
            ),
            record(
                "C2",
                paired.LOCAL_PROVIDER,
                task="classification",
                gold="SOB_DEMANDA",
                decision="TRIAGEM_MANUAL",
                predicted_class="TRIAGEM_MANUAL",
                routed_to_human=True,
            ),
            record(
                "C2",
                paired.REMOTE_PROVIDER,
                task="classification",
                gold="SOB_DEMANDA",
                decision="OBRA",
                predicted_class="OBRA",
                routed_to_human=False,
            ),
        ]
        summary = paired.summarize(
            records,
            plan,
            expected_unit_ids=["D1", "D2", "C1", "C2"],
        )
        critical = summary["critical_risk_strata"]
        self.assertEqual(
            critical["analysis_type"],
            "PAIRED_DESCRIPTIVE_CRITICAL_RISK_STRATIFICATION",
        )
        self.assertFalse(critical["inferential_test_performed"])
        self.assertFalse(critical["noninferiority_evaluated"])
        self.assertIsNone(critical["noninferiority_margin"])

        dedup = critical["strata"]["automatic_dedup_false_negative"]
        self.assertEqual(dedup["planned_opportunity_units_from_frozen_plan"], 2)
        self.assertEqual(dedup["observable_paired_units"], 2)
        self.assertEqual(dedup["local"]["event_count"], 1)
        self.assertEqual(dedup["gemini"]["event_count"], 1)
        self.assertEqual(dedup["risk_difference_local_minus_gemini"], 0.0)
        self.assertEqual(dedup["paired_event_table"]["local_only_event"], 1)
        self.assertEqual(dedup["paired_event_table"]["gemini_only_event"], 1)

        classification = critical["strata"]["automatic_maintenance_as_obra"]
        self.assertEqual(
            classification["planned_opportunity_units_from_frozen_plan"], 2
        )
        self.assertEqual(classification["observable_paired_units"], 2)
        self.assertEqual(classification["local"]["event_rate"], 0.5)
        self.assertEqual(classification["gemini"]["event_rate"], 0.5)
        self.assertFalse(classification["mcnemar_evaluated"])
        self.assertTrue(
            classification["zero_observed_events_does_not_imply_zero_risk"]
        )

    def test_critical_risk_does_not_treat_missing_pair_as_safe(self) -> None:
        plan = {
            "manifest_payload_sha256": "a" * 64,
            "sample": {
                "units": 1,
                "label_counts": {"deduplication:DUPLICADO": 1},
            },
            "paired_design": {"seed": paired.DEFAULT_SEED},
            "remote": {"budget": {}},
            "noninferiority": {"margin_local_minus_gemini": None},
        }
        local = {
            "unit_id": "D-MISSING",
            "provider": paired.LOCAL_PROVIDER,
            "task": "deduplication",
            "ok": True,
            "decision": "NAO_DUPLICADO",
            "operational_abstention": False,
            "routed_to_human": False,
            "gold": {"decision": "DUPLICADO", "reference_id": 2},
            "reference_id": None,
            "latency_ms": 1.0,
            "usage": None,
        }
        summary = paired.summarize(
            [local], plan, expected_unit_ids=["D-MISSING"]
        )
        stratum = summary["critical_risk_strata"]["strata"][
            "automatic_dedup_false_negative"
        ]
        self.assertEqual(stratum["identified_opportunity_units_from_records"], 1)
        self.assertEqual(stratum["observable_paired_units"], 0)
        self.assertFalse(stratum["all_planned_opportunity_units_observable"])
        self.assertEqual(stratum["invalid_or_incomplete_opportunity_pairs"], 1)
        self.assertIsNone(stratum["local"]["event_rate"])
        self.assertIsNone(stratum["risk_difference_local_minus_gemini"])

    def test_pair_contract_mismatch_blocks_all_paired_inference(self) -> None:
        plan = {
            "manifest_payload_sha256": "b" * 64,
            "sample": {"units": 1},
            "paired_design": {"seed": paired.DEFAULT_SEED},
            "remote": {"budget": {}},
            "noninferiority": {
                "margin_local_minus_gemini": 0.05,
                "confidence": 0.95,
            },
        }
        base = {
            "unit_id": "PAIR-MISMATCH",
            "task": "classification",
            "ok": True,
            "decision": "DEMO",
            "predicted_class": "DEMO",
            "operational_abstention": False,
            "routed_to_human": False,
            "reference_id": None,
            "latency_ms": 1.0,
            "usage": None,
        }
        summary = paired.summarize(
            [
                {
                    **base,
                    "provider": paired.LOCAL_PROVIDER,
                    "gold": {"decision": "DEMO"},
                },
                {
                    **base,
                    "provider": paired.REMOTE_PROVIDER,
                    "gold": {"decision": "SOB_DEMANDA"},
                },
            ],
            plan,
            expected_unit_ids=["PAIR-MISMATCH"],
        )
        self.assertFalse(summary["stability"]["all_planned_pairs_present_and_valid"])
        self.assertEqual(summary["stability"]["pair_contract_mismatch_count"], 1)
        self.assertIn(
            "PAIR_TASK_GOLD_OR_INPUT_HASH_MISMATCH",
            summary["stability"]["validity_blockers"],
        )
        self.assertEqual(summary["paired"]["jointly_valid_pairs"], 0)
        self.assertFalse(summary["noninferiority"]["evaluated"])
        composite = summary["conservative_availability_accuracy_composite"]
        self.assertEqual(composite["local_accuracy"], 0.0)
        self.assertEqual(composite["gemini_accuracy"], 0.0)


class LocalOnlyBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = paired.load_jsonl(paired.DEFAULT_DEV_DATASET)
        cls.audit = paired.validate_local_only_dataset(
            paired.DEFAULT_DEV_DATASET,
            paired.DEFAULT_DEV_DATASET_MANIFEST,
            cls.rows,
            allow_reserved=False,
        )
        cls.local_candidate = paired.validate_local_candidate(
            paired.DEFAULT_LOCAL_MODEL_MANIFEST
        )

    def test_full_development_design_has_expected_cores_and_realizations(self) -> None:
        units = paired.build_local_only_units(self.rows)
        repeated = paired.build_local_only_units(self.rows)
        self.assertEqual(paired.canonical_sha256(units), paired.canonical_sha256(repeated))
        self.assertEqual(len(units), 1240)
        tasks = Counter(unit["task"] for unit in units)
        self.assertEqual(tasks, {"classification": 640, "deduplication": 600})
        cores = Counter(unit["scenario_id"] for unit in units)
        self.assertEqual(len(cores), 248)
        self.assertEqual(set(cores.values()), {5})
        self.assertTrue(all("gemini_prompt" not in unit for unit in units))
        self.assertTrue(all("budget" not in unit for unit in units))

    def test_local_only_cli_needs_no_remote_caps_and_dry_run_calls_no_api(self) -> None:
        args = paired.parse_args(["--local-only"])
        self.assertTrue(args.local_only)
        self.assertIsNone(args.max_remote_calls)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "local-plan"
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = paired.main(
                    [
                        "--local-only",
                        "--output-dir",
                        str(output),
                        "--classification-cores",
                        "4",
                        "--dedup-cores",
                        "2",
                        "--realizations-per-core",
                        "1",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("chamadas_remotas=0", stdout.getvalue())
            self.assertTrue((output / paired.LOCAL_PLAN_FILENAME).is_file())
            self.assertFalse((output / paired.LOCAL_RESULTS_FILENAME).exists())

    def test_local_execution_never_uses_remote_and_preserves_abstention(self) -> None:
        all_units = paired.build_local_only_units(
            self.rows,
            realizations_per_core=1,
            classification_core_limit=4,
            dedup_core_limit=2,
        )
        units = [
            next(unit for unit in all_units if unit["task"] == "classification"),
            next(unit for unit in all_units if unit["task"] == "deduplication"),
        ]
        calls: list[str] = []

        def transport(url: str, headers: dict, payload: dict, timeout: float) -> tuple[int, dict]:
            calls.append(url)
            metadata = {
                "gates": ["operational_abstention"] if "deduplicate" in url else [],
                "features": {"runtime": "hybrid_joblib"},
                "candidate_evaluation_eligible": True,
                "pipeline_evaluation_eligible": True,
                "artifact": {"version": "fixture"},
            }
            if "classify" in url:
                return 200, {
                    "result": {
                        "tipo": "MANUTENCAO",
                        "executor": "DEMO",
                        "confianca": 0.9,
                    },
                    "metadata": metadata,
                }
            return 200, {
                "result": {
                    "eh_duplicado": False,
                    "chamado_referencia_id": None,
                    "confianca": 0.5,
                    "probabilidades": {"duplicado": 0.5, "nao_duplicado": 0.5},
                },
                "metadata": metadata,
            }

        records = paired.run_local_only_execution(
            units,
            local_model="local-hybrid-v1.1.0",
            local_base_url="http://127.0.0.1:8090",
            local_token="local-secret",
            timeout_seconds=1,
            post_json=transport,
        )
        self.assertEqual(len(calls), 2)
        self.assertTrue(all("127.0.0.1" in url for url in calls))
        dedup = next(row for row in records if row["task"] == "deduplication")
        self.assertTrue(dedup["abstained"])
        self.assertEqual(dedup["decision"], "TRIAGEM_MANUAL")
        self.assertEqual(dedup["decision_path"], "MODEL_ABSTENTION")
        self.assertNotIn("local-secret", json.dumps(records))

    def test_local_execution_requires_token_and_stops_on_first_invalid_response(self) -> None:
        units = paired.build_local_only_units(
            self.rows,
            realizations_per_core=1,
            classification_core_limit=4,
            dedup_core_limit=2,
        )[:2]
        with self.assertRaisesRegex(paired.BenchmarkGuardError, "Credencial"):
            paired.run_local_only_execution(
                units,
                local_model="fixture",
                local_base_url="http://127.0.0.1:8090",
                local_token="",
                timeout_seconds=1,
                post_json=lambda *_: (200, {}),
            )

        calls = 0

        def invalid_transport(*_: object) -> tuple[int, dict]:
            nonlocal calls
            calls += 1
            return 503, {"error": {"code": "LOCAL_BUSY", "message": "fixture"}}

        with self.assertRaises(paired.BenchmarkExecutionAborted) as captured:
            paired.run_local_only_execution(
                units,
                local_model="fixture",
                local_base_url="http://127.0.0.1:8090",
                local_token="secret",
                timeout_seconds=1,
                post_json=invalid_transport,
            )
        self.assertEqual(calls, 1)
        self.assertEqual(len(captured.exception.records), 1)
        self.assertEqual(captured.exception.phase, "LOCAL_ONLY_CONTRACT_ERROR")

    def test_local_summary_has_task_core_path_and_eligibility_strata(self) -> None:
        unit = paired.build_local_only_units(
            self.rows,
            realizations_per_core=1,
            classification_core_limit=4,
            dedup_core_limit=2,
        )[0]
        record = paired._prediction_record(
            unit=unit,
            provider=paired.LOCAL_PROVIDER,
            model="local-hybrid-v1.1.0",
            status=200,
            latency_ms=2.0,
            normalized=(True, unit["gold"]["decision"], 0.9, False, None, None),
            usage=None,
            raw_body={
                "metadata": {
                    "features": {"runtime": "hybrid_joblib"},
                    "candidate_evaluation_eligible": True,
                    "pipeline_evaluation_eligible": True,
                }
            },
            secrets=[],
        )
        plan, _ = paired.build_local_only_plan(
            dataset=paired.DEFAULT_DEV_DATASET,
            dataset_manifest=paired.DEFAULT_DEV_DATASET_MANIFEST,
            dataset_audit=self.audit,
            local_candidate=self.local_candidate,
            units=[unit],
            seed=paired.DEFAULT_SEED,
            realizations_per_core=1,
            classification_core_limit=4,
            dedup_core_limit=2,
            candidate_limit=20,
        )
        summary = paired.summarize_local_only([record], plan)
        self.assertFalse(summary["scientific_result"])
        self.assertIn(unit["task"], summary["metrics"]["by_task"])
        self.assertIn(unit["scenario_id"], summary["metrics"]["by_core"])
        self.assertIn("HYBRID_MODEL", summary["metrics"]["by_decision_path"])
        self.assertEqual(
            summary["metrics"]["eligibility_strata"]["pipeline_complete_system"]["metrics"]["total"],
            1,
        )
        self.assertEqual(
            summary["metrics"]["eligibility_strata"]["model_only"]["metrics"]["total"],
            1,
        )

    def test_resummarize_existing_is_offline_hashed_and_idempotent(self) -> None:
        record = {
            "unit_id": "LOCAL-DERIVED",
            "ordinal": 1,
            "task": "classification",
            "case_id": "DEV-DERIVED",
            "scenario_id": "DEV_CLS_TRIAGEM_MANUAL_001",
            "provider": paired.LOCAL_PROVIDER,
            "model": "local-hybrid-v1.8.0",
            "ok": True,
            "decision": "TRIAGEM_MANUAL",
            "confidence": 0.95,
            "abstained": True,
            "decision_path": "HYBRID_MODEL",
            "reference_id": None,
            "gold": {"decision": "TRIAGEM_MANUAL"},
            "correct": True,
            "http_status": 200,
            "latency_ms": 1.0,
            "usage": None,
            "runtime_provenance": {
                "candidate_evaluation_eligible": True,
                "pipeline_evaluation_eligible": True,
                "pipeline_eligibility_declared": True,
            },
        }
        plan = {
            "manifest_payload_sha256": "c" * 64,
            "runtime_source_provenance": {},
        }
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            (source / paired.LOCAL_RESULTS_FILENAME).write_text(
                paired.canonical_json(record) + "\n", encoding="utf-8"
            )
            (source / paired.LOCAL_PLAN_FILENAME).write_text(
                json.dumps(plan), encoding="utf-8"
            )
            destination, summary, reused = paired.resummarize_existing(source)
            self.assertFalse(reused)
            self.assertTrue(destination.is_file())
            self.assertEqual(summary["schema_version"], paired.SUMMARY_SCHEMA_VERSION)
            metrics = summary["metrics"]["all_contract_valid"]
            self.assertEqual(metrics["abstention_count"], 0)
            self.assertEqual(metrics["predicted_class_triagem_manual"], 1)
            self.assertEqual(metrics["routed_to_human_total"], 1)
            self.assertEqual(metrics["semantic_coverage"], 1.0)
            self.assertFalse(
                summary["metric_recalculation"]["inference_reexecuted"]
            )
            self.assertRegex(
                summary["metric_recalculation"]["source_predictions_sha256"],
                r"^[0-9a-f]{64}$",
            )
            second_path, second_summary, reused = paired.resummarize_existing(source)
            self.assertTrue(reused)
            self.assertEqual(second_path, destination)
            self.assertEqual(second_summary, summary)

    def test_reserved_local_requires_explicit_flag_and_one_shot_ledger(self) -> None:
        rows = paired.load_jsonl(paired.DEFAULT_DATASET)
        with self.assertRaisesRegex(paired.BenchmarkGuardError, "one-shot"):
            paired.validate_local_only_dataset(
                paired.DEFAULT_DATASET,
                paired.DEFAULT_DATASET_MANIFEST,
                rows,
                allow_reserved=False,
            )
        audit = paired.validate_local_only_dataset(
            paired.DEFAULT_DATASET,
            paired.DEFAULT_DATASET_MANIFEST,
            rows,
            allow_reserved=True,
        )
        with tempfile.TemporaryDirectory() as temporary:
            ledger = Path(temporary) / "once.json"
            paired._begin_reserved_once(
                ledger,
                dataset_sha256=audit["dataset_sha256"],
                plan_sha256="a" * 64,
            )
            with self.assertRaisesRegex(paired.BenchmarkGuardError, "já foi iniciada"):
                paired._begin_reserved_once(
                    ledger,
                    dataset_sha256=audit["dataset_sha256"],
                    plan_sha256="a" * 64,
                )


if __name__ == "__main__":
    unittest.main()
