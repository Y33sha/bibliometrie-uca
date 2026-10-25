"""Éditeur d'une revue, calculé d'après ses publications.

L'éditeur d'une revue est le plus fréquent parmi ses publications de la dernière année qui en a un ; à égalité, le plus fréquent sur toutes les années ; à égalité encore, le plus petit identifiant. Une revue dont aucune publication n'a d'éditeur n'en a pas.
"""

from sqlalchemy import Connection, text

_REFRESH = text("""
    WITH counts AS (
        SELECT serial_id, publisher_id, publication_year, COUNT(*) AS n
        FROM publications
        WHERE serial_id IS NOT NULL AND publisher_id IS NOT NULL
          AND (CAST(:serial_id AS integer) IS NULL OR serial_id = :serial_id)
        GROUP BY serial_id, publisher_id, publication_year
    ),
    latest AS (
        SELECT serial_id, MAX(publication_year) AS year FROM counts GROUP BY serial_id
    ),
    ranked AS (
        SELECT c.serial_id, c.publisher_id,
               SUM(c.n) FILTER (WHERE c.publication_year = l.year) AS latest_n,
               SUM(c.n) AS total_n
        FROM counts c JOIN latest l ON l.serial_id = c.serial_id
        GROUP BY c.serial_id, c.publisher_id
    ),
    chosen AS (
        SELECT DISTINCT ON (serial_id) serial_id, publisher_id
        FROM ranked
        ORDER BY serial_id, latest_n DESC NULLS LAST, total_n DESC, publisher_id
    )
    UPDATE serials j
    SET publisher_id = c.publisher_id
    FROM serials j2
    LEFT JOIN chosen c ON c.serial_id = j2.id
    WHERE j2.id = j.id AND j.publisher_id IS DISTINCT FROM c.publisher_id
      AND (CAST(:serial_id AS integer) IS NULL OR j2.id = :serial_id)
""")


def refresh_serial_publishers(conn: Connection, serial_id: int | None = None) -> int:
    """Recalcule l'éditeur de chaque revue, ou de la seule revue `serial_id`. Rend le nombre de revues dont l'éditeur change."""
    return conn.execute(_REFRESH, {"serial_id": serial_id}).rowcount
