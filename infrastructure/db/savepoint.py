"""Context manager `savepoint` : encadre un traitement unitaire dans un SAVEPOINT. Une erreur annule ce traitement sans abandonner la transaction du lot."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress

from sqlalchemy import Connection, NestedTransaction


@contextmanager
def savepoint(
    conn: Connection,
    *,
    on_rollback_failure: Callable[[], None] | None = None,
) -> Iterator[None]:
    """Encadre un traitement dans un SAVEPOINT (`Connection.begin_nested()`).

    Si l'annulation du SAVEPOINT échoue (transaction cassée), `on_rollback_failure`, en général `conn.rollback`, rend la connexion utilisable. L'exception d'origine remonte, même si cette seconde annulation échoue aussi (connexion perdue).
    """
    source_record: NestedTransaction = conn.begin_nested()
    try:
        yield
    except Exception:
        try:
            source_record.rollback()
        except Exception:
            if on_rollback_failure is not None:
                with suppress(Exception):
                    on_rollback_failure()
        raise
    else:
        source_record.commit()


def rollback_unless_invalidated(conn: Connection) -> None:
    """Annule la transaction en cours. Une connexion invalidée (interruption clavier ou coupure en pleine requête) a déjà perdu sa transaction côté serveur : son `rollback()` lèverait `PendingRollbackError`."""
    if not conn.invalidated:
        conn.rollback()
