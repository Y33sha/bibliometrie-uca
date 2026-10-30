"""Écriture par lots des corrections de métadonnées, commune aux sous-étapes.

Chaque sous-étape calcule ses mises à jour, puis les écrit avec un commit par lot : un run interrompu garde les lots écrits, et le journal de transactions reste borné.
"""

from collections.abc import Callable

from sqlalchemy import Connection

PERSIST_BATCH = 5000


def persist_in_batches[U](
    conn: Connection,
    updates: list[U],
    persist: Callable[[list[U]], int | None],
) -> int:
    """Écrit les mises à jour par lots de `PERSIST_BATCH`, un commit par lot. Renvoie la somme des comptes de `persist`, où `None` vaut 0."""
    total = 0
    for start in range(0, len(updates), PERSIST_BATCH):
        total += persist(updates[start : start + PERSIST_BATCH]) or 0
        conn.commit()
    return total
