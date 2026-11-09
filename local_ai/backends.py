from __future__ import annotations

import hashlib
import importlib.util
import math
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .cache import BoundedLRUCache
from .config import Settings
from .text import l2_normalize, normalize_text, stable_hash, tokens


class BackendUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BackendMetadata:
    backend: str
    model: str
    fallback_used: bool
    fallback_reason: str | None
    development_only: bool
    scientific_eligible: bool
    dimension: int
    model_revision: str | None = None
    model_tree_sha256: str | None = None
    runtime_backend: str | None = None
    precision: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class _DevelopmentEmbeddingBackend:
    def __init__(self, mode: str, idf: dict[str, float], dimension: int = 384) -> None:
        self.mode = mode
        self.idf = idf
        self.dimension = dimension

    @staticmethod
    def _bucket(feature: str, dimension: int) -> tuple[int, float]:
        digest = hashlib.sha256(feature.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        return index, sign

    def _tfidf(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        normalized_tokens = tokens(text)
        counts: dict[str, int] = {}
        for token in normalized_tokens:
            counts[token] = counts.get(token, 0) + 1
        for token, count in counts.items():
            index, sign = self._bucket("w:" + token, self.dimension)
            idf = float(self.idf.get(token, self.idf.get("__default__", 1.0)))
            vector[index] += sign * (1.0 + math.log(count)) * idf
        # Bigramas melhoram a separação de "portão automático" e "ar condicionado".
        for left, right in zip(normalized_tokens, normalized_tokens[1:]):
            feature = f"b:{left}_{right}"
            index, sign = self._bucket(feature, self.dimension)
            vector[index] += sign * 1.25
        return l2_normalize(vector)

    def _hash(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        compact = " " + normalize_text(text) + " "
        for size in (3, 4, 5):
            for offset in range(max(0, len(compact) - size + 1)):
                feature = compact[offset : offset + size]
                index, sign = self._bucket(f"c{size}:{feature}", self.dimension)
                vector[index] += sign
        return l2_normalize(vector)

    def encode(self, texts: list[str]) -> list[list[float]]:
        method = self._tfidf if self.mode == "tfidf" else self._hash
        return [method(text) for text in texts]


class _GraniteEmbeddingBackend:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.dimension = 384
        self._model: Any | None = None
        self._lock = threading.Lock()
        self.model_tree_sha256: str | None = None

    @staticmethod
    def _directory_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        files = sorted(
            item
            for item in path.rglob("*")
            if item.is_file() and ".cache" not in item.relative_to(path).parts
        )
        if not files:
            raise BackendUnavailable("Diretório local do Granite está vazio")
        for item in files:
            relative = item.relative_to(path).as_posix().encode("utf-8")
            digest.update(len(relative).to_bytes(4, "big"))
            digest.update(relative)
            file_digest = hashlib.sha256()
            with item.open("rb") as handle:
                for chunk in iter(lambda: handle.read(65536), b""):
                    file_digest.update(chunk)
            digest.update(file_digest.digest())
        return digest.hexdigest()

    def _source(self) -> tuple[str, bool]:
        if self.settings.embedding_model_path:
            path = Path(self.settings.embedding_model_path).expanduser().resolve()
            if not path.exists():
                raise BackendUnavailable(f"LOCAL_AI_EMBED_MODEL_PATH não existe: {path}")
            return str(path), True
        if not self.settings.allow_model_download:
            raise BackendUnavailable(
                "Granite 97M não está instalado localmente; configure "
                "LOCAL_AI_EMBED_MODEL_PATH. Download automático permanece desativado"
            )
        return self.settings.preferred_embedding_model, False

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            if importlib.util.find_spec("sentence_transformers") is None:
                raise BackendUnavailable(
                    "Dependência opcional sentence-transformers ausente; use requirements-granite.txt"
                )
            if self.settings.embedding_backend != "pytorch_fp32":
                raise BackendUnavailable(
                    "Backend de embedding não autorizado em produção: "
                    f"{self.settings.embedding_backend!r}. Use pytorch_fp32"
                )
            source, source_is_local = self._source()
            try:
                import torch  # type: ignore
                from sentence_transformers import SentenceTransformer  # type: ignore

                torch.set_num_threads(self.settings.cpu_threads)
                try:
                    torch.set_num_interop_threads(1)
                except RuntimeError:
                    pass
                kwargs: dict[str, Any] = {"device": "cpu"}
                # O backend e a precisão são explícitos para impedir que a
                # presença residual de OpenVINO/ONNX altere o experimento.
                kwargs["backend"] = "torch"
                if source_is_local or not self.settings.allow_model_download:
                    kwargs["local_files_only"] = True
                self._model = SentenceTransformer(source, **kwargs)
                self._model.to(dtype=torch.float32)
                self._model.eval()
                floating_dtypes = {
                    parameter.dtype
                    for parameter in self._model.parameters()
                    if parameter.is_floating_point()
                }
                if floating_dtypes != {torch.float32}:
                    rendered = ", ".join(sorted(str(item) for item in floating_dtypes))
                    raise BackendUnavailable(
                        "Granite não permaneceu integralmente em FP32: " + rendered
                    )
                if source_is_local:
                    self.model_tree_sha256 = self._directory_sha256(Path(source))
            except BackendUnavailable:
                raise
            except Exception as exc:  # erro de runtime do backend deve ser explícito
                raise BackendUnavailable(f"Falha ao carregar Granite 97M: {exc}") from exc
            return self._model

    def encode(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        try:
            import gc
            import torch  # type: ignore

            torch.set_num_threads(2)
            with torch.inference_mode():
                vectors = model.encode(
                    texts,
                    batch_size=min(4, len(texts)),
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
            result = [[float(item) for item in vector.tolist()] for vector in vectors]
            del vectors
            gc.collect()
        except Exception as exc:
            raise BackendUnavailable(f"Falha na inferência Granite 97M: {exc}") from exc
        if result:
            self.dimension = len(result[0])
        return result


class EmbeddingProvider:
    """Seleciona Granite ou fallback de desenvolvimento sem troca silenciosa."""

    def __init__(self, settings: Settings, idf: dict[str, float]) -> None:
        self.settings = settings
        self.preferred = _GraniteEmbeddingBackend(settings)
        self.cache = BoundedLRUCache(settings.cache_entries, settings.cache_bytes)
        self._idf = idf
        self._selected: Any | None = None
        self._metadata: BackendMetadata | None = None
        self._selection_lock = threading.Lock()

    def _select(self) -> tuple[Any, BackendMetadata]:
        if self._selected is not None and self._metadata is not None:
            return self._selected, self._metadata
        with self._selection_lock:
            if self._selected is not None and self._metadata is not None:
                return self._selected, self._metadata
            try:
                # Apenas resolve/carrega aqui, na primeira inferência.
                self.preferred._load()
                backend: Any = self.preferred
                metadata = BackendMetadata(
                    backend="granite_embedding_pytorch_fp32",
                    model=self.settings.preferred_embedding_model,
                    fallback_used=False,
                    fallback_reason=None,
                    development_only=False,
                    scientific_eligible=True,
                    dimension=self.preferred.dimension,
                    model_revision=self.settings.embedding_model_revision,
                    model_tree_sha256=self.preferred.model_tree_sha256,
                    runtime_backend="pytorch_fp32",
                    precision="fp32",
                )
            except BackendUnavailable as exc:
                fallback_allowed = self.settings.development and self.settings.dev_fallback in {
                    "tfidf",
                    "hash",
                }
                if not fallback_allowed:
                    raise BackendUnavailable(str(exc)) from exc
                backend = _DevelopmentEmbeddingBackend(self.settings.dev_fallback, self._idf)
                metadata = BackendMetadata(
                    backend=f"development_{self.settings.dev_fallback}",
                    model=f"deterministic-{self.settings.dev_fallback}-384",
                    fallback_used=True,
                    fallback_reason=str(exc),
                    development_only=True,
                    scientific_eligible=False,
                    dimension=backend.dimension,
                    model_revision=None,
                    model_tree_sha256=None,
                    runtime_backend="deterministic_python",
                    precision="float64",
                )
            self._selected = backend
            self._metadata = metadata
            return backend, metadata

    def encode(self, texts: list[str]) -> tuple[list[list[float]], BackendMetadata]:
        if not texts:
            raise ValueError("Lista de textos vazia")
        sanitized = [str(text)[: self.settings.max_text_chars] for text in texts]
        backend, metadata = self._select()
        vectors: list[list[float] | None] = [None] * len(sanitized)
        missing_texts: list[str] = []
        missing_indexes: list[int] = []
        prefix = f"{metadata.backend}:{metadata.model}:"
        for index, text in enumerate(sanitized):
            cached = self.cache.get(prefix + stable_hash(text))
            if cached is None:
                missing_texts.append(text)
                missing_indexes.append(index)
            else:
                vectors[index] = cached
        if missing_texts:
            # Deduplicação pode produzir 1 + max_candidates textos, quantidade
            # maior que o micro-lote configurado. Fragmentar aqui preserva a
            # ordem, limita o pico de memória e evita rejeitar candidatos.
            encoded: list[list[float]] = []
            for offset in range(0, len(missing_texts), self.settings.max_embed_batch):
                encoded.extend(
                    backend.encode(
                        missing_texts[offset : offset + self.settings.max_embed_batch]
                    )
                )
            if len(encoded) != len(missing_texts):
                raise BackendUnavailable(
                    "Backend retornou quantidade incorreta de embeddings no micro-batching"
                )
            for index, text, vector in zip(missing_indexes, missing_texts, encoded):
                vectors[index] = vector
                self.cache.put(prefix + stable_hash(text), vector)
        complete = [vector for vector in vectors if vector is not None]
        if len(complete) != len(sanitized):
            raise BackendUnavailable("Backend retornou quantidade incorreta de embeddings")
        if complete and len(complete[0]) != metadata.dimension:
            metadata = BackendMetadata(
                backend=metadata.backend,
                model=metadata.model,
                fallback_used=metadata.fallback_used,
                fallback_reason=metadata.fallback_reason,
                development_only=metadata.development_only,
                scientific_eligible=metadata.scientific_eligible,
                dimension=len(complete[0]),
                model_revision=metadata.model_revision,
                model_tree_sha256=metadata.model_tree_sha256,
                runtime_backend=metadata.runtime_backend,
                precision=metadata.precision,
            )
            self._metadata = metadata
        return complete, metadata

    def status(self) -> dict[str, Any]:
        if self._metadata is not None:
            return {"ready": True, **self._metadata.as_dict()}
        path_ready = bool(
            self.settings.embedding_model_path
            and Path(self.settings.embedding_model_path).expanduser().exists()
        )
        dependency_ready = importlib.util.find_spec("sentence_transformers") is not None
        runtime_backend_ready = self.settings.embedding_backend == "pytorch_fp32"
        granite_configured = runtime_backend_ready and (
            (path_ready and dependency_ready) or self.settings.allow_model_download
        )
        fallback_configured = self.settings.development and self.settings.dev_fallback in {
            "tfidf",
            "hash",
        }
        return {
            "ready": granite_configured or fallback_configured,
            "selected": None,
            "preferred": "granite_embedding_pytorch_fp32",
            "runtime_backend": self.settings.embedding_backend,
            "precision": "fp32",
            "runtime_backend_supported": runtime_backend_ready,
            "model": self.settings.preferred_embedding_model,
            "local_model_path_configured": path_ready,
            "dependency_installed": dependency_ready,
            "automatic_download_allowed": self.settings.allow_model_download,
            "development_fallback": self.settings.dev_fallback if fallback_configured else "off",
            "scientific_eligible": bool(granite_configured),
            "configuration_error": None
            if runtime_backend_ready
            else "LOCAL_AI_EMBED_BACKEND deve ser pytorch_fp32",
        }
