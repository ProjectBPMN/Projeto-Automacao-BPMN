from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ArtifactError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LoadedArtifact:
    task: str
    version: str
    scientific_status: str
    path: Path
    content: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LoadedHybridBundle:
    version: str
    path: Path
    manifest_path: Path
    manifest: dict[str, Any]
    content: dict[str, Any]


class ArtifactStore:
    def __init__(self, artifact_dir: Path, hybrid_manifest_path: str = "") -> None:
        self.artifact_dir = artifact_dir.resolve()
        self.manifest: dict[str, Any] = {}
        self._by_task: dict[str, LoadedArtifact] = {}
        self.hybrid: LoadedHybridBundle | None = None
        self.hybrid_error: str | None = None
        self.hybrid_declared = False
        self._load()
        self._load_hybrid(hybrid_manifest_path)

    def _load(self) -> None:
        manifest_path = self.artifact_dir / "manifest.json"
        try:
            self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactError(f"Manifesto de artefatos inválido: {exc}") from exc
        if self.manifest.get("manifest_schema") != "local-ai-artifact-manifest-v1":
            raise ArtifactError("Versão de manifesto incompatível")
        for entry in self.manifest.get("artifacts", []):
            task = str(entry.get("task", ""))
            relative = Path(str(entry.get("path", "")))
            path = (self.artifact_dir / relative).resolve()
            try:
                path.relative_to(self.artifact_dir)
            except ValueError as exc:
                raise ArtifactError("Caminho de artefato fora do diretório permitido") from exc
            try:
                raw = path.read_bytes()
            except OSError as exc:
                raise ArtifactError(f"Artefato ausente: {path.name}") from exc
            expected = str(entry.get("sha256", "")).lower()
            actual = hashlib.sha256(raw).hexdigest()
            if not expected or actual != expected:
                raise ArtifactError(f"Checksum inválido para {path.name}")
            try:
                content = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ArtifactError(f"JSON inválido em {path.name}") from exc
            if content.get("artifact_schema") != "local-ai-calibrated-linear-v1":
                raise ArtifactError(f"Esquema incompatível em {path.name}")
            loaded = LoadedArtifact(
                task=task,
                version=str(entry.get("version", "")),
                scientific_status=str(entry.get("scientific_status", "unknown")),
                path=path,
                content=content,
            )
            self._by_task[task] = loaded
        for required in ("deduplication", "classification"):
            if required not in self._by_task:
                raise ArtifactError(f"Artefato obrigatório ausente: {required}")

    def get(self, task: str) -> LoadedArtifact:
        try:
            return self._by_task[task]
        except KeyError as exc:
            raise ArtifactError(f"Artefato desconhecido: {task}") from exc

    def _load_hybrid(self, configured_path: str) -> None:
        manifest_path = (
            Path(configured_path).expanduser().resolve()
            if configured_path
            else (self.artifact_dir / "local_hybrid_manifest.json").resolve()
        )
        if not manifest_path.exists():
            return
        self.hybrid_declared = True
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise ArtifactError("Manifesto híbrido deve ser um objeto")
            payload_checksum = str(
                manifest.get("manifest_payload_sha256") or ""
            ).lower()
            if payload_checksum:
                checksum_payload = json.loads(json.dumps(manifest))
                checksum_payload["manifest_payload_sha256"] = None
                canonical = json.dumps(
                    checksum_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                actual_payload_checksum = hashlib.sha256(canonical).hexdigest()
                if not hmac.compare_digest(
                    payload_checksum, actual_payload_checksum
                ):
                    raise ArtifactError("Checksum do manifesto híbrido inválido")
            bundle_entry = manifest.get("bundle", {})
            if not isinstance(bundle_entry, dict):
                bundle_entry = {}
            bundle_name = str(
                manifest.get("bundle_file")
                or manifest.get("bundle_path")
                or manifest.get("artifact")
                or bundle_entry.get("path")
                or "local_hybrid_bundle.joblib"
            )
            bundle_path = (manifest_path.parent / bundle_name).resolve()
            try:
                bundle_path.relative_to(manifest_path.parent.resolve())
            except ValueError as exc:
                raise ArtifactError("Bundle híbrido fora do diretório do manifesto") from exc
            raw = bundle_path.read_bytes()
            expected = str(
                manifest.get("sha256")
                or manifest.get("bundle_sha256")
                or manifest.get("checksum_sha256")
                or bundle_entry.get("sha256")
                or ""
            ).lower()
            actual = hashlib.sha256(raw).hexdigest()
            if not expected or not hmac.compare_digest(expected, actual):
                raise ArtifactError("Checksum do bundle híbrido inválido")
            if importlib.util.find_spec("joblib") is None:
                raise ArtifactError("joblib ausente; instale requirements-hybrid.txt")
            import joblib  # type: ignore

            bundle = joblib.load(bundle_path)
            if not isinstance(bundle, dict):
                raise ArtifactError("Bundle joblib deve conter um dicionário")
            required = manifest.get(
                "required_keys",
                bundle_entry.get("required_keys")
                or [
                    "bundle_version",
                    "classification_model",
                    "dedup_model",
                    "vectorizers",
                    "feature_schema",
                    "classes",
                    "thresholds",
                    "embedding",
                    "training_metadata",
                ],
            )
            if not isinstance(required, list):
                raise ArtifactError("required_keys do manifesto híbrido é inválido")
            missing = [key for key in required if key not in bundle]
            if missing:
                raise ArtifactError("Bundle híbrido sem chaves: " + ", ".join(missing))
            vectorizers = bundle.get("vectorizers")
            if not isinstance(vectorizers, dict) or not {"classification", "dedup"} <= set(vectorizers):
                raise ArtifactError("Bundle híbrido sem vectorizers classification/dedup")
            thresholds = bundle.get("thresholds")
            if not isinstance(thresholds, dict) or not {"classification", "deduplication"} <= set(thresholds):
                raise ArtifactError("Bundle híbrido sem thresholds separados")
            self.hybrid = LoadedHybridBundle(
                version=str(bundle.get("bundle_version", "unknown")),
                path=bundle_path,
                manifest_path=manifest_path,
                manifest=manifest,
                content=bundle,
            )
        except Exception as exc:
            self.hybrid_error = str(exc)

    @property
    def scientifically_ready(self) -> bool:
        if self.hybrid_declared:
            if self.hybrid is None:
                return False
            metadata = self.hybrid.content.get("training_metadata", {})
            thresholds = self.hybrid.content.get("thresholds", {})
            return bool(
                thresholds.get("approved") is True
                and metadata.get("scientifically_validated") is True
                and metadata.get("test_data_used") is False
                and metadata.get("primary33_used") is False
            )
        return all(
            artifact.scientific_status == "trained_calibrated_validated"
            for artifact in self._by_task.values()
        )

    @property
    def candidate_evaluation_eligible(self) -> bool:
        """Indica que o bundle congelado pode entrar no holdout confirmatório.

        Esta propriedade deliberadamente não equivale a ``scientifically_ready``:
        um candidato calibrado precisa ser medido no conjunto confirmatório antes
        de qualquer alegação de validação científica.
        """
        if self.hybrid is None:
            return False
        manifest = self.hybrid.manifest
        metadata = self.hybrid.content.get("training_metadata", {})
        thresholds = self.hybrid.content.get("thresholds", {})
        return bool(
            thresholds.get("approved") is True
            and manifest.get("candidate_frozen") is True
            and manifest.get("evaluation_eligible") is True
            and manifest.get("test_data_used") is False
            and manifest.get("primary33_used") is False
            and metadata.get("test_data_used") is False
            and metadata.get("primary33_used") is False
        )

    def summary(self) -> dict[str, Any]:
        return {
            "manifest_version": self.manifest.get("manifest_version"),
            "scientifically_ready": self.scientifically_ready,
            "candidate_evaluation_eligible": self.candidate_evaluation_eligible,
            "artifacts": {
                task: {
                    "version": artifact.version,
                    "scientific_status": artifact.scientific_status,
                    "file": artifact.path.name,
                }
                for task, artifact in self._by_task.items()
            },
            "hybrid_bundle": (
                {
                    "loaded": True,
                    "version": self.hybrid.version,
                    "file": self.hybrid.path.name,
                    "manifest": self.hybrid.manifest_path.name,
                    "candidate_frozen": self.hybrid.manifest.get("candidate_frozen") is True,
                    "evaluation_eligible": self.hybrid.manifest.get("evaluation_eligible") is True,
                    "scientifically_validated": self.hybrid.manifest.get("scientifically_validated") is True,
                    "scientific_result": self.hybrid.manifest.get("scientific_result") is True,
                    "test_data_used": self.hybrid.manifest.get("test_data_used"),
                    "primary33_used": self.hybrid.manifest.get("primary33_used"),
                }
                if self.hybrid is not None
                else {
                    "loaded": False,
                    "declared": self.hybrid_declared,
                    "error": self.hybrid_error,
                }
            ),
        }
