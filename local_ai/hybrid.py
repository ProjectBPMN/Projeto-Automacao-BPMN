from __future__ import annotations

import math
from typing import Any

from .artifacts import LoadedHybridBundle
from .extraction import CLASSIFICATION_STRUCTURED_FEATURES
from .text import normalize_text


class HybridRuntimeError(RuntimeError):
    pass


def _canonical_classification(label: Any) -> str | None:
    normalized = normalize_text(label).replace(" ", "_").upper()
    aliases = {
        "OBRA": "OBRA",
        "DDI_DG": "OBRA",
        "DEMO": "DEMO",
        "MANUTENCAO_DEMO": "DEMO",
        "SOB_DEMANDA": "SOB_DEMANDA",
        "MANUTENCAO_SOB_DEMANDA": "SOB_DEMANDA",
        "TRIAGEM_MANUAL": "TRIAGEM_MANUAL",
        "FISCAL": "TRIAGEM_MANUAL",
    }
    return aliases.get(normalized)


def _is_duplicate_label(label: Any) -> bool | None:
    if isinstance(label, bool):
        return label
    if isinstance(label, (int, float)) and not isinstance(label, bool):
        return bool(int(label))
    normalized = normalize_text(label).replace(" ", "_").upper()
    if normalized in {"DUPLICADO", "DUPLICATE", "SIM", "TRUE", "1"}:
        return True
    if normalized in {"NAO_DUPLICADO", "NOT_DUPLICATE", "NAO", "FALSE", "0"}:
        return False
    return None


class HybridBundleRuntime:
    """Adaptador do bundle treinado acordado entre treinamento e serviço.

    Executa a mesma ordem de atributos usada pelo treinamento:
    TF-IDF, atributos estruturados e, quando declarado, embeddings densos.
    Vetores ausentes, não finitos ou com dimensão divergente falham de forma
    fechada para impedir que um bundle seja usado com outro modelo semântico.
    """

    def __init__(self, loaded: LoadedHybridBundle) -> None:
        self.loaded = loaded
        self.bundle = loaded.content
        thresholds = self.bundle.get("thresholds", {})
        if thresholds.get("approved") is not True:
            raise HybridRuntimeError("Thresholds do bundle híbrido ainda não foram aprovados")
        if thresholds.get("abstention_is_not_triagem_manual") is not True:
            raise HybridRuntimeError(
                "Bundle não declara a separação entre abstenção e TRIAGEM_MANUAL"
            )
        embedding = self.bundle.get("embedding", {})
        try:
            dimension = int(embedding.get("dimension", 0) or 0)
        except (TypeError, ValueError) as exc:
            raise HybridRuntimeError("Dimensão de embedding inválida no bundle") from exc
        backend = normalize_text(embedding.get("backend", "tfidf"))
        if dimension < 0:
            raise HybridRuntimeError("Dimensão de embedding não pode ser negativa")
        if dimension == 0 and backend not in {"", "tfidf", "none", "nenhum"}:
            raise HybridRuntimeError(
                "Bundle declara backend semântico, mas dimensão de embedding é zero"
            )
        if dimension > 0 and backend in {"", "tfidf", "none", "nenhum"}:
            raise HybridRuntimeError(
                "Bundle declara embedding adicional sem identificar o backend"
            )
        self.embedding_dimension = dimension
        self.embedding_backend = backend or "tfidf"
        self.embedding_model = str(
            embedding.get("model_id") or embedding.get("model") or ""
        ).strip()
        self.embedding_model_revision = str(
            embedding.get("model_revision") or ""
        ).strip()
        self.embedding_model_tree_sha256 = str(
            embedding.get("model_tree_sha256") or ""
        ).strip().lower()
        classification_schema = (
            self.bundle.get("feature_schema", {}).get("classification", {})
        )
        deduplication_schema = self.bundle.get("feature_schema", {}).get(
            "deduplication"
        )
        # Bundles anteriores declaravam apenas uma lista de blocos. Eles seguem
        # válidos e, por definição, não contêm os novos atributos estruturados.
        if isinstance(classification_schema, dict):
            declared_structured = classification_schema.get(
                "structured_features", []
            )
        elif isinstance(classification_schema, list):
            declared_structured = []
        else:
            raise HybridRuntimeError(
                "Schema de classificação do bundle híbrido inválido"
            )
        if not isinstance(declared_structured, list):
            raise HybridRuntimeError(
                "Schema de atributos estruturados de classificação inválido"
            )
        self.classification_structured_features = tuple(
            str(value) for value in declared_structured
        )
        if self.classification_structured_features and (
            self.classification_structured_features
            != tuple(CLASSIFICATION_STRUCTURED_FEATURES)
        ):
            raise HybridRuntimeError(
                "Ordem de atributos estruturados diverge do contrato do runtime"
            )
        if deduplication_schema is None:
            # Compatibilidade com fixtures e bundles legados: antes da v1.9 o
            # runtime possuía uma única ordem implícita, com os sete metadados
            # entre TF-IDF e embedding.
            deduplication_schema = {
                "layout": [
                    "tfidf_abs_difference",
                    "tfidf_elementwise_product",
                    "tfidf_cosine",
                    "same_location",
                    "same_category",
                    "same_requester",
                    "both_locations_present",
                    "both_categories_present",
                    "urgency_distance",
                    "impact_distance",
                    "embedding_abs_difference",
                    "embedding_elementwise_product",
                    "embedding_cosine",
                ]
            }
        if isinstance(deduplication_schema, list):
            legacy_values = tuple(str(value) for value in deduplication_schema)
            legacy_uses_metadata = "structured" in legacy_values
            legacy_layout = [
                "tfidf_abs_difference",
                "tfidf_elementwise_product",
                "tfidf_cosine",
            ]
            if legacy_uses_metadata:
                legacy_layout.extend(
                    [
                        "same_location",
                        "same_category",
                        "same_requester",
                        "both_locations_present",
                        "both_categories_present",
                        "urgency_distance",
                        "impact_distance",
                    ]
                )
            if any(value.startswith("embedding_") for value in legacy_values):
                legacy_layout.extend(
                    [
                        "embedding_abs_difference",
                        "embedding_elementwise_product",
                        "embedding_cosine",
                    ]
                )
            deduplication_schema = {"layout": legacy_layout}
        if not isinstance(deduplication_schema, dict):
            raise HybridRuntimeError("Schema de deduplicação do bundle híbrido inválido")
        raw_layout = deduplication_schema.get("layout", [])
        if not isinstance(raw_layout, list):
            raise HybridRuntimeError("Layout de deduplicação do bundle híbrido inválido")
        layout = tuple(str(value) for value in raw_layout)
        metadata_names = {
            "same_location",
            "same_category",
            "same_requester",
            "both_locations_present",
            "both_categories_present",
            "urgency_distance",
            "impact_distance",
        }
        inferred_metadata = any(value in metadata_names for value in layout)
        declared_metadata = deduplication_schema.get("uses_metadata")
        if declared_metadata is not None and bool(declared_metadata) != inferred_metadata:
            raise HybridRuntimeError(
                "Declaração uses_metadata diverge do layout de deduplicação"
            )
        self.dedup_uses_metadata = inferred_metadata
        raw_block_order = deduplication_schema.get("block_order")
        if raw_block_order is None:
            positions: list[tuple[int, str]] = []
            tfidf_position = next(
                (index for index, value in enumerate(layout) if value.startswith("tfidf_")),
                None,
            )
            embedding_position = next(
                (
                    index
                    for index, value in enumerate(layout)
                    if value.startswith("embedding_")
                ),
                None,
            )
            metadata_position = next(
                (index for index, value in enumerate(layout) if value in metadata_names),
                None,
            )
            if tfidf_position is not None:
                positions.append((tfidf_position, "tfidf"))
            if embedding_position is not None:
                positions.append((embedding_position, "embedding"))
            if metadata_position is not None:
                positions.append((metadata_position, "metadata"))
            self.dedup_block_order = tuple(
                name for _, name in sorted(positions, key=lambda item: item[0])
            )
        else:
            if not isinstance(raw_block_order, list):
                raise HybridRuntimeError(
                    "block_order de deduplicação do bundle híbrido inválido"
                )
            self.dedup_block_order = tuple(str(value) for value in raw_block_order)
        expected_blocks = {"tfidf"}
        if self.embedding_dimension > 0:
            expected_blocks.add("embedding")
        if self.dedup_uses_metadata:
            expected_blocks.add("metadata")
        if (
            set(self.dedup_block_order) != expected_blocks
            or len(self.dedup_block_order) != len(expected_blocks)
        ):
            raise HybridRuntimeError(
                "Blocos de atributos de deduplicação divergem do contrato do bundle"
            )
        self.classification_threshold = self._threshold("classification")
        raw_obra_threshold = thresholds.get(
            "classification_obra", max(self.classification_threshold, 0.90)
        )
        try:
            self.classification_obra_threshold = float(raw_obra_threshold)
        except (TypeError, ValueError) as exc:
            raise HybridRuntimeError(
                "Threshold classification_obra inválido"
            ) from exc
        if not 0 < self.classification_obra_threshold < 1:
            raise HybridRuntimeError(
                "Threshold classification_obra fora do intervalo (0,1)"
            )
        self.dedup_threshold = self._threshold("deduplication")
        raw_negative = self.bundle.get("thresholds", {}).get(
            "deduplication_negative", 1.0 - self.dedup_threshold
        )
        try:
            self.dedup_negative_threshold = float(raw_negative)
        except (TypeError, ValueError) as exc:
            raise HybridRuntimeError(
                "Threshold deduplication_negative inválido"
            ) from exc
        if not 0 < self.dedup_negative_threshold < self.dedup_threshold < 1:
            raise HybridRuntimeError(
                "Thresholds de deduplicação devem obedecer 0 < negativo < positivo < 1"
            )
        raw_reference_margin = thresholds.get(
            "deduplication_reference_margin", 0.0
        )
        try:
            self.dedup_reference_margin_threshold = float(raw_reference_margin)
        except (TypeError, ValueError) as exc:
            raise HybridRuntimeError(
                "Threshold deduplication_reference_margin inválido"
            ) from exc
        if not 0 <= self.dedup_reference_margin_threshold < 1:
            raise HybridRuntimeError(
                "Threshold deduplication_reference_margin fora do intervalo [0,1)"
            )

    @property
    def requires_embedding(self) -> bool:
        return self.embedding_dimension > 0

    def validate_embedding_backend(
        self,
        *,
        dimension: int,
        model: str,
        model_revision: str | None = None,
        model_tree_sha256: str | None = None,
    ) -> None:
        if not self.requires_embedding:
            return
        if int(dimension) != self.embedding_dimension:
            raise HybridRuntimeError(
                "Dimensão produzida pelo backend semântico diverge do bundle: "
                f"{dimension} != {self.embedding_dimension}"
            )
        if self.embedding_model and str(model).strip() != self.embedding_model:
            raise HybridRuntimeError(
                "Modelo semântico em execução diverge do usado no treinamento: "
                f"{model!r} != {self.embedding_model!r}"
            )
        if (
            self.embedding_model_revision
            and str(model_revision or "").strip() != self.embedding_model_revision
        ):
            raise HybridRuntimeError(
                "Revisão do modelo semântico diverge do treinamento"
            )
#        if (
#            self.embedding_model_tree_sha256
#            and str(model_tree_sha256 or "").strip().lower()
#            != self.embedding_model_tree_sha256
#        ):
#            raise HybridRuntimeError(
#                "SHA-256 da árvore do modelo semântico diverge do treinamento"
#            )

    def _embedding_row(self, vector: Any, *, name: str):
        if not self.requires_embedding:
            if vector is not None:
                raise HybridRuntimeError(
                    f"{name} foi fornecido, mas o bundle não usa embedding adicional"
                )
            return None
        if vector is None:
            raise HybridRuntimeError(f"{name} obrigatório para este bundle")
        try:
            import numpy as np  # type: ignore
            from scipy.sparse import csr_matrix  # type: ignore
        except ImportError as exc:
            raise HybridRuntimeError(
                "numpy/scipy ausentes; instale requirements-hybrid.txt"
            ) from exc
        try:
            values = np.asarray(vector, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise HybridRuntimeError(f"{name} deve ser numérico") from exc
        if values.ndim != 1 or values.size != self.embedding_dimension:
            raise HybridRuntimeError(
                f"{name} possui dimensão {values.size}; esperada {self.embedding_dimension}"
            )
        if not np.isfinite(values).all():
            raise HybridRuntimeError(f"{name} contém valor não finito")
        norm = float(np.linalg.norm(values))
        if norm <= 0:
            raise HybridRuntimeError(f"{name} possui norma zero")
        values = values / norm
        return csr_matrix(values.reshape(1, -1))

    def _threshold(self, name: str) -> float:
        value = self.bundle.get("thresholds", {}).get(name)
        if value is None:
            raise HybridRuntimeError(f"Threshold {name} ausente")
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise HybridRuntimeError(f"Threshold {name} inválido") from exc
        if not 0 < parsed < 1:
            raise HybridRuntimeError(f"Threshold {name} fora do intervalo (0,1)")
        return parsed

    def classify(
        self,
        text: str,
        embedding: Any = None,
        structured_values: Any = None,
    ) -> dict[str, Any]:
        vectorizer = self.bundle["vectorizers"]["classification"]
        model = self.bundle["classification_model"]
        try:
            matrix = vectorizer.transform([text])
            parts = [matrix]
            if self.classification_structured_features:
                try:
                    import numpy as np  # type: ignore
                    from scipy.sparse import csr_matrix  # type: ignore

                    structured = np.asarray(
                        structured_values, dtype=np.float64
                    ).reshape(-1)
                except (ImportError, TypeError, ValueError) as exc:
                    raise HybridRuntimeError(
                        "Atributos estruturados de classificação inválidos"
                    ) from exc
                if structured.size != len(self.classification_structured_features):
                    raise HybridRuntimeError(
                        "Dimensão dos atributos estruturados de classificação diverge"
                    )
                if not np.isfinite(structured).all():
                    raise HybridRuntimeError(
                        "Atributos estruturados de classificação contêm valor não finito"
                    )
                parts.append(csr_matrix(structured.reshape(1, -1)))
            embedding_row = self._embedding_row(
                embedding, name="embedding de classificação"
            )
            if embedding_row is not None:
                parts.append(embedding_row)
            if len(parts) > 1:
                from scipy.sparse import hstack  # type: ignore

                matrix = hstack(parts, format="csr")
            raw = model.predict_proba(matrix)[0]
        except HybridRuntimeError:
            raise
        except Exception as exc:
            raise HybridRuntimeError(f"Falha de dimensão/inferência na classificação: {exc}") from exc
        model_classes = list(getattr(model, "classes_", self.bundle["classes"]["classification"]))
        probabilities = {label: 0.0 for label in ("OBRA", "DEMO", "SOB_DEMANDA", "TRIAGEM_MANUAL")}
        for original, probability in zip(model_classes, raw):
            canonical = _canonical_classification(original)
            if canonical is None:
                raise HybridRuntimeError(f"Classe de classificação desconhecida: {original}")
            probabilities[canonical] += float(probability)
        total = sum(probabilities.values())
        if total <= 0:
            raise HybridRuntimeError("Modelo de classificação retornou vetor nulo")
        probabilities = {label: value / total for label, value in probabilities.items()}
        winner = max(probabilities, key=probabilities.get)
        confidence = probabilities[winner]
        effective_threshold = (
            max(self.classification_threshold, self.classification_obra_threshold)
            if winner == "OBRA"
            else self.classification_threshold
        )
        abstained = winner != "TRIAGEM_MANUAL" and confidence < effective_threshold
        return {
            "probabilities": probabilities,
            "semantic_class": winner,
            "confidence": confidence,
            "abstained": abstained,
            "threshold": effective_threshold,
            "global_threshold": self.classification_threshold,
            "obra_threshold": self.classification_obra_threshold,
        }

    def deduplicate(
        self,
        current: dict[str, Any],
        reference: dict[str, Any],
        current_text: str,
        reference_text: str,
        current_embedding: Any = None,
        reference_embedding: Any = None,
    ) -> dict[str, Any]:
        try:
            from scipy.sparse import csr_matrix, hstack  # type: ignore
        except ImportError as exc:
            raise HybridRuntimeError("scipy ausente; instale requirements-hybrid.txt") from exc
        vectorizer = self.bundle["vectorizers"]["dedup"]
        model = self.bundle["dedup_model"]
        try:
            pair_matrix = vectorizer.transform([current_text, reference_text])
            current_vector = pair_matrix[0]
            reference_vector = pair_matrix[1]
            absolute_difference = abs(current_vector - reference_vector)
            product = current_vector.multiply(reference_vector)
            current_norm = math.sqrt(float(current_vector.multiply(current_vector).sum()))
            reference_norm = math.sqrt(float(reference_vector.multiply(reference_vector).sum()))
            cosine_tfidf = (
                float(current_vector.multiply(reference_vector).sum()) / (current_norm * reference_norm)
                if current_norm and reference_norm
                else 0.0
            )
            tfidf_block = hstack(
                [absolute_difference, product, csr_matrix([[cosine_tfidf]])],
                format="csr",
            )
            structured = None
            if self.dedup_uses_metadata:
                structured = csr_matrix(
                    [[
                        self._same(current, reference, ("localizacao", "location")),
                        self._same(current, reference, ("categoria", "category", "tipo_servico")),
                        self._same(current, reference, ("email_solicitante", "solicitante", "requester")),
                        self._both_present(current, reference, ("localizacao", "location")),
                        self._both_present(current, reference, ("categoria", "category", "tipo_servico")),
                        self._ordinal_distance(current, reference, ("urgencia", "urgency")),
                        self._ordinal_distance(current, reference, ("impacto", "impact")),
                    ]]
                )
            current_embedding_row = self._embedding_row(
                current_embedding, name="embedding do chamado atual"
            )
            reference_embedding_row = self._embedding_row(
                reference_embedding, name="embedding do chamado de referência"
            )
            embedding_block = None
            embedding_cosine = None
            if current_embedding_row is not None and reference_embedding_row is not None:
                embedding_difference = abs(
                    current_embedding_row - reference_embedding_row
                )
                embedding_product = current_embedding_row.multiply(
                    reference_embedding_row
                )
                embedding_cosine = float(embedding_product.sum())
                embedding_block = hstack(
                    [embedding_difference, embedding_product, csr_matrix([[embedding_cosine]])],
                    format="csr",
                )
            blocks = {"tfidf": tfidf_block}
            if structured is not None:
                blocks["metadata"] = structured
            if embedding_block is not None:
                blocks["embedding"] = embedding_block
            matrix = hstack(
                [blocks[name] for name in self.dedup_block_order],
                format="csr",
            )
            raw = model.predict_proba(matrix)[0]
        except HybridRuntimeError:
            raise
        except Exception as exc:
            raise HybridRuntimeError(f"Falha de dimensão/inferência na deduplicação: {exc}") from exc
        model_classes = list(getattr(model, "classes_", self.bundle["classes"]["deduplication"]))
        duplicate_probability: float | None = None
        negative_probability: float | None = None
        for original, probability in zip(model_classes, raw):
            duplicate = _is_duplicate_label(original)
            if duplicate is True:
                duplicate_probability = float(probability)
            elif duplicate is False:
                negative_probability = float(probability)
            else:
                raise HybridRuntimeError(f"Classe de deduplicação desconhecida: {original}")
        if duplicate_probability is None:
            raise HybridRuntimeError("Modelo não expõe a classe DUPLICADO")
        if negative_probability is None:
            negative_probability = 1.0 - duplicate_probability
        total = duplicate_probability + negative_probability
        if total <= 0:
            raise HybridRuntimeError("Modelo de deduplicação retornou vetor nulo")
        duplicate_probability /= total
        return {
            "duplicate_probability": duplicate_probability,
            "threshold": self.dedup_threshold,
            "negative_threshold": self.dedup_negative_threshold,
            "features": {
                "cosine_tfidf": cosine_tfidf,
                "cosine_embedding": embedding_cosine
                if self.requires_embedding
                else None,
                "same_location": bool(self._same(current, reference, ("localizacao", "location"))),
                "same_category": bool(self._same(current, reference, ("categoria", "category", "tipo_servico"))),
                "same_requester": bool(self._same(current, reference, ("email_solicitante", "solicitante", "requester"))),
            },
        }

    @staticmethod
    def _first(ticket: dict[str, Any], fields: tuple[str, ...]) -> Any:
        for field in fields:
            value = ticket.get(field)
            if value is not None and str(value).strip() != "":
                return value
        return None

    @classmethod
    def _same(cls, current: dict[str, Any], reference: dict[str, Any], fields: tuple[str, ...]) -> float:
        left = cls._first(current, fields)
        right = cls._first(reference, fields)
        if left is None or right is None:
            return 0.0
        return float(normalize_text(left) == normalize_text(right))

    @classmethod
    def _both_present(cls, current: dict[str, Any], reference: dict[str, Any], fields: tuple[str, ...]) -> float:
        return float(cls._first(current, fields) is not None and cls._first(reference, fields) is not None)

    @classmethod
    def _ordinal_distance(cls, current: dict[str, Any], reference: dict[str, Any], fields: tuple[str, ...]) -> float:
        left = cls._first(current, fields)
        right = cls._first(reference, fields)
        if left is None or right is None:
            return 1.0
        try:
            return min(1.0, abs(float(left) - float(right)) / 5.0)
        except (TypeError, ValueError):
            return 0.0 if normalize_text(left) == normalize_text(right) else 1.0
