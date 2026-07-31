"""Recompute du cache `addresses.pub_count`, en fin de phase publications."""

from sqlalchemy import Connection, text

from application.ports.pipeline.publications.address_pub_count import AddressPubCountQueries


class PgAddressPubCountQueries(AddressPubCountQueries):
    """Adapter PostgreSQL pour le port `AddressPubCountQueries`."""

    def recompute_pub_count(self, conn: Connection) -> int:
        return conn.execute(
            text("""
                UPDATE addresses a
                SET pub_count = COALESCE(sub.cnt, 0)
                FROM (
                    SELECT a2.id AS address_id, agg.cnt
                    FROM addresses a2
                    LEFT JOIN (
                        SELECT saa.address_id, COUNT(DISTINCT sd.publication_id) AS cnt
                        FROM source_authorship_addresses saa
                        JOIN source_authorships sa ON sa.id = saa.source_authorship_id
                        JOIN source_publications sd ON sd.id = sa.source_publication_id
                        WHERE sd.publication_id IS NOT NULL
                        GROUP BY saa.address_id
                    ) agg ON agg.address_id = a2.id
                ) sub
                WHERE a.id = sub.address_id
                  AND a.pub_count IS DISTINCT FROM COALESCE(sub.cnt, 0)
            """)
        ).rowcount
