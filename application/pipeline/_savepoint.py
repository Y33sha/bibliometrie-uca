"""Context manager `savepoint` pour le pipeline.

Réservé aux modules `application/pipeline/*` qui ont besoin
d'encadrer un traitement unitaire dans un SAVEPOINT (rollback fin
sans abandonner toute la transaction de batch).

Vit dans `application/` plutôt que `infrastructure/db_helpers.py`
parce que la règle DDD `application ⊥ infrastructure` interdit
l'import inverse — et seuls les pipelines en ont l'usage.

Dispatche sur le type du premier argument : curseur psycopg (mode
legacy, exécute SQL `SAVEPOINT … RELEASE`) ou `Connection` SA
(mode cible, délègue à `Connection.begin_nested()`). Le dispatch
disparaîtra quand tous les callers (normalizers + merges) seront SA.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Connection


@contextmanager
def savepoint(
    conn_or_cur: Any,
    name: str,
    *,
    on_rollback_failure: Callable[[], None] | None = None,
) -> Iterator[None]:
    """Context manager autour d'un SAVEPOINT.

    Sortie sans exception → RELEASE / commit.
    Exception dans le bloc → ROLLBACK TO / rollback, puis re-raise.
    Si le rollback échoue (transaction cassée), `on_rollback_failure`
    est appelé (typiquement `conn.rollback`) et l'exception originale
    est re-raise.

    Usage :
        with savepoint(conn_or_cur, "merge_pub"):
            do_work(conn_or_cur)
    """
    if isinstance(conn_or_cur, Connection):
        sp: Any = conn_or_cur.begin_nested()
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
        return

    # Mode psycopg cur.
    conn_or_cur.execute(f"SAVEPOINT {name}")
    try:
        yield
    except Exception:
        try:
            conn_or_cur.execute(f"ROLLBACK TO SAVEPOINT {name}")
        except Exception:
            if on_rollback_failure is not None:
                on_rollback_failure()
        raise
    else:
        conn_or_cur.execute(f"RELEASE SAVEPOINT {name}")
