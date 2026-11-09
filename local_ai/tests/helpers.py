from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from local_ai.config import Settings


ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "artifacts"


def development_settings(**changes: object) -> Settings:
    settings = replace(
        Settings.from_env(),
        mode="development",
        artifact_dir=ARTIFACT_DIR.resolve(),
        hybrid_manifest_path="",
        embedding_model_path="",
        allow_model_download=False,
        dev_fallback="tfidf",
        extractor_enabled=False,
        extractor_url="",
        api_token="",
        max_concurrent_requests=1,
    )
    return replace(settings, **changes)

