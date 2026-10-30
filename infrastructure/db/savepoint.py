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

    L'exception d'origine remonte toujours, même si la seconde annulation échoue aussi (connexion perdue).

    Args:
        on_rollback_failure: appelé si l'annulation du SAVEPOINT échoue (transaction cassée) ; en général `conn.rollback`, pour remettre la connexion en état.
    """
    nested: NestedTransaction = conn.begin_nested()
    try:
        yield
    except Exception:
        try:
            nested.rollback()
        except Exception:
            if on_rollback_failure is not None:
                with suppress(Exception):
                    on_rollback_failure()
        raise
    else:
        nested.commit()


def rollback_unless_invalidated(conn: Connection) -> None:
    """Annule la transaction en cours, sauf sur une connexion invalidée.

    Une connexion invalidée (interruption clavier, coupure en pleine requête) a déjà perdu sa transaction côté serveur. Son `rollback()` lèverait `PendingRollbackError`.
    """
    if not conn.invalidated:
        conn.rollback()
