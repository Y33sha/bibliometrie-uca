"""Compteurs `pub_count` (publications in-perimeter) sur `journals` + `publishers`.

`journals.pub_count` = publications in-perimeter in-scope de la revue.
`publishers.pub_count` = somme des `pub_count` de ses revues.

Le bulk `refresh_pub_counts` tourne dans le pipeline après que `in_perimeter` est
posé (phase `authorships`). Les variantes scopées servent aux fusions admin (on ne
recalcule que les lignes touchées). Tous idempotents (`IS DISTINCT FROM`).
"""

from sqlalchemy import Connection, text


def refresh_pub_counts(conn: Connection) -> tuple[int, int]:
    """Recalcule tous les `pub_count` (journals puis publishers). Retourne les
    nombres de lignes modifiées."""
    n_journals = conn.execute(
        text("""
            WITH counts AS (
                SELECT journal_id, COUNT(*) AS n
                FROM publications
                WHERE in_perimeter
                  AND journal_id IS NOT NULL
                GROUP BY journal_id
            )
            UPDATE journals j
            SET pub_count = COALESCE(c.n, 0)
            FROM journals j2
            LEFT JOIN counts c ON c.journal_id = j2.id
            WHERE j2.id = j.id AND j.pub_count IS DISTINCT FROM COALESCE(c.n, 0)
        """)
    ).rowcount
    n_publishers = _refresh_all_publishers(conn)
    return n_journals, n_publishers


def _refresh_all_publishers(conn: Connection) -> int:
    return conn.execute(
        text("""
            WITH counts AS (
                SELECT publisher_id, SUM(pub_count) AS n
                FROM journals
                WHERE publisher_id IS NOT NULL
                GROUP BY publisher_id
            )
            UPDATE publishers p
            SET pub_count = COALESCE(c.n, 0)
            FROM publishers p2
            LEFT JOIN counts c ON c.publisher_id = p2.id
            WHERE p2.id = p.id AND p.pub_count IS DISTINCT FROM COALESCE(c.n, 0)
        """)
    ).rowcount


def refresh_journal_pub_count(conn: Connection, journal_id: int) -> None:
    """Recalcule le `pub_count` d'une seule revue (fusion admin)."""
    conn.execute(
        text("""
            UPDATE journals j SET pub_count = COALESCE((
                SELECT COUNT(*) FROM publications p
                WHERE p.journal_id = j.id AND p.in_perimeter
            ), 0)
            WHERE j.id = :jid
        """),
        {"jid": journal_id},
    )


def refresh_publisher_pub_count(conn: Connection, publisher_id: int) -> None:
    """Recalcule le `pub_count` d'un seul éditeur (= somme de ses revues)."""
    conn.execute(
        text("""
            UPDATE publishers p SET pub_count = COALESCE((
                SELECT SUM(j.pub_count) FROM journals j WHERE j.publisher_id = p.id
            ), 0)
            WHERE p.id = :pid
        """),
        {"pid": publisher_id},
    )
