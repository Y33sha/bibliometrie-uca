"""Helpers pour l'accès aux rows psycopg3, compatibles tuple et dict_row."""

from contextlib import asynccontextmanager, contextmanager
from typing import Any

from psycopg.rows import class_row


def rows_as_dicts(cur: Any) -> list[dict[str, Any]]:
    """`cur.fetchall()` mais garantit des dicts.

    Supporte les curseurs tuple (remappés via `cur.description`) et les
    curseurs dict_row (déjà dict-like, juste copiés en dict standard).
    """
    rows = cur.fetchall()
    if not rows:
        return []
    if isinstance(rows[0], dict):
        return [dict(r) for r in rows]
    columns = [desc[0] for desc in cur.description]
    return [dict(zip(columns, r, strict=True)) for r in rows]


def row_val(row: Any, index_or_key: Any, default: Any = None) -> Any:
    """Extrait une valeur d'une row psycopg3, quel que soit le type de curseur.

    Supporte les tuples (accès par index) et les rows dict (accès par clé).
    Avec un index entier, tente d'abord l'accès par position, puis par
    position dans les valeurs du dict si c'est une row dict.
    """
    if row is None:
        return default
    try:
        return row[index_or_key]
    except (KeyError, IndexError, TypeError):
        if isinstance(index_or_key, int):
            try:
                return list(row.values())[index_or_key]
            except (AttributeError, IndexError):
                pass
        return default


@contextmanager
def row_as(cur: Any, cls: type) -> Any:
    """Sur un curseur sync, bascule `row_factory` sur `class_row(cls)` le temps
    d'un bloc. Restaure la factory précédente en sortie.

    Usage :
        with row_as(self._cur, PubByDoi) as cur:
            cur.execute("SELECT id, doc_type, title_normalized FROM ...")
            return cur.fetchone()
    """
    old = cur.row_factory
    cur.row_factory = class_row(cls)
    try:
        yield cur
    finally:
        cur.row_factory = old


@asynccontextmanager
async def async_row_as(cur: Any, cls: type) -> Any:
    """Variante async de `row_as` pour les curseurs `psycopg.AsyncCursor`."""
    old = cur.row_factory
    cur.row_factory = class_row(cls)
    try:
        yield cur
    finally:
        cur.row_factory = old
