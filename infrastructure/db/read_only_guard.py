"""Garde-fou d'exécution : aucune connexion en écriture pendant une requête de lecture.

Une requête de lecture ouvre ses connexions par la composition root de l'API, en lecture seule. Une connexion ouverte par un autre chemin, en remontant à l'engine depuis une connexion reçue, pourrait écrire. Le garde-fou l'arrête à sa première instruction. Ni le contrat d'architecture ni l'analyse statique ne ferment ce chemin.

Un middleware de l'API déclare la requête de lecture par `read_request()`. Hors de cette déclaration, le garde-fou laisse tout passer : le pipeline et les scripts en ligne de commande écrivent.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import Connection, Engine, event

_read_request: ContextVar[bool] = ContextVar("read_request", default=False)


@contextmanager
def read_request() -> Iterator[None]:
    """Déclare le bloc au service d'une requête de lecture.

    La déclaration suit le contexte d'exécution. Elle vaut pour le thread de la route, et pour les threads démarrés par une lecture parallélisée avec une copie du contexte.
    """
    token = _read_request.set(True)
    try:
        yield
    finally:
        _read_request.reset(token)


def _refuse_writable_connection(
    conn: Connection,
    cursor: object,
    statement: str,
    parameters: object,
    context: object,
    executemany: bool,
) -> None:
    """Refuse le statement émis, pendant une requête de lecture, sur une connexion pouvant écrire."""
    if not _read_request.get():
        return
    if conn.get_execution_options().get("postgresql_readonly"):
        return
    raise RuntimeError(
        "Requête de lecture servie par une connexion ouverte hors de la composition root, "
        "qui porte donc le droit d'écrire. Les connexions supplémentaires d'une lecture "
        f"s'obtiennent par la fabrique qu'elle reçoit. Statement refusé : {statement[:200]}"
    )


def install_read_only_guard(engine: Engine) -> None:
    """Attache le contrôle à toutes les connexions de l'engine."""
    event.listen(engine, "before_cursor_execute", _refuse_writable_connection)
