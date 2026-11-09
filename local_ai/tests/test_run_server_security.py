from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "local_ai" / "run_server.py"


def test_direct_runner_requires_external_token_without_embedding_a_value() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert 'os.environ["LOCAL_AI_API_TOKEN"] =' not in source
    assert 'os.environ.get("LOCAL_AI_API_TOKEN"' in source

    environment = os.environ.copy()
    environment.pop("LOCAL_AI_API_TOKEN", None)
    completed = subprocess.run(
        [sys.executable, "-c", "import local_ai.run_server"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode != 0
    assert "Defina LOCAL_AI_API_TOKEN fora do código" in completed.stderr
