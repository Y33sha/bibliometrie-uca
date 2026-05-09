"""Port : lectures pour /api/hal-problems/*.

Deux variantes (chantier sync-async-deduplication, option D) :
- `AsyncHalProblemsQueries` : routers FastAPI async.
- `HalProblemsQueries` : routers FastAPI sync.

Implémentés respectivement par `PgAsyncHalProblemsQueries` et
`PgHalProblemsQueries` dans `infrastructure.db.queries.hal_problems`.

`hal_duplicate_accounts` est inclus ici (même si la query touche
`source_persons` plutôt que `source_publications`) parce que le
seul caller est ce router de diagnostics HAL — placement par cas
d'usage plutôt que par table.
"""

from typing import Any, Protocol


class AsyncHalProblemsQueries(Protocol):
    """Lectures de diagnostic qualité HAL (async)."""

    async def hal_duplicate_accounts(self, *, page: int, per_page: int) -> dict[str, Any]: ...

    async def hal_duplicate_pubs_by_doi(self, *, page: int, per_page: int) -> dict[str, Any]: ...

    async def hal_duplicate_pubs_by_metadata(
        self, *, page: int, per_page: int
    ) -> dict[str, Any]: ...

    async def hal_missing_collections_labs(self) -> list[dict[str, Any]]: ...

    async def hal_missing_collections(
        self, *, lab_id: int, page: int, per_page: int
    ) -> dict[str, Any]: ...

    async def hal_affiliation_conflicts(self, *, page: int, per_page: int) -> dict[str, Any]: ...


class HalProblemsQueries(Protocol):
    """Variante sync d'`AsyncHalProblemsQueries`."""

    def hal_duplicate_accounts(self, *, page: int, per_page: int) -> dict[str, Any]: ...

    def hal_duplicate_pubs_by_doi(self, *, page: int, per_page: int) -> dict[str, Any]: ...

    def hal_duplicate_pubs_by_metadata(self, *, page: int, per_page: int) -> dict[str, Any]: ...

    def hal_missing_collections_labs(self) -> list[dict[str, Any]]: ...

    def hal_missing_collections(
        self, *, lab_id: int, page: int, per_page: int
    ) -> dict[str, Any]: ...

    def hal_affiliation_conflicts(self, *, page: int, per_page: int) -> dict[str, Any]: ...
