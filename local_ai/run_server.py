"""
Script de inicialização do servidor local_ai com variáveis de ambiente configuradas.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULTS = {
    "LOCAL_AI_MODE": "production",
    "LOCAL_AI_HOST": "0.0.0.0",
    "LOCAL_AI_PORT": "8090",
    "LOCAL_AI_CPU_THREADS": "2",
    "LOCAL_AI_MAX_CONCURRENT": "4",
    "LOCAL_AI_MAX_EMBED_BATCH": "4",
    "LOCAL_AI_DEV_FALLBACK": "off",
    "LOCAL_AI_ALLOW_MODEL_DOWNLOAD": "false",
    "LOCAL_AI_EMBED_BACKEND": "pytorch_fp32",
    "LOCAL_AI_EMBED_MODEL_REVISION": "835ad14087e140460703cf0fae09f97d469d65c2",
    "LOCAL_AI_EMBED_MODEL_PATH": str(
        ROOT / "local_ai" / "models" / "granite-embedding-97m-multilingual-r2"
    ),
    "LOCAL_AI_MAX_CANDIDATES": "20",
    "LOCAL_AI_HYBRID_MANIFEST": str(
        ROOT / "local_ai" / "artifacts" / "local_hybrid_manifest.json"
    ),
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "TOKENIZERS_PARALLELISM": "false",
    "PYTHONUNBUFFERED": "1",
}
for name, value in DEFAULTS.items():
    os.environ.setdefault(name, value)

api_token = os.environ.get("LOCAL_AI_API_TOKEN", "").strip()
if not api_token or api_token.upper() in {"CHANGE_ME", "CHANGEME", "SEU_TOKEN"}:
    raise RuntimeError(
        "Defina LOCAL_AI_API_TOKEN fora do código ou use "
        "local_ai/scripts/start-local-ai.ps1."
    )

if __name__ == "__main__":
    from local_ai.config import Settings
    from local_ai.http_api import serve

    settings = Settings.from_env()
    serve(settings)
