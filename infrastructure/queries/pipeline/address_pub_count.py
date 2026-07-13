"""Recompute du cache `addresses.pub_count`, en fin de phase publications."""

from sqlalchemy import Connection, text

from application.ports.pipeline.address_pub_count import AddressPubCountQueries


def recompute_pub_count(conn: Connection) -> int:
    """Recalcule `addresses.pub_count` = nb de publications canoniques distinctes
    liées à l'adresse via `source_authorship_addresses`.

    Recompute global idempotent (guard `IS DISTINCT FROM`) couvrant **toutes**
    les adresses : celles qui ont perdu tous leurs liens repassent à 0. Lancé en
    fin de phase `publications`, une fois les publications créées et fusionnées —
    il n'y a rien à compter au stade `normalize`. Un run `--only publications`
    suffit à tenir le décompte à jour.

    Ne committe pas (le caller orchestre). Retourne le nombre de rows modifiées.
    """
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


class PgAddressPubCountQueries(AddressPubCountQueries):
    """Adapter PostgreSQL pour le port `AddressPubCountQueries`."""

    def recompute_pub_count(self, conn: Connection) -> int:
        return recompute_pub_count(conn)
