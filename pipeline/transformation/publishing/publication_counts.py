"""Compteurs `publication_count` (publications in-perimeter) sur `serials` + `publishers`.

`serials.publication_count` = nombre de publications in-perimeter de la revue.
`publishers.publication_count` = nombre de publications in-perimeter de l'éditeur (`publications.publisher_id`).

Les deux recalculs en masse tournent dans la phase `finalize`, après `in_perimeter`. Les variantes ciblées servent aux fusions de revues et d'éditeurs. Tous sont idempotents (`IS DISTINCT FROM`).
"""

from sqlalchemy import Connection, text


def refresh_serial_publication_count(conn: Connection, serial_id: int) -> None:
    """Recalcule le `publication_count` d'une seule revue (fusion admin)."""
    conn.execute(
        text("""
            UPDATE serials j SET publication_count = COALESCE((
                SELECT COUNT(*) FROM publications p
                WHERE p.serial_id = j.id AND p.in_perimeter
            ), 0)
            WHERE j.id = :jid
        """),
        {"jid": serial_id},
    )


def refresh_publisher_publication_count(conn: Connection, publisher_id: int) -> None:
    """Recalcule le `publication_count` d'un seul éditeur (fusion admin)."""
    conn.execute(
        text("""
            UPDATE publishers p SET publication_count = COALESCE((
                SELECT COUNT(*) FROM publications pu
                WHERE pu.publisher_id = p.id AND pu.in_perimeter
            ), 0)
            WHERE p.id = :pid
        """),
        {"pid": publisher_id},
    )


def refresh_serial_publication_counts(conn: Connection) -> int:
    """Recalcule le `publication_count` de chaque revue.

    Rend le nombre de lignes changées (garde `IS DISTINCT FROM` : les lignes inchangées ne comptent pas).
    """
    return conn.execute(
        text("""
            WITH counts AS (
                SELECT serial_id, COUNT(*) AS n
                FROM publications
                WHERE in_perimeter
                  AND serial_id IS NOT NULL
                GROUP BY serial_id
            )
            UPDATE serials j
            SET publication_count = COALESCE(c.n, 0)
            FROM serials j2
            LEFT JOIN counts c ON c.serial_id = j2.id
            WHERE j2.id = j.id AND j.publication_count IS DISTINCT FROM COALESCE(c.n, 0)
        """)
    ).rowcount


def refresh_publisher_publication_counts(conn: Connection) -> int:
    """Recalcule le `publication_count` de chaque éditeur. Rend le nombre de lignes changées."""
    return conn.execute(
        text("""
            WITH counts AS (
                SELECT publisher_id, COUNT(*) AS n
                FROM publications
                WHERE in_perimeter
                  AND publisher_id IS NOT NULL
                GROUP BY publisher_id
            )
            UPDATE publishers p
            SET publication_count = COALESCE(c.n, 0)
            FROM publishers p2
            LEFT JOIN counts c ON c.publisher_id = p2.id
            WHERE p2.id = p.id AND p.publication_count IS DISTINCT FROM COALESCE(c.n, 0)
        """)
    ).rowcount


class PublicationCountRecompute:
    """Recalcul ciblé du `publication_count` d'un éditeur, exposé à l'API par `pipeline/public.py`."""

    def refresh_publisher_publication_count(self, conn: Connection, publisher_id: int) -> None:
        """Recalcule le `publication_count` de l'éditeur."""
        refresh_publisher_publication_count(conn, publisher_id)
