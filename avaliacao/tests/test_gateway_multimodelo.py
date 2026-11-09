from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / "n8n" / "workflows" / "Versão9"
SCRIPT_DIR = ROOT / "avaliacao" / "scripts"
for path in (WORKFLOW_DIR, SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from ai_gateway_builder import build_gateway_js  # noqa: E402
import conferir_gabarito  # noqa: E402


class TestGatewayMultimodelo(unittest.TestCase):
    def test_gateway_freezes_models_and_experimental_policy(self):
        for task in ("DEDUPLICACAO", "CLASSIFICACAO"):
            js = build_gateway_js(
                task=task,
                prompt="Responda JSON",
                schema={"type": "object"},
            )
            for marker in (
                "gemini-3.5-flash",
                "IA_MODEL_SECONDARY",
                "EXPERIMENT_MODEL_MISMATCH",
                "failoverRequested && !experimental && !benchmark",
                "parseRetryAfter",
                "http_status",
                "retry_after_seconds",
                "retryable",
                "error_type",
                "ia_http_status",
                "ia_retry_after_seconds",
                "ia_retryable",
                "ia_error_type",
                "LOCAL_AI_EMBED_BACKEND",
                "granite_embedding_pytorch_fp32",
                "LOCAL_AI_EMBED_MODEL_REVISION",
                "LOCAL_RUNTIME_MISMATCH",
                "LOCAL_DEVELOPMENT_FALLBACK",
                "LOCAL_SEMANTIC_METADATA_INVALID",
                "EXPERIMENT_ROLE_INVALID",
                "EXPERIMENT_MODEL_NOT_FROZEN",
                "BENCHMARK_CANDIDATE_SET_INVALID",
                "DEDUP_BENCHMARK_PAIRED_FROZEN",
            ):
                self.assertIn(marker, js)
            self.assertIn(
                "const roles = ['LOCAL','SECONDARY'];",
                js,
            )
            self.assertIn("if (role === 'LOCAL') return ['LOCAL'];", js)
            self.assertIn("envValue('IA_FIXED_MODEL_ROLE','LOCAL')", js)
            self.assertIn(
                "supportedRoles.includes(requestedRole) ? requestedRole : 'LOCAL'",
                js,
            )
            self.assertIn("const fixedProvider = providers[fixedRole] || providers.LOCAL;", js)
            self.assertNotIn("providers[fixedRole].model", js)
            self.assertNotIn("candidateCount", js)

    def test_generated_workflows_use_gateway_and_attempt_table(self):
        checks = (
            ("V9-WF02-Triagem.json", "IA: Verificar Duplicidade"),
            ("V9-WF03-Classificacao.json", "IA: Classificar"),
        )
        for filename, node_name in checks:
            workflow = json.loads((WORKFLOW_DIR / filename).read_text(encoding="utf-8"))
            node = next(item for item in workflow["nodes"] if item["name"] == node_name)
            self.assertEqual(node["type"], "n8n-nodes-base.code")
            self.assertIn("ia_tentativas_modelo", json.dumps(workflow, ensure_ascii=False))

    def test_operational_actions_require_persisted_ai_decision(self):
        cases = (
            (
                "V9-WF02-Triagem.json",
                "Normalizar Dedup",
                "PG: Registrar IA Dedup",
                "Decisão IA Persistida?",
                "Duplicado?",
                "Preparar Erro Persistência IA",
                "PG: Erro IA Dedup",
                "duplicidade",
            ),
            (
                "V9-WF03-Classificacao.json",
                "Normalizar Classificação",
                "PG: Registrar IA Classificação",
                "Decisão IA Classificação Persistida?",
                "Switch Classificação",
                "Preparar Erro Persistência IA Classif",
                "PG: Erro IA Classif",
                "classificacao",
            ),
        )
        for (
            filename,
            normalizer,
            recorder,
            gate,
            operational_node,
            persistence_error,
            terminal_error,
            payload_field,
        ) in cases:
            with self.subTest(filename=filename):
                workflow = json.loads(
                    (WORKFLOW_DIR / filename).read_text(encoding="utf-8")
                )
                connections = workflow["connections"]
                self.assertEqual(
                    [edge["node"] for edge in connections[normalizer]["main"][0]],
                    [recorder],
                )
                self.assertEqual(
                    [edge["node"] for edge in connections[recorder]["main"][0]],
                    [gate],
                )
                self.assertEqual(
                    [edge["node"] for edge in connections[gate]["main"][0]],
                    [operational_node],
                )
                self.assertEqual(
                    [edge["node"] for edge in connections[gate]["main"][1]],
                    [persistence_error],
                )
                self.assertEqual(
                    [
                        edge["node"]
                        for edge in connections[persistence_error]["main"][0]
                    ],
                    [terminal_error],
                )
                recorder_node = next(
                    node for node in workflow["nodes"] if node["name"] == recorder
                )
                self.assertEqual(recorder_node.get("onError"), "continueRegularOutput")
                query = recorder_node["parameters"]["query"]
                self.assertIn("AS ia_decisao_id", query)
                self.assertIn("AS chamado", query)
                self.assertIn(f"AS {payload_field}", query)
                self.assertIn("integerSql", query)
                error_source = next(
                    node
                    for node in workflow["nodes"]
                    if node["name"] == persistence_error
                )["parameters"]["jsCode"]
                self.assertIn("ia_error_type:'PERSISTENCE'", error_source)
                self.assertIn("ia_retryable:true", error_source)

    def test_workflows_separate_candidate_eligibility_from_confirmatory_claim(self):
        checks = (
            ("V9-WF02-Triagem.json", "PG: Registrar IA Dedup"),
            ("V9-WF03-Classificacao.json", "PG: Registrar IA Classificação"),
        )
        for filename, node_name in checks:
            workflow = json.loads((WORKFLOW_DIR / filename).read_text(encoding="utf-8"))
            node = next(item for item in workflow["nodes"] if item["name"] == node_name)
            query = str(node["parameters"]["query"])
            self.assertIn("scientificMetadata.candidate_evaluation_eligible===true", query)
            self.assertIn("scientificMetadata.pipeline_evaluation_eligible===true", query)
            self.assertIn("frozenCandidateValid && localPipelineEvaluationEligible", query)
            self.assertIn("confirmatory_result_validated", query)
            self.assertIn("local_decision_path", query)
            self.assertNotIn("frozenCandidateValid && localArtifactScientificEligible", query)
            self.assertNotIn("frozenCandidateValid && localCandidateEvaluationEligible", query)

    def test_specialized_asset_is_a_frozen_pipeline_rule_not_a_probability_score(self):
        gateway = build_gateway_js(
            task="CLASSIFICACAO",
            prompt="Responda JSON",
            schema={"type": "object"},
        )
        self.assertIn("'deterministic_specialized_asset'", gateway)

        for filename, recorder in (
            ("V9-WF02-Triagem.json", "PG: Registrar IA Dedup"),
            ("V9-WF03-Classificacao.json", "PG: Registrar IA Classificação"),
        ):
            workflow = json.loads(
                (WORKFLOW_DIR / filename).read_text(encoding="utf-8")
            )
            query = next(
                node for node in workflow["nodes"] if node["name"] == recorder
            )["parameters"]["query"]
            self.assertIn("'deterministic_specialized_asset'", query)
            self.assertIn("localDeterministicPathFrozen", query)

        sql = (ROOT / "database" / "init_v9.sql").read_text(encoding="utf-8")
        class_scores = sql.rsplit(
            "CREATE OR REPLACE VIEW vw_scores_classificacao AS", 1
        )[1].split("CREATE OR REPLACE VIEW vw_roc_classificacao AS", 1)[0]
        dedup_scores = sql.rsplit(
            "CREATE OR REPLACE VIEW vw_scores_deduplicacao AS", 1
        )[1].split("CREATE OR REPLACE VIEW vw_roc_deduplicacao AS", 1)[0]
        for scores in (class_scores, dedup_scores):
            self.assertIn("IN ('hybrid_model','hybrid_model_abstention')", scores)
            self.assertNotIn("deterministic_specialized_asset", scores)

    def test_experimental_history_is_prior_same_run_not_same_episode(self):
        workflow = json.loads(
            (WORKFLOW_DIR / "V9-WF02-Triagem.json").read_text(encoding="utf-8")
        )
        history_node = next(
            item for item in workflow["nodes"] if item["name"] == "PG: Histórico Dedup"
        )
        query = str(history_node["parameters"]["query"])
        self.assertIn("ON c.run_id=dc.run_id", query)
        self.assertIn("dc.id < c.dataset_row_id", query)
        self.assertNotIn("c.episode_id=dc.episode_id", query)

    @unittest.skipUnless(shutil.which("node"), "Node.js indisponível para executar payload")
    def test_benchmark_payload_freezes_same_20_candidate_pool_without_rank_leak(self):
        workflow = json.loads(
            (WORKFLOW_DIR / "V9-WF02-Triagem.json").read_text(encoding="utf-8")
        )
        source = next(
            item for item in workflow["nodes"] if item["name"] == "Montar Payload Dedup"
        )["parameters"]["jsCode"]
        current = {
            "id": 99,
            "titulo": "Lâmpada apagada",
            "descricao": "Sala 101",
            "localizacao": "Sala 101",
            "tipo_servico": "Elétrica",
            "ia_execution_mode": "BENCHMARK",
            "experiment_split": "TESTE",
        }
        history = [
            {
                "id": identifier,
                "titulo": title,
                "descricao": "Sala 101",
                "localizacao": "Sala 101",
                "tipo_servico": "Elétrica",
                "status_num": 1,
                "data_ultima_mudanca": f"2026-01-{day:02d}T10:00:00Z",
            }
            for identifier, title, day in ((30, "Luz", 3), (10, "Janela", 1), (20, "Tomada", 2))
        ]
        harness = f"""
const AsyncFunction=Object.getPrototypeOf(async function(){{}}).constructor;
const source={json.dumps(source)};
const current={json.dumps(current)};
const history={json.dumps(history)};
process.env.DEDUP_CANDIDATE_LIMIT='3';
process.env.DEDUP_LOCAL_TOP_K='2';
const input={{all:()=>history.map(json=>({{json}}))}};
const lookup=()=>({{first:()=>({{json:{{chamado:current}}}})}});
console.log=()=>{{}};
const fn=new AsyncFunction('$input','$',source);
const output=await fn(input,lookup);
process.stdout.write(JSON.stringify(output[0].json));
"""
        completed = subprocess.run(
            [shutil.which("node") or "node", "--input-type=module"],
            input=harness,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
            encoding="utf-8",
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["candidate_limit"], 20)
        self.assertEqual(payload["local_candidate_limit"], 20)
        self.assertEqual(payload["historico"], payload["historico_local"])
        self.assertEqual(payload["historico"], payload["historico_benchmark"])
        self.assertEqual(
            payload["candidate_policy"]["candidate_ids"],
            [item["id"] for item in payload["historico"]],
        )
        self.assertTrue(payload["candidate_policy"]["same_list_and_order"])
        self.assertTrue(
            all("_dedup_score" not in candidate for candidate in payload["historico"])
        )

    @unittest.skipUnless(shutil.which("node"), "Node.js indisponível para executar normalizador")
    def test_wf02_abstains_between_asymmetric_thresholds_and_on_blocking_gate(self):
        workflow = json.loads(
            (WORKFLOW_DIR / "V9-WF02-Triagem.json").read_text(encoding="utf-8")
        )
        source = next(
            item for item in workflow["nodes"] if item["name"] == "Normalizar Dedup"
        )["parameters"]["jsCode"]

        cases = [
            {"pd": 0.50, "decision": False, "gates": [], "abstain": True},
            {"pd": 0.20, "decision": False, "gates": [], "abstain": False},
            {"pd": 0.08, "decision": False, "gates": [], "abstain": False},
            {"pd": 0.95, "decision": True, "gates": [], "abstain": False},
            {
                "pd": 0.01,
                "decision": False,
                "gates": ["operational_abstention"],
                "abstain": True,
            },
            {
                "pd": 0.50,
                "decision": False,
                "gates": ["operational_abstention"],
                "abstain": True,
                "role": "LOCAL",
                "decision_path": "hybrid_model_abstention",
                "features": {
                    "duplicate_probability_before_abstention": 0.72,
                    "best_candidate_id": 10,
                },
                "semantic_pd": 0.72,
                "semantic_prediction": "DUPLICADO",
            },
        ]
        payload = {
            "chamado_atual": {"id": 99},
            "chamado_original": {"id": 99},
            "historico": [{"id": 10}],
        }
        harness = f"""
const AsyncFunction=Object.getPrototypeOf(async function(){{}}).constructor;
const source={json.dumps(source)};
const payload={json.dumps(payload)};
const cases={json.dumps(cases)};
process.env.IA_CONFIANCA_MINIMA='0.65';
process.env.DEDUP_POSITIVE_THRESHOLD='0.95';
process.env.DEDUP_NEGATIVE_THRESHOLD='0.08';
console.log=()=>{{}};
const lookup=()=>({{first:()=>({{json:payload}})}});
const results=[];
for (const item of cases) {{
  const result={{
    eh_duplicado:item.decision,
    chamado_referencia_id:item.decision ? 10 : null,
    justificativa:'smoke',caracteristicas_match:[],
    confianca:item.decision ? item.pd : 1-item.pd,
    probabilidades:{{duplicado:item.pd,nao_duplicado:1-item.pd}}
  }};
  const envelope={{
    ia_raw:result,
    ia_model_role:item.role || 'LOCAL',
    ia_attempts:[{{schema_ok:true,scientific_metadata:{{
      gates:item.gates,
      decision_path:item.decision_path || '',
      features:item.features || {{}}
    }}}}]
  }};
  const input={{first:()=>({{json:envelope}})}};
  const fn=new AsyncFunction('$input','$',source);
  const output=await fn(input,lookup);
  results.push(output[0].json);
}}
process.stdout.write(JSON.stringify(results));
"""
        completed = subprocess.run(
            [shutil.which("node") or "node", "--input-type=module"],
            input=harness,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
            encoding="utf-8",
        )
        results = json.loads(completed.stdout)
        for case, result in zip(cases, results):
            self.assertEqual(result["requer_revisao_dedup"], case["abstain"])
            self.assertEqual(result["abstencao_operacional_dedup"], case["abstain"])
            self.assertEqual(
                result["decisao_operacional_dedup"],
                "ABSTENCAO"
                if case["abstain"]
                else ("DUPLICADO" if case["decision"] else "NAO_DUPLICADO"),
            )
            if "semantic_pd" in case:
                self.assertAlmostEqual(
                    result["duplicidade"]["probabilidades_semanticas"]["duplicado"],
                    case["semantic_pd"],
                )
                self.assertEqual(
                    result["duplicidade"]["predicao_semantica"],
                    case["semantic_prediction"],
                )
                self.assertEqual(
                    result["duplicidade"]["probabilidades"]["duplicado"], 0.5
                )

        register_query = next(
            item for item in workflow["nodes"] if item["name"] == "PG: Registrar IA Dedup"
        )["parameters"]["query"]
        self.assertIn("predSemantica", register_query)
        self.assertNotIn("d.requer_revisao_dedup===true?'ABSTENCAO'", register_query)

    def test_dedup_sql_metrics_separate_abstention_from_confusion_matrix(self):
        sql = (ROOT / "database" / "init_v9.sql").read_text(encoding="utf-8")
        metrics = sql.split("CREATE OR REPLACE VIEW vw_metricas_deduplicacao AS", 1)[1]
        metrics = metrics.split("CREATE OR REPLACE VIEW vw_scores_deduplicacao AS", 1)[0]
        self.assertIn("AS abstencao", sql)
        self.assertIn("AS cobertura_automatica", metrics)
        self.assertIn("classe_predita='NAO_DUPLICADO'", metrics)
        self.assertNotIn("classe_predita<>'DUPLICADO'", metrics)

    @unittest.skipUnless(shutil.which("node"), "Node.js indisponível para executar normalizador")
    def test_wf03_preserves_semantic_class_and_separates_operational_abstention(self):
        workflow = json.loads(
            (WORKFLOW_DIR / "V9-WF03-Classificacao.json").read_text(encoding="utf-8")
        )
        source = next(
            item
            for item in workflow["nodes"]
            if item["name"] == "Normalizar Classificação"
        )["parameters"]["jsCode"]
        cases = [
            {
                "name": "semantic_manual",
                "raw": {
                    "tipo": "TRIAGEM_MANUAL",
                    "executor": "FISCAL",
                    "confianca": 0.8,
                    "probabilidades": {
                        "OBRA": 0.05,
                        "DEMO": 0.05,
                        "SOB_DEMANDA": 0.1,
                        "TRIAGEM_MANUAL": 0.8,
                    },
                },
                "gates": [],
            },
            {
                "name": "low_confidence_obra",
                "raw": {
                    "tipo": "OBRA",
                    "executor": "DDI_DG",
                    "confianca": 0.5,
                    "probabilidades": {
                        "OBRA": 0.5,
                        "DEMO": 0.2,
                        "SOB_DEMANDA": 0.2,
                        "TRIAGEM_MANUAL": 0.1,
                    },
                },
                "gates": [],
            },
            {
                "name": "blocking_gate_obra",
                "raw": {
                    "tipo": "OBRA",
                    "executor": "DDI_DG",
                    "confianca": 0.8,
                    "probabilidades": {
                        "OBRA": 0.8,
                        "DEMO": 0.05,
                        "SOB_DEMANDA": 0.05,
                        "TRIAGEM_MANUAL": 0.1,
                    },
                },
                "gates": ["operational_abstention"],
            },
            {
                "name": "explicit_review_demo",
                "raw": {
                    "tipo": "MANUTENCAO",
                    "executor": "DEMO",
                    "requer_triagem_manual": True,
                    "confianca": 0.8,
                    "probabilidades": {
                        "OBRA": 0.05,
                        "DEMO": 0.8,
                        "SOB_DEMANDA": 0.05,
                        "TRIAGEM_MANUAL": 0.1,
                    },
                },
                "gates": [],
            },
            {
                "name": "demo_without_team",
                "raw": {
                    "tipo": "MANUTENCAO",
                    "executor": "DEMO",
                    "confianca": 0.8,
                    "probabilidades": {
                        "OBRA": 0.05,
                        "DEMO": 0.8,
                        "SOB_DEMANDA": 0.05,
                        "TRIAGEM_MANUAL": 0.1,
                    },
                },
                "gates": [],
            },
            {
                "name": "local_missing_exact_location",
                "role": "LOCAL",
                "decision_path": "hybrid_model",
                "raw": {
                    "tipo": "MANUTENCAO",
                    "executor": "DEMO",
                    "confianca": 0.8,
                    "probabilidades": {
                        "OBRA": 0.05,
                        "DEMO": 0.8,
                        "SOB_DEMANDA": 0.05,
                        "TRIAGEM_MANUAL": 0.1,
                    },
                },
                "gates": ["operational_information_insufficient"],
                "features": {
                    "semantic_class_prediction": "DEMO",
                    "semantic_probabilities": {
                        "OBRA": 0.05,
                        "DEMO": 0.8,
                        "SOB_DEMANDA": 0.05,
                        "TRIAGEM_MANUAL": 0.1,
                    },
                    "operational_information_sufficient": False,
                    "serviceable_location": False,
                },
            },
            {
                "name": "local_hybrid_abstention_preserves_semantics",
                "role": "LOCAL",
                "decision_path": "hybrid_model_abstention",
                "raw": {
                    "tipo": "TRIAGEM_MANUAL",
                    "executor": "FISCAL",
                    "confianca": 0.66,
                    "probabilidades": {
                        "OBRA": 0.3,
                        "DEMO": 0.02,
                        "SOB_DEMANDA": 0.02,
                        "TRIAGEM_MANUAL": 0.66,
                    },
                },
                "gates": ["operational_abstention"],
                "features": {
                    "semantic_class_prediction": "OBRA",
                    "semantic_probabilities": {
                        "OBRA": 0.8,
                        "DEMO": 0.05,
                        "SOB_DEMANDA": 0.05,
                        "TRIAGEM_MANUAL": 0.1,
                    },
                    "operational_abstention": True,
                    "operational_information_sufficient": True,
                    "serviceable_location": True,
                },
            },
        ]
        harness = f"""
const AsyncFunction=Object.getPrototypeOf(async function(){{}}).constructor;
const source={json.dumps(source)};
const cases={json.dumps(cases)};
process.env.IA_CONFIANCA_MINIMA='0.65';
process.env.DEMO_EQUIPE_DISPONIVEL='false';
console.log=()=>{{}};
const payload={{chamado_modelo:{{id:303,titulo:'Teste',descricao:'Teste'}}}};
const lookup=()=>({{first:()=>({{json:payload}})}});
const results=[];
for (const item of cases) {{
  const envelope={{
    ia_raw:item.raw,
    ia_model_role:item.role || 'LOCAL',
    ia_attempts:[{{schema_ok:true,scientific_metadata:{{
      gates:item.gates,
      decision_path:item.decision_path || '',
      features:item.features || {{}}
    }}}}]
  }};
  const input={{first:()=>({{json:envelope}})}};
  const fn=new AsyncFunction('$input','$',source);
  const output=await fn(input,lookup);
  results.push({{name:item.name,...output[0].json}});
}}
process.stdout.write(JSON.stringify(results));
"""
        completed = subprocess.run(
            [shutil.which("node") or "node", "--input-type=module"],
            input=harness,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
            encoding="utf-8",
        )
        results = {item["name"]: item for item in json.loads(completed.stdout)}

        semantic = results["semantic_manual"]
        self.assertEqual(semantic["classificacao"]["classe_semantica"], "TRIAGEM_MANUAL")
        self.assertFalse(semantic["abstencao_operacional_classif"])
        self.assertEqual(semantic["decisao_operacional_classif"], "TRIAGEM_MANUAL")

        for name in ("low_confidence_obra", "blocking_gate_obra"):
            abstained = results[name]
            self.assertEqual(abstained["classificacao"]["classe_semantica"], "OBRA")
            self.assertTrue(abstained["abstencao_operacional_classif"])
            self.assertEqual(abstained["decisao_operacional_classif"], "ABSTENCAO")
            self.assertTrue(abstained["classificacao"]["abstained"])

        explicit = results["explicit_review_demo"]
        self.assertEqual(explicit["classificacao"]["classe_semantica"], "DEMO")
        self.assertTrue(explicit["abstencao_operacional_classif"])
        self.assertEqual(explicit["decisao_operacional_classif"], "ABSTENCAO")

        demo = results["demo_without_team"]
        self.assertEqual(demo["classificacao"]["classe_semantica"], "DEMO")
        # A disponibilidade da equipe é configuração congelada no workflow;
        # variáveis do processo Node não podem alterar o artefato publicado.
        self.assertEqual(demo["classificacao"]["rota_operacional"], "DEMO")
        self.assertFalse(demo["abstencao_operacional_classif"])

        missing_location = results["local_missing_exact_location"]
        self.assertEqual(missing_location["classificacao"]["classe_semantica"], "DEMO")
        self.assertEqual(
            missing_location["classificacao"]["rota_operacional"], "TRIAGEM_MANUAL"
        )
        self.assertTrue(missing_location["abstencao_operacional_classif"])
        self.assertEqual(missing_location["decisao_operacional_classif"], "ABSTENCAO")

        local_abstention = results["local_hybrid_abstention_preserves_semantics"]
        self.assertEqual(local_abstention["classificacao"]["classe_semantica"], "OBRA")
        self.assertEqual(
            local_abstention["classificacao"]["probabilidades_semanticas"]["OBRA"],
            0.8,
        )
        self.assertEqual(
            local_abstention["classificacao"]["probabilidades_operacionais"][
                "TRIAGEM_MANUAL"
            ],
            0.66,
        )
        self.assertEqual(local_abstention["decisao_operacional_classif"], "ABSTENCAO")

        register_query = next(
            item
            for item in workflow["nodes"]
            if item["name"] == "PG: Registrar IA Classificação"
        )["parameters"]["query"]
        self.assertIn("classeSemantica", register_query)
        self.assertNotIn("pred='ABSTENCAO'", register_query)
        self.assertNotIn("pred='DEMO_SEM_EQUIPE'", register_query)

    def test_classification_sql_excludes_only_operational_abstentions(self):
        sql = (ROOT / "database" / "init_v9.sql").read_text(encoding="utf-8")
        decisions = sql.rsplit(
            "CREATE OR REPLACE VIEW vw_decisoes_classificacao AS", 1
        )[1].split("CREATE OR REPLACE VIEW vw_matriz_confusao_classificacao AS", 1)[0]
        matrix = sql.rsplit(
            "CREATE OR REPLACE VIEW vw_matriz_confusao_classificacao AS", 1
        )[1].split(
            "CREATE OR REPLACE VIEW vw_metricas_assertividade_classificacao AS", 1
        )[0]
        self.assertIn(
            "NOT IN ('OBRA','DEMO','SOB_DEMANDA','TRIAGEM_MANUAL')", decisions
        )
        self.assertIn("output_normalizado->>'abstained'", decisions)
        self.assertNotIn("classe_predita = 'TRIAGEM_MANUAL'", decisions)
        self.assertIn("WHERE NOT abstencao", matrix)

    def test_probabilistic_metrics_exclude_local_deterministic_one_hot_rules(self):
        sql = (ROOT / "database" / "init_v9.sql").read_text(encoding="utf-8")
        class_scores = sql.rsplit(
            "CREATE OR REPLACE VIEW vw_scores_classificacao AS", 1
        )[1].split("CREATE OR REPLACE VIEW vw_roc_classificacao AS", 1)[0]
        dedup_scores = sql.rsplit(
            "CREATE OR REPLACE VIEW vw_scores_deduplicacao AS", 1
        )[1].split("CREATE OR REPLACE VIEW vw_roc_deduplicacao AS", 1)[0]
        class_pipeline = sql.rsplit(
            "CREATE OR REPLACE VIEW vw_kpi_classificacao AS", 1
        )[1].split("CREATE OR REPLACE VIEW vw_scores_classificacao AS", 1)[0]
        dedup_pipeline = sql.rsplit(
            "CREATE OR REPLACE VIEW vw_metricas_deduplicacao AS", 1
        )[1].split("CREATE OR REPLACE VIEW vw_scores_deduplicacao AS", 1)[0]

        for model_scores in (class_scores, dedup_scores):
            self.assertIn("local_candidate_evaluation_eligible", model_scores)
            self.assertIn("IN ('hybrid_model','hybrid_model_abstention')", model_scores)
            self.assertIn("probability_semantics", model_scores)
            self.assertIn("probabilidades_semanticas", model_scores)

        self.assertNotIn("THEN NOT (d.output_normalizado->>'abstained')::boolean", class_scores)

        # Class accuracy/coverage remain pipeline metrics and therefore retain
        # deterministic policy decisions instead of silently discarding them.
        self.assertNotIn("local_candidate_evaluation_eligible", class_pipeline)
        self.assertNotIn("local_candidate_evaluation_eligible", dedup_pipeline)

        for filename, node_name in (
            ("V9-WF02-Triagem.json", "PG: Registrar IA Dedup"),
            ("V9-WF03-Classificacao.json", "PG: Registrar IA Classificação"),
        ):
            workflow = json.loads((WORKFLOW_DIR / filename).read_text(encoding="utf-8"))
            query = next(
                item for item in workflow["nodes"] if item["name"] == node_name
            )["parameters"]["query"]
            self.assertIn("local_probability_semantics", query)
            self.assertIn("scientificMetadata?.probability_semantics", query)

    def test_confirmatory_metrics_require_normative_human_gold(self):
        sql = (ROOT / "database" / "init_v9.sql").read_text(encoding="utf-8")
        gold = sql.rsplit("CREATE OR REPLACE VIEW vw_gabarito_final AS", 1)[1].split(
            "CREATE OR REPLACE VIEW vw_decisoes_classificacao AS", 1
        )[0]
        classification = sql.rsplit(
            "CREATE OR REPLACE VIEW vw_decisoes_classificacao AS", 1
        )[1].split("CREATE OR REPLACE VIEW vw_matriz_confusao_classificacao AS", 1)[0]
        deduplication = sql.rsplit(
            "CREATE OR REPLACE VIEW vw_decisoes_deduplicacao AS", 1
        )[1].split("CREATE OR REPLACE VIEW vw_recall_candidatos_deduplicacao AS", 1)[0]
        confirmatory = sql.split(
            "CREATE OR REPLACE VIEW vw_decisoes_confirmatorias_elegiveis AS", 1
        )[1].split("DROP VIEW IF EXISTS vw_log_loss_deduplicacao", 1)[0]

        self.assertIn("AS gabarito_humano", gold)
        self.assertIn("AS gabarito_sintetico", gold)
        self.assertIn("'ORACULO_GABARITO'", gold)
        self.assertIn("LIKE 'SINTETICO_%'", gold)
        for view in (classification, deduplication):
            self.assertIn("g.gabarito_humano", view)
            self.assertIn("NOT IN ('TEST','TESTE','BENCHMARK')", view)
            self.assertIn("confirmatory_eligible", view)
            self.assertIn("scientific_result", view)
            self.assertIn("d.run_id IS NOT DISTINCT FROM g.run_id", view)
            self.assertIn("dc.run_id IS NOT DISTINCT FROM g.run_id", view)
        for marker in (
            "e.rotulos_validados=TRUE",
            "e.protocolo_rotulagem_validado=TRUE",
            "e.auditoria_humana_concluida=TRUE",
            "a.fonte_gabarito IN ('ADJUDICADO','REVISAO_HUMANA')",
        ):
            self.assertIn(marker, confirmatory)

        class_scores = sql.rsplit(
            "CREATE OR REPLACE VIEW vw_scores_classificacao AS", 1
        )[1].split("CREATE OR REPLACE VIEW vw_roc_classificacao AS", 1)[0]
        self.assertIn("FROM vw_decisoes_classificacao g", class_scores)
        self.assertIn("JOIN validas u ON u.id = g.ia_decisao_id", class_scores)

    @unittest.skipUnless(shutil.which("node"), "Node.js indisponível para validar sintaxe do gateway")
    def test_gateway_javascript_is_syntactically_valid(self):
        for task in ("DEDUPLICACAO", "CLASSIFICACAO"):
            js = build_gateway_js(
                task=task,
                prompt="Responda JSON",
                schema={"type": "object"},
            )
            wrapped = "async function gatewayN8n(){\n" + js + "\n}\n"
            checked = subprocess.run(
                [shutil.which("node") or "node", "--check"],
                input=wrapped,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                checked.returncode,
                0,
                msg=f"Gateway {task} contém JavaScript inválido:\n{checked.stderr}",
            )

    @unittest.skipUnless(shutil.which("node"), "Node.js indisponível para executar o gateway")
    def test_local_candidate_requires_frozen_pytorch_fp32_runtime_not_holdout_claim(self):
        js = build_gateway_js(
            task="DEDUPLICACAO",
            prompt="Responda JSON",
            schema={"type": "object"},
        )
        result_v9 = {
            "duplicidade": {
                "eh_duplicado": False,
                "chamado_referencia_id": None,
                "justificativa": "casos distintos",
                "caracteristicas_match": [],
                "confianca": 0.91,
                "probabilidades": {"duplicado": 0.09, "nao_duplicado": 0.91},
            }
        }
        metadata = {
            "fallback_used": False,
            # Candidato ainda não recebeu uma alegação confirmatória pós-holdout.
            "scientific_eligible": False,
            "candidate_evaluation_eligible": True,
            "pipeline_evaluation_eligible": True,
            "decision_path": "hybrid_model",
            "artifact": {"version": "local-hybrid-bundle-v1.8.0"},
            "embedding": {
                "backend": "granite_embedding_pytorch_fp32",
                "runtime_backend": "pytorch_fp32",
                "precision": "fp32",
                "dimension": 384,
                "model_revision": "835ad14087e140460703cf0fae09f97d469d65c2",
                "model_tree_sha256": "a" * 64,
                "fallback_used": False,
                "development_only": False,
                "scientific_eligible": True,
            },
        }

        def execute(
            response_metadata: dict,
            payload_override: dict | None = None,
        ) -> dict:
            payload = {
                "chamado_atual": {
                    "id": 9901,
                    "run_id": "BENCH-LOCAL-FROZEN",
                    "experiment_split": "TESTE",
                    "ia_execution_mode": "BENCHMARK",
                    "ia_fixed_model_role": "LOCAL",
                    "ia_expected_model": "local-hybrid-v1.8.0",
                },
                "historico_local": [],
                "historico": [],
                "historico_benchmark": [],
                "candidate_policy": {
                    "mode": "BENCHMARK_PAIRED_FROZEN",
                    "benchmark_paired": True,
                    "same_list_and_order": True,
                    "configured_remote_limit": 20,
                    "configured_local_limit": 20,
                    "candidate_ids": [],
                },
            }
            if payload_override:
                payload.update(payload_override)
            env = {
                "IA_FAILOVER_ENABLED": "true",
                "IA_MODEL_LOCAL": "local-hybrid-v1.8.0",
                "LOCAL_AI_EMBED_BACKEND": "pytorch_fp32",
                "LOCAL_AI_EMBED_MODEL_REVISION": "835ad14087e140460703cf0fae09f97d469d65c2",
            }
            response = {"result": result_v9, "metadata": response_metadata}
            harness = f"""
const AsyncFunction=Object.getPrototypeOf(async function(){{}}).constructor;
const source={json.dumps(js)};
const payload={json.dumps(payload)};
const env={json.dumps(env)};
const response={json.dumps(response)};
let calls=0;
const helpers={{httpRequest:async()=>{{calls++;return response;}}}};
const input={{first:()=>({{json:payload}})}};
const fn=new AsyncFunction('$input','$env','helpers',source);
const output=await fn(input,env,helpers);
process.stdout.write(JSON.stringify({{calls,envelope:output[0].json}}));
"""
            completed = subprocess.run(
                [shutil.which("node") or "node", "--input-type=module"],
                input=harness,
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
                encoding="utf-8",
            )
            return json.loads(completed.stdout)

        accepted = execute(metadata)
        self.assertEqual(accepted["calls"], 1)
        self.assertEqual(accepted["envelope"]["ia_model_role"], "LOCAL")
        self.assertTrue(accepted["envelope"]["ia_attempts"][0]["schema_ok"])
        self.assertFalse(accepted["envelope"]["ia_attempts"][0]["scientific_metadata"]["scientific_eligible"])
        self.assertTrue(
            accepted["envelope"]["ia_attempts"][0]["scientific_metadata"][
                "candidate_evaluation_eligible"
            ]
        )
        self.assertFalse(accepted["envelope"]["ia_policy"]["failover_allowed"])
        self.assertTrue(accepted["envelope"]["ia_policy"]["paired_candidate_set_valid"])
        self.assertEqual(
            accepted["envelope"]["ia_attempts"][0]["input_profile"],
            "DEDUP_BENCHMARK_PAIRED_FROZEN",
        )

        deterministic_metadata = {
            "fallback_used": False,
            "scientific_eligible": False,
            "candidate_evaluation_eligible": False,
            "pipeline_evaluation_eligible": True,
            "decision_path": "deterministic_empty_history",
            "artifact": {
                "version": "local-hybrid-bundle-v1.8.0",
                "candidate_bundle_eligible": True,
            },
            "embedding": None,
            "gates": ["empty_history"],
        }
        deterministic = execute(deterministic_metadata)
        deterministic_attempt = deterministic["envelope"]["ia_attempts"][0]
        self.assertTrue(deterministic_attempt["schema_ok"])
        self.assertFalse(
            deterministic_attempt["scientific_metadata"][
                "candidate_evaluation_eligible"
            ]
        )
        self.assertTrue(
            deterministic_attempt["scientific_metadata"][
                "pipeline_evaluation_eligible"
            ]
        )

        invalid_metadata = json.loads(json.dumps(metadata))
        invalid_metadata["embedding"]["backend"] = "granite_embedding_openvino_int8"
        rejected = execute(invalid_metadata)
        attempt = rejected["envelope"]["ia_attempts"][0]
        self.assertFalse(attempt["schema_ok"])
        self.assertEqual(attempt["error_code"], "LOCAL_RUNTIME_MISMATCH")
        self.assertEqual(attempt["error_type"], "CONFIGURATION")
        self.assertFalse(attempt["retryable"])

        mismatched = execute(
            metadata,
            {
                "historico": [{"id": 10}],
                "historico_local": [{"id": 11}],
                "historico_benchmark": [{"id": 10}],
                "candidate_policy": {
                    "mode": "BENCHMARK_PAIRED_FROZEN",
                    "benchmark_paired": True,
                    "same_list_and_order": True,
                    "configured_remote_limit": 20,
                    "configured_local_limit": 20,
                    "candidate_ids": [10],
                },
            },
        )
        self.assertEqual(mismatched["calls"], 0)
        mismatch_attempt = mismatched["envelope"]["ia_attempts"][0]
        self.assertEqual(
            mismatch_attempt["error_code"], "BENCHMARK_CANDIDATE_SET_INVALID"
        )
        self.assertFalse(
            mismatched["envelope"]["ia_policy"]["paired_candidate_set_valid"]
        )

    def test_confirmatory_integrity_accepts_only_one_frozen_model(self):
        exp = {
            "run_id": "BENCH-V3-TEST",
            "split": "TESTE",
            "modelo_ia": "gemini-3.5-flash",
            "generation_config": {
                "ia_execution_mode": "BENCHMARK",
                "ia_failover_enabled": False,
                "ia_fixed_model_role": "PRIMARY",
                "ia_expected_model": "gemini-3.5-flash",
            },
        }
        final = {
            "esperadas": 2,
            "observadas": 2,
            "modelo_incorreto": 0,
            "papel_incorreto": 0,
            "fallback": 0,
            "cadeia_invalida": 0,
            "modo_incorreto": 0,
            "inelegiveis": 0,
            "gabaritos_observados": 2,
            "gabaritos_humanos": 2,
            "gabaritos_sinteticos": 0,
            "gabaritos_oraculo": 0,
        }
        attempts = {
            "total": 2,
            "modelo_incorreto": 0,
            "papel_incorreto": 0,
            "fallback": 0,
            "modelos_distintos": 1,
            "erros_politica": 0,
        }
        with patch.object(conferir_gabarito, "query", side_effect=[[final], [attempts]]):
            self.assertEqual(conferir_gabarito.confirmatory_model_integrity(exp), [])

        contaminated = {**attempts, "fallback": 1, "modelos_distintos": 2}
        with patch.object(conferir_gabarito, "query", side_effect=[[final], [contaminated]]):
            errors = conferir_gabarito.confirmatory_model_integrity(exp)
        self.assertTrue(any("misturaram modelos" in item for item in errors))
        self.assertTrue(any("fallback" in item for item in errors))

        contaminated_gold = {
            **final,
            "gabaritos_humanos": 1,
            "gabaritos_sinteticos": 1,
            "gabaritos_oraculo": 1,
        }
        with patch.object(
            conferir_gabarito,
            "query",
            side_effect=[[contaminated_gold], [attempts]],
        ):
            errors = conferir_gabarito.confirmatory_model_integrity(exp)
        self.assertTrue(any("fontes humanas normativas" in item for item in errors))
        self.assertTrue(any("oráculo=1" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
