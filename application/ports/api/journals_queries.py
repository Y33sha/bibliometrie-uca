"""Port : lectures sur les revues (consommé par le router journals).

Implémenté par `infrastructure.queries.journals.PgJournalQueries`.
"""

from typing import Any, Protocol


class JournalQueries(Protocol):
    """Opérations de lecture sur les revues."""

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
