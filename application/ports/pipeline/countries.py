"""Port : recalcul des caches dénormalisés de pays.

Implémenté par `infrastructure.queries.countries.PgCountryQueries`.
Utilisé par `application.pipeline.countries.refresh_publication_countries`.
"""

from typing import Protocol

from sqlalchemy import Connection


class CountryQueries(Protocol):
    """Opérations SQL pour recalculer les caches countries (sa, sp, publications)
    à partir de `addresses.countries` (seule source de vérité)."""

    def refresh_sa_countries_for_source(self, conn: Connection, source: str) -> int: ...

    def cleanup_sa_countries_orphans(self, conn: Connection) -> int: ...

    def refresh_address_source_countries(self, conn: Connection) -> int: ...

    def refresh_publication_countries(self, conn: Connection) -> int: ...
