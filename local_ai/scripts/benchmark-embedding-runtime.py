"""Benchmark reproduzível do Granite Embedding no workload real do n8n.

Mede lotes de um texto (classificação) e sete textos (chamado atual mais seis
candidatos de deduplicação). Warmup, carregamento do modelo e inferências são
registrados separadamente; nenhum resultado de warmup entra nas latências.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = ROOT / "local_ai" / "models" / "granite-embedding-97m-multilingual-r2"

WORKLOADS = {
    "classification_batch_1": [
        "Ar-condicionado da sala 204 do bloco B não está gelando desde ontem.",
    ],
    "deduplication_batch_7": [
        "Ar-condicionado da sala 204 do bloco B não está gelando desde ontem.",
        "O ar condicionado da sala 204, bloco B, liga mas não refrigera.",
        "Ar da sala 204 fazendo barulho forte, porém continua gelando.",
        "Ar-condicionado da sala 205 do bloco B parou de funcionar.",
        "Manutenção concluída no aparelho da sala 204; problema voltou hoje.",
        "Lâmpada queimada na sala 204 do bloco B, próximo à porta.",
        "Aparelho de climatização sem gelar; não informaram bloco nem sala.",
    ],
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        item
        for item in path.rglob("*")
        if item.is_file() and ".cache" not in item.relative_to(path).parts
    )
    for item in files:
        relative = item.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(item)))
    return digest.hexdigest()


def percentile(values: list[float], probability: float) -> float:
    """Percentil linear, equivalente ao método padrão do NumPy."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("Amostra vazia")
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def rounded(value: float) -> float:
    return round(float(value), 6)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--rounds", type=int, default=30)
    parser.add_argument("--cpu-threads", type=int, default=2)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.warmup < 1 or args.rounds < 5:
        raise SystemExit("Use warmup >= 1 e rounds >= 5")
    if not 1 <= args.cpu_threads <= 4:
        raise SystemExit("Use 1 a 4 threads de CPU")
    model_path = args.model_path.expanduser().resolve()
    if not model_path.is_dir():
        raise SystemExit(f"Modelo ausente: {model_path}")

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[name] = str(args.cpu_threads)

    import psutil  # type: ignore
    import numpy as np  # type: ignore
    import torch  # type: ignore
    from sentence_transformers import SentenceTransformer  # type: ignore

    process = psutil.Process()
    rss_after_import = process.memory_info().rss
    torch.set_num_threads(args.cpu_threads)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass

    load_started = time.perf_counter()
    model = SentenceTransformer(
        str(model_path),
        device="cpu",
        local_files_only=True,
        backend="torch",
    )
    model.to(dtype=torch.float32)
    model.eval()
    load_seconds = time.perf_counter() - load_started
    floating_dtypes = sorted(
        {
            str(parameter.dtype)
            for parameter in model.parameters()
            if parameter.is_floating_point()
        }
    )
    if floating_dtypes != ["torch.float32"]:
        raise SystemExit(f"Precisão inesperada: {floating_dtypes}")
    rss_after_model_load = process.memory_info().rss

    dimension = int(model.get_embedding_dimension() or 0)
    if dimension != 384:
        raise SystemExit(f"Dimensão inesperada: {dimension}")

    max_sampled_rss = process.memory_info().rss

    def encode(texts: list[str]) -> None:
        nonlocal max_sampled_rss
        vectors = np.asarray(
            model.encode(
                texts,
                batch_size=len(texts),
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            ),
            dtype=np.float32,
        )
        if vectors.shape != (len(texts), 384):
            raise RuntimeError(f"Shape inesperado: {vectors.shape}")
        if not np.isfinite(vectors).all():
            raise RuntimeError("Embedding contém valor não finito")
        norms = np.linalg.norm(vectors, axis=1)
        if not np.allclose(norms, 1.0, atol=1e-5):
            raise RuntimeError(f"Embedding não normalizado: {norms.tolist()}")
        max_sampled_rss = max(max_sampled_rss, process.memory_info().rss)

    for _ in range(args.warmup):
        for texts in WORKLOADS.values():
            encode(texts)

    timings: dict[str, list[float]] = {name: [] for name in WORKLOADS}
    benchmark_started = time.perf_counter()
    # Alternar workloads distribui aquecimento e throttling entre os dois lotes.
    for _ in range(args.rounds):
        for name, texts in WORKLOADS.items():
            started = time.perf_counter()
            encode(texts)
            timings[name].append(time.perf_counter() - started)
    benchmark_seconds = time.perf_counter() - benchmark_started

    workload_results: dict[str, Any] = {}
    for name, texts in WORKLOADS.items():
        values = timings[name]
        total_seconds = sum(values)
        workload_results[name] = {
            "batch_size": len(texts),
            "warmup_rounds_excluded": args.warmup,
            "measured_rounds": args.rounds,
            "total_texts": len(texts) * args.rounds,
            "total_seconds": rounded(total_seconds),
            "latency_seconds": {
                "mean": rounded(statistics.fmean(values)),
                "p50": rounded(statistics.median(values)),
                "p95": rounded(percentile(values, 0.95)),
                "minimum": rounded(min(values)),
                "maximum": rounded(max(values)),
            },
            "throughput_texts_per_second": rounded(
                (len(texts) * args.rounds) / total_seconds
            ),
        }

    script_path = Path(__file__).resolve()
    manifest_path = ROOT / "local_ai" / "models" / "manifest.json"
    payload = {
        "schema": "projeto-ic-embedding-runtime-benchmark-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "VALID",
        "backend": "pytorch_fp32",
        "device": "cpu",
        "model": {
            "id": "ibm-granite/granite-embedding-97m-multilingual-r2",
            "revision": "835ad14087e140460703cf0fae09f97d469d65c2",
            "path": str(model_path),
            "dimension": dimension,
            "floating_parameter_dtypes": floating_dtypes,
            "model_safetensors_sha256": sha256_file(model_path / "model.safetensors"),
            "tree_sha256": directory_sha256(model_path),
        },
        "protocol": {
            "cpu_threads": args.cpu_threads,
            "interop_threads": 1,
            "warmup_rounds_per_workload": args.warmup,
            "measured_rounds_per_workload": args.rounds,
            "workload_order": list(WORKLOADS),
            "warmup_excluded_from_latency": True,
            "downloads_disabled": True,
            "host_file_cache_flushed": False,
            "background_processes_suspended": False,
            "measurement_scope": "Granite embedding only; excludes HTTP, TF-IDF and calibrated classifiers",
            "interpretation": "steady-state host benchmark; model_load_seconds is not a cold-boot measurement",
            "inputs_sha256": hashlib.sha256(
                json.dumps(WORKLOADS, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        },
        "timing": {
            "model_load_seconds": rounded(load_seconds),
            "measured_loop_wall_seconds": rounded(benchmark_seconds),
        },
        "memory": {
            "rss_after_import_mb": rounded(rss_after_import / 1024**2),
            "rss_after_model_load_mb": rounded(rss_after_model_load / 1024**2),
            "max_sampled_rss_mb": rounded(max_sampled_rss / 1024**2),
            "system_total_mb": rounded(psutil.virtual_memory().total / 1024**2),
            "metric_definition": "RSS do processo; máximo amostrado após cada encode",
        },
        "workloads": workload_results,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpu_count": psutil.cpu_count(logical=True),
            "physical_cpu_count": psutil.cpu_count(logical=False),
            "packages": {
                name: version(name)
                for name in (
                    "torch",
                    "sentence-transformers",
                    "transformers",
                    "huggingface-hub",
                    "numpy",
                    "psutil",
                )
            },
        },
        "provenance": {
            "script": str(script_path.relative_to(ROOT)),
            "script_sha256": sha256_file(script_path),
            "model_manifest_sha256": sha256_file(manifest_path),
        },
    }
    output = args.output.expanduser()
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"Resultado: {output.resolve()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
