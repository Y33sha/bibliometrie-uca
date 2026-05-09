"""Port : lectures sur les revues (consommé par le router journals).

Deux variantes (chantier sync-async-deduplication, option D) :
- `AsyncJournalQueries` : routers async.
- `JournalQueries` : routers sync.

Implémentés respectivement par `PgAsyncJournalQueries` et
`PgJournalQueries` dans `infrastructure.db.queries.journals`.
"""

from typing import Any, Protocol


class AsyncJournalQueries(Protocol):
    """Opérations de lecture async sur les revues."""

    async def list_journals(
        self,
        *,
        search: str | None,
        publisher_id: int | None,
        sort: str,
        page: int,
        per_page: int,
    ) -> dict[str, Any]: ...

    async def get_journal(self, journal_id: int) -> dict[str, Any] | None: ...

    async def existing_journal_ids(self, journal_ids: tuple[int, ...]) -> set[int]: ...


class JournalQueries(Protocol):
    """Variante sync d'`AsyncJournalQueries`."""

    def list_journals(
        self,
        *,
        search: str | None,
        publisher_id: int | None,
        sort: str,
        page: int,
        per_page: int,
    ) -> dict[str, Any]: ...

    def get_journal(self, journal_id: int) -> dict[str, Any] | None: ...

    def existing_journal_ids(self, journal_ids: tuple[int, ...]) -> set[int]: ...
