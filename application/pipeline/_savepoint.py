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


@contextmanager
def savepoint(
    cur: Any,
    name: str,
    *,
    on_rollback_failure: Callable[[], None] | None = None,
) -> Iterator[None]:
    """Context manager autour d'un SAVEPOINT psycopg.

    Sortie sans exception → `RELEASE SAVEPOINT`.
    Exception dans le bloc → `ROLLBACK TO SAVEPOINT`, puis re-raise.
    Si le ROLLBACK TO SAVEPOINT échoue (transaction cassée),
    `on_rollback_failure` est appelé (typiquement `conn.rollback`)
    pour permettre au caller de récupérer un état utilisable, et
    l'exception originale est re-raise.

    Usage :
        with savepoint(cur, "merge_pub"):
            do_work(cur)
    """
    cur.execute(f"SAVEPOINT {name}")
    try:
        yield
    except Exception:
        try:
            cur.execute(f"ROLLBACK TO SAVEPOINT {name}")
        except Exception:
            if on_rollback_failure is not None:
                on_rollback_failure()
        raise
    else:
        cur.execute(f"RELEASE SAVEPOINT {name}")
