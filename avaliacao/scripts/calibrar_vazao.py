from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import random
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from project_env import configured_value, load_project_env  # noqa: E402

load_project_env()

LOCAL_DOCKER_CONTEXT = os.getenv("DOCKER_CONTEXT", "desktop-linux")
os.environ["DOCKER_CONTEXT"] = LOCAL_DOCKER_CONTEXT

import conferir_gabarito as checker  # noqa: E402
import gerar_dataset_avaliacao as dataset  # noqa: E402
from isolamento_experimentos import serialized_experiment  # noqa: E402


CALIBRATION_MODEL_ROLE = "LOCAL"
CALIBRATION_EXECUTION_MODE = "CALIBRACAO"
CALIBRATION_PROTOCOL_VERSION = "calibracao-fila-v2.6.0"
QUEUE_SCHEDULER_LOCK_KEY = 9062026
INGRESS_PROFILES = ("deterministic", "poisson", "burst")
DEFAULT_BURST_SIZES = (25, 50, 100)
MINIMUM_REPETITIONS = {
    "rastreio": 3,
    "confirmacao": 5,
    "rajada": 3,
}


def canonical_sha256(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def evidence_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def validate_model_manifest(path: Path) -> dict:
    """Validate the frozen LOCAL candidate before any experimental mutation."""
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise RuntimeError(f"Manifesto LOCAL ausente: {resolved}")
    try:
        manifest = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Manifesto LOCAL inválido: {exc}") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("Manifesto LOCAL deve conter um objeto JSON")

    model_version = str(manifest.get("model_version") or "").strip()
    bundle_version = str(manifest.get("bundle_version") or "").strip()
    bundle_entry = manifest.get("bundle")
    thresholds = manifest.get("thresholds")
    embedding = manifest.get("embedding")
    if not model_version or not bundle_version:
        raise RuntimeError("Manifesto LOCAL não declara model_version/bundle_version")
    if not checker.ORACLE_RUN_RE.fullmatch(model_version):
        raise RuntimeError("model_version do manifesto LOCAL possui formato inválido")
    if not isinstance(bundle_entry, dict) or not isinstance(thresholds, dict):
        raise RuntimeError("Manifesto LOCAL não declara bundle/thresholds válidos")
    if not isinstance(embedding, dict):
        raise RuntimeError("Manifesto LOCAL não declara a proveniência do embedding")

    gates = {
        "candidate_frozen": manifest.get("candidate_frozen") is True,
        "evaluation_eligible": manifest.get("evaluation_eligible") is True,
        "thresholds_approved": thresholds.get("approved") is True,
        "test_data_unused": manifest.get("test_data_used") is False,
        "primary33_unused": manifest.get("primary33_used") is False,
        "scientific_claim_not_premature": (
            manifest.get("scientifically_validated") is False
            and manifest.get("scientific_result") is False
        ),
        "granite_384": (
            str(embedding.get("model_id") or "")
            == "ibm-granite/granite-embedding-97m-multilingual-r2"
            and int(embedding.get("dimension") or 0) == 384
        ),
        "embedding_revision_frozen": bool(
            str(embedding.get("model_revision") or "").strip()
        ),
        "embedding_tree_hash_frozen": (
            len(str(embedding.get("model_tree_sha256") or "").strip()) == 64
            and all(
                character in "0123456789abcdef"
                for character in str(
                    embedding.get("model_tree_sha256") or ""
                ).strip().lower()
            )
        ),
    }
    if not all(gates.values()):
        raise RuntimeError(f"Candidato LOCAL não passou os gates: {gates}")

    expected_payload_hash = str(
        manifest.get("manifest_payload_sha256") or ""
    ).strip().lower()
    payload_copy = json.loads(json.dumps(manifest))
    payload_copy["manifest_payload_sha256"] = None
    observed_payload_hash = canonical_sha256(payload_copy)
    if not expected_payload_hash or not hmac.compare_digest(
        expected_payload_hash, observed_payload_hash
    ):
        raise RuntimeError("Auto-hash do manifesto LOCAL é inválido")

    bundle_relative = Path(str(bundle_entry.get("path") or ""))
    bundle_path = (resolved.parent / bundle_relative).resolve()
    try:
        bundle_path.relative_to(resolved.parent)
    except ValueError as exc:
        raise RuntimeError("Bundle LOCAL está fora do diretório do manifesto") from exc
    if not bundle_path.is_file():
        raise RuntimeError("Bundle LOCAL declarado está ausente")
    expected_bundle_hash = str(bundle_entry.get("sha256") or "").strip().lower()
    observed_bundle_hash = file_sha256(bundle_path)
    if not expected_bundle_hash or not hmac.compare_digest(
        expected_bundle_hash, observed_bundle_hash
    ):
        raise RuntimeError("SHA-256 do bundle LOCAL diverge do manifesto")

    return {
        "model_version": model_version,
        "bundle_version": bundle_version,
        "status": manifest.get("status"),
        "manifest_path": evidence_path(resolved),
        "manifest_sha256": file_sha256(resolved),
        "manifest_payload_sha256": expected_payload_hash,
        "bundle_path": evidence_path(bundle_path),
        "bundle_sha256": observed_bundle_hash,
        "embedding": {
            "model_id": str(embedding.get("model_id") or ""),
            "dimension": int(embedding.get("dimension") or 0),
            "model_revision": str(embedding.get("model_revision") or ""),
            "model_tree_sha256": str(
                embedding.get("model_tree_sha256") or ""
            ).lower(),
        },
        "gates": gates,
    }


def _request_json(
    url: str,
    token: str,
    *,
    payload: dict | None = None,
    timeout_seconds: float = 30.0,
) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    method = "GET"
    if payload is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        method = "POST"
    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"Serviço local recusou a verificação de proveniência: HTTP {exc.code}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(
            "Serviço local indisponível para verificação de proveniência"
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Serviço local retornou JSON inválido") from exc
    if not isinstance(body, dict):
        raise RuntimeError("Serviço local retornou payload incompatível")
    return body


def preflight_local_ai(
    base_url: str,
    token: str,
    model_provenance: dict,
    *,
    timeout_seconds: float = 30.0,
) -> dict:
    """Prove that the running service matches the frozen manifest exactly."""
    parsed_url = urllib.parse.urlparse(str(base_url or "").strip())
    if (
        parsed_url.scheme not in {"http", "https"}
        or parsed_url.hostname not in {"127.0.0.1", "localhost", "::1"}
    ):
        raise RuntimeError(
            "--local-ai-url deve apontar explicitamente para o serviço local"
        )
    if not token:
        raise RuntimeError("Token do serviço LOCAL ausente")
    normalized_base = str(base_url).rstrip("/")
    health = _request_json(
        f"{normalized_base}/health",
        token,
        timeout_seconds=timeout_seconds,
    )
    hybrid = ((health.get("artifacts") or {}).get("hybrid_bundle") or {})
    health_embedding = health.get("embedding") or {}
    health_gates = {
        "alive": health.get("alive") is True,
        "decision_ready": health.get("decision_ready") is True,
        "candidate_evaluation_eligible": (
            health.get("candidate_evaluation_eligible") is True
        ),
        "production_mode": health.get("mode") == "production",
        "hybrid_loaded": hybrid.get("loaded") is True,
        "bundle_version": (
            str(hybrid.get("version") or "")
            == str(model_provenance["bundle_version"])
        ),
        "embedding_backend": (
            health_embedding.get("backend")
            == "granite_embedding_pytorch_fp32"
        ),
        "embedding_dimension": health_embedding.get("dimension") == 384,
        "embedding_revision": (
            str(health_embedding.get("model_revision") or "")
            == model_provenance["embedding"]["model_revision"]
        ),
        "embedding_tree_hash": hmac.compare_digest(
            str(health_embedding.get("model_tree_sha256") or "").lower(),
            model_provenance["embedding"]["model_tree_sha256"],
        ),
        "no_embedding_fallback": health_embedding.get("fallback_used") is False,
    }
    if not all(health_gates.values()):
        raise RuntimeError(
            "Serviço LOCAL não corresponde ao candidato congelado: "
            f"{health_gates}"
        )

    probe = _request_json(
        f"{normalized_base}/v1/classify?include_metadata=1",
        token,
        payload={
            "titulo": "Lâmpada queimada na sala 101",
            "descricao": (
                "A lâmpada central da sala 101 do Bloco A queimou e precisa "
                "ser substituída."
            ),
            "tipo_servico": "Elétrica",
            "localizacao": "Bloco A - Sala 101",
            "solicitante": "calibracao.proveniencia",
            "urgencia": 2,
            "impacto": 2,
        },
        timeout_seconds=timeout_seconds,
    )
    metadata = probe.get("metadata") or {}
    artifact = metadata.get("artifact") or {}
    probe_embedding = metadata.get("embedding") or {}
    probe_gates = {
        "hybrid_path": metadata.get("decision_path")
        in {"hybrid_model", "hybrid_model_abstention"},
        "candidate_evaluation_eligible": (
            metadata.get("candidate_evaluation_eligible") is True
        ),
        "pipeline_evaluation_eligible": (
            metadata.get("pipeline_evaluation_eligible") is True
        ),
        "artifact_version": (
            str(artifact.get("version") or "")
            == str(model_provenance["bundle_version"])
        ),
        "bundle_sha256": hmac.compare_digest(
            str(artifact.get("bundle_sha256") or "").lower(),
            model_provenance["bundle_sha256"],
        ),
        "manifest_payload_sha256": hmac.compare_digest(
            str(artifact.get("manifest_payload_sha256") or "").lower(),
            model_provenance["manifest_payload_sha256"],
        ),
        "embedding_revision": (
            str(probe_embedding.get("model_revision") or "")
            == model_provenance["embedding"]["model_revision"]
        ),
        "embedding_tree_hash": hmac.compare_digest(
            str(probe_embedding.get("model_tree_sha256") or "").lower(),
            model_provenance["embedding"]["model_tree_sha256"],
        ),
        "no_fallback": metadata.get("fallback_used") is False,
    }
    if not all(probe_gates.values()):
        raise RuntimeError(
            "Inferência de prova não corresponde ao candidato congelado: "
            f"{probe_gates}"
        )
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "service_version": health.get("service_version"),
        "mode": health.get("mode"),
        "health_gates": health_gates,
        "probe_gates": probe_gates,
        "decision_path": metadata.get("decision_path"),
        "artifact": {
            "version": artifact.get("version"),
            "bundle_sha256": artifact.get("bundle_sha256"),
            "manifest_payload_sha256": artifact.get(
                "manifest_payload_sha256"
            ),
        },
        "embedding": {
            "backend": probe_embedding.get("backend"),
            "runtime_backend": probe_embedding.get("runtime_backend"),
            "precision": probe_embedding.get("precision"),
            "dimension": probe_embedding.get("dimension"),
            "model_revision": probe_embedding.get("model_revision"),
            "model_tree_sha256": probe_embedding.get("model_tree_sha256"),
        },
    }


def _timestamp_seconds(value: object) -> float | None:
    """Normalize database/ISO timestamps for temporal integrity checks."""
    if value is None:
        return None
    parsed = value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(parsed, datetime):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def audit_temporal_observations(observations: list[dict]) -> dict:
    """Fail closed on incomplete, inverted or non-FIFO calibration clocks."""
    timestamp_fields = (
        "ingresso_banco_em",
        "primeira_reserva_wf06_em",
        "primeira_decisao_ia_em",
        "ultimo_update_terminal_em",
    )
    missing: list[int] = []
    negative: list[int] = []
    normalized: list[tuple[float, int, float]] = []

    for observation in observations:
        ticket_id = int(observation.get("ticket_id") or 0)
        values = [_timestamp_seconds(observation.get(field)) for field in timestamp_fields]
        if any(value is None for value in values):
            missing.append(ticket_id)
            continue
        start, reservation, decision, end = values
        if not (start <= reservation <= decision <= end):
            negative.append(ticket_id)
            continue
        fifo_order = observation.get("ordem_fifo_esperada")
        try:
            fifo_sort_key = float(fifo_order)
        except (TypeError, ValueError):
            fifo_sort_key = start
        normalized.append((fifo_sort_key, ticket_id, reservation))

    fifo_violations: list[int] = []
    previous_reservation: float | None = None
    for _, ticket_id, reservation in sorted(normalized):
        if previous_reservation is not None and reservation < previous_reservation:
            fifo_violations.append(ticket_id)
        previous_reservation = reservation

    return {
        "timestamps_ausentes": len(missing),
        "latencias_negativas": len(negative),
        "violacoes_fifo_primeira_reserva": len(fifo_violations),
        "tickets_com_timestamp_ausente": missing,
        "tickets_com_latencia_negativa": negative,
        "tickets_com_violacao_fifo": fifo_violations,
    }


def calibration_generation_config(config: dict, model_provenance: dict) -> dict:
    """Freeze the local-only policy used by every calibration treatment."""
    return {
        **config,
        "test_mode": True,
        "auto_human_confirmation": True,
        "label_source": "SYNTHETIC_GENERATOR",
        "scientific_result": False,
        "confirmatory_eligible": False,
        "purpose": "THROUGHPUT_CALIBRATION",
        "ia_fixed_model_role": CALIBRATION_MODEL_ROLE,
        "ia_expected_model": model_provenance["model_version"],
        "ia_execution_mode": CALIBRATION_EXECUTION_MODE,
        "failover_enabled": False,
        "fallback_enabled": False,
        "model_manifest_sha256": model_provenance["manifest_sha256"],
        "model_manifest_payload_sha256": model_provenance[
            "manifest_payload_sha256"
        ],
        "model_bundle_sha256": model_provenance["bundle_sha256"],
        "embedding_model_revision": model_provenance["embedding"][
            "model_revision"
        ],
        "embedding_model_tree_sha256": model_provenance["embedding"][
            "model_tree_sha256"
        ],
    }


def prepare_output_dir(path: Path) -> None:
    """Create a fresh evidence directory without overwriting a previous run."""
    if path.exists():
        if not path.is_dir():
            raise RuntimeError(f"Saída existe e não é diretório: {path}")
        if any(path.iterdir()):
            raise RuntimeError(
                f"Diretório de saída já contém evidências: {path}. "
                "Use um novo --saida-dir."
            )
        return
    path.mkdir(parents=True, exist_ok=False)


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def wilson_interval(successes: int, total: int, confidence: float = 0.95) -> dict:
    """Wilson score interval for the repetition-level success proportion."""
    if total <= 0:
        return {"lower": None, "upper": None, "confidence": confidence}
    z = NormalDist().inv_cdf(1.0 - (1.0 - confidence) / 2.0)
    proportion = successes / total
    denominator = 1.0 + (z * z) / total
    center = (proportion + (z * z) / (2.0 * total)) / denominator
    margin = (
        z
        * (
            (proportion * (1.0 - proportion) / total)
            + (z * z) / (4.0 * total * total)
        )
        ** 0.5
        / denominator
    )
    return {
        "lower": max(0.0, center - margin),
        "upper": min(1.0, center + margin),
        "confidence": confidence,
    }


def parse_configs(raw: str) -> list[dict]:
    configs: list[dict] = []
    for index, item in enumerate(raw.split(","), start=1):
        try:
            batch_raw, interval_raw = item.strip().split("@", 1)
            batch, interval = int(batch_raw), int(interval_raw)
        except ValueError as exc:
            raise SystemExit(
                f"Configuração inválida {item!r}; use lote@intervalo."
            ) from exc
        if batch <= 0 or interval < 0:
            raise SystemExit(f"Configuração inválida: {item}")
        configs.append(
            {"id": f"Q{index}", "batch": batch, "interval_seconds": interval}
        )
    return configs


def parse_burst_sizes(raw: str) -> list[int]:
    try:
        sizes = [int(value.strip()) for value in raw.split(",") if value.strip()]
    except ValueError as exc:
        raise SystemExit("--burst-sizes deve conter inteiros separados por vírgula") from exc
    if not sizes or any(value <= 0 for value in sizes):
        raise SystemExit("--burst-sizes deve conter valores positivos")
    if len(set(sizes)) != len(sizes):
        raise SystemExit("--burst-sizes não pode conter valores repetidos")
    return sizes


def build_ingress_offsets(
    total: int,
    interval_seconds: float,
    profile: str,
    seed: int,
) -> list[float]:
    """Return reproducible submission offsets for the selected arrival process."""
    if total < 0:
        raise ValueError("total de ingressos não pode ser negativo")
    if interval_seconds < 0:
        raise ValueError("intervalo de ingresso não pode ser negativo")
    if profile not in INGRESS_PROFILES:
        raise ValueError(f"perfil de ingresso inválido: {profile}")
    if total == 0:
        return []
    if profile == "burst" or interval_seconds == 0:
        return [0.0] * total
    if profile == "deterministic":
        return [round(index * interval_seconds, 9) for index in range(total)]

    generator = random.Random(seed)
    offsets = [0.0]
    elapsed = 0.0
    rate = 1.0 / interval_seconds
    for _ in range(1, total):
        elapsed += generator.expovariate(rate)
        offsets.append(round(elapsed, 9))
    return offsets


def pace_submission(started_at: float, offset_seconds: float) -> float:
    """Wait until a scheduled offset; requests can be late, never early."""
    remaining = started_at + offset_seconds - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)
    return max(0.0, time.monotonic() - started_at)


def audit_ingress_timing(created: list[dict], tolerance_seconds: float = 0.005) -> dict:
    """Quantify whether concurrent requests respected the planned arrival clock."""
    if tolerance_seconds < 0:
        raise ValueError("tolerância de ingresso não pode ser negativa")
    ordered = sorted(created, key=lambda item: int(item["ingress_sequence"]))
    early: list[str] = []
    submission_lateness: list[float] = []
    start_lateness: list[float] = []
    request_starts: list[float] = []
    for item in ordered:
        planned = float(item["scheduled_offset_s"])
        submitted = float(item["submitted_offset_s"])
        started = float(item["request_started_offset_s"])
        submission_lateness.append(max(0.0, submitted - planned))
        start_lateness.append(max(0.0, started - planned))
        request_starts.append(started)
        if submitted + tolerance_seconds < planned or started + tolerance_seconds < planned:
            early.append(str(item.get("case_id") or item["ingress_sequence"]))
    interarrival = [
        max(0.0, right - left)
        for left, right in zip(request_starts, request_starts[1:])
    ]
    return {
        "tickets_observados": len(ordered),
        "tolerancia_s": tolerance_seconds,
        "submissoes_antecipadas": len(early),
        "tickets_antecipados": early,
        "atraso_submissao_max_s": max(submission_lateness, default=None),
        "atraso_inicio_requisicao_max_s": max(start_lateness, default=None),
        "intervalo_inicio_requisicao_p50_s": percentile(interarrival, 0.50),
        "intervalo_inicio_requisicao_p95_s": percentile(interarrival, 0.95),
        "duracao_planejada_ingresso_s": (
            float(ordered[-1]["scheduled_offset_s"]) if ordered else None
        ),
        "duracao_observada_inicio_requisicoes_s": (
            max(request_starts) - min(request_starts) if request_starts else None
        ),
        "cronograma_respeitado": not early,
    }


def build_treatments(
    configs: list[dict],
    *,
    ingress_profile: str,
    tickets_per_repetition: int,
    burst_sizes: list[int],
) -> list[dict]:
    if ingress_profile == "burst":
        return [
            {
                **config,
                "id": f"{config['id']}-B{size}",
                "base_configuration_id": config["id"],
                "ingress_profile": ingress_profile,
                "tickets_per_repetition": size,
                "burst_size": size,
            }
            for config in configs
            for size in burst_sizes
        ]
    return [
        {
            **config,
            "base_configuration_id": config["id"],
            "ingress_profile": ingress_profile,
            "tickets_per_repetition": tickets_per_repetition,
            "burst_size": None,
        }
        for config in configs
    ]


def build_treatment_schedule(
    treatments: list[dict],
    repetitions: int,
    *,
    randomized: bool,
    seed: int,
) -> list[dict]:
    schedule = [
        {**treatment, "repetition": repetition}
        for repetition in range(1, repetitions + 1)
        for treatment in treatments
    ]
    if randomized:
        random.Random(seed).shuffle(schedule)
    return schedule


def ensure_quiescent_queue() -> None:
    rows = checker.query(
        """
        SELECT COUNT(*)::int AS n
        FROM tickets_processados
        WHERE triagem_status IN (
          'PENDENTE_FILA_IA','FILA_IA_LIBERADA','CLASSIFICANDO_DUP',
          'CLASSIFICANDO','AGUARDANDO_FILA_CLASSIFICACAO'
        )
        """
    )
    if len(rows) != 1 or "n" not in rows[0]:
        raise RuntimeError("Não foi possível comprovar que a fila está vazia")
    active = int(rows[0].get("n") or 0)
    if active:
        raise RuntimeError(
            f"A fila não está vazia ({active} tickets). "
            "Calibração controlada exige janela operacional isolada."
        )


def audit_queue_drain(run_id: str) -> dict:
    """Confirm that the scoped repetition left no active queue item behind."""
    row = checker.query(
        """
        WITH proprios AS MATERIALIZED (
          SELECT DISTINCT ticket_id
          FROM dataset_controle
          WHERE run_id=%s AND ticket_id IS NOT NULL
        ),
        ativos AS MATERIALIZED (
          SELECT tp.id
          FROM tickets_processados tp
          WHERE tp.triagem_status IN (
            'PENDENTE_FILA_IA','FILA_IA_LIBERADA','CLASSIFICANDO_DUP',
            'CLASSIFICANDO','AGUARDANDO_FILA_CLASSIFICACAO'
          )
        )
        SELECT
          COUNT(*) FILTER (
            WHERE EXISTS (SELECT 1 FROM proprios p WHERE p.ticket_id=a.id)
          )::int AS ativos_do_run,
          COUNT(*) FILTER (
            WHERE NOT EXISTS (SELECT 1 FROM proprios p WHERE p.ticket_id=a.id)
          )::int AS ativos_estranhos,
          COALESCE(array_agg(a.id ORDER BY a.id) FILTER (
            WHERE EXISTS (SELECT 1 FROM proprios p WHERE p.ticket_id=a.id)
          ),ARRAY[]::bigint[]) AS tickets_ativos_do_run,
          COALESCE(array_agg(a.id ORDER BY a.id) FILTER (
            WHERE NOT EXISTS (SELECT 1 FROM proprios p WHERE p.ticket_id=a.id)
          ),ARRAY[]::bigint[]) AS tickets_ativos_estranhos
        FROM ativos a
        """,
        (run_id,),
    )[0]
    result = {
        "ativos_do_run": int(row.get("ativos_do_run") or 0),
        "ativos_estranhos": int(row.get("ativos_estranhos") or 0),
        "tickets_ativos_do_run": [
            int(value) for value in (row.get("tickets_ativos_do_run") or [])
        ],
        "tickets_ativos_estranhos": [
            int(value) for value in (row.get("tickets_ativos_estranhos") or [])
        ],
    }
    result["fila_vazia_ao_final"] = (
        result["ativos_do_run"] == 0 and result["ativos_estranhos"] == 0
    )
    return result


def compose_n8n(
    batch: int,
    interval: int,
    run_scope: str | None = None,
    model_version: str | None = None,
) -> None:
    env = os.environ.copy()
    env["FILA_IA_LOTE_TAMANHO"] = str(batch)
    env["FILA_IA_INTERVALO_SEGUNDOS"] = str(interval)
    if run_scope:
        if not checker.ORACLE_RUN_RE.fullmatch(run_scope):
            raise ValueError("run_scope inválido para FILA_IA_RUN_SCOPE")
        env["FILA_IA_RUN_SCOPE"] = run_scope
    else:
        # O escopo é exclusivamente experimental. A recriação operacional não
        # pode herdar um valor definido no shell nem em n8n/.env.
        env["FILA_IA_RUN_SCOPE"] = ""
    if model_version:
        env["IA_MODEL_LOCAL"] = model_version
    else:
        env.pop("IA_MODEL_LOCAL", None)
    result = subprocess.run(
        [
            "docker",
            "--context",
            LOCAL_DOCKER_CONTEXT,
            "compose",
            "-f",
            str(ROOT / "n8n" / "docker-compose.yml"),
            "up",
            "-d",
            "--force-recreate",
            "n8n",
        ],
        cwd=ROOT / "n8n",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Falha ao reiniciar n8n")
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen("http://localhost:5678/healthz", timeout=5) as response:
                if response.status < 400:
                    return
        except Exception:
            pass
        time.sleep(3)
    raise TimeoutError("n8n não ficou saudável em 120 segundos.")


def capture_n8n_queue_profile() -> dict[str, Any]:
    """Capture only the non-secret live values that calibration may change."""
    result = subprocess.run(
        ["docker", "--context", LOCAL_DOCKER_CONTEXT, "inspect", "n8n", "--format", "{{json .Config.Env}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Falha ao inspecionar n8n")
    try:
        entries = json.loads(result.stdout.strip())
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("docker inspect não retornou o ambiente do n8n") from exc
    values = {}
    for entry in entries if isinstance(entries, list) else []:
        key, separator, value = str(entry).partition("=")
        if separator:
            values[key] = value
    try:
        batch = int(values["FILA_IA_LOTE_TAMANHO"])
        interval = int(values["FILA_IA_INTERVALO_SEGUNDOS"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("Perfil vivo do WF06 não contém lote/intervalo válidos") from exc
    run_scope = str(values.get("FILA_IA_RUN_SCOPE") or "").strip()
    model_version = str(values.get("IA_MODEL_LOCAL") or "").strip()
    if not 1 <= batch <= 50 or not 0 <= interval <= 600:
        raise RuntimeError("Perfil vivo do WF06 está fora dos limites aceitos")
    if run_scope and not checker.ORACLE_RUN_RE.fullmatch(run_scope):
        raise RuntimeError("FILA_IA_RUN_SCOPE vivo é inválido")
    if not model_version:
        raise RuntimeError("IA_MODEL_LOCAL vivo não foi identificado")
    return {
        "batch": batch,
        "interval_seconds": interval,
        "run_scope": run_scope or None,
        "model_version": model_version,
    }


@contextmanager
def queue_scheduler_lock():
    """Freeze WF06 reservations while changing or restoring its live profile."""
    connection = checker.connect_pg()
    acquired = False
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_try_advisory_lock(%s) AS acquired",
                (QUEUE_SCHEDULER_LOCK_KEY,),
            )
            row = cursor.fetchone()
            acquired = bool(row and row.get("acquired"))
        if not acquired:
            raise RuntimeError(
                "WF06 está reservando a fila; calibração não iniciou para evitar corrida"
            )
        yield connection
    finally:
        if acquired:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_unlock(%s)",
                        (QUEUE_SCHEDULER_LOCK_KEY,),
                    )
            except Exception:
                pass
        connection.close()


def capture_queue_controller(connection=None) -> dict[str, Any]:
    sql = """
        SELECT proxima_liberacao_em,intervalo_segundos,lote_tamanho
        FROM fila_ia_controle
        WHERE id=1
        """
    if connection is None:
        rows = checker.query(sql)
    else:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            rows = [dict(row) for row in cursor.fetchall()]
    if len(rows) != 1:
        raise RuntimeError("fila_ia_controle id=1 não pôde ser congelado")
    row = rows[0]
    next_release = row.get("proxima_liberacao_em")
    interval_raw = row.get("intervalo_segundos")
    batch_raw = row.get("lote_tamanho")
    if not isinstance(next_release, datetime):
        raise RuntimeError("Snapshot da fila não contém próxima liberação válida")
    if interval_raw is None or batch_raw is None:
        raise RuntimeError("Snapshot da fila contém lote/intervalo nulos")
    try:
        interval = int(interval_raw)
        batch = int(batch_raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Snapshot da fila contém lote/intervalo inválidos") from exc
    if not 1 <= batch <= 50 or not 0 <= interval <= 600:
        raise RuntimeError("Snapshot da fila está fora dos limites aceitos")
    return {
        "proxima_liberacao_em": next_release,
        "intervalo_segundos": interval,
        "lote_tamanho": batch,
    }


def restore_queue_controller(snapshot: dict[str, Any], connection=None) -> None:
    """Restore the scheduler row captured before the first treatment."""
    interval = int(snapshot["intervalo_segundos"])
    batch = int(snapshot["lote_tamanho"])
    if not 1 <= batch <= 50 or not 0 <= interval <= 600:
        raise RuntimeError("Snapshot de fila inválido; restauração bloqueada")
    sql = """
        UPDATE fila_ia_controle f
        SET proxima_liberacao_em=%s,
            intervalo_segundos=%s,
            lote_tamanho=%s,
            atualizado_em=NOW()
        WHERE f.id=1
        """
    parameters = (snapshot.get("proxima_liberacao_em"), interval, batch)
    if connection is None:
        with queue_scheduler_lock() as locked_connection:
            restore_queue_controller(snapshot, connection=locked_connection)
        return
    with connection.cursor() as cursor:
        cursor.execute(sql, parameters)
        if cursor.rowcount != 1:
            raise RuntimeError("fila_ia_controle id=1 não foi restaurado")


def assert_runtime_profile(expected: dict[str, Any]) -> None:
    observed = capture_n8n_queue_profile()
    if observed != expected:
        raise RuntimeError(
            "Perfil do n8n divergiu após recriação: "
            f"esperado={expected!r}; observado={observed!r}"
        )


def assert_queue_controller(expected: dict[str, Any], connection=None) -> None:
    observed = capture_queue_controller(connection)
    if observed != expected:
        raise RuntimeError(
            "Controlador da fila divergiu após restauração: "
            f"esperado={expected!r}; observado={observed!r}"
        )


def restore_calibration_state(
    runtime_profile: dict[str, Any],
    queue_controller: dict[str, Any],
) -> None:
    """Restore the controller before exposing the operational WF06 scope."""
    with queue_scheduler_lock() as connection:
        restore_queue_controller(queue_controller, connection=connection)
        assert_queue_controller(queue_controller, connection=connection)
        compose_n8n(
            runtime_profile["batch"],
            runtime_profile["interval_seconds"],
            run_scope=runtime_profile["run_scope"],
            model_version=runtime_profile["model_version"],
        )
        assert_runtime_profile(runtime_profile)


def database_now() -> datetime:
    row = checker.query("SELECT clock_timestamp() AS agora")[0]
    value = row.get("agora")
    if not isinstance(value, datetime):
        raise RuntimeError("PostgreSQL não retornou o relógio da janela experimental")
    return value


def reset_queue_controller(batch: int, interval: int) -> None:
    """Start every isolated repetition from the same scheduler clock."""
    checker.execute(
        """
        WITH bloqueio AS MATERIALIZED (
          SELECT pg_advisory_xact_lock(9062026) AS adquirido
        )
        UPDATE fila_ia_controle f
        SET proxima_liberacao_em=NOW(),
            intervalo_segundos=%s,
            lote_tamanho=%s,
            atualizado_em=NOW()
        FROM bloqueio
        WHERE f.id=1
        """,
        (interval, batch),
    )


def audit_foreign_interference(
    run_id: str,
    window_started_at: datetime,
    window_finished_at: datetime,
) -> dict:
    """Detect queue ingress or IA processing outside the scoped repetition.

    The audit is event/time based. A closed historical ticket is therefore not
    counted merely because it exists in ``tickets_processados``.
    """
    if window_finished_at < window_started_at:
        raise ValueError("janela de auditoria de interferência está invertida")
    row = checker.query(
        """
        WITH parametros AS (
          SELECT %s::text AS run_id,%s::timestamptz AS inicio,%s::timestamptz AS fim
        ),
        proprios AS MATERIALIZED (
          SELECT DISTINCT dc.ticket_id
          FROM dataset_controle dc,parametros p
          WHERE dc.run_id=p.run_id AND dc.ticket_id IS NOT NULL
        ),
        eventos_fila_estranhos AS MATERIALIZED (
          SELECT DISTINCT tp.id AS ticket_id,
                 UPPER(COALESCE(evento->>'acao','')) AS acao
          FROM tickets_processados tp
          CROSS JOIN parametros p
          CROSS JOIN LATERAL jsonb_array_elements(
            CASE jsonb_typeof(COALESCE(tp.log_workflow,'[]'::jsonb))
              WHEN 'array' THEN COALESCE(tp.log_workflow,'[]'::jsonb)
              WHEN 'object' THEN jsonb_build_array(tp.log_workflow)
              ELSE '[]'::jsonb
            END
          ) evento
          CROSS JOIN LATERAL (
            SELECT CASE
              WHEN COALESCE(evento->>'ts','') ~
                '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+(Z|[+-][0-9]{2}:[0-9]{2})$'
              THEN (evento->>'ts')::timestamptz
            END AS evento_em
          ) relogio
          WHERE NOT EXISTS (
                  SELECT 1 FROM proprios o WHERE o.ticket_id=tp.id
                )
            AND relogio.evento_em BETWEEN p.inicio AND p.fim
            AND UPPER(COALESCE(evento->>'acao','')) ~
                '(ENFILEIR|RESERVAR_FILA|REENFILEIR)'
        ),
        fila_ativa_estranha AS MATERIALIZED (
          SELECT DISTINCT tp.id AS ticket_id
          FROM tickets_processados tp,parametros p
          WHERE tp.triagem_status IN (
                  'PENDENTE_FILA_IA','FILA_IA_LIBERADA','CLASSIFICANDO_DUP',
                  'CLASSIFICANDO','AGUARDANDO_FILA_CLASSIFICACAO'
                )
            AND NOT EXISTS (
                  SELECT 1 FROM proprios o WHERE o.ticket_id=tp.id
                )
            AND (
              tp.criado_em BETWEEN p.inicio AND p.fim
              OR tp.atualizado_em BETWEEN p.inicio AND p.fim
              OR EXISTS (
                SELECT 1 FROM eventos_fila_estranhos e WHERE e.ticket_id=tp.id
              )
            )
        ),
        decisoes_estranhas AS MATERIALIZED (
          SELECT DISTINCT i.ticket_id
          FROM ia_decisoes i,parametros p
          WHERE i.criado_em BETWEEN p.inicio AND p.fim
            AND (
              i.ticket_id IS NULL
              OR NOT EXISTS (
                SELECT 1 FROM proprios o WHERE o.ticket_id=i.ticket_id
              )
            )
        ),
        ids_estranhos AS (
          SELECT ticket_id FROM eventos_fila_estranhos
          UNION
          SELECT ticket_id FROM fila_ativa_estranha
          UNION
          SELECT ticket_id FROM decisoes_estranhas WHERE ticket_id IS NOT NULL
        )
        SELECT
          (SELECT COUNT(DISTINCT ticket_id)::int
             FROM eventos_fila_estranhos) AS entradas_fila_estranhas,
          (SELECT COUNT(DISTINCT ticket_id)::int
             FROM eventos_fila_estranhos
            WHERE acao='RESERVAR_FILA') AS reservas_wf06_estranhas,
          (SELECT COUNT(DISTINCT ticket_id)::int
             FROM fila_ativa_estranha) AS tickets_fila_estranhos_ativos,
          (SELECT COUNT(*)::int FROM decisoes_estranhas) AS decisoes_ia_estranhas,
          COALESCE(
            (SELECT array_agg(ticket_id ORDER BY ticket_id) FROM ids_estranhos),
            ARRAY[]::bigint[]
          ) AS tickets_estranhos
        """,
        (run_id, window_started_at, window_finished_at),
    )[0]
    result = {
        "janela_inicio_em": window_started_at,
        "janela_fim_em": window_finished_at,
        "entradas_fila_estranhas": int(row.get("entradas_fila_estranhas") or 0),
        "reservas_wf06_estranhas": int(row.get("reservas_wf06_estranhas") or 0),
        "tickets_fila_estranhos_ativos": int(
            row.get("tickets_fila_estranhos_ativos") or 0
        ),
        "decisoes_ia_estranhas": int(row.get("decisoes_ia_estranhas") or 0),
        "tickets_estranhos": [
            int(ticket_id) for ticket_id in (row.get("tickets_estranhos") or [])
        ],
    }
    result["interferencia_estranha_detectada"] = any(
        result[key] > 0
        for key in (
            "entradas_fila_estranhas",
            "reservas_wf06_estranhas",
            "tickets_fila_estranhos_ativos",
            "decisoes_ia_estranhas",
        )
    )
    return result


def calibration_cases(total: int, seed: int) -> list[dataset.EvalCase]:
    if total <= 0:
        raise ValueError("total deve ser maior que zero")

    # O número de cenários de classificação é definido pelo catálogo, não por
    # uma constante. Aumentamos as variações até obter exatamente a amostra
    # declarada pela CLI; isso evita calibrações silenciosamente menores.
    for per_scenario in range(1, total + 1):
        cases = [
            case
            for case in dataset.generate_cases(
                per_scenario,
                seed,
                dataset_version=dataset.DEFAULT_DATASET_VERSION,
                split="CALIBRACAO",
            )
            if case.dimension == "CLASSIFICACAO"
        ]
        if len(cases) >= total:
            return cases[:total]
    raise RuntimeError("O catálogo não produziu casos de classificação suficientes")


def register_experiment(
    run_id: str,
    seed: int,
    config: dict,
    model_provenance: dict,
) -> None:
    scientific_config = calibration_generation_config(config, model_provenance)
    checker.execute(
        """
        INSERT INTO experimentos_avaliacao(
          run_id,origem,dataset_version,dataset_sha256,seed,split,modelo_ia,
          prompt_dedup_version,prompt_classif_version,generation_profile,
          generation_config,protocolo_version,status,rotulos_validados,iniciado_em
        )
        VALUES(
          %s,%s,%s,%s,%s,'CALIBRACAO',%s,
          'deduplicacao_v9.1-episodica','classificacao_v9.1-episodica',
          'local-pytorch-fp32-deterministic',
          %s::jsonb,%s,'CALIBRANDO',FALSE,NOW()
        )
        """,
        (
            run_id,
            f"CALIBRACAO_FILA_{run_id}",
            dataset.DEFAULT_DATASET_VERSION,
            hashlib.sha256(
                json.dumps(scientific_config, sort_keys=True).encode()
            ).hexdigest(),
            seed,
            model_provenance["model_version"],
            json.dumps(scientific_config),
            CALIBRATION_PROTOCOL_VERSION,
        ),
    )


def create_cases(
    cases: list[dataset.EvalCase],
    run_id: str,
    ingress_interval: float,
    ingress_seed: int,
    args: argparse.Namespace,
) -> list[dict]:
    generator_args = SimpleNamespace(
        url=args.url,
        app_token=args.app_token,
        user=args.user,
        password=args.password,
        limite=0,
        intervalo=ingress_interval,
        origem=f"CALIBRACAO_FILA_{run_id}",
        run_id=run_id,
        postgres_container=args.postgres_container,
        postgres_user=args.postgres_user,
        postgres_db=args.postgres_db,
    )
    seed_module = dataset.load_seed_module()
    setup_client = seed_module.GLPIClient(
        args.url, args.app_token, args.user, args.password
    )
    setup_client.init_session()
    try:
        category_map = seed_module.seed_categorias(setup_client)
        location_map = seed_module.seed_localizacoes(setup_client)
        seed_module.seed_usuarios(setup_client)
        user_map = dataset.build_user_map(seed_module, setup_client)
    finally:
        setup_client.kill_session()

    offsets = build_ingress_offsets(
        len(cases),
        ingress_interval,
        args.ingress_profile,
        ingress_seed,
    )
    ingress_started_at = time.monotonic()

    def create_one(
        sequence: int,
        case: dataset.EvalCase,
        scheduled_offset: float,
        submitted_offset: float,
    ) -> dict:
        request_started_offset = max(
            0.0, time.monotonic() - ingress_started_at
        )
        client = seed_module.GLPIClient(
            args.url, args.app_token, args.user, args.password
        )
        client.init_session()
        try:
            result = client.create_item(
                "Ticket",
                {
                    "name": case.title,
                    "content": case.content,
                    "itilcategories_id": category_map[case.category],
                    "locations_id": location_map[case.location],
                    "type": 1,
                    "status": case.status,
                    "urgency": case.urgency,
                    "impact": case.impact,
                    "_users_id_requester": user_map.get(case.requester, 2),
                },
            )
        finally:
            client.kill_session()
        if not result or "id" not in result:
            raise RuntimeError(f"Falha ao criar {case.case_id}")
        ticket_id = int(result["id"])
        row = {
            "ticket_id": ticket_id,
            "origem": generator_args.origem,
            "cenario_controle": f"{case.scenario_id}:{case.case_id}",
            "duplicado_esperado": case.expected_dedup,
            "referencia_duplicado_esperada": None,
            "classificacao_esperada": case.expected_classification or None,
            "executor_esperado": case.expected_executor or None,
            "status_final_esperado": case.expected_status or None,
            "nivel_dificuldade": case.difficulty,
            "observacao": (
                f"case_id={case.case_id}; episode_id={case.episode_id}; "
                f"concorrencia={args.concorrencia_ingresso}; "
                f"perfil_ingresso={args.ingress_profile}; "
                f"sequencia_ingresso={sequence}; "
                f"offset_planejado_s={scheduled_offset:.9f}"
            ),
            "run_id": run_id,
            "case_id": case.case_id,
            "episode_id": case.episode_id,
            "scenario_id": case.scenario_id,
            "dimension": case.dimension,
            "order_in_episode": case.order_in_group,
            "reference_case_id": None,
            "requires_human_review": case.requires_human_review,
            "risk": case.risk,
            "rationale": case.rationale,
            "label_source": case.label_source,
            "template_family": case.template_family,
            "dataset_version": case.dataset_version,
            "split": case.split,
        }
        dataset.run_dataset_sql(
            dataset.dataset_sql([row]), generator_args, quiet=True
        )
        return {
            "case_id": case.case_id,
            "ticket_id": ticket_id,
            "title": case.title,
            "ingress_sequence": sequence,
            "scheduled_offset_s": round(scheduled_offset, 9),
            "submitted_offset_s": round(submitted_offset, 9),
            "request_started_offset_s": round(request_started_offset, 9),
            "created_offset_s": round(
                max(0.0, time.monotonic() - ingress_started_at), 9
            ),
        }

    created: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.concorrencia_ingresso) as pool:
        futures = {}
        for sequence, (case, offset) in enumerate(
            zip(cases, offsets, strict=True),
            start=1,
        ):
            submitted_offset = pace_submission(ingress_started_at, offset)
            for completed in [future for future in futures if future.done()]:
                item = completed.result()
                created.append(item)
                print(f"[OK] {item['case_id']} -> GLPI #{item['ticket_id']}")
                del futures[completed]
            future = pool.submit(
                create_one,
                sequence,
                case,
                offset,
                submitted_offset,
            )
            futures[future] = case
        for future in as_completed(futures):
            item = future.result()
            created.append(item)
            print(f"[OK] {item['case_id']} -> GLPI #{item['ticket_id']}")
    return sorted(created, key=lambda item: item["ingress_sequence"])


def execute_repetition(
    item: dict,
    run_id: str,
    seed: int,
    cases: list[dataset.EvalCase],
    args: argparse.Namespace,
    model_provenance: dict,
) -> tuple[list[dict], dict]:
    """Run one treatment with a registered, scoped WF06 instance."""
    ingress_seed = seed
    register_experiment(
        run_id,
        seed,
        {
            **item,
            "warmup": args.warmup,
            "ingress_concurrency": args.concorrencia_ingresso,
            "ingress_interval": args.ingress_interval,
            "ingress_profile": args.ingress_profile,
            "ingress_seed": ingress_seed,
            "planned_ingress_offsets_sha256": canonical_sha256(
                build_ingress_offsets(
                    len(cases),
                    args.ingress_interval,
                    args.ingress_profile,
                    ingress_seed,
                )
            ),
        },
        model_provenance,
    )
    # The experiment must exist before WF06 validates its database scope. The
    # window starts before recreation so concurrent ingress is still audited.
    window_started_at = database_now()
    compose_n8n(
        item["batch"],
        item["interval_seconds"],
        run_scope=run_id,
        model_version=model_provenance["model_version"],
    )
    reset_queue_controller(item["batch"], item["interval_seconds"])
    created = create_cases(
        cases,
        run_id,
        args.ingress_interval,
        ingress_seed,
        args,
    )
    ingress_audit = audit_ingress_timing(created)
    checker.wait_processing(
        run_id,
        args.timeout,
        args.poll,
        use_oracle=True,
    )
    window_finished_at = database_now()
    metrics = collect_result(run_id, args.warmup, model_provenance)
    interference = audit_foreign_interference(
        run_id,
        window_started_at,
        window_finished_at,
    )
    metrics["auditoria_interferencia"] = interference
    queue_drain = audit_queue_drain(run_id)
    metrics["auditoria_drenagem_fila"] = queue_drain
    metrics["auditoria_cronograma_ingresso"] = ingress_audit
    metrics["success"] = bool(
        metrics["success"]
        and not interference["interferencia_estranha_detectada"]
        and queue_drain["fila_vazia_ao_final"]
        and ingress_audit["cronograma_respeitado"]
        and ingress_audit["tickets_observados"] == len(cases)
    )
    return created, metrics


def collect_result(run_id: str, warmup: int, model_provenance: dict) -> dict:
    rows = checker.query(
        """
        WITH alvo_base AS (
          SELECT dc.ticket_id,tp.criado_em AS ingresso_banco_em,
                 COALESCE(tp.data_abertura,tp.criado_em) AS chave_fifo_em,
                 tp.atualizado_em AS ultimo_update_terminal_em,tp.triagem_status,
                 tp.log_workflow
          FROM dataset_controle dc
          JOIN tickets_processados tp ON tp.id=dc.ticket_id
          WHERE dc.run_id=%s
        ),
        tempos AS (
          SELECT
            a.ticket_id,a.ingresso_banco_em,a.ultimo_update_terminal_em,
            a.triagem_status,
            reserva.primeira_reserva_wf06_em,
            (
              SELECT MIN(i.criado_em)
              FROM ia_decisoes i
              WHERE i.ticket_id=a.ticket_id
                AND i.run_id=%s
            ) AS primeira_decisao_ia_em,
            ROW_NUMBER() OVER (
              ORDER BY a.ingresso_banco_em,a.ticket_id
            ) AS ordem_ingresso,
            ROW_NUMBER() OVER (
              ORDER BY a.chave_fifo_em,a.ticket_id
            ) AS ordem_fifo_esperada
          FROM alvo_base a
          LEFT JOIN LATERAL (
            SELECT MIN(
              CASE
                WHEN COALESCE(evento->>'ts','') ~
                  '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+(Z|[+-][0-9]{2}:[0-9]{2})$'
                THEN (evento->>'ts')::timestamptz
              END
            ) AS primeira_reserva_wf06_em
            FROM jsonb_array_elements(
              CASE jsonb_typeof(COALESCE(a.log_workflow,'[]'::jsonb))
                WHEN 'array' THEN COALESCE(a.log_workflow,'[]'::jsonb)
                WHEN 'object' THEN jsonb_build_array(a.log_workflow)
                ELSE '[]'::jsonb
              END
            ) evento
            WHERE UPPER(COALESCE(evento->>'wf',''))='WF06'
              AND UPPER(COALESCE(evento->>'acao',''))='RESERVAR_FILA'
          ) reserva ON TRUE
        ),
        medidos AS (
          SELECT * FROM tempos WHERE ordem_ingresso > %s
        ),
        medidos_validos AS (
          SELECT * FROM medidos
          WHERE ingresso_banco_em IS NOT NULL
            AND primeira_reserva_wf06_em IS NOT NULL
            AND primeira_decisao_ia_em IS NOT NULL
            AND ultimo_update_terminal_em IS NOT NULL
            AND ingresso_banco_em <= primeira_reserva_wf06_em
            AND primeira_reserva_wf06_em <= primeira_decisao_ia_em
            AND primeira_decisao_ia_em <= ultimo_update_terminal_em
        )
        SELECT
          (SELECT COUNT(*)::int FROM tempos) AS total,
          (SELECT COUNT(*)::int FROM medidos) AS total_medido,
          (SELECT COUNT(*)::int FROM medidos_validos) AS latencias_validas,
          LEAST(%s,(SELECT COUNT(*)::int FROM tempos)) AS warmup_descartado,
          (SELECT COUNT(*) FILTER (
            WHERE triagem_status IN (
              'ERRO_IA','TRIAGEM_MANUAL','DUPLICADO_FECHADO','ATRIBUIDO_DEMO',
              'PLANEJADO_DEMO_SEM_EQUIPE','ENCAMINHADO_PLANEJADO','FECHADO_OBRA'
            )
          )::int FROM tempos) AS terminal,
          ROUND(AVG(EXTRACT(EPOCH FROM (
            primeira_decisao_ia_em-ingresso_banco_em
          )))::numeric,3) AS espera_ingresso_banco_ate_primeira_decisao_ia_media_s,
          ROUND(percentile_cont(0.50) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (
              primeira_decisao_ia_em-ingresso_banco_em
            ))
          )::numeric,3) AS espera_ingresso_banco_ate_primeira_decisao_ia_p50_s,
          ROUND(percentile_cont(0.95) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (
              primeira_decisao_ia_em-ingresso_banco_em
            ))
          )::numeric,3) AS espera_ingresso_banco_ate_primeira_decisao_ia_p95_s,
          ROUND(percentile_cont(0.99) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (
              primeira_decisao_ia_em-ingresso_banco_em
            ))
          )::numeric,3) AS espera_ingresso_banco_ate_primeira_decisao_ia_p99_s,
          ROUND(AVG(EXTRACT(EPOCH FROM (
            ultimo_update_terminal_em-ingresso_banco_em
          )))::numeric,3) AS duracao_ingresso_banco_ate_ultimo_update_terminal_media_s,
          ROUND(percentile_cont(0.50) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (
              ultimo_update_terminal_em-ingresso_banco_em
            ))
          )::numeric,3) AS duracao_ingresso_banco_ate_ultimo_update_terminal_p50_s,
          ROUND(percentile_cont(0.95) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (
              ultimo_update_terminal_em-ingresso_banco_em
            ))
          )::numeric,3) AS duracao_ingresso_banco_ate_ultimo_update_terminal_p95_s,
          ROUND(percentile_cont(0.99) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (
              ultimo_update_terminal_em-ingresso_banco_em
            ))
          )::numeric,3) AS duracao_ingresso_banco_ate_ultimo_update_terminal_p99_s
        FROM medidos_validos
        """,
        (run_id, run_id, warmup, warmup),
    )[0]
    quality = checker.query(
        """
        WITH parametros AS (
          SELECT %s::text AS run_id,%s::text AS modelo,
                 %s::text AS bundle_sha256,%s::text AS manifest_payload_sha256
        ),
        decisoes AS MATERIALIZED (
          SELECT i.*
          FROM ia_decisoes i,parametros p
          WHERE i.run_id=p.run_id
        ),
        tentativas AS MATERIALIZED (
          SELECT t.*
          FROM ia_tentativas_modelo t,parametros p
          WHERE t.run_id=p.run_id
        ),
        dlq AS MATERIALIZED (
          SELECT d.*
          FROM fila_ia_dead_letter d,parametros p
          WHERE d.run_id=p.run_id
        ),
        metricas_fila AS MATERIALIZED (
          SELECT m.*
          FROM fila_ia_metricas m,parametros p
          WHERE m.run_id=p.run_id
        ),
        tickets_run AS MATERIALIZED (
          SELECT DISTINCT tp.id,tp.log_workflow
          FROM dataset_controle dc
          JOIN tickets_processados tp ON tp.id=dc.ticket_id
          CROSS JOIN parametros p
          WHERE dc.run_id=p.run_id
        ),
        reingressos_fila AS MATERIALIZED (
          SELECT t.id AS ticket_id
          FROM tickets_run t
          CROSS JOIN LATERAL jsonb_array_elements(
            CASE jsonb_typeof(COALESCE(t.log_workflow,'[]'::jsonb))
              WHEN 'array' THEN COALESCE(t.log_workflow,'[]'::jsonb)
              WHEN 'object' THEN jsonb_build_array(t.log_workflow)
              ELSE '[]'::jsonb
            END
          ) evento
          WHERE UPPER(COALESCE(evento->>'acao','')) ~ 'REENFILEIR'
        )
        SELECT
          (SELECT COUNT(*)::int FROM decisoes) AS decisoes_total,
          (SELECT COUNT(*) FILTER (WHERE erro_ia)::int
             FROM decisoes) AS erros_ia,
          (SELECT COUNT(*) FILTER (
             WHERE erro_ia=FALSE AND probabilidades_validas=FALSE
           )::int FROM decisoes) AS probabilidades_invalidas,
          (SELECT COUNT(*) FILTER (
             WHERE LOWER(COALESCE(mensagem_erro,'')) ~
               '(quota|rate|429|resource.exhausted|too many)'
           )::int FROM decisoes) AS rate_limits_decisoes,
          (SELECT COUNT(*)::int FROM tentativas) AS tentativas_modelo_total,
          (SELECT COUNT(*) FILTER (
             WHERE UPPER(COALESCE(status_tentativa,'')) <> 'VALID'
           )::int FROM tentativas) AS tentativas_modelo_falhas,
          (SELECT COUNT(*) FILTER (WHERE ordem_tentativa > 1)::int
             FROM tentativas) AS retentativas_modelo,
          (SELECT COUNT(*) FILTER (
             WHERE http_status=429
                OR UPPER(COALESCE(tipo_erro,''))='RATE_LIMIT'
                OR UPPER(COALESCE(codigo_erro,'')) IN (
                  'HTTP_429','RESOURCE_EXHAUSTED'
                )
           )::int FROM tentativas) AS rate_limits_429,
          (SELECT COUNT(*) FILTER (WHERE COALESCE(retryable,FALSE))::int
             FROM tentativas) AS falhas_retentaveis,
          (SELECT COUNT(*) FILTER (
             WHERE UPPER(COALESCE(tipo_erro,''))='TIMEOUT'
                OR UPPER(COALESCE(codigo_erro,'')) ~ 'TIMEOUT'
           )::int FROM tentativas) AS timeouts_modelo,
          (SELECT COUNT(*) FILTER (WHERE fallback_utilizado)::int
             FROM tentativas) AS fallbacks_utilizados,
          (SELECT COUNT(*) FILTER (
             WHERE UPPER(COALESCE(papel_modelo,'')) <> 'LOCAL'
                OR COALESCE(versao_modelo,'') <> p.modelo
           )::int
             FROM tentativas CROSS JOIN parametros p
          ) AS tentativas_modelo_inesperado,
          (SELECT COUNT(*) FILTER (
             WHERE LOWER(COALESCE(
                     metadata_cientifica->>'pipeline_evaluation_eligible','false'
                   )) <> 'true'
                OR LOWER(COALESCE(
                     metadata_cientifica->'artifact'->>'bundle_sha256',''
                   )) <> p.bundle_sha256
                OR LOWER(COALESCE(
                     metadata_cientifica->'artifact'->>'manifest_payload_sha256',''
                   )) <> p.manifest_payload_sha256
                OR LOWER(COALESCE(
                     metadata_cientifica->>'fallback_used','false'
                   )) = 'true'
           )::int
             FROM tentativas CROSS JOIN parametros p
             WHERE UPPER(COALESCE(status_tentativa,''))='VALID'
          ) AS tentativas_proveniencia_invalida,
          (SELECT GREATEST(
             COUNT(*)-COUNT(DISTINCT (ticket_id,etapa)),0
           )::int FROM decisoes) AS retentativas_workflow,
          (SELECT COUNT(*)::int FROM dlq) AS entradas_dlq,
          (SELECT COUNT(*) FILTER (WHERE NOT resolvido)::int
             FROM dlq) AS entradas_dlq_abertas,
          (SELECT COUNT(*)::int FROM metricas_fila) AS ciclos_wf06_metrificados,
          (SELECT COALESCE(MAX(pendentes),0)::int
             FROM metricas_fila) AS pico_pendentes,
          (SELECT COALESCE(MAX(reservados),0)::int
             FROM metricas_fila) AS pico_reservados,
          (SELECT COALESCE(SUM(liberados_ciclo),0)::int
             FROM metricas_fila) AS liberacoes_wf06,
          (SELECT COUNT(*)::int FROM reingressos_fila) AS reingressos_fila
        """,
        (
            run_id,
            model_provenance["model_version"],
            model_provenance["bundle_sha256"],
            model_provenance["manifest_payload_sha256"],
        ),
    )[0]
    observations = checker.query(
        """
        WITH alvo_base AS (
          SELECT dc.ticket_id,tp.criado_em AS ingresso_banco_em,
                 COALESCE(tp.data_abertura,tp.criado_em) AS chave_fifo_em,
                 tp.atualizado_em AS ultimo_update_terminal_em,tp.triagem_status,
                 tp.log_workflow
          FROM dataset_controle dc
          JOIN tickets_processados tp ON tp.id=dc.ticket_id
          WHERE dc.run_id=%s
        ),
        tempos AS (
          SELECT
            a.ticket_id,a.ingresso_banco_em,a.ultimo_update_terminal_em,
            a.triagem_status,
            reserva.primeira_reserva_wf06_em,
            (
              SELECT MIN(i.criado_em)
              FROM ia_decisoes i
              WHERE i.ticket_id=a.ticket_id
                AND i.run_id=%s
            ) AS primeira_decisao_ia_em,
            ROW_NUMBER() OVER (
              ORDER BY a.ingresso_banco_em,a.ticket_id
            ) AS ordem_ingresso,
            ROW_NUMBER() OVER (
              ORDER BY a.chave_fifo_em,a.ticket_id
            ) AS ordem_fifo_esperada
          FROM alvo_base a
          LEFT JOIN LATERAL (
            SELECT MIN(
              CASE
                WHEN COALESCE(evento->>'ts','') ~
                  '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+(Z|[+-][0-9]{2}:[0-9]{2})$'
                THEN (evento->>'ts')::timestamptz
              END
            ) AS primeira_reserva_wf06_em
            FROM jsonb_array_elements(
              CASE jsonb_typeof(COALESCE(a.log_workflow,'[]'::jsonb))
                WHEN 'array' THEN COALESCE(a.log_workflow,'[]'::jsonb)
                WHEN 'object' THEN jsonb_build_array(a.log_workflow)
                ELSE '[]'::jsonb
              END
            ) evento
            WHERE UPPER(COALESCE(evento->>'wf',''))='WF06'
              AND UPPER(COALESCE(evento->>'acao',''))='RESERVAR_FILA'
          ) reserva ON TRUE
        )
        SELECT
          ticket_id,ordem_ingresso,ordem_fifo_esperada,triagem_status,
          ingresso_banco_em,primeira_reserva_wf06_em,
          primeira_decisao_ia_em,ultimo_update_terminal_em,
          (ordem_ingresso <= %s) AS warmup,
          CASE WHEN ingresso_banco_em <= primeira_reserva_wf06_em
            THEN ROUND(EXTRACT(EPOCH FROM (
              primeira_reserva_wf06_em-ingresso_banco_em
            ))::numeric,3) END AS espera_ingresso_banco_ate_primeira_reserva_wf06_s,
          CASE WHEN ingresso_banco_em <= primeira_decisao_ia_em
            THEN ROUND(EXTRACT(EPOCH FROM (
              primeira_decisao_ia_em-ingresso_banco_em
            ))::numeric,3) END AS espera_ingresso_banco_ate_primeira_decisao_ia_s,
          CASE WHEN primeira_reserva_wf06_em <= primeira_decisao_ia_em
            THEN ROUND(EXTRACT(EPOCH FROM (
              primeira_decisao_ia_em-primeira_reserva_wf06_em
            ))::numeric,3) END AS duracao_primeira_reserva_ate_primeira_decisao_ia_s,
          CASE WHEN ingresso_banco_em <= ultimo_update_terminal_em
            THEN ROUND(EXTRACT(EPOCH FROM (
              ultimo_update_terminal_em-ingresso_banco_em
            ))::numeric,3) END AS duracao_ingresso_banco_ate_ultimo_update_terminal_s
        FROM tempos
        ORDER BY ordem_ingresso
        """,
        (run_id, run_id, warmup),
    )
    temporal_audit = audit_temporal_observations(observations)
    result = {**rows, **quality, **temporal_audit}
    result["observations"] = observations
    started = [
        _timestamp_seconds(row.get("ingresso_banco_em"))
        for row in observations
        if _timestamp_seconds(row.get("ingresso_banco_em")) is not None
    ]
    finished = [
        _timestamp_seconds(row.get("ultimo_update_terminal_em"))
        for row in observations
        if _timestamp_seconds(row.get("ultimo_update_terminal_em")) is not None
    ]
    drain_elapsed = (
        max(finished) - min(started)
        if started and finished
        else None
    )
    result["janela_drenagem_ingresso_banco_ate_ultimo_update_terminal_s"] = (
        round(drain_elapsed, 3) if drain_elapsed is not None else None
    )
    result["vazao_observada_terminalizacoes_por_minuto"] = (
        round(float(result["total"]) * 60.0 / drain_elapsed, 6)
        if drain_elapsed is not None and drain_elapsed > 0
        else None
    )
    result["p99_confirmatorio"] = bool(result.get("latencias_validas", 0) >= 500)
    result["nota_p99"] = (
        "confirmatório"
        if result["p99_confirmatorio"]
        else "exploratório; requer pelo menos 500 latências medidas por tratamento"
    )
    result["definicao_latencia"] = (
        "intervalo observado entre tickets_processados.criado_em e "
        "tickets_processados.atualizado_em no estado terminal; não inclui o "
        "tempo anterior à ingestão no banco e não deve ser rotulado como "
        "latência ponta a ponta do usuário"
    )
    result["fonte_inicio_observacao"] = "tickets_processados.criado_em"
    result["fonte_fim_observacao"] = (
        "tickets_processados.atualizado_em após estado terminal observado"
    )
    result["fonte_fifo"] = (
        "primeiro evento WF06/RESERVAR_FILA em tickets_processados.log_workflow"
    )
    result["success"] = bool(
        result["total"] > 0
        and result["terminal"] == result["total"]
        and result["erros_ia"] == 0
        and result["probabilidades_invalidas"] == 0
        and result["rate_limits_decisoes"] == 0
        and result["rate_limits_429"] == 0
        and result["tentativas_modelo_falhas"] == 0
        and result["retentativas_modelo"] == 0
        and result["falhas_retentaveis"] == 0
        and result["timeouts_modelo"] == 0
        and result["fallbacks_utilizados"] == 0
        and result["tentativas_modelo_inesperado"] == 0
        and result["tentativas_proveniencia_invalida"] == 0
        and result["retentativas_workflow"] == 0
        and result["entradas_dlq"] == 0
        and result["entradas_dlq_abertas"] == 0
        and result["reingressos_fila"] == 0
        and result["ciclos_wf06_metrificados"] > 0
        and result["liberacoes_wf06"] >= result["total"]
        and result["decisoes_total"] >= result["total"]
        and result["tentativas_modelo_total"] == result["decisoes_total"]
        and result["latencias_validas"] == result["total_medido"]
        and result["timestamps_ausentes"] == 0
        and result["latencias_negativas"] == 0
        and result["violacoes_fifo_primeira_reserva"] == 0
    )
    return result


def aggregate_configurations(
    runs: list[dict],
    configs: list[dict],
    repetitions: int,
    p95_sla_seconds: float | None,
) -> list[dict]:
    aggregates: list[dict] = []
    for config in configs:
        group = [
            item
            for item in runs
            if item["id"] == config["id"]
        ]
        measured = [
            observation
            for item in group
            for observation in item["metrics"].get("observations", [])
            if not observation.get("warmup")
        ]
        waits = [
            float(
                observation[
                    "espera_ingresso_banco_ate_primeira_decisao_ia_s"
                ]
            )
            for observation in measured
            if observation.get(
                "espera_ingresso_banco_ate_primeira_decisao_ia_s"
            )
            is not None
        ]
        latencies = [
            float(
                observation[
                    "duracao_ingresso_banco_ate_ultimo_update_terminal_s"
                ]
            )
            for observation in measured
            if observation.get(
                "duracao_ingresso_banco_ate_ultimo_update_terminal_s"
            )
            is not None
        ]
        throughputs = [
            float(
                item["metrics"][
                    "vazao_observada_terminalizacoes_por_minuto"
                ]
            )
            for item in group
            if item["metrics"].get(
                "vazao_observada_terminalizacoes_por_minuto"
            )
            is not None
        ]
        successful_runs = sum(bool(item["metrics"].get("success")) for item in group)
        complete = len(group) == repetitions
        p95 = percentile(latencies, 0.95)
        sla_met = (
            p95 is not None and p95 <= p95_sla_seconds
            if p95_sla_seconds is not None
            else None
        )
        all_success = complete and successful_runs == repetitions
        aggregates.append(
            {
                **config,
                "runs_expected": repetitions,
                "runs_observed": len(group),
                "successful_runs": successful_runs,
                "all_runs_successful": all_success,
                "run_success_wilson_95": wilson_interval(
                    successful_runs, len(group)
                ),
                "tickets_total": sum(
                    int(item["metrics"].get("total") or 0) for item in group
                ),
                "latency_observations_after_warmup": len(latencies),
                "espera_ingresso_banco_ate_primeira_decisao_ia_s": {
                    "mean": sum(waits) / len(waits) if waits else None,
                    "p50": percentile(waits, 0.50),
                    "p95": percentile(waits, 0.95),
                    "p99": percentile(waits, 0.99),
                },
                "duracao_ingresso_banco_ate_ultimo_update_terminal_s": {
                    "mean": sum(latencies) / len(latencies) if latencies else None,
                    "p50": percentile(latencies, 0.50),
                    "p95": p95,
                    "p99": percentile(latencies, 0.99),
                },
                "vazao_observada_terminalizacoes_por_minuto": {
                    "mean_between_runs": (
                        sum(throughputs) / len(throughputs) if throughputs else None
                    ),
                    "p50_between_runs": percentile(throughputs, 0.50),
                    "minimum_between_runs": min(throughputs) if throughputs else None,
                },
                "p95_sla_seconds": p95_sla_seconds,
                "p95_sla_met": sla_met,
                "p99_confirmatory": len(latencies) >= 500,
                "telemetria": {
                    "tentativas_modelo": sum(
                        int(item["metrics"].get("tentativas_modelo_total") or 0)
                        for item in group
                    ),
                    "retentativas_modelo": sum(
                        int(item["metrics"].get("retentativas_modelo") or 0)
                        for item in group
                    ),
                    "retentativas_workflow": sum(
                        int(item["metrics"].get("retentativas_workflow") or 0)
                        for item in group
                    ),
                    "rate_limits_429": sum(
                        int(item["metrics"].get("rate_limits_429") or 0)
                        for item in group
                    ),
                    "entradas_dlq": sum(
                        int(item["metrics"].get("entradas_dlq") or 0)
                        for item in group
                    ),
                    "reingressos_fila": sum(
                        int(item["metrics"].get("reingressos_fila") or 0)
                        for item in group
                    ),
                },
                "eligible_for_selection": bool(
                    all_success and (sla_met is not False)
                ),
            }
        )
    return aggregates


def write_report(path: Path, payload: dict) -> None:
    lines = [
        "# Calibração repetida da fila WF06",
        "",
        f"- Início: `{payload['started_at']}`",
        f"- Fase: `{payload['phase']}`",
        f"- Repetições por tratamento: `{payload['repetitions']}`",
        f"- Tickets por repetição: `{payload['tickets_per_repetition']}`",
        f"- Warm-up excluído da latência: `{payload['warmup_per_repetition']}`",
        f"- Concorrência de ingresso GLPI: `{payload['ingress_concurrency']}`",
        f"- Perfil de ingresso: `{payload['ingress_profile']}`",
        f"- Intervalo/tempo médio de ingresso: `{payload['ingress_interval_seconds']}s`",
        f"- Modelo LOCAL: `{payload['model']}`",
        f"- SHA-256 do manifesto: `{payload['model_provenance']['manifest_sha256']}`",
        f"- SHA-256 do bundle: `{payload['model_provenance']['bundle_sha256']}`",
        "- SLA p95 da duração ingresso no banco → atualização terminal: "
        f"`{payload.get('p95_sla_seconds')}` segundos",
        f"- Configuração aprovada: `{payload.get('selected_config')}`",
        f"- Aprovada: `{'SIM' if payload['approved'] else 'NÃO'}`",
        "",
        "Uma configuração só é aprovada quando todas as repetições terminam sem "
        "erro de IA, rate limit, probabilidade inválida, timeout, fallback, DLQ, "
        "proveniência divergente, fila residual, violação de ordem ou interferência "
        "de tickets externos à janela isolada.",
        "",
        "A duração reportada começa em `tickets_processados.criado_em` e termina "
        "em `tickets_processados.atualizado_em` no estado terminal observado. Ela "
        "não inclui o tempo anterior à ingestão e, portanto, não é rotulada como "
        "latência ponta a ponta do usuário.",
        "",
    ]
    for item in payload["runs"]:
        report_metrics = {
            key: value
            for key, value in item["metrics"].items()
            if key != "observations"
        }
        lines.extend(
            [
                f"## {item['run_id']}",
                "",
                f"- Configuração: lote `{item['batch']}`, intervalo `{item['interval_seconds']}s`",
                f"- Perfil/carga: `{item['ingress_profile']}` / `{item['tickets_per_repetition']}` tickets",
                f"- Repetição: `{item['repetition']}`",
                f"- Resultado: `{'OK' if item['metrics']['success'] else 'FALHA'}`",
                f"- Métricas: `{json.dumps(report_metrics, ensure_ascii=False, default=str)}`",
                "",
            ]
        )
    lines.extend(["## Resumo por configuração", ""])
    for aggregate in payload.get("configuration_aggregates", []):
        lines.extend(
            [
                f"### Lote {aggregate['batch']} a cada {aggregate['interval_seconds']}s",
                "",
                f"- Elegível: `{'SIM' if aggregate['eligible_for_selection'] else 'NÃO'}`",
                f"- Resumo: `{json.dumps(aggregate, ensure_ascii=False, default=str)}`",
                "",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calibração repetida dos parâmetros de liberação do WF06."
    )
    parser.add_argument(
        "--configuracoes",
        default="1@60,2@45,3@30",
        help="Lista lote@intervalo_segundos.",
    )
    parser.add_argument(
        "--fase",
        choices=tuple(MINIMUM_REPETITIONS),
        default="rastreio",
        help="Define o mínimo protocolar de repetições.",
    )
    parser.add_argument("--repeticoes", type=int, default=3)
    parser.add_argument("--tickets-por-repeticao", type=int, default=12)
    parser.add_argument("--ingress-interval", type=float, default=0.0)
    parser.add_argument(
        "--ingress-profile",
        choices=INGRESS_PROFILES,
        default="deterministic",
        help=(
            "deterministic usa intervalo fixo; poisson usa chegadas exponenciais "
            "reprodutíveis; burst submete a rajada sem espaçamento."
        ),
    )
    parser.add_argument(
        "--burst-sizes",
        default=",".join(str(value) for value in DEFAULT_BURST_SIZES),
        help="Tamanhos usados pelo perfil burst; protocolo: 25,50,100.",
    )
    parser.add_argument(
        "--concorrencia-ingresso",
        type=int,
        default=4,
        help="Número de requisições GLPI simultâneas por repetição.",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=2,
        help="Primeiros tickets excluídos somente das métricas de latência.",
    )
    parser.add_argument("--seed", type=int, default=20260702)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--poll", type=int, default=10)
    parser.add_argument(
        "--p95-sla-seconds",
        type=float,
        help=(
            "SLA p95 pré-registrado para a duração entre o ingresso em "
            "tickets_processados e a atualização terminal observada. Não é "
            "latência ponta a ponta do usuário. Se omitido, a aprovação é "
            "apenas operacional e não aplica gate de duração."
        ),
    )
    parser.add_argument("--randomizar-ordem", action="store_true", default=True)
    parser.add_argument("--ordem-fixa", dest="randomizar_ordem", action="store_false")
    parser.add_argument("--saida-dir", default="avaliacao/resultados/calibracao-fila-v2.6")
    parser.add_argument(
        "--model-manifest",
        "--modelo-manifesto",
        dest="model_manifest",
        required=True,
        help=(
            "Manifesto imutável do modelo LOCAL realmente carregado; não há "
            "padrão para impedir calibração acidental de uma versão obsoleta."
        ),
    )
    parser.add_argument(
        "--local-ai-url",
        default="http://127.0.0.1:8090",
        help="Serviço LOCAL usado apenas para a prova fail-closed de proveniência.",
    )
    parser.add_argument(
        "--local-token-env",
        default="IA_LOCAL_API_TOKEN",
        help="Nome da variável de ambiente que contém o token LOCAL.",
    )
    parser.add_argument("--local-ai-timeout", type=float, default=30.0)
    parser.add_argument("--url", default=configured_value("GLPI_URL"))
    parser.add_argument("--app-token", default=configured_value("GLPI_APP_TOKEN"))
    parser.add_argument("--user", default=configured_value("GLPI_USER"))
    parser.add_argument("--password", default=configured_value("GLPI_PASSWORD"))
    parser.add_argument("--postgres-container", default="glpi-dedup-db")
    parser.add_argument("--postgres-user", default="triagem_user")
    parser.add_argument("--postgres-db", default="triagem")
    return parser.parse_args()


@serialized_experiment(checker.connect_pg, "CALIBRACAO_VAZAO")
def _run_calibration(args: argparse.Namespace) -> int:
    for attribute, option in (
        ("url", "--url/GLPI_URL"),
        ("app_token", "--app-token/GLPI_APP_TOKEN"),
        ("user", "--user/GLPI_USER"),
        ("password", "--password/GLPI_PASSWORD"),
    ):
        value = str(getattr(args, attribute, "") or "").strip()
        if not value or value.upper() == "CHANGE_ME":
            raise SystemExit(f"Configuração obrigatória ausente: {option}")
    minimum_repetitions = MINIMUM_REPETITIONS[args.fase]
    if args.repeticoes < minimum_repetitions:
        raise SystemExit(
            f"A fase {args.fase} exige pelo menos {minimum_repetitions} "
            "repetições por tratamento."
        )
    if args.tickets_por_repeticao <= 0:
        raise SystemExit("--tickets-por-repeticao deve ser positivo.")
    burst_sizes = parse_burst_sizes(args.burst_sizes)
    if args.concorrencia_ingresso < 1:
        raise SystemExit("--concorrencia-ingresso deve ser >= 1.")
    minimum_tickets = (
        min(burst_sizes)
        if args.ingress_profile == "burst"
        else args.tickets_por_repeticao
    )
    if args.warmup < 0 or args.warmup >= minimum_tickets:
        raise SystemExit(
            "--warmup deve estar entre 0 e o menor tratamento menos 1."
        )
    if args.timeout <= 0 or args.poll <= 0:
        raise SystemExit("--timeout e --poll devem ser positivos.")
    if args.p95_sla_seconds is not None and args.p95_sla_seconds <= 0:
        raise SystemExit("--p95-sla-seconds deve ser positivo.")
    if args.ingress_interval < 0:
        raise SystemExit("--ingress-interval não pode ser negativo.")
    if args.ingress_profile == "poisson" and args.ingress_interval <= 0:
        raise SystemExit("O perfil poisson exige --ingress-interval positivo.")
    if args.ingress_profile == "burst" and args.ingress_interval != 0:
        raise SystemExit("O perfil burst exige --ingress-interval 0.")
    if args.fase == "rajada" and args.ingress_profile != "burst":
        raise SystemExit("A fase rajada exige --ingress-profile burst.")
    if args.ingress_profile == "burst" and args.fase != "rajada":
        raise SystemExit("O perfil burst deve ser executado com --fase rajada.")
    if args.local_ai_timeout <= 0:
        raise SystemExit("--local-ai-timeout deve ser positivo.")
    configs = parse_configs(args.configuracoes)
    if args.fase == "rajada" and tuple(burst_sizes) != DEFAULT_BURST_SIZES:
        raise SystemExit(
            "A fase rajada protocolar exige --burst-sizes 25,50,100."
        )
    treatments = build_treatments(
        configs,
        ingress_profile=args.ingress_profile,
        tickets_per_repetition=args.tickets_por_repeticao,
        burst_sizes=burst_sizes,
    )
    schedule = build_treatment_schedule(
        treatments,
        args.repeticoes,
        randomized=args.randomizar_ordem,
        seed=args.seed,
    )
    model_provenance = validate_model_manifest(Path(args.model_manifest))
    local_token = str(
        os.environ.get(args.local_token_env)
        or configured_value(args.local_token_env)
        or ""
    ).strip()
    runtime_provenance = preflight_local_ai(
        args.local_ai_url,
        local_token,
        model_provenance,
        timeout_seconds=args.local_ai_timeout,
    )
    out_dir = ROOT / args.saida_dir
    prepare_output_dir(out_dir)
    started_at = datetime.now().isoformat(timespec="seconds")
    runs: list[dict] = []
    active_run_id: str | None = None
    previous_runtime_profile = capture_n8n_queue_profile()
    previous_queue_controller: dict[str, Any] | None = None
    original_error: Exception | None = None
    try:
        bootstrap_scope = (
            "CALQ-BOOTSTRAP-" + datetime.now().strftime("%Y%m%dT%H%M%S%f")
        )
        with queue_scheduler_lock() as connection:
            previous_queue_controller = capture_queue_controller(connection)
            compose_n8n(
                previous_runtime_profile["batch"],
                previous_runtime_profile["interval_seconds"],
                run_scope=bootstrap_scope,
                model_version=previous_runtime_profile["model_version"],
            )
            assert_runtime_profile(
                {
                    **previous_runtime_profile,
                    "run_scope": bootstrap_scope,
                }
            )
        ensure_quiescent_queue()
        for index, item in enumerate(schedule, start=1):
            ensure_quiescent_queue()
            run_id = (
                f"CALQ-{datetime.now().strftime('%Y%m%dT%H%M%S%f')}-"
                f"{item['id']}-R{item['repetition']}"
            )
            active_run_id = run_id
            print(
                f"[CAL] {index}/{len(schedule)} {run_id}: "
                f"lote={item['batch']} intervalo={item['interval_seconds']}s"
            )
            # Blocos de mesma repetição usam exatamente a mesma carga em todas
            # as configurações; só lote/intervalo podem explicar a diferença.
            seed = args.seed + item["repetition"]
            cases = calibration_cases(item["tickets_per_repetition"], seed)
            created, metrics = execute_repetition(
                item,
                run_id,
                seed,
                cases,
                args,
                model_provenance,
            )
            checker.set_experiment_status(
                run_id, "CONCLUIDO" if metrics["success"] else "FALHOU"
            )
            active_run_id = None
            run_payload = {
                **item,
                "run_id": run_id,
                "protocol_version": CALIBRATION_PROTOCOL_VERSION,
                "model_provenance": model_provenance,
                "runtime_provenance_preflight": runtime_provenance,
                "tickets": created,
                "metrics": metrics,
            }
            runs.append(run_payload)
            (out_dir / f"{run_id}.json").write_text(
                json.dumps(run_payload, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
    except Exception as exc:
        original_error = exc
        if active_run_id:
            checker.set_experiment_status(active_run_id, "FALHOU")
        raise
    finally:
        if previous_queue_controller is not None:
            try:
                restore_calibration_state(
                    previous_runtime_profile,
                    previous_queue_controller,
                )
            except Exception as exc:
                restoration_error = RuntimeError(
                    "Restauração pós-calibração falhou: "
                    f"{type(exc).__name__}: {exc}"
                )
                if original_error is not None:
                    raise ExceptionGroup(
                        "Calibração e restauração falharam",
                        [original_error, restoration_error],
                    )
                raise restoration_error from exc

    configuration_aggregates = aggregate_configurations(
        runs,
        treatments,
        args.repeticoes,
        args.p95_sla_seconds,
    )
    if args.ingress_profile == "burst":
        safe = []
        for config in configs:
            group = [
                item
                for item in configuration_aggregates
                if item["base_configuration_id"] == config["id"]
            ]
            observed_sizes = {item.get("burst_size") for item in group}
            if (
                observed_sizes == set(burst_sizes)
                and all(item["eligible_for_selection"] for item in group)
            ):
                safe.append(
                    {
                        **config,
                        "ingress_profile": "burst",
                        "burst_sizes": burst_sizes,
                    }
                )
    else:
        safe = [
            {
                "id": item["id"],
                "batch": item["batch"],
                "interval_seconds": item["interval_seconds"],
                "ingress_profile": item["ingress_profile"],
            }
            for item in configuration_aggregates
            if item["eligible_for_selection"]
        ]
    selected = min(
        safe,
        key=lambda item: (item["interval_seconds"], -item["batch"]),
        default=None,
    )
    payload = {
        "protocol_version": CALIBRATION_PROTOCOL_VERSION,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "repetitions": args.repeticoes,
        "phase": args.fase,
        "minimum_repetitions": minimum_repetitions,
        "tickets_per_repetition": (
            burst_sizes
            if args.ingress_profile == "burst"
            else args.tickets_por_repeticao
        ),
        "warmup_per_repetition": args.warmup,
        "ingress_concurrency": args.concorrencia_ingresso,
        "ingress_profile": args.ingress_profile,
        "ingress_interval_seconds": args.ingress_interval,
        "ingress_seed": args.seed,
        "burst_sizes": burst_sizes if args.ingress_profile == "burst" else [],
        "randomized_order": args.randomizar_ordem,
        "model_role": CALIBRATION_MODEL_ROLE,
        "model": model_provenance["model_version"],
        "model_provenance": model_provenance,
        "runtime_provenance_preflight": runtime_provenance,
        "ia_execution_mode": CALIBRATION_EXECUTION_MODE,
        "failover_enabled": False,
        "queue_run_scope": "FILA_IA_RUN_SCOPE por repetição; perfil anterior restaurado ao final",
        "restored_runtime_profile": previous_runtime_profile,
        "p95_sla_seconds": args.p95_sla_seconds,
        "p95_sla_metric": (
            "tickets_processados.criado_em_ate_"
            "tickets_processados.atualizado_em_terminal"
        ),
        "approval_scope": (
            "OPERACIONAL_COM_GATE_P95_PRE_REGISTRADO"
            if args.p95_sla_seconds is not None
            else "OPERACIONAL_SEM_GATE_DE_LATENCIA"
        ),
        "scientific_result": False,
        "confirmatory_eligible": False,
        "approved": selected is not None,
        "selected_config": selected,
        "selection_policy": (
            "entre tratamentos elegíveis, menor intervalo e depois maior lote; "
            "a elegibilidade exige todas as repetições sem falha e, quando "
            "informado, p95 dentro do SLA pré-registrado"
        ),
        "configuration_aggregates": configuration_aggregates,
        "runs": runs,
    }
    approved_path = out_dir / "calibracao_aprovada.json"
    approved_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    write_report(out_dir / "relatorio.md", payload)
    print(f"[OK] Resultado: {approved_path}")
    return 0 if selected else 2


def main() -> int:
    return _run_calibration(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
