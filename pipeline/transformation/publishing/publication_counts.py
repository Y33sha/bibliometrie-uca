"""Compteurs `publication_count` (publications in-perimeter) sur `journals` + `publishers`.

`journals.publication_count` = nombre de publications in-perimeter de la revue.
`publishers.publication_count` = somme des `publication_count` de ses revues.

Les deux recalculs en masse tournent dans la phase `contributions`, après `in_perimeter`, les éditeurs après les revues dont ils somment le compteur. Les variantes ciblées servent aux fusions de revues et d'éditeurs. Tous sont idempotents (`IS DISTINCT FROM`).
"""

from sqlalchemy import Connection, text


def refresh_journal_publication_count(conn: Connection, journal_id: int) -> None:
    """Recalcule le `publication_count` d'une seule revue (fusion admin)."""
    conn.execute(
        text("""
            UPDATE journals j SET publication_count = COALESCE((
                SELECT COUNT(*) FROM publications p
                WHERE p.journal_id = j.id AND p.in_perimeter
            ), 0)
            WHERE j.id = :jid
        """),
        {"jid": journal_id},
    )


def refresh_publisher_publication_count(conn: Connection, publisher_id: int) -> None:
    """Recalcule le `publication_count` d'un seul éditeur (= somme de ses revues)."""
    conn.execute(
        text("""
            UPDATE publishers p SET publication_count = COALESCE((
                SELECT SUM(j.publication_count) FROM journals j WHERE j.publisher_id = p.id
            ), 0)
            WHERE p.id = :pid
        """),
        {"pid": publisher_id},
    )


def refresh_journal_publication_counts(conn: Connection) -> int:
    """Recalcule le `publication_count` de chaque revue.

    Rend le nombre de lignes changées (garde `IS DISTINCT FROM` : les lignes inchangées ne comptent pas).
    """
    return conn.execute(
        text("""
            WITH counts AS (
                SELECT journal_id, COUNT(*) AS n
                FROM publications
                WHERE in_perimeter
                  AND journal_id IS NOT NULL
                GROUP BY journal_id
            )
            UPDATE journals j
            SET publication_count = COALESCE(c.n, 0)
            FROM journals j2
            LEFT JOIN counts c ON c.journal_id = j2.id
            WHERE j2.id = j.id AND j.publication_count IS DISTINCT FROM COALESCE(c.n, 0)
        """)
    ).rowcount


def refresh_publisher_publication_counts(conn: Connection) -> int:
    """Recalcule le `publication_count` de chaque éditeur, somme de celui de ses revues.

    À appeler après `refresh_journal_publication_counts`, dont il lit le résultat. Rend le nombre de lignes changées.
    """
    return conn.execute(
        text("""
            WITH counts AS (
                SELECT publisher_id, SUM(publication_count) AS n
                FROM journals
                WHERE publisher_id IS NOT NULL
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
        """Recalcule le `publication_count` de l'éditeur, somme de celui de ses revues."""
        refresh_publisher_publication_count(conn, publisher_id)
