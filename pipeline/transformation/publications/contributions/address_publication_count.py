"""Recalcul du cache `addresses.publication_count`, en fin de phase `contributions`."""

from sqlalchemy import Connection, text


class AddressPublicationCountQueries:
    """Recalcul du nombre de publications distinctes rattachées à chaque adresse."""

    def recompute_publication_count(self, conn: Connection) -> int:
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
                        SELECT saa.address_id, COUNT(DISTINCT sd.publication_id) AS cnt
                        FROM source_contribution_addresses saa
                        JOIN source_contributions sa ON sa.id = saa.source_contribution_id
                        JOIN source_records sd ON sd.id = sa.source_record_id
                        WHERE sd.publication_id IS NOT NULL
                        GROUP BY saa.address_id
                    ) agg ON agg.address_id = a2.id
                ) sub
                WHERE a.id = sub.address_id
                  AND a.publication_count IS DISTINCT FROM COALESCE(sub.cnt, 0)
            """)
        ).rowcount
