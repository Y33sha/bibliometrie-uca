"""Port : lectures pour /api/admin/person-duplicates/*.

Implémenté par
`infrastructure.queries.person_duplicates.PgPersonDuplicatesQueries`.
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


class PersonDuplicatesQueries(Protocol):
    """Lectures sur les doublons personnes (candidats + conflits co-auteurs)."""

    def count_person_duplicates(self) -> int: ...

    def next_person_duplicate(
        self, *, skip_pairs: set[tuple[int, int]] | None, offset: int
    ) -> dict[str, Any] | None: ...

    def count_person_conflict_pairs(self) -> int: ...

    def next_person_conflict(
        self, *, skip_pairs: set[tuple[int, int]], offset: int
    ) -> dict[str, Any] | None: ...
