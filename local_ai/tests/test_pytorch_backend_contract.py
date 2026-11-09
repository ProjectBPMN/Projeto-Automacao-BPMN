from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from local_ai.backends import (
    BackendMetadata,
    BackendUnavailable,
    EmbeddingProvider,
    _GraniteEmbeddingBackend,
)
from local_ai.config import Settings
from local_ai.inference import LocalAIService

from .helpers import development_settings


class PyTorchBackendContractTests(unittest.TestCase):
    def test_default_runtime_is_pytorch_fp32(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_env()
            self.assertEqual(settings.embedding_backend, "pytorch_fp32")
            self.assertEqual(settings.cpu_threads, 4)

    def test_non_pytorch_runtime_fails_before_model_resolution(self) -> None:
        with patch.dict(
            os.environ,
            {"LOCAL_AI_EMBED_BACKEND": "openvino_int8"},
            clear=True,
        ):
            backend = _GraniteEmbeddingBackend(Settings.from_env())
            with self.assertRaisesRegex(BackendUnavailable, "pytorch_fp32"):
                backend._load()

    def test_non_pytorch_runtime_is_not_reported_as_ready(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LOCAL_AI_EMBED_BACKEND": "openvino_int8",
                "LOCAL_AI_EMBED_MODEL_PATH": str(
                    development_settings().artifact_dir
                ),
            },
            clear=True,
        ):
            provider = EmbeddingProvider(Settings.from_env(), {"__default__": 1.0})
            status = provider.status()
            self.assertFalse(status["ready"])
            self.assertFalse(status["scientific_eligible"])
            self.assertFalse(status["runtime_backend_supported"])

    def test_internal_embedding_is_split_without_losing_vector_order(self) -> None:
        settings = development_settings(max_embed_batch=2, max_candidates=4)
        provider = EmbeddingProvider(settings, {"__default__": 1.0})

        class RecordingBackend:
            def __init__(self) -> None:
                self.calls: list[list[str]] = []

            def encode(self, texts: list[str]) -> list[list[float]]:
                self.calls.append(list(texts))
                return [
                    [float(int(text.removeprefix("texto-")))] + [0.0] * 383
                    for text in texts
                ]

        recording = RecordingBackend()
        provider._selected = recording
        provider._metadata = BackendMetadata(
            backend="granite_embedding_pytorch_fp32",
            model="fixture",
            fallback_used=False,
            fallback_reason=None,
            development_only=False,
            scientific_eligible=True,
            dimension=384,
            runtime_backend="pytorch_fp32",
            precision="fp32",
        )
        vectors, metadata = provider.encode([f"texto-{index}" for index in range(5)])

        self.assertEqual([len(call) for call in recording.calls], [2, 2, 1])
        self.assertEqual([int(vector[0]) for vector in vectors], list(range(5)))
        self.assertEqual(metadata.runtime_backend, "pytorch_fp32")
        self.assertEqual(metadata.precision, "fp32")

    def test_public_embed_keeps_request_limit(self) -> None:
        service = LocalAIService(development_settings(max_embed_batch=2))
        with self.assertRaisesRegex(ValueError, "limite público de 2"):
            service.embed({"input": ["um", "dois", "três"]})


if __name__ == "__main__":
    unittest.main()
