from typing import Any

"""Helpers pour l'acces aux rows psycopg2, compatibles tuple et RealDictCursor."""


def mark_staging_done(cur: Any, staging_id: int) -> Any:
    """Marque un document staging comme traite et vide le raw_data."""
    cur.execute(
        "UPDATE staging SET processed = TRUE, raw_data = '{}'::jsonb WHERE id = %s", (staging_id,)
    )


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
