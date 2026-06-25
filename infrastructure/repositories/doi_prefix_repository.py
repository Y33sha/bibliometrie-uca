"""Adapter PostgreSQL pour la table `doi_prefixes`.

Implémente `DoiPrefixRepository`. Sert la phase pipeline `resolve_doi_prefixes` : lecture des préfixes à résoudre + insertion des préfixes résolus (Crossref ou DataCite).
"""

from sqlalchemy import Connection, text

from application.ports.repositories.doi_prefix_repository import UnmatchedPrefix


class PgDoiPrefixRepository:
    """Accès PostgreSQL à `doi_prefixes` via une `Connection` SA."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def get_unresolved_prefixes_with_samples(
        self, *, n_samples_per_prefix: int
    ) -> list[tuple[str, list[str]]]:
        """Renvoie `[(prefix, [doi1, doi2, ...]), ...]` pour chaque préfixe DOI absent de `doi_prefixes`. Les DOI proviennent de la vue `candidate_dois` — le même pool que le cross-import par DOI (staging, related_dois, cibles de relations, arXiv-dérivés), pour que tout préfixe interrogé par cross-import soit résolu ici. Au plus `n_samples_per_prefix` DOIs par préfixe, ordonnés par longueur croissante pour minimiser la complexité d'encodage URL côté client doi.org/ra."""
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

    def insert_doi_prefix(
        self,
        *,
        prefix: str,
        ra: str,
        publisher_id: int | None,
        publisher_name_raw: str | None,
        publisher_name_normalized: str | None,
        crossref_member_id: int | None,
        client_name_raw: str | None,
        client_name_normalized: str | None,
        datacite_client_symbol: str | None,
    ) -> bool:
        """Insère un préfixe résolu. Retourne True si inséré, False si déjà présent (conflit sur la PK)."""
        result = self._conn.execute(
            text(
                """
                INSERT INTO doi_prefixes (
                    prefix, ra, publisher_id,
                    publisher_name_raw, publisher_name_normalized,
                    crossref_member_id,
                    client_name_raw, client_name_normalized,
                    datacite_client_symbol
                )
                VALUES (
                    :prefix, :ra, :publisher_id,
                    :publisher_name_raw, :publisher_name_normalized,
                    :crossref_member_id,
                    :client_name_raw, :client_name_normalized,
                    :datacite_client_symbol
                )
                ON CONFLICT (prefix) DO NOTHING
                """
            ),
            {
                "prefix": prefix,
                "ra": ra,
                "publisher_id": publisher_id,
                "publisher_name_raw": publisher_name_raw,
                "publisher_name_normalized": publisher_name_normalized,
                "crossref_member_id": crossref_member_id,
                "client_name_raw": client_name_raw,
                "client_name_normalized": client_name_normalized,
                "datacite_client_symbol": datacite_client_symbol,
            },
        )
        return result.rowcount > 0

    def get_unmatched_prefixes(self) -> list[UnmatchedPrefix]:
        """Rows avec `publisher_name_normalized` rempli mais `publisher_id IS NULL`. Couvre Crossref et DataCite indifféremment. Ordre par prefix ASC."""
        result = self._conn.execute(
            text(
                """
                SELECT prefix, publisher_name_raw, publisher_name_normalized
                FROM doi_prefixes
                WHERE publisher_id IS NULL
                  AND publisher_name_normalized IS NOT NULL
                ORDER BY prefix
                """
            )
        )
        return [
            UnmatchedPrefix(
                prefix=r.prefix,
                publisher_name_raw=r.publisher_name_raw,
                publisher_name_normalized=r.publisher_name_normalized,
            )
            for r in result
        ]

    def update_publisher_id(self, prefix: str, publisher_id: int) -> None:
        """Rattache un préfixe existant à un publisher (passe de rattrapage)."""
        self._conn.execute(
            text("UPDATE doi_prefixes SET publisher_id = :pid WHERE prefix = :prefix"),
            {"pid": publisher_id, "prefix": prefix},
        )
