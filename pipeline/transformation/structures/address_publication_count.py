"""Nombre de publications de chaque adresse (`addresses.publication_count`), recalculé en fin de phase `finalize`."""

from sqlalchemy import Connection, text

_COUNTS = "address_publication_counts"


def recompute_address_publication_count(conn: Connection) -> int:
    """Recalcule le nombre de publications de chaque adresse, d'après les enregistrements sources de ses contributions sources. Une adresse sans publication repasse à 0. Renvoie le nombre d'adresses modifiées."""
    # Un `UPDATE` s'exécute sans parallélisme. Le décompte se calcule donc à part, dans une table temporaire.
    conn.execute(
        text(f"""
            CREATE TEMP TABLE {_COUNTS} AS
            SELECT sca.address_id, COUNT(DISTINCT sr.publication_id) AS publication_count
            FROM source_contribution_addresses sca
            JOIN source_contributions sc ON sc.id = sca.source_contribution_id
            JOIN source_records sr ON sr.id = sc.source_record_id
            WHERE sr.publication_id IS NOT NULL
            GROUP BY sca.address_id
        """)
    )
    conn.execute(text(f"ANALYZE {_COUNTS}"))
    updated = conn.execute(
        text(f"""
            UPDATE addresses a
            SET publication_count = COALESCE(c.publication_count, 0)
            FROM addresses a2
            LEFT JOIN {_COUNTS} c ON c.address_id = a2.id
            WHERE a.id = a2.id
              AND a.publication_count IS DISTINCT FROM COALESCE(c.publication_count, 0)
        """)
    ).rowcount
    conn.execute(text(f"DROP TABLE {_COUNTS}"))
    return updated
