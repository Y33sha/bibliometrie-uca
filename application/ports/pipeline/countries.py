"""Port : recalcul des caches dénormalisés de pays.

Implémenté par `infrastructure.queries.pipeline.countries.PgCountryQueries`.
Utilisé par `application.pipeline.countries.refresh_publication_countries`.
"""

from typing import Protocol

from sqlalchemy import Connection


class CountryQueries(Protocol):
    """Opérations SQL pour recalculer les caches countries (sa, sp, publications)
    à partir de `addresses.countries` (seule source de vérité)."""

    def refresh_sa_countries(self, conn: Connection) -> int: ...

    def refresh_address_source_countries(self, conn: Connection) -> int: ...

    def refresh_publication_countries(self, conn: Connection) -> int: ...

    def clear_countries_dirty(self, conn: Connection) -> None: ...
