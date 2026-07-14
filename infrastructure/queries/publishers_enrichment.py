"""Query service : sélection des éditeurs à enrichir depuis OpenAlex Publishers.

Implémente `application.ports.publishers_enrichment.PublisherEnrichmentQueries`. Alimente `application.services.publishers.enrich_country` (lancé par le CLI de maintenance, hors pipeline — l'enrichissement éditeurs est cosmétique).
"""

from sqlalchemy import Connection, text

from application.ports.publishers_enrichment import PublisherEnrichmentQueries


def fetch_publishers_needing_enrichment(
    conn: Connection, *, limit: int | None = None
) -> list[tuple[int, str]]:
    """Liste `(id, openalex_id)` des publishers à enrichir depuis OpenAlex Publishers.

    Filtre les publishers avec un `openalex_id` et un `country` absent. Tri par id
    pour batching stable.
    """
    if limit and limit > 0:
        rows = conn.execute(
            text("""
                SELECT id, openalex_id
                FROM publishers
                WHERE openalex_id IS NOT NULL
                  AND country IS NULL
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
                  AND country IS NULL
                ORDER BY id
            """)
        ).all()
    return [(r.id, r.openalex_id) for r in rows]


class PgPublisherEnrichmentQueries(PublisherEnrichmentQueries):
    """Adapter PostgreSQL pour `PublisherEnrichmentQueries`."""

    def fetch_publishers_needing_enrichment(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, str]]:
        return fetch_publishers_needing_enrichment(conn, limit=limit)
