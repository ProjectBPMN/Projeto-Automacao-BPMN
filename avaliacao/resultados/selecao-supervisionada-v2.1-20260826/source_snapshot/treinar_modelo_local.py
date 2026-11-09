from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Any, Callable, Sequence

import joblib
import numpy as np
import scipy
from scipy import sparse
import sklearn
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.frozen import FrozenEstimator
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    log_loss,
    roc_auc_score,
)
from sklearn.model_selection import GroupShuffleSplit, StratifiedGroupKFold
from sklearn.pipeline import FeatureUnion


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from local_ai.extraction import (  # noqa: E402
    classification_operational_information_sufficient,
    classification_pre_model_path,
    deterministic_extract,
    obra_automatic_evidence,
)
from local_ai.inference import SERVICE_VERSION as LOCAL_AI_SERVICE_VERSION  # noqa: E402
from local_ai.text import (  # noqa: E402
    sanitize_untrusted_text,
    ticket_narrative_text,
)


MODEL_VERSION = "local-hybrid-v1.8.0"
BUNDLE_VERSION = "local-hybrid-bundle-v1.8.0"
PIPELINE_VERSION = "local-ai-hybrid-pipeline-v1.8.0"
GENERATION_PROFILE = "granite97m-pytorch-fp32-tfidf-logreg-calibrated-v1.8.0"
CALIBRATION_METHOD = "sigmoid"
CONFIDENCE_LEVEL = 0.95
DEDUP_FALSE_POSITIVE_COST = 1.0
OBRA_AUTOMATIC_MIN_CONFIDENCE = 0.90
DEDUP_REFERENCE_MARGIN_MIN = 0.035
CLASS_LABELS = ("OBRA", "DEMO", "SOB_DEMANDA", "TRIAGEM_MANUAL")
DEDUP_LABELS = ("NAO_DUPLICADO", "DUPLICADO")
TRAIN_SPLITS = {"TREINO", "TRAIN", "DESENVOLVIMENTO", "DEVELOPMENT", "PILOTO"}
CALIBRATION_SPLITS = {"VALIDACAO", "VALIDATION", "CALIBRACAO", "CALIBRATION"}
FORBIDDEN_SPLITS = {
    "TESTE",
    "TEST",
    "BENCHMARK",
    "CONFIRMATORIO",
    "CONFIRMATORY",
    "HOLDOUT_FINAL",
}
FORBIDDEN_SCENARIO_SETS = {"PRIMARY33", "ALL35", "STRESS2"}
PRIMARY33_IDS = {
    *(f"D{index:02d}" for index in range(1, 15)),
    *(f"C{index:02d}" for index in range(1, 20)),
}
TEXT_FIELDS = ("title", "content", "location")
GROUP_FIELDS = (
    "scenario_id",
    "narrative_core_sha256",
    "narrative_core",
    "template_family",
    "episode_id",
)
PIPELINE_SOURCE_FILES = {
    "trainer": Path(__file__).resolve(),
    "extraction": PROJECT_ROOT / "local_ai" / "extraction.py",
    "inference": PROJECT_ROOT / "local_ai" / "inference.py",
    "text": PROJECT_ROOT / "local_ai" / "text.py",
}
LEAKAGE_FIELDS = (
    "case_id",
    "episode_id",
    "narrative_core_sha256",
    "narrative_core",
    "template_family",
    "scenario_id",
    "visible_text_sha256",
)
STRUCTURED_PAIR_FEATURES = (
    "same_location",
    "same_category",
    "same_requester",
    "both_locations_present",
    "both_categories_present",
    "urgency_distance",
    "impact_distance",
)


class ScientificGuardError(ValueError):
    """Raised before fitting when scientific split integrity is violated."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def normalize_token(value: Any) -> str:
    return re.sub(r"[^A-Z0-9_]+", "_", str(value or "").strip().upper()).strip("_")


def visible_text(case: dict[str, Any]) -> str:
    aliases = (
        ("title", "titulo", "name"),
        ("content", "descricao"),
        ("location", "localizacao"),
        ("category", "categoria", "tipo_servico"),
    )
    parts: list[str] = []
    for group in aliases:
        value = next(
            (
                case.get(field)
                for field in group
                if case.get(field) is not None and str(case.get(field)).strip()
            ),
            None,
        )
        if value is not None:
            parts.append(str(value).strip())
    return " ".join(parts)


def model_text(case: dict[str, Any]) -> str:
    return sanitize_untrusted_text(ticket_narrative_text(case, 6000))


def normalized_visible_hash(case: dict[str, Any]) -> str:
    text = re.sub(r"\s+", " ", visible_text(case).casefold()).strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ScientificGuardError(
                    f"{path}:{line_number}: JSON inválido: {exc.msg}"
                ) from exc
            if not isinstance(value, dict):
                raise ScientificGuardError(
                    f"{path}:{line_number}: cada linha deve ser um objeto JSON"
                )
            cases.append(value)
    if not cases:
        raise ScientificGuardError(f"Dataset vazio: {path}")
    return cases


def _recursive_markers(value: Any, key_hint: str = "") -> set[str]:
    markers: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            key_norm = normalize_token(key)
            if key_norm in {
                "SCENARIO_SET",
                "CENARIO_SET",
                "DATASET_ROLE",
                "EXPERIMENT_SPLIT",
                "SPLIT",
            }:
                markers.add(normalize_token(item))
            markers.update(_recursive_markers(item, key_norm))
    elif isinstance(value, list):
        for item in value:
            markers.update(_recursive_markers(item, key_hint))
    elif key_hint:
        markers.add(normalize_token(value))
    return markers


def _neighbor_metadata(path: Path) -> list[tuple[Path, Any]]:
    candidates = {
        path.with_name(path.stem + "_manifest.json"),
        path.with_name(path.stem + "_manifesto.json"),
        path.parent / "freeze_manifest.json",
    }
    result: list[tuple[Path, Any]] = []
    for candidate in sorted(candidates):
        if not candidate.exists() or candidate == path:
            continue
        try:
            result.append((candidate, json.loads(candidate.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError):
            continue
    return result


def validate_source_role(
    path: Path,
    cases: Sequence[dict[str, Any]],
    *,
    role: str,
) -> dict[str, Any]:
    normalized_role = normalize_token(role)
    allowed = TRAIN_SPLITS if normalized_role == "TRAIN" else CALIBRATION_SPLITS
    observed_splits = {
        normalize_token(case.get("split")) for case in cases if case.get("split")
    }
    if not observed_splits:
        raise ScientificGuardError(
            f"{path}: split ausente; treino científico exige papel explícito"
        )
    forbidden = observed_splits & FORBIDDEN_SPLITS
    if forbidden:
        raise ScientificGuardError(
            f"{path}: uso de split de teste/benchmark em treino ou calibração bloqueado: "
            + ", ".join(sorted(forbidden))
        )
    unexpected = observed_splits - allowed
    if unexpected:
        raise ScientificGuardError(
            f"{path}: split incompatível com papel {normalized_role}: "
            + ", ".join(sorted(unexpected))
        )

    direct_markers = {
        normalize_token(case.get("scenario_set"))
        for case in cases
        if case.get("scenario_set")
    }
    metadata_files: list[str] = []
    for metadata_path, payload in _neighbor_metadata(path):
        metadata_files.append(str(metadata_path))
        direct_markers.update(_recursive_markers(payload))
    blocked_sets = direct_markers & FORBIDDEN_SCENARIO_SETS
    if blocked_sets:
        raise ScientificGuardError(
            f"{path}: conjunto reservado para avaliação não pode treinar o modelo: "
            + ", ".join(sorted(blocked_sets))
        )

    scenario_counts = Counter(normalize_token(case.get("scenario_id")) for case in cases)
    scenario_counts.pop("", None)
    looks_like_primary33 = (
        len(cases) >= 990
        and PRIMARY33_IDS.issubset(scenario_counts)
        and sum(scenario_counts[item] for item in PRIMARY33_IDS) >= 990
    )
    if looks_like_primary33:
        raise ScientificGuardError(
            f"{path}: assinatura volumétrica do primary33 detectada; o conjunto 33x30 "
            "é reservado à robustez/avaliação"
        )

    filename_marker = normalize_token(path.stem)
    if "PRIMARY33" in filename_marker or "33X30" in filename_marker:
        raise ScientificGuardError(
            f"{path}: nome identifica corpus primary33/33x30 reservado à avaliação"
        )
    return {
        "path": str(path.resolve()),
        "role": normalized_role,
        "splits": sorted(observed_splits),
        "records": len(cases),
        "sha256": sha256_file(path),
        "neighbor_metadata_checked": metadata_files,
        "test_split_detected": False,
        "reserved_scenario_set_detected": False,
    }


def group_key(case: dict[str, Any], field: str = "auto") -> str:
    if field != "auto":
        if field not in GROUP_FIELDS:
            raise ScientificGuardError(
                f"Campo de grupo inseguro {field!r}; use auto ou um de {GROUP_FIELDS}"
            )
        value = str(case.get(field, "") or "").strip()
        if not value:
            raise ScientificGuardError(
                f"{case.get('case_id', '<sem-id>')}: campo de grupo {field!r} ausente"
            )
        return f"{field}:{value}"
    for candidate in GROUP_FIELDS:
        value = str(case.get(candidate, "") or "").strip()
        if value:
            return f"{candidate}:{value}"
    raise ScientificGuardError(
        f"{case.get('case_id', '<sem-id>')}: nenhum identificador de núcleo/grupo"
    )


def _identity_tokens(cases: Sequence[dict[str, Any]]) -> dict[str, set[str]]:
    result = {field: set() for field in LEAKAGE_FIELDS}
    result["normalized_visible_text"] = set()
    for case in cases:
        for field in LEAKAGE_FIELDS:
            value = str(case.get(field, "") or "").strip()
            if value:
                result[field].add(value)
        result["normalized_visible_text"].add(normalized_visible_hash(case))
    return result


def assert_no_split_leakage(
    train: Sequence[dict[str, Any]], calibration: Sequence[dict[str, Any]]
) -> dict[str, int]:
    left = _identity_tokens(train)
    right = _identity_tokens(calibration)
    overlaps = {
        field: sorted(left[field] & right[field])
        for field in left
        if left[field] & right[field]
    }
    if overlaps:
        details = "; ".join(
            f"{field}={values[:3]}" for field, values in sorted(overlaps.items())
        )
        raise ScientificGuardError(
            "Vazamento entre treino e calibração detectado: " + details
        )
    return {field: 0 for field in left}


def _task_label_sets(cases: Sequence[dict[str, Any]]) -> tuple[set[str], set[str]]:
    classification = {
        str(case.get("expected_classification", "") or "").strip().upper()
        for case in cases
        if str(case.get("expected_classification", "") or "").strip()
    }
    dedup = {
        "DUPLICADO" if bool(case.get("expected_dedup")) else "NAO_DUPLICADO"
        for case in cases
        if is_dedup_challenge(case)
    }
    return classification, dedup


def grouped_development_split(
    cases: Sequence[dict[str, Any]],
    *,
    validation_fraction: float,
    seed: int,
    group_field: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if not 0.1 <= validation_fraction <= 0.5:
        raise ScientificGuardError("validation_fraction deve estar entre 0.1 e 0.5")
    groups = np.asarray([group_key(case, group_field) for case in cases])
    indices = np.arange(len(cases))
    all_class, all_dedup = _task_label_sets(cases)
    if len(all_class) < 2 or len(all_dedup) < 2:
        raise ScientificGuardError(
            "Pool de desenvolvimento precisa de >=2 classes de classificação e dedup"
        )

    # A rota determinística não depende do split. Pré-computá-la evita repetir
    # milhares de extrações em cada uma das até 256 tentativas do GroupShuffle.
    model_labels = np.asarray(
        [
            str(case.get("expected_classification", "") or "").strip().upper()
            for case in cases
        ],
        dtype=object,
    )
    model_eligible = np.asarray(
        [
            bool(model_labels[index])
            and classification_pre_model_path(
                deterministic_extract(case, 6000)
            )
            is None
            for index, case in enumerate(cases)
        ],
        dtype=bool,
    )

    def model_group_support(selected_indices: np.ndarray) -> dict[str, int]:
        eligible_indices = selected_indices[model_eligible[selected_indices]]
        return {
            label: len(
                set(
                    groups[
                        eligible_indices[
                            model_labels[eligible_indices] == label
                        ]
                    ].tolist()
                )
            )
            for label in CLASS_LABELS
        }

    for attempt in range(256):
        split_seed = seed + attempt
        splitter = GroupShuffleSplit(
            n_splits=1, test_size=validation_fraction, random_state=split_seed
        )
        train_indices, calibration_indices = next(splitter.split(indices, groups=groups))
        train = [cases[index] for index in train_indices]
        calibration = [cases[index] for index in calibration_indices]
        train_class, train_dedup = _task_label_sets(train)
        cal_class, cal_dedup = _task_label_sets(calibration)
        train_model_groups = model_group_support(train_indices)
        calibration_model_groups = model_group_support(calibration_indices)
        model_support_ok = bool(
            min(train_model_groups.values(), default=0) >= 5
            and min(calibration_model_groups.values(), default=0) >= 3
        )
        if (
            train_class == all_class == cal_class
            and train_dedup == all_dedup == cal_dedup
            and model_support_ok
        ):
            assert_no_split_leakage(train, calibration)
            return train, calibration, {
                "strategy": "GroupShuffleSplit",
                "group_field": group_field,
                "requested_seed": seed,
                "effective_seed": split_seed,
                "validation_fraction": validation_fraction,
                "train_groups": len({group_key(case, group_field) for case in train}),
                "calibration_groups": len(
                    {group_key(case, group_field) for case in calibration}
                ),
                "model_only_train_groups_by_class": train_model_groups,
                "model_only_calibration_groups_by_class": (
                    calibration_model_groups
                ),
                "model_only_minimum_group_support": {
                    "train": 5,
                    "calibration": 3,
                },
            }
    raise ScientificGuardError(
        "Não foi possível criar split agrupado com todas as classes em 256 tentativas"
    )


def is_dedup_challenge(case: dict[str, Any]) -> bool:
    dimension = normalize_token(case.get("dimension"))
    raw_order = case.get("order_in_episode", case.get("order_in_group", 0)) or 0
    try:
        order = int(raw_order)
    except (TypeError, ValueError) as exc:
        raise ScientificGuardError(
            f"{case.get('case_id', '<sem-id>')}: ordem do episódio inválida: {raw_order!r}"
        ) from exc
    return dimension == "DEDUPLICACAO" and order > 1 and case.get("expected_dedup") is not None


def validate_labels(cases: Sequence[dict[str, Any]], source: str) -> None:
    case_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    for index, case in enumerate(cases, start=1):
        case_id = str(case.get("case_id", "") or "").strip()
        if not case_id:
            raise ScientificGuardError(f"{source}: registro {index} sem case_id")
        if case_id in case_ids:
            duplicate_ids.add(case_id)
        case_ids.add(case_id)
        if is_dedup_challenge(case) and not isinstance(case.get("expected_dedup"), bool):
            raise ScientificGuardError(
                f"{source}: {case_id}: expected_dedup deve ser booleano, não "
                f"{type(case.get('expected_dedup')).__name__}"
            )
    if duplicate_ids:
        raise ScientificGuardError(
            f"{source}: case_id duplicado: {sorted(duplicate_ids)[:5]}"
        )
    classification, dedup = _task_label_sets(cases)
    invalid_classification = classification - set(CLASS_LABELS)
    if invalid_classification:
        raise ScientificGuardError(
            f"{source}: classes de classificação inválidas: {sorted(invalid_classification)}"
        )
    if classification != set(CLASS_LABELS):
        raise ScientificGuardError(
            f"{source}: classificação deve conter as quatro classes {CLASS_LABELS}; "
            f"observado={sorted(classification)}"
        )
    if dedup != set(DEDUP_LABELS):
        raise ScientificGuardError(
            f"{source}: deduplicação deve conter {DEDUP_LABELS}; observado={sorted(dedup)}"
        )
    # Também valida a integridade temporal e referencial dos episódios.
    dedup_pairs(cases)


def build_text_vectorizer() -> FeatureUnion:
    return FeatureUnion(
        [
            (
                "word",
                TfidfVectorizer(
                    ngram_range=(1, 2),
                    min_df=1,
                    sublinear_tf=True,
                    strip_accents="unicode",
                    dtype=np.float64,
                ),
            ),
            (
                "char",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(3, 5),
                    min_df=1,
                    sublinear_tf=True,
                    dtype=np.float64,
                ),
            ),
        ]
    )


def _mock_embedding(text: str, dimension: int) -> np.ndarray:
    vector = np.zeros(dimension, dtype=np.float64)
    for token in re.findall(r"\w+", text.casefold()):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm else vector


class GraniteEmbeddingEncoder:
    """Encoder local, versionado e reutilizado por todo o treinamento.

    O carregamento é explícito e somente local: o script de treino não baixa
    pesos automaticamente. Um cache em memória garante que a mesma narrativa
    não seja inferida repetidamente ao construir pares de deduplicação.
    """

    def __init__(
        self,
        model_path: Path,
        *,
        model_id: str,
        revision: str,
        batch_size: int = 8,
        cpu_threads: int = 4,
    ) -> None:
        resolved = model_path.expanduser().resolve()
        if not resolved.is_dir():
            raise ScientificGuardError(
                f"Diretório local do Granite Embedding ausente: {resolved}"
            )
        try:
            import torch  # type: ignore
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as exc:
            raise ScientificGuardError(
                "Granite exige sentence-transformers/torch; instale "
                "local_ai/requirements-granite.txt"
            ) from exc
        torch.set_num_threads(max(1, min(4, int(cpu_threads))))
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass
        try:
            self.model = SentenceTransformer(
                str(resolved), device="cpu", local_files_only=True
            )
        except Exception as exc:
            raise ScientificGuardError(
                f"Falha ao carregar Granite Embedding local: {exc}"
            ) from exc
        self.model_path = resolved
        self.model_id = model_id.strip()
        self.revision = revision.strip()
        self.batch_size = max(1, min(32, int(batch_size)))
        dimension_getter = getattr(self.model, "get_embedding_dimension", None)
        if not callable(dimension_getter):
            dimension_getter = getattr(
                self.model, "get_sentence_embedding_dimension", None
            )
        if not callable(dimension_getter):
            raise ScientificGuardError(
                "SentenceTransformer não expõe a dimensão do embedding"
            )
        self.dimension = int(dimension_getter() or 0)
        if self.dimension != 384:
            raise ScientificGuardError(
                f"Granite Embedding deve produzir 384 dimensões, recebeu {self.dimension}"
            )
        self._cache: dict[str, np.ndarray] = {}
        self.tree_sha256 = self._directory_sha256(resolved)

    @staticmethod
    def _directory_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        files = sorted(
            item
            for item in path.rglob("*")
            if item.is_file() and ".cache" not in item.relative_to(path).parts
        )
        if not files:
            raise ScientificGuardError("Diretório do modelo Granite está vazio")
        for item in files:
            relative = item.relative_to(path).as_posix().encode("utf-8")
            digest.update(len(relative).to_bytes(4, "big"))
            digest.update(relative)
            digest.update(bytes.fromhex(sha256_file(item)))
        return digest.hexdigest()

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        missing = list(dict.fromkeys(text for text in texts if text not in self._cache))
        if missing:
            try:
                vectors = self.model.encode(
                    missing,
                    batch_size=min(self.batch_size, len(missing)),
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
            except Exception as exc:
                raise ScientificGuardError(
                    f"Falha ao gerar embeddings Granite durante o treino: {exc}"
                ) from exc
            for text, raw in zip(missing, vectors):
                vector = np.asarray(raw, dtype=np.float64)
                if (
                    vector.ndim != 1
                    or len(vector) != self.dimension
                    or not np.isfinite(vector).all()
                ):
                    raise ScientificGuardError(
                        "Granite retornou embedding inválido ou dimensão inesperada"
                    )
                norm = float(np.linalg.norm(vector))
                if norm <= 0:
                    raise ScientificGuardError("Granite retornou embedding de norma zero")
                self._cache[text] = vector / norm
        return np.vstack([self._cache[text] for text in texts])


def embedding_matrix(
    cases: Sequence[dict[str, Any]],
    *,
    backend: str,
    field: str,
    mock_dimension: int,
    expected_dimension: int | None = None,
    encoder: GraniteEmbeddingEncoder | None = None,
) -> tuple[np.ndarray | None, int]:
    if backend == "tfidf":
        return None, 0
    if backend == "granite":
        if encoder is None:
            raise ScientificGuardError("Backend granite exige encoder local explícito")
        matrix = encoder.encode([model_text(case) for case in cases])
        dimension = int(matrix.shape[1]) if matrix.ndim == 2 else 0
        if expected_dimension is not None and dimension != expected_dimension:
            raise ScientificGuardError(
                f"Dimensão de embedding divergente: {dimension} != {expected_dimension}"
            )
        return matrix, dimension
    vectors: list[np.ndarray] = []
    for case in cases:
        if backend == "mock":
            vector = _mock_embedding(model_text(case), mock_dimension)
        elif backend == "precomputed":
            raw = case.get(field)
            if not isinstance(raw, list) or not raw:
                raise ScientificGuardError(
                    f"{case.get('case_id')}: embedding pré-computado ausente em {field!r}"
                )
            try:
                vector = np.asarray(raw, dtype=np.float64)
            except (TypeError, ValueError) as exc:
                raise ScientificGuardError(
                    f"{case.get('case_id')}: embedding não numérico"
                ) from exc
            if vector.ndim != 1 or not np.isfinite(vector).all():
                raise ScientificGuardError(
                    f"{case.get('case_id')}: embedding deve ser vetor finito 1-D"
                )
            norm = float(np.linalg.norm(vector))
            vector = vector / norm if norm else vector
        else:
            raise ScientificGuardError(f"Backend de embedding desconhecido: {backend}")
        vectors.append(vector)
    dimension = len(vectors[0])
    if any(len(vector) != dimension for vector in vectors):
        raise ScientificGuardError("Embeddings possuem dimensões diferentes")
    if expected_dimension is not None and dimension != expected_dimension:
        raise ScientificGuardError(
            f"Dimensão de embedding divergente: {dimension} != {expected_dimension}"
        )
    return np.vstack(vectors), dimension


def classification_rows(cases: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        case
        for case in cases
        if str(case.get("expected_classification", "") or "").strip()
    ]


def classification_model_rows(
    cases: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Estrato realmente encaminhado à regressão no runtime."""
    return [
        case
        for case in classification_rows(cases)
        if classification_pre_model_path(deterministic_extract(case, 6000))
        is None
    ]


def _episode_anchor_map(cases: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    episodes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        episode = str(case.get("episode_id", "") or "").strip()
        if episode:
            episodes[episode].append(case)
    anchors: dict[str, dict[str, Any]] = {}
    for episode, members in episodes.items():
        ordered = sorted(
            members,
            key=lambda case: int(
                case.get("order_in_episode", case.get("order_in_group", 0)) or 0
            ),
        )
        if ordered:
            anchors[episode] = ordered[0]
    return anchors


def dedup_pairs(
    cases: Sequence[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any], str]]:
    by_id: dict[str, dict[str, Any]] = {}
    for case in cases:
        case_id = str(case.get("case_id", "") or "").strip()
        if not case_id:
            continue
        if case_id in by_id:
            raise ScientificGuardError(f"case_id duplicado ao montar pares: {case_id}")
        by_id[case_id] = case
    anchors = _episode_anchor_map(cases)
    pairs: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    for case in cases:
        if not is_dedup_challenge(case):
            continue
        reference_id = str(case.get("reference_case_id", "") or "").strip()
        episode_id = str(case.get("episode_id", "") or "").strip()
        reference = by_id.get(reference_id) if reference_id else None
        if reference_id and reference is None:
            raise ScientificGuardError(
                f"{case.get('case_id')}: reference_case_id inexistente: {reference_id}"
            )
        if reference is None:
            reference = anchors.get(episode_id)
        if reference is None or reference is case:
            raise ScientificGuardError(
                f"{case.get('case_id')}: desafio dedup sem âncora anterior disponível"
            )
        reference_episode = str(reference.get("episode_id", "") or "").strip()
        if not episode_id or reference_episode != episode_id:
            raise ScientificGuardError(
                f"{case.get('case_id')}: referência fora do próprio episódio"
            )
        current_order = int(
            case.get("order_in_episode", case.get("order_in_group", 0)) or 0
        )
        reference_order = int(
            reference.get(
                "order_in_episode", reference.get("order_in_group", 0)
            )
            or 0
        )
        if reference_order >= current_order:
            raise ScientificGuardError(
                f"{case.get('case_id')}: referência deve anteceder o desafio"
            )
        label = "DUPLICADO" if bool(case.get("expected_dedup")) else "NAO_DUPLICADO"
        pairs.append((case, reference, label))
    return pairs


def _normalized_equal(left: Any, right: Any) -> float:
    a = re.sub(r"\s+", " ", str(left or "").casefold()).strip()
    b = re.sub(r"\s+", " ", str(right or "").casefold()).strip()
    return float(bool(a) and a == b)


def _bounded_distance(left: Any, right: Any, maximum: float = 5.0) -> float:
    try:
        return min(1.0, abs(float(left) - float(right)) / maximum)
    except (TypeError, ValueError):
        return 1.0


def structured_pair_matrix(
    pairs: Sequence[tuple[dict[str, Any], dict[str, Any], str]]
) -> sparse.csr_matrix:
    rows = []
    for current, reference, _ in pairs:
        rows.append(
            [
                _normalized_equal(current.get("location"), reference.get("location")),
                _normalized_equal(current.get("category"), reference.get("category")),
                _normalized_equal(current.get("requester"), reference.get("requester")),
                float(bool(current.get("location")) and bool(reference.get("location"))),
                float(bool(current.get("category")) and bool(reference.get("category"))),
                _bounded_distance(current.get("urgency"), reference.get("urgency")),
                _bounded_distance(current.get("impact"), reference.get("impact")),
            ]
        )
    return sparse.csr_matrix(np.asarray(rows, dtype=np.float64))


def _pair_tfidf_features(
    vectorizer: FeatureUnion,
    pairs: Sequence[tuple[dict[str, Any], dict[str, Any], str]],
) -> sparse.csr_matrix:
    current = vectorizer.transform([model_text(pair[0]) for pair in pairs]).tocsr()
    reference = vectorizer.transform([model_text(pair[1]) for pair in pairs]).tocsr()
    absolute_difference = abs(current - reference)
    overlap = current.multiply(reference)
    dot = np.asarray(current.multiply(reference).sum(axis=1), dtype=np.float64).reshape(-1)
    current_norm = np.sqrt(
        np.asarray(current.multiply(current).sum(axis=1), dtype=np.float64).reshape(-1)
    )
    reference_norm = np.sqrt(
        np.asarray(reference.multiply(reference).sum(axis=1), dtype=np.float64).reshape(-1)
    )
    denominator = current_norm * reference_norm
    cosine_values = np.divide(
        dot,
        denominator,
        out=np.zeros_like(dot),
        where=denominator > 0,
    ).reshape(-1, 1)
    return sparse.hstack(
        [
            absolute_difference,
            overlap,
            sparse.csr_matrix(cosine_values),
            structured_pair_matrix(pairs),
        ],
        format="csr",
    )


def _pair_embedding_features(
    pairs: Sequence[tuple[dict[str, Any], dict[str, Any], str]],
    *,
    backend: str,
    field: str,
    mock_dimension: int,
    expected_dimension: int,
    encoder: GraniteEmbeddingEncoder | None = None,
) -> sparse.csr_matrix | None:
    if backend == "tfidf":
        return None
    current, _ = embedding_matrix(
        [pair[0] for pair in pairs],
        backend=backend,
        field=field,
        mock_dimension=mock_dimension,
        expected_dimension=expected_dimension,
        encoder=encoder,
    )
    reference, _ = embedding_matrix(
        [pair[1] for pair in pairs],
        backend=backend,
        field=field,
        mock_dimension=mock_dimension,
        expected_dimension=expected_dimension,
        encoder=encoder,
    )
    assert current is not None and reference is not None
    cosine = np.sum(current * reference, axis=1, keepdims=True)
    dense = np.hstack([np.abs(current - reference), current * reference, cosine])
    return sparse.csr_matrix(dense)


def _candidate_group_splits(
    labels: Sequence[str],
    groups: Sequence[str],
    *,
    seed: int,
    minimum_train_class_support: int = 1,
) -> tuple[list[tuple[np.ndarray, np.ndarray]], int, int | None]:
    unique_groups = len(set(groups))
    minimum_class_support = min(Counter(labels).values(), default=0)
    for folds in range(min(5, unique_groups, minimum_class_support), 1, -1):
        for attempt in range(64):
            splitter = StratifiedGroupKFold(
                n_splits=folds, shuffle=True, random_state=seed + attempt
            )
            splits = list(splitter.split(np.zeros(len(labels)), labels, groups))
            all_labels = set(labels)
            valid = True
            for train_index, validation_index in splits:
                train_counts = Counter(np.asarray(labels)[train_index])
                if (
                    set(train_counts) != all_labels
                    or set(np.asarray(labels)[validation_index]) != all_labels
                    or min(train_counts.values()) < minimum_train_class_support
                ):
                    valid = False
                    break
            if valid:
                return splits, folds, seed + attempt
    return [], 0, None


def _select_logistic_hyperparameters(
    matrix: sparse.csr_matrix,
    labels: Sequence[str],
    groups: Sequence[str],
    *,
    seed: int,
    task: str,
    fold_feature_factory: Callable[
        [np.ndarray, np.ndarray], tuple[sparse.csr_matrix, sparse.csr_matrix]
    ]
    | None = None,
    false_negative_cost: float = 5.0,
    false_positive_cost: float = DEDUP_FALSE_POSITIVE_COST,
) -> tuple[dict[str, Any], dict[str, Any]]:
    splits, folds, effective_seed = _candidate_group_splits(
        labels, groups, seed=seed
    )
    default_weight: Any = "balanced"
    if task == "deduplication":
        default_weight = {
            "NAO_DUPLICADO": float(false_positive_cost),
            "DUPLICADO": float(false_negative_cost),
        }
    default = {"C": 1.0, "class_weight": default_weight}
    if not splits:
        return default, {
            "strategy": "fixed_fallback",
            "reason": "insufficient_class_support_across_disjoint_groups",
            "group_folds": 0,
            "requested_seed": seed,
            "effective_seed": None,
            "selected": default,
            "candidates": [],
        }
    prepared_folds: list[
        tuple[np.ndarray, np.ndarray, sparse.csr_matrix, sparse.csr_matrix]
    ] = []
    for train_index, validation_index in splits:
        if fold_feature_factory is None:
            fold_train = matrix[train_index]
            fold_validation = matrix[validation_index]
        else:
            fold_train, fold_validation = fold_feature_factory(
                train_index, validation_index
            )
        if fold_train.shape[0] != len(train_index) or fold_validation.shape[0] != len(
            validation_index
        ):
            raise ScientificGuardError(
                "Fábrica de atributos do CV retornou número de linhas divergente"
            )
        prepared_folds.append(
            (train_index, validation_index, fold_train, fold_validation)
        )

    results: list[dict[str, Any]] = []
    label_array = np.asarray(labels)
    class_weights: tuple[Any, ...] = (None, "balanced")
    if task == "deduplication":
        class_weights = (
            {
                "NAO_DUPLICADO": float(false_positive_cost),
                "DUPLICADO": float(false_negative_cost),
            },
            None,
            "balanced",
        )
    for regularization in (0.03, 0.1, 0.3, 1.0, 3.0, 10.0):
        for class_weight in class_weights:
            fold_scores: list[float] = []
            fold_macro_f1: list[float] = []
            fold_average_precision: list[float] = []
            fold_weighted_costs: list[float] = []
            fold_duplicate_recalls: list[float] = []
            for fold_index, (
                train_index,
                validation_index,
                fold_train,
                fold_validation,
            ) in enumerate(prepared_folds):
                estimator = LogisticRegression(
                    C=regularization,
                    class_weight=class_weight,
                    max_iter=4000,
                    random_state=seed + fold_index,
                    solver="liblinear" if len(set(labels)) == 2 else "lbfgs",
                )
                estimator.fit(fold_train, label_array[train_index])
                predicted = estimator.predict(fold_validation)
                macro_f1 = float(
                    f1_score(
                        label_array[validation_index],
                        predicted,
                        average="macro",
                        zero_division=0,
                    )
                )
                average_precision: float | None = None
                normalized_weighted_cost: float | None = None
                duplicate_recall: float | None = None
                score = macro_f1
                if task == "deduplication":
                    positive_index = list(estimator.classes_).index("DUPLICADO")
                    positive_probability = estimator.predict_proba(
                        fold_validation
                    )[:, positive_index]
                    binary_gold = (
                        label_array[validation_index] == "DUPLICADO"
                    ).astype(int)
                    average_precision = float(
                        average_precision_score(binary_gold, positive_probability)
                    )
                    fold_gold = label_array[validation_index]
                    false_negatives = int(
                        np.sum(
                            (fold_gold == "DUPLICADO")
                            & (predicted == "NAO_DUPLICADO")
                        )
                    )
                    false_positives = int(
                        np.sum(
                            (fold_gold == "NAO_DUPLICADO")
                            & (predicted == "DUPLICADO")
                        )
                    )
                    positives = int(np.sum(fold_gold == "DUPLICADO"))
                    negatives = int(np.sum(fold_gold == "NAO_DUPLICADO"))
                    weighted_cost = (
                        false_negative_cost * false_negatives
                        + false_positive_cost * false_positives
                    )
                    maximum_cost = (
                        false_negative_cost * positives
                        + false_positive_cost * negatives
                    )
                    normalized_weighted_cost = (
                        float(weighted_cost / maximum_cost) if maximum_cost else 1.0
                    )
                    duplicate_recall = (
                        float((positives - false_negatives) / positives)
                        if positives
                        else 0.0
                    )
                    # A função-objetivo aplica literalmente o custo definido no
                    # protocolo: FN=5 e FP=1 por padrão. AP fica como métrica de
                    # desempate/auditoria, sem diluir a assimetria de custo.
                    score = 1.0 - normalized_weighted_cost
                fold_scores.append(score)
                fold_macro_f1.append(macro_f1)
                if average_precision is not None:
                    fold_average_precision.append(average_precision)
                if normalized_weighted_cost is not None:
                    fold_weighted_costs.append(normalized_weighted_cost)
                if duplicate_recall is not None:
                    fold_duplicate_recalls.append(duplicate_recall)
            results.append(
                {
                    "C": regularization,
                    "class_weight": class_weight,
                    "mean_score": float(np.mean(fold_scores)),
                    "std_score": float(np.std(fold_scores)),
                    "mean_macro_f1": float(np.mean(fold_macro_f1)),
                    "mean_average_precision": float(
                        np.mean(fold_average_precision)
                    )
                    if fold_average_precision
                    else None,
                    "mean_normalized_weighted_cost": float(
                        np.mean(fold_weighted_costs)
                    )
                    if fold_weighted_costs
                    else None,
                    "mean_duplicate_recall": float(np.mean(fold_duplicate_recalls))
                    if fold_duplicate_recalls
                    else None,
                    "objective_false_negative_cost": false_negative_cost
                    if task == "deduplication"
                    else None,
                    "objective_false_positive_cost": false_positive_cost
                    if task == "deduplication"
                    else None,
                }
            )
    # Ordem determinística: melhor média, menor variância e regularização mais
    # forte em caso de empate para reduzir sobreajuste no corpus pequeno.
    winner = max(
        results,
        key=lambda item: (
            round(float(item["mean_score"]), 12),
            round(float(item.get("mean_average_precision") or 0.0), 12),
            -round(float(item["std_score"]), 12),
            -float(item["C"]),
            isinstance(item["class_weight"], dict),
        ),
    )
    selected = {"C": winner["C"], "class_weight": winner["class_weight"]}
    return selected, {
        "strategy": "stratified_group_cross_validation",
        "objective": "macro_f1"
        if task == "classification"
        else "minimize_group_cv_expected_cost",
        "error_costs": {
            "false_negative": false_negative_cost,
            "false_positive": false_positive_cost,
        }
        if task == "deduplication"
        else None,
        "group_folds": folds,
        "requested_seed": seed,
        "effective_seed": effective_seed,
        "fold_local_feature_fitting": fold_feature_factory is not None,
        "selected": selected,
        "candidates": results,
    }


def _fit_frozen_calibrator(
    base: LogisticRegression,
    matrix: sparse.csr_matrix,
    labels: Sequence[str],
) -> CalibratedClassifierCV:
    if set(labels) != set(base.classes_):
        raise ScientificGuardError(
            "Calibração probabilística precisa conter todas as classes do modelo-base"
        )
    if min(Counter(labels).values(), default=0) < 2:
        raise ScientificGuardError(
            "Calibração sigmoide exige ao menos duas observações por classe"
        )
    # Com FrozenEstimator o classificador não é reajustado. O sklearn 1.7 ainda
    # usa cv apenas para produzir as respostas do estimador congelado antes de
    # ajustar um único calibrador; dois folds evitam a dependência do default=5
    # sem reintroduzir treino do modelo-base no conjunto de calibração.
    calibrated = CalibratedClassifierCV(
        FrozenEstimator(base), method=CALIBRATION_METHOD, cv=2, ensemble=False
    )
    calibrated.fit(matrix, labels)
    return calibrated


def _cross_fitted_calibration(
    base: LogisticRegression,
    calibration_matrix: sparse.csr_matrix,
    calibration_labels: Sequence[str],
    calibration_groups: Sequence[str],
    *,
    seed: int,
) -> tuple[CalibratedClassifierCV, np.ndarray, dict[str, Any]]:
    """Gera probabilidades OOF agrupadas e ajusta o calibrador operacional final.

    Cada registro usado para selecionar limiares é previsto por um calibrador
    que não o viu. Depois disso, um calibrador separado é ajustado em toda a
    calibração para ser serializado no bundle; suas probabilidades não entram
    na escolha nem nas métricas dos limiares.
    """

    splits, folds, effective_seed = _candidate_group_splits(
        calibration_labels,
        calibration_groups,
        seed=seed,
        minimum_train_class_support=2,
    )
    if not splits:
        raise ScientificGuardError(
            "Calibração cruzada agrupada exige >=2 folds com todas as classes"
        )
    classes = list(base.classes_)
    probabilities = np.full(
        (len(calibration_labels), len(classes)), np.nan, dtype=np.float64
    )
    fold_audit: list[dict[str, Any]] = []
    labels_array = np.asarray(calibration_labels)
    groups_array = np.asarray(calibration_groups)
    for fold_index, (fit_index, validation_index) in enumerate(splits):
        fit_groups = set(groups_array[fit_index])
        validation_groups = set(groups_array[validation_index])
        overlap = fit_groups & validation_groups
        if overlap:
            raise ScientificGuardError(
                f"Vazamento de grupo no fold de calibração {fold_index}: {sorted(overlap)[:3]}"
            )
        fold_calibrator = _fit_frozen_calibrator(
            base, calibration_matrix[fit_index], labels_array[fit_index]
        )
        fold_probability = fold_calibrator.predict_proba(
            calibration_matrix[validation_index]
        )
        fold_classes = list(fold_calibrator.classes_)
        if set(fold_classes) != set(classes):
            raise ScientificGuardError(
                "Classes divergentes entre folds da calibração probabilística"
            )
        reorder = [fold_classes.index(label) for label in classes]
        probabilities[validation_index] = fold_probability[:, reorder]
        fold_audit.append(
            {
                "fold": fold_index,
                "fit_records": len(fit_index),
                "validation_records": len(validation_index),
                "fit_groups": len(fit_groups),
                "validation_groups": len(validation_groups),
                "group_overlap": 0,
                "fit_groups_sha256": canonical_sha256(sorted(fit_groups)),
                "validation_groups_sha256": canonical_sha256(
                    sorted(validation_groups)
                ),
                "validation_indices_sha256": canonical_sha256(
                    sorted(int(index) for index in validation_index)
                ),
            }
        )
    if not np.isfinite(probabilities).all():
        raise ScientificGuardError(
            "Calibração cruzada não produziu uma probabilidade OOF para cada registro"
        )
    final_calibrator = _fit_frozen_calibrator(
        base, calibration_matrix, calibration_labels
    )
    return final_calibrator, probabilities, {
        "method": CALIBRATION_METHOD,
        "frozen_estimator_response_cv": 2,
        "strategy": "group_cross_fitted_threshold_probabilities_then_full_refit",
        "folds": folds,
        "requested_seed": seed,
        "effective_seed": effective_seed,
        "threshold_probabilities_out_of_fold": True,
        "final_calibrator_probabilities_used_for_threshold_selection": False,
        "fold_audit": fold_audit,
    }


def _fit_calibrated_model(
    train_matrix: sparse.csr_matrix,
    train_labels: Sequence[str],
    train_groups: Sequence[str],
    calibration_matrix: sparse.csr_matrix,
    calibration_labels: Sequence[str],
    calibration_groups: Sequence[str],
    *,
    seed: int,
    task: str,
    fold_feature_factory: Callable[
        [np.ndarray, np.ndarray], tuple[sparse.csr_matrix, sparse.csr_matrix]
    ]
    | None = None,
    false_negative_cost: float = 5.0,
    false_positive_cost: float = DEDUP_FALSE_POSITIVE_COST,
) -> tuple[CalibratedClassifierCV, dict[str, Any], np.ndarray]:
    parameters, tuning_audit = _select_logistic_hyperparameters(
        train_matrix,
        train_labels,
        train_groups,
        seed=seed,
        task=task,
        fold_feature_factory=fold_feature_factory,
        false_negative_cost=false_negative_cost,
        false_positive_cost=false_positive_cost,
    )
    base = LogisticRegression(
        C=float(parameters["C"]),
        class_weight=parameters["class_weight"],
        max_iter=4000,
        random_state=seed,
        solver="liblinear" if len(set(train_labels)) == 2 else "lbfgs",
    )
    base.fit(train_matrix, train_labels)
    calibrated, out_of_fold_probabilities, calibration_audit = (
        _cross_fitted_calibration(
            base,
            calibration_matrix,
            calibration_labels,
            [str(group) for group in calibration_groups],
            seed=seed + 1000,
        )
    )
    tuning_audit["probability_calibration"] = calibration_audit
    return calibrated, tuning_audit, out_of_fold_probabilities


def _wilson_interval(
    successes: int,
    total: int,
    *,
    confidence_level: float = CONFIDENCE_LEVEL,
) -> list[float] | None:
    if total <= 0:
        return None
    z = NormalDist().inv_cdf(0.5 + confidence_level / 2.0)
    proportion = successes / total
    denominator = 1.0 + z * z / total
    centre = (proportion + z * z / (2.0 * total)) / denominator
    margin = (
        z
        * np.sqrt(
            proportion * (1.0 - proportion) / total
            + z * z / (4.0 * total * total)
        )
        / denominator
    )
    return [float(max(0.0, centre - margin)), float(min(1.0, centre + margin))]


def _expected_calibration_error(
    probabilities: np.ndarray,
    gold: Sequence[str],
    classes: Sequence[str],
    *,
    bins: int = 10,
) -> float:
    predicted_index = np.argmax(probabilities, axis=1)
    confidence = np.max(probabilities, axis=1)
    class_index = {label: index for index, label in enumerate(classes)}
    correct = np.asarray(
        [predicted_index[index] == class_index[label] for index, label in enumerate(gold)],
        dtype=np.float64,
    )
    error = 0.0
    edges = np.linspace(0.0, 1.0, bins + 1)
    for bin_index in range(bins):
        lower = edges[bin_index]
        upper = edges[bin_index + 1]
        mask = (confidence >= lower) & (
            confidence <= upper if bin_index == bins - 1 else confidence < upper
        )
        count = int(mask.sum())
        if not count:
            continue
        error += (count / len(gold)) * abs(
            float(np.mean(correct[mask])) - float(np.mean(confidence[mask]))
        )
    return float(error)


def _classification_probability_metrics(
    probabilities: np.ndarray,
    gold: Sequence[str],
    classes: Sequence[str],
) -> dict[str, Any]:
    predicted = np.asarray(classes)[np.argmax(probabilities, axis=1)]
    class_index = {label: index for index, label in enumerate(classes)}
    one_hot = np.zeros_like(probabilities, dtype=np.float64)
    for row_index, label in enumerate(gold):
        one_hot[row_index, class_index[label]] = 1.0
    matrix = confusion_matrix(gold, predicted, labels=list(classes))
    return {
        "source": "group_cross_fitted_probability_calibration",
        "records": len(gold),
        "accuracy": float(accuracy_score(gold, predicted)),
        "macro_f1": float(f1_score(gold, predicted, average="macro", zero_division=0)),
        "multiclass_log_loss": float(
            log_loss(gold, probabilities, labels=list(classes))
        ),
        "multiclass_brier_score": float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1))),
        "expected_calibration_error_10_bins": _expected_calibration_error(
            probabilities, gold, classes
        ),
        "confusion_matrix": {
            "labels": list(classes),
            "values": matrix.astype(int).tolist(),
        },
    }


def _classification_pipeline_metrics(
    full_cases: Sequence[dict[str, Any]],
    model_cases: Sequence[dict[str, Any]],
    model_probabilities: np.ndarray,
    model_classes: Sequence[str],
    threshold: float | None,
    obra_threshold: float = OBRA_AUTOMATIC_MIN_CONFIDENCE,
) -> dict[str, Any]:
    """Mede o pipeline completo sem misturar one-hot de regra à calibração."""
    probability_by_case = {
        str(case["case_id"]): model_probabilities[index]
        for index, case in enumerate(model_cases)
    }
    classes = list(model_classes)
    gold: list[str] = []
    predicted: list[str] = []
    automatic: list[bool] = []
    paths: list[str] = []
    operational_sufficient: list[bool] = []
    obra_safety_gated: list[bool] = []
    for case in full_cases:
        obra_blocked = False
        expected = str(case["expected_classification"]).upper()
        extracted = deterministic_extract(case, 6000)
        route = classification_pre_model_path(extracted)
        operational = classification_operational_information_sufficient(
            extracted
        )
        if route == "deterministic_specialized_asset":
            decision = "SOB_DEMANDA"
            covered = operational
        elif route in {
            "deterministic_insufficient_information",
            "deterministic_contradiction",
            "deterministic_out_of_scope",
        }:
            decision = "TRIAGEM_MANUAL"
            covered = False
        else:
            row = probability_by_case.get(str(case["case_id"]))
            if row is None:
                raise ScientificGuardError(
                    f"{case.get('case_id')}: caso model-only sem probabilidade OOF"
                )
            winner_index = int(np.argmax(row))
            decision = classes[winner_index]
            confidence = float(row[winner_index])
            abstained = bool(
                decision != "TRIAGEM_MANUAL"
                and (
                    threshold is None
                    or confidence < threshold
                    or (decision == "OBRA" and confidence < obra_threshold)
                )
            )
            obra_gate = obra_automatic_evidence(extracted)
            obra_blocked = bool(
                decision == "OBRA" and not obra_gate["sufficient"]
            )
            covered = bool(
                operational
                and not abstained
                and not obra_blocked
                and decision != "TRIAGEM_MANUAL"
            )
            route = "hybrid_model_abstention" if abstained else "hybrid_model"
        gold.append(expected)
        predicted.append(decision)
        automatic.append(covered)
        paths.append(str(route))
        operational_sufficient.append(operational)
        obra_safety_gated.append(obra_blocked)

    gold_array = np.asarray(gold)
    predicted_array = np.asarray(predicted)
    automatic_array = np.asarray(automatic, dtype=bool)
    correct = predicted_array == gold_array
    path_metrics: dict[str, Any] = {}
    for path in sorted(set(paths)):
        mask = np.asarray([value == path for value in paths], dtype=bool)
        path_metrics[path] = {
            "records": int(mask.sum()),
            "semantic_correct": int(np.sum(correct & mask)),
            "semantic_errors": int(np.sum((~correct) & mask)),
            "automatic_records": int(np.sum(automatic_array & mask)),
        }
    covered_count = int(automatic_array.sum())
    covered_errors = int(np.sum((~correct) & automatic_array))
    maintenance_gold = np.asarray(
        [value in {"DEMO", "SOB_DEMANDA"} for value in gold], dtype=bool
    )
    predicted_obra = predicted_array == "OBRA"
    maintenance_as_obra_semantic = int(
        np.sum(maintenance_gold & predicted_obra)
    )
    maintenance_as_obra_automatic = int(
        np.sum(maintenance_gold & predicted_obra & automatic_array)
    )
    confusion_labels = list(CLASS_LABELS)
    return {
        "scope": "full_pipeline_including_deterministic_paths",
        "source": "development_group_cross_fitted_calibration",
        "records": len(full_cases),
        "semantic_accuracy": float(accuracy_score(gold, predicted)),
        "semantic_macro_f1": float(
            f1_score(gold, predicted, average="macro", zero_division=0)
        ),
        "semantic_confusion_matrix": {
            "labels": confusion_labels,
            "values": confusion_matrix(
                gold, predicted, labels=confusion_labels
            ).astype(int).tolist(),
        },
        "operational_information_sufficient_records": int(
            np.sum(operational_sufficient)
        ),
        "operational_information_insufficient_records": int(
            len(full_cases) - np.sum(operational_sufficient)
        ),
        "automatic_coverage": (
            covered_count / len(full_cases) if full_cases else 0.0
        ),
        "automatic_records": covered_count,
        "human_review_records": len(full_cases) - covered_count,
        "automatic_errors": covered_errors,
        "automatic_risk": (
            covered_errors / covered_count if covered_count else None
        ),
        "critical_error_policy": {
            "error": "maintenance_as_obra",
            "automatic_errors": maintenance_as_obra_automatic,
            "semantic_errors_before_gate": maintenance_as_obra_semantic,
            "obra_safety_gated_records": int(np.sum(obra_safety_gated)),
            "maximum_automatic_errors_for_approval": 0,
            "rationale": (
                "OBRA dispara comunicacao automatica ao DDI/DG; predicoes sem "
                "evidencia explicita sao abstidas para revisao fiscal"
            ),
        },
        "model_probability_records": len(model_cases),
        "deterministic_policy_probabilities_excluded": True,
        "probability_metrics_are_model_only": True,
        "by_decision_path": path_metrics,
    }


def _dedup_probability_metrics(
    probabilities: np.ndarray,
    gold: Sequence[str],
    classes: Sequence[str],
) -> dict[str, Any]:
    positive_index = list(classes).index("DUPLICADO")
    positive_probability = probabilities[:, positive_index]
    binary_gold = np.asarray([label == "DUPLICADO" for label in gold], dtype=int)
    return {
        "source": "group_cross_fitted_probability_calibration",
        "records": len(gold),
        "positive_records": int(binary_gold.sum()),
        "negative_records": int(len(binary_gold) - binary_gold.sum()),
        "average_precision": float(
            average_precision_score(binary_gold, positive_probability)
        ),
        "roc_auc": float(roc_auc_score(binary_gold, positive_probability)),
        "binary_log_loss": float(
            log_loss(gold, probabilities, labels=list(classes))
        ),
        "brier_score": float(np.mean((positive_probability - binary_gold) ** 2)),
        "expected_calibration_error_10_bins": _expected_calibration_error(
            probabilities, gold, classes
        ),
    }


def _validate_operating_policy(
    *,
    max_classification_risk: float,
    min_classification_coverage: float,
    max_dedup_false_positive_rate: float,
    min_dedup_precision: float,
    min_dedup_coverage: float,
    max_dedup_false_negative_rate: float,
    min_dedup_negative_predictive_value: float,
    dedup_false_negative_cost: float,
) -> None:
    proportions = {
        "max_classification_risk": max_classification_risk,
        "min_classification_coverage": min_classification_coverage,
        "max_dedup_false_positive_rate": max_dedup_false_positive_rate,
        "min_dedup_precision": min_dedup_precision,
        "min_dedup_coverage": min_dedup_coverage,
        "max_dedup_false_negative_rate": max_dedup_false_negative_rate,
        "min_dedup_negative_predictive_value": min_dedup_negative_predictive_value,
    }
    invalid = {
        name: value for name, value in proportions.items() if not 0.0 <= value <= 1.0
    }
    if invalid:
        raise ScientificGuardError(f"Parâmetros de proporção fora de 0..1: {invalid}")
    if dedup_false_negative_cost <= DEDUP_FALSE_POSITIVE_COST:
        raise ScientificGuardError(
            "O custo de falso negativo deve ser maior que o custo de falso positivo"
        )


def _classification_threshold(
    probabilities: np.ndarray,
    predicted: Sequence[str],
    gold: Sequence[str],
    classes: Sequence[str],
    *,
    max_risk: float,
    min_coverage: float,
) -> tuple[float | None, list[dict[str, Any]]]:
    class_index = {label: index for index, label in enumerate(classes)}
    confidence = np.asarray(
        [probabilities[index, class_index[label]] for index, label in enumerate(predicted)]
    )
    curve: list[dict[str, Any]] = []
    eligible: list[dict[str, Any]] = []
    for threshold_int in range(50, 100):
        threshold = threshold_int / 100
        covered = confidence >= threshold
        covered_count = int(covered.sum())
        correct = sum(
            bool(covered[index]) and predicted[index] == gold[index]
            for index in range(len(gold))
        )
        coverage = covered_count / len(gold) if gold else 0.0
        risk = 1 - correct / covered_count if covered_count else None
        point = {
            "threshold": threshold,
            "coverage": coverage,
            "covered": covered_count,
            "abstained": len(gold) - covered_count,
            "correct": correct,
            "errors": covered_count - correct,
            "risk": risk,
        }
        curve.append(point)
        if risk is not None and risk <= max_risk and coverage >= min_coverage:
            eligible.append(point)
    selected = (
        float(
            min(
                eligible,
                key=lambda point: (
                    float(point["risk"]),
                    -float(point["coverage"]),
                    -float(point["threshold"]),
                ),
            )["threshold"]
        )
        if eligible
        else None
    )
    return selected, curve


def _dedup_threshold(
    probabilities: np.ndarray,
    gold: Sequence[str],
    classes: Sequence[str],
    *,
    max_false_positive_rate: float,
    min_precision: float,
    min_coverage: float,
    max_false_negative_rate: float = 0.02,
    min_negative_predictive_value: float = 0.98,
    false_negative_cost: float = 5.0,
    false_positive_cost: float = 1.0,
) -> tuple[float | None, float | None, list[dict[str, Any]]]:
    positive_index = list(classes).index("DUPLICADO")
    p_duplicate = probabilities[:, positive_index]
    negatives = sum(label == "NAO_DUPLICADO" for label in gold)
    positives = sum(label == "DUPLICADO" for label in gold)
    curve: list[dict[str, Any]] = []
    eligible: list[dict[str, Any]] = []
    for positive_int in range(50, 100):
        positive_threshold = positive_int / 100
        for negative_int in range(1, 50):
            negative_threshold = negative_int / 100
            if negative_threshold >= positive_threshold:
                continue
            auto_positive = p_duplicate >= positive_threshold
            auto_negative = p_duplicate <= negative_threshold
            covered = auto_positive | auto_negative
            tp = fp = tn = fn = 0
            for index, label in enumerate(gold):
                if auto_positive[index]:
                    if label == "DUPLICADO":
                        tp += 1
                    else:
                        fp += 1
                elif auto_negative[index]:
                    if label == "NAO_DUPLICADO":
                        tn += 1
                    else:
                        fn += 1
            covered_count = int(covered.sum())
            coverage = covered_count / len(gold) if gold else 0.0
            precision = tp / (tp + fp) if tp + fp else None
            negative_predictive_value = tn / (tn + fn) if tn + fn else None
            false_positive_rate = fp / negatives if negatives else None
            false_negative_rate = fn / positives if positives else None
            error_rate = (fp + fn) / covered_count if covered_count else None
            weighted_error = (
                false_positive_cost * fp + false_negative_cost * fn
            ) / covered_count if covered_count else None
            point = {
                "threshold": positive_threshold,
                "positive_threshold": positive_threshold,
                "negative_threshold": negative_threshold,
                "coverage": coverage,
                "covered": covered_count,
                "abstained": len(gold) - covered_count,
                "tp": tp,
                "fp": fp,
                "tn": tn,
                "fn": fn,
                "positives": positives,
                "negatives": negatives,
                "precision": precision,
                "negative_predictive_value": negative_predictive_value,
                "automated_false_positive_rate": false_positive_rate,
                "automated_false_negative_rate": false_negative_rate,
                "covered_error_rate": error_rate,
                "weighted_covered_error": weighted_error,
                "automation_duplicate_recall": tp / positives if positives else None,
                "automation_nonduplicate_recall": tn / negatives if negatives else None,
                "false_negative_cost": false_negative_cost,
                "false_positive_cost": false_positive_cost,
            }
            curve.append(point)
            if (
                precision is not None
                and negative_predictive_value is not None
                and false_positive_rate is not None
                and false_negative_rate is not None
                and precision >= min_precision
                and negative_predictive_value >= min_negative_predictive_value
                and false_positive_rate <= max_false_positive_rate
                and false_negative_rate <= max_false_negative_rate
                and coverage >= min_coverage
            ):
                eligible.append(point)
    if not eligible:
        return None, None, curve
    selected = min(
        eligible,
        key=lambda point: (
            float(point["weighted_covered_error"]),
            int(point["fn"]),
            -float(point["coverage"]),
            -float(point["positive_threshold"]),
            float(point["negative_threshold"]),
        ),
    )
    return (
        float(selected["positive_threshold"]),
        float(selected["negative_threshold"]),
        curve,
    )


def train_bundle(
    train_cases: Sequence[dict[str, Any]],
    calibration_cases: Sequence[dict[str, Any]],
    *,
    output_dir: Path,
    source_audit: Sequence[dict[str, Any]],
    split_audit: dict[str, Any],
    seed: int = 20260715,
    group_field: str = "auto",
    embedding_backend: str = "tfidf",
    embedding_field: str = "embedding",
    mock_embedding_dimension: int = 16,
    embedding_encoder: GraniteEmbeddingEncoder | None = None,
    max_classification_risk: float = 0.10,
    min_classification_coverage: float = 0.60,
    max_dedup_false_positive_rate: float = 0.05,
    min_dedup_precision: float = 0.90,
    min_dedup_coverage: float = 0.50,
    max_dedup_false_negative_rate: float = 0.02,
    min_dedup_negative_predictive_value: float = 0.98,
    dedup_false_negative_cost: float = 5.0,
) -> tuple[dict[str, Any], Path, Path]:
    pipeline_source_hashes = {
        name: sha256_file(path) for name, path in PIPELINE_SOURCE_FILES.items()
    }
    _validate_operating_policy(
        max_classification_risk=max_classification_risk,
        min_classification_coverage=min_classification_coverage,
        max_dedup_false_positive_rate=max_dedup_false_positive_rate,
        min_dedup_precision=min_dedup_precision,
        min_dedup_coverage=min_dedup_coverage,
        max_dedup_false_negative_rate=max_dedup_false_negative_rate,
        min_dedup_negative_predictive_value=min_dedup_negative_predictive_value,
        dedup_false_negative_cost=dedup_false_negative_cost,
    )
    validate_labels(train_cases, "treino")
    validate_labels(calibration_cases, "calibração")
    leakage_audit = assert_no_split_leakage(train_cases, calibration_cases)

    train_class_all = classification_rows(train_cases)
    calibration_class_all = classification_rows(calibration_cases)
    train_class = classification_model_rows(train_cases)
    calibration_class = classification_model_rows(calibration_cases)
    if set(case["expected_classification"] for case in train_class) != set(
        CLASS_LABELS
    ):
        raise ScientificGuardError(
            "Estrato model-only de treino precisa conter as quatro classes"
        )
    if set(case["expected_classification"] for case in calibration_class) != set(
        CLASS_LABELS
    ):
        raise ScientificGuardError(
            "Estrato model-only de calibração precisa conter as quatro classes"
        )
    classification_vectorizer = build_text_vectorizer()
    train_class_tfidf = classification_vectorizer.fit_transform(
        [model_text(case) for case in train_class]
    ).tocsr()
    calibration_class_tfidf = classification_vectorizer.transform(
        [model_text(case) for case in calibration_class]
    ).tocsr()
    train_embeddings, embedding_dimension = embedding_matrix(
        train_class,
        backend=embedding_backend,
        field=embedding_field,
        mock_dimension=mock_embedding_dimension,
        encoder=embedding_encoder,
    )
    calibration_embeddings, _ = embedding_matrix(
        calibration_class,
        backend=embedding_backend,
        field=embedding_field,
        mock_dimension=mock_embedding_dimension,
        expected_dimension=embedding_dimension if embedding_dimension else None,
        encoder=embedding_encoder,
    )
    if train_embeddings is not None and calibration_embeddings is not None:
        train_class_matrix = sparse.hstack(
            [
                train_class_tfidf,
                sparse.csr_matrix(train_embeddings),
            ],
            format="csr",
        )
        calibration_class_matrix = sparse.hstack(
            [
                calibration_class_tfidf,
                sparse.csr_matrix(calibration_embeddings),
            ],
            format="csr",
        )
    else:
        train_class_matrix = train_class_tfidf
        calibration_class_matrix = calibration_class_tfidf
    train_class_labels = [str(case["expected_classification"]).upper() for case in train_class]
    calibration_class_labels = [
        str(case["expected_classification"]).upper() for case in calibration_class
    ]

    def classification_fold_features(
        fit_index: np.ndarray, validation_index: np.ndarray
    ) -> tuple[sparse.csr_matrix, sparse.csr_matrix]:
        fold_vectorizer = build_text_vectorizer()
        fold_train = fold_vectorizer.fit_transform(
            [model_text(train_class[index]) for index in fit_index]
        ).tocsr()
        fold_validation = fold_vectorizer.transform(
            [model_text(train_class[index]) for index in validation_index]
        ).tocsr()
        if train_embeddings is not None:
            fold_train = sparse.hstack(
                [fold_train, sparse.csr_matrix(train_embeddings[fit_index])],
                format="csr",
            )
            fold_validation = sparse.hstack(
                [
                    fold_validation,
                    sparse.csr_matrix(train_embeddings[validation_index]),
                ],
                format="csr",
            )
        return fold_train, fold_validation

    (
        classification_model,
        classification_tuning,
        classification_probabilities,
    ) = _fit_calibrated_model(
        train_class_matrix,
        train_class_labels,
        [group_key(case, group_field) for case in train_class],
        calibration_class_matrix,
        calibration_class_labels,
        [group_key(case, group_field) for case in calibration_class],
        seed=seed,
        task="classification",
        fold_feature_factory=classification_fold_features,
    )

    train_pairs = dedup_pairs(train_cases)
    calibration_pairs = dedup_pairs(calibration_cases)
    dedup_vectorizer = build_text_vectorizer()
    dedup_vectorizer.fit(
        [model_text(pair[index]) for pair in train_pairs for index in (0, 1)]
    )
    train_dedup_matrix = _pair_tfidf_features(dedup_vectorizer, train_pairs)
    calibration_dedup_matrix = _pair_tfidf_features(
        dedup_vectorizer, calibration_pairs
    )
    train_pair_embeddings = _pair_embedding_features(
        train_pairs,
        backend=embedding_backend,
        field=embedding_field,
        mock_dimension=mock_embedding_dimension,
        expected_dimension=embedding_dimension,
        encoder=embedding_encoder,
    )
    calibration_pair_embeddings = _pair_embedding_features(
        calibration_pairs,
        backend=embedding_backend,
        field=embedding_field,
        mock_dimension=mock_embedding_dimension,
        expected_dimension=embedding_dimension,
        encoder=embedding_encoder,
    )
    if train_pair_embeddings is not None and calibration_pair_embeddings is not None:
        train_dedup_matrix = sparse.hstack(
            [train_dedup_matrix, train_pair_embeddings], format="csr"
        )
        calibration_dedup_matrix = sparse.hstack(
            [calibration_dedup_matrix, calibration_pair_embeddings], format="csr"
        )
    train_dedup_labels = [pair[2] for pair in train_pairs]
    calibration_dedup_labels = [pair[2] for pair in calibration_pairs]
    def dedup_fold_features(
        fit_index: np.ndarray, validation_index: np.ndarray
    ) -> tuple[sparse.csr_matrix, sparse.csr_matrix]:
        fold_vectorizer = build_text_vectorizer()
        fit_pairs = [train_pairs[index] for index in fit_index]
        validation_pairs = [train_pairs[index] for index in validation_index]
        fold_vectorizer.fit(
            [model_text(pair[index]) for pair in fit_pairs for index in (0, 1)]
        )
        fold_train = _pair_tfidf_features(fold_vectorizer, fit_pairs)
        fold_validation = _pair_tfidf_features(
            fold_vectorizer, validation_pairs
        )
        if train_pair_embeddings is not None:
            fold_train = sparse.hstack(
                [fold_train, train_pair_embeddings[fit_index]], format="csr"
            )
            fold_validation = sparse.hstack(
                [fold_validation, train_pair_embeddings[validation_index]],
                format="csr",
            )
        return fold_train, fold_validation

    dedup_model, dedup_tuning, dedup_probabilities = _fit_calibrated_model(
        train_dedup_matrix,
        train_dedup_labels,
        [group_key(pair[0], group_field) for pair in train_pairs],
        calibration_dedup_matrix,
        calibration_dedup_labels,
        [group_key(pair[0], group_field) for pair in calibration_pairs],
        seed=seed + 1,
        task="deduplication",
        fold_feature_factory=dedup_fold_features,
        false_negative_cost=dedup_false_negative_cost,
        false_positive_cost=DEDUP_FALSE_POSITIVE_COST,
    )

    classification_predictions = np.asarray(classification_model.classes_)[
        np.argmax(classification_probabilities, axis=1)
    ]
    classification_threshold, classification_curve = _classification_threshold(
        classification_probabilities,
        classification_predictions,
        calibration_class_labels,
        classification_model.classes_,
        max_risk=max_classification_risk,
        min_coverage=min_classification_coverage,
    )
    dedup_threshold, dedup_negative_threshold, dedup_curve = _dedup_threshold(
        dedup_probabilities,
        calibration_dedup_labels,
        dedup_model.classes_,
        max_false_positive_rate=max_dedup_false_positive_rate,
        min_precision=min_dedup_precision,
        min_coverage=min_dedup_coverage,
        max_false_negative_rate=max_dedup_false_negative_rate,
        min_negative_predictive_value=min_dedup_negative_predictive_value,
        false_negative_cost=dedup_false_negative_cost,
    )
    selected_classification_point = next(
        (
            dict(point)
            for point in classification_curve
            if classification_threshold is not None
            and abs(float(point["threshold"]) - classification_threshold) < 1e-12
        ),
        None,
    )
    if selected_classification_point is not None:
        selected_classification_point["confidence_intervals_95"] = {
            "coverage": _wilson_interval(
                int(selected_classification_point["covered"]),
                len(calibration_class_labels),
            ),
            "selective_risk": _wilson_interval(
                int(selected_classification_point["errors"]),
                int(selected_classification_point["covered"]),
            ),
        }
    selected_dedup_point = next(
        (
            dict(point)
            for point in dedup_curve
            if dedup_threshold is not None
            and dedup_negative_threshold is not None
            and abs(float(point["positive_threshold"]) - dedup_threshold) < 1e-12
            and abs(
                float(point["negative_threshold"]) - dedup_negative_threshold
            )
            < 1e-12
        ),
        None,
    )
    if selected_dedup_point is not None:
        selected_dedup_point["confidence_intervals_95"] = {
            "precision": _wilson_interval(
                int(selected_dedup_point["tp"]),
                int(selected_dedup_point["tp"])
                + int(selected_dedup_point["fp"]),
            ),
            "negative_predictive_value": _wilson_interval(
                int(selected_dedup_point["tn"]),
                int(selected_dedup_point["tn"])
                + int(selected_dedup_point["fn"]),
            ),
            "false_positive_rate": _wilson_interval(
                int(selected_dedup_point["fp"]),
                int(selected_dedup_point["negatives"]),
            ),
            "false_negative_rate": _wilson_interval(
                int(selected_dedup_point["fn"]),
                int(selected_dedup_point["positives"]),
            ),
            "coverage": _wilson_interval(
                int(selected_dedup_point["covered"]),
                len(calibration_dedup_labels),
            ),
        }
    thresholds = {
        "classification": classification_threshold,
        "classification_obra": OBRA_AUTOMATIC_MIN_CONFIDENCE,
        "deduplication": dedup_threshold,
        "deduplication_negative": dedup_negative_threshold,
        "deduplication_reference_margin": DEDUP_REFERENCE_MARGIN_MIN,
        "approved": classification_threshold is not None
        and dedup_threshold is not None
        and dedup_negative_threshold is not None,
        "selection_source": "independent_group_cross_fitted_calibration_split",
        "selection_objective": (
            "minimum_weighted_covered_error_then_maximum_coverage_"
            "then_maximum_abstention_margin"
        ),
        "threshold_grid_step": 0.01,
        "approval_scope": "operational_candidate_for_confirmatory_evaluation",
        "approval_uses_point_estimates": True,
        "confidence_intervals_are_descriptive": True,
        "error_costs": {
            "false_negative": dedup_false_negative_cost,
            "false_positive": 1.0,
            "rationale": "false_negative_bypasses_human_duplicate_confirmation",
        },
        "abstention_is_not_triagem_manual": True,
        "reference_selection_safety": {
            "policy": "top2_candidate_margin_abstention_v1",
            "minimum_margin": DEDUP_REFERENCE_MARGIN_MIN,
            "selection_source": (
                "development_20_candidate_pool_error_separation_v1.7"
            ),
            "evidence_artifact": (
                "avaliacao/resultados/"
                "dedup-reference-margin-v1.7.0-20260716.json"
            ),
            "confirmatory_data_used": False,
        },
        "classification_asymmetric_risk": {
            "most_costly_error": "maintenance_as_obra",
            "obra_requires_explicit_evidence": True,
            "obra_minimum_confidence": OBRA_AUTOMATIC_MIN_CONFIDENCE,
        },
    }

    probability_metrics = {
        "classification": _classification_probability_metrics(
            classification_probabilities,
            calibration_class_labels,
            classification_model.classes_,
        ),
        "deduplication": _dedup_probability_metrics(
            dedup_probabilities,
            calibration_dedup_labels,
            dedup_model.classes_,
        ),
    }
    probability_metrics["classification"]["scope"] = (
        "model_only_pre_gate_eligible"
    )
    pipeline_metrics = {
        "classification": _classification_pipeline_metrics(
            calibration_class_all,
            calibration_class,
            classification_probabilities,
            classification_model.classes_,
            classification_threshold,
            OBRA_AUTOMATIC_MIN_CONFIDENCE,
        )
    }
    critical_policy = pipeline_metrics["classification"]["critical_error_policy"]
    thresholds["classification_safety_gate"] = {
        "policy": "obra_asymmetric_safety_gate_v1",
        "critical_error": "maintenance_as_obra",
        "maximum_automatic_errors": 0,
        "observed_automatic_errors": int(critical_policy["automatic_errors"]),
        "approved": int(critical_policy["automatic_errors"]) == 0,
    }
    thresholds["approved"] = bool(
        thresholds["approved"]
        and thresholds["classification_safety_gate"]["approved"]
    )
    selected_operating_points = {
        "classification": selected_classification_point,
        "deduplication": selected_dedup_point,
    }

    feature_schema = {
        "classification": {
            "text_fields": list(TEXT_FIELDS),
            "model_text_fields": ["title", "content", "location"],
            "excluded_weak_field": "category",
            "evaluation_scope": "model_only_pre_gate_eligible",
            "layout": ["tfidf_word_char", "embedding"]
            if embedding_dimension
            else ["tfidf_word_char"],
            "structured_features": [],
            "structured_feature_ablation": (
                "excluded_from_primary_after_v1.2_development_regression"
            ),
        },
        "deduplication": {
            "pair_order": ["current", "reference"],
            "text_fields": list(TEXT_FIELDS),
            "layout": [
                "tfidf_abs_difference",
                "tfidf_elementwise_product",
                "tfidf_cosine",
                *STRUCTURED_PAIR_FEATURES,
                *(
                    [
                        "embedding_abs_difference",
                        "embedding_elementwise_product",
                        "embedding_cosine",
                    ]
                    if embedding_dimension
                    else []
                ),
            ],
        },
    }
    training_metadata = {
        "model_version": MODEL_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "service_version": LOCAL_AI_SERVICE_VERSION,
        "generation_profile": GENERATION_PROFILE,
        "pipeline_source_sha256": pipeline_source_hashes,
        "seed": seed,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_audit": list(source_audit),
        "split_audit": split_audit,
        "leakage_overlap_counts": leakage_audit,
        "train_cases_canonical_sha256": canonical_sha256(list(train_cases)),
        "calibration_cases_canonical_sha256": canonical_sha256(
            list(calibration_cases)
        ),
        "train_group_membership_sha256": canonical_sha256(
            sorted(group_key(case, group_field) for case in train_cases)
        ),
        "calibration_group_membership_sha256": canonical_sha256(
            sorted(group_key(case, group_field) for case in calibration_cases)
        ),
        "train_records": len(train_cases),
        "calibration_records": len(calibration_cases),
        "train_classification": len(train_class),
        "calibration_classification": len(calibration_class),
        "train_classification_full_pipeline": len(train_class_all),
        "calibration_classification_full_pipeline": len(
            calibration_class_all
        ),
        "classification_training_scope": "model_only_pre_gate_eligible",
        "classification_probability_metrics_scope": (
            "model_only_pre_gate_eligible"
        ),
        "classification_pipeline_metrics_scope": (
            "full_pipeline_including_deterministic_paths"
        ),
        "classification_route_counts": {
            "train": dict(
                sorted(
                    Counter(
                        classification_pre_model_path(
                            deterministic_extract(case, 6000)
                        )
                        or "hybrid_model"
                        for case in train_class_all
                    ).items()
                )
            ),
            "calibration": dict(
                sorted(
                    Counter(
                        classification_pre_model_path(
                            deterministic_extract(case, 6000)
                        )
                        or "hybrid_model"
                        for case in calibration_class_all
                    ).items()
                )
            ),
        },
        "structured_feature_ablation": {
            "candidate": "local-hybrid-v1.2.0",
            "status": "REJECTED_DEVELOPMENT_REGRESSION",
            "comparison_split": "same_development_calibration_v1.1_vs_v1.2",
            "v1_1_accuracy": 0.925,
            "v1_2_accuracy": 0.85,
            "v1_1_macro_f1": 0.9154457193292144,
            "v1_2_macro_f1": 0.8332871041007207,
            "v1_1_coverage": 0.8875,
            "v1_2_coverage": 0.70625,
            "confirmatory_data_used": False,
        },
        "train_dedup_pairs": len(train_pairs),
        "calibration_dedup_pairs": len(calibration_pairs),
        "test_data_used": False,
        "primary33_used": False,
        "scientific_result": False,
        "scientifically_validated": False,
        "confirmatory_evaluation_completed": False,
        "operational_pilot_only": True,
        "model_input_sanitization": "sanitize_untrusted_text_v1",
        "hyperparameter_selection": {
            "classification": classification_tuning,
            "deduplication": dedup_tuning,
        },
    }
    bundle = {
        "bundle_version": BUNDLE_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "service_version": LOCAL_AI_SERVICE_VERSION,
        "generation_profile": GENERATION_PROFILE,
        "pipeline_source_sha256": pipeline_source_hashes,
        "classification_model": classification_model,
        "dedup_model": dedup_model,
        "vectorizers": {
            "classification": classification_vectorizer,
            "dedup": dedup_vectorizer,
        },
        "feature_schema": feature_schema,
        "classes": {
            "classification": list(classification_model.classes_),
            "deduplication": list(dedup_model.classes_),
        },
        "thresholds": thresholds,
        "calibration_metrics": probability_metrics,
        "pipeline_metrics": pipeline_metrics,
        "selected_operating_points": selected_operating_points,
        "embedding": {
            "backend": embedding_backend,
            "field": embedding_field if embedding_backend == "precomputed" else None,
            "dimension": embedding_dimension,
            "model_id": embedding_encoder.model_id if embedding_encoder else None,
            "model_revision": embedding_encoder.revision if embedding_encoder else None,
            "model_tree_sha256": embedding_encoder.tree_sha256
            if embedding_encoder
            else None,
            "normalized": bool(embedding_dimension),
            "external_download_performed": False,
        },
        "training_metadata": training_metadata,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / "local_hybrid_bundle.joblib"
    manifest_path = output_dir / "local_hybrid_manifest.json"
    joblib.dump(bundle, bundle_path, compress=3)
    bundle_hash = sha256_file(bundle_path)
    manifest = {
        "schema_version": "1.0.0",
        "model_version": MODEL_VERSION,
        "bundle_version": BUNDLE_VERSION,
        "pipeline": {
            "version": PIPELINE_VERSION,
            "service_version": LOCAL_AI_SERVICE_VERSION,
            "generation_profile": GENERATION_PROFILE,
            "source_sha256": pipeline_source_hashes,
        },
        "status": "CALIBRATED" if thresholds["approved"] else "CALIBRATION_NOT_APPROVED",
        "scientific_result": False,
        "scientifically_validated": False,
        "confirmatory_evaluation_completed": False,
        "evaluation_eligible": bool(thresholds["approved"]),
        "confirmatory_eligible": bool(thresholds["approved"]),
        "candidate_frozen": True,
        "scientific_claim_status": "PENDING_CONFIRMATORY_HOLDOUT",
        "test_data_used": False,
        "primary33_used": False,
        "bundle": {
            "path": bundle_path.name,
            "sha256": bundle_hash,
            "load_contract": "joblib.load(path)",
            "required_keys": [
                "classification_model",
                "dedup_model",
                "vectorizers",
                "feature_schema",
                "classes",
                "thresholds",
                "embedding",
                "training_metadata",
                "pipeline_version",
                "service_version",
                "generation_profile",
                "pipeline_source_sha256",
            ],
        },
        "classes": bundle["classes"],
        "thresholds": thresholds,
        "calibration_curves": {
            "classification": classification_curve,
            "deduplication": dedup_curve,
        },
        "calibration_metrics": probability_metrics,
        "pipeline_metrics": pipeline_metrics,
        "selected_operating_points": selected_operating_points,
        "feature_schema": feature_schema,
        "embedding": bundle["embedding"],
        "training": training_metadata,
        "runtime_versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
        "reproducibility": {
            "training_script_sha256": sha256_file(Path(__file__)),
            "pipeline_source_sha256": pipeline_source_hashes,
            "seed": seed,
            "bundle_sha256": bundle_hash,
            "candidate_frozen_by_content_hash": True,
            "test_or_confirmatory_data_used": False,
        },
        "manifest_payload_sha256": None,
    }
    manifest["manifest_payload_sha256"] = canonical_sha256(manifest)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest, bundle_path, manifest_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Treina candidato local TF-IDF + embeddings opcionais + LogReg calibrada, "
            "sem permitir TESTE/benchmark/primary33 em ajuste."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--dados", type=Path, help="Pool de desenvolvimento a dividir por grupo")
    source.add_argument("--treino", type=Path, help="Split de treino explícito")
    parser.add_argument("--validacao", type=Path, help="Split de calibração explícito")
    parser.add_argument("--saida", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260715)
    parser.add_argument("--validation-fraction", type=float, default=0.25)
    parser.add_argument("--group-field", default="auto")
    parser.add_argument(
        "--embedding-backend",
        choices=("tfidf", "mock", "precomputed", "granite"),
        default="tfidf",
    )
    parser.add_argument("--embedding-field", default="embedding")
    parser.add_argument("--mock-embedding-dimension", type=int, default=16)
    parser.add_argument("--embedding-model-path", type=Path)
    parser.add_argument(
        "--embedding-model-id",
        default="ibm-granite/granite-embedding-97m-multilingual-r2",
    )
    parser.add_argument("--embedding-model-revision", default="")
    parser.add_argument("--embedding-batch-size", type=int, default=8)
    parser.add_argument("--cpu-threads", type=int, default=4)
    parser.add_argument("--risco-classificacao-maximo", type=float, default=0.10)
    parser.add_argument("--cobertura-classificacao-minima", type=float, default=0.60)
    parser.add_argument("--fp-dedup-maximo", type=float, default=0.05)
    parser.add_argument("--fn-dedup-maximo", type=float, default=0.02)
    parser.add_argument("--precisao-dedup-minima", type=float, default=0.90)
    parser.add_argument("--vpn-dedup-minimo", type=float, default=0.98)
    parser.add_argument("--custo-fn-dedup", type=float, default=5.0)
    parser.add_argument("--cobertura-dedup-minima", type=float, default=0.50)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.treino and not args.validacao:
        raise SystemExit("--treino exige --validacao")
    if args.validacao and not args.treino:
        raise SystemExit("--validacao exige --treino")
    source_audit: list[dict[str, Any]] = []
    if args.dados:
        development = load_jsonl(args.dados)
        source_audit.append(validate_source_role(args.dados, development, role="TRAIN"))
        train_cases, calibration_cases, split_audit = grouped_development_split(
            development,
            validation_fraction=args.validation_fraction,
            seed=args.seed,
            group_field=args.group_field,
        )
    else:
        assert args.treino is not None and args.validacao is not None
        train_cases = load_jsonl(args.treino)
        calibration_cases = load_jsonl(args.validacao)
        source_audit.append(validate_source_role(args.treino, train_cases, role="TRAIN"))
        source_audit.append(
            validate_source_role(args.validacao, calibration_cases, role="CALIBRATION")
        )
        assert_no_split_leakage(train_cases, calibration_cases)
        split_audit = {
            "strategy": "explicit_group_disjoint_splits",
            "group_field": args.group_field,
            "train_groups": len({group_key(case, args.group_field) for case in train_cases}),
            "calibration_groups": len(
                {group_key(case, args.group_field) for case in calibration_cases}
            ),
        }
    embedding_encoder: GraniteEmbeddingEncoder | None = None
    if args.embedding_backend == "granite":
        if args.embedding_model_path is None:
            raise SystemExit("--embedding-backend granite exige --embedding-model-path")
        if not args.embedding_model_revision.strip():
            raise SystemExit(
                "--embedding-backend granite exige --embedding-model-revision "
                "para reprodutibilidade"
            )
        embedding_encoder = GraniteEmbeddingEncoder(
            args.embedding_model_path,
            model_id=args.embedding_model_id,
            revision=args.embedding_model_revision,
            batch_size=args.embedding_batch_size,
            cpu_threads=args.cpu_threads,
        )
    manifest, bundle_path, manifest_path = train_bundle(
        train_cases,
        calibration_cases,
        output_dir=args.saida,
        source_audit=source_audit,
        split_audit=split_audit,
        seed=args.seed,
        group_field=args.group_field,
        embedding_backend=args.embedding_backend,
        embedding_field=args.embedding_field,
        mock_embedding_dimension=args.mock_embedding_dimension,
        embedding_encoder=embedding_encoder,
        max_classification_risk=args.risco_classificacao_maximo,
        min_classification_coverage=args.cobertura_classificacao_minima,
        max_dedup_false_positive_rate=args.fp_dedup_maximo,
        max_dedup_false_negative_rate=args.fn_dedup_maximo,
        min_dedup_precision=args.precisao_dedup_minima,
        min_dedup_negative_predictive_value=args.vpn_dedup_minimo,
        dedup_false_negative_cost=args.custo_fn_dedup,
        min_dedup_coverage=args.cobertura_dedup_minima,
    )
    print(f"[OK] Bundle: {bundle_path}")
    print(f"[OK] Manifesto: {manifest_path}")
    print(f"[OK] Status: {manifest['status']}; thresholds={manifest['thresholds']}")
    return 0 if manifest["thresholds"]["approved"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
