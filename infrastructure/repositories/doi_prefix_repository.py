"""Adapter PostgreSQL pour la table `doi_prefixes`.

Implémente `DoiPrefixRepository`. Sert la phase pipeline
`resolve_doi_prefixes` : lecture des préfixes à résoudre + insertion
des préfixes résolus.
"""

from sqlalchemy import Connection, text

from application.ports.repositories.doi_prefix_repository import UnmatchedCrossrefPrefix


class PgDoiPrefixRepository:
    """Accès PostgreSQL à `doi_prefixes` via une `Connection` SA."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def get_unresolved_prefixes_with_samples(
        self, *, n_samples_per_prefix: int
    ) -> list[tuple[str, list[str]]]:
        """Renvoie `[(prefix, [doi1, doi2, ...]), ...]` pour chaque préfixe
        DOI présent en staging mais absent de `doi_prefixes`. Au plus
        `n_samples_per_prefix` DOIs par préfixe, ordonnés par longueur
        croissante pour minimiser la complexité d'encodage URL côté
        client doi.org/ra."""
        result = self._conn.execute(
            text(
                """
                WITH new_prefixes AS (
                    SELECT DISTINCT split_part(s.doi, '/', 1) AS prefix
                    FROM staging s
                    LEFT JOIN doi_prefixes dp
                        ON dp.prefix = split_part(s.doi, '/', 1)
                    WHERE s.doi IS NOT NULL
                      AND s.doi <> ''
                      AND dp.prefix IS NULL
                ),
                samples AS (
                    SELECT
                        split_part(s.doi, '/', 1) AS prefix,
                        s.doi,
                        ROW_NUMBER() OVER (
                            PARTITION BY split_part(s.doi, '/', 1)
                            ORDER BY length(s.doi), s.doi
                        ) AS rn
                    FROM staging s
                    JOIN new_prefixes np
                        ON np.prefix = split_part(s.doi, '/', 1)
                    WHERE s.doi IS NOT NULL AND s.doi <> ''
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
    ) -> bool:
        """Insère un préfixe résolu. Retourne True si inséré, False si
        déjà présent (conflit sur la PK)."""
        result = self._conn.execute(
            text(
                """
                INSERT INTO doi_prefixes (
                    prefix, ra, publisher_id,
                    publisher_name_raw, publisher_name_normalized,
                    crossref_member_id
                )
                VALUES (
                    :prefix, :ra, :publisher_id,
                    :publisher_name_raw, :publisher_name_normalized,
                    :crossref_member_id
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
            },
        )
        return result.rowcount > 0

    def get_unmatched_crossref_prefixes(self) -> list[UnmatchedCrossrefPrefix]:
        """Rows connues de Crossref mais sans publisher_id, ordre par prefix ASC."""
        result = self._conn.execute(
            text(
                """
                SELECT prefix, publisher_name_raw, publisher_name_normalized,
                       crossref_member_id
                FROM doi_prefixes
                WHERE publisher_id IS NULL
                  AND publisher_name_normalized IS NOT NULL
                ORDER BY prefix
                """
            )
        )
        return [
            UnmatchedCrossrefPrefix(
                prefix=r.prefix,
                publisher_name_raw=r.publisher_name_raw,
                publisher_name_normalized=r.publisher_name_normalized,
                crossref_member_id=r.crossref_member_id,
            )
            for r in result
        ]

    def update_publisher_id(self, prefix: str, publisher_id: int) -> None:
        """Rattache un préfixe existant à un publisher (passe de rattrapage)."""
        self._conn.execute(
            text("UPDATE doi_prefixes SET publisher_id = :pid WHERE prefix = :prefix"),
            {"pid": publisher_id, "prefix": prefix},
        )
