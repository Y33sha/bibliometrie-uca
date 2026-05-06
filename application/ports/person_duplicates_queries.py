"""Port : lectures pour /api/admin/person-duplicates/*.

Implémenté par
`infrastructure.db.queries.person_duplicates.PgAsyncPersonDuplicatesQueries`.
"""

from typing import Any, Protocol


def parse_skip_pairs(skip: str) -> set[tuple[int, int]]:
    """Parse 'idA-idB,idA-idB,...' en set de tuples (helper pur)."""
    result: set[tuple[int, int]] = set()
    if skip:
        for s in skip.split(","):
            parts = s.strip().split("-")
            if len(parts) == 2:
                try:
                    result.add((int(parts[0]), int(parts[1])))
                except ValueError:
                    pass
    return result


class AsyncPersonDuplicatesQueries(Protocol):
    """Lectures async sur les doublons personnes (candidats + conflits co-auteurs)."""

    async def count_person_duplicates(self) -> int: ...

    async def next_person_duplicate(
        self, *, skip_pairs: set[tuple[int, int]] | None, offset: int
    ) -> dict[str, Any] | None: ...

    async def count_person_conflict_pairs(self) -> int: ...

    async def next_person_conflict(
        self, *, skip_pairs: set[tuple[int, int]], offset: int
    ) -> dict[str, Any] | None: ...
