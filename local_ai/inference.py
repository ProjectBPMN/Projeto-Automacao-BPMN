from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from .artifacts import ArtifactError, ArtifactStore, LoadedArtifact
from .backends import BackendMetadata, BackendUnavailable, EmbeddingProvider
from .config import Settings
from .contracts import (
    CLASS_LABELS,
    rounded_probabilities,
    validate_classification_v9,
    validate_dedup_v9,
)
from .extraction import (
    OptionalGraniteExtractor,
    classification_operational_information_sufficient,
    classification_pre_model_path,
    obra_automatic_evidence,
    classification_structured_values,
    deterministic_extract,
)
from .hybrid import HybridBundleRuntime, HybridRuntimeError
from .text import (
    cosine,
    normalize_text,
    parse_datetime,
    sanitize_untrusted_text,
    tfidf_cosine,
    ticket_narrative_text,
)

SERVICE_VERSION = "0.8.0"


@dataclass(frozen=True, slots=True)
class InferenceResult:
    result: dict[str, Any]
    metadata: dict[str, Any]


def _sigmoid(value: float) -> float:
    if value >= 0:
        exponential = math.exp(-min(value, 60.0))
        return 1.0 / (1.0 + exponential)
    exponential = math.exp(max(value, -60.0))
    return exponential / (1.0 + exponential)


def _softmax(logits: dict[str, float], temperature: float) -> dict[str, float]:
    safe_temperature = max(0.05, float(temperature))
    maximum = max(logits.values())
    values = {
        label: math.exp(max(-60.0, min(60.0, (value - maximum) / safe_temperature)))
        for label, value in logits.items()
    }
    total = sum(values.values())
    return {label: value / total for label, value in values.items()}


def _manual_probabilities(base: dict[str, float] | None = None, strength: float = 0.72) -> dict[str, float]:
    source = base or {label: 1.0 / len(CLASS_LABELS) for label in CLASS_LABELS}
    manual = max(strength, source.get("TRIAGEM_MANUAL", 0.0))
    remainder = max(0.0, 1.0 - manual)
    others = [label for label in CLASS_LABELS if label != "TRIAGEM_MANUAL"]
    other_total = sum(max(0.0, source.get(label, 0.0)) for label in others)
    if other_total <= 0:
        values = {label: remainder / len(others) for label in others}
    else:
        values = {
            label: remainder * max(0.0, source.get(label, 0.0)) / other_total for label in others
        }
    values["TRIAGEM_MANUAL"] = manual
    return rounded_probabilities(values, CLASS_LABELS)


class LocalAIService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.artifact_error: str | None = None
        self.artifacts: ArtifactStore | None = None
        try:
            self.artifacts = ArtifactStore(
                self.settings.artifact_dir, self.settings.hybrid_manifest_path
            )
        except ArtifactError as exc:
            # Serviço continua vivo para health/extract e devolve TRIAGEM_MANUAL
            # nos endpoints decisórios. Nunca usa coeficientes implícitos.
            self.artifact_error = str(exc)
        idf: dict[str, float] = {"__default__": 1.0}
        if self.artifacts is not None:
            for task in ("deduplication", "classification"):
                artifact_idf = self.artifacts.get(task).content.get("tfidf", {}).get("idf", {})
                idf.update({str(key): float(value) for key, value in artifact_idf.items()})
        self.embedding = EmbeddingProvider(self.settings, idf)
        self.extractor = OptionalGraniteExtractor(self.settings)
        self.hybrid_runtime: HybridBundleRuntime | None = None
        self.hybrid_runtime_error: str | None = None
        if self.artifacts is not None and self.artifacts.hybrid is not None:
            try:
                self.hybrid_runtime = HybridBundleRuntime(self.artifacts.hybrid)
            except HybridRuntimeError as exc:
                self.hybrid_runtime_error = str(exc)

    def _artifact(self, task: str) -> LoadedArtifact | None:
        if self.artifacts is not None and self.artifacts.hybrid_declared and self.hybrid_runtime is None:
            return None
        return self.artifacts.get(task) if self.artifacts is not None else None

    def _candidate_backend_ready(
        self, backend: BackendMetadata | dict[str, Any] | None
    ) -> bool:
        """Valida a proveniência exata exigida pelo candidato PyTorch FP32."""
        if backend is None:
            return False
        raw = backend.as_dict() if isinstance(backend, BackendMetadata) else backend
        tree_hash = str(raw.get("model_tree_sha256") or "").lower()
        valid_tree_hash = len(tree_hash) == 64 and all(
            character in "0123456789abcdef" for character in tree_hash
        )
        if not tree_hash:
            valid_tree_hash = True
        return bool(
            raw.get("backend") == "granite_embedding_pytorch_fp32"
            and raw.get("model") == self.settings.preferred_embedding_model
            and raw.get("runtime_backend") == "pytorch_fp32"
            and str(raw.get("precision") or "").lower() == "fp32"
            and raw.get("dimension") == 384
            and raw.get("model_revision") == self.settings.embedding_model_revision
            and valid_tree_hash
            and raw.get("fallback_used") is False
            and raw.get("development_only") is False
            and raw.get("scientific_eligible") is True
        )

    def health(self) -> dict[str, Any]:
        backend = self.embedding.status()
        artifacts_summary = (
            self.artifacts.summary()
            if self.artifacts is not None
            else {
                "scientifically_ready": False,
                "candidate_evaluation_eligible": False,
                "error": self.artifact_error,
                "artifacts": {},
            }
        )
        using_hybrid = self.hybrid_runtime is not None
        decision_ready = bool(
            using_hybrid
            or (
                self.artifacts is not None
                and not self.artifacts.hybrid_declared
                and backend.get("ready")
            )
        )
        scientific_ready = bool(
            decision_ready
            and artifacts_summary.get("scientifically_ready")
            and backend.get("scientific_eligible")
            and self.settings.mode == "production"
        )
        candidate_evaluation_eligible = bool(
            decision_ready
            and artifacts_summary.get("candidate_evaluation_eligible")
            and self._candidate_backend_ready(backend)
            and self.settings.mode == "production"
        )
        return {
            "status": "ok" if decision_ready else "degraded",
            "alive": True,
            "decision_ready": decision_ready,
            "scientific_ready": scientific_ready,
            "candidate_evaluation_eligible": candidate_evaluation_eligible,
            "pipeline_evaluation_eligible": candidate_evaluation_eligible,
            "service_version": SERVICE_VERSION,
            "mode": self.settings.mode,
            "limits": {
                "cpu_threads": self.settings.cpu_threads,
                "max_concurrent_requests": self.settings.max_concurrent_requests,
                "max_body_bytes": self.settings.max_body_bytes,
                "max_text_chars": self.settings.max_text_chars,
                "max_embed_batch": self.settings.max_embed_batch,
                "max_candidates": self.settings.max_candidates,
            },
            "embedding": backend,
            "artifacts": artifacts_summary,
            "decision_runtime": {
                "kind": "hybrid_joblib" if using_hybrid else "json_calibrated_linear",
                "hybrid_error": self.hybrid_runtime_error
                or (self.artifacts.hybrid_error if self.artifacts is not None else None),
            },
            "extractor": {
                "enabled": self.settings.extractor_enabled,
                "lazy": True,
                "required": False,
                "model": self.settings.extractor_model,
                "url_configured": bool(self.settings.extractor_url),
                "timeout_seconds": self.settings.extractor_timeout_seconds,
                "circuit_breaker_cooldown_seconds": self.settings.extractor_cooldown_seconds,
            },
            "cache": self.embedding.cache.stats(),
        }

    def embed(self, payload: dict[str, Any]) -> InferenceResult:
        started = time.perf_counter()
        value = payload.get("input", payload.get("texts", payload.get("text")))
        if isinstance(value, str):
            texts = [value]
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            texts = value
        else:
            raise ValueError("Use input como string ou lista de strings")
        if not texts:
            raise ValueError("input não pode ser vazio")
        if len(texts) > self.settings.max_embed_batch:
            raise ValueError(
                f"input excede o limite público de {self.settings.max_embed_batch} textos"
            )
        vectors, backend = self.embedding.encode(texts)
        metadata = self._metadata(
            endpoint="embed",
            decision_path="embedding_only",
            started=started,
            artifact=None,
            backend=backend,
            extractor=None,
            gates=[],
        )
        result = {
            "object": "list",
            "model": backend.model,
            "dimension": backend.dimension,
            "data": [
                {"object": "embedding", "index": index, "embedding": vector}
                for index, vector in enumerate(vectors)
            ],
            "backend": backend.as_dict(),
        }
        return InferenceResult(result=result, metadata=metadata)

    def extract(self, payload: dict[str, Any]) -> InferenceResult:
        started = time.perf_counter()
        ticket = self._ticket_from_payload(payload)
        deterministic = deterministic_extract(ticket, self.settings.max_text_chars)
        requested = bool(payload.get("use_optional_model", False))
        extracted, extractor_metadata = self.extractor.refine(
            ticket, deterministic, requested=requested
        )
        metadata = self._metadata(
            endpoint="extract",
            decision_path=(
                "optional_extractor"
                if extractor_metadata.optional_model_used
                else "deterministic_extraction"
            ),
            started=started,
            artifact=None,
            backend=None,
            extractor=extractor_metadata.as_dict(),
            gates=self._gate_names(extracted),
        )
        return InferenceResult(result=extracted, metadata=metadata)

    def classify(self, payload: dict[str, Any]) -> InferenceResult:
        started = time.perf_counter()
        ticket = self._ticket_from_payload(payload)
        extracted, extractor_metadata = self.extractor.refine(
            ticket,
            deterministic_extract(ticket, self.settings.max_text_chars),
            requested=bool(payload.get("use_optional_model", False)),
        )
        gates = self._gate_names(extracted)
        if extracted.get("conflito_categoria_ativo"):
            gates.append("category_narrative_conflict_ignored")
        artifact = self._artifact("classification")
        if artifact is None:
            result = self._manual_classification(
                "Artefato versionado de classificação ausente ou inválido; decisão automática bloqueada."
            )
            metadata = self._metadata(
                endpoint="classify",
                decision_path="blocked_artifact_unavailable",
                started=started,
                artifact=None,
                backend=None,
                extractor=extractor_metadata.as_dict(),
                gates=[*gates, "artifact_unavailable"],
            )
            validate_classification_v9(result)
            return InferenceResult(result, metadata)

        deterministic_path = classification_pre_model_path(extracted)
        operational_information_sufficient = (
            classification_operational_information_sufficient(extracted)
        )
        if not operational_information_sufficient:
            gates.append("operational_information_insufficient")
        operational_gate = (
            "deterministic_unserviceable_location"
            if not extracted.get("localizacao_atendivel_deterministica")
            else None
        )
        if operational_gate:
            gates.append(operational_gate)
        deterministic_features = {
            "policy_source": "docs/DocumentaçãoInicialProjeto.txt:40-44",
            "narrative_asset": extracted.get(
                "ativo_narrativa_deterministico"
            ),
            "category_suggested_asset": extracted.get(
                "ativo_sugerido_categoria"
            ),
            "category_narrative_conflict_ignored": bool(
                extracted.get("conflito_categoria_ativo")
            ),
            "serviceable_location": bool(
                extracted.get("localizacao_atendivel_deterministica")
            ),
            "exact_location": bool(extracted.get("localizacao_especifica")),
            "unique_named_location": bool(
                extracted.get("localizacao_unica_explicita")
            ),
            "structured_location_valid": bool(
                extracted.get("localizacao_estruturada_valida")
            ),
            "structured_location_generic": bool(
                extracted.get("localizacao_estruturada_generica")
            ),
            "structured_location_placeholder": bool(
                extracted.get("localizacao_estruturada_placeholder")
            ),
            "structured_narrative_location_conflict": bool(
                extracted.get("conflito_localizacao_estruturada_narrativa")
            ),
            "contextual_locations": list(
                extracted.get("localizacoes_contextuais") or []
            ),
            "deduplication_location_sufficient": bool(
                extracted.get("localizacao_suficiente_deduplicacao")
            ),
            "operational_information_sufficient": (
                operational_information_sufficient
            ),
            "operational_gate": operational_gate,
            "probabilistic_model_output": False,
            "probability_semantics": (
                "deterministic_gate_or_policy_not_model_probability"
            ),
        }
        if deterministic_path == "deterministic_insufficient_information":
            result = self._manual_classification(
                "Informação insuficiente para decidir escopo ou executor sem inventar dados."
            )
            metadata = self._metadata(
                endpoint="classify",
                decision_path=deterministic_path,
                started=started,
                artifact=artifact,
                backend=None,
                extractor=extractor_metadata.as_dict(),
                gates=[*gates, "insufficient_information"],
                features=deterministic_features,
            )
            validate_classification_v9(result)
            return InferenceResult(result, metadata)
        if deterministic_path == "deterministic_contradiction":
            result = self._manual_classification(
                "O relato contém informações contraditórias e requer validação pelo fiscal."
            )
            metadata = self._metadata(
                endpoint="classify",
                decision_path=deterministic_path,
                started=started,
                artifact=artifact,
                backend=None,
                extractor=extractor_metadata.as_dict(),
                gates=[*gates, "contradiction"],
                features=deterministic_features,
            )
            validate_classification_v9(result)
            return InferenceResult(result, metadata)
        if deterministic_path == "deterministic_out_of_scope":
            result = self._manual_classification(
                "Demanda de software ou sistema fora do escopo de manutenção física."
            )
            metadata = self._metadata(
                endpoint="classify",
                decision_path=deterministic_path,
                started=started,
                artifact=artifact,
                backend=None,
                extractor=extractor_metadata.as_dict(),
                gates=[*gates, "out_of_scope"],
                features=deterministic_features,
            )
            validate_classification_v9(result)
            return InferenceResult(result, metadata)

        if deterministic_path == "deterministic_specialized_asset":
            result = self._specialized_policy_classification(extracted)
            metadata = self._metadata(
                endpoint="classify",
                decision_path=deterministic_path,
                started=started,
                artifact=artifact,
                backend=None,
                extractor=extractor_metadata.as_dict(),
                gates=[*gates, "strict_specialized_asset_policy"],
                features={
                    **deterministic_features,
                    "policy_class": "SOB_DEMANDA",
                    "policy_rule": "strict_specialized_asset_whitelist",
                    "probability_semantics": (
                        "deterministic_policy_one_hot_not_model_probability"
                    ),
                },
            )
            validate_classification_v9(result)
            return InferenceResult(result, metadata)

        if self.hybrid_runtime is not None:
            raw_text = ticket_narrative_text(
                ticket, self.settings.max_text_chars
            )
            text = sanitize_untrusted_text(raw_text)
            if text != raw_text:
                gates.append("model_input_sanitized")
            backend: BackendMetadata | None = None
            try:
                embedding_vector = None
                if self.hybrid_runtime.requires_embedding:
                    vectors, backend = self.embedding.encode([text])
                    self.hybrid_runtime.validate_embedding_backend(
                        dimension=backend.dimension,
                        model=backend.model,
                        model_revision=backend.model_revision,
                        model_tree_sha256=backend.model_tree_sha256,
                    )
                    embedding_vector = vectors[0]
                prediction = self.hybrid_runtime.classify(
                    text,
                    embedding_vector,
                    classification_structured_values(extracted),
                )
            except HybridRuntimeError as exc:
                result = self._manual_classification(
                    "Bundle híbrido incompatível durante a inferência; decisão automática bloqueada."
                )
                metadata = self._metadata(
                    endpoint="classify",
                    decision_path="blocked_hybrid_runtime_error",
                    started=started,
                    artifact=artifact,
                    backend=backend,
                    extractor=extractor_metadata.as_dict(),
                    gates=[*gates, "hybrid_runtime_error"],
                    features={"runtime_error": str(exc)},
                )
                validate_classification_v9(result)
                return InferenceResult(result, metadata)
            original_probabilities = rounded_probabilities(
                prediction["probabilities"], CLASS_LABELS
            )
            semantic_class = str(prediction["semantic_class"])
            obra_evidence = obra_automatic_evidence(extracted)
            obra_safety_abstention = bool(
                semantic_class == "OBRA" and not obra_evidence["sufficient"]
            )
            operational_abstention = bool(
                prediction["abstained"] or obra_safety_abstention
            )
            if obra_safety_abstention:
                gates.append("obra_safety_evidence_insufficient")
            if operational_abstention:
                gates.append("operational_abstention")
                probabilities = _manual_probabilities(original_probabilities, strength=0.66)
                result = self._classification_contract(
                    "TRIAGEM_MANUAL",
                    probabilities["TRIAGEM_MANUAL"],
                    probabilities,
                    extracted,
                )
            else:
                result = self._classification_contract(
                    semantic_class,
                    original_probabilities[semantic_class],
                    original_probabilities,
                    extracted,
                )
            validate_classification_v9(result)
            metadata = self._metadata(
                endpoint="classify",
                decision_path=(
                    "hybrid_model_abstention"
                    if operational_abstention
                    else "hybrid_model"
                ),
                started=started,
                artifact=artifact,
                backend=backend,
                extractor=extractor_metadata.as_dict(),
                gates=gates,
                features={
                    **deterministic_features,
                    "runtime": "hybrid_joblib",
                    "probabilistic_model_output": True,
                    "probability_semantics": "calibrated_model_probability",
                    "semantic_class_prediction": semantic_class,
                    "semantic_probabilities": original_probabilities,
                    "operational_abstention": operational_abstention,
                    "obra_safety_abstention": obra_safety_abstention,
                    "obra_automatic_evidence": obra_evidence,
                    "abstention_is_not_triagem_manual": True,
                    "decision_threshold": prediction["threshold"],
                },
            )
            return InferenceResult(result, metadata)

        raw_text = ticket_narrative_text(ticket, self.settings.max_text_chars)
        text = sanitize_untrusted_text(raw_text)
        if text != raw_text:
            gates.append("model_input_sanitized")
        model = artifact.content
        prototypes = model.get("prototypes", {})
        prototype_texts = [str(prototypes.get(label, "")) for label in CLASS_LABELS]
        vectors, backend = self.embedding.encode([text, *prototype_texts])
        input_vector = vectors[0]
        semantic = {
            label: cosine(input_vector, vectors[index + 1])
            for index, label in enumerate(CLASS_LABELS)
        }
        normalized = normalize_text(text)
        logits: dict[str, float] = {}
        for label in CLASS_LABELS:
            coefficient = model.get("coefficients", {}).get(label, {})
            logit = float(coefficient.get("intercept", 0.0))
            logit += float(coefficient.get("embedding_similarity", 0.0)) * semantic[label]
            for term, weight in coefficient.get("tfidf_terms", {}).items():
                normalized_term = normalize_text(term)
                if normalized_term and normalized_term in normalized:
                    occurrences = max(1, normalized.count(normalized_term))
                    idf = float(model.get("tfidf", {}).get("idf", {}).get(normalized_term, 1.0))
                    logit += float(weight) * (1.0 + math.log(occurrences)) * idf
            logits[label] = logit
        calibration = model.get("calibration", {})
        probabilities = _softmax(logits, float(calibration.get("temperature", 1.0)))
        probabilities = rounded_probabilities(probabilities, CLASS_LABELS)
        winner = max(CLASS_LABELS, key=lambda label: probabilities[label])
        confidence = probabilities[winner]
        if confidence < self.settings.confidence_minimum:
            gates.append("below_confidence_threshold")
            probabilities = _manual_probabilities(probabilities, strength=0.66)
            winner = "TRIAGEM_MANUAL"
            confidence = probabilities[winner]
        result = self._classification_contract(winner, confidence, probabilities, extracted)
        validate_classification_v9(result)
        metadata = self._metadata(
            endpoint="classify",
            decision_path="legacy_json_model",
            started=started,
            artifact=artifact,
            backend=backend,
            extractor=extractor_metadata.as_dict(),
            gates=gates,
            features={
                **deterministic_features,
                "semantic_similarity": semantic,
                "probabilistic_model_output": True,
                "probability_semantics": "legacy_model_probability",
            },
        )
        return InferenceResult(result, metadata)

    def deduplicate(self, payload: dict[str, Any]) -> InferenceResult:
        started = time.perf_counter()
        current = payload.get("chamado_atual")
        history = payload.get("historico", [])
        if not isinstance(current, dict):
            raise ValueError("chamado_atual deve ser um objeto")
        if not isinstance(history, list) or not all(isinstance(item, dict) for item in history):
            raise ValueError("historico deve ser uma lista de objetos")
        if len(history) > self.settings.max_candidates:
            raise ValueError(f"historico excede o limite de {self.settings.max_candidates} candidatos")
        artifact = self._artifact("deduplication")
        current_extraction = deterministic_extract(current, self.settings.max_text_chars)
        gates = self._gate_names(current_extraction)
        if artifact is None:
            result = self._blocked_dedup(
                "Artefato versionado de deduplicação ausente ou inválido; revisão humana obrigatória."
            )
            metadata = self._metadata(
                endpoint="deduplicate",
                decision_path="blocked_artifact_unavailable",
                started=started,
                artifact=None,
                backend=None,
                extractor=None,
                gates=[*gates, "artifact_unavailable"],
            )
            validate_dedup_v9(result)
            return InferenceResult(result, metadata)
        current_id = current.get("id")
        candidates = [item for item in history if str(item.get("id")) != str(current_id)]
        if not candidates:
            result = self._negative_dedup(0.01, "Não existem candidatos históricos distintos para comparação.")
            metadata = self._metadata(
                endpoint="deduplicate",
                decision_path="deterministic_empty_history",
                started=started,
                artifact=artifact,
                backend=None,
                extractor=None,
                gates=[*gates, "empty_history"],
            )
            validate_dedup_v9(result)
            return InferenceResult(result, metadata)

        if self.hybrid_runtime is not None:
            return self._deduplicate_with_hybrid(
                current=current,
                candidates=candidates,
                artifact=artifact,
                current_extraction=current_extraction,
                started=started,
                gates=gates,
            )

        model = artifact.content
        raw_current_text = ticket_narrative_text(
            current, self.settings.max_text_chars
        )
        current_text = sanitize_untrusted_text(raw_current_text)
        raw_candidate_texts = [
            ticket_narrative_text(candidate, self.settings.max_text_chars)
            for candidate in candidates
        ]
        candidate_texts = [
            sanitize_untrusted_text(value) for value in raw_candidate_texts
        ]
        if current_text != raw_current_text:
            gates.append("model_input_sanitized")
        if any(
            sanitized != raw
            for sanitized, raw in zip(candidate_texts, raw_candidate_texts)
        ):
            gates.append("candidate_model_input_sanitized")
        vectors, backend = self.embedding.encode([current_text, *candidate_texts])
        best: dict[str, Any] | None = None
        for index, (candidate, candidate_text) in enumerate(zip(candidates, candidate_texts)):
            candidate_extraction = deterministic_extract(candidate, self.settings.max_text_chars)
            features = self._dedup_features(
                current,
                candidate,
                current_text,
                candidate_text,
                current_extraction,
                candidate_extraction,
                cosine(vectors[0], vectors[index + 1]),
                model.get("tfidf", {}).get("idf", {}),
            )
            raw_logit = float(model.get("coefficients", {}).get("intercept", 0.0))
            weights = model.get("coefficients", {}).get("features", {})
            raw_logit += sum(float(weights.get(name, 0.0)) * value for name, value in features.items())
            calibration = model.get("calibration", {})
            probability = _sigmoid(
                float(calibration.get("slope", 1.0)) * raw_logit
                + float(calibration.get("intercept", 0.0))
            )
            hard_blocks: list[str] = []
            if features["missing_location"]:
                probability = min(probability, 0.35)
                hard_blocks.append("localizacao_insuficiente")
            if features["location_conflict"]:
                probability = min(probability, 0.05)
                hard_blocks.append("localizacao_divergente")
            if features["asset_conflict"]:
                probability = min(probability, 0.20)
                hard_blocks.append("elemento_divergente")
            if features["symptom_conflict"]:
                probability = min(probability, 0.35)
                hard_blocks.append("sintoma_divergente")
            if features["insufficient_issue"]:
                probability = min(probability, 0.35)
                hard_blocks.append("problema_insuficiente")
            if self._int_or_none(candidate.get("id")) is None:
                probability = min(probability, 0.49)
                hard_blocks.append("referencia_sem_id_valido")
            scored = {
                "candidate": candidate,
                "probability": probability,
                "features": features,
                "hard_blocks": hard_blocks,
            }
            if best is None or probability > best["probability"]:
                best = scored
        assert best is not None
        probability = max(0.0, min(1.0, float(best["probability"])))
        threshold = float(model.get("decision_threshold", self.settings.confidence_minimum))
        duplicated = probability >= threshold and not best["hard_blocks"]
        probabilities = rounded_probabilities(
            {"duplicado": probability, "nao_duplicado": 1.0 - probability},
            ("duplicado", "nao_duplicado"),
        )
        confidence = probabilities["duplicado"] if duplicated else probabilities["nao_duplicado"]
        matches = self._match_descriptions(best["features"])
        if duplicated:
            justification = "Mesmo elemento, sintoma e localização apresentam evidência conjunta acima do limiar calibrado."
            reference = self._int_or_none(best["candidate"].get("id"))
        else:
            blocks = ", ".join(best["hard_blocks"])
            justification = (
                "Nenhum candidato atingiu os critérios conjuntos de elemento, sintoma e localização."
                + (f" Bloqueios determinísticos: {blocks}." if blocks else "")
            )
            reference = None
        result = {
            "eh_duplicado": duplicated,
            "chamado_referencia_id": reference,
            "justificativa": justification,
            "caracteristicas_match": matches,
            "confianca": confidence,
            "probabilidades": probabilities,
        }
        validate_dedup_v9(result)
        metadata = self._metadata(
            endpoint="deduplicate",
            decision_path="legacy_json_model",
            started=started,
            artifact=artifact,
            backend=backend,
            extractor=None,
            gates=[*gates, *best["hard_blocks"]],
            features={
                "best_candidate_id": best["candidate"].get("id"),
                "best_candidate_features": best["features"],
                "decision_threshold": threshold,
            },
        )
        return InferenceResult(result, metadata)

    def _deduplicate_with_hybrid(
        self,
        *,
        current: dict[str, Any],
        candidates: list[dict[str, Any]],
        artifact: LoadedArtifact,
        current_extraction: dict[str, Any],
        started: float,
        gates: list[str],
    ) -> InferenceResult:
        assert self.hybrid_runtime is not None
        raw_current_text = ticket_narrative_text(
            current, self.settings.max_text_chars
        )
        current_text = sanitize_untrusted_text(raw_current_text)
        raw_candidate_texts = [
            ticket_narrative_text(candidate, self.settings.max_text_chars)
            for candidate in candidates
        ]
        candidate_texts = [
            sanitize_untrusted_text(value) for value in raw_candidate_texts
        ]
        if current_text != raw_current_text:
            gates.append("model_input_sanitized")
        if any(
            sanitized != raw
            for sanitized, raw in zip(candidate_texts, raw_candidate_texts)
        ):
            gates.append("candidate_model_input_sanitized")
        backend: BackendMetadata | None = None
        embedding_vectors: list[list[float]] | None = None
        best: dict[str, Any] | None = None
        scored_candidates: list[dict[str, Any]] = []
        try:
            if self.hybrid_runtime.requires_embedding:
                embedding_vectors, backend = self.embedding.encode(
                    [current_text, *candidate_texts]
                )
                self.hybrid_runtime.validate_embedding_backend(
                    dimension=backend.dimension,
                    model=backend.model,
                    model_revision=backend.model_revision,
                    model_tree_sha256=backend.model_tree_sha256,
                )
            for index, (candidate, candidate_text) in enumerate(
                zip(candidates, candidate_texts)
            ):
                prediction = self.hybrid_runtime.deduplicate(
                    current,
                    candidate,
                    current_text,
                    candidate_text,
                    embedding_vectors[0] if embedding_vectors is not None else None,
                    embedding_vectors[index + 1]
                    if embedding_vectors is not None
                    else None,
                )
                probability = float(prediction["duplicate_probability"])
                candidate_extraction = deterministic_extract(
                    candidate, self.settings.max_text_chars
                )
                current_locations, current_location_level = (
                    self._dedup_location_evidence(current_extraction)
                )
                candidate_locations, candidate_location_level = (
                    self._dedup_location_evidence(candidate_extraction)
                )
                location_match = self._sets_equivalent(
                    current_locations, candidate_locations
                )
                current_structured = self._qualified_structured_location(
                    current_extraction
                )
                candidate_structured = self._qualified_structured_location(
                    candidate_extraction
                )
                structured_location_match = bool(
                    current_structured
                    and candidate_structured
                    and self._sets_equivalent(
                        {current_structured}, {candidate_structured}
                    )
                )
                exact_levels = {"exact_room_or_asset"}
                location_detail_asymmetry = bool(
                    not location_match
                    and structured_location_match
                    and (
                        (current_location_level in exact_levels)
                        != (candidate_location_level in exact_levels)
                    )
                )
                hard_blocks: list[str] = []
                if not current_locations or not candidate_locations:
                    probability = min(probability, 0.35)
                    hard_blocks.append("localizacao_insuficiente")
                elif location_detail_asymmetry:
                    probability = min(probability, 0.49)
                    hard_blocks.append("localizacao_precisao_assimetrica")
                elif not location_match:
                    probability = min(probability, 0.05)
                    hard_blocks.append("localizacao_divergente")
                current_asset = current_extraction.get("ativo")
                candidate_asset = candidate_extraction.get("ativo")
                if current_asset and candidate_asset and current_asset != candidate_asset:
                    probability = min(probability, 0.20)
                    hard_blocks.append("elemento_divergente")
                current_symptom = current_extraction.get("sintoma")
                candidate_symptom = candidate_extraction.get("sintoma")
                if current_symptom and candidate_symptom and current_symptom != candidate_symptom:
                    probability = min(probability, 0.35)
                    hard_blocks.append("conflito_sintoma")
                if not current_asset or not candidate_asset:
                    probability = min(probability, 0.35)
                    hard_blocks.append("problema_insuficiente")
                if self._int_or_none(candidate.get("id")) is None:
                    probability = min(probability, 0.49)
                    hard_blocks.append("referencia_sem_id_valido")
                scored = {
                    "candidate": candidate,
                    "probability": probability,
                    "threshold": float(prediction["threshold"]),
                    "negative_threshold": float(prediction["negative_threshold"]),
                    "features": prediction["features"],
                    "hard_blocks": hard_blocks,
                    "location_evidence": {
                        "current": current_location_level,
                        "candidate": candidate_location_level,
                    },
                }
                scored_candidates.append(scored)
                if best is None or probability > best["probability"]:
                    best = scored
        except HybridRuntimeError as exc:
            result = self._blocked_dedup(
                "Bundle híbrido incompatível durante a inferência; revisão humana obrigatória."
            )
            metadata = self._metadata(
                endpoint="deduplicate",
                decision_path="blocked_hybrid_runtime_error",
                started=started,
                artifact=artifact,
                backend=backend,
                extractor=None,
                gates=[*gates, "hybrid_runtime_error"],
                features={"runtime_error": str(exc)},
            )
            validate_dedup_v9(result)
            return InferenceResult(result, metadata)
        assert best is not None
        ranked_candidates = sorted(
            scored_candidates,
            key=lambda item: (-float(item["probability"]), self._int_or_none(item["candidate"].get("id")) or 0),
        )
        best = ranked_candidates[0]
        runner_up = ranked_candidates[1] if len(ranked_candidates) > 1 else None
        probability = max(0.0, min(1.0, float(best["probability"])))
        runner_up_probability = (
            max(0.0, min(1.0, float(runner_up["probability"])))
            if runner_up is not None
            else 0.0
        )
        candidate_probability_margin = probability - runner_up_probability
        reference_ambiguity = bool(
            runner_up is not None
            and probability >= best["threshold"]
            and runner_up_probability >= best["threshold"]
            and candidate_probability_margin
            < self.hybrid_runtime.dedup_reference_margin_threshold
        )
        if reference_ambiguity:
            best["hard_blocks"].append("referencia_duplicada_ambigua")
        review_blocks = {
            "localizacao_insuficiente",
            "localizacao_precisao_assimetrica",
            "problema_insuficiente",
            "referencia_sem_id_valido",
            "referencia_duplicada_ambigua",
        }.intersection(best["hard_blocks"])
        threshold_abstention = (
            best["negative_threshold"]
            < probability
            < best["threshold"]
        )
        if review_blocks or threshold_abstention:
            reason_parts = []
            if review_blocks:
                reason_parts.append(
                    "informação insuficiente ou referência inválida: "
                    + ", ".join(sorted(review_blocks))
                )
            if threshold_abstention:
                reason_parts.append(
                    "probabilidade situada entre os limiares calibrados de decisão"
                )
            result = self._blocked_dedup(
                "Revisão humana obrigatória; " + "; ".join(reason_parts) + "."
            )
            validate_dedup_v9(result)
            metadata = self._metadata(
                endpoint="deduplicate",
                decision_path="hybrid_model_abstention",
                started=started,
                artifact=artifact,
                backend=backend,
                extractor=None,
                gates=[
                    *gates,
                    *best["hard_blocks"],
                    "operational_abstention",
                ],
                features={
                    "runtime": "hybrid_joblib",
                    "best_candidate_id": best["candidate"].get("id"),
                    "best_candidate_features": best["features"],
                    "runner_up_candidate_id": (
                        runner_up["candidate"].get("id") if runner_up else None
                    ),
                    "runner_up_duplicate_probability": runner_up_probability,
                    "candidate_probability_margin": candidate_probability_margin,
                    "reference_margin_threshold": (
                        self.hybrid_runtime.dedup_reference_margin_threshold
                    ),
                    "location_evidence": best["location_evidence"],
                    "duplicate_probability_raw": probability,
                    "duplicate_probability_before_abstention": probability,
                    "positive_decision_threshold": best["threshold"],
                    "negative_decision_threshold": best["negative_threshold"],
                    "abstention_is_not_negative": True,
                    "probabilistic_model_output": True,
                    "probability_semantics": "calibrated_model_probability",
                },
            )
            return InferenceResult(result, metadata)
        duplicated = probability >= best["threshold"] and not best["hard_blocks"]
        probabilities = rounded_probabilities(
            {"duplicado": probability, "nao_duplicado": 1.0 - probability},
            ("duplicado", "nao_duplicado"),
        )
        if duplicated:
            result = {
                "eh_duplicado": True,
                "chamado_referencia_id": self._int_or_none(best["candidate"].get("id")),
                "justificativa": "Bundle calibrado identificou evidência conjunta acima do limiar aprovado.",
                "caracteristicas_match": [
                    description
                    for flag, description in (
                        (best["features"].get("same_location"), "mesma localização explícita"),
                        (best["features"].get("same_category"), "mesma categoria"),
                        (best["features"].get("same_requester"), "mesmo solicitante"),
                    )
                    if flag
                ],
                "confianca": probabilities["duplicado"],
                "probabilidades": probabilities,
            }
        else:
            result = {
                "eh_duplicado": False,
                "chamado_referencia_id": None,
                "justificativa": "Bundle calibrado não atingiu os critérios conjuntos de duplicidade."
                + (
                    " Bloqueios determinísticos: "
                    + ", ".join(best["hard_blocks"])
                    + "."
                    if best["hard_blocks"]
                    else ""
                ),
                "caracteristicas_match": [],
                "confianca": probabilities["nao_duplicado"],
                "probabilidades": probabilities,
            }
        validate_dedup_v9(result)
        metadata = self._metadata(
            endpoint="deduplicate",
            decision_path="hybrid_model",
            started=started,
            artifact=artifact,
            backend=backend,
            extractor=None,
            gates=[*gates, *best["hard_blocks"]],
            features={
                "runtime": "hybrid_joblib",
                "best_candidate_id": best["candidate"].get("id"),
                "best_candidate_features": best["features"],
                "runner_up_candidate_id": (
                    runner_up["candidate"].get("id") if runner_up else None
                ),
                "runner_up_duplicate_probability": runner_up_probability,
                "candidate_probability_margin": candidate_probability_margin,
                "reference_margin_threshold": (
                    self.hybrid_runtime.dedup_reference_margin_threshold
                ),
                "location_evidence": best["location_evidence"],
                "duplicate_probability_raw": probability,
                "positive_decision_threshold": best["threshold"],
                "decision_threshold": best["threshold"],
                "negative_decision_threshold": best["negative_threshold"],
                "probabilistic_model_output": True,
                "probability_semantics": "calibrated_model_probability",
            },
        )
        return InferenceResult(result, metadata)

    def _dedup_features(
        self,
        current: dict[str, Any],
        candidate: dict[str, Any],
        current_text: str,
        candidate_text: str,
        current_extraction: dict[str, Any],
        candidate_extraction: dict[str, Any],
        semantic_similarity: float,
        idf: dict[str, float],
    ) -> dict[str, float]:
        current_locations, _ = self._dedup_location_evidence(current_extraction)
        candidate_locations, _ = self._dedup_location_evidence(candidate_extraction)
        location_match = self._sets_equivalent(current_locations, candidate_locations)
        missing_location = not current_locations or not candidate_locations
        location_conflict = bool(current_locations and candidate_locations and not location_match)
        current_asset = current_extraction.get("ativo")
        candidate_asset = candidate_extraction.get("ativo")
        asset_match = bool(current_asset and current_asset == candidate_asset)
        asset_conflict = bool(current_asset and candidate_asset and current_asset != candidate_asset)
        current_symptom = current_extraction.get("sintoma")
        candidate_symptom = candidate_extraction.get("sintoma")
        symptom_match = bool(current_symptom and current_symptom == candidate_symptom)
        symptom_conflict = bool(current_symptom and candidate_symptom and current_symptom != candidate_symptom)
        current_date = parse_datetime(
            current.get("data_abertura") or current.get("date") or current.get("data_ultima_mudanca")
        )
        candidate_date = parse_datetime(
            candidate.get("data_abertura") or candidate.get("date") or candidate.get("data_ultima_mudanca")
        )
        temporal_close = bool(
            current_date
            and candidate_date
            and abs(current_date - candidate_date) <= timedelta(days=30)
        )
        normalized_current = normalize_text(current_text)
        explicit_reference = any(
            phrase in normalized_current
            for phrase in ("chamado anterior", "como falei", "reabrindo", "problema nao resolvido")
        )
        return {
            "tfidf_similarity": tfidf_cosine(current_text, candidate_text, idf),
            "embedding_similarity": max(-1.0, min(1.0, semantic_similarity)),
            "location_match": float(location_match),
            "asset_match": float(asset_match),
            "symptom_match": float(symptom_match),
            "temporal_close": float(temporal_close),
            "explicit_reference": float(explicit_reference),
            "location_conflict": float(location_conflict),
            "asset_conflict": float(asset_conflict),
            "symptom_conflict": float(symptom_conflict),
            "missing_location": float(missing_location),
            "insufficient_issue": float(not current_asset or not candidate_asset or not current_symptom or not candidate_symptom),
        }

    @staticmethod
    def _qualified_structured_location(extracted: dict[str, Any]) -> str:
        structured = normalize_text(extracted.get("localizacao_informada") or "")
        if (
            not structured
            or extracted.get("localizacao_estruturada_valida") is not True
            or extracted.get("localizacao_estruturada_placeholder") is True
        ):
            return ""
        generic_location_tokens = {
            "bloco",
            "campus",
            "departamento",
            "de",
            "do",
            "da",
            "dos",
            "das",
            "ensino",
            "local",
            "predio",
            "sala",
            "salas",
            "setor",
            "unidade",
        }
        informative_tokens = {
            token
            for token in structured.split()
            if len(token) >= 3 and token not in generic_location_tokens
        }
        if (
            extracted.get("localizacao_estruturada_generica") is True
            and not informative_tokens
        ):
            return ""
        return structured

    @staticmethod
    def _dedup_location_evidence(
        extracted: dict[str, Any],
    ) -> tuple[set[str], str]:
        exact = {
            normalize_text(value)
            for value in extracted.get("localizacoes", [])
            if normalize_text(value)
        }
        if exact:
            return exact, "exact_room_or_asset"
        unique_named = {
            normalize_text(value)
            for value in extracted.get("localizacoes_unicas_explicitas", [])
            if normalize_text(value)
        }
        if unique_named:
            return unique_named, "unique_named_location"
        structured = LocalAIService._qualified_structured_location(extracted)
        if structured:
            return {structured}, "structured_glpi_named_location"
        return set(), "insufficient_or_generic"

    @staticmethod
    def _sets_equivalent(left: set[str], right: set[str]) -> bool:
        if not left or not right:
            return False
        for a in left:
            a_tokens = set(a.split())
            for b in right:
                b_tokens = set(b.split())
                if a == b or (a_tokens and b_tokens and (a_tokens <= b_tokens or b_tokens <= a_tokens)):
                    return True
        return False

    @staticmethod
    def _match_descriptions(features: dict[str, float]) -> list[str]:
        mapping = (
            ("location_match", "mesma localização explícita"),
            ("asset_match", "mesmo elemento ou equipamento"),
            ("symptom_match", "mesmo sintoma"),
            ("temporal_close", "intervalo temporal de até 30 dias"),
            ("explicit_reference", "referência explícita a chamado anterior"),
        )
        result = [description for feature, description in mapping if features.get(feature, 0) > 0]
        if features.get("tfidf_similarity", 0) >= 0.65:
            result.append("alta correspondência lexical")
        if features.get("embedding_similarity", 0) >= 0.75:
            result.append("alta correspondência semântica")
        return result[:10]

    @staticmethod
    def _gate_names(extracted: dict[str, Any]) -> list[str]:
        gates: list[str] = []
        if extracted.get("possivel_prompt_injection"):
            gates.append("prompt_injection_ignored")
        if extracted.get("contradicoes"):
            gates.append("contradiction_detected")
        if extracted.get("campos_ausentes"):
            gates.append("missing_fields:" + ",".join(extracted["campos_ausentes"]))
        return gates

    @staticmethod
    def _ticket_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
        nested = payload.get("chamado")
        if isinstance(nested, dict):
            return nested
        reserved = {"use_optional_model", "include_metadata"}
        ticket = {key: value for key, value in payload.items() if key not in reserved}
        if not ticket:
            raise ValueError("Chamado ausente")
        return ticket

    @staticmethod
    def _int_or_none(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            parsed = int(value)
            return parsed if parsed >= 0 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _manual_classification(reason: str) -> dict[str, Any]:
        probabilities = rounded_probabilities(
            {"OBRA": 0.05, "DEMO": 0.05, "SOB_DEMANDA": 0.05, "TRIAGEM_MANUAL": 0.85},
            CLASS_LABELS,
        )
        return {
            "tipo": "TRIAGEM_MANUAL",
            "executor": "FISCAL",
            "categoria": "triagem manual",
            "justificativa": reason,
            "mensagem_solicitante": "O chamado será validado pelo fiscal antes de qualquer encaminhamento.",
            "confianca": probabilities["TRIAGEM_MANUAL"],
            "probabilidades": probabilities,
        }

    @staticmethod
    def _specialized_policy_classification(
        extracted: dict[str, Any],
    ) -> dict[str, Any]:
        probabilities = rounded_probabilities(
            {
                "OBRA": 0.0,
                "DEMO": 0.0,
                "SOB_DEMANDA": 1.0,
                "TRIAGEM_MANUAL": 0.0,
            },
            CLASS_LABELS,
        )
        asset = str(
            extracted.get("ativo_narrativa_deterministico")
            or extracted.get("ativo")
            or "equipamento especializado"
        ).replace("_", " ")
        return {
            "tipo": "MANUTENCAO",
            "executor": "SOB_DEMANDA",
            "categoria": asset,
            "justificativa": (
                "Regra documental determinística: o ativo explicitamente descrito "
                "exige empresa ou assistência técnica especializada."
            ),
            "mensagem_solicitante": (
                "O chamado foi encaminhado para atendimento sob demanda e permanece "
                "sujeito às confirmações humanas do fluxo."
            ),
            "confianca": 1.0,
            "probabilidades": probabilities,
        }

    @staticmethod
    def _classification_contract(
        winner: str,
        confidence: float,
        probabilities: dict[str, float],
        extracted: dict[str, Any],
    ) -> dict[str, Any]:
        pairs = {
            "OBRA": ("OBRA", "DDI_DG"),
            "DEMO": ("MANUTENCAO", "DEMO"),
            "SOB_DEMANDA": ("MANUTENCAO", "SOB_DEMANDA"),
            "TRIAGEM_MANUAL": ("TRIAGEM_MANUAL", "FISCAL"),
        }
        type_name, executor = pairs[winner]
        asset = str(extracted.get("ativo") or extracted.get("escopo") or "infraestrutura").replace("_", " ")
        if winner == "TRIAGEM_MANUAL":
            justification = "A regressão calibrada não ultrapassou o limiar mínimo de confiança."
            message = "O chamado será validado pelo fiscal antes do encaminhamento."
        else:
            justification = f"Predição conjunta TF-IDF, embedding e regressão calibrada: {winner}."
            message = f"O chamado foi encaminhado para {executor} e permanece sujeito às confirmações do fluxo."
        return {
            "tipo": type_name,
            "executor": executor,
            "categoria": asset,
            "justificativa": justification,
            "mensagem_solicitante": message,
            "confianca": round(float(confidence), 6),
            "probabilidades": probabilities,
        }

    @staticmethod
    def _blocked_dedup(reason: str) -> dict[str, Any]:
        return {
            "eh_duplicado": False,
            "chamado_referencia_id": None,
            "justificativa": reason,
            "caracteristicas_match": [],
            "confianca": 0.5,
            "probabilidades": {"duplicado": 0.5, "nao_duplicado": 0.5},
        }

    @staticmethod
    def _negative_dedup(probability_duplicate: float, reason: str) -> dict[str, Any]:
        probabilities = rounded_probabilities(
            {"duplicado": probability_duplicate, "nao_duplicado": 1.0 - probability_duplicate},
            ("duplicado", "nao_duplicado"),
        )
        return {
            "eh_duplicado": False,
            "chamado_referencia_id": None,
            "justificativa": reason,
            "caracteristicas_match": [],
            "confianca": probabilities["nao_duplicado"],
            "probabilidades": probabilities,
        }

    def _metadata(
        self,
        *,
        endpoint: str,
        decision_path: str,
        started: float,
        artifact: LoadedArtifact | None,
        backend: BackendMetadata | None,
        extractor: dict[str, Any] | None,
        gates: list[str],
        features: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        hybrid = self.artifacts.hybrid if self.artifacts is not None else None
        if hybrid is not None:
            thresholds = hybrid.content.get("thresholds", {})
            training_metadata = hybrid.content.get("training_metadata", {})
            manifest = hybrid.manifest
            artifact_ready = bool(
                thresholds.get("approved") is True
                and training_metadata.get("scientifically_validated") is True
                and training_metadata.get("test_data_used") is False
                and training_metadata.get("primary33_used") is False
            )
            candidate_artifact_ready = bool(
                self.artifacts is not None
                and self.artifacts.candidate_evaluation_eligible
                and self.hybrid_runtime is not None
            )
            bundle_entry = manifest.get("bundle", {})
            if not isinstance(bundle_entry, dict):
                bundle_entry = {}
            artifact_info = {
                "version": hybrid.version,
                "scientific_status": "trained_calibrated_validated"
                if artifact_ready
                else (
                    "candidate_frozen_pending_confirmatory"
                    if candidate_artifact_ready
                    else "not_approved"
                ),
                "file": hybrid.path.name,
                "manifest": hybrid.manifest_path.name,
                "bundle_sha256": str(
                    manifest.get("sha256")
                    or manifest.get("bundle_sha256")
                    or manifest.get("checksum_sha256")
                    or bundle_entry.get("sha256")
                    or ""
                ).lower(),
                "manifest_payload_sha256": str(
                    manifest.get("manifest_payload_sha256") or ""
                ).lower(),
                "format": "joblib_hybrid_bundle",
                "candidate_frozen": manifest.get("candidate_frozen") is True,
                "evaluation_eligible": manifest.get("evaluation_eligible") is True,
                "candidate_bundle_eligible": candidate_artifact_ready,
                "scientifically_validated": manifest.get("scientifically_validated") is True,
                "scientific_result": manifest.get("scientific_result") is True,
                "test_data_used": manifest.get("test_data_used"),
                "primary33_used": manifest.get("primary33_used"),
            }
        else:
            candidate_artifact_ready = False
            artifact_ready = artifact is not None and artifact.scientific_status == "trained_calibrated_validated"
            artifact_info = (
                {
                    "version": artifact.version,
                    "scientific_status": artifact.scientific_status,
                    "file": artifact.path.name,
                    "format": "json_calibrated_linear_v1",
                }
                if artifact is not None
                else {"version": None, "scientific_status": "unavailable", "error": self.artifact_error or self.hybrid_runtime_error or (self.artifacts.hybrid_error if self.artifacts is not None else None)}
            )
        if endpoint == "embed":
            artifact_ready = True
        backend_ready = backend is None or backend.scientific_eligible
        extractor_ready = extractor is None or extractor.get("scientific_eligible", False)
        candidate_runtime_used = bool(
            endpoint in {"classify", "deduplicate"}
            and isinstance(features, dict)
            and features.get("runtime") == "hybrid_joblib"
        )
        candidate_evaluation_eligible = bool(
            candidate_artifact_ready
            and candidate_runtime_used
            and self._candidate_backend_ready(backend)
            and extractor_ready
            and self.settings.mode == "production"
        )
        deterministic_pipeline_paths = {
            "deterministic_insufficient_information",
            "deterministic_contradiction",
            "deterministic_out_of_scope",
            "deterministic_specialized_asset",
            "deterministic_empty_history",
        }
        hybrid_pipeline_paths = {"hybrid_model", "hybrid_model_abstention"}
        pipeline_evaluation_eligible = bool(
            candidate_artifact_ready
            and extractor_ready
            and self.settings.mode == "production"
            and (
                decision_path in deterministic_pipeline_paths
                or (
                    decision_path in hybrid_pipeline_paths
                    and candidate_evaluation_eligible
                )
            )
        )
        return {
            "trace_id": str(uuid.uuid4()),
            "endpoint": endpoint,
            "decision_path": decision_path,
            "service_version": SERVICE_VERSION,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "artifact": artifact_info,
            "embedding": backend.as_dict() if backend is not None else None,
            "extractor": extractor,
            "gates": list(dict.fromkeys(gates)),
            "features": features,
            "operational_information_sufficient": (
                features.get("operational_information_sufficient")
                if isinstance(features, dict)
                and "operational_information_sufficient" in features
                else None
            ),
            "operational_gate": (
                features.get("operational_gate")
                if isinstance(features, dict)
                else None
            ),
            "probabilistic_model_output": (
                features.get("probabilistic_model_output")
                if isinstance(features, dict)
                else None
            ),
            "probability_semantics": (
                features.get("probability_semantics")
                if isinstance(features, dict)
                else None
            ),
            "fallback_used": bool(backend and backend.fallback_used),
            "candidate_evaluation_eligible": candidate_evaluation_eligible,
            "pipeline_evaluation_eligible": pipeline_evaluation_eligible,
            "scientific_eligible": bool(
                artifact_ready
                and backend_ready
                and extractor_ready
                and self.settings.mode == "production"
            ),
        }
