"""Context manager `savepoint` pour le pipeline.

Réservé aux modules `application/pipeline/*` qui ont besoin d'encadrer un traitement unitaire dans un SAVEPOINT (rollback fin sans abandonner toute la transaction de batch).

Vit dans `application/` plutôt que `infrastructure/db_helpers.py` parce que la règle DDD `application ⊥ infrastructure` interdit l'import inverse — et seuls les pipelines en ont l'usage.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress

from sqlalchemy import Connection, NestedTransaction


@contextmanager
def savepoint(
    conn: Connection,
    *,
    on_rollback_failure: Callable[[], None] | None = None,
) -> Iterator[None]:
    """Context manager autour d'un SAVEPOINT SQLAlchemy (`Connection.begin_nested()`).

    Si le rollback du SAVEPOINT échoue (transaction cassée), `on_rollback_failure` est appelé (typiquement `conn.rollback`) pour permettre au caller de récupérer un état utilisable. L'exception originale est re-raise, même si ce second rollback échoue aussi (connexion perdue).

    Usage :
        with savepoint(conn):
            do_work(conn)
    """
    sp: NestedTransaction = conn.begin_nested()
    try:
        yield
    except Exception:
        try:
            sp.rollback()
        except Exception:
            if on_rollback_failure is not None:
                with suppress(Exception):
                    on_rollback_failure()
        raise
    else:
        sp.commit()


def rollback_unless_invalidated(conn: Connection) -> None:
    """Annule la transaction en cours. Une connexion invalidée (interruption clavier ou coupure en pleine requête) a déjà perdu sa transaction côté serveur : son `rollback()` lèverait `PendingRollbackError`."""
    if not conn.invalidated:
        conn.rollback()
