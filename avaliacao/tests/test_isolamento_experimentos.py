from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "avaliacao" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from isolamento_experimentos import exclusive_experiment_window  # noqa: E402


def fake_connection(*, acquired: bool, active: list[dict] | None = None):
    connection = MagicMock()
    cursor = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.return_value = {"pg_try_advisory_lock": acquired}
    cursor.fetchall.return_value = active or []
    return connection, cursor


class IsolationTests(unittest.TestCase):
    def test_lock_is_held_for_the_whole_window_and_released(self) -> None:
        connection, cursor = fake_connection(acquired=True)
        inside = []

        with exclusive_experiment_window(lambda: connection, "TESTE"):
            inside.append(True)

        self.assertEqual(inside, [True])
        sql = "\n".join(str(call.args[0]) for call in cursor.execute.call_args_list)
        self.assertIn("pg_try_advisory_lock", sql)
        self.assertIn("experimentos_avaliacao", sql)
        self.assertIn("pg_advisory_unlock", sql)
        connection.close.assert_called_once()

    def test_busy_lock_fails_before_experiment_body(self) -> None:
        connection, _ = fake_connection(acquired=False)

        with self.assertRaisesRegex(RuntimeError, "janela exclusiva ocupada"):
            with exclusive_experiment_window(lambda: connection, "TESTE"):
                self.fail("corpo não pode executar")

        connection.close.assert_called_once()

    def test_stale_active_experiment_fails_closed_and_unlocks(self) -> None:
        connection, cursor = fake_connection(
            acquired=True,
            active=[{"run_id": "CALQ-STALE", "status": "CALIBRANDO"}],
        )

        with self.assertRaisesRegex(RuntimeError, "CALQ-STALE"):
            with exclusive_experiment_window(lambda: connection, "TESTE"):
                self.fail("corpo não pode executar")

        sql = "\n".join(str(call.args[0]) for call in cursor.execute.call_args_list)
        self.assertIn("pg_advisory_unlock", sql)
        connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
