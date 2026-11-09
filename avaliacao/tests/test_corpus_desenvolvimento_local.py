from __future__ import annotations

import json
import sys
import tempfile
import unittest
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "avaliacao" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import gerar_corpus_desenvolvimento_local as corpus  # noqa: E402
import treinar_modelo_local as local_training  # noqa: E402


DATASET = ROOT / "avaliacao" / "datasets" / "desenvolvimento_local_v1.jsonl"
MANIFEST = (
    ROOT / "avaliacao" / "datasets" / "desenvolvimento_local_v1_manifest.json"
)
REFERENCE = ROOT / "avaliacao" / "datasets" / "corpus_v3_teste.jsonl"


class DevelopmentCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records = corpus.load_jsonl(DATASET)
        cls.reference = corpus.load_jsonl(REFERENCE)
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_committed_artifact_is_deterministic_and_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "development.jsonl"
            manifest = Path(directory) / "development_manifest.json"
            regenerated, regenerated_manifest = corpus.generate(
                output, manifest, REFERENCE
            )
            self.assertEqual(len(regenerated), 1360)
            self.assertEqual(output.read_bytes(), DATASET.read_bytes())
            self.assertEqual(
                regenerated_manifest["files"]["jsonl"]["sha256"],
                self.manifest["files"]["jsonl"]["sha256"],
            )

    def test_classification_is_balanced_by_independent_core(self) -> None:
        rows = [r for r in self.records if r["dimension"] == "CLASSIFICACAO"]
        by_class = Counter(r["expected_classification"] for r in rows)
        self.assertEqual(
            by_class,
            Counter(
                {
                    "OBRA": 160,
                    "DEMO": 160,
                    "SOB_DEMANDA": 160,
                    "TRIAGEM_MANUAL": 160,
                }
            ),
        )
        for label in corpus.CLASSES:
            selected = [r for r in rows if r["expected_classification"] == label]
            scenarios = Counter(r["scenario_id"] for r in selected)
            self.assertEqual(len(scenarios), 32)
            self.assertTrue(all(count == 5 for count in scenarios.values()))
            cores = {r["narrative_core_sha256"] for r in selected}
            self.assertEqual(len(cores), 32)

    def test_dedup_has_balanced_episodes_and_required_hard_cases(self) -> None:
        rows = [r for r in self.records if r["dimension"] == "DEDUPLICACAO"]
        episodes: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            episodes[row["episode_id"]].append(row)
        self.assertEqual(len(episodes), 120)
        labels: Counter[str] = Counter()
        family_episodes: Counter[str] = Counter()
        for members in episodes.values():
            ordered = sorted(members, key=lambda row: row["order_in_episode"])
            self.assertEqual(len(ordered), 6)
            anchor = ordered[0]
            self.assertEqual(anchor["pair_role"], "ANCHOR")
            self.assertIsNone(anchor["expected_dedup"])
            family_episodes[anchor["dedup_family"]] += 1
            for challenge in ordered[1:]:
                self.assertEqual(challenge["reference_case_id"], anchor["case_id"])
                labels[
                    "DUPLICADO"
                    if challenge["expected_dedup"] is True
                    else "NAO_DUPLICADO"
                ] += 1
        self.assertEqual(labels, Counter({"DUPLICADO": 300, "NAO_DUPLICADO": 300}))
        self.assertEqual(
            set(family_episodes),
            {*corpus.POSITIVE_DEDUP_FAMILIES, *corpus.NEGATIVE_DEDUP_FAMILIES},
        )
        self.assertTrue(all(count == 10 for count in family_episodes.values()))
        for required in (
            "different_asset_same_room",
            "different_symptom_same_asset",
            "same_issue_different_location",
            "resolved_then_new_recurrence",
            "missing_location_without_evidence",
            "prompt_injection_hard_negative",
            "unresolved_recurrence",
        ):
            self.assertIn(required, family_episodes)

    def test_no_text_scenario_template_or_core_leaks_from_test_corpus(self) -> None:
        reference = corpus.reference_identity(self.reference)
        current = {
            field: {str(record.get(field, "") or "") for record in self.records}
            for field in reference
        }
        for field in reference:
            self.assertFalse((current[field] - {""}) & reference[field], field)
        self.assertEqual(len({r["visible_text_sha256"] for r in self.records}), 1360)
        self.assertTrue(all(r["scenario_id"].startswith("DEV_") for r in self.records))
        self.assertNotIn("SIGMU", json.dumps(self.records, ensure_ascii=False).upper())

    def test_manifest_blocks_confirmatory_use_and_hashes_every_source(self) -> None:
        manifest = self.manifest
        self.assertEqual(manifest["split"], "DESENVOLVIMENTO")
        self.assertTrue(manifest["synthetic"])
        self.assertTrue(manifest["pilot_only"])
        self.assertFalse(manifest["confirmatory_eligible"])
        self.assertTrue(manifest["confirmatory_block"]["blocked"])
        self.assertEqual(
            manifest["license"]["id"], "USO_INTERNO_ACADEMICO_IF_SUDESTE_MG"
        )
        self.assertEqual(
            manifest["files"]["jsonl"]["sha256"], corpus.sha256_file(DATASET)
        )
        self.assertEqual(
            manifest["files"]["generator"]["sha256"],
            corpus.sha256_file(Path(corpus.__file__)),
        )
        self.assertEqual(
            manifest["files"]["anti_leakage_reference"]["sha256"],
            corpus.sha256_file(REFERENCE),
        )
        self.assertFalse(manifest["provenance"]["sigmu_used"])
        self.assertFalse(
            manifest["provenance"]["reserved_evaluation_corpus_used_for_training"]
        )
        for key in (
            "visible_text_hash_overlap",
            "scenario_id_overlap",
            "template_family_overlap",
            "narrative_core_hash_overlap",
        ):
            self.assertEqual(manifest["counts"][key], 0)

    def test_naturalistic_noise_and_wrong_categories_are_auditable(self) -> None:
        contents = "\n".join(r["content"] for r in self.records).casefold()
        self.assertIn("qdo", contents)
        self.assertIn("p/", contents)
        self.assertIn("pfvr", contents)
        self.assertIn("verficar", contents)
        wrong = sum(
            r["category_intentionally_incorrect"] is True for r in self.records
        )
        self.assertGreaterEqual(wrong, 136)
        self.assertLessEqual(wrong, 340)
        self.assertTrue(any(not r["location"] for r in self.records))
        self.assertTrue(
            all(
                r["split"] == "DESENVOLVIMENTO"
                and r["synthetic"] is True
                and r["pilot_only"] is True
                and r["confirmatory_eligible"] is False
                for r in self.records
            )
        )

    def test_each_classification_core_contains_a_concise_realization(self) -> None:
        concise = [
            row
            for row in self.records
            if row["dimension"] == "CLASSIFICACAO"
            and row["surface_realization"] == "DEV_R02"
        ]
        self.assertEqual(len(concise), 128)
        self.assertTrue(all(len(row["content"]) <= 140 for row in concise))
        self.assertTrue(all("Registro feito em" not in row["content"] for row in concise))

    def test_grouped_development_split_is_accepted_without_leakage(self) -> None:
        audit = local_training.validate_source_role(
            DATASET, self.records, role="TRAIN"
        )
        self.assertEqual(audit["splits"], ["DESENVOLVIMENTO"])
        train, calibration, split = local_training.grouped_development_split(
            self.records,
            validation_fraction=0.2,
            seed=corpus.SEED,
            group_field="scenario_id",
        )
        self.assertTrue(train)
        self.assertTrue(calibration)
        self.assertEqual(split["group_field"], "scenario_id")
        train_groups = {r["scenario_id"] for r in train}
        calibration_groups = {r["scenario_id"] for r in calibration}
        self.assertFalse(train_groups & calibration_groups)
        local_training.validate_labels(train, "treino")
        local_training.validate_labels(calibration, "calibração")


if __name__ == "__main__":
    unittest.main()
