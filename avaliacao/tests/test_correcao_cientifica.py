from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "avaliacao" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import conferir_gabarito  # noqa: E402
import comparar_baselines  # noqa: E402
import estatistica  # noqa: E402
import validar_rotulos_especialistas as rotulos  # noqa: E402


def make_case(
    case_id: str,
    order: int,
    title: str,
    *,
    episode_id: str = "EP-001",
    expected_dedup: bool = False,
    expected_classification: str = "",
) -> dict:
    return {
        "case_id": case_id,
        "episode_id": episode_id,
        "scenario_id": "CENARIO-001",
        "order_in_group": order,
        "title": title,
        "content": f"Descrição de {title}",
        "location": "Bloco A / Sala 1",
        "expected_dedup": expected_dedup,
        "expected_classification": expected_classification,
    }


def write_dataset(path: Path, cases: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases),
        encoding="utf-8",
    )


def valid_reviewer_profile() -> dict:
    return {
        "versao_instrucoes": "protocolo-teste-v1",
        "avaliadores": [
            {
                "id_anonimo": reviewer_id,
                "area_atuacao": "Manutenção predial",
                "anos_experiencia": 3,
                "treinamento_protocolo": "Concluído",
            }
            for reviewer_id in ("R1", "R2", "R3")
        ],
    }


def fill_sheet(sheet: Path, *, same_reviewer: bool = False) -> None:
    with sheet.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0])

    for row in rows:
        row["revisor_1"] = "R1"
        row["revisor_2"] = "R1" if same_reviewer else "R2"
        if row["etapa"] == "DEDUPLICACAO":
            row["rotulo_revisor_1"] = "NAO_DUPLICADO"
            row["rotulo_revisor_2"] = "NAO_DUPLICADO"
        else:
            row["rotulo_revisor_1"] = "DEMO"
            row["rotulo_revisor_2"] = "DEMO"

    with sheet.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class TestMetricasCientificas(unittest.TestCase):
    def test_f1_is_zero_when_supported_class_is_never_predicted(self) -> None:
        precision, recall, f1 = estatistica._class_metrics(
            ["OBRA", "OBRA", "DEMO"],
            ["DEMO", "SOB_DEMANDA", "DEMO"],
            "OBRA",
        )

        self.assertEqual(precision, 0.0)
        self.assertEqual(recall, 0.0)
        self.assertEqual(f1, 0.0)

    def test_binary_f1_is_zero_with_supported_positive_never_predicted(self) -> None:
        metrics = comparar_baselines.binary_metrics(
            ["DUPLICADO", "NAO_DUPLICADO"],
            ["NAO_DUPLICADO", "NAO_DUPLICADO"],
        )

        self.assertEqual(metrics["precision"], 0.0)
        self.assertEqual(metrics["recall"], 0.0)
        self.assertEqual(metrics["f1"], 0.0)

    def test_dedup_primary_selects_only_later_challenge_tickets(self) -> None:
        anchor = make_case("C1", 1, "Âncora")
        anchor["dimension"] = "DEDUPLICACAO"
        challenge = make_case("C2", 2, "Desafio", expected_dedup=True)
        challenge["dimension"] = "DEDUPLICACAO"
        classification_only = make_case("C3", 1, "Classificação")
        classification_only["dimension"] = "CLASSIFICACAO"
        predictions = {
            ("C1", "DEDUPLICACAO"): "NAO_DUPLICADO",
            ("C2", "DEDUPLICACAO"): "DUPLICADO",
            ("C3", "DEDUPLICACAO"): "NAO_DUPLICADO",
        }

        gold, predicted, groups = comparar_baselines.paired_vectors(
            [anchor, challenge, classification_only],
            predictions,
            "DEDUPLICACAO",
            challenge_only=True,
        )

        self.assertEqual(gold, ["DUPLICADO"])
        self.assertEqual(predicted, ["DUPLICADO"])
        self.assertEqual(groups, [challenge["episode_id"]])

    def test_paired_bootstrap_resamples_whole_episodes(self) -> None:
        class FirstEpisodeRandom:
            choices: list[tuple[str, ...]] = []

            def __init__(self, seed: int) -> None:
                self.seed = seed

            def choice(self, values: list[str]) -> str:
                self.__class__.choices.append(tuple(values))
                return values[0]

        gold = ["A", "B", "A"]
        predicted_a = ["A", "B", "B"]
        predicted_b = ["B", "A", "A"]
        groups = ["episodio-1", "episodio-1", "episodio-2"]

        with patch.object(estatistica.random, "Random", FirstEpisodeRandom):
            result = estatistica.bootstrap_paired_difference(
                gold,
                predicted_a,
                predicted_b,
                groups,
                labels=["A", "B"],
                task="CLASSIFICACAO",
                replications=1,
                seed=42,
            )

        accuracy = result["diferenca_a_menos_b"]["accuracy"]
        self.assertEqual(
            FirstEpisodeRandom.choices,
            [("episodio-1", "episodio-2")] * 2,
        )
        self.assertAlmostEqual(accuracy["estimate"], 1 / 3)
        self.assertEqual(accuracy["lower"], 1.0)
        self.assertEqual(accuracy["upper"], 1.0)
        self.assertEqual(result["unidade_reamostragem"], "episode_id")


class TestRotulagemCega(unittest.TestCase):
    def test_blind_export_contains_only_prior_episode_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            dataset = directory / "dataset.jsonl"
            sheet = directory / "rotulagem.csv"
            write_dataset(
                dataset,
                [
                    make_case("C3", 3, "Chamado futuro"),
                    make_case("C1", 1, "Chamado inicial"),
                    make_case("C2", 2, "Chamado atual"),
                ],
            )

            rotulos.export(dataset, sheet)

            with sheet.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
                fieldnames = set(reader.fieldnames or [])

            self.assertNotIn("expected_dedup", fieldnames)
            self.assertNotIn("expected_classification", fieldnames)
            self.assertNotIn("gabarito_sintetico", fieldnames)

            current = next(row for row in rows if row["titulo"] == "Chamado atual")
            current_context = json.loads(current["contexto_anterior_episodio"])
            self.assertEqual(
                [item["titulo"] for item in current_context],
                ["Chamado inicial"],
            )
            self.assertNotIn("Chamado futuro", current["contexto_anterior_episodio"])

            initial = next(row for row in rows if row["titulo"] == "Chamado inicial")
            self.assertEqual(json.loads(initial["contexto_anterior_episodio"]), [])

    def test_incorporate_rejects_same_reviewer_for_both_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            dataset = directory / "dataset.jsonl"
            sheet = directory / "rotulagem.csv"
            profile = directory / "perfil.json"
            output = directory / "validacao.json"
            write_dataset(dataset, [make_case("C1", 1, "Chamado")])
            rotulos.export(dataset, sheet)
            fill_sheet(sheet, same_reviewer=True)
            profile.write_text(
                json.dumps(valid_reviewer_profile(), ensure_ascii=False),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "revisores devem ser distintos"):
                rotulos.incorporate(dataset, sheet, output, profile)
            self.assertFalse(output.exists())

    def test_profile_rejects_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile_path = Path(temporary) / "perfil.json"
            profile = valid_reviewer_profile()
            profile["avaliadores"][1]["area_atuacao"] = "PREENCHER"
            profile_path.write_text(
                json.dumps(profile, ensure_ascii=False), encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "placeholders"):
                rotulos.load_reviewer_profile(profile_path)

    def test_incorporate_rejects_incomplete_sheet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            dataset = directory / "dataset.jsonl"
            sheet = directory / "rotulagem.csv"
            profile = directory / "perfil.json"
            output = directory / "validacao.json"
            write_dataset(
                dataset,
                [
                    make_case("C1", 1, "Primeiro"),
                    make_case("C2", 2, "Segundo"),
                ],
            )
            rotulos.export(dataset, sheet)
            profile.write_text(
                json.dumps(valid_reviewer_profile(), ensure_ascii=False),
                encoding="utf-8",
            )

            with sheet.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
                fieldnames = list(rows[0])
            with sheet.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow(rows[0])

            with self.assertRaisesRegex(ValueError, "Planilha incompleta"):
                rotulos.incorporate(dataset, sheet, output, profile)
            self.assertFalse(output.exists())


class TestCompletionGates(unittest.TestCase):
    def test_non_benchmark_does_not_require_human_audit_gate(self) -> None:
        experiment = {
            "split": "CALIBRACAO",
            "rotulos_validados": True,
            "protocolo_rotulagem_validado": True,
            "auditoria_humana_concluida": False,
        }

        gates = conferir_gabarito.completion_gates(experiment)

        self.assertTrue(all(gates.values()))
        conferir_gabarito.require_completion_gates(experiment)

        reported = conferir_gabarito.reported_gate_status(experiment)
        self.assertFalse(reported["auditoria_humana_concluida"])
        self.assertFalse(reported["auditoria_humana_exigida_nesta_fase"])
        self.assertTrue(reported["gates_obrigatorios_satisfeitos"])

    def test_benchmark_requires_human_audit(self) -> None:
        experiment = {
            "split": "TESTE",
            "rotulos_validados": True,
            "protocolo_rotulagem_validado": True,
            "auditoria_humana_concluida": False,
        }

        with self.assertRaisesRegex(RuntimeError, "auditoria_humana_concluida"):
            conferir_gabarito.require_completion_gates(experiment)

    def test_missing_label_and_protocol_gates_prevent_completion(self) -> None:
        experiment = {
            "split": "BENCHMARK",
            "rotulos_validados": False,
            "protocolo_rotulagem_validado": False,
            "auditoria_humana_concluida": True,
        }

        with self.assertRaises(RuntimeError) as raised:
            conferir_gabarito.require_completion_gates(experiment)

        message = str(raised.exception)
        self.assertIn("rotulos_validados", message)
        self.assertIn("protocolo_rotulagem_validado", message)


if __name__ == "__main__":
    unittest.main()
