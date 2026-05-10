"""Context manager `savepoint` pour le pipeline.

Réservé aux modules `application/pipeline/*` qui ont besoin
d'encadrer un traitement unitaire dans un SAVEPOINT (rollback fin
sans abandonner toute la transaction de batch).

Vit dans `application/` plutôt que `infrastructure/db_helpers.py`
parce que la règle DDD `application ⊥ infrastructure` interdit
l'import inverse — et seuls les pipelines en ont l'usage.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Connection


@contextmanager
def savepoint(
    conn: Connection,
    name: str,
    *,
    on_rollback_failure: Callable[[], None] | None = None,
) -> Iterator[None]:
    """Context manager autour d'un SAVEPOINT SQLAlchemy.

    Délégué à `Connection.begin_nested()`. Le paramètre `name` est
    conservé pour faciliter le tracing (SA gère la nomenclature interne).

    Si le rollback du SAVEPOINT échoue (transaction cassée),
    `on_rollback_failure` est appelé (typiquement `conn.rollback`)
    pour permettre au caller de récupérer un état utilisable, et
    l'exception originale est re-raise.

    Usage :
        with savepoint(conn, "merge_pub"):
            do_work(conn)
    """
    sp: Any = conn.begin_nested()
    try:
        yield
    except Exception:
        try:
            sp.rollback()
        except Exception:
            if on_rollback_failure is not None:
                on_rollback_failure()
        raise
    else:
        sp.commit()
