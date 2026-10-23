"""Lecture et vidage des files d'attente de recalcul."""

from sqlalchemy import Connection, text

from infrastructure.db.queues import Queue


def queued(conn: Connection, queue: Queue) -> set[int]:
    """Identifiants présents dans `queue`."""
    return set(conn.execute(text(f"SELECT id FROM {queue}")).scalars())


def clear(conn: Connection, queue: Queue) -> None:
    """Vide `queue`."""
    conn.execute(text(f"DELETE FROM {queue}"))


def unmark(conn: Connection, queue: Queue, row_id: int) -> None:
    """Retire `row_id` de `queue`."""
    conn.execute(text(f"DELETE FROM {queue} WHERE id = :id"), {"id": row_id})
