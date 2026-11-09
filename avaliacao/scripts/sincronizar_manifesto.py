from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / "n8n" / "workflows" / "Versão9"
PROMPT_DIR = ROOT / "avaliacao" / "prompts"
SCHEMA_DIR = ROOT / "avaliacao" / "schemas"
MANIFEST_PATH = ROOT / "avaliacao" / "manifesto_modelo_prompts.json"
MODEL_CONFIG_PATH = ROOT / "avaliacao" / "config" / "modelos_ia_v1.json"
MODEL = "gemini-3.5-flash"


def load_workflow(filename: str) -> dict:
    return json.loads((WORKFLOW_DIR / filename).read_text(encoding="utf-8-sig"))


def gateway_node(workflow: dict, name: str) -> dict:
    return next(node for node in workflow["nodes"] if node.get("name") == name)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def gateway_contract_errors(
    label: str, node: dict, prompt: str, schema: dict
) -> list[str]:
    errors: list[str] = []
    js = str((node.get("parameters") or {}).get("jsCode") or "")
    if node.get("type") != "n8n-nodes-base.code":
        errors.append(f"{label} não usa nó Code do gateway")
    if f"const PROMPT_TEMPLATE = {json.dumps(prompt, ensure_ascii=False)};" not in js:
        errors.append(f"{label} != prompt canônico")
    schema_literal = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    if f"const RESPONSE_SCHEMA = {schema_literal};" not in js:
        errors.append(f"{label} != schema canônico")
    required = (
        "IA_MODEL_SECONDARY", "IA_MODEL_LOCAL",
        "gemini-3.5-flash", "local-hybrid-v1.8.0",
        "generativelanguage.googleapis.com/v1beta/models/",
        "EXPERIMENT_MODEL_MISMATCH",
        "failoverAllowed = failoverRequested && !experimental && !benchmark",
    )
    for marker in required:
        if marker not in js:
            errors.append(f"{label} sem contrato {marker}")
    if "candidateCount" in js:
        errors.append(f"{label} mantém candidateCount incompatível com Gemini 3.x")
    return errors


def expected_artifacts() -> tuple[dict[Path, str], dict, list[str]]:
    wf02 = load_workflow("V9-WF02-Triagem.json")
    wf03 = load_workflow("V9-WF03-Classificacao.json")
    dedup = gateway_node(wf02, "IA: Verificar Duplicidade")
    classif = gateway_node(wf03, "IA: Classificar")
    dedup_path = PROMPT_DIR / "prompt_deduplicacao_v9.1.txt"
    classif_path = PROMPT_DIR / "prompt_classificacao_v9.1.txt"
    dedup_schema_path = SCHEMA_DIR / "deduplicacao_v9.1.schema.json"
    classif_schema_path = SCHEMA_DIR / "classificacao_v9.1.schema.json"
    dedup_prompt = dedup_path.read_text(encoding="utf-8").rstrip("\r\n")
    classif_prompt = classif_path.read_text(encoding="utf-8").rstrip("\r\n")
    dedup_schema = json.loads(dedup_schema_path.read_text(encoding="utf-8"))
    classif_schema = json.loads(classif_schema_path.read_text(encoding="utf-8"))
    prompt_mismatches = gateway_contract_errors("WF02", dedup, dedup_prompt, dedup_schema)
    prompt_mismatches += gateway_contract_errors("WF03", classif, classif_prompt, classif_schema)
    model_config = json.loads(MODEL_CONFIG_PATH.read_text(encoding="utf-8"))
    files = {
        PROMPT_DIR / "LEIA-ME.txt": (
            "PASTA AVALIACAO/PROMPTS\n"
            "========================\n\n"
            "Fontes canônicas dos prompts implantados nos JSONs V9.\n"
            "Edite estes TXT, regenere os builders e execute\n"
            "sincronizar_manifesto.py. O script recusa qualquer divergência.\n"
            "Os hashes estão em\n"
            "avaliacao/manifesto_modelo_prompts.json.\n"
        ),
    }
    manifest = {
        "schema_version": "2.1.0",
        "model": MODEL,
        "model_ids": {
            "principal": model_config["models"]["LOCAL"]["model"],
            "secundario": model_config["models"]["SECONDARY"]["model"],
            "deduplicacao": model_config["models"]["LOCAL"]["model"],
            "classificacao": model_config["models"]["LOCAL"]["model"],
        },
        "provider_transport": (
            "Gateway Code do n8n: API local nativa, com Gemini generateContent "
            "REST como contingência operacional explícita"
        ),
        "generation_options": {
            "sampling": "provider_default",
            "local_profile": "granite97m-pytorch-fp32-tfidf-logreg-calibrated-v1.8.0",
            "remote_secondary_thinking_profile": "provider_default",
            "structured_output": "JSON Schema no Gemini",
        },
        "gateway_policy": {
            "operational_failover": model_config["operational_policy"]["sequence"],
            "confirmatory_one_model_per_run": True,
            "confirmatory_failover_enabled": False,
            "attempt_provenance_table": "ia_tentativas_modelo",
        },
        "prompt_versions": {
            "deduplicacao": "deduplicacao_v9.1-episodica",
            "classificacao": "classificacao_v9.1-episodica",
        },
        "prompt_sha256": {
            "deduplicacao": sha(dedup_prompt),
            "classificacao": sha(classif_prompt),
        },
        "schema_sha256": {
            "deduplicacao": sha(
                json.dumps(dedup_schema, ensure_ascii=False, sort_keys=True)
            ),
            "classificacao": sha(
                json.dumps(classif_schema, ensure_ascii=False, sort_keys=True)
            ),
        },
        "generation_seed_env": "IA_GENERATION_SEED",
        "model_policy_sha256": hashlib.sha256(MODEL_CONFIG_PATH.read_bytes()).hexdigest(),
        "gateway_builder_sha256": hashlib.sha256(
            (WORKFLOW_DIR / "ai_gateway_builder.py").read_bytes()
        ).hexdigest(),
        "workflow_sha256": {
            "WF02": hashlib.sha256((WORKFLOW_DIR / "V9-WF02-Triagem.json").read_bytes()).hexdigest(),
            "WF03": hashlib.sha256((WORKFLOW_DIR / "V9-WF03-Classificacao.json").read_bytes()).hexdigest(),
        },
        "dataset_version": "corpus-v3.0.0-episodico",
    }
    return files, manifest, prompt_mismatches


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files, manifest, prompt_mismatches = expected_artifacts()
    manifest_text = json.dumps(
        manifest, ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    if args.check:
        mismatches = prompt_mismatches + [
            str(path.relative_to(ROOT))
            for path, content in files.items()
            if not path.exists() or path.read_text(encoding="utf-8") != content
        ]
        if not MANIFEST_PATH.exists() or MANIFEST_PATH.read_text(
            encoding="utf-8"
        ) != manifest_text:
            mismatches.append(str(MANIFEST_PATH.relative_to(ROOT)))
        if mismatches:
            print("DIVERGENTE: " + ", ".join(mismatches))
            return 1
        print("OK: modelo, opções e prompts sincronizados")
        return 0
    if prompt_mismatches:
        print("DIVERGENTE: " + ", ".join(prompt_mismatches))
        print("Regenere WF02/WF03 a partir dos prompts canônicos.")
        return 1
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    for path, content in files.items():
        path.write_text(content, encoding="utf-8", newline="\n")
    MANIFEST_PATH.write_text(manifest_text, encoding="utf-8", newline="\n")
    print(f"[OK] Manifesto: {MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
