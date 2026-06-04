"""Port : lectures pour les scripts d'enrichissement pipeline.

Implémenté par `infrastructure.queries.pipeline.enrich.PgEnrichQueries`. Consommé
par les phases `oa_status` (Unpaywall) et `publishers_journals`
(sub-step `enrich_journals_from_openalex`).
"""

from typing import Protocol

from sqlalchemy import Connection


class EnrichQueries(Protocol):
    """Opérations SQL pour les scripts d'enrichissement pipeline."""

    def fetch_publications_with_doi(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, str, str | None]]: ...

    def fetch_journals_needing_apc(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, str]]: ...

    def fetch_publishers_needing_enrichment(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, str]]: ...

    def fetch_publishers_needing_publisher_type_from_ror(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, str]]: ...

    def fetch_publishers_needing_country_from_crossref(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, int]]: ...

    def fetch_journals_needing_doaj_fetch(
        self,
        conn: Connection,
        *,
        stale_days: int,
        limit: int | None = None,
    ) -> list[tuple[int, str | None, str | None, str | None]]: ...
