"""Port : lecture pour l'enrichissement (cosmétique) des éditeurs depuis OpenAlex Publishers.

Implémenté par `infrastructure.queries.publishers_enrichment.PgPublisherEnrichmentQueries`. Consommé par `application.services.publishers.enrichment.from_openalex` et le CLI de maintenance `interfaces/cli/maintenance/enrich_publishers.py`.

L'enrichissement éditeurs est purement cosmétique (affichage), hors du pipeline, lancé à la demande — d'où ce port distinct de `application.ports.pipeline.enrich.EnrichQueries` (pipeline : oa_status, journaux, DOAJ).
"""

from typing import Protocol

from sqlalchemy import Connection


class PublisherEnrichmentQueries(Protocol):
    """Opérations SQL de sélection des éditeurs à enrichir."""

    def fetch_publishers_needing_enrichment(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, str]]:
        """`(id, openalex_id)` des éditeurs avec `openalex_id` et `country` manquant."""
        ...
