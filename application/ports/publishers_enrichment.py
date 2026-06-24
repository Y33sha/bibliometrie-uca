"""Port : lectures pour l'enrichissement (cosmétique) des éditeurs.

Implémenté par `infrastructure.queries.publishers_enrichment.PgPublisherEnrichmentQueries`.
Consommé par les orchestrateurs `application.publishers_enrichment` et le CLI de
maintenance `interfaces/cli/maintenance/enrich_publishers.py`.

L'enrichissement éditeurs (pays, ROR, type) est purement cosmétique (affichage) —
hors du pipeline, lancé à la demande — d'où ce port distinct de
`application.ports.pipeline.enrich.EnrichQueries` (qui reste pipeline : oa_status,
journaux, DOAJ).
"""

from typing import Protocol

from sqlalchemy import Connection


class PublisherEnrichmentQueries(Protocol):
    """Opérations SQL de sélection des éditeurs à enrichir."""

    def fetch_publishers_needing_enrichment(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, str]]:
        """`(id, openalex_id)` des éditeurs avec `openalex_id` et `country` ou `ror` manquant."""
        ...

    def fetch_publishers_needing_publisher_type_from_ror(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, str]]:
        """`(id, ror)` des éditeurs avec `ror` non-NULL et `publisher_type = 'unknown'`."""
        ...

    def fetch_publishers_needing_country_from_crossref(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, int]]:
        """`(publisher_id, crossref_member_id)` des éditeurs sans `country` mais reliés à un
        membre Crossref via `doi_prefixes` (fallback country après OpenAlex)."""
        ...
