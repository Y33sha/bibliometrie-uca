"""Query service : sélection des éditeurs à enrichir (pays, ROR, type).

Implémente `application.ports.publishers_enrichment.PublisherEnrichmentQueries`.
Alimente les orchestrateurs `application.publishers_enrichment` (lancés par le CLI
de maintenance, hors pipeline — l'enrichissement éditeurs est cosmétique).
"""

from sqlalchemy import Connection, text

from application.ports.publishers_enrichment import PublisherEnrichmentQueries


def fetch_publishers_needing_enrichment(
    conn: Connection, *, limit: int | None = None
) -> list[tuple[int, str]]:
    """Liste `(id, openalex_id)` des publishers à enrichir depuis OpenAlex Publishers.

    Filtre les publishers avec un `openalex_id` et auxquels il manque au moins
    `country` ou `ror`. Tri par id pour batching stable.
    """
    if limit and limit > 0:
        rows = conn.execute(
            text("""
                SELECT id, openalex_id
                FROM publishers
                WHERE openalex_id IS NOT NULL
                  AND (country IS NULL OR ror IS NULL)
                ORDER BY id
                LIMIT :lim
            """),
            {"lim": limit},
        ).all()
    else:
        rows = conn.execute(
            text("""
                SELECT id, openalex_id
                FROM publishers
                WHERE openalex_id IS NOT NULL
                  AND (country IS NULL OR ror IS NULL)
                ORDER BY id
            """)
        ).all()
    return [(r.id, r.openalex_id) for r in rows]


def fetch_publishers_needing_publisher_type_from_ror(
    conn: Connection, *, limit: int | None = None
) -> list[tuple[int, str]]:
    """Liste `(id, ror)` des publishers à typer via leur record ROR.

    Filtre les publishers avec un `ror` non-NULL et un `publisher_type='unknown'`
    (= défaut DB, non encore arbitré manuellement). Préserve les valeurs admin.
    """
    if limit and limit > 0:
        rows = conn.execute(
            text("""
                SELECT id, ror
                FROM publishers
                WHERE ror IS NOT NULL
                  AND publisher_type = 'unknown'
                ORDER BY id
                LIMIT :lim
            """),
            {"lim": limit},
        ).all()
    else:
        rows = conn.execute(
            text("""
                SELECT id, ror
                FROM publishers
                WHERE ror IS NOT NULL
                  AND publisher_type = 'unknown'
                ORDER BY id
            """)
        ).all()
    return [(r.id, r.ror) for r in rows]


def fetch_publishers_needing_country_from_crossref(
    conn: Connection, *, limit: int | None = None
) -> list[tuple[int, int]]:
    """Liste `(publisher_id, crossref_member_id)` pour le fallback country via Crossref Members.

    Filtre les publishers sans country et avec au moins un `doi_prefixes.crossref_member_id`.
    Prend le plus petit member_id par publisher (déterministe ; un publisher a rarement
    plusieurs members Crossref distincts).
    """
    if limit and limit > 0:
        rows = conn.execute(
            text("""
                SELECT
                    p.id AS publisher_id,
                    (SELECT MIN(dp.crossref_member_id)
                     FROM doi_prefixes dp
                     WHERE dp.publisher_id = p.id
                       AND dp.crossref_member_id IS NOT NULL
                    ) AS member_id
                FROM publishers p
                WHERE p.country IS NULL
                  AND EXISTS (
                      SELECT 1 FROM doi_prefixes dp2
                      WHERE dp2.publisher_id = p.id
                        AND dp2.crossref_member_id IS NOT NULL
                  )
                ORDER BY p.id
                LIMIT :lim
            """),
            {"lim": limit},
        ).all()
    else:
        rows = conn.execute(
            text("""
                SELECT
                    p.id AS publisher_id,
                    (SELECT MIN(dp.crossref_member_id)
                     FROM doi_prefixes dp
                     WHERE dp.publisher_id = p.id
                       AND dp.crossref_member_id IS NOT NULL
                    ) AS member_id
                FROM publishers p
                WHERE p.country IS NULL
                  AND EXISTS (
                      SELECT 1 FROM doi_prefixes dp2
                      WHERE dp2.publisher_id = p.id
                        AND dp2.crossref_member_id IS NOT NULL
                  )
                ORDER BY p.id
            """)
        ).all()
    return [(r.publisher_id, r.member_id) for r in rows]


class PgPublisherEnrichmentQueries(PublisherEnrichmentQueries):
    """Adapter PostgreSQL pour `PublisherEnrichmentQueries`."""

    def fetch_publishers_needing_enrichment(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, str]]:
        return fetch_publishers_needing_enrichment(conn, limit=limit)

    def fetch_publishers_needing_publisher_type_from_ror(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, str]]:
        return fetch_publishers_needing_publisher_type_from_ror(conn, limit=limit)

    def fetch_publishers_needing_country_from_crossref(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, int]]:
        return fetch_publishers_needing_country_from_crossref(conn, limit=limit)
