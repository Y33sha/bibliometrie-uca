"""Persistance par lots des corrections de métadonnées, partagée par les sous-étapes.

Chaque sous-étape calcule une liste de mises à jour pures, puis les persiste par lots avec un commit par lot : la progression est durable si le run est interrompu et le journal de transactions reste borné.
"""

from collections.abc import Callable

from sqlalchemy import Connection

PERSIST_BATCH = 5000


def persist_in_batches[U](
    conn: Connection,
    updates: list[U],
    persist: Callable[[Connection, list[U]], int | None],
) -> int:
    """Persiste `updates` par lots de `PERSIST_BATCH`, un commit par lot. Retourne le total remonté par `persist` (0 si `persist` ne compte pas)."""
    total = 0
    for start in range(0, len(updates), PERSIST_BATCH):
        total += persist(conn, updates[start : start + PERSIST_BATCH]) or 0
        conn.commit()
    return total
