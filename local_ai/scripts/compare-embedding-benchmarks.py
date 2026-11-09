"""Valida, consolida e seleciona a melhor contagem de threads do benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_THREADS = {1, 2, 4}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolved(path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def validate(payload: dict[str, Any], path: Path) -> int:
    if payload.get("schema") != "projeto-ic-embedding-runtime-benchmark-v1":
        raise ValueError(f"Schema inválido em {path}")
    if payload.get("status") != "VALID" or payload.get("backend") != "pytorch_fp32":
        raise ValueError(f"Execução inválida ou backend incorreto em {path}")
    model = payload.get("model", {})
    if model.get("dimension") != 384 or model.get("floating_parameter_dtypes") != [
        "torch.float32"
    ]:
        raise ValueError(f"Dimensão/precisão inválida em {path}")
    protocol = payload.get("protocol", {})
    threads = int(protocol.get("cpu_threads", 0))
    if protocol.get("warmup_rounds_per_workload") != 5:
        raise ValueError(f"Warmup divergente em {path}")
    if protocol.get("measured_rounds_per_workload") != 30:
        raise ValueError(f"Número de rodadas divergente em {path}")
    if protocol.get("warmup_excluded_from_latency") is not True:
        raise ValueError(f"Warmup incluído indevidamente em {path}")
    return threads


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, nargs="+", required=True)
    parser.add_argument("--excluded-contaminated", type=Path, nargs="*", default=[])
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if len(args.input) != len(EXPECTED_THREADS):
        raise SystemExit("Informe exatamente três resultados: 1, 2 e 4 threads")
    entries: list[tuple[Path, dict[str, Any], int]] = []
    for raw_path in args.input:
        path = resolved(raw_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries.append((path, payload, validate(payload, path)))
    observed = {threads for _, _, threads in entries}
    if observed != EXPECTED_THREADS:
        raise SystemExit(f"Threads esperadas {sorted(EXPECTED_THREADS)}; recebidas {sorted(observed)}")

    input_hashes = {payload["protocol"]["inputs_sha256"] for _, payload, _ in entries}
    model_hashes = {payload["model"]["model_safetensors_sha256"] for _, payload, _ in entries}
    if len(input_hashes) != 1 or len(model_hashes) != 1:
        raise SystemExit("Entradas ou pesos divergiram entre as execuções")

    def selection_key(entry: tuple[Path, dict[str, Any], int]) -> tuple[float, ...]:
        _, payload, _ = entry
        workloads = payload["workloads"]
        return (
            float(workloads["deduplication_batch_7"]["latency_seconds"]["p95"]),
            float(workloads["classification_batch_1"]["latency_seconds"]["p95"]),
            -float(workloads["deduplication_batch_7"]["throughput_texts_per_second"]),
            float(payload["memory"]["max_sampled_rss_mb"]),
        )

    winner = min(entries, key=selection_key)
    comparisons = []
    for path, payload, threads in sorted(entries, key=lambda item: item[2]):
        workloads = payload["workloads"]
        comparisons.append(
            {
                "cpu_threads": threads,
                "model_load_seconds": payload["timing"]["model_load_seconds"],
                "max_sampled_rss_mb": payload["memory"]["max_sampled_rss_mb"],
                "classification_batch_1": workloads["classification_batch_1"],
                "deduplication_batch_7": workloads["deduplication_batch_7"],
                "source": str(path.relative_to(ROOT)),
                "source_sha256": sha256_file(path),
            }
        )

    output_payload = {
        "schema": "projeto-ic-embedding-thread-comparison-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "VALID",
        "backend": "pytorch_fp32",
        "model_dimension": 384,
        "precision": "fp32",
        "selection_policy": [
            "minimum deduplication_batch_7 p95 latency",
            "minimum classification_batch_1 p95 latency",
            "maximum deduplication_batch_7 throughput",
            "minimum max sampled RSS",
        ],
        "recommended_cpu_threads": winner[2],
        "comparisons": comparisons,
        "excluded_runs": [
            {
                "source": str(resolved(path).relative_to(ROOT)),
                "source_sha256": sha256_file(resolved(path)),
                "reason": "concurrent Python process observed during measurement",
            }
            for path in args.excluded_contaminated
        ],
        "limitations": [
            "host file cache was not flushed",
            "background processes were not suspended",
            "results measure embedding only, not the complete workflow",
        ],
        "provenance": {
            "script": str(Path(__file__).resolve().relative_to(ROOT)),
            "script_sha256": sha256_file(Path(__file__).resolve()),
        },
    }
    output = resolved(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(output_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(output_payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
