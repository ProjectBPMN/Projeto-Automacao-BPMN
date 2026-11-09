from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "sim", "yes", "on"}


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def _float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True, slots=True)
class Settings:
    mode: str
    host: str
    port: int
    api_token: str
    artifact_dir: Path
    hybrid_manifest_path: str
    cpu_threads: int
    max_concurrent_requests: int
    max_body_bytes: int
    max_text_chars: int
    max_embed_batch: int
    max_candidates: int
    cache_entries: int
    cache_bytes: int
    confidence_minimum: float
    preferred_embedding_model: str
    embedding_model_path: str
    allow_model_download: bool
    dev_fallback: str
    extractor_enabled: bool
    extractor_url: str
    extractor_model: str
    extractor_timeout_seconds: float
    extractor_cooldown_seconds: float
    embedding_model_revision: str = "835ad14087e140460703cf0fae09f97d469d65c2"
    embedding_backend: str = "pytorch_fp32"

    @property
    def development(self) -> bool:
        return self.mode == "development"

    @classmethod
    def from_env(cls) -> "Settings":
        base = Path(__file__).resolve().parent
        mode = os.getenv("LOCAL_AI_MODE", "production").strip().lower()
        if mode not in {"production", "development", "test"}:
            mode = "production"
        fallback = os.getenv("LOCAL_AI_DEV_FALLBACK", "off").strip().lower()
        if fallback not in {"off", "tfidf", "hash"}:
            fallback = "off"
        return cls(
            mode=mode,
            host=os.getenv("LOCAL_AI_HOST", "127.0.0.1"),
            port=_int_env("LOCAL_AI_PORT", 8090, 1, 65535),
            api_token=os.getenv("LOCAL_AI_API_TOKEN", ""),
            artifact_dir=Path(os.getenv("LOCAL_AI_ARTIFACT_DIR", str(base / "artifacts"))).resolve(),
            hybrid_manifest_path=os.getenv("LOCAL_AI_HYBRID_MANIFEST", "").strip(),
            cpu_threads=_int_env("LOCAL_AI_CPU_THREADS", 4, 1, 4),
            max_concurrent_requests=_int_env("LOCAL_AI_MAX_CONCURRENT", 1, 1, 4),
            max_body_bytes=_int_env("LOCAL_AI_MAX_BODY_BYTES", 1_048_576, 4096, 8_388_608),
            max_text_chars=_int_env("LOCAL_AI_MAX_TEXT_CHARS", 6000, 256, 50_000),
            max_embed_batch=_int_env("LOCAL_AI_MAX_EMBED_BATCH", 16, 1, 64),
            max_candidates=_int_env("LOCAL_AI_MAX_CANDIDATES", 20, 1, 20),
            cache_entries=_int_env("LOCAL_AI_CACHE_ENTRIES", 256, 0, 4096),
            cache_bytes=_int_env("LOCAL_AI_CACHE_BYTES", 16 * 1024 * 1024, 0, 256 * 1024 * 1024),
            confidence_minimum=_float_env("IA_CONFIANCA_MINIMA", 0.65, 0.5, 0.99),
            preferred_embedding_model=os.getenv(
                "LOCAL_AI_EMBED_MODEL",
                "ibm-granite/granite-embedding-97m-multilingual-r2",
            ),
            embedding_model_path=os.getenv("LOCAL_AI_EMBED_MODEL_PATH", "").strip(),
            allow_model_download=_bool_env("LOCAL_AI_ALLOW_MODEL_DOWNLOAD", False),
            dev_fallback=fallback,
            extractor_enabled=_bool_env("LOCAL_AI_EXTRACTOR_ENABLED", False),
            extractor_url=os.getenv(
                "LOCAL_AI_EXTRACTOR_URL", "http://127.0.0.1:8091/v1"
            ).strip(),
            extractor_model=os.getenv(
                "LOCAL_AI_EXTRACTOR_MODEL",
                "ibm-granite/granite-4.0-h-350m-GGUF-Q4_K_M",
            ),
            extractor_timeout_seconds=_float_env("LOCAL_AI_EXTRACTOR_TIMEOUT", 8.0, 1.0, 60.0),
            extractor_cooldown_seconds=_float_env(
                "LOCAL_AI_EXTRACTOR_COOLDOWN", 60.0, 0.0, 3600.0
            ),
            embedding_model_revision=os.getenv(
                "LOCAL_AI_EMBED_MODEL_REVISION",
                "835ad14087e140460703cf0fae09f97d469d65c2",
            ).strip(),
            embedding_backend=os.getenv(
                "LOCAL_AI_EMBED_BACKEND", "pytorch_fp32"
            ).strip().lower(),
        )

    def with_network(self, *, host: str, port: int) -> "Settings":
        return replace(self, host=host, port=port)
