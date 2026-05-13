"""Port : lectures pour /api/hal-problems/*.

Implémenté par `infrastructure.db.queries.hal_problems.PgHalProblemsQueries`.

Placement par cas d'usage (le seul caller est le router de diagnostics
HAL), pas par table.
"""

from typing import Any, Protocol


class HalProblemsQueries(Protocol):
    """Lectures de diagnostic qualité HAL."""

    def hal_duplicate_accounts(self, *, page: int, per_page: int) -> dict[str, Any]: ...

    def hal_duplicate_pubs_by_doi(self, *, page: int, per_page: int) -> dict[str, Any]: ...

    def hal_duplicate_pubs_by_metadata(self, *, page: int, per_page: int) -> dict[str, Any]: ...

    def hal_missing_collections_labs(self) -> list[dict[str, Any]]: ...

    def hal_missing_collections(
        self, *, lab_id: int, page: int, per_page: int
    ) -> dict[str, Any]: ...

    def hal_affiliation_conflicts(self, *, page: int, per_page: int) -> dict[str, Any]: ...
