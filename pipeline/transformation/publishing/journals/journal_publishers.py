"""Éditeur d'une revue, calculé d'après ses publications.

L'éditeur d'une revue est le plus fréquent parmi ses publications de la dernière année qui en a un ; à égalité, le plus fréquent sur toutes les années ; à égalité encore, le plus petit identifiant. Une revue dont aucune publication n'a d'éditeur n'en a pas.
"""

from sqlalchemy import Connection, text

_REFRESH = text("""
    WITH counts AS (
        SELECT journal_id, publisher_id, publication_year, COUNT(*) AS n
        FROM publications
        WHERE journal_id IS NOT NULL AND publisher_id IS NOT NULL
          AND (CAST(:journal_id AS integer) IS NULL OR journal_id = :journal_id)
        GROUP BY journal_id, publisher_id, publication_year
    ),
    latest AS (
        SELECT journal_id, MAX(publication_year) AS year FROM counts GROUP BY journal_id
    ),
    ranked AS (
        SELECT c.journal_id, c.publisher_id,
               SUM(c.n) FILTER (WHERE c.publication_year = l.year) AS latest_n,
               SUM(c.n) AS total_n
        FROM counts c JOIN latest l ON l.journal_id = c.journal_id
        GROUP BY c.journal_id, c.publisher_id
    ),
    chosen AS (
        SELECT DISTINCT ON (journal_id) journal_id, publisher_id
        FROM ranked
        ORDER BY journal_id, latest_n DESC NULLS LAST, total_n DESC, publisher_id
    )
    UPDATE journals j
    SET publisher_id = c.publisher_id
    FROM journals j2
    LEFT JOIN chosen c ON c.journal_id = j2.id
    WHERE j2.id = j.id AND j.publisher_id IS DISTINCT FROM c.publisher_id
      AND (CAST(:journal_id AS integer) IS NULL OR j2.id = :journal_id)
""")


def refresh_journal_publishers(conn: Connection, journal_id: int | None = None) -> int:
    """Recalcule l'éditeur de chaque revue, ou de la seule revue `journal_id`. Rend le nombre de revues dont l'éditeur change."""
    return conn.execute(_REFRESH, {"journal_id": journal_id}).rowcount
