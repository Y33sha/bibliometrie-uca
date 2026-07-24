"""Adapter PostgreSQL pour la table `doi_prefixes`.

Sert la phase `resolve_ra` (lecture des préfixes à résoudre, insertion de leur Registration Agency) et le volet publisher de `publishers_journals` (attache de l'éditeur Crossref / repository DataCite).
"""

from sqlalchemy import Connection, text

from application.ports.repositories.doi_prefix_repository import (
    DoiPrefixRepository,
    PendingPublisherPrefix,
)


class PgDoiPrefixRepository(DoiPrefixRepository):
    """Accès PostgreSQL à `doi_prefixes` via une `Connection` SQLAlchemy."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def get_unresolved_prefixes_with_samples(
        self, *, n_samples_per_prefix: int
    ) -> list[tuple[str, list[str]]]:
        """Les DOI proviennent de la vue `candidate_dois` — le même pool que le cross-import par DOI (DOI primaires des source_publications in-périmètre, related_dois, cibles de relations, arXiv-dérivés), pour que tout préfixe interrogé par cross-import soit résolu ici."""
        result = self._conn.execute(
            text(
                """
                WITH all_dois AS (
                    SELECT doi FROM candidate_dois WHERE doi <> ''
                ),
                new_prefixes AS (
                    SELECT DISTINCT split_part(ad.doi, '/', 1) AS prefix
                    FROM all_dois ad
                    LEFT JOIN doi_prefixes dp
                        ON dp.prefix = split_part(ad.doi, '/', 1)
                    WHERE dp.prefix IS NULL
                ),
                samples AS (
                    SELECT
                        split_part(ad.doi, '/', 1) AS prefix,
                        ad.doi,
                        ROW_NUMBER() OVER (
                            PARTITION BY split_part(ad.doi, '/', 1)
                            ORDER BY length(ad.doi), ad.doi
                        ) AS rn
                    FROM all_dois ad
                    JOIN new_prefixes np
                        ON np.prefix = split_part(ad.doi, '/', 1)
                )
                SELECT prefix, array_agg(doi ORDER BY rn) AS dois
                FROM samples
                WHERE rn <= :n_samples
                GROUP BY prefix
                ORDER BY prefix
                """
            ),
            {"n_samples": n_samples_per_prefix},
        )
        return [(row.prefix, list(row.dois)) for row in result]

    def insert_ra(self, *, prefix: str, ra: str) -> bool:
        result = self._conn.execute(
            text(
                "INSERT INTO doi_prefixes (prefix, ra) VALUES (:prefix, :ra) "
                "ON CONFLICT (prefix) DO NOTHING"
            ),
            {"prefix": prefix, "ra": ra},
        )
        return result.rowcount > 0

    def breakdown_by_registration_agency(self) -> list[tuple[str, int, int]]:
        result = self._conn.execute(
            text(
                """
                SELECT COALESCE(dp.ra, 'unknown') AS ra,
                       count(DISTINCT c.doi) AS dois,
                       count(DISTINCT split_part(c.doi, '/', 1)) AS prefixes
                FROM candidate_dois c
                LEFT JOIN doi_prefixes dp ON dp.prefix = split_part(c.doi, '/', 1)
                WHERE c.doi <> ''
                GROUP BY COALESCE(dp.ra, 'unknown')
                ORDER BY count(DISTINCT c.doi) DESC
                """
            )
        )
        return [(row.ra, int(row.dois), int(row.prefixes)) for row in result]

    def get_prefixes_pending_publisher(self) -> list[PendingPublisherPrefix]:
        result = self._conn.execute(
            text(
                """
                SELECT prefix, ra, publisher_name_raw, publisher_name_normalized
                FROM doi_prefixes
                WHERE publisher_id IS NULL
                  AND publisher_checked_at IS NULL
                  AND ra IN ('Crossref', 'DataCite', 'unknown')
                ORDER BY prefix
                """
            )
        )
        return [
            PendingPublisherPrefix(
                prefix=r.prefix,
                ra=r.ra,
                publisher_name_raw=r.publisher_name_raw,
                publisher_name_normalized=r.publisher_name_normalized,
            )
            for r in result
        ]

    def set_prefix_publisher_metadata(
        self,
        *,
        prefix: str,
        ra: str,
        publisher_name_raw: str | None,
        publisher_name_normalized: str | None,
        crossref_member_id: int | None,
        client_name_raw: str | None,
        client_name_normalized: str | None,
        datacite_client_symbol: str | None,
    ) -> None:
        self._conn.execute(
            text(
                """
                UPDATE doi_prefixes SET
                    ra = :ra,
                    publisher_name_raw = :publisher_name_raw,
                    publisher_name_normalized = :publisher_name_normalized,
                    crossref_member_id = :crossref_member_id,
                    client_name_raw = :client_name_raw,
                    client_name_normalized = :client_name_normalized,
                    datacite_client_symbol = :datacite_client_symbol
                WHERE prefix = :prefix
                """
            ),
            {
                "prefix": prefix,
                "ra": ra,
                "publisher_name_raw": publisher_name_raw,
                "publisher_name_normalized": publisher_name_normalized,
                "crossref_member_id": crossref_member_id,
                "client_name_raw": client_name_raw,
                "client_name_normalized": client_name_normalized,
                "datacite_client_symbol": datacite_client_symbol,
            },
        )

    def update_publisher_id(self, prefix: str, publisher_id: int) -> None:
        self._conn.execute(
            text("UPDATE doi_prefixes SET publisher_id = :pid WHERE prefix = :prefix"),
            {"pid": publisher_id, "prefix": prefix},
        )

    def mark_publisher_checked(self, prefix: str) -> None:
        self._conn.execute(
            text("UPDATE doi_prefixes SET publisher_checked_at = now() WHERE prefix = :prefix"),
            {"prefix": prefix},
        )
