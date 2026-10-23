"""Recalcul du cache `addresses.publication_count`, en fin de phase `contributions`."""

from sqlalchemy import Connection, text


def recompute_address_publication_count(conn: Connection) -> int:
    """Recalcule `addresses.publication_count` sur **toutes** les adresses, depuis les publications du référentiel liées par `source_contribution_addresses`. Retourne le nombre de lignes modifiées.

    Idempotent, et de portée globale : une adresse qui a perdu tous ses liens repasse à 0.
    """
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
