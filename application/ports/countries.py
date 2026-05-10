"""Port : recalcul des pays des publications.

Implémenté par `infrastructure.db.queries.countries.PgCountryQueries`.
Utilisé par `application.pipeline.countries.refresh_publication_countries`.
"""

from typing import Any, Protocol


class CountryQueries(Protocol):
    """Opérations SQL pour recalculer `publications.countries` depuis les sources."""

    def refresh_hal_source_countries(self, conn: Any) -> int: ...

    def refresh_address_source_countries(self, conn: Any) -> int: ...

    def refresh_publication_countries(self, conn: Any) -> int: ...
