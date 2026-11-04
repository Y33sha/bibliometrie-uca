"""Nombre de publications du périmètre de chaque revue et de chaque éditeur (`publication_count`).

Le recalcul de toutes les revues et de tous les éditeurs se fait dans la phase `finalize`, après celui du périmètre. Le recalcul d'une seule revue ou d'un seul éditeur sert aux fusions. Tous sont idempotents.
"""

from sqlalchemy import Connection, text


def refresh_serial_publication_counts(conn: Connection, serial_id: int | None = None) -> int:
    """Recalcule le `publication_count` de chaque revue, ou de la seule revue `serial_id`. Renvoie le nombre de lignes changées."""
    return _refresh(conn, "serials", "serial_id", serial_id)


def refresh_publisher_publication_counts(conn: Connection, publisher_id: int | None = None) -> int:
    """Recalcule le `publication_count` de chaque éditeur, ou du seul éditeur `publisher_id`. Renvoie le nombre de lignes changées."""
    return _refresh(conn, "publishers", "publisher_id", publisher_id)


def _refresh(conn: Connection, table: str, column: str, entity_id: int | None) -> int:
    """Recalcule le `publication_count` des lignes de `table`, ou de la seule ligne `entity_id`, d'après la colonne `column` des publications du périmètre."""
    return conn.execute(
        text(f"""
            WITH counts AS (
                SELECT {column} AS id, COUNT(*) AS n
                FROM publications
                WHERE in_perimeter AND {column} IS NOT NULL
                  AND (CAST(:id AS integer) IS NULL OR {column} = :id)
                GROUP BY {column}
            )
            UPDATE {table} t
            SET publication_count = COALESCE(c.n, 0)
            FROM {table} t2
            LEFT JOIN counts c ON c.id = t2.id
            WHERE t2.id = t.id AND t.publication_count IS DISTINCT FROM COALESCE(c.n, 0)
              AND (CAST(:id AS integer) IS NULL OR t2.id = :id)
        """),  # noqa: S608 — table et colonne choisies par le code
        {"id": entity_id},
    ).rowcount


class PublicationCountRecompute:
    """Recalcul ciblé du `publication_count` d'un éditeur, exposé à l'API par `pipeline/public.py`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def refresh_publisher_publication_count(self, publisher_id: int) -> None:
        """Recalcule le `publication_count` de l'éditeur."""
        refresh_publisher_publication_counts(self._conn, publisher_id)
