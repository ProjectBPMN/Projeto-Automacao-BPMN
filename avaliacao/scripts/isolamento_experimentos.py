from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Iterator


EXPERIMENT_LOCK_KEY = 9062028
ACTIVE_STATUSES = ("CALIBRANDO", "EXECUTANDO")


def _first_value(row: Any) -> Any:
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


@contextmanager
def exclusive_experiment_window(
    connect_pg: Callable[[], Any],
    owner: str,
) -> Iterator[None]:
    """Serialize integration experiments that mutate the shared GLPI/n8n stack."""
    connection = connect_pg()
    acquired = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", (EXPERIMENT_LOCK_KEY,))
            acquired = bool(_first_value(cursor.fetchone()))
            if not acquired:
                raise RuntimeError(
                    "Outro experimento de integração mantém a janela exclusiva ocupada; "
                    f"{owner} não foi iniciado."
                )
            cursor.execute(
                """
                SELECT run_id,status
                FROM experimentos_avaliacao
                WHERE status=ANY(%s)
                ORDER BY criado_em DESC
                """,
                (list(ACTIVE_STATUSES),),
            )
            active = [dict(row) for row in cursor.fetchall()]
            if active:
                labels = ", ".join(
                    f"{row['run_id']} ({row['status']})" for row in active
                )
                raise RuntimeError(
                    "Existem experimentos ativos ou interrompidos sem encerramento: "
                    + labels
                )
        connection.commit()
        yield
    finally:
        if acquired:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_unlock(%s)", (EXPERIMENT_LOCK_KEY,)
                    )
                connection.commit()
            except Exception:
                pass
        connection.close()


def serialized_experiment(connect_pg: Callable[[], Any], owner: str):
    """Decorator form used by command-line experiment entrypoints."""

    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with exclusive_experiment_window(connect_pg, owner):
                return function(*args, **kwargs)

        return wrapped

    return decorate
