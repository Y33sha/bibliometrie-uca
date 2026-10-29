"""Nombre de publications de chaque adresse (`addresses.publication_count`), recalculé en fin de phase `finalize`."""

from sqlalchemy import Connection, text


def recompute_address_publication_count(conn: Connection) -> int:
    """Recalcule le nombre de publications de chaque adresse, d'après les enregistrements sources de ses contributions sources. Une adresse sans publication repasse à 0. Rend le nombre d'adresses modifiées."""
    return conn.execute(
        text("""
            UPDATE addresses a
            SET publication_count = COALESCE(sub.cnt, 0)
            FROM (
                SELECT a2.id AS address_id, agg.cnt
                FROM addresses a2
                LEFT JOIN (
                    SELECT sca.address_id, COUNT(DISTINCT sr.publication_id) AS cnt
                    FROM source_contribution_addresses sca
                    JOIN source_contributions sc ON sc.id = sca.source_contribution_id
                    JOIN source_records sr ON sr.id = sc.source_record_id
                    WHERE sr.publication_id IS NOT NULL
                    GROUP BY sca.address_id
                ) agg ON agg.address_id = a2.id
            ) sub
            WHERE a.id = sub.address_id
              AND a.publication_count IS DISTINCT FROM COALESCE(sub.cnt, 0)
        """)
    ).rowcount
