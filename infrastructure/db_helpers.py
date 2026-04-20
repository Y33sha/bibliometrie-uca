from typing import Any

"""Helpers pour l'acces aux rows psycopg2, compatibles tuple et RealDictCursor."""


def rows_as_dicts(cur: Any) -> list[dict[str, Any]]:
    """`cur.fetchall()` mais garantit des dicts.

    Supporte les curseurs tuple (remappés via `cur.description`) et les
    RealDictCursor (déjà dict-like, juste copiés en dict standard).
    """
    rows = cur.fetchall()
    if not rows:
        return []
    if isinstance(rows[0], dict):
        return [dict(r) for r in rows]
    columns = [desc[0] for desc in cur.description]
    return [dict(zip(columns, r, strict=True)) for r in rows]


def row_val(row: Any, index_or_key: Any, default: Any = None) -> Any:
    """Extrait une valeur d'une row psycopg2, quel que soit le type de curseur.

    Supporte les tuples (accès par index) et les RealDictRow (accès par clé).
    Avec un index entier, tente d'abord l'accès par position, puis par
    position dans les valeurs du dict si c'est un RealDictRow.
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
